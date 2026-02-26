"""Replan node — policy-driven mid-run replanning."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.interfaces.llm_provider import LLMProvider


REPLAN_PROMPT = """\
You are a replanner for a multi-agent software delivery DAG.

A step has failed repeatedly or violated policy contracts.
Provide a concise corrective plan that is cost-aware.

Return ONLY JSON:
{
  "adjustment": "short directive for the next execution attempt",
  "target_role": "role to retry now",
  "reasoning": "one sentence"
}
"""


async def replan_node(
    state: TaskState,
    llm: LLMProvider,
) -> dict[str, Any]:
    """Create a corrective replan instruction and route back to execution."""
    await asyncio.sleep(0)
    policy = state.get("replan_policy", {}) or {}
    max_replans = int(policy.get("max_replans_per_task", 1) or 1)
    strategy = str(policy.get("strategy", "deterministic") or "deterministic").strip().lower()
    next_replan_count = int(state.get("replan_count", 0) or 0) + 1

    events = list(state.get("events", []))
    replan_history = list(state.get("replan_history", []))

    if next_replan_count > max_replans:
        trigger_reason = _derive_trigger_reason(state, policy)
        history_entry = {
            "status": "replan_failed",
            "reason": "replan_budget_exhausted",
            "trigger_reason": trigger_reason,
            "replan_count": next_replan_count - 1,
            "max_replans_per_task": max_replans,
            "strategy": strategy,
        }
        replan_history.append(history_entry)
        events.append(
            {
                "type": "replan_failed",
                "reason": "replan_budget_exhausted",
                "trigger_reason": trigger_reason,
                "replan_count": next_replan_count - 1,
                "max_replans_per_task": max_replans,
                "strategy": strategy,
            }
        )
        return {
            "status": "replan_failed",
            "error": (
                f"Replan budget exhausted ({next_replan_count - 1}/{max_replans})."
            ),
            "replan_history": replan_history,
            "events": events,
        }

    current_role = str(state.get("current_agent_role", "") or "")
    gate_results = state.get("gate_results", {})
    prompt_input = {
        "task": state.get("description", ""),
        "current_role": current_role,
        "retry_count": state.get("retry_count", 0),
        "contract_stage": state.get("contract_stage", ""),
        "gate_results": gate_results,
    }

    trigger_reason = _derive_trigger_reason(state, policy)
    if strategy == "llm":
        response = await llm.invoke(
            messages=[
                {"role": "system", "content": REPLAN_PROMPT},
                {"role": "user", "content": json.dumps(prompt_input, default=str)},
            ],
            temperature=0.0,
            max_tokens=256,
        )

        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            parsed = _deterministic_replan(state, trigger_reason)
            parsed["reasoning"] = "Failed to parse replanner output; using deterministic fallback."
    else:
        parsed = _deterministic_replan(state, trigger_reason)

    target_role = str(parsed.get("target_role", current_role) or current_role).strip()
    if target_role not in state.get("team_config", {}).get("agents", {}):
        target_role = current_role

    adjustment = str(parsed.get("adjustment", "")).strip() or (
        "Focus on resolving policy and gate failures with minimal edits."
    )
    fix_packets = list(state.get("fix_packets", []))
    fix_packets.append(
        f"[REPLAN REQUIRED #{next_replan_count}]\n"
        f"{adjustment}"
    )

    events.append(
        {
            "type": "replan_triggered",
            "replan_count": next_replan_count,
            "target_role": target_role,
            "trigger_reason": trigger_reason,
            "strategy": strategy,
            "reasoning": str(parsed.get("reasoning", "")),
        }
    )
    replan_history.append(
        {
            "status": "replanned",
            "replan_count": next_replan_count,
            "target_role": target_role,
            "trigger_reason": trigger_reason,
            "strategy": strategy,
        }
    )

    return {
        "status": "replanned",
        "replan_count": next_replan_count,
        "current_agent_role": target_role,
        "fix_packets": fix_packets,
        "retry_count": 0,
        "replan_history": replan_history,
        "events": events,
    }


def _derive_trigger_reason(state: TaskState, policy: dict[str, Any]) -> str:
    """Derive deterministic reason for a replan trigger from state + policy."""
    gate_results = state.get("gate_results", {}) or {}
    if bool(policy.get("trigger_contract_failures", True)):
        if gate_results.get("reason") == "contract_failed" or bool(state.get("contract_stage")):
            return "contract_failure"
    retry_threshold = int(policy.get("trigger_retry_count", 3) or 3)
    if int(state.get("retry_count", 0) or 0) >= retry_threshold:
        return "retry_threshold"
    violation_threshold = int(policy.get("trigger_gate_violation_count", 5) or 5)
    if int(gate_results.get("violation_count", 0) or 0) >= violation_threshold:
        return "gate_violation_threshold"
    return "policy_replan"


def _deterministic_replan(state: TaskState, trigger_reason: str) -> dict[str, Any]:
    """Deterministic, policy-based replan output with no model variance."""
    current_role = str(state.get("current_agent_role", "") or "").strip()
    target_role = current_role or "coder"
    if trigger_reason == "contract_failure":
        adjustment = (
            "Satisfy contract requirements exactly; produce only required schema fields "
            "and keep edits minimal."
        )
    elif trigger_reason == "gate_violation_threshold":
        adjustment = (
            "Address all gate violations with focused fixes, then regenerate changed tests "
            "for touched files."
        )
    elif trigger_reason == "retry_threshold":
        adjustment = (
            "Reduce scope to smallest failing surface and apply a single coherent fix path."
        )
    else:
        adjustment = "Apply a minimal corrective patch that resolves current execution blockers."

    return {
        "adjustment": adjustment,
        "target_role": target_role,
        "reasoning": f"Deterministic replan selected for {trigger_reason}.",
    }
