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


# ── Role resolution ──────────────────────────────────────────────────


def _resolve_base_role(role: str, verifiable: set[str] = VERIFIABLE_ROLES) -> str:
    """Resolve an instance ID or compound role name to its base role.

    Handles cases like:
    - "coder-1"            → "coder"
    - "backend-engineer-1" → "backend-engineer"  (not verifiable) → try "coder" via config
    - "qa"                 → "qa"

    The strategy: strip the last segment if it's numeric. If still not in the
    verifiable set, the caller falls through to the skip path.
    """
    if role in verifiable:
        return role
    # Strip numeric suffix: "coder-1" → "coder", "backend-engineer-1" → "backend-engineer"
    parts = role.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return role


# ── Project type detection ────────────────────────────────────────────


def _detect_project_type(project_root: Path) -> dict[str, Any]:
    """Detect the project type from marker files.

    Returns a dict with:
    - ``language``: python | javascript | typescript | go | rust | java | csharp | cpp | ruby | unknown
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

    # C# / .NET (glob for .csproj / .sln files)
    if list(project_root.glob("*.csproj")) or list(project_root.glob("*.sln")):
        info["language"] = "csharp"
        info["build_cmd"] = "dotnet build --no-restore -v q"
        info["test_cmd"] = "dotnet test --no-build -v q"
        return info

    # C++ (CMake)
    if (project_root / "CMakeLists.txt").exists():
        info["language"] = "cpp"
        info["build_cmd"] = "cmake --build build"
        info["test_cmd"] = "ctest --test-dir build"
        return info

    # C++ (Makefile fallback)
    if (project_root / "Makefile").exists():
        info["language"] = "cpp"
        info["build_cmd"] = "make"
        info["test_cmd"] = "make test"
        return info

    # Ruby
    if (project_root / "Gemfile").exists():
        info["language"] = "ruby"
        if (project_root / "Rakefile").exists():
            info["test_cmd"] = "bundle exec rake test"
        else:
            info["test_cmd"] = "bundle exec rspec"
        return info

    return info


def _detect_config_validators(files_changed: list[str]) -> list[str]:
    """Detect validation commands for config files that were changed.

    Returns a list of validation commands to run.
    """
    validators: list[str] = []
    seen: set[str] = set()

    for filepath in files_changed:
        lower = filepath.lower()
        basename = Path(filepath).name.lower()

        # Terraform
        if lower.endswith(".tf") and "terraform" not in seen:
            validators.append("terraform validate")
            seen.add("terraform")

        # Docker — use hadolint for linting (docker build --check doesn't exist)
        if basename.startswith("dockerfile") and "docker" not in seen:
            validators.append("hadolint " + filepath)
            seen.add("docker")

        # Docker Compose
        if ("docker-compose" in basename or "compose" in basename) and basename.endswith(
            (".yaml", ".yml")
        ):
            if "docker-compose" not in seen:
                validators.append("docker compose -f " + filepath + " config --quiet")
                seen.add("docker-compose")

        # YAML (kubernetes, helm, etc.)
        if lower.endswith((".yaml", ".yml")):
            if "k8s" in lower or "kubernetes" in lower or "deploy" in lower:
                if "kubectl" not in seen:
                    validators.append("kubectl apply --dry-run=client -f " + filepath)
                    seen.add("kubectl")

        # Helm charts
        if "chart.yaml" in basename or lower.endswith("/values.yaml"):
            if "helm" not in seen:
                chart_dir = str(Path(filepath).parent)
                validators.append("helm lint " + chart_dir)
                seen.add("helm")

        # CloudFormation
        if lower.endswith(".template") or "cloudformation" in lower:
            if "cfn" not in seen:
                validators.append(
                    "aws cloudformation validate-template --template-body file://" + filepath
                )
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

    # Only match actual source/test files — ignore data files, configs, docs.
    _CODE_EXTENSIONS = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".cs",
        ".rb",
        ".swift",
        ".cpp",
        ".c",
        ".h",
    }

    # Find test files the QA wrote (distinguishing runnable tests from test infra)
    _TEST_FILE_PATTERN = re.compile(r"(test_|_test\.|\.test\.|\.spec\.)", re.IGNORECASE)
    # Test infrastructure files that are valid QA output but not runnable tests
    _TEST_INFRA_PATTERN = re.compile(
        r"(conftest\.py|fixtures\.py|factories\.py|__init__\.py|pytest\.ini|"
        r"setup\.cfg|jest\.config|jest\.setup|vitest\.config|playwright\.config)",
        re.IGNORECASE,
    )

    def _is_code_file(filepath: str) -> bool:
        return Path(filepath).suffix.lower() in _CODE_EXTENSIONS

    runnable_test_files = [
        f for f in files_changed if _is_code_file(f) and _TEST_FILE_PATTERN.search(Path(f).name)
    ]
    infra_files = [f for f in files_changed if _TEST_INFRA_PATTERN.search(Path(f).name)]

    if not runnable_test_files:
        if infra_files:
            # QA wrote conftest/fixtures only — valid output, soft pass
            checks.append(
                {
                    "label": "test_infra_only",
                    "command": "(check)",
                    "passed": True,
                    "exit_code": 0,
                    "stdout": f"QA wrote {len(infra_files)} test infrastructure file(s) "
                    f"({', '.join(Path(f).name for f in infra_files[:3])}). "
                    "No runnable test files to verify.",
                    "stderr": "",
                    "timed_out": False,
                    "error": "",
                }
            )
            return checks
        else:
            # QA wrote files but none are test files — verification failure
            checks.append(
                {
                    "label": "test_files_exist",
                    "command": "(check)",
                    "passed": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"QA agent wrote {len(files_changed)} file(s) but none are test files. "
                    "QA must write test files (test_*.py, *.test.ts, etc.).",
                    "timed_out": False,
                    "error": "no_test_files_produced",
                }
            )
            return checks

    # Run each test file individually for precise feedback
    lang = project_info.get("language", "unknown")
    for test_file in runnable_test_files:
        if lang == "python":
            cmd = f"python -m pytest {test_file} --tb=short -q"
        elif lang in ("typescript", "javascript"):
            cmd = f"npx jest {test_file}"
        elif lang == "go":
            # Go test files need to be run from their package directory
            test_dir = str(Path(test_file).parent)
            cmd = f"go test ./{test_dir}/..."
        elif lang == "rust":
            cmd = "cargo test --lib"
        elif lang == "java":
            cmd = f"mvn test -pl {test_file} -q"
        else:
            cmd = f"python -m pytest {test_file} --tb=short -q"

        checks.append(
            _run_verification_command(runner, cmd, f"run_test:{Path(test_file).name}", timeout=180)
        )

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
            checks.append(
                _run_verification_command(
                    runner,
                    f"python -c \"import yaml; yaml.safe_load(open('{yf}'))\"",
                    f"yaml_syntax:{Path(yf).name}",
                )
            )

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
        f for f in files_changed if re.search(r"(test_|_test\.|\.test\.|\.spec\.)", f.lower())
    ]
    if test_files and project_info.get("test_cmd"):
        for tf in test_files:
            if project_info["language"] == "python":
                checks.append(
                    _run_verification_command(
                        runner,
                        f"python -m pytest {tf} --tb=short -q",
                        f"test:{Path(tf).name}",
                    )
                )

    return checks


# ── Main node ─────────────────────────────────────────────────────────


def _make_skip_result(
    current_instance: str,
    current_role: str,
    reason: str,
    state: TaskState,
    *,
    event_reason: str = "",
) -> dict[str, Any]:
    """Build a skip verification result with history and events."""
    skip_verification: dict[str, Any] = {
        "status": "skipped",
        "passed": True,
        "role": current_role,
        "instance_id": current_instance,
        "reason": reason,
    }
    verification_history = list(state.get("verification_history") or [])
    verification_history.append({"instance_id": current_instance, **skip_verification})
    event: dict[str, Any] = {
        "type": "execution_verification",
        "instance_id": current_instance,
        "role": current_role,
        "status": "skipped",
    }
    if event_reason:
        event["reason"] = event_reason
    return {
        "execution_verification": skip_verification,
        "verification_history": verification_history,
        "events": list(state.get("events") or []) + [event],
    }


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

    current_instance = state.get("current_instance_id") or state.get("current_agent_role") or ""
    agents_cfg = (state.get("team_config") or {}).get("agents") or {}
    agent_config = agents_cfg.get(current_instance) or {}
    current_role = agent_config.get("role", current_instance)

    # Resolve base role — handles "coder-1" → "coder", "backend-engineer-1" → "backend-engineer"
    base_role = _resolve_base_role(current_role)

    # Skip non-verifiable roles
    if base_role not in VERIFIABLE_ROLES:
        return _make_skip_result(
            current_instance,
            current_role,
            f"Role '{current_role}' does not require execution verification",
            state,
        )

    # Get the agent's output
    agent_output = (state.get("agent_outputs") or {}).get(current_instance) or {}
    files_changed = agent_output.get("files_changed") or []

    if not files_changed:
        return _make_skip_result(
            current_instance,
            current_role,
            "No files produced to verify",
            state,
            event_reason="no_files",
        )

    # Validate project root exists before running commands
    project_root_str = state.get("project_root") or "."
    project_root = Path(project_root_str)
    if not project_root.is_dir():
        logger.warning(
            "Project root '%s' does not exist or is not a directory — skipping verification",
            project_root_str,
        )
        return _make_skip_result(
            current_instance,
            current_role,
            f"Project root '{project_root_str}' not found",
            state,
            event_reason="project_root_missing",
        )

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
    except (OSError, FileNotFoundError) as exc:
        # Filesystem issues — non-fatal, report as verification error
        logger.warning(
            "Filesystem error during verification for %s (%s): %s",
            current_instance,
            current_role,
            exc,
        )
        checks = [
            {
                "label": "verification_error",
                "command": "(internal)",
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Filesystem error: {exc}",
                "timed_out": False,
                "error": str(exc),
            }
        ]
    except Exception as exc:
        # Unexpected errors — log at error level but don't crash the pipeline
        logger.error(
            "Unexpected error in execution verification for %s (%s): %s",
            current_instance,
            current_role,
            exc,
            exc_info=True,
        )
        checks = [
            {
                "label": "verification_error",
                "command": "(internal)",
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "timed_out": False,
                "error": str(exc),
            }
        ]

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
    verification_history = list(state.get("verification_history") or [])
    verification_history.append(
        {
            "instance_id": current_instance,
            "role": current_role,
            **verification,
        }
    )

    events = list(state.get("events") or [])
    events.append(
        {
            "type": "execution_verification",
            "instance_id": current_instance,
            "role": current_role,
            "status": verification["status"],
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "passed": bool(verification.get("passed", True)),
            "project_language": project_info.get("language", "unknown"),
        }
    )

    return {
        "execution_verification": verification,
        "verification_history": verification_history,
        "events": events,
    }
