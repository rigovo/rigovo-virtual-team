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
    next_replan_count = int(state.get("replan_count", 0) or 0) + 1

    events = list(state.get("events", []))

    if next_replan_count > max_replans:
        events.append(
            {
                "type": "replan_failed",
                "reason": "replan_budget_exhausted",
                "replan_count": next_replan_count - 1,
                "max_replans_per_task": max_replans,
            }
        )
        return {
            "status": "replan_failed",
            "error": (
                f"Replan budget exhausted ({next_replan_count - 1}/{max_replans})."
            ),
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
        parsed = {
            "adjustment": (
                "Tighten implementation scope and fix reported violations only."
            ),
            "target_role": current_role,
            "reasoning": "Failed to parse replanner output; using safe fallback.",
        }

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
            "reasoning": str(parsed.get("reasoning", "")),
        }
    )

    return {
        "status": "replanned",
        "replan_count": next_replan_count,
        "current_agent_role": target_role,
        "fix_packets": fix_packets,
        "retry_count": 0,
        "events": events,
    }
