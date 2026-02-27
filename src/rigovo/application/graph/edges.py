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

    if _should_trigger_replan(state):
        return "trigger_replan"

    if retry_count < max_retries:
        return "fail_fix_loop"

    return "fail_max_retries"


def _should_trigger_replan(state: TaskState) -> bool:
    """Policy gate for when a failed step should trigger global replanning."""
    policy = state.get("replan_policy", {}) or {}
    if not isinstance(policy, dict) or not policy.get("enabled", False):
        return False

    replan_count = int(state.get("replan_count", 0) or 0)
    max_replans = int(policy.get("max_replans_per_task", 1) or 1)
    if replan_count >= max_replans:
        return False

    gate_results = state.get("gate_results", {}) or {}

    if bool(policy.get("trigger_contract_failures", True)):
        if gate_results.get("reason") == "contract_failed" or bool(state.get("contract_stage")):
            return True

    retry_threshold = int(policy.get("trigger_retry_count", 3) or 3)
    if int(state.get("retry_count", 0) or 0) >= retry_threshold:
        return True

    violation_threshold = int(policy.get("trigger_gate_violation_count", 5) or 5)
    if int(gate_results.get("violation_count", 0) or 0) >= violation_threshold:
        return True

    return False


def check_replan_result(state: TaskState) -> str:
    """Route after replanning step."""
    if state.get("status") == "replan_failed":
        return "replan_failed"
    return "replan_continue"


# Roles that can run in parallel (no inter-dependency)
_PARALLELIZABLE_ROLES = {"reviewer", "qa", "security", "docs"}


def check_pipeline_complete(state: TaskState) -> str:
    """
    Route after completing an agent — check if remaining agents can run
    in parallel, sequentially, or if the pipeline is done.
    """
    if state.get("status") == "pipeline_failed_dependency":
        return "pipeline_failed"

    # DAG-aware path
    if "ready_roles" in state:
        ready_roles = state.get("ready_roles", [])
        if not ready_roles:
            return "pipeline_done"

        if len(ready_roles) >= 2 and all(r in _PARALLELIZABLE_ROLES for r in ready_roles):
            return "parallel_fan_out"

        return "more_agents"

    # Backward-compatible linear path
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    current_index = state.get("current_agent_index", 0)
    if current_index + 1 >= len(pipeline_order):
        return "pipeline_done"
    remaining_roles = pipeline_order[current_index + 1 :]
    if len(remaining_roles) >= 2 and all(r in _PARALLELIZABLE_ROLES for r in remaining_roles):
        return "parallel_fan_out"

    return "more_agents"


def check_parallel_postprocess(state: TaskState) -> str:
    """
    Route after a parallel wave.

    Keep DAG scheduling semantics first; only trigger debate when the
    pipeline is otherwise done and reviewer requested changes.
    """
    pipeline_route = check_pipeline_complete(state)
    if pipeline_route != "pipeline_done":
        return pipeline_route
    if check_debate_needed(state) == "debate_needed":
        return "debate_needed"
    return "pipeline_done"


def _compute_blocked_roles(
    execution_dag: dict[str, list[str]],
    completed: set[str],
    blocked: set[str],
) -> set[str]:
    """Compute blocked roles caused by unsatisfied blocked dependencies."""
    blocked_out = set(blocked)
    changed = True
    while changed:
        changed = False
        for role, deps in execution_dag.items():
            if role in completed or role in blocked_out:
                continue
            if any(dep in blocked_out for dep in deps):
                blocked_out.add(role)
                changed = True
    return blocked_out


def advance_to_next_agent(state: TaskState) -> dict:
    """
    Helper: advance the pipeline index to the next agent.

    Called as a node or inline when routing to the next agent.
    """
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    execution_dag = team_config.get("execution_dag", {})

    # Fallback compatibility: no DAG configured, use linear progression.
    if not execution_dag:
        next_index = state.get("current_agent_index", 0) + 1
        next_role = pipeline_order[next_index] if next_index < len(pipeline_order) else ""
        return {
            "current_agent_index": next_index,
            "current_agent_role": next_role,
            "fix_packets": [],  # Clear fix packets for new agent
            "retry_count": 0,  # Reset retries for new agent
        }

    current_role = state.get("current_agent_role", "")
    completed_roles = set(state.get("completed_roles", []))
    blocked_roles = set(state.get("blocked_roles", []))
    if current_role and current_role not in blocked_roles:
        completed_roles.add(current_role)

    # Debate mode: after coder retry, force reviewer re-validation before commit.
    debate_target_role = str(state.get("debate_target_role", "") or "").strip()
    if debate_target_role and current_role == "coder" and debate_target_role in pipeline_order:
        next_index = pipeline_order.index(debate_target_role)
        events = list(state.get("events", []))
        events.append(
            {
                "type": "debate_reviewer_rerun",
                "target_role": debate_target_role,
            }
        )
        return {
            "current_agent_index": next_index,
            "current_agent_role": debate_target_role,
            "ready_roles": [debate_target_role],
            "completed_roles": sorted(completed_roles),
            "blocked_roles": sorted(blocked_roles),
            "fix_packets": [],
            "retry_count": 0,
            "status": "routing_next_agent",
            "error": "",
            "events": events,
        }

    blocked_roles = _compute_blocked_roles(execution_dag, completed_roles, blocked_roles)

    ready_roles: list[str] = []
    for role in pipeline_order:
        if role in completed_roles or role in blocked_roles:
            continue
        deps = execution_dag.get(role, [])
        if all(dep in completed_roles for dep in deps):
            ready_roles.append(role)

    events = list(state.get("events", []))
    status = "routing_next_agent"
    error = ""
    remaining = [r for r in pipeline_order if r not in completed_roles and r not in blocked_roles]
    if remaining and not ready_roles:
        status = "pipeline_failed_dependency"
        error = "No executable DAG nodes remain; unresolved dependencies for roles: " + ", ".join(
            remaining
        )
        events.append(
            {
                "type": "dag_blocked",
                "remaining_roles": remaining,
                "completed_roles": sorted(completed_roles),
                "blocked_roles": sorted(blocked_roles),
            }
        )

    next_role = ready_roles[0] if ready_roles else ""
    next_index = (
        pipeline_order.index(next_role) if next_role in pipeline_order else len(pipeline_order)
    )

    return {
        "current_agent_index": next_index,
        "current_agent_role": next_role,
        "ready_roles": ready_roles,
        "completed_roles": sorted(completed_roles),
        "blocked_roles": sorted(blocked_roles),
        "debate_target_role": "" if current_role == debate_target_role else debate_target_role,
        "fix_packets": [],
        "retry_count": 0,
        "status": status,
        "error": error,
        "events": events,
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
    needs_changes = any(marker in reviewer_summary for marker in _CHANGES_REQUESTED_MARKERS)

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

    completed_roles = [r for r in state.get("completed_roles", []) if r != "reviewer"]
    ready_roles = [r for r in state.get("ready_roles", []) if r != "reviewer"]
    agent_outputs = dict(state.get("agent_outputs", {}))
    # Reviewer output must be regenerated after coder updates.
    agent_outputs.pop("reviewer", None)

    events = list(state.get("events", []))
    events.append(
        {
            "type": "debate_round",
            "round": debate_round,
            "reviewer_feedback": reviewer_summary[:200],
        }
    )

    return {
        "current_agent_index": coder_index,
        "current_agent_role": "coder",
        "debate_round": debate_round,
        "debate_target_role": "reviewer",
        "reviewer_feedback": reviewer_summary,
        "completed_roles": completed_roles,
        "ready_roles": ready_roles,
        "agent_outputs": agent_outputs,
        # Inject reviewer feedback as a fix packet so coder sees it
        "fix_packets": [
            f"[REVIEWER FEEDBACK — Round {debate_round}]\n"
            f"The code reviewer has requested changes. "
            f"Address the following feedback:\n\n{reviewer_summary}"
        ],
        "retry_count": 0,
        "events": events,
    }
