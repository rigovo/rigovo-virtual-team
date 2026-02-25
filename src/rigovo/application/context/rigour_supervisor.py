"""Rigour supervisor — per-role quality enforcement.

This is where Rigour becomes the DETERMINISTIC BRAIN of the agent system.

Each agent role has different quality expectations:
- Coder: file size, imports, error handling, type hints, magic numbers
- QA: test coverage, assertion quality, no flaky tests
- DevOps: no hardcoded values, health checks, no latest tags
- Security: no secrets in code, input validation

The supervisor runs Rigour gates TAILORED to each role, not just a
generic lint pass. It produces structured fix packets that tell the
agent EXACTLY what to fix and WHERE.

This is what separates "generate and hope" from "generate, verify,
fix, verify again" — the self-correction loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from rigovo.domain.entities.quality import (
    GateResult,
    GateStatus,
    Violation,
    ViolationSeverity,
)

logger = logging.getLogger(__name__)

# --- Gate severity thresholds per role ---
# Which severity levels BLOCK each role (must fix before proceeding)
BLOCKING_SEVERITIES: dict[str, set[str]] = {
    "coder": {"critical", "high", "medium"},
    "qa": {"critical", "high"},
    "devops": {"critical", "high", "medium"},
    "sre": {"critical", "high"},
    # Non-code-producing roles don't get blocked by gates
}

# Maximum retries per role before giving up
MAX_RETRIES_BY_ROLE: dict[str, int] = {
    "coder": 3,
    "qa": 2,
    "devops": 2,
    "sre": 2,
}

DEFAULT_MAX_RETRIES = 3


@dataclass
class FixItem:
    """A single violation that needs fixing."""

    gate_id: str
    file_path: str
    rule: str
    message: str
    severity: str
    suggestion: str = ""
    line_number: int | None = None


@dataclass
class FixPacket:
    """Structured fix instructions for an agent.

    This is NOT a vague "please fix your code" message.
    It's a precise, machine-readable list of violations with
    file paths, line numbers, and specific fix suggestions.
    """

    items: list[FixItem] = field(default_factory=list)
    attempt: int = 1
    max_attempts: int = DEFAULT_MAX_RETRIES
    role: str = ""

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def has_blockers(self) -> bool:
        """Whether any violations are blocking for this role."""
        blocking = BLOCKING_SEVERITIES.get(self.role, {"critical", "high"})
        return any(item.severity in blocking for item in self.items)

    def to_agent_message(self) -> str:
        """Render as a message to inject into the agent's conversation.

        This is what the agent sees when gates fail — structured,
        actionable instructions, not vague feedback.
        """
        parts = [
            f"[FIX REQUIRED — Attempt {self.attempt}/{self.max_attempts}]",
            f"Quality gates found {self.count} violation(s) in your output.\n",
        ]

        for i, item in enumerate(self.items, 1):
            entry = f"{i}. [{item.severity.upper()}] {item.rule}"
            if item.file_path:
                entry += f" in {item.file_path}"
            if item.line_number:
                entry += f":{item.line_number}"
            entry += f"\n   {item.message}"
            if item.suggestion:
                entry += f"\n   Fix: {item.suggestion}"
            parts.append(entry)

        parts.append(
            "\nFix ONLY the listed violations. Do not refactor unrelated code."
        )

        return "\n".join(parts)


class RigourSupervisor:
    """Supervises agent output through Rigour quality gates.

    This is the self-correction engine. After each code-producing
    agent runs, the supervisor:

    1. Runs Rigour gates on the output files
    2. Filters violations by role-appropriate severity
    3. Builds a structured FixPacket
    4. If blockers exist and retries remain → loop back to agent
    5. If no blockers or max retries → proceed to next agent

    The key insight: different roles have different quality bars.
    A coder is blocked by medium+ violations. A devops engineer
    is blocked by high+ violations. QA is blocked by test-specific
    gates.
    """

    def evaluate(
        self,
        gate_results: list[GateResult],
        role: str,
        attempt: int = 1,
    ) -> FixPacket:
        """Evaluate gate results and build a fix packet for the role.

        Args:
            gate_results: Results from all quality gates.
            role: Agent role that produced the code.
            attempt: Current retry attempt number.

        Returns:
            FixPacket with violations filtered to this role's concerns.
        """
        max_attempts = MAX_RETRIES_BY_ROLE.get(role, DEFAULT_MAX_RETRIES)
        packet = FixPacket(attempt=attempt, max_attempts=max_attempts, role=role)

        for result in gate_results:
            if result.status == GateStatus.PASSED:
                continue

            for violation in result.violations:
                item = FixItem(
                    gate_id=violation.gate_id,
                    file_path=violation.file_path or "",
                    rule=violation.category or violation.gate_id,
                    message=violation.message,
                    severity=violation.severity.value,
                    suggestion=violation.suggestion or "",
                    line_number=violation.line,
                )
                packet.items.append(item)

        # Sort by severity (critical first)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        packet.items.sort(key=lambda x: severity_order.get(x.severity, 5))

        return packet

    def should_retry(self, packet: FixPacket) -> bool:
        """Determine if the agent should retry based on the fix packet."""
        if not packet.items:
            return False

        if packet.attempt >= packet.max_attempts:
            logger.warning(
                "Agent %s exhausted retries (%d/%d) with %d violations",
                packet.role, packet.attempt, packet.max_attempts, packet.count,
            )
            return False

        return packet.has_blockers

    def extract_patterns(self, packet: FixPacket) -> list[str]:
        """Extract recurring violation patterns for enrichment.

        When the same rule is violated multiple times, it becomes
        a 'known pitfall' that gets injected into the agent's
        enrichment context for future tasks.
        """
        rule_counts: dict[str, int] = {}
        rule_messages: dict[str, str] = {}

        for item in packet.items:
            rule_counts[item.rule] = rule_counts.get(item.rule, 0) + 1
            if item.rule not in rule_messages:
                rule_messages[item.rule] = item.message

        patterns = []
        for rule, count in rule_counts.items():
            if count >= 2:
                patterns.append(
                    f"Repeated violation: '{rule}' ({count}x). {rule_messages[rule]}"
                )

        return patterns
