"""Team assembler — decides which agents execute in what order for a task."""

from __future__ import annotations

from dataclasses import dataclass

from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.task import TaskType, TaskComplexity


@dataclass
class PipelineConfig:
    """The assembled pipeline: which agents run, in what order."""

    agents: list[Agent]  # Ordered by pipeline_order
    gates_after: list[str]  # Which roles trigger quality gates (e.g., ['coder', 'devops'])

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    @property
    def roles(self) -> list[str]:
        return [a.role for a in self.agents]


class TeamAssemblerService:
    """
    Assembles the execution pipeline for a task.

    Given a team's agents and the task classification, decides:
    - Which agents participate (not all agents for every task)
    - In what order they execute
    - Which agents' output triggers quality gates

    Pure domain logic. No I/O.
    """

    # Roles that produce code → gates should run after them
    CODE_PRODUCING_ROLES = {"coder", "devops", "sre"}

    # Minimum pipeline for different task types
    TASK_PIPELINES: dict[str, list[str]] = {
        "feature": ["planner", "coder", "reviewer", "qa"],
        "bug": ["coder", "reviewer"],
        "refactor": ["coder", "reviewer"],
        "test": ["qa"],
        "docs": ["coder"],
        "infra": ["devops", "sre", "reviewer"],
        "security": ["security", "coder", "reviewer"],
        "performance": ["coder", "reviewer"],
        "investigation": ["planner"],
    }

    def assemble(
        self,
        available_agents: list[Agent],
        task_type: TaskType,
        complexity: TaskComplexity,
    ) -> PipelineConfig:
        """
        Build the execution pipeline.

        Args:
            available_agents: All active agents in the assigned team.
            task_type: Classified task type.
            complexity: Classified complexity level.

        Returns:
            PipelineConfig with ordered agents and gate triggers.
        """
        # 1. Get the ideal pipeline for this task type
        ideal_roles = self.TASK_PIPELINES.get(task_type.value, ["coder", "reviewer"])

        # 2. For high/critical complexity, add more agents
        if complexity in (TaskComplexity.HIGH, TaskComplexity.CRITICAL):
            # Add lead if available and not already in pipeline
            if "lead" not in ideal_roles:
                ideal_roles = ["lead"] + ideal_roles
            # Add security for critical tasks
            if complexity == TaskComplexity.CRITICAL and "security" not in ideal_roles:
                ideal_roles.append("security")

        # 3. Match ideal roles to available agents
        agent_by_role: dict[str, Agent] = {a.role: a for a in available_agents if a.is_active}
        pipeline_agents: list[Agent] = []

        for role in ideal_roles:
            if role in agent_by_role:
                pipeline_agents.append(agent_by_role[role])

        # 4. If no coder was found (e.g., team only has generic agents), include all
        if not pipeline_agents:
            pipeline_agents = sorted(
                [a for a in available_agents if a.is_active],
                key=lambda a: a.pipeline_order,
            )

        # 5. Sort by pipeline_order (CTO-defined execution sequence)
        pipeline_agents.sort(key=lambda a: a.pipeline_order)

        # 6. Determine which roles trigger quality gates
        gates_after = [
            a.role for a in pipeline_agents
            if a.role in self.CODE_PRODUCING_ROLES
        ]

        return PipelineConfig(agents=pipeline_agents, gates_after=gates_after)
