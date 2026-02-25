"""Tests for the Engineering domain plugin."""

from rigovo.domains.engineering.plugin import EngineeringDomain
from rigovo.domains.engineering.roles import get_engineering_roles
from rigovo.domains.engineering.tools import get_engineering_tools
from rigovo.domains.engineering.gates import get_engineering_gates


class TestEngineeringDomain:
    def setup_method(self):
        self.domain = EngineeringDomain()

    def test_domain_id(self):
        assert self.domain.domain_id == "engineering"

    def test_has_all_core_roles(self):
        roles = self.domain.get_agent_roles()
        role_ids = [r.role_id for r in roles]

        assert "coder" in role_ids
        assert "reviewer" in role_ids
        assert "planner" in role_ids
        assert "qa" in role_ids
        assert "security" in role_ids
        assert "devops" in role_ids
        assert "lead" in role_ids

    def test_all_roles_have_system_prompts(self):
        for role in self.domain.get_agent_roles():
            assert role.default_system_prompt, f"Role {role.role_id} missing system prompt"
            assert len(role.default_system_prompt) > 100, (
                f"Role {role.role_id} has suspiciously short prompt"
            )

    def test_code_producing_roles_flagged(self):
        roles = self.domain.get_agent_roles()
        code_roles = [r for r in roles if r.produces_code]
        code_role_ids = [r.role_id for r in code_roles]

        assert "coder" in code_role_ids
        assert "qa" in code_role_ids
        assert "devops" in code_role_ids
        # These should NOT produce code
        assert "reviewer" not in code_role_ids
        assert "planner" not in code_role_ids

    def test_task_types(self):
        task_types = self.domain.get_task_types()
        type_ids = [t.type_id for t in task_types]

        assert "feature" in type_ids
        assert "bug" in type_ids
        assert "refactor" in type_ids
        assert "security" in type_ids
        assert "investigation" in type_ids

    def test_tools_per_role(self):
        # Coder should have write_file
        coder_tools = self.domain.get_tools("coder")
        coder_tool_names = [t["name"] for t in coder_tools]
        assert "write_file" in coder_tool_names
        assert "read_file" in coder_tool_names

        # Reviewer should NOT have write_file
        reviewer_tools = self.domain.get_tools("reviewer")
        reviewer_tool_names = [t["name"] for t in reviewer_tools]
        assert "write_file" not in reviewer_tool_names
        assert "read_file" in reviewer_tool_names

    def test_build_system_prompt(self):
        prompt = self.domain.build_system_prompt("coder")
        assert "Senior Software Engineer" in prompt

    def test_build_system_prompt_with_enrichment(self):
        prompt = self.domain.build_system_prompt(
            "coder",
            enrichment_context="Always check for CSRF on POST endpoints.",
        )
        assert "CSRF" in prompt
        assert "ENRICHMENT" in prompt

    def test_build_system_prompt_unknown_role(self):
        prompt = self.domain.build_system_prompt("unknown_role")
        assert "unknown_role" in prompt


class TestEngineeringGates:
    def test_has_security_gates(self):
        gates = get_engineering_gates()
        security_gates = [g for g in gates if g.category == "security"]
        assert len(security_gates) >= 5

    def test_zero_tolerance_security_gates(self):
        gates = get_engineering_gates()
        security_gates = [g for g in gates if g.category == "security"]
        for gate in security_gates:
            assert gate.threshold == 0, f"Security gate {gate.gate_id} should be zero-tolerance"

    def test_has_complexity_gates(self):
        gates = get_engineering_gates()
        complexity_gates = [g for g in gates if g.category == "complexity"]
        assert len(complexity_gates) >= 3
