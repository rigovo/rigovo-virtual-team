"""Assemble node — builds the agent execution pipeline from team config."""

from __future__ import annotations

from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.task import TaskType, TaskComplexity
from rigovo.domain.entities.agent import Agent
from rigovo.domain.services.team_assembler import TeamAssemblerService


async def assemble_node(
    state: TaskState,
    agents: list[Agent],
    assembler: TeamAssemblerService | None = None,
) -> dict[str, Any]:
    """Assemble the execution pipeline based on task classification and team agents."""
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
            "enrichment_context": agent.enrichment.to_prompt_section(),
        }
        pipeline_order.append(agent.role)

    team_config = {
        **state.get("team_config", {}),
        "agents": agent_configs,
        "pipeline_order": pipeline_order,
        "gates_after": pipeline.gates_after,
    }

    return {
        "team_config": team_config,
        "current_agent_index": 0,
        "current_agent_role": pipeline_order[0] if pipeline_order else "",
        "agent_outputs": {},
        "retry_count": 0,
        "status": "assembled",
        "events": state.get("events", []) + [{
            "type": "pipeline_assembled",
            "agent_count": pipeline.agent_count,
            "roles": pipeline.roles,
            "gates_after": pipeline.gates_after,
        }],
    }
