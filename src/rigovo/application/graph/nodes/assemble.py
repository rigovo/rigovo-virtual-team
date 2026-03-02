"""Assemble node — builds the agent execution pipeline from the staffing plan.

Primary path: Uses the Master Agent's ``staffing_plan`` (from classify node)
to create per-instance agents with custom assignments, dependency DAGs, and
parallel execution groups.

Fallback: If no staffing plan exists (legacy tasks), falls back to the old
static TASK_PIPELINES lookup.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.task import TaskComplexity, TaskType
from rigovo.domain.services.team_assembler import TeamAssemblerService

logger = logging.getLogger(__name__)


async def assemble_node(
    state: TaskState,
    agents: list[Agent],
    assembler: TeamAssemblerService | None = None,
) -> dict[str, Any]:
    """Assemble the execution pipeline.

    If a ``staffing_plan`` is present (set by the Master Agent in classify),
    uses it to build per-instance agents with the exact team composition the
    SME requested. Otherwise falls back to legacy static assembly.
    """
    await asyncio.sleep(0)
    assembler = assembler or TeamAssemblerService()
    classification = state.get("classification", {})
    staffing_plan = state.get("staffing_plan")

    # ── Intent-aware agent cap ────────────────────────────────────────
    # If the intent gate detected a brainstorm/research task, trim the
    # staffing plan to avoid spawning 12 agents for a thinking task.
    intent_profile = state.get("intent_profile") or {}
    max_agents = int(intent_profile.get("max_agents", 0))
    if max_agents > 0 and staffing_plan and isinstance(staffing_plan, dict):
        plan_agents = staffing_plan.get("agents", [])
        if len(plan_agents) > max_agents:
            logger.info(
                "Intent cap: trimming team from %d to %d agents (intent=%s)",
                len(plan_agents),
                max_agents,
                intent_profile.get("intent", ""),
            )
            # Keep the first N agents by pipeline priority (planner first)
            staffing_plan = {**staffing_plan, "agents": plan_agents[:max_agents]}

    # ── Primary path: StaffingPlan-driven assembly ────────────────────
    if staffing_plan and isinstance(staffing_plan, dict) and staffing_plan.get("agents"):
        pipeline = assembler.assemble_from_plan(staffing_plan, agents)
    else:
        # ── Fallback: legacy static assembly ──────────────────────────
        task_type = TaskType(classification.get("task_type", "feature"))
        complexity = TaskComplexity(classification.get("complexity", "medium"))
        pipeline = assembler.assemble(agents, task_type, complexity)

    # Build agent configs dict for the state
    agent_configs: dict[str, dict[str, Any]] = {}
    pipeline_order: list[str] = []

    for agent in pipeline.agents:
        instance_id = getattr(agent, "instance_id", agent.role)
        agent_configs[instance_id] = {
            "id": str(agent.id),
            "name": agent.name,
            "role": agent.role,
            "instance_id": instance_id,
            "system_prompt": agent.system_prompt,
            "llm_model": agent.llm_model,
            "tools": agent.tools,
            "depends_on": list(getattr(agent, "depends_on", [])),
            "enrichment_context": agent.enrichment.to_prompt_section(),
            "input_contract": getattr(agent, "input_contract", {}) or {},
            "output_contract": getattr(agent, "output_contract", {}) or {},
            # Instance-specific metadata from staffing plan
            "assignment": pipeline.instance_assignments.get(instance_id, ""),
            "verification": pipeline.instance_verifications.get(instance_id, ""),
            "specialisation": pipeline.instance_specialisations.get(instance_id, ""),
        }
        pipeline_order.append(instance_id)

    # Build DAG — prefer staffing plan DAG, fall back to linear chain
    execution_dag: dict[str, list[str]] = {}
    if pipeline.execution_dag:
        execution_dag = pipeline.execution_dag
    else:
        for idx, instance_id in enumerate(pipeline_order):
            explicit = agent_configs.get(instance_id, {}).get("depends_on", []) or []
            deps = [d for d in explicit if d in pipeline_order and d != instance_id]
            if not deps and idx > 0:
                deps = [pipeline_order[idx - 1]]
            execution_dag[instance_id] = deps

    ready_roles = [r for r in pipeline_order if not execution_dag.get(r, [])]
    first_role = ready_roles[0] if ready_roles else (pipeline_order[0] if pipeline_order else "")

    team_config = {
        **state.get("team_config", {}),
        "agents": agent_configs,
        "pipeline_order": pipeline_order,
        "execution_dag": execution_dag,
        "gates_after": pipeline.gates_after,
        "parallel_groups": pipeline.parallel_groups if pipeline.parallel_groups else [],
    }

    # Build the event with rich info about the assembled team
    agent_summaries = []
    for iid in pipeline_order:
        cfg = agent_configs[iid]
        agent_summaries.append(
            {
                "instance_id": iid,
                "role": cfg["role"],
                "name": cfg["name"],
                "specialisation": cfg.get("specialisation", ""),
                "assignment": (cfg.get("assignment", "") or "")[:200],
            }
        )

    return {
        "team_config": team_config,
        "current_agent_index": 0,
        "current_agent_role": first_role,
        "current_instance_id": first_role,
        "ready_roles": ready_roles,
        "completed_roles": [],
        "blocked_roles": [],
        "agent_outputs": {},
        "agent_messages": state.get("agent_messages", []),
        "feedback_loops": state.get("feedback_loops", []),
        "active_feedback": {},
        "retry_count": 0,
        "status": "assembled",
        "events": state.get("events", [])
        + [
            {
                "type": "pipeline_assembled",
                "agent_count": pipeline.agent_count,
                "roles": [a.role for a in pipeline.agents],
                "instance_ids": pipeline_order,
                "gates_after": pipeline.gates_after,
                "parallel_groups": pipeline.parallel_groups if pipeline.parallel_groups else [],
                "agent_models": {
                    iid: config.get("llm_model", "unknown") for iid, config in agent_configs.items()
                },
                "agent_summaries": agent_summaries,
            },
        ],
    }
