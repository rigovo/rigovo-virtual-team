"""Quality gate results — deterministic code analysis outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field

from rigovo.domain._compat import StrEnum


class GateStatus(StrEnum):
    """Overall gate outcome."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"  # Agent role doesn't produce code


class ViolationSeverity(StrEnum):
    """How serious a violation is."""

    ERROR = "error"  # Must fix — blocks pipeline
    WARNING = "warning"  # Should fix — counted in score
    INFO = "info"  # Informational — no score impact


@dataclass
class Violation:
    """A single quality gate violation."""

    gate_id: str  # e.g., "hallucinated-imports", "file-size"
    message: str
    severity: ViolationSeverity
    file_path: str | None = None
    line: int | None = None
    column: int | None = None
    category: str = ""  # "security", "complexity", "style", "correctness"
    suggestion: str = ""  # Machine-readable fix suggestion


@dataclass
class GateResult:
    """
    Aggregated result from running all quality gates on agent output.

    This is the output of the rigour_check graph node.
    Deterministic: same input always produces same result.
    No LLM opinions — pure AST analysis.
    """

    status: GateStatus
    score: float = 100.0  # 0-100, higher is better
    violations: list[Violation] = field(default_factory=list)
    gates_run: int = 0
    gates_passed: int = 0
    duration_ms: int = 0

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASSED

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ViolationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ViolationSeverity.WARNING)


@dataclass
class FixItem:
    """A single actionable fix instruction for an agent."""

    gate_id: str
    file_path: str
    message: str
    suggestion: str
    severity: ViolationSeverity
    line: int | None = None
    instructions: list[str] = field(default_factory=list)


@dataclass
class FixPacket:
    """
    Fix Packet V2 — structured, machine-readable instructions
    sent back to the Coder agent when gates fail.

    The agent receives this as part of its retry context.
    """

    items: list[FixItem] = field(default_factory=list)
    attempt: int = 1
    max_attempts: int = 3
    explain_text: str = ""

    def to_prompt(self) -> str:
        """Render as a prompt section for the retry agent."""
        lines = [
            f"FIX REQUIRED (attempt {self.attempt}/{self.max_attempts}):",
            f"Total issues: {len(self.items)}",
            "",
        ]
        for i, item in enumerate(self.items, 1):
            loc = f" (line {item.line})" if item.line else ""
            lines.append(f"{i}. [{item.severity.upper()}] {item.gate_id}")
            lines.append(f"   File: {item.file_path}{loc}")
            lines.append(f"   Issue: {item.message}")
            lines.append(f"   Fix: {item.suggestion}")
            lines.append("")

        return "\n".join(lines)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == ViolationSeverity.ERROR for i in self.items)
