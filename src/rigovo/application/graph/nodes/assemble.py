"""Assemble node — builds the agent execution pipeline from team config."""

from __future__ import annotations

import asyncio
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.task import TaskComplexity, TaskType
from rigovo.domain.services.team_assembler import TeamAssemblerService


async def assemble_node(
    state: TaskState,
    agents: list[Agent],
    assembler: TeamAssemblerService | None = None,
) -> dict[str, Any]:
    """Assemble the execution pipeline based on task classification and team agents."""
    await asyncio.sleep(0)
    assembler = assembler or TeamAssemblerService()
    classification = state.get("classification", {})

    task_type = TaskType(classification.get("task_type", "feature"))
    complexity = TaskComplexity(classification.get("complexity", "medium"))

    pipeline = assembler.assemble(agents, task_type, complexity)

    # Build agent configs dict for the state
    agent_configs: dict[str, dict[str, Any]] = {}
    pipeline_order: list[str] = []

    for agent in pipeline.agents:
        agent_configs[agent.role] = {
            "id": str(agent.id),
            "name": agent.name,
            "role": agent.role,
            "system_prompt": agent.system_prompt,
            "llm_model": agent.llm_model,
            "tools": agent.tools,
            "depends_on": list(getattr(agent, "depends_on", [])),
            "enrichment_context": agent.enrichment.to_prompt_section(),
            "input_contract": getattr(agent, "input_contract", {}) or {},
            "output_contract": getattr(agent, "output_contract", {}) or {},
        }
        pipeline_order.append(agent.role)

    # Build DAG dependencies.
    # Default behavior remains linear pipeline when depends_on isn't configured.
    execution_dag: dict[str, list[str]] = {}
    for idx, role in enumerate(pipeline_order):
        explicit = agent_configs.get(role, {}).get("depends_on", []) or []
        deps = [d for d in explicit if d in pipeline_order and d != role]
        if not deps and idx > 0:
            deps = [pipeline_order[idx - 1]]
        execution_dag[role] = deps

    ready_roles = [r for r in pipeline_order if not execution_dag.get(r, [])]
    first_role = ready_roles[0] if ready_roles else (pipeline_order[0] if pipeline_order else "")

    team_config = {
        **state.get("team_config", {}),
        "agents": agent_configs,
        "pipeline_order": pipeline_order,
        "execution_dag": execution_dag,
        "gates_after": pipeline.gates_after,
    }

    return {
        "team_config": team_config,
        "current_agent_index": 0,
        "current_agent_role": first_role,
        "ready_roles": ready_roles,
        "completed_roles": [],
        "blocked_roles": [],
        "agent_outputs": {},
        "agent_messages": state.get("agent_messages", []),
        "retry_count": 0,
        "status": "assembled",
        "events": state.get("events", [])
        + [
            {
                "type": "pipeline_assembled",
                "agent_count": pipeline.agent_count,
                "roles": pipeline.roles,
                "gates_after": pipeline.gates_after,
                # Agent → LLM mapping for transparency (shown in TUI)
                "agent_models": {
                    role: config.get("llm_model", "unknown")
                    for role, config in agent_configs.items()
                },
            },
        ],
    }
