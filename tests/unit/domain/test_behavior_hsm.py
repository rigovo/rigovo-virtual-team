"""Tests for Hierarchical State Machine (HSM) behavioral inheritance.

Covers:
- State resolution by role, specialisation, and task_type
- Phase inheritance from parent states
- Prompt section generation
- Edge cases (unknown roles, empty specialisation)
"""

from __future__ import annotations

import unittest

from rigovo.domain.services.behavior_hsm import (
    BehaviorPhase,
    BehaviorState,
    build_hsm_prompt_section,
    get_inherited_phases,
    resolve_behavior_state,
)


class TestResolveState(unittest.TestCase):
    """Test behavioral state resolution."""

    def test_coder_resolves_to_senior_engineer(self):
        """A bare coder should resolve to senior_engineer root state."""
        state = resolve_behavior_state("coder")
        assert state is not None
        assert state.state_id == "senior_engineer"

    def test_frontend_coder_resolves_to_frontend_expert(self):
        """A coder with 'frontend' specialisation should resolve to frontend_expert."""
        state = resolve_behavior_state("coder", specialisation="frontend", task_type="feature")
        assert state is not None
        assert state.state_id == "frontend_expert"

    def test_backend_coder_resolves_to_backend_expert(self):
        """A coder with 'backend' specialisation should resolve to backend_expert."""
        state = resolve_behavior_state("coder", specialisation="backend", task_type="feature")
        assert state is not None
        assert state.state_id == "backend_expert"

    def test_fullstack_coder_resolves(self):
        """A coder with 'fullstack' specialisation resolves to fullstack_engineer."""
        state = resolve_behavior_state("coder", specialisation="fullstack")
        assert state is not None
        assert state.state_id == "fullstack_engineer"

    def test_devops_resolves_to_senior_engineer(self):
        """DevOps without infra task type resolves to senior_engineer root."""
        state = resolve_behavior_state("devops")
        assert state is not None
        assert state.state_id == "senior_engineer"

    def test_devops_infra_resolves_to_infra_engineer(self):
        """DevOps with infra task type resolves to infra_engineer."""
        state = resolve_behavior_state("devops", task_type="infra")
        assert state is not None
        assert state.state_id == "infra_engineer"

    def test_reviewer_resolves_to_senior_reviewer(self):
        """Reviewer resolves to senior_reviewer."""
        state = resolve_behavior_state("reviewer")
        assert state is not None
        assert state.state_id == "senior_reviewer"

    def test_security_resolves_to_security_reviewer(self):
        """Security role resolves to security_reviewer (child of senior_reviewer)."""
        state = resolve_behavior_state("security")
        assert state is not None
        assert state.state_id == "security_reviewer"

    def test_qa_resolves_to_senior_qa(self):
        """QA role resolves to senior_qa."""
        state = resolve_behavior_state("qa")
        assert state is not None
        assert state.state_id == "senior_qa"

    def test_unknown_role_returns_none(self):
        """Unknown role with no matching conditions returns None."""
        state = resolve_behavior_state("unknown_role")
        assert state is None

    def test_react_specialisation_matches_frontend(self):
        """'react' specialisation should match frontend_expert."""
        state = resolve_behavior_state("coder", specialisation="react", task_type="feature")
        assert state is not None
        assert state.state_id == "frontend_expert"


class TestPhaseInheritance(unittest.TestCase):
    """Test that phases are inherited correctly from parent states."""

    def test_senior_engineer_has_base_phases(self):
        """Root senior_engineer should have architecture_review and dependency_check."""
        state = resolve_behavior_state("coder")
        assert state is not None
        phases = get_inherited_phases(state)
        names = [p.name for p in phases]
        assert "architecture_review" in names
        assert "dependency_check" in names

    def test_frontend_expert_inherits_parent_phases(self):
        """frontend_expert should have parent phases + component_design."""
        state = resolve_behavior_state("coder", specialisation="frontend", task_type="feature")
        assert state is not None
        phases = get_inherited_phases(state)
        names = [p.name for p in phases]
        # Inherited from senior_engineer (parent)
        assert "architecture_review" in names
        assert "dependency_check" in names
        # Own phase
        assert "component_design" in names
        # Architecture review should come BEFORE component design (parent first)
        assert names.index("architecture_review") < names.index("component_design")

    def test_backend_expert_inherits_and_adds(self):
        """backend_expert should have parent phases + api_contract + data_model_review."""
        state = resolve_behavior_state("coder", specialisation="backend", task_type="feature")
        assert state is not None
        phases = get_inherited_phases(state)
        names = [p.name for p in phases]
        assert "architecture_review" in names
        assert "dependency_check" in names
        assert "api_contract" in names
        assert "data_model_review" in names

    def test_security_reviewer_has_audit_phase(self):
        """security_reviewer should have security audit phase."""
        state = resolve_behavior_state("security")
        assert state is not None
        phases = get_inherited_phases(state)
        names = [p.name for p in phases]
        assert "pre_security_scan" in names

    def test_qa_has_test_strategy_phase(self):
        """QA should have test_strategy mandatory phase."""
        state = resolve_behavior_state("qa")
        assert state is not None
        phases = get_inherited_phases(state)
        names = [p.name for p in phases]
        assert "test_strategy" in names

    def test_no_duplicate_phases(self):
        """Phases should not be duplicated even if parent and child define the same name."""
        state = resolve_behavior_state("coder", specialisation="frontend", task_type="feature")
        assert state is not None
        phases = get_inherited_phases(state)
        names = [p.name for p in phases]
        # No duplicates
        assert len(names) == len(set(names))

    def test_infra_engineer_has_infra_impact(self):
        """infra_engineer should inherit base + add infra_impact."""
        state = resolve_behavior_state("devops", task_type="infra")
        assert state is not None
        phases = get_inherited_phases(state)
        names = [p.name for p in phases]
        assert "architecture_review" in names
        assert "infra_impact" in names


class TestBuildHSMPromptSection(unittest.TestCase):
    """Test prompt section generation."""

    def test_coder_gets_behavioral_prompt(self):
        """Coder should get a non-empty behavioral prompt section."""
        section = build_hsm_prompt_section("coder")
        assert len(section) > 0
        assert "BEHAVIORAL STATE" in section
        assert "Senior Engineer" in section

    def test_frontend_expert_prompt_includes_phases(self):
        """Frontend expert prompt should mention all mandatory phases."""
        section = build_hsm_prompt_section("coder", specialisation="frontend", task_type="feature")
        assert "ARCHITECTURE REVIEW" in section
        assert "DEPENDENCY CHECK" in section
        assert "COMPONENT DESIGN" in section

    def test_unknown_role_returns_empty(self):
        """Unknown role should return empty string."""
        section = build_hsm_prompt_section("unknown_role")
        assert section == ""

    def test_reviewer_gets_light_prompt(self):
        """Reviewer has no mandatory phases, so prompt should be minimal or empty."""
        section = build_hsm_prompt_section("reviewer")
        # senior_reviewer has no mandatory_phases, so no behavioral section
        assert section == ""

    def test_security_gets_audit_prompt(self):
        """Security reviewer should get security audit in behavioral prompt."""
        section = build_hsm_prompt_section("security")
        assert "SECURITY" in section

    def test_phase_order_in_prompt(self):
        """Phases should appear in inheritance order (parent first) in prompt."""
        section = build_hsm_prompt_section("coder", specialisation="backend", task_type="feature")
        arch_pos = section.find("ARCHITECTURE REVIEW")
        api_pos = section.find("API CONTRACT")
        assert arch_pos < api_pos, "Architecture review must come before API contract"


class TestBehaviorPhaseDataclass(unittest.TestCase):
    """Test BehaviorPhase and BehaviorState dataclasses."""

    def test_phase_defaults(self):
        """Phase should have sensible defaults."""
        phase = BehaviorPhase(
            name="test",
            description="Test phase",
            prompt_injection="Do the thing",
            output_label="TEST_OUTPUT",
        )
        assert phase.tools_required == []
        assert phase.estimated_tokens == 500

    def test_state_defaults(self):
        """State should have sensible defaults."""
        state = BehaviorState(
            state_id="test",
            name="Test State",
            description="For testing",
        )
        assert state.parent_id is None
        assert state.mandatory_phases == []
        assert state.activation_conditions == {}


if __name__ == "__main__":
    unittest.main()
