"""Conditional edge functions for graph routing decisions.

Instance-ID aware: pipeline_order now contains instance_ids (e.g.
"backend-engineer-1", "qa-unit-1") not bare role names. All routing
logic resolves the base role from ``team_config["agents"][instance_id]["role"]``
when it needs role-level semantics (parallelization, debate eligibility).

The debate protocol is now **generic**: any reviewer/QA instance can push
back to any coder instance. The feedback loop tracks which specific
instance_ids are involved.
"""

from __future__ import annotations

from typing import Any

from rigovo.application.graph.state import TaskState


# ── Helpers ─────────────────────────────────────────────────────────────

def _get_role_for_instance(state: TaskState, instance_id: str) -> str:
    """Resolve the base role (coder, reviewer, qa, …) for an instance_id."""
    agents = state.get("team_config", {}).get("agents", {})
    agent_cfg = agents.get(instance_id, {})
    return agent_cfg.get("role", instance_id.split("-")[0] if "-" in instance_id else instance_id)


def _get_instances_by_role(state: TaskState, role: str) -> list[str]:
    """Return all instance_ids that map to a given role."""
    agents = state.get("team_config", {}).get("agents", {})
    return [
        iid for iid, cfg in agents.items()
        if cfg.get("role") == role
    ]


# ── Approval ────────────────────────────────────────────────────────────

def check_approval(state: TaskState) -> str:
    """Route based on user approval status."""
    status = state.get("approval_status", "pending")
    if status == "rejected":
        return "rejected"
    return "approved"


# ── Quality gate routing ────────────────────────────────────────────────

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


# ── Pipeline completion routing ─────────────────────────────────────────

# Roles that can run in parallel (no inter-dependency by nature)
_PARALLELIZABLE_ROLES = {"reviewer", "qa", "security", "docs"}


def check_pipeline_complete(state: TaskState) -> str:
    """
    Route after completing an agent — check if remaining agents can run
    in parallel, sequentially, or if the pipeline is done.

    Instance-ID aware: ready_roles/pipeline_order contain instance_ids.
    We resolve the base role to check parallelizability.
    """
    if state.get("status") == "pipeline_failed_dependency":
        return "pipeline_failed"

    # DAG-aware path (primary)
    if "ready_roles" in state:
        ready_roles = state.get("ready_roles", [])
        if not ready_roles:
            return "pipeline_done"

        # Check if all ready instances are parallelizable by role
        if len(ready_roles) >= 2:
            all_parallelizable = all(
                _get_role_for_instance(state, iid) in _PARALLELIZABLE_ROLES
                for iid in ready_roles
            )
            if all_parallelizable:
                return "parallel_fan_out"

        return "more_agents"

    # Backward-compatible linear path
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    current_index = state.get("current_agent_index", 0)
    if current_index + 1 >= len(pipeline_order):
        return "pipeline_done"
    remaining = pipeline_order[current_index + 1:]
    if len(remaining) >= 2 and all(
        _get_role_for_instance(state, iid) in _PARALLELIZABLE_ROLES
        for iid in remaining
    ):
        return "parallel_fan_out"

    return "more_agents"


def check_parallel_postprocess(state: TaskState) -> str:
    """
    Route after a parallel wave.

    Keep DAG scheduling semantics first; only trigger debate when the
    pipeline is otherwise done and a reviewer/QA requested changes.
    """
    pipeline_route = check_pipeline_complete(state)
    if pipeline_route != "pipeline_done":
        return pipeline_route
    if check_debate_needed(state) == "debate_needed":
        return "debate_needed"
    return "pipeline_done"


# ── DAG helpers ─────────────────────────────────────────────────────────

def _compute_blocked_roles(
    execution_dag: dict[str, list[str]],
    completed: set[str],
    blocked: set[str],
) -> set[str]:
    """Compute blocked instances caused by unsatisfied blocked dependencies."""
    blocked_out = set(blocked)
    changed = True
    while changed:
        changed = False
        for instance_id, deps in execution_dag.items():
            if instance_id in completed or instance_id in blocked_out:
                continue
            if any(dep in blocked_out for dep in deps):
                blocked_out.add(instance_id)
                changed = True
    return blocked_out


# ── Advance pipeline ────────────────────────────────────────────────────

def advance_to_next_agent(state: TaskState) -> dict:
    """
    Advance the pipeline to the next agent instance.

    Instance-ID aware: pipeline_order contains instance_ids.
    Sets both ``current_agent_role`` (the base role for tool resolution)
    and ``current_instance_id`` (the specific instance for config lookup).
    """
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    execution_dag = team_config.get("execution_dag", {})
    agents_cfg = team_config.get("agents", {})

    # Fallback compatibility: no DAG configured, use linear progression.
    if not execution_dag:
        next_index = state.get("current_agent_index", 0) + 1
        next_instance = pipeline_order[next_index] if next_index < len(pipeline_order) else ""
        next_role = agents_cfg.get(next_instance, {}).get("role", next_instance)
        return {
            "current_agent_index": next_index,
            "current_agent_role": next_instance,  # Backward compat: config keyed by instance_id
            "current_instance_id": next_instance,
            "fix_packets": [],
            "retry_count": 0,
        }

    # Current instance just finished
    current_instance = state.get("current_instance_id", "") or state.get("current_agent_role", "")
    completed_roles = set(state.get("completed_roles", []))
    blocked_roles = set(state.get("blocked_roles", []))
    if current_instance and current_instance not in blocked_roles:
        completed_roles.add(current_instance)

    # ── Feedback loop / debate: after coder fix, force reviewer/QA re-run ──
    debate_target = str(state.get("debate_target_role", "") or "").strip()
    current_role = _get_role_for_instance(state, current_instance)
    if debate_target and current_role == "coder" and debate_target in pipeline_order:
        next_index = pipeline_order.index(debate_target)
        target_role = agents_cfg.get(debate_target, {}).get("role", debate_target)
        events = list(state.get("events", []))
        events.append(
            {
                "type": "debate_reviewer_rerun",
                "target_instance": debate_target,
                "target_role": target_role,
            }
        )
        return {
            "current_agent_index": next_index,
            "current_agent_role": debate_target,
            "current_instance_id": debate_target,
            "ready_roles": [debate_target],
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
    for instance_id in pipeline_order:
        if instance_id in completed_roles or instance_id in blocked_roles:
            continue
        deps = execution_dag.get(instance_id, [])
        if all(dep in completed_roles for dep in deps):
            ready_roles.append(instance_id)

    events = list(state.get("events", []))
    status = "routing_next_agent"
    error = ""
    remaining = [
        iid for iid in pipeline_order
        if iid not in completed_roles and iid not in blocked_roles
    ]
    if remaining and not ready_roles:
        status = "pipeline_failed_dependency"
        error = (
            "No executable DAG nodes remain; unresolved dependencies for: "
            + ", ".join(remaining)
        )
        events.append(
            {
                "type": "dag_blocked",
                "remaining_instances": remaining,
                "completed_instances": sorted(completed_roles),
                "blocked_instances": sorted(blocked_roles),
            }
        )

    next_instance = ready_roles[0] if ready_roles else ""
    next_index = (
        pipeline_order.index(next_instance)
        if next_instance in pipeline_order
        else len(pipeline_order)
    )

    return {
        "current_agent_index": next_index,
        "current_agent_role": next_instance,  # Config lookup key = instance_id
        "current_instance_id": next_instance,
        "ready_roles": ready_roles,
        "completed_roles": sorted(completed_roles),
        "blocked_roles": sorted(blocked_roles),
        "debate_target_role": (
            "" if current_instance == debate_target else debate_target
        ),
        "fix_packets": [],
        "retry_count": 0,
        "status": status,
        "error": error,
        "events": events,
    }


# ── Generic debate / feedback protocol ──────────────────────────────────
#
# The debate protocol is now generic:
# - ANY reviewer instance can push back to ANY coder instance
# - ANY QA instance can raise issues for ANY coder instance
# - The feedback loop tracks specific instance_ids, not bare roles
#
# Feedback sources: reviewer, qa
# Feedback targets: coder (any instance with role=coder)
#
# The Team Lead (state) knows who worked on what, so feedback is routed
# to the right coder instance based on the dependency DAG.

_CHANGES_REQUESTED_MARKERS = [
    "CHANGES_REQUESTED",
    "changes requested",
    "needs revision",
    "BLOCKED",
    "ISSUES_FOUND",
    "issues found",
    "FAILED",
    "tests failed",
]

_FEEDBACK_SOURCE_ROLES = {"reviewer", "qa"}

DEFAULT_MAX_DEBATE_ROUNDS = 2


def _find_feedback_source(state: TaskState) -> tuple[str, str, str]:
    """Find the first reviewer/QA instance that requested changes.

    Returns:
        (source_instance_id, source_role, feedback_summary) or ("", "", "")
    """
    agent_outputs = state.get("agent_outputs", {})
    agents_cfg = state.get("team_config", {}).get("agents", {})

    for instance_id, output in agent_outputs.items():
        # Resolve role: from agent config (new style) or infer from key (backward compat)
        role = agents_cfg.get(instance_id, {}).get("role", "")
        if not role:
            # Backward compat: key might be the bare role name itself
            role = instance_id
        if role not in _FEEDBACK_SOURCE_ROLES:
            continue
        summary = output.get("summary", "")
        if any(marker in summary for marker in _CHANGES_REQUESTED_MARKERS):
            return instance_id, role, summary

    return "", "", ""


def _find_target_coder(
    state: TaskState,
    feedback_source: str,
) -> str:
    """Find which coder instance should receive the feedback.

    Strategy:
    1. Look at the DAG — the coder that the feedback source depends on
    2. Fall back to the first coder instance in pipeline_order
    3. Backward compat: if pipeline_order has bare role names, look for "coder"
    """
    agents_cfg = state.get("team_config", {}).get("agents", {})
    execution_dag = state.get("team_config", {}).get("execution_dag", {})
    pipeline_order = state.get("team_config", {}).get("pipeline_order", [])

    # Strategy 1: Find coder in the feedback source's dependency chain
    deps = execution_dag.get(feedback_source, [])
    for dep in deps:
        dep_role = agents_cfg.get(dep, {}).get("role", "")
        if dep_role == "coder":
            return dep

    # Strategy 2: First coder instance in pipeline (new style with agents cfg)
    for iid in pipeline_order:
        if agents_cfg.get(iid, {}).get("role") == "coder":
            return iid

    # Strategy 3: Backward compat — pipeline_order may contain bare role names
    if not agents_cfg:
        for iid in pipeline_order:
            if iid == "coder" or iid.startswith("coder-"):
                return iid

    return ""


def check_debate_needed(state: TaskState) -> str:
    """
    After agents complete, check if any reviewer/QA requested changes.

    Generic: works with any instance_ids, not just "reviewer"/"coder".
    Checks all reviewer and QA instances for CHANGES_REQUESTED markers.

    Returns:
        "debate_needed" — a coder must address feedback
        "debate_done"   — all agents approved, proceed to commit
    """
    debate_round = state.get("debate_round", 0)
    max_rounds = state.get("max_debate_rounds", DEFAULT_MAX_DEBATE_ROUNDS)

    source_instance, source_role, _ = _find_feedback_source(state)

    if source_instance and debate_round < max_rounds:
        return "debate_needed"

    return "debate_done"


def prepare_debate_round(state: TaskState) -> dict:
    """
    Prepare state for coder re-execution with reviewer/QA feedback.

    Generic feedback loop:
    1. Find which reviewer/QA instance raised the issue
    2. Find which coder instance should fix it (via DAG deps)
    3. Reset that coder for re-execution with feedback injected
    4. Mark the feedback source for re-execution after coder finishes

    This implements the human-like workflow:
    - Reviewer raises comments → Engineer fixes → Reviewer re-reviews
    - QA raises issues → Engineer fixes → QA retests → Reviewer re-reviews
    """
    source_instance, source_role, feedback_summary = _find_feedback_source(state)
    debate_round = state.get("debate_round", 0) + 1

    # Find the target coder
    target_coder = _find_target_coder(state, source_instance)

    pipeline_order = state.get("team_config", {}).get("pipeline_order", [])
    agents_cfg = state.get("team_config", {}).get("agents", {})

    # Find coder's index
    coder_index = 0
    if target_coder in pipeline_order:
        coder_index = pipeline_order.index(target_coder)

    # Remove feedback source from completed so it re-runs after coder
    completed_roles = [
        r for r in state.get("completed_roles", [])
        if r != source_instance
    ]
    # Also remove the target coder from completed
    completed_roles = [r for r in completed_roles if r != target_coder]

    agent_outputs = dict(state.get("agent_outputs", {}))
    # Remove feedback source output so it regenerates
    agent_outputs.pop(source_instance, None)

    # Record the feedback loop in history
    feedback_loops = list(state.get("feedback_loops", []))
    feedback_loops.append({
        "round": debate_round,
        "source_instance": source_instance,
        "source_role": source_role,
        "target_coder": target_coder,
        "feedback": feedback_summary[:500],
    })

    events = list(state.get("events", []))
    events.append(
        {
            "type": "feedback_loop",
            "round": debate_round,
            "source_instance": source_instance,
            "source_role": source_role,
            "target_coder": target_coder,
            "feedback_preview": feedback_summary[:200],
        }
    )

    # Build the feedback source label for display
    source_name = agents_cfg.get(source_instance, {}).get("name", source_role.title())

    return {
        "current_agent_index": coder_index,
        "current_agent_role": target_coder,
        "current_instance_id": target_coder,
        "debate_round": debate_round,
        "debate_target_role": source_instance,  # After coder, re-run this instance
        "reviewer_feedback": feedback_summary,
        "completed_roles": completed_roles,
        "ready_roles": [target_coder],
        "agent_outputs": agent_outputs,
        "feedback_loops": feedback_loops,
        "active_feedback": {
            "source_instance": source_instance,
            "source_role": source_role,
            "target_coder": target_coder,
            "round": debate_round,
        },
        # Inject feedback as a fix packet so coder sees it
        "fix_packets": [
            f"[{source_role.upper()} FEEDBACK — Round {debate_round}]\n"
            f"From: {source_name} ({source_instance})\n\n"
            f"Your work has been reviewed and changes are requested. "
            f"Address the following feedback:\n\n{feedback_summary}"
        ],
        "retry_count": 0,
        "events": events,
    }
