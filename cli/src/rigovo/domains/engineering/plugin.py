"""Engineering domain plugin — ships with Rigovo v1."""

from __future__ import annotations

from typing import Any

from rigovo.domain.interfaces.domain_plugin import (
    DomainPlugin,
    AgentRoleDefinition,
    TaskTypeDefinition,
)
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domains.engineering.roles import get_engineering_roles
from rigovo.domains.engineering.tools import get_engineering_tools


class EngineeringDomain(DomainPlugin):
    """
    Engineering domain plugin.

    Provides agent roles, task types, quality gates, and tools
    for software engineering teams (backend, frontend, infra, etc.).

    This is the default domain that ships with Rigovo v1.
    """

    @property
    def domain_id(self) -> str:
        return "engineering"

    @property
    def name(self) -> str:
        return "Software Engineering"

    def get_agent_roles(self) -> list[AgentRoleDefinition]:
        return get_engineering_roles()

    def get_task_types(self) -> list[TaskTypeDefinition]:
        return [
            TaskTypeDefinition("feature", "Feature", "New functionality or capability"),
            TaskTypeDefinition("bug", "Bug Fix", "Fix a defect in existing code"),
            TaskTypeDefinition("refactor", "Refactor", "Improve code structure without changing behaviour"),
            TaskTypeDefinition("test", "Test", "Add or improve tests"),
            TaskTypeDefinition("docs", "Documentation", "Write or update documentation"),
            TaskTypeDefinition("infra", "Infrastructure", "CI/CD, deployment, or infrastructure changes"),
            TaskTypeDefinition("security", "Security", "Fix or improve security posture"),
            TaskTypeDefinition("performance", "Performance", "Optimise speed, memory, or efficiency"),
            TaskTypeDefinition("investigation", "Investigation", "Research or spike — no code output"),
        ]

    def get_quality_gates(self) -> list[QualityGate]:
        # Quality gates are infrastructure — they wrap the Rigour CLI.
        # The plugin returns an empty list here; the container wires
        # the RigourGate implementation based on gate configs.
        # This keeps the domain layer free of infrastructure deps.
        return []

    def get_tools(self, role_id: str) -> list[dict[str, Any]]:
        return get_engineering_tools(role_id)

    def build_system_prompt(self, role_id: str, enrichment_context: str = "") -> str:
        """Build a full system prompt for an engineering agent role."""
        roles = {r.role_id: r for r in self.get_agent_roles()}
        role_def = roles.get(role_id)

        if not role_def:
            return f"You are a {role_id} agent in a software engineering team."

        sections = [role_def.default_system_prompt]

        if enrichment_context:
            sections.append(
                f"--- ENRICHMENT (from Master Agent) ---\n{enrichment_context}"
            )

        return "\n\n".join(sections)
