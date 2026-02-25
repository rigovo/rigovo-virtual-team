"""Conditional edge functions for graph routing decisions."""

from __future__ import annotations

from rigovo.application.graph.state import TaskState


def check_approval(state: TaskState) -> str:
    """Route based on user approval status."""
    status = state.get("approval_status", "pending")
    if status == "rejected":
        return "rejected"
    # approved or pending (pending = auto-approved, handler already ran)
    return "approved"


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


# Roles that can run in parallel (no inter-dependency)
_PARALLELIZABLE_ROLES = {"reviewer", "qa", "security", "docs"}


def check_pipeline_complete(state: TaskState) -> str:
    """
    Route after completing an agent — check if remaining agents can run
    in parallel, sequentially, or if the pipeline is done.
    """
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    current_index = state.get("current_agent_index", 0)

    if current_index + 1 >= len(pipeline_order):
        return "pipeline_done"

    # Check if ALL remaining agents are parallelizable
    remaining_roles = pipeline_order[current_index + 1:]
    if len(remaining_roles) >= 2 and all(r in _PARALLELIZABLE_ROLES for r in remaining_roles):
        return "parallel_fan_out"

    return "more_agents"


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


# ---------------------------------------------------------------------------
# Agent debate protocol — reviewer ↔ coder feedback loop
# ---------------------------------------------------------------------------

_CHANGES_REQUESTED_MARKERS = [
    "CHANGES_REQUESTED",
    "changes requested",
    "needs revision",
    "BLOCKED",
]

DEFAULT_MAX_DEBATE_ROUNDS = 2


def check_debate_needed(state: TaskState) -> str:
    """
    After parallel agents complete, check if reviewer requested changes.

    If CHANGES_REQUESTED found in reviewer output AND debate rounds remain,
    route coder back for another pass with reviewer feedback.

    Returns:
        "debate_needed" — coder must address reviewer feedback
        "debate_done"   — all agents approved, proceed to commit
    """
    reviewer_output = state.get("agent_outputs", {}).get("reviewer", {})
    reviewer_summary = reviewer_output.get("summary", "")

    debate_round = state.get("debate_round", 0)
    max_rounds = state.get("max_debate_rounds", DEFAULT_MAX_DEBATE_ROUNDS)

    # Check if reviewer requested changes
    needs_changes = any(
        marker in reviewer_summary for marker in _CHANGES_REQUESTED_MARKERS
    )

    if needs_changes and debate_round < max_rounds:
        return "debate_needed"

    return "debate_done"


def prepare_debate_round(state: TaskState) -> dict:
    """
    Prepare state for coder re-execution with reviewer feedback.

    Resets the pipeline to coder, injects reviewer feedback as a fix packet,
    and increments the debate round counter.
    """
    reviewer_output = state.get("agent_outputs", {}).get("reviewer", {})
    reviewer_summary = reviewer_output.get("summary", "")
    debate_round = state.get("debate_round", 0) + 1

    # Find coder's index in pipeline
    pipeline_order = state.get("team_config", {}).get("pipeline_order", [])
    coder_index = 0
    for i, role in enumerate(pipeline_order):
        if role == "coder":
            coder_index = i
            break

    events = list(state.get("events", []))
    events.append({
        "type": "debate_round",
        "round": debate_round,
        "reviewer_feedback": reviewer_summary[:200],
    })

    return {
        "current_agent_index": coder_index,
        "current_agent_role": "coder",
        "debate_round": debate_round,
        "reviewer_feedback": reviewer_summary,
        # Inject reviewer feedback as a fix packet so coder sees it
        "fix_packets": [
            f"[REVIEWER FEEDBACK — Round {debate_round}]\n"
            f"The code reviewer has requested changes. "
            f"Address the following feedback:\n\n{reviewer_summary}"
        ],
        "retry_count": 0,
        "events": events,
    }
