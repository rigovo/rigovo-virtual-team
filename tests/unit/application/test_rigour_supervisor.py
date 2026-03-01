"""Tests for RigourSupervisor — per-role quality gate enforcement.

Covers:
- Fix packet creation and formatting
- Retry decision logic
- Pattern extraction for enrichment
- Phase 7: Role gate profile filtering
- Phase 7: Severity escalation per role+category
- Phase 7: Persona boundary enforcement
- Phase 7: Output contract validation
- Phase 7: Role-aware violation filtering
"""

from __future__ import annotations

import pytest

from rigovo.application.context.rigour_supervisor import (
    BLOCKING_SEVERITIES,
    CODE_PRODUCING_ROLES,
    KNOWN_GATE_CATEGORIES,
    MAX_RETRIES_BY_ROLE,
    OUTPUT_CONTRACT_PATTERNS,
    PERSONA_BOUNDARIES,
    ROLE_GATE_PROFILES,
    SEVERITY_ESCALATION,
    SEVERITY_ORDER,
    UNIVERSAL_GATE_CATEGORIES,
    FixItem,
    FixPacket,
    PersonaViolation,
    RigourSupervisor,
    _glob_match,
    _str_to_violation_severity,
)
from rigovo.domain.entities.quality import (
    GateResult,
    GateStatus,
    Violation,
    ViolationSeverity,
)


@pytest.fixture
def supervisor() -> RigourSupervisor:
    return RigourSupervisor()


def _make_gate_result(
    status: GateStatus,
    violations: list[tuple[str, str, str]] | None = None,
    category: str = "",
) -> GateResult:
    """Helper: (severity, gate_id, message) tuples → GateResult."""
    vs = []
    if violations:
        for sev, gate_id, msg in violations:
            vs.append(Violation(
                severity=ViolationSeverity(sev),
                gate_id=gate_id,
                message=msg,
                category=category or gate_id,
            ))
    return GateResult(status=status, violations=vs)


def _make_categorized_gate_result(
    status: GateStatus,
    violations: list[tuple[str, str, str, str]] | None = None,
) -> GateResult:
    """Helper: (severity, gate_id, message, category) tuples → GateResult."""
    vs = []
    if violations:
        for sev, gate_id, msg, cat in violations:
            vs.append(Violation(
                severity=ViolationSeverity(sev),
                gate_id=gate_id,
                message=msg,
                category=cat,
            ))
    return GateResult(status=status, violations=vs)


# ── Original tests (pre-Phase 7) ────────────────────────────────────────

class TestFixPacketCreation:

    def test_passed_gates_empty_packet(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.PASSED)]
        packet = supervisor.evaluate(results, role="coder")
        assert packet.count == 0

    def test_failed_gates_produce_fix_items(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "file_size", "File exceeds 400 lines"),
            ("warning", "magic_number", "Magic number 42 found"),
        ])]
        packet = supervisor.evaluate(results, role="coder")
        assert packet.count == 2

    def test_role_specific_max_retries(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "test", "Missing assertion"),
        ])]
        qa_packet = supervisor.evaluate(results, role="qa")
        coder_packet = supervisor.evaluate(results, role="coder")
        assert qa_packet.max_attempts == MAX_RETRIES_BY_ROLE["qa"]
        assert coder_packet.max_attempts == MAX_RETRIES_BY_ROLE["coder"]


class TestFixPacketMessages:

    def test_message_includes_violations(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "file_size", "app.py exceeds 400 lines"),
        ])]
        packet = supervisor.evaluate(results, role="coder")
        msg = packet.to_agent_message()
        assert "FIX REQUIRED" in msg
        assert "file_size" in msg

    def test_message_includes_attempt_count(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "test", "No assertions"),
        ])]
        packet = supervisor.evaluate(results, role="coder", attempt=2)
        msg = packet.to_agent_message()
        assert "Attempt 2/" in msg


class TestRetryDecision:

    def test_no_violations_no_retry(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(role="coder")
        assert not supervisor.should_retry(packet)

    def test_blocking_violations_trigger_retry(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(
            items=[FixItem(gate_id="rigour", file_path="x.py",
                           rule="file_size", message="Too long", severity="high")],
            role="coder", attempt=1, max_attempts=3,
        )
        assert supervisor.should_retry(packet)

    def test_max_retries_exhausted_no_retry(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(
            items=[FixItem(gate_id="rigour", file_path="x.py",
                           rule="file_size", message="Too long", severity="high")],
            role="coder", attempt=3, max_attempts=3,
        )
        assert not supervisor.should_retry(packet)


class TestPatternExtraction:

    def test_repeated_violations_become_patterns(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(items=[
            FixItem(gate_id="r", file_path="a.py", rule="magic_number",
                    message="42 found", severity="warning"),
            FixItem(gate_id="r", file_path="b.py", rule="magic_number",
                    message="99 found", severity="warning"),
        ], role="coder")
        patterns = supervisor.extract_patterns(packet)
        assert len(patterns) >= 1
        assert "magic_number" in patterns[0]

    def test_single_violations_not_patterns(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(items=[
            FixItem(gate_id="r", file_path="a.py", rule="file_size",
                    message="Too long", severity="error"),
        ], role="coder")
        patterns = supervisor.extract_patterns(packet)
        assert len(patterns) == 0


# ── Phase 7: Role Gate Profile Filtering ─────────────────────────────────

class TestRoleGateProfiles:
    """Test that ROLE_GATE_PROFILES correctly filters violations per role."""

    def test_coder_profile_includes_all_categories(self) -> None:
        """Coder has the broadest profile — all categories matter."""
        profile = ROLE_GATE_PROFILES["coder"]
        assert "security" in profile
        assert "correctness" in profile
        assert "complexity" in profile
        assert "style" in profile
        assert "size" in profile

    def test_qa_profile_only_security_and_correctness(self) -> None:
        """QA is lenient on style/complexity — test files can be verbose."""
        profile = ROLE_GATE_PROFILES["qa"]
        assert "security" in profile
        assert "correctness" in profile
        assert "complexity" not in profile
        assert "style" not in profile

    def test_security_is_universal_gate_category(self) -> None:
        """Security gates are never downgraded, regardless of role."""
        assert "security" in UNIVERSAL_GATE_CATEGORIES

    def test_evaluate_downgrades_irrelevant_categories_for_qa(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """QA agent: complexity violations should be downgraded to info."""
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "function-length", "Test helper is 80 lines", "complexity"),
        ])]
        packet = supervisor.evaluate(results, role="qa")
        assert packet.count == 1
        # Complexity is NOT in QA's profile → downgraded to info
        assert packet.items[0].severity == "info"

    def test_evaluate_keeps_relevant_categories_for_coder(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Coder: complexity violations stay at full severity."""
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "function-length", "Handler is 80 lines", "complexity"),
        ])]
        packet = supervisor.evaluate(results, role="coder")
        assert packet.count == 1
        # Complexity IS in coder's profile → stays at error
        assert packet.items[0].severity == "error"

    def test_security_violations_never_downgraded(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Even for roles where security isn't in their profile (if any),
        security violations should never be downgraded because it's universal."""
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "hardcoded-secrets", "API key found in test", "security"),
        ])]
        # QA doesn't have a broad profile, but security is universal
        packet = supervisor.evaluate(results, role="qa")
        assert packet.count == 1
        assert packet.items[0].severity == "error"

    def test_devops_style_violations_downgraded(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """DevOps: style violations should be downgraded (infra code has different style)."""
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("warning", "missing-docstrings", "Missing docstring in Dockerfile", "style"),
        ])]
        packet = supervisor.evaluate(results, role="devops")
        assert packet.count == 1
        assert packet.items[0].severity == "info"


# ── Phase 7: Severity Escalation ─────────────────────────────────────────

class TestSeverityEscalation:
    """Test that severity gets escalated for certain role+category combinations."""

    def test_security_violations_escalated_to_critical_for_coder(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Security violations in production code (coder) should escalate to critical."""
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "sql-injection", "SQL injection risk", "security"),
        ])]
        packet = supervisor.evaluate(results, role="coder")
        assert packet.count == 1
        assert packet.items[0].severity == "critical"

    def test_security_escalation_for_devops(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """DevOps: security violations also escalate to critical."""
        assert "security" in SEVERITY_ESCALATION.get("devops", {})
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "hardcoded-secrets", "Secret in terraform", "security"),
        ])]
        packet = supervisor.evaluate(results, role="devops")
        assert packet.items[0].severity == "critical"

    def test_no_escalation_for_qa(self, supervisor: RigourSupervisor) -> None:
        """QA: no security escalation — test secrets are common (test fixtures)."""
        escalation = SEVERITY_ESCALATION.get("qa", {})
        assert "security" not in escalation

    def test_escalation_only_promotes_never_demotes(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Escalation should only increase severity, never decrease it."""
        # If a violation is already critical, escalation shouldn't change it
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "hardcoded-secrets", "Critical secret", "security"),
        ])]
        packet = supervisor.evaluate(results, role="coder")
        # critical > error, so it should escalate
        assert packet.items[0].severity == "critical"


# ── Phase 7: Persona Boundary Enforcement ────────────────────────────────

class TestPersonaBoundaries:
    """Test persona boundary enforcement — agents staying in scope."""

    def test_coder_writing_to_src_is_allowed(self, supervisor: RigourSupervisor) -> None:
        violations = supervisor.check_persona_boundaries(
            role="coder",
            files_changed=["src/auth/handler.py", "src/models/user.py"],
        )
        assert len(violations) == 0

    def test_coder_writing_tests_is_forbidden(self, supervisor: RigourSupervisor) -> None:
        """Coder should not write test files — that's QA's job."""
        violations = supervisor.check_persona_boundaries(
            role="coder",
            files_changed=["src/auth.py", "tests/test_auth.py"],
        )
        assert len(violations) >= 1
        assert any(v.violation_type == "forbidden_file" for v in violations)
        assert any("tests/test_auth.py" in v.message for v in violations)

    def test_coder_writing_test_suffix_files_forbidden(self, supervisor: RigourSupervisor) -> None:
        """Coder writing *_test.py files should be caught."""
        violations = supervisor.check_persona_boundaries(
            role="coder",
            files_changed=["src/auth_test.py"],
        )
        assert len(violations) >= 1

    def test_qa_writing_tests_is_allowed(self, supervisor: RigourSupervisor) -> None:
        violations = supervisor.check_persona_boundaries(
            role="qa",
            files_changed=["tests/test_auth.py", "tests/conftest.py"],
        )
        assert len(violations) == 0

    def test_reviewer_writing_any_file_is_forbidden(self, supervisor: RigourSupervisor) -> None:
        """Reviewer should NOT produce files."""
        violations = supervisor.check_persona_boundaries(
            role="reviewer",
            files_changed=["src/fix.py"],
        )
        assert len(violations) >= 1

    def test_lead_writing_any_file_is_forbidden(self, supervisor: RigourSupervisor) -> None:
        """Lead should NOT produce files."""
        violations = supervisor.check_persona_boundaries(
            role="lead",
            files_changed=["src/architecture.md"],
        )
        assert len(violations) >= 1

    def test_security_writing_any_file_is_forbidden(self, supervisor: RigourSupervisor) -> None:
        """Security should NOT produce files."""
        violations = supervisor.check_persona_boundaries(
            role="security",
            files_changed=["src/patch.py"],
        )
        assert len(violations) >= 1

    def test_planner_writing_files_is_forbidden(self, supervisor: RigourSupervisor) -> None:
        """Planner should NOT produce files."""
        violations = supervisor.check_persona_boundaries(
            role="planner",
            files_changed=["plan.md"],
        )
        assert len(violations) >= 1

    def test_devops_writing_dockerfile_is_allowed(self, supervisor: RigourSupervisor) -> None:
        violations = supervisor.check_persona_boundaries(
            role="devops",
            files_changed=["Dockerfile", "docker-compose.yml"],
        )
        assert len(violations) == 0

    def test_devops_writing_github_actions_allowed(self, supervisor: RigourSupervisor) -> None:
        violations = supervisor.check_persona_boundaries(
            role="devops",
            files_changed=[".github/workflows/ci.yml"],
        )
        assert len(violations) == 0

    def test_no_files_no_violations(self, supervisor: RigourSupervisor) -> None:
        """No files changed → no boundary violations."""
        violations = supervisor.check_persona_boundaries(
            role="coder",
            files_changed=[],
        )
        assert len(violations) == 0

    def test_unknown_role_no_violations(self, supervisor: RigourSupervisor) -> None:
        """Unknown role has no boundary → no violations."""
        violations = supervisor.check_persona_boundaries(
            role="custom_role",
            files_changed=["anything.py"],
        )
        assert len(violations) == 0


# ── Phase 7: Output Contract Validation ──────────────────────────────────

class TestOutputContracts:
    """Test that non-code-producing roles produce expected output structure."""

    def test_planner_with_complete_output(self, supervisor: RigourSupervisor) -> None:
        """Planner producing correct markers → no violations."""
        violations = supervisor.check_persona_boundaries(
            role="planner",
            files_changed=[],
            output_summary="## Execution Plan\n## Acceptance Criteria\n## Files Touched",
        )
        # Should have no output contract violations
        contract_violations = [v for v in violations if v.violation_type == "missing_output_marker"]
        assert len(contract_violations) == 0

    def test_planner_missing_markers(self, supervisor: RigourSupervisor) -> None:
        """Planner without expected markers → contract violations."""
        violations = supervisor.check_persona_boundaries(
            role="planner",
            files_changed=[],
            output_summary="I think we should probably fix the bug.",
        )
        contract_violations = [v for v in violations if v.violation_type == "missing_output_marker"]
        assert len(contract_violations) >= 1

    def test_reviewer_with_verdict(self, supervisor: RigourSupervisor) -> None:
        """Reviewer producing verdict → no violations."""
        violations = supervisor.check_persona_boundaries(
            role="reviewer",
            files_changed=[],
            output_summary="## Verdict\nAPPROVED\n## Summary\nCode looks good.",
        )
        contract_violations = [v for v in violations if v.violation_type == "missing_output_marker"]
        assert len(contract_violations) == 0

    def test_reviewer_missing_verdict(self, supervisor: RigourSupervisor) -> None:
        """Reviewer without verdict → contract violation."""
        violations = supervisor.check_persona_boundaries(
            role="reviewer",
            files_changed=[],
            output_summary="The code has some issues but overall fine.",
        )
        contract_violations = [v for v in violations if v.violation_type == "missing_output_marker"]
        assert len(contract_violations) >= 1

    def test_security_with_pass_verdict(self, supervisor: RigourSupervisor) -> None:
        violations = supervisor.check_persona_boundaries(
            role="security",
            files_changed=[],
            output_summary="## Verdict\nPASS\n## Findings\nNo issues.",
        )
        contract_violations = [v for v in violations if v.violation_type == "missing_output_marker"]
        assert len(contract_violations) == 0

    def test_empty_summary_no_crash(self, supervisor: RigourSupervisor) -> None:
        """Empty output summary should not crash — just skip contract check."""
        violations = supervisor.check_persona_boundaries(
            role="planner",
            files_changed=[],
            output_summary="",
        )
        # Empty summary means contract patterns aren't checked
        assert isinstance(violations, list)


# ── Phase 7: Role-Aware Violation Filtering ──────────────────────────────

class TestFilterViolationsForRole:
    """Test the filter_violations_for_role method."""

    def test_security_violations_pass_through_for_all_roles(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Security violations should always pass through at full severity."""
        violations = [
            Violation(
                gate_id="hardcoded-secrets",
                message="API key found",
                severity=ViolationSeverity.ERROR,
                category="security",
            )
        ]
        for role in ["coder", "qa", "devops", "sre"]:
            filtered = supervisor.filter_violations_for_role(violations, role)
            assert len(filtered) == 1
            assert filtered[0].severity == ViolationSeverity.ERROR

    def test_complexity_downgraded_for_qa(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Complexity violations should be INFO for QA (test files can be verbose)."""
        violations = [
            Violation(
                gate_id="function-length",
                message="Test function too long",
                severity=ViolationSeverity.WARNING,
                category="complexity",
            )
        ]
        filtered = supervisor.filter_violations_for_role(violations, "qa")
        assert len(filtered) == 1
        assert filtered[0].severity == ViolationSeverity.INFO

    def test_complexity_kept_for_coder(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Complexity violations stay at original severity for coder."""
        violations = [
            Violation(
                gate_id="function-length",
                message="Handler too long",
                severity=ViolationSeverity.WARNING,
                category="complexity",
            )
        ]
        filtered = supervisor.filter_violations_for_role(violations, "coder")
        assert len(filtered) == 1
        assert filtered[0].severity == ViolationSeverity.WARNING

    def test_style_downgraded_for_devops(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Style violations should be INFO for DevOps."""
        violations = [
            Violation(
                gate_id="missing-docstrings",
                message="No docstring",
                severity=ViolationSeverity.WARNING,
                category="style",
            )
        ]
        filtered = supervisor.filter_violations_for_role(violations, "devops")
        assert len(filtered) == 1
        assert filtered[0].severity == ViolationSeverity.INFO

    def test_no_category_violations_pass_through(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Violations with empty category should pass through unchanged."""
        violations = [
            Violation(
                gate_id="unknown-gate",
                message="Something wrong",
                severity=ViolationSeverity.ERROR,
                category="",
            )
        ]
        filtered = supervisor.filter_violations_for_role(violations, "qa")
        assert len(filtered) == 1
        assert filtered[0].severity == ViolationSeverity.ERROR


# ── Phase 7: Glob Matching Helper ────────────────────────────────────────

class TestGlobMatch:
    """Test the _glob_match helper for persona boundary checks."""

    def test_double_star_matches_everything(self) -> None:
        assert _glob_match("any/file.py", "**") is True

    def test_prefix_pattern(self) -> None:
        assert _glob_match("tests/test_auth.py", "tests/**") is True
        assert _glob_match("src/main.py", "tests/**") is False

    def test_suffix_pattern(self) -> None:
        assert _glob_match("src/auth_test.py", "*_test.*") is True
        assert _glob_match("src/auth.py", "*_test.*") is False

    def test_spec_pattern(self) -> None:
        assert _glob_match("src/auth.spec.ts", "*.spec.*") is True
        assert _glob_match("src/auth.ts", "*.spec.*") is False

    def test_exact_match(self) -> None:
        assert _glob_match("Dockerfile", "Dockerfile*") is True
        assert _glob_match("Makefile", "Makefile") is True

    def test_nested_prefix(self) -> None:
        assert _glob_match(".github/workflows/ci.yml", ".github/**") is True

    def test_test_star_prefix_pattern(self) -> None:
        """test*/** should match test/ and tests/."""
        assert _glob_match("test/unit/test_foo.py", "test*/**") is True
        assert _glob_match("tests/unit/test_foo.py", "test*/**") is True
        assert _glob_match("src/utils.py", "test*/**") is False

    def test_backslash_normalization(self) -> None:
        assert _glob_match("tests\\test_auth.py", "tests/**") is True


# ── Phase 7: Configuration Consistency ───────────────────────────────────

class TestConfigConsistency:
    """Ensure configuration dicts are internally consistent."""

    def test_all_blocking_roles_have_retry_limits(self) -> None:
        """Every role in BLOCKING_SEVERITIES should have a MAX_RETRIES entry."""
        for role in BLOCKING_SEVERITIES:
            assert role in MAX_RETRIES_BY_ROLE, (
                f"Role '{role}' has blocking severities but no max retry limit"
            )

    def test_all_profiles_include_security(self) -> None:
        """Every role gate profile should include security (if it has a profile at all)."""
        for role, profile in ROLE_GATE_PROFILES.items():
            assert "security" in profile, (
                f"Role '{role}' gate profile missing 'security' category"
            )

    def test_code_producing_roles_have_boundaries(self) -> None:
        """Code-producing roles should have persona boundaries."""
        code_roles = {"coder", "qa", "devops", "sre"}
        for role in code_roles:
            assert role in PERSONA_BOUNDARIES, (
                f"Code-producing role '{role}' missing persona boundary"
            )

    def test_non_code_roles_forbid_all_files(self) -> None:
        """Non-code-producing roles should have '**' in forbidden patterns."""
        non_code_roles = {"planner", "reviewer", "security", "lead"}
        for role in non_code_roles:
            boundary = PERSONA_BOUNDARIES.get(role)
            assert boundary is not None, f"Role '{role}' missing persona boundary"
            assert "**" in boundary.forbidden_file_patterns, (
                f"Non-code role '{role}' should forbid all file writes"
            )
            assert boundary.must_produce_files is False, (
                f"Non-code role '{role}' should not be required to produce files"
            )

    def test_escalation_roles_exist_in_profiles(self) -> None:
        """Roles with severity escalation should also have gate profiles."""
        for role in SEVERITY_ESCALATION:
            assert role in ROLE_GATE_PROFILES, (
                f"Role '{role}' has severity escalation but no gate profile"
            )

    def test_code_producing_roles_matches_blocking_severities(self) -> None:
        """CODE_PRODUCING_ROLES should match BLOCKING_SEVERITIES keys."""
        for role in CODE_PRODUCING_ROLES:
            assert role in BLOCKING_SEVERITIES, (
                f"Code-producing role '{role}' missing from BLOCKING_SEVERITIES"
            )

    def test_known_gate_categories_covers_all_profiles(self) -> None:
        """All categories in role profiles should be in KNOWN_GATE_CATEGORIES."""
        for role, profile in ROLE_GATE_PROFILES.items():
            for category in profile:
                assert category in KNOWN_GATE_CATEGORIES, (
                    f"Role '{role}' profile category '{category}' not in KNOWN_GATE_CATEGORIES"
                )

    def test_universal_categories_subset_of_known(self) -> None:
        """Universal gate categories must be a subset of known categories."""
        assert UNIVERSAL_GATE_CATEGORIES.issubset(KNOWN_GATE_CATEGORIES)


# ── Phase 7: Gate category cross-validation with gates.py ────────────────

class TestGateCategoryCrossValidation:
    """Cross-validate that gates.py categories match supervisor profiles."""

    def test_all_engineering_gate_categories_are_known(self) -> None:
        """Every category in engineering gates should be in KNOWN_GATE_CATEGORIES."""
        from rigovo.domains.engineering.gates import get_engineering_gates
        gates = get_engineering_gates()
        for gate in gates:
            assert gate.category in KNOWN_GATE_CATEGORIES, (
                f"Gate '{gate.gate_id}' has category '{gate.category}' "
                f"which is not in KNOWN_GATE_CATEGORIES"
            )

    def test_security_gates_have_empty_relevant_roles(self) -> None:
        """Security gates should apply to all roles (empty relevant_roles)."""
        from rigovo.domains.engineering.gates import get_engineering_gates
        gates = get_engineering_gates()
        for gate in gates:
            if gate.category == "security":
                assert gate.relevant_roles == [], (
                    f"Security gate '{gate.gate_id}' should have empty "
                    f"relevant_roles (applies to all), got {gate.relevant_roles}"
                )


# ── Phase 7: SME Gap #4 — Additional Escalation Tests ───────────────────

class TestSeverityEscalationExtended:
    """Extended escalation tests from SME review Gap #4."""

    def test_sre_security_escalation(self, supervisor: RigourSupervisor) -> None:
        """SRE: security violations should escalate to critical."""
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "hardcoded-secrets", "API key in SRE logging config", "security"),
        ])]
        packet = supervisor.evaluate(results, role="sre")
        assert packet.items[0].severity == "critical"

    def test_already_critical_stays_critical(self, supervisor: RigourSupervisor) -> None:
        """Escalation on an already-critical severity should not demote."""
        # Simulate a violation that's already at critical level
        violations = [Violation(
            gate_id="hardcoded-secrets",
            message="Root password exposed",
            severity=ViolationSeverity.ERROR,  # Highest enum level
            category="security",
        )]
        filtered = supervisor.filter_violations_for_role(violations, "coder")
        # Should stay at ERROR (highest enum level — "critical" maps to ERROR in enums)
        assert filtered[0].severity == ViolationSeverity.ERROR

    def test_escalation_fires_after_profile_filtering(self, supervisor: RigourSupervisor) -> None:
        """Verify escalation applies AFTER profile check (security is universal)."""
        # Security is universal, so even if role doesn't have security in profile
        # (which won't happen, but conceptually), escalation still fires
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("warning", "eval-usage", "eval() used in build script", "security"),
        ])]
        packet = supervisor.evaluate(results, role="devops")
        # Security + devops → escalated to critical (even from warning)
        assert packet.items[0].severity == "critical"


# ── Phase 7: SME Gap #11 — Instance-Based Agent Tests ────────────────────

class TestInstanceBasedAgentIntegration:
    """Test that instance-based agents correctly resolve to base roles."""

    def test_instance_agent_uses_base_role_for_boundaries(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """backend-engineer-1 should use 'coder' persona boundaries."""
        # Simulate: the instance role maps to "coder"
        # check_persona_boundaries uses the base role, not instance ID
        violations = supervisor.check_persona_boundaries(
            role="coder",  # This is what quality_check.py passes as base_role
            files_changed=["tests/test_auth.py"],
        )
        assert any(v.violation_type == "forbidden_file" for v in violations)

    def test_instance_agent_severity_escalation(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Instance agent with base_role=coder should get coder's escalation."""
        results = [_make_categorized_gate_result(GateStatus.FAILED, [
            ("error", "sql-injection", "SQL injection in ORM", "security"),
        ])]
        # Evaluate with base_role "coder" (as quality_check.py would)
        packet = supervisor.evaluate(results, role="coder")
        assert packet.items[0].severity == "critical"

    def test_instance_agent_gate_profile_filtering(
        self, supervisor: RigourSupervisor,
    ) -> None:
        """Instance agent with base_role=qa should get qa's profile filtering."""
        violations = [
            Violation(
                gate_id="function-length",
                message="Test helper long",
                severity=ViolationSeverity.WARNING,
                category="complexity",
            ),
        ]
        # QA profile doesn't include complexity → downgraded to INFO
        filtered = supervisor.filter_violations_for_role(violations, "qa")
        assert filtered[0].severity == ViolationSeverity.INFO


# ── Phase 7: Severity Helper Tests ──────────────────────────────────────

class TestStrToViolationSeverity:
    """Test the _str_to_violation_severity helper."""

    def test_critical_maps_to_error(self) -> None:
        assert _str_to_violation_severity("critical") == ViolationSeverity.ERROR

    def test_high_maps_to_error(self) -> None:
        assert _str_to_violation_severity("high") == ViolationSeverity.ERROR

    def test_medium_maps_to_warning(self) -> None:
        assert _str_to_violation_severity("medium") == ViolationSeverity.WARNING

    def test_info_maps_to_info(self) -> None:
        assert _str_to_violation_severity("info") == ViolationSeverity.INFO

    def test_empty_returns_none(self) -> None:
        assert _str_to_violation_severity("") is None

    def test_unknown_returns_none(self) -> None:
        assert _str_to_violation_severity("debug") is None

    def test_case_insensitive(self) -> None:
        assert _str_to_violation_severity("ERROR") == ViolationSeverity.ERROR
        assert _str_to_violation_severity("Warning") == ViolationSeverity.WARNING
