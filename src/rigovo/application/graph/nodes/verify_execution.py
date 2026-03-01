"""Execution verification node — runs agent output to verify it actually works.

Phase 4: Per-agent execution verification.

This node sits between ``execute_agent`` and ``quality_check`` in the graph.
Static analysis catches style/security issues; this node catches **runtime** failures:

- **Coder**: build/compile + existing tests must pass
- **QA**: tests they wrote must actually pass
- **DevOps**: infrastructure configs must validate
- **SRE**: reliability configs must validate
- **Others** (planner, reviewer, security, lead): skip — no runtime verification

The verification result is stored in state and incorporated into the quality gate.
If verification fails, the agent gets a fix packet with the actual error output.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.infrastructure.filesystem.command_runner import CommandRunner

logger = logging.getLogger(__name__)

# Roles that require execution verification (code-producing roles).
VERIFIABLE_ROLES = {"coder", "qa", "devops", "sre"}

# Default timeout for verification commands (2 minutes).
VERIFICATION_TIMEOUT = 120

# Max output to capture from verification commands.
MAX_VERIFICATION_OUTPUT = 10_000


# ── Project type detection ────────────────────────────────────────────

def _detect_project_type(project_root: Path) -> dict[str, Any]:
    """Detect the project type from marker files.

    Returns a dict with:
    - ``language``: python | javascript | typescript | go | rust | java | unknown
    - ``build_cmd``: command to build/compile (if applicable)
    - ``test_cmd``: command to run tests
    - ``validate_cmds``: list of validation commands for config files
    """
    info: dict[str, Any] = {
        "language": "unknown",
        "build_cmd": None,
        "test_cmd": None,
        "validate_cmds": [],
    }

    # Python
    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        info["language"] = "python"
        info["test_cmd"] = "python -m pytest --tb=short -q"
        if (project_root / "pyproject.toml").exists():
            info["build_cmd"] = "python -m py_compile"  # Syntax check
        return info

    if (project_root / "requirements.txt").exists():
        info["language"] = "python"
        info["test_cmd"] = "python -m pytest --tb=short -q"
        return info

    # TypeScript / JavaScript
    if (project_root / "tsconfig.json").exists():
        info["language"] = "typescript"
        info["build_cmd"] = "npx tsc --noEmit"
        if (project_root / "package.json").exists():
            info["test_cmd"] = "npm test"
        return info

    if (project_root / "package.json").exists():
        info["language"] = "javascript"
        info["test_cmd"] = "npm test"
        return info

    # Go
    if (project_root / "go.mod").exists():
        info["language"] = "go"
        info["build_cmd"] = "go build ./..."
        info["test_cmd"] = "go test ./..."
        return info

    # Rust
    if (project_root / "Cargo.toml").exists():
        info["language"] = "rust"
        info["build_cmd"] = "cargo check"
        info["test_cmd"] = "cargo test"
        return info

    # Java (Maven)
    if (project_root / "pom.xml").exists():
        info["language"] = "java"
        info["build_cmd"] = "mvn compile -q"
        info["test_cmd"] = "mvn test -q"
        return info

    # Java (Gradle)
    if (project_root / "build.gradle").exists() or (project_root / "build.gradle.kts").exists():
        info["language"] = "java"
        info["build_cmd"] = "gradle compileJava -q"
        info["test_cmd"] = "gradle test -q"
        return info

    return info


def _detect_config_validators(files_changed: list[str]) -> list[str]:
    """Detect validation commands for config files that were changed.

    Returns a list of validation commands to run.
    """
    validators: list[str] = []
    seen = set()

    for filepath in files_changed:
        lower = filepath.lower()

        # Terraform
        if lower.endswith(".tf") and "terraform" not in seen:
            validators.append("terraform validate")
            seen.add("terraform")

        # Docker
        if "dockerfile" in lower.split("/")[-1].lower() and "docker" not in seen:
            # Hadolint for Dockerfile linting (safe, read-only)
            validators.append("docker build --check .")
            seen.add("docker")

        # YAML (kubernetes, helm, etc.)
        if lower.endswith((".yaml", ".yml")):
            base = Path(filepath).name.lower()
            if "k8s" in lower or "kubernetes" in lower or "deploy" in lower:
                if "kubectl" not in seen:
                    validators.append("kubectl apply --dry-run=client -f " + filepath)
                    seen.add("kubectl")

        # CloudFormation
        if lower.endswith(".template") or "cloudformation" in lower:
            if "cfn" not in seen:
                validators.append("aws cloudformation validate-template --template-body file://" + filepath)
                seen.add("cfn")

    return validators


# ── Verification runners ──────────────────────────────────────────────

def _run_verification_command(
    runner: CommandRunner,
    command: str,
    label: str,
    timeout: int = VERIFICATION_TIMEOUT,
) -> dict[str, Any]:
    """Run a single verification command and return structured result."""
    result = runner.run(command, timeout_seconds=timeout)
    exit_code = result.get("exit_code", -1)
    stdout = str(result.get("stdout", ""))[:MAX_VERIFICATION_OUTPUT]
    stderr = str(result.get("stderr", ""))[:MAX_VERIFICATION_OUTPUT]
    timed_out = bool(result.get("timed_out", False))
    error = str(result.get("error", ""))

    passed = exit_code == 0 and not timed_out and not error

    return {
        "label": label,
        "command": command,
        "passed": passed,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "error": error,
    }


def _verify_coder(
    runner: CommandRunner,
    project_info: dict[str, Any],
    files_changed: list[str],
) -> list[dict[str, Any]]:
    """Verify coder output: build + existing tests."""
    checks: list[dict[str, Any]] = []

    # 1. Build/compile check
    build_cmd = project_info.get("build_cmd")
    if build_cmd:
        checks.append(_run_verification_command(runner, build_cmd, "build"))

    # 2. Run existing tests (not the whole suite — just relevant tests)
    test_cmd = project_info.get("test_cmd")
    if test_cmd:
        # Run test command; timeout is generous since test suites can be slow
        checks.append(_run_verification_command(runner, test_cmd, "test", timeout=180))

    return checks


def _verify_qa(
    runner: CommandRunner,
    project_info: dict[str, Any],
    files_changed: list[str],
) -> list[dict[str, Any]]:
    """Verify QA output: the test files they wrote must actually pass."""
    checks: list[dict[str, Any]] = []

    # Find test files the QA wrote
    test_files = [
        f for f in files_changed
        if re.search(r"(test_|_test\.|\.test\.|\.spec\.)", f.lower())
    ]

    if not test_files:
        # QA wrote files but none are test files — that's a verification failure
        checks.append({
            "label": "test_files_exist",
            "command": "(check)",
            "passed": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"QA agent wrote {len(files_changed)} file(s) but none are test files. "
                      "QA must write test files (test_*.py, *.test.ts, etc.).",
            "timed_out": False,
            "error": "no_test_files_produced",
        })
        return checks

    # Run each test file individually for precise feedback
    lang = project_info.get("language", "unknown")
    for test_file in test_files:
        if lang == "python":
            cmd = f"python -m pytest {test_file} --tb=short -q"
        elif lang in ("typescript", "javascript"):
            cmd = f"npx jest {test_file}"
        elif lang == "go":
            # Go test files need to be run from their package directory
            test_dir = str(Path(test_file).parent)
            cmd = f"go test ./{test_dir}/..."
        elif lang == "rust":
            cmd = f"cargo test --lib"
        elif lang == "java":
            cmd = f"mvn test -pl {test_file} -q"
        else:
            cmd = f"python -m pytest {test_file} --tb=short -q"

        checks.append(_run_verification_command(
            runner, cmd, f"run_test:{Path(test_file).name}", timeout=180
        ))

    return checks


def _verify_devops(
    runner: CommandRunner,
    files_changed: list[str],
) -> list[dict[str, Any]]:
    """Verify DevOps output: config validation."""
    checks: list[dict[str, Any]] = []
    validators = _detect_config_validators(files_changed)

    for cmd in validators:
        label = cmd.split()[0]  # e.g., "terraform", "docker", "kubectl"
        checks.append(_run_verification_command(runner, cmd, f"validate:{label}"))

    # If no specific validators found, at least check YAML syntax
    yaml_files = [f for f in files_changed if f.lower().endswith((".yaml", ".yml"))]
    if yaml_files and not validators:
        for yf in yaml_files[:5]:  # Check up to 5 YAML files
            checks.append(_run_verification_command(
                runner, f"python -c \"import yaml; yaml.safe_load(open('{yf}'))\"",
                f"yaml_syntax:{Path(yf).name}",
            ))

    return checks


def _verify_sre(
    runner: CommandRunner,
    files_changed: list[str],
    project_info: dict[str, Any],
) -> list[dict[str, Any]]:
    """Verify SRE output: reliability config validation."""
    checks: list[dict[str, Any]] = []

    # SRE typically writes monitoring configs, alerting rules, etc.
    # Run same config validators as DevOps
    validators = _detect_config_validators(files_changed)
    for cmd in validators:
        label = cmd.split()[0]
        checks.append(_run_verification_command(runner, cmd, f"validate:{label}"))

    # Also run tests if SRE wrote test files
    test_files = [
        f for f in files_changed
        if re.search(r"(test_|_test\.|\.test\.|\.spec\.)", f.lower())
    ]
    if test_files and project_info.get("test_cmd"):
        for tf in test_files:
            if project_info["language"] == "python":
                checks.append(_run_verification_command(
                    runner, f"python -m pytest {tf} --tb=short -q", f"test:{Path(tf).name}",
                ))

    return checks


# ── Main node ─────────────────────────────────────────────────────────

async def verify_execution_node(
    state: TaskState,
) -> dict[str, Any]:
    """
    Verify that the current agent's output actually works at runtime.

    Runs after execute_agent, before quality_check. Produces structured
    verification results that the quality gate incorporates.

    Non-verifiable roles (planner, reviewer, security, lead) are skipped.
    """
    await asyncio.sleep(0)

    current_instance = (
        state.get("current_instance_id", "")
        or state.get("current_agent_role", "")
    )
    agents_cfg = state.get("team_config", {}).get("agents", {})
    agent_config = agents_cfg.get(current_instance, {})
    current_role = agent_config.get("role", current_instance)

    # Strip instance suffix to get base role (e.g. "coder-1" → "coder")
    base_role = current_role
    if base_role not in VERIFIABLE_ROLES:
        # Try stripping numeric suffix
        parts = base_role.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            base_role = parts[0]

    # Skip non-verifiable roles
    if base_role not in VERIFIABLE_ROLES:
        skip_verification = {
            "status": "skipped",
            "role": current_role,
            "instance_id": current_instance,
            "reason": f"Role '{current_role}' does not require execution verification",
        }
        verification_history = list(state.get("verification_history", []))
        verification_history.append({"instance_id": current_instance, **skip_verification})
        return {
            "execution_verification": skip_verification,
            "verification_history": verification_history,
            "events": state.get("events", [])
            + [
                {
                    "type": "execution_verification",
                    "instance_id": current_instance,
                    "role": current_role,
                    "status": "skipped",
                }
            ],
        }

    # Get the agent's output
    agent_output = state.get("agent_outputs", {}).get(current_instance, {})
    files_changed = agent_output.get("files_changed", [])

    if not files_changed:
        # No files to verify — let quality_check handle the no-files case
        skip_verification = {
            "status": "skipped",
            "role": current_role,
            "instance_id": current_instance,
            "reason": "No files produced to verify",
        }
        verification_history = list(state.get("verification_history", []))
        verification_history.append({"instance_id": current_instance, **skip_verification})
        return {
            "execution_verification": skip_verification,
            "verification_history": verification_history,
            "events": state.get("events", [])
            + [
                {
                    "type": "execution_verification",
                    "instance_id": current_instance,
                    "role": current_role,
                    "status": "skipped",
                    "reason": "no_files",
                }
            ],
        }

    # Set up command runner
    project_root = Path(state.get("project_root", "."))
    runner = CommandRunner(project_root)
    project_info = _detect_project_type(project_root)

    # Run role-specific verification
    checks: list[dict[str, Any]] = []
    try:
        if base_role == "coder":
            checks = _verify_coder(runner, project_info, files_changed)
        elif base_role == "qa":
            checks = _verify_qa(runner, project_info, files_changed)
        elif base_role == "devops":
            checks = _verify_devops(runner, files_changed)
        elif base_role == "sre":
            checks = _verify_sre(runner, files_changed, project_info)
    except Exception as exc:
        logger.warning(
            "Execution verification failed for %s (%s): %s",
            current_instance, current_role, exc,
        )
        checks = [{
            "label": "verification_error",
            "command": "(internal)",
            "passed": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "error": str(exc),
        }]

    # Aggregate results
    total_checks = len(checks)
    passed_checks = sum(1 for c in checks if c["passed"])
    all_passed = total_checks > 0 and passed_checks == total_checks

    # If no checks were run (e.g. no build/test commands detected),
    # that's OK — treat as passed (soft verification)
    if total_checks == 0:
        verification = {
            "status": "no_checks",
            "role": current_role,
            "instance_id": current_instance,
            "project_language": project_info.get("language", "unknown"),
            "checks": [],
            "total_checks": 0,
            "passed_checks": 0,
            "passed": True,
            "reason": "No verification commands available for this project type",
        }
    else:
        # Build failure summary for fix packets
        failure_details = []
        for c in checks:
            if not c["passed"]:
                detail = f"[{c['label']}] {c['command']}"
                if c.get("stderr"):
                    detail += f"\n  stderr: {c['stderr'][:500]}"
                if c.get("stdout") and c.get("exit_code", 0) != 0:
                    detail += f"\n  stdout: {c['stdout'][:500]}"
                failure_details.append(detail)

        verification = {
            "status": "passed" if all_passed else "failed",
            "role": current_role,
            "instance_id": current_instance,
            "project_language": project_info.get("language", "unknown"),
            "checks": checks,
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "passed": all_passed,
            "failure_details": failure_details if not all_passed else [],
        }

    # Update verification history
    verification_history = list(state.get("verification_history", []))
    verification_history.append({
        "instance_id": current_instance,
        "role": current_role,
        **verification,
    })

    events = list(state.get("events", []))
    events.append({
        "type": "execution_verification",
        "instance_id": current_instance,
        "role": current_role,
        "status": verification["status"],
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "passed": verification.get("passed", True),
        "project_language": project_info.get("language", "unknown"),
    })

    return {
        "execution_verification": verification,
        "verification_history": verification_history,
        "events": events,
    }
