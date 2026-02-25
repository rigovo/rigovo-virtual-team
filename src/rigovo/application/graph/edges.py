"""Conditional edge functions for graph routing decisions."""

from __future__ import annotations

from rigovo.application.graph.state import TaskState


def check_approval(state: TaskState) -> str:
    """Route based on user approval status."""
    status = state.get("approval_status", "pending")
    if status == "approved":
        return "approved"
    if status == "rejected":
        return "rejected"
    # If still pending, stay at approval (shouldn't happen with interrupt)
    return "approved"  # Default to approved for non-interactive mode


def check_gates_and_route(state: TaskState) -> str:
    """
    Route after quality gate check.

    Three outcomes:
    - pass: gates passed → move to next agent or finish
    - fix_loop: gates failed, retries remaining → back to coder
    - max_retries: gates failed, no retries left → fail
    """
    gate_results = state.get("gate_results", {})
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 5)

    if gate_results.get("passed", True) or gate_results.get("status") == "skipped":
        return "pass_next_agent"

    if retry_count < max_retries:
        return "fail_fix_loop"

    return "fail_max_retries"


def check_pipeline_complete(state: TaskState) -> str:
    """
    Route after completing an agent — is there another agent in the pipeline?
    """
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    current_index = state.get("current_agent_index", 0)

    if current_index + 1 < len(pipeline_order):
        return "more_agents"

    return "pipeline_done"


def advance_to_next_agent(state: TaskState) -> dict:
    """
    Helper: advance the pipeline index to the next agent.

    Called as a node or inline when routing to the next agent.
    """
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    next_index = state.get("current_agent_index", 0) + 1

    next_role = pipeline_order[next_index] if next_index < len(pipeline_order) else ""

    return {
        "current_agent_index": next_index,
        "current_agent_role": next_role,
        "fix_packets": [],  # Clear fix packets for new agent
        "retry_count": 0,   # Reset retries for new agent
    }
