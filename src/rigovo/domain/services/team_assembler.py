"""Team assembler — translates Master Agent's staffing plan into executable pipeline.

The old assembler was a hardcoded lookup table:
    "feature" → [planner, coder, reviewer, qa]
    "infra" → [devops, sre, reviewer]

The new assembler takes the Master Agent's StaffingPlan (which specifies
exactly which agents, how many of each role, their specialisations,
assignments, and dependencies) and produces the executable PipelineConfig.

The assembler's job is NOT to decide team composition — that's the Master
Agent's job. The assembler's job is to:
1. Map StaffingPlan agent assignments to actual Agent entities
2. Clone Agent entities when multiple instances of same role are needed
3. Inject per-instance assignments into each agent's system prompt
4. Build the execution DAG from the staffing plan's dependency graph
5. Validate that all dependencies are satisfiable
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid5, NAMESPACE_DNS

from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.task import TaskComplexity, TaskType

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """The assembled pipeline: which agents run, in what order."""

    agents: list[Agent]  # Ordered by execution priority
    gates_after: list[str]  # Which instance_ids trigger quality gates
    execution_dag: dict[str, list[str]] = field(default_factory=dict)
    parallel_groups: list[list[str]] = field(default_factory=list)

    # Per-instance metadata from the staffing plan
    instance_assignments: dict[str, str] = field(default_factory=dict)  # instance_id → assignment
    instance_verifications: dict[str, str] = field(default_factory=dict)  # instance_id → verification
    instance_specialisations: dict[str, str] = field(default_factory=dict)  # instance_id → specialisation

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    @property
    def roles(self) -> list[str]:
        return [a.role for a in self.agents]

    @property
    def instance_ids(self) -> list[str]:
        return [a.instance_id for a in self.agents if hasattr(a, "instance_id")]


# Roles that produce code → quality gates should run after them
CODE_PRODUCING_ROLES = {"coder", "devops", "sre", "qa"}

# ── Canonical flow order — enforced programmatically, NOT by LLM prompt ──
# Lower number = runs earlier. Agents MUST follow this ordering.
# The LLM can decide WHICH agents to include, but it CANNOT override the order.
ROLE_PRIORITY: dict[str, int] = {
    "planner":  10,   # ALWAYS first — creates the plan
    "coder":    20,   # Implements the plan
    "reviewer": 30,   # Reviews code produced by coders
    "security": 40,   # Security audit after code review
    "qa":       50,   # Tests after code is reviewed and secure
    "devops":   60,   # Infrastructure after quality checks
    "sre":      70,   # Reliability after infra
    "docs":     80,   # Documentation after everything
    "lead":     90,   # Tech Lead LAST — final architectural review of ALL work
}


class TeamAssemblerService:
    """
    Assembles the execution pipeline from the Master Agent's staffing plan.

    Two modes:
    1. **Staffing plan mode** (primary): ``assemble_from_plan()`` takes the
       Master Agent's StaffingPlan dict and produces a PipelineConfig with
       per-instance agents, custom assignments, and a real DAG.
    2. **Legacy mode** (fallback): ``assemble()`` uses the old hardcoded
       TASK_PIPELINES dict for backward compatibility.
    """

    # ── Primary: StaffingPlan-driven assembly ──────────────────────────

    def assemble_from_plan(
        self,
        staffing_plan: dict[str, Any],
        available_agents: list[Agent],
    ) -> PipelineConfig:
        """Build pipeline from the Master Agent's staffing plan.

        This is where the magic happens:
        - Multiple coders get cloned from the "coder" template agent
        - Each clone gets a unique instance_id and a custom assignment
        - The execution DAG comes from the staffing plan, not hardcoded
        - Quality gates fire after any code-producing agent
        """
        agent_by_role: dict[str, Agent] = {
            a.role: a for a in available_agents if a.is_active
        }

        plan_agents = staffing_plan.get("agents", [])
        if not plan_agents:
            logger.warning("Empty staffing plan, falling back to legacy assembly")
            return self.assemble(
                available_agents,
                TaskType(staffing_plan.get("task_type", "feature")),
                TaskComplexity(staffing_plan.get("complexity", "medium")),
            )

        pipeline_agents: list[Agent] = []
        instance_assignments: dict[str, str] = {}
        instance_verifications: dict[str, str] = {}
        instance_specialisations: dict[str, str] = {}
        seen_instance_ids: set[str] = set()

        for slot in plan_agents:
            role = slot.get("role", "coder")
            instance_id = slot.get("instance_id", f"{role}-{len(pipeline_agents) + 1}")
            specialisation = slot.get("specialisation", "general")
            assignment = slot.get("assignment", "")
            verification = slot.get("verification", "")

            # Deduplicate instance IDs
            if instance_id in seen_instance_ids:
                instance_id = f"{instance_id}-{len(pipeline_agents)}"
            seen_instance_ids.add(instance_id)

            # Find the template agent for this role
            template = agent_by_role.get(role)
            if template is None:
                logger.warning(
                    "Staffing plan requests role '%s' (instance '%s') "
                    "but no such agent exists — skipping",
                    role,
                    instance_id,
                )
                continue

            # Clone the template for this specific instance
            agent = self._clone_agent_for_instance(
                template, instance_id, specialisation, assignment, verification,
                slot.get("tools_required", []),
            )
            pipeline_agents.append(agent)
            instance_assignments[instance_id] = assignment
            instance_verifications[instance_id] = verification
            instance_specialisations[instance_id] = specialisation

        if not pipeline_agents:
            logger.warning("No agents could be assembled from plan, falling back")
            return self.assemble(
                available_agents,
                TaskType(staffing_plan.get("task_type", "feature")),
                TaskComplexity(staffing_plan.get("complexity", "medium")),
            )

        # ─────────────────────────────────────────────────────────────────
        # ENFORCE CANONICAL ORDERING — sort agents by ROLE_PRIORITY
        # The LLM decides WHICH agents to include, but we enforce ORDER.
        # This prevents "lead first" or "qa before coder" mistakes.
        # ─────────────────────────────────────────────────────────────────
        pipeline_agents = self._enforce_canonical_order(pipeline_agents)

        # Build DAG from the CORRECTED agent order — rebuild from scratch
        # to ensure dependencies match the enforced order.
        execution_dag = self._build_enforced_dag(pipeline_agents, plan_agents)

        # Compute parallel groups from the corrected DAG
        parallel_groups = self._compute_parallel_groups(
            [a.instance_id for a in pipeline_agents],
            execution_dag,
        )

        # Quality gates after code-producing agents
        gates_after = [
            a.instance_id for a in pipeline_agents
            if a.role in CODE_PRODUCING_ROLES
        ]

        return PipelineConfig(
            agents=pipeline_agents,
            gates_after=gates_after,
            execution_dag=execution_dag,
            parallel_groups=parallel_groups,
            instance_assignments=instance_assignments,
            instance_verifications=instance_verifications,
            instance_specialisations=instance_specialisations,
        )

    @staticmethod
    def _enforce_canonical_order(agents: list[Agent]) -> list[Agent]:
        """Sort agents by ROLE_PRIORITY to enforce canonical pipeline order.

        This is the KEY architectural enforcement. The LLM decides which
        agents to staff, but we ALWAYS enforce:
            planner → coder(s) → reviewer → security → qa → devops → sre → lead

        Within the same role (e.g. multiple coders), we preserve the LLM's
        original order since it may have intentional specialisation sequencing.
        """
        def sort_key(agent: Agent) -> tuple[int, int]:
            role = agent.role
            priority = ROLE_PRIORITY.get(role, 55)  # Unknown roles go between qa and devops
            # Preserve original order within same role by using enumerate index
            return (priority, 0)

        # Stable sort: agents with same priority keep their relative order
        sorted_agents = sorted(agents, key=sort_key)

        if [a.instance_id for a in sorted_agents] != [a.instance_id for a in agents]:
            original = [f"{a.role}({a.instance_id})" for a in agents]
            corrected = [f"{a.role}({a.instance_id})" for a in sorted_agents]
            logger.info(
                "Enforced canonical ordering. LLM proposed: %s → Corrected to: %s",
                " → ".join(original),
                " → ".join(corrected),
            )

        return sorted_agents

    @staticmethod
    def _build_enforced_dag(
        pipeline_agents: list[Agent],
        plan_agents: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        """Build a dependency DAG that respects canonical role ordering.

        Strategy:
        - Group agents by ROLE_PRIORITY tier
        - Each tier depends on ALL agents in the previous tier
        - Within the same tier, agents can run in parallel (no inter-dependency)
        - This guarantees: all planners finish → all coders start →
          all coders finish → all reviewers start → etc.
        """
        valid_ids = {a.instance_id for a in pipeline_agents}

        # Group agents by priority tier
        tiers: dict[int, list[str]] = {}
        for agent in pipeline_agents:
            priority = ROLE_PRIORITY.get(agent.role, 55)
            tiers.setdefault(priority, []).append(agent.instance_id)

        sorted_priorities = sorted(tiers.keys())

        dag: dict[str, list[str]] = {}
        for tier_idx, priority in enumerate(sorted_priorities):
            tier_agents = tiers[priority]
            if tier_idx == 0:
                # First tier has no dependencies
                for iid in tier_agents:
                    dag[iid] = []
            else:
                # This tier depends on ALL agents in the previous tier
                prev_priority = sorted_priorities[tier_idx - 1]
                prev_agents = tiers[prev_priority]
                for iid in tier_agents:
                    dag[iid] = list(prev_agents)

        return dag

    def _clone_agent_for_instance(
        self,
        template: Agent,
        instance_id: str,
        specialisation: str,
        assignment: str,
        verification: str,
        extra_tools: list[str],
    ) -> Agent:
        """Create a new Agent instance from a template with custom identity.

        Each clone gets:
        - A unique ID (derived from instance_id)
        - A unique instance_id
        - A customised name (e.g. "Backend Engineer (API)")
        - An augmented system prompt with its specific assignment
        - Verification requirements injected into the prompt
        """
        agent = deepcopy(template)
        agent.id = uuid5(NAMESPACE_DNS, instance_id)
        agent.instance_id = instance_id  # type: ignore[attr-defined]

        # Build a human-readable name
        spec_label = specialisation.replace("-", " ").replace("_", " ").title()
        if specialisation and specialisation != "general":
            agent.name = f"{template.name} ({spec_label})"
        else:
            agent.name = template.name

        # Augment system prompt with specific assignment and verification
        assignment_section = f"""

## YOUR SPECIFIC ASSIGNMENT FOR THIS TASK
Instance ID: {instance_id}
Specialisation: {specialisation}

{assignment}

## VERIFICATION REQUIREMENT
Your work is NOT done until you have verified it:
{verification}

If you cannot verify (e.g. tests don't exist yet), document exactly what
you tried and what the outcome was. "Assuming it works" is NOT acceptable.
"""
        agent.system_prompt = agent.system_prompt + assignment_section

        # Add extra tools if specified in the staffing plan
        if extra_tools:
            existing = set(agent.tools)
            for tool in extra_tools:
                if tool not in existing:
                    agent.tools.append(tool)

        return agent

    def _compute_parallel_groups(
        self,
        instance_ids: list[str],
        dag: dict[str, list[str]],
    ) -> list[list[str]]:
        """Compute execution waves from a DAG."""
        completed: set[str] = set()
        remaining = set(instance_ids)
        groups: list[list[str]] = []

        while remaining:
            ready = [
                iid for iid in remaining
                if all(d in completed for d in dag.get(iid, []))
            ]
            if not ready:
                # Deadlock — break by taking first remaining
                ready = [sorted(remaining)[0]]
            groups.append(ready)
            completed.update(ready)
            remaining -= set(ready)

        return groups

    # ── Legacy: hardcoded pipeline (backward compatibility) ────────────

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
        """Legacy assembly — hardcoded pipeline from task type.

        Kept for backward compatibility and as fallback when no
        staffing plan is available.
        """
        ideal_roles = list(self.TASK_PIPELINES.get(task_type.value, ["coder", "reviewer"]))

        if complexity in (TaskComplexity.HIGH, TaskComplexity.CRITICAL):
            if "lead" not in ideal_roles:
                ideal_roles = ["lead"] + ideal_roles
            if complexity == TaskComplexity.CRITICAL and "security" not in ideal_roles:
                ideal_roles.append("security")

        agent_by_role: dict[str, Agent] = {a.role: a for a in available_agents if a.is_active}
        pipeline_agents: list[Agent] = []

        for role in ideal_roles:
            if role in agent_by_role:
                agent = deepcopy(agent_by_role[role])
                agent.instance_id = f"{role}-1"  # type: ignore[attr-defined]
                pipeline_agents.append(agent)

        if not pipeline_agents:
            pipeline_agents = sorted(
                [deepcopy(a) for a in available_agents if a.is_active],
                key=lambda a: a.pipeline_order,
            )
            for a in pipeline_agents:
                a.instance_id = f"{a.role}-1"  # type: ignore[attr-defined]

        pipeline_agents.sort(key=lambda a: a.pipeline_order)

        gates_after = [a.instance_id for a in pipeline_agents if a.role in CODE_PRODUCING_ROLES]

        return PipelineConfig(agents=pipeline_agents, gates_after=gates_after)
