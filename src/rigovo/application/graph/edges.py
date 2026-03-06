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
    return [iid for iid, cfg in agents.items() if cfg.get("role") == role]


def _latest_gate_passed_by_instance(state: TaskState) -> dict[str, bool]:
    """Return latest gate pass/fail status for each instance from gate history."""
    history = state.get("gate_history", []) or []
    latest: dict[str, bool] = {}
    for entry in history:
        if not isinstance(entry, dict):
            continue
        instance = str(entry.get("role", "") or "").strip()
        if not instance:
            continue
        if "passed" in entry:
            latest[instance] = bool(entry.get("passed"))
    return latest


def _resolve_remediation_lock_target(
    state: TaskState,
    completed_roles: set[str],
    blocked_roles: set[str],
) -> str:
    """Resolve forced remediation target when a source role failed Rigour gates.

    Source-role-first lock:
    - If active_feedback identifies a target coder and that coder's latest gate is failing,
      force that coder before downstream reviewers/QA/security.
    - Otherwise, if any coder instance has unresolved gate failure, force that coder.
    """
    latest = _latest_gate_passed_by_instance(state)
    if not latest:
        return ""

    active_fix_packet = state.get("active_fix_packet", {}) or {}
    remediation_owner = str(active_fix_packet.get("remediation_owner", "") or "").strip()
    if (
        remediation_owner
        and remediation_owner in latest
        and latest.get(remediation_owner) is False
        and remediation_owner not in blocked_roles
    ):
        return remediation_owner

    active_feedback = state.get("active_feedback", {}) or {}
    target_coder = str(active_feedback.get("target_coder", "") or "").strip()
    if (
        target_coder
        and latest.get(target_coder) is False
        and target_coder not in blocked_roles
        and target_coder not in completed_roles
    ):
        return target_coder

    for coder_instance in _get_instances_by_role(state, "coder"):
        if (
            latest.get(coder_instance) is False
            and coder_instance not in blocked_roles
            and coder_instance not in completed_roles
        ):
            return coder_instance

    return ""


# ── Reclassification check ──────────────────────────────────────────────


def check_reclassify_needed(state: TaskState) -> str:
    """Route after verify_execution — check if agent requested reclassification.

    If reclassify_requested is True and budget permits, route to reclassify
    node instead of quality gates. This short-circuits the normal pipeline
    because reclassification invalidates the current team composition.

    Returns:
        "reclassify" — agent requested reclassification, budget permits
        "continue"   — normal flow, proceed to quality gates
    """
    if not state.get("reclassify_requested", False):
        return "continue"

    reclassify_count = int(state.get("reclassify_count", 0) or 0)
    if reclassify_count >= 1:  # Max 1 reclassification per task
        return "continue"

    return "reclassify"


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

    Priority order (architectural invariant):
    1. Gates passed → advance to next agent
    2. Retries remaining → let the agent self-correct first (fix loop)
    3. Retries exhausted + replan available → escalate to replanner
    4. Retries exhausted + no replan → hard fail

    IMPORTANT: Replan is an ESCALATION after all retries are exhausted,
    never an interruption of the agent's retry budget.  This prevents
    the "replan triggered too early" problem where agents lose retries
    3-4 because the old code checked replan BEFORE retry budget.
    """
    gate_results = state.get("gate_results", {})
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 5)

    # 1. Gates passed → move on
    if gate_results.get("passed", True) or gate_results.get("status") == "skipped":
        return "pass_next_agent"

    # 2. Agent still has retries → let it self-correct
    if retry_count < max_retries:
        return "fail_fix_loop"

    # 3. Retries exhausted → escalate to replan if available
    if _should_trigger_replan(state):
        return "trigger_replan"

    # 4. No replan available → hard fail
    return "fail_max_retries"


def _should_trigger_replan(state: TaskState) -> bool:
    """Policy gate: should this exhausted-retry step escalate to replanning?

    IMPORTANT: This function is ONLY called after the agent has exhausted
    its full retry budget (check_gates_and_route ensures this).  We no
    longer need a retry-count threshold — if we got here, retries ARE
    exhausted.  The policy now decides if the failure warrants a global
    replan vs a hard abort.
    """
    policy = state.get("replan_policy", {}) or {}
    if not isinstance(policy, dict) or not policy.get("enabled", False):
        return False

    replan_count = int(state.get("replan_count", 0) or 0)
    max_replans = int(policy.get("max_replans_per_task", 1) or 1)
    if replan_count >= max_replans:
        return False

    gate_results = state.get("gate_results", {}) or {}

    # Contract failures always warrant replan (structural mismatch)
    if bool(policy.get("trigger_contract_failures", True)) and (
        gate_results.get("reason") == "contract_failed" or bool(state.get("contract_stage"))
    ):
        return True

    # Since we only get here when retries are exhausted, always allow
    # replan as a recovery mechanism (the agent genuinely couldn't self-fix)
    return True


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
                _get_role_for_instance(state, iid) in _PARALLELIZABLE_ROLES for iid in ready_roles
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
    remaining = pipeline_order[current_index + 1 :]
    if len(remaining) >= 2 and all(
        _get_role_for_instance(state, iid) in _PARALLELIZABLE_ROLES for iid in remaining
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

    # ── Feedback loop / debate: after coder fix, force reviewer/QA/security re-run ──
    # Gap #14 safety: only route to debate target if:
    # 1. debate_target is a valid pipeline member
    # 2. current agent is a coder (just finished fixing)
    # 3. debate_target is not the same as current instance (prevent self-loop)
    debate_target = str(state.get("debate_target_role", "") or "").strip()
    current_role = _get_role_for_instance(state, current_instance)
    if (
        debate_target
        and current_role == "coder"
        and debate_target in pipeline_order
        and debate_target != current_instance  # Never loop coder back to itself
        and debate_target not in blocked_roles  # Don't route to blocked agents
    ):
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
            "debate_target_role": "",  # Clear after routing to prevent re-trigger
            "fix_packets": [],
            "retry_count": 0,
            "status": "routing_next_agent",
            "error": "",
            "events": events,
        }

    blocked_roles = _compute_blocked_roles(execution_dag, completed_roles, blocked_roles)

    lock_target = _resolve_remediation_lock_target(state, completed_roles, blocked_roles)
    if lock_target:
        events = list(state.get("events", []))
        events.append(
            {
                "type": "remediation_lock",
                "target_instance": lock_target,
                "reason": "source_role_gate_failed",
            }
        )
        next_index = (
            pipeline_order.index(lock_target)
            if lock_target in pipeline_order
            else len(pipeline_order)
        )
        return {
            "current_agent_index": next_index,
            "current_agent_role": lock_target,
            "current_instance_id": lock_target,
            "ready_roles": [lock_target],
            "completed_roles": sorted(completed_roles),
            "blocked_roles": sorted(blocked_roles),
            "debate_target_role": ("" if current_instance == debate_target else debate_target),
            "fix_packets": [],
            "retry_count": 0,
            "status": "routing_next_agent",
            "error": "",
            "events": events,
        }

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
        iid for iid in pipeline_order if iid not in completed_roles and iid not in blocked_roles
    ]
    if remaining and not ready_roles:
        status = "pipeline_failed_dependency"
        error = "No executable DAG nodes remain; unresolved dependencies for: " + ", ".join(
            remaining
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
        "debate_target_role": ("" if current_instance == debate_target else debate_target),
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

# Phase 5: Security can also raise issues that need coder fixes.
_FEEDBACK_SOURCE_ROLES = {"reviewer", "qa", "security"}

DEFAULT_MAX_DEBATE_ROUNDS = 2

# Per-source-role debate round limits. Security reviews are typically
# one-shot (fix or acknowledge), while code review can iterate more.
_DEFAULT_MAX_ROUNDS_BY_ROLE: dict[str, int] = {
    "reviewer": 2,
    "qa": 2,
    "security": 1,  # Security findings: fix once, then re-verify
}


def _find_feedback_source(state: TaskState) -> tuple[str, str, str]:
    """Find the first reviewer/QA/security instance that requested changes.

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


def _find_all_feedback_sources(state: TaskState) -> list[tuple[str, str, str]]:
    """Find ALL feedback sources that requested changes (for multi-source feedback).

    Returns list of (source_instance_id, source_role, feedback_summary) tuples.
    """
    agent_outputs = state.get("agent_outputs", {})
    agents_cfg = state.get("team_config", {}).get("agents", {})
    sources: list[tuple[str, str, str]] = []

    for instance_id, output in agent_outputs.items():
        role = agents_cfg.get(instance_id, {}).get("role", "")
        if not role:
            role = instance_id
        if role not in _FEEDBACK_SOURCE_ROLES:
            continue
        summary = output.get("summary", "")
        if any(marker in summary for marker in _CHANGES_REQUESTED_MARKERS):
            sources.append((instance_id, role, summary))

    return sources


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
    After agents complete, check if any reviewer/QA/security requested changes.

    Phase 5: Generic debate protocol with per-source-role round limits.
    Works with any instance_ids, not just "reviewer"/"coder".
    Checks all feedback source roles for CHANGES_REQUESTED markers.

    Per-source round tracking: a reviewer can trigger 2 rounds, security 1 round,
    independently. The global debate_round is the total sum.

    Returns:
        "debate_needed" — a coder must address feedback
        "debate_done"   — all agents approved, proceed to commit
    """
    debate_round = state.get("debate_round", 0)
    max_rounds = state.get("max_debate_rounds", DEFAULT_MAX_DEBATE_ROUNDS)

    # Global cap still applies
    if debate_round >= max_rounds:
        return "debate_done"

    # Find all feedback sources
    all_sources = _find_all_feedback_sources(state)
    if not all_sources:
        return "debate_done"

    # Per-source-role round tracking
    feedback_loops = state.get("feedback_loops", [])
    for source_instance, source_role, _ in all_sources:
        # Count how many rounds this specific source has already triggered
        rounds_for_source = sum(
            1 for fl in feedback_loops if fl.get("source_instance") == source_instance
        )
        role_max = _DEFAULT_MAX_ROUNDS_BY_ROLE.get(source_role, DEFAULT_MAX_DEBATE_ROUNDS)
        if rounds_for_source < role_max:
            return "debate_needed"

    return "debate_done"


def prepare_debate_round(state: TaskState) -> dict:
    """
    Prepare state for coder re-execution with reviewer/QA/security feedback.

    Phase 5: Generic feedback loop supporting multiple simultaneous sources.

    1. Find ALL reviewer/QA/security instances that raised issues
    2. For each, check per-source round limits
    3. Find which coder instance should fix it (via DAG deps)
    4. Combine all feedback into a single fix packet
    5. Mark all feedback sources for re-execution after coder finishes

    This implements the human-like workflow:
    - Reviewer raises comments → Engineer fixes → Reviewer re-reviews
    - QA raises issues → Engineer fixes → QA retests → Reviewer re-reviews
    - Security raises vulnerabilities → Engineer fixes → Security re-scans
    - Multiple sources can raise issues simultaneously — all feedback combined
    """
    debate_round = state.get("debate_round", 0) + 1
    feedback_loops = list(state.get("feedback_loops", []))

    # Find all feedback sources, filter by per-source round limits
    all_sources = _find_all_feedback_sources(state)
    active_sources: list[tuple[str, str, str]] = []
    for src_instance, src_role, summary in all_sources:
        rounds_for_source = sum(
            1 for fl in feedback_loops if fl.get("source_instance") == src_instance
        )
        role_max = _DEFAULT_MAX_ROUNDS_BY_ROLE.get(src_role, DEFAULT_MAX_DEBATE_ROUNDS)
        if rounds_for_source < role_max:
            active_sources.append((src_instance, src_role, summary))

    # Fall back to first source if multi-source filtering yields nothing
    if not active_sources:
        source_instance, source_role, feedback_summary = _find_feedback_source(state)
        if source_instance:
            active_sources = [(source_instance, source_role, feedback_summary)]

    # Use the first active source as the primary (for coder routing)
    if not active_sources:
        # No actionable feedback — shouldn't happen but be defensive
        return {
            "debate_round": debate_round,
            "events": [
                *list(state.get("events", [])),
                {
                    "type": "feedback_loop",
                    "round": debate_round,
                    "status": "no_actionable_feedback",
                },
            ],
        }

    primary_instance, primary_role, primary_summary = active_sources[0]
    target_coder = _find_target_coder(state, primary_instance)

    pipeline_order = state.get("team_config", {}).get("pipeline_order", [])
    agents_cfg = state.get("team_config", {}).get("agents", {})

    # Find coder's index
    coder_index = 0
    if target_coder in pipeline_order:
        coder_index = pipeline_order.index(target_coder)

    # Remove ALL feedback sources from completed so they re-run after coder
    source_instances = {src[0] for src in active_sources}
    completed_roles = [
        r
        for r in state.get("completed_roles", [])
        if r not in source_instances and r != target_coder
    ]

    agent_outputs = dict(state.get("agent_outputs", {}))
    # Remove all feedback source outputs so they regenerate
    for src_inst, _, _ in active_sources:
        agent_outputs.pop(src_inst, None)

    # Record each feedback loop in history
    events = list(state.get("events", []))
    for src_instance, src_role, summary in active_sources:
        feedback_loops.append(
            {
                "round": debate_round,
                "source_instance": src_instance,
                "source_role": src_role,
                "target_coder": target_coder,
                "feedback": summary[:500],
            }
        )
        events.append(
            {
                "type": "feedback_loop",
                "round": debate_round,
                "source_instance": src_instance,
                "source_role": src_role,
                "target_coder": target_coder,
                "feedback_preview": summary[:200],
            }
        )

    # Build combined fix packet with all feedback.
    # Truncate each summary to prevent token waste (2000 chars max per source).
    max_feedback_chars = 2000
    fix_packet_parts: list[str] = []
    for src_instance, src_role, summary in active_sources:
        src_name = agents_cfg.get(src_instance, {}).get("name", src_role.title())
        truncated_summary = summary[:max_feedback_chars]
        if len(summary) > max_feedback_chars:
            truncated_summary += "... (truncated)"
        fix_packet_parts.append(
            f"[{src_role.upper()} FEEDBACK — Round {debate_round}]\n"
            f"From: {src_name} ({src_instance})\n\n"
            f"Your work has been reviewed and changes are requested. "
            f"Address the following feedback:\n\n{truncated_summary}"
        )

    action_delta = {
        "fix_packet_count": len(fix_packet_parts),
        "feedback_source_count": len(active_sources),
        "requeue_after_coder": [src[0] for src in active_sources],
    }
    events.append(
        {
            "type": "debate_adjudicated",
            "round": debate_round,
            "selected_next_owner": target_coder,
            "primary_source_instance": primary_instance,
            "primary_source_role": primary_role,
            "feedback_sources": [
                {"instance": src_instance, "role": src_role}
                for src_instance, src_role, _ in active_sources
            ],
            "action_delta": action_delta,
            "target_coder": target_coder,
        }
    )

    # The debate_target_role is the primary source (first to re-run after coder)
    # Additional sources will be picked up via the DAG ready-roles mechanism
    return {
        "current_agent_index": coder_index,
        "current_agent_role": target_coder,
        "current_instance_id": target_coder,
        "debate_round": debate_round,
        "debate_target_role": primary_instance,  # After coder, re-run this instance
        "reviewer_feedback": primary_summary,
        "completed_roles": completed_roles,
        "ready_roles": [target_coder],
        "agent_outputs": agent_outputs,
        "feedback_loops": feedback_loops,
        "active_feedback": {
            "source_instance": primary_instance,
            "source_role": primary_role,
            "target_coder": target_coder,
            "round": debate_round,
            "selected_next_owner": target_coder,
            "primary_source_instance": primary_instance,
            "action_delta": action_delta,
            "all_sources": [{"instance": s[0], "role": s[1]} for s in active_sources],
        },
        # Inject ALL feedback as fix packets so coder sees everything
        "fix_packets": fix_packet_parts,
        "retry_count": 0,
        "events": events,
    }
