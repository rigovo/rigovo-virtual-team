"""Approval nodes — human-in-the-loop via LangGraph interrupt()."""

from __future__ import annotations

import asyncio
from typing import Any

from rigovo.application.graph.state import TaskState


async def plan_approval_node(state: TaskState) -> dict[str, Any]:
    """
    Pause the graph for user approval of the plan.

    In a LangGraph context this uses interrupt() to checkpoint state
    and wait for user input. For now, we model the approval interface.
    The actual interrupt() call happens in the graph builder when
    langgraph is available.
    """
    await asyncio.sleep(0)
    team_config = state.get("team_config", {})
    classification = state.get("classification", {})

    approval_summary = {
        "checkpoint": "plan_ready",
        "task_type": classification.get("task_type"),
        "complexity": classification.get("complexity"),
        "team": team_config.get("team_name"),
        "pipeline": team_config.get("pipeline_order", []),
        "agent_count": len(team_config.get("agents", {})),
    }

    return {
        "status": "awaiting_plan_approval",
        "approval_status": "pending",
        "events": state.get("events", []) + [{
            "type": "approval_requested",
            "checkpoint": "plan_ready",
            "summary": approval_summary,
        }],
    }


async def commit_approval_node(state: TaskState) -> dict[str, Any]:
    """
    Pause the graph for user approval before finalising.

    Shows the user what was done — all agent outputs, gate results,
    files changed — and asks for confirmation to proceed.
    """
    await asyncio.sleep(0)
    agent_outputs = state.get("agent_outputs", {})

    approval_summary = {
        "checkpoint": "commit_ready",
        "agents_completed": list(agent_outputs.keys()),
        "gate_passed": state.get("gate_results", {}).get("passed", False),
        "total_cost": sum(
            o.get("cost", 0.0) for o in agent_outputs.values()
        ),
        "files_changed": [
            f
            for o in agent_outputs.values()
            for f in o.get("files_changed", [])
        ],
    }

    return {
        "status": "awaiting_commit_approval",
        "approval_status": "pending",
        "events": state.get("events", []) + [{
            "type": "approval_requested",
            "checkpoint": "commit_ready",
            "summary": approval_summary,
        }],
    }
