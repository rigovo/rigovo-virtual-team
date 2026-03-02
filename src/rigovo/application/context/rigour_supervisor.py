"""Rigour supervisor — per-role quality enforcement with persona guardrails.

This is where Rigour becomes the DETERMINISTIC BRAIN of the agent system.

Each agent role has different quality expectations:
- Coder: file size, imports, error handling, type hints, magic numbers
- QA: test coverage, assertion quality, no flaky tests
- DevOps: no hardcoded values, health checks, no latest tags
- Security: no secrets in code, input validation

The supervisor runs Rigour gates TAILORED to each role, not just a
generic lint pass. It produces structured fix packets that tell the
agent EXACTLY what to fix and WHERE.

Phase 7 adds PERSONA GUARDRAILS:
1. Role gate profiles — which gate categories apply per role
2. Persona boundary enforcement — prevent agents from drifting outside scope
3. Output contract validation — check agents produce expected structure
4. Role-aware severity escalation — security violations hit coder harder

This is what separates "generate and hope" from "generate, verify,
fix, verify again" — the self-correction loop.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

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

# Single source of truth: which roles produce code (used by quality_check too)
CODE_PRODUCING_ROLES: set[str] = {"coder", "qa", "devops", "sre"}

# Canonical severity ordering (string-based, matching Rigour CLI output)
SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "error": 1,
    "medium": 2,
    "warning": 2,
    "low": 3,
    "info": 4,
}

# ---------------------------------------------------------------------------
# Phase 7: Per-role gate profiles
# ---------------------------------------------------------------------------
# Which gate categories are RELEVANT to each role. Gates outside a role's
# profile are still run but their violations are downgraded to INFO (advisory).
# This prevents a QA engineer being blocked by "function-length" in test
# helpers, or a DevOps engineer being blocked by "missing-docstrings" in
# Dockerfiles. Security gates are universal — never downgraded.

ROLE_GATE_PROFILES: dict[str, set[str]] = {
    "coder": {"security", "correctness", "complexity", "style", "size"},
    "qa": {"security", "correctness"},  # Test files can be long/repetitive
    "devops": {"security", "correctness", "size"},  # Infra code style is flexible
    "sre": {"security", "correctness"},  # Observability code is often boilerplate
}

# Gate categories that are ALWAYS enforced at full severity, regardless of role
UNIVERSAL_GATE_CATEGORIES: set[str] = {"security"}

# All valid gate categories (used for cross-validation with gates.py)
KNOWN_GATE_CATEGORIES: set[str] = {"security", "correctness", "complexity", "style", "size"}

# ---------------------------------------------------------------------------
# Phase 7: Persona boundary enforcement
# ---------------------------------------------------------------------------
# What each role is EXPECTED to produce (file patterns) and what it must NOT
# produce. This catches agents drifting outside their scope — e.g., a reviewer
# writing code, or a coder creating test files (that's QA's job).


@dataclass
class PersonaBoundary:
    """Defines what a role is allowed and not allowed to produce."""

    allowed_file_patterns: list[str] = field(default_factory=list)
    forbidden_file_patterns: list[str] = field(default_factory=list)
    must_produce_files: bool = True  # If True, zero files = violation
    expected_output_markers: list[str] = field(default_factory=list)


PERSONA_BOUNDARIES: dict[str, PersonaBoundary] = {
    "coder": PersonaBoundary(
        allowed_file_patterns=[
            "src/**",
            "lib/**",
            "app/**",
            "pkg/**",
            "*.py",
            "*.ts",
            "*.js",
            "*.go",
            "*.rs",
        ],
        forbidden_file_patterns=[
            "test*/**",
            "tests/**",
            "*_test.*",
            "*_spec.*",
            "*.test.*",
            "*.spec.*",
        ],
        must_produce_files=True,
        expected_output_markers=[],
    ),
    "qa": PersonaBoundary(
        allowed_file_patterns=[
            "test*/**",
            "tests/**",
            "*_test.*",
            "*_spec.*",
            "*.test.*",
            "*.spec.*",
            "conftest.*",
        ],
        forbidden_file_patterns=[],  # QA can read anything but should write test files
        must_produce_files=True,
        expected_output_markers=[],
    ),
    "devops": PersonaBoundary(
        allowed_file_patterns=[
            "Dockerfile*",
            "docker-compose*",
            ".github/**",
            ".gitlab-ci*",
            "Makefile",
            "*.yml",
            "*.yaml",
            "terraform/**",
            "*.tf",
            "infra/**",
            "deploy/**",
            "ci/**",
            "scripts/**",
        ],
        forbidden_file_patterns=[],
        must_produce_files=True,
        expected_output_markers=[],
    ),
    "sre": PersonaBoundary(
        allowed_file_patterns=[
            "src/**",
            "lib/**",
            "app/**",
            "*.py",
            "*.ts",
            "*.go",
            "runbook*",
            "docs/**",
            "monitoring/**",
            "*.yml",
            "*.yaml",
        ],
        forbidden_file_patterns=[],
        must_produce_files=True,
        expected_output_markers=[],
    ),
    "planner": PersonaBoundary(
        allowed_file_patterns=[],
        forbidden_file_patterns=["**"],  # Planner should NOT write files
        must_produce_files=False,
        expected_output_markers=["Execution Plan", "Acceptance Criteria", "Files Touched"],
    ),
    "reviewer": PersonaBoundary(
        allowed_file_patterns=[],
        forbidden_file_patterns=["**"],  # Reviewer should NOT write files
        must_produce_files=False,
        expected_output_markers=["Verdict", "APPROVED", "CHANGES_REQUESTED", "BLOCKED"],
    ),
    "security": PersonaBoundary(
        allowed_file_patterns=[],
        forbidden_file_patterns=["**"],  # Security should NOT write files
        must_produce_files=False,
        expected_output_markers=["Verdict", "PASS", "FAIL"],
    ),
    "lead": PersonaBoundary(
        allowed_file_patterns=[],
        forbidden_file_patterns=["**"],  # Lead should NOT write files
        must_produce_files=False,
        expected_output_markers=["Verdict", "APPROVED", "CONCERNS"],
    ),
}

# ---------------------------------------------------------------------------
# Phase 7: Role-aware severity escalation
# ---------------------------------------------------------------------------
# Certain gate categories trigger ESCALATED severity for specific roles.
# E.g., security violations in coder output are escalated to critical,
# even if the gate itself reports them as high.

SEVERITY_ESCALATION: dict[str, dict[str, str]] = {
    "coder": {
        "security": "critical",  # Any security issue in production code is critical
    },
    "devops": {
        "security": "critical",  # Secrets in infra code = critical
    },
    "qa": {},  # No escalation for tests
    "sre": {
        "security": "critical",
    },
}

# ---------------------------------------------------------------------------
# Phase 7: Output contract patterns
# ---------------------------------------------------------------------------
# Validate that agent output summaries contain expected structural markers.
# This catches agents that "complete" without actually doing their job.

OUTPUT_CONTRACT_PATTERNS: dict[str, list[str]] = {
    "planner": [
        r"(?i)(execution\s+plan|implementation\s+plan|plan\s*:)",
        r"(?i)(acceptance\s+criteria|done\s+criteria)",
    ],
    "reviewer": [
        r"(?i)(verdict|APPROVED|CHANGES_REQUESTED|BLOCKED)",
    ],
    "security": [
        r"(?i)(verdict|findings|PASS|FAIL)",
    ],
    "lead": [
        r"(?i)(verdict|APPROVED|CONCERNS)",
    ],
}


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

        parts.append("\nFix ONLY the listed violations. Do not refactor unrelated code.")

        return "\n".join(parts)


@dataclass
class PersonaViolation:
    """A persona boundary violation (agent drifted outside its role)."""

    role: str
    violation_type: str  # "forbidden_file", "missing_output_marker", "unexpected_file_write"
    message: str
    severity: str = "high"
    file_path: str = ""


class RigourSupervisor:
    """Supervises agent output through Rigour quality gates + persona guardrails.

    This is the self-correction engine. After each code-producing
    agent runs, the supervisor:

    1. Runs Rigour gates on the output files
    2. Filters violations by role gate profile (Phase 7)
    3. Applies severity escalation per role (Phase 7)
    4. Checks persona boundaries (Phase 7)
    5. Validates output contracts (Phase 7)
    6. Builds a structured FixPacket
    7. If blockers exist and retries remain → loop back to agent
    8. If no blockers or max retries → proceed to next agent
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

        role_profile = ROLE_GATE_PROFILES.get(role, set())
        escalation_map = SEVERITY_ESCALATION.get(role, {})

        for result in gate_results:
            if result.status == GateStatus.PASSED:
                continue

            for violation in result.violations:
                category = violation.category or ""
                severity_value = violation.severity.value

                # Phase 7: Role gate profile filtering
                # If this gate category isn't in the role's profile AND isn't
                # a universal category, downgrade to info (advisory only)
                if (
                    role_profile
                    and category
                    and category not in role_profile
                    and category not in UNIVERSAL_GATE_CATEGORIES
                ):
                    severity_value = "info"

                # Phase 7: Severity escalation for role+category combos
                # Escalation only PROMOTES severity, never demotes
                if category in escalation_map:
                    escalated = escalation_map[category]
                    if SEVERITY_ORDER.get(escalated, 5) < SEVERITY_ORDER.get(severity_value, 5):
                        severity_value = escalated

                item = FixItem(
                    gate_id=violation.gate_id,
                    file_path=violation.file_path or "",
                    rule=violation.category or violation.gate_id,
                    message=violation.message,
                    severity=severity_value,
                    suggestion=violation.suggestion or "",
                    line_number=violation.line,
                )
                packet.items.append(item)

        # Sort by severity (critical first)
        packet.items.sort(key=lambda x: SEVERITY_ORDER.get(x.severity, 5))

        return packet

    def check_persona_boundaries(
        self,
        role: str,
        files_changed: list[str],
        output_summary: str = "",
    ) -> list[PersonaViolation]:
        """Check whether the agent stayed within its persona boundaries.

        Phase 7: This catches agents that drift outside their scope:
        - Coder writing test files (QA's job)
        - Reviewer/Lead/Security writing files (they should only review)
        - Planner not producing expected plan structure

        Args:
            role: Agent role.
            files_changed: Files the agent created/modified.
            output_summary: Agent's text output summary.

        Returns:
            List of persona violations (empty = clean).
        """
        boundary = PERSONA_BOUNDARIES.get(role)
        if not boundary:
            return []

        violations: list[PersonaViolation] = []

        # Check forbidden file patterns
        if boundary.forbidden_file_patterns and files_changed:
            for file_path in files_changed:
                for pattern in boundary.forbidden_file_patterns:
                    if _glob_match(file_path, pattern):
                        violations.append(
                            PersonaViolation(
                                role=role,
                                violation_type="forbidden_file",
                                message=(
                                    f"Agent '{role}' wrote to '{file_path}' which matches "
                                    f"forbidden pattern '{pattern}'. This is outside the "
                                    f"'{role}' role's scope. Do not create or modify "
                                    f"files — only produce text output."
                                )
                                if not boundary.must_produce_files
                                else (
                                    f"Agent '{role}' wrote to '{file_path}' which matches "
                                    f"forbidden pattern '{pattern}'. This file type belongs "
                                    f"to a different role's scope."
                                ),
                                severity="high",
                                file_path=file_path,
                            )
                        )
                        break  # One match per file is enough

        # Check output contract markers (for non-code-producing roles)
        contract_patterns = OUTPUT_CONTRACT_PATTERNS.get(role, [])
        if contract_patterns and output_summary:
            for pattern in contract_patterns:
                if not re.search(pattern, output_summary):
                    violations.append(
                        PersonaViolation(
                            role=role,
                            violation_type="missing_output_marker",
                            message=(
                                f"Agent '{role}' output is missing expected structural "
                                f"marker matching '{pattern}'. Ensure your output includes "
                                f"the required sections for the '{role}' role."
                            ),
                            severity="medium",
                        )
                    )

        return violations

    def should_retry(self, packet: FixPacket) -> bool:
        """Determine if the agent should retry based on the fix packet."""
        if not packet.items:
            return False

        if packet.attempt >= packet.max_attempts:
            logger.warning(
                "Agent %s exhausted retries (%d/%d) with %d violations",
                packet.role,
                packet.attempt,
                packet.max_attempts,
                packet.count,
            )
            return False

        return packet.has_blockers

    def filter_violations_for_role(
        self,
        violations: list[Violation],
        role: str,
    ) -> list[Violation]:
        """Filter and re-severity violations based on role gate profile.

        Phase 7: Returns only violations that are relevant to this role,
        with severity adjusted per the role's profile.

        Rules:
        1. Universal categories (security) pass through, with escalation applied
        2. Categories NOT in the role's profile are downgraded to INFO
        3. Categories IN the role's profile keep original severity
        4. Empty category = no profile filtering, pass through unchanged
        """
        role_profile = ROLE_GATE_PROFILES.get(role, set())
        escalation_map = SEVERITY_ESCALATION.get(role, {})
        filtered: list[Violation] = []

        for v in violations:
            category = v.category or ""

            # Universal categories always pass through at full severity
            if category in UNIVERSAL_GATE_CATEGORIES:
                # Apply escalation if applicable (only promotes, never demotes)
                new_severity = v.severity
                if category in escalation_map:
                    escalated_str = escalation_map[category]
                    # Map escalated string to ViolationSeverity
                    escalated_sev = _str_to_violation_severity(escalated_str)
                    if escalated_sev is not None and SEVERITY_ORDER.get(
                        escalated_str, 5
                    ) < SEVERITY_ORDER.get(v.severity.value, 5):
                        new_severity = escalated_sev
                filtered.append(
                    Violation(
                        gate_id=v.gate_id,
                        message=v.message,
                        severity=new_severity,
                        file_path=v.file_path,
                        line=v.line,
                        column=v.column,
                        category=v.category,
                        suggestion=v.suggestion,
                    )
                )
                continue

            # If role has a gate profile and this category isn't in it, downgrade
            if role_profile and category and category not in role_profile:
                filtered.append(
                    Violation(
                        gate_id=v.gate_id,
                        message=v.message,
                        severity=ViolationSeverity.INFO,
                        file_path=v.file_path,
                        line=v.line,
                        column=v.column,
                        category=v.category,
                        suggestion=v.suggestion,
                    )
                )
                continue

            # Category is in the role's profile — keep at full severity
            filtered.append(v)

        return filtered

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
                patterns.append(f"Repeated violation: '{rule}' ({count}x). {rule_messages[rule]}")

        return patterns


def _str_to_violation_severity(s: str) -> ViolationSeverity | None:
    """Map a string severity to ViolationSeverity enum, or None if unmappable.

    Handles both Rigour CLI names ("critical", "high") and enum names ("error").
    """
    mapping = {
        "critical": ViolationSeverity.ERROR,  # No CRITICAL in enum → map to ERROR
        "high": ViolationSeverity.ERROR,
        "error": ViolationSeverity.ERROR,
        "medium": ViolationSeverity.WARNING,
        "warning": ViolationSeverity.WARNING,
        "low": ViolationSeverity.WARNING,
        "info": ViolationSeverity.INFO,
    }
    return mapping.get(s.lower()) if s else None


def _glob_match(file_path: str, pattern: str) -> bool:
    """Simple glob-style matching for persona boundary checks.

    Supports:
    - '**' → matches any path segment(s)
    - '*' → matches any characters in a single segment
    - Exact match
    """
    # Normalize separators
    file_path = file_path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")

    # Handle the "match everything" wildcard
    if pattern == "**":
        return True

    # Handle prefix patterns like "tests/**" or "src/**" or "test*/**"
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if "*" in prefix:
            # Glob in the prefix: convert to regex (e.g. "test*" → "test[^/]*")
            prefix_regex = prefix.replace(".", r"\.").replace("*", "[^/]*")
            return bool(re.match(f"^{prefix_regex}/", file_path)) or bool(
                re.match(f"^{prefix_regex}$", file_path)
            )
        return file_path.startswith(prefix + "/") or file_path == prefix

    # Handle suffix patterns like "*_test.*" or "*.test.*"
    if "*" in pattern and "/" not in pattern:
        # Convert glob to regex
        regex = pattern.replace(".", r"\.").replace("*", "[^/]*")
        # Match against the filename only
        filename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        return bool(re.match(f"^{regex}$", filename))

    # Handle "test*/**" or ".github/**" patterns with ** in them
    if "**" in pattern:
        prefix_pat, _suffix_pat = pattern.split("**", 1)
        # Convert glob prefix to regex: "test*/" → "test[^/]*/"
        # Note: glob '*' matches zero or more chars
        prefix_regex = prefix_pat.replace(".", r"\.")
        prefix_regex = prefix_regex.replace("*", "[^/]*")
        return bool(re.match(prefix_regex, file_path))

    # Exact match
    return file_path == pattern
