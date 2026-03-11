"""Rigour quality gate — wraps @rigour-labs/cli for deterministic code checks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rigovo.domain.entities.quality import (
    FixItem,
    FixPacket,
    GateResult,
    GateStatus,
    Violation,
    ViolationSeverity,
)
from rigovo.domain.interfaces.quality_gate import GateInput, QualityGate

logger = logging.getLogger(__name__)


@dataclass
class RigourGateConfig:
    """Configuration for a single Rigour gate."""

    gate_id: str
    name: str
    threshold: float = 0.0  # 0 = zero-tolerance
    severity: ViolationSeverity = ViolationSeverity.ERROR
    enabled: bool = True


class RigourQualityGate(QualityGate):
    """
    Runs Rigour CLI checks against the project.

    This wraps `rigour check --json` and maps its output to our
    domain GateResult / Violation / FixPacket models.

    Falls back to built-in AST checks when rigour CLI is not installed.
    """

    @property
    def gate_id(self) -> str:
        return "rigour"

    @property
    def name(self) -> str:
        return "Rigour Quality Gate"

    def __init__(
        self,
        gate_configs: list[RigourGateConfig] | None = None,
        rigour_binary: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._configs = {g.gate_id: g for g in (gate_configs or [])}
        self._binary = rigour_binary or self._find_binary()
        self._timeout = timeout_seconds

    # Cached binary path shared across instances (installed once per process)
    _cached_binary: str | None = None
    _install_attempted: bool = False

    @staticmethod
    def _build_cmd(binary: str, *args: str) -> list[str]:
        """Build a Rigour CLI command, handling npx format correctly.

        When binary is "npx", produces: ["npx", "-y", "@rigour-labs/cli", ...args]
        Otherwise: [binary, ...args]
        """
        if binary == "npx":
            return ["npx", "-y", "@rigour-labs/cli", *args]
        return [binary, *args]

    @classmethod
    def _find_binary(cls, project_root: str | Path | None = None) -> str | None:
        """Locate the rigour CLI binary with multi-strategy resolution.

        Priority:
        1. Cached result from previous call (avoid repeated lookups)
        2. Workspace-local: ``{project_root}/node_modules/.bin/rigour``
        3. ``rigour`` on PATH (user already installed globally)
        4. ``~/.rigovo/bin/rigour`` (our own cached install)
        5. npx @rigour-labs/cli (slow but always works with Node.js)
        """
        if cls._cached_binary:
            return cls._cached_binary

        # 1. Workspace-local install (fastest, no npx overhead)
        if project_root:
            local_bin = Path(project_root) / "node_modules" / ".bin" / "rigour"
            if local_bin.exists() and local_bin.is_file():
                cls._cached_binary = str(local_bin)
                return str(local_bin)

        # 2. Direct binary on PATH
        path = shutil.which("rigour")
        if path:
            cls._cached_binary = path
            return path

        # 3. Our cached install location
        cached = Path.home() / ".rigovo" / "bin" / "rigour"
        if cached.exists() and cached.is_file():
            cls._cached_binary = str(cached)
            return str(cached)

        # 4. npx fallback (slow first time, cached after)
        if shutil.which("npx"):
            cls._cached_binary = "npx"
            return "npx"

        return None

    @classmethod
    async def ensure_binary(
        cls, project_root: str | Path | None = None,
    ) -> str | None:
        """Auto-install Rigour CLI, preferring workspace-local install.

        Strategy:
        1. Check if already available (fast path)
        2. If workspace has package.json → ``npm install --save-dev @rigour-labs/cli``
        3. Else → ``npm install -g @rigour-labs/cli``
        4. After install → run ``rigour init`` if .rigour/ doesn't exist
        5. Fall back to npx cache priming
        6. Graceful degradation to builtin checks

        Called during prefetch so install happens while planner runs.
        """
        # Fast path: already found or already tried
        if cls._cached_binary and cls._cached_binary != "npx":
            return cls._cached_binary
        if cls._install_attempted:
            return cls._cached_binary

        cls._install_attempted = True

        existing = cls._find_binary(project_root)
        if existing and existing != "npx":
            await cls._ensure_rigour_init(existing, project_root)
            return existing

        if not shutil.which("npm"):
            logger.info("Rigour CLI not available (no npm), using builtin checks")
            return None

        loop = asyncio.get_running_loop()

        # Try workspace-local install if package.json exists
        if project_root:
            pkg_json = Path(project_root) / "package.json"
            if pkg_json.exists():
                try:
                    logger.info("Installing Rigour CLI locally in workspace...")
                    result = await loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            ["npm", "install", "--save-dev", "@rigour-labs/cli"],
                            capture_output=True,
                            text=True,
                            timeout=120,
                            cwd=str(project_root),
                        ),
                    )
                    if result.returncode == 0:
                        local_bin = Path(project_root) / "node_modules" / ".bin" / "rigour"
                        if local_bin.exists():
                            cls._cached_binary = str(local_bin)
                            logger.info("Rigour CLI installed locally: %s", local_bin)
                            await cls._ensure_rigour_init(str(local_bin), project_root)
                            return str(local_bin)
                except Exception as e:
                    logger.debug("Workspace-local install failed: %s", e)

        # Try npm global install
        try:
            logger.info("Installing Rigour CLI globally...")
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["npm", "install", "-g", "@rigour-labs/cli"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                ),
            )
            if result.returncode == 0:
                path = shutil.which("rigour")
                if path:
                    cls._cached_binary = path
                    logger.info("Rigour CLI installed globally: %s", path)
                    await cls._ensure_rigour_init(path, project_root)
                    return path
        except Exception as e:
            logger.debug("npm global install failed: %s", e)

        # Try npx cache priming (so first real run is faster)
        if shutil.which("npx"):
            try:
                logger.info("Priming Rigour CLI via npx cache...")
                await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["npx", "-y", "@rigour-labs/cli", "--help"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    ),
                )
                cls._cached_binary = "npx"
                return "npx"
            except Exception as e:
                logger.debug("npx cache priming failed: %s", e)

        logger.info("Rigour CLI not available, will use builtin quality checks")
        return None

    @classmethod
    async def _ensure_rigour_init(
        cls, binary: str, project_root: str | Path | None,
    ) -> None:
        """Run ``rigour init`` if .rigour/ doesn't exist in the workspace."""
        if not project_root:
            return
        rigour_dir = Path(project_root) / ".rigour"
        if rigour_dir.exists():
            return
        try:
            cmd = cls._build_cmd(binary, "init")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(project_root),
                ),
            )
            logger.info("Rigour initialized in workspace: %s", project_root)
        except Exception as e:
            logger.debug("rigour init failed (non-fatal): %s", e)

    async def run_explain(self, project_root: str | Path) -> str | None:
        """Run ``rigour explain`` and return the human-readable output.

        Called after gate failure to provide a plain-English explanation
        of what's wrong and how to fix it. Returns None on failure.
        """
        if not self._binary:
            return None
        cmd = self._build_cmd(self._binary, "explain")
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    cwd=str(project_root),
                ),
            )
            output = result.stdout.strip()
            return output if output else None
        except Exception:
            return None

    async def run_recall(self, project_root: str | Path) -> str | None:
        """Run ``rigour recall`` to load stored project conventions.

        Returns a string of project conventions/memories, or None if
        unavailable. This is injected into agent context so they follow
        established project patterns.
        """
        if not self._binary:
            return None
        cmd = self._build_cmd(self._binary, "recall")
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(project_root),
                ),
            )
            output = result.stdout.strip()
            return output if output else None
        except Exception:
            return None

    async def run(self, gate_input: GateInput) -> GateResult:
        """Run quality gates and return structured results."""
        if self._binary:
            result = await self._run_rigour_cli(gate_input)
            if result is not None:
                return result
            # CLI failed to produce valid output — fall back to builtin checks
            logger.info("Rigour CLI unavailable or failed, falling back to builtin checks")
        return self._run_builtin_checks(gate_input)

    async def _run_rigour_cli(self, gate_input: GateInput) -> GateResult | None:
        """Execute rigour CLI and parse JSON output.

        Returns None if CLI is not available or fails to produce valid output,
        signaling the caller to fall back to builtin checks.
        """
        cmd = self._build_cmd(self._binary, "check", "--json")

        if gate_input.deep:
            cmd.append("--deep")
        if gate_input.pro:
            cmd.append("--pro")

        # Files are positional arguments, not --file flags.
        # Rigour CLI: `rigour check [options] [files...]`
        if gate_input.files_changed:
            cmd.extend(gate_input.files_changed)

        project_root = (
            Path(gate_input.project_root)
            if isinstance(gate_input.project_root, str)
            else gate_input.project_root
        )

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    cwd=str(project_root),
                ),
            )

            # If the CLI produced no valid JSON, it's not installed or broken.
            # Fall back to builtin checks instead of phantom-failing.
            stdout = result.stdout.strip()
            if not stdout:
                logger.warning(
                    "Rigour CLI returned empty output (exit %d, stderr: %s)",
                    result.returncode,
                    (result.stderr or "")[:200],
                )
                return None  # Signal fallback to builtin checks

            try:
                json.loads(stdout)
            except json.JSONDecodeError:
                logger.warning(
                    "Rigour CLI returned non-JSON output (exit %d): %s",
                    result.returncode,
                    stdout[:200],
                )
                return None  # Signal fallback to builtin checks

            return self._parse_rigour_output(stdout, result.returncode)

        except subprocess.TimeoutExpired:
            logger.warning("Rigour check timed out after %ds", self._timeout)
            return GateResult(
                status=GateStatus.FAILED,
                violations=[
                    Violation(
                        gate_id="timeout",
                        message=f"Quality check timed out after {self._timeout}s",
                        severity=ViolationSeverity.WARNING,
                    )
                ],
            )
        except FileNotFoundError:
            # Binary not found (e.g., npx not installed)
            logger.warning("Rigour CLI binary not found: %s", self._binary)
            return None  # Signal fallback
        except Exception as e:
            logger.exception("Rigour check failed: %s", e)
            return None  # Signal fallback rather than phantom failure

    def _parse_rigour_output(self, stdout: str, return_code: int) -> GateResult:
        """Parse rigour CLI JSON output into GateResult."""
        violations: list[Violation] = []
        score = 100.0
        gates_run = 0
        gates_passed = 0

        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            logger.warning("Failed to parse rigour output as JSON")
            return GateResult(
                status=GateStatus.PASSED if return_code == 0 else GateStatus.FAILED,
                score=100.0 if return_code == 0 else 0.0,
                violations=[],
            )

        # Parse legacy gate results shape: {"gates":[...]}
        gates = data.get("gates", [])
        for gate in gates:
            gate_id = gate.get("id", "unknown")
            gate_status = gate.get("status", "unknown")
            gate_score = gate.get("score", 0)

            config = self._configs.get(gate_id)
            if config and not config.enabled:
                continue

            if gate_status == "FAIL":
                severity = config.severity if config else ViolationSeverity.ERROR
                threshold = config.threshold if config else 0.0

                for issue in gate.get("issues", []):
                    violations.append(
                        Violation(
                            gate_id=gate_id,
                            message=issue.get("message", ""),
                            file_path=issue.get("file"),
                            line=issue.get("line"),
                            severity=severity,
                            suggestion=issue.get("fix"),
                        )
                    )

                if gate_score < score:
                    score = gate_score

        # Parse modern/deep shape: {"failures":[...], "summary": {...}}
        failures = data.get("failures", [])
        for failure in failures:
            gate_id = str(failure.get("id", "unknown"))
            config = self._configs.get(gate_id)
            if config and not config.enabled:
                continue

            severity = (
                config.severity if config else self._map_rigour_severity(failure.get("severity"))
            )
            parsed_issues = self._extract_failure_issues(failure)
            if not parsed_issues:
                details = str(failure.get("details") or "")
                title = str(failure.get("title") or "")
                # Guard against phantom failure stubs like "0 violations".
                if re.search(r"\b0\s+violations?\b", f"{title} {details}".lower()):
                    continue
                violations.append(
                    Violation(
                        gate_id=gate_id,
                        message=str(details or title or "Gate failed"),
                        severity=severity,
                        suggestion=str(failure.get("hint") or ""),
                    )
                )
                continue

            hint = str(failure.get("hint") or "")
            for issue in parsed_issues:
                violations.append(
                    Violation(
                        gate_id=gate_id,
                        message=issue["message"],
                        file_path=issue["file_path"],
                        line=issue["line"],
                        severity=severity,
                        suggestion=hint,
                    )
                )

        summary = data.get("summary")
        if isinstance(summary, dict):
            gates_run = len(summary)
            gates_passed = sum(
                1 for status in summary.values() if str(status).upper() in {"PASS", "PASSED"}
            )
        elif gates:
            gates_run = len(gates)
            gates_passed = sum(
                1 for gate in gates if str(gate.get("status", "")).upper() in {"PASS", "PASSED"}
            )

        # Parse overall status
        overall = data.get("status", "PASS" if return_code == 0 else "FAIL")
        if data.get("score") is not None:
            score = data["score"]

        has_blockers = any(v.severity == ViolationSeverity.ERROR for v in violations)
        status = GateStatus.FAILED if has_blockers else GateStatus.PASSED
        if not violations and (overall != "PASS" or return_code != 0):
            # Unknown failure shape: fail closed, except when output explicitly
            # reports zero violations.
            zero_violations_reported = bool(re.search(r"\b0\s+violations?\b", stdout.lower()))
            status = GateStatus.PASSED if zero_violations_reported else GateStatus.FAILED

        fix_packet = None
        if violations:
            fix_packet = FixPacket(
                items=[
                    FixItem(
                        gate_id=v.gate_id,
                        file_path=v.file_path,
                        message=v.message,
                        suggestion=v.suggestion,
                        severity=v.severity,
                        line=v.line,
                    )
                    for v in violations
                ],
                attempt=1,
                max_attempts=1,
            )

        return GateResult(
            status=status,
            score=score,
            violations=violations,
            gates_run=gates_run,
            gates_passed=gates_passed,
        )

    @staticmethod
    def _map_rigour_severity(severity: object) -> ViolationSeverity:
        value = str(severity or "").strip().lower()
        if value in {"critical", "high", "error"}:
            return ViolationSeverity.ERROR
        if value in {"medium", "low", "warning", "warn"}:
            return ViolationSeverity.WARNING
        return ViolationSeverity.INFO

    @staticmethod
    def _normalize_file_path(raw: object) -> str | None:
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        # Some rigour failures format entries as "path/to/file.py (123 lines)".
        return re.sub(r"\s+\(\d+\s+lines\)\s*$", "", text)

    def _extract_failure_issues(self, failure: dict[str, object]) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        gate_id = str(failure.get("id", "unknown"))

        for raw in failure.get("issues", []) if isinstance(failure.get("issues"), list) else []:
            if not isinstance(raw, dict):
                continue
            issues.append(
                {
                    "file_path": self._normalize_file_path(raw.get("file")),
                    "line": raw.get("line") if isinstance(raw.get("line"), int) else None,
                    "message": str(raw.get("message") or failure.get("details") or gate_id),
                }
            )

        if issues:
            return issues

        files = failure.get("files")
        file_paths = (
            [self._normalize_file_path(f) for f in files if self._normalize_file_path(f)]
            if isinstance(files, list)
            else []
        )
        details = str(failure.get("details") or "")

        line_items: list[tuple[int | None, str]] = []
        for raw_line in details.splitlines():
            line = raw_line.strip()
            m = re.match(r"^L(\d+):\s*(.+)$", line)
            if m:
                line_items.append((int(m.group(1)), m.group(2).strip()))

        if line_items:
            target_file = file_paths[0] if len(file_paths) == 1 else None
            for line_no, message in line_items:
                issues.append(
                    {
                        "file_path": target_file,
                        "line": line_no,
                        "message": message,
                    }
                )
            return issues

        if file_paths:
            for file_path in file_paths:
                issues.append(
                    {
                        "file_path": file_path,
                        "line": None,
                        "message": details or str(failure.get("title") or gate_id),
                    }
                )

        return issues

    def _run_builtin_checks(self, gate_input: GateInput) -> GateResult:
        """
        Fallback checks when rigour CLI is not available.

        Performs basic AST-level analysis for critical issues:
        - Hardcoded secrets
        - File size limits
        - Import validation
        """
        violations: list[Violation] = []

        if not gate_input.files_changed:
            return GateResult(
                status=GateStatus.PASSED,
                score=100.0,
                violations=[],
            )

        project_root = (
            Path(gate_input.project_root)
            if isinstance(gate_input.project_root, str)
            else gate_input.project_root
        )

        for file_path in gate_input.files_changed:
            full_path = project_root / file_path
            if not full_path.exists() or not full_path.is_file():
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # Check file size (500 lines default)
            lines = content.splitlines()
            if len(lines) > 500:
                violations.append(
                    Violation(
                        gate_id="file-size",
                        message=f"File has {len(lines)} lines (max 500)",
                        file_path=file_path,
                        severity=ViolationSeverity.WARNING,
                        suggestion="Split into smaller modules",
                    )
                )

            # Check for hardcoded secrets patterns
            secret_patterns = [
                ("API_KEY", "=", "sk-"),
                ("SECRET", "=", "'"),
                ("PASSWORD", "=", "'"),
                ("TOKEN", "=", "'"),
                ("PRIVATE_KEY", "=", "-----BEGIN"),
            ]
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                for name, op, prefix in secret_patterns:
                    if name in stripped.upper() and op in stripped:
                        # Check it's an assignment with a literal
                        after_eq = stripped.split(op, 1)[-1].strip()
                        if after_eq.startswith(("'", '"')) and len(after_eq) > 3:
                            if "os.environ" not in stripped and "getenv" not in stripped:
                                violations.append(
                                    Violation(
                                        gate_id="hardcoded-secrets",
                                        message=f"Possible hardcoded secret: {name}",
                                        file_path=file_path,
                                        line=i,
                                        severity=ViolationSeverity.ERROR,
                                        suggestion="Use environment variables",
                                    )
                                )
                                break

            # Check for function length (Python only)
            if file_path.endswith(".py"):
                self._check_python_function_length(lines, file_path, violations)

        has_errors = any(v.severity == ViolationSeverity.ERROR for v in violations)
        status = GateStatus.FAILED if has_errors else GateStatus.PASSED
        score = max(0.0, 100.0 - (len(violations) * 10))

        fix_packet = None
        if violations:
            fix_packet = FixPacket(
                items=[
                    FixItem(
                        gate_id=v.gate_id,
                        file_path=v.file_path,
                        message=v.message,
                        suggestion=v.suggestion,
                        severity=v.severity,
                        line=v.line,
                    )
                    for v in violations
                ],
                attempt=1,
                max_attempts=1,
            )

        return GateResult(
            status=status,
            score=score,
            violations=violations,
        )

    @staticmethod
    def _check_python_function_length(
        lines: list[str],
        file_path: str,
        violations: list[Violation],
    ) -> None:
        """Check Python function lengths."""
        func_start: int | None = None
        func_name: str = ""
        indent_level: int = 0

        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                # Save previous function if too long
                if func_start is not None:
                    length = i - func_start
                    if length > 50:
                        violations.append(
                            Violation(
                                gate_id="function-length",
                                message=f"Function '{func_name}' is {length} lines (max 50)",
                                file_path=file_path,
                                line=func_start + 1,
                                severity=ViolationSeverity.WARNING,
                                suggestion="Extract helper functions",
                            )
                        )

                func_start = i
                func_name = stripped.split("(")[0].replace("def ", "").replace("async ", "")
                indent_level = len(line) - len(stripped)

        # Check last function
        if func_start is not None:
            length = len(lines) - func_start
            if length > 50:
                violations.append(
                    Violation(
                        gate_id="function-length",
                        message=f"Function '{func_name}' is {length} lines (max 50)",
                        file_path=file_path,
                        line=func_start + 1,
                        severity=ViolationSeverity.WARNING,
                        suggestion="Extract helper functions",
                    )
                )

    @staticmethod
    def _build_fix_instructions(violations: list[Violation]) -> str:
        """Build human/LLM-readable fix instructions."""
        by_file: dict[str, list[Violation]] = {}
        for v in violations:
            key = v.file_path or "<global>"
            by_file.setdefault(key, []).append(v)

        parts: list[str] = ["FIX REQUIRED — Address the following violations:\n"]
        for file_path, file_violations in by_file.items():
            parts.append(f"\n## {file_path}")
            for v in file_violations:
                loc = f" (line {v.line})" if v.line else ""
                parts.append(f"  - [{v.severity.value}] {v.gate_id}{loc}: {v.message}")
                if v.suggestion:
                    parts.append(f"    → {v.suggestion}")

        return "\n".join(parts)
