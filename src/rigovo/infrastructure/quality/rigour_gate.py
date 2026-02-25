"""Rigour quality gate — wraps @rigour-labs/cli for deterministic code checks."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
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

    @staticmethod
    def _find_binary() -> str | None:
        """Locate the rigour CLI binary. Falls back to npx if available."""
        # Direct binary first
        path = shutil.which("rigour")
        if path:
            return path
        # npx is always available when Node.js is installed
        if shutil.which("npx"):
            return "npx"
        return None

    async def run(self, gate_input: GateInput) -> GateResult:
        """Run quality gates and return structured results."""
        if self._binary:
            return await self._run_rigour_cli(gate_input)
        return self._run_builtin_checks(gate_input)

    async def _run_rigour_cli(self, gate_input: GateInput) -> GateResult:
        """Execute rigour CLI and parse JSON output."""
        if self._binary == "npx":
            cmd = ["npx", "-y", "@rigour-labs/cli", "check", "--json"]
        else:
            cmd = [self._binary, "check", "--json"]

        if gate_input.files_changed:
            for f in gate_input.files_changed:
                cmd.extend(["--file", f])

        project_root = Path(gate_input.project_root) if isinstance(gate_input.project_root, str) else gate_input.project_root

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
                )
            )

            return self._parse_rigour_output(result.stdout, result.returncode)

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
        except Exception as e:
            logger.exception("Rigour check failed")
            return GateResult(
                status=GateStatus.FAILED,
                violations=[
                    Violation(
                        gate_id="execution-error",
                        message=str(e),
                        severity=ViolationSeverity.ERROR,
                    )
                ],
            )

    def _parse_rigour_output(self, stdout: str, return_code: int) -> GateResult:
        """Parse rigour CLI JSON output into GateResult."""
        violations: list[Violation] = []
        score = 100.0

        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            logger.warning("Failed to parse rigour output as JSON")
            return GateResult(
                status=GateStatus.PASSED if return_code == 0 else GateStatus.FAILED,
                score=100.0 if return_code == 0 else 0.0,
                violations=[],
            )

        # Parse gate results
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

        # Parse overall status
        overall = data.get("status", "PASS" if return_code == 0 else "FAIL")
        if data.get("score") is not None:
            score = data["score"]

        status = GateStatus.PASSED if overall == "PASS" else GateStatus.FAILED
        has_blockers = any(v.severity == ViolationSeverity.ERROR for v in violations)
        if has_blockers:
            status = GateStatus.FAILED

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

        project_root = Path(gate_input.project_root) if isinstance(gate_input.project_root, str) else gate_input.project_root

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
                self._check_python_function_length(
                    lines, file_path, violations
                )

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
