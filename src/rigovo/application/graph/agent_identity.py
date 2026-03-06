"""Canonical agent identity helpers for graph nodes."""

from __future__ import annotations

from typing import Any

from rigovo.application.graph.state import TaskState


def resolve_current_instance_id(state: TaskState) -> str:
    """Resolve active instance id from state with backward compatibility."""
    current_role = str(state.get("current_agent_role", "") or "").strip()
    current_instance = str(state.get("current_instance_id", "") or "").strip()
    return current_instance or current_role


def resolve_base_role(state: TaskState, instance_id: str) -> str:
    """Resolve base role (coder/qa/...) for an agent instance."""
    team_config = state.get("team_config", {}) or {}
    agents_cfg = team_config.get("agents", {}) or {}
    cfg = agents_cfg.get(instance_id, {}) or {}
    role = str(cfg.get("role", "") or "").strip()
    if role:
        return role
    if "-" in instance_id:
        head, _, tail = instance_id.rpartition("-")
        if head and tail.isdigit():
            return head
    return instance_id


def resolve_agent_output(state: TaskState, instance_id: str, current_role: str) -> dict[str, Any]:
    """Get output record for an agent with instance-first fallback lookup."""
    outputs = state.get("agent_outputs", {}) or {}
    output = outputs.get(instance_id)
    if isinstance(output, dict):
        return output
    output = outputs.get(current_role)
    return output if isinstance(output, dict) else {}
