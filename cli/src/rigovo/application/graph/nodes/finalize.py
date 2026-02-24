"""Finalize node — wraps up the task, aggregates results."""

from __future__ import annotations

from typing import Any

from rigovo.application.graph.state import TaskState


async def finalize_node(state: TaskState) -> dict[str, Any]:
    """
    Final node — aggregates results and determines final status.

    This node runs regardless of whether the task succeeded, failed,
    or was rejected. It ensures clean state for audit and reporting.
    """
    agent_outputs = state.get("agent_outputs", {})
    approval_status = state.get("approval_status", "")
    gate_results = state.get("gate_results", {})

    # Aggregate totals
    total_tokens = sum(o.get("tokens", 0) for o in agent_outputs.values())
    total_cost = sum(o.get("cost", 0.0) for o in agent_outputs.values())
    total_duration = sum(o.get("duration_ms", 0) for o in agent_outputs.values())
    files_changed = list({
        f
        for o in agent_outputs.values()
        for f in o.get("files_changed", [])
    })

    # Determine final status
    if approval_status == "rejected":
        final_status = "rejected"
    elif state.get("error"):
        final_status = "failed"
    elif not gate_results.get("passed", True) and state.get("retry_count", 0) >= state.get("max_retries", 3):
        final_status = "failed"
    else:
        final_status = "completed"

    return {
        "status": final_status,
        "events": state.get("events", []) + [{
            "type": "task_finalized",
            "status": final_status,
            "agents_run": list(agent_outputs.keys()),
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 6),
            "total_duration_ms": total_duration,
            "files_changed": files_changed,
            "retries": state.get("retry_count", 0),
            "memories_stored": len(state.get("memories_to_store", [])),
        }],
    }
