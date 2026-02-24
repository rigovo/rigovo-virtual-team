"""Route team node — Master Agent routes the task to the appropriate team."""

from __future__ import annotations

import json
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.interfaces.llm_provider import LLMProvider


ROUTING_PROMPT = """\
You are a team router for a workspace with multiple engineering teams.

Given a task description and its classification, decide which team should handle it.

Available teams:
{teams_json}

Task type: {task_type}
Task complexity: {complexity}

Respond with ONLY valid JSON:
{{
    "team_id": "...",
    "team_name": "...",
    "reasoning": "..."
}}
"""


async def route_team_node(
    state: TaskState,
    llm: LLMProvider,
    available_teams: list[dict[str, Any]],
) -> dict[str, Any]:
    """Route the task to a team using the Master Agent's LLM."""
    classification = state.get("classification", {})

    # If there's only one team, route directly
    if len(available_teams) == 1:
        team = available_teams[0]
        return {
            "team_config": {
                "team_id": team["id"],
                "team_name": team["name"],
                "domain": team.get("domain", "engineering"),
                "agents": team.get("agents", {}),
                "pipeline_order": team.get("pipeline_order", []),
            },
            "status": "routed",
            "events": state.get("events", []) + [{
                "type": "team_routed",
                "team_name": team["name"],
                "reasoning": "Only one team available.",
            }],
        }

    prompt = ROUTING_PROMPT.format(
        teams_json=json.dumps(
            [{"id": t["id"], "name": t["name"], "domain": t.get("domain")} for t in available_teams],
            indent=2,
        ),
        task_type=classification.get("task_type", "unknown"),
        complexity=classification.get("complexity", "medium"),
    )

    response = await llm.invoke(
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": state["description"]},
        ],
        temperature=0.0,
        max_tokens=256,
    )

    try:
        routing = json.loads(response.content)
    except json.JSONDecodeError:
        # Default to first team
        routing = {
            "team_id": available_teams[0]["id"],
            "team_name": available_teams[0]["name"],
            "reasoning": "Failed to parse routing, defaulting to first team.",
        }

    # Find the matched team config
    matched_team = next(
        (t for t in available_teams if t["id"] == routing["team_id"]),
        available_teams[0],
    )

    return {
        "team_config": {
            "team_id": matched_team["id"],
            "team_name": matched_team["name"],
            "domain": matched_team.get("domain", "engineering"),
            "agents": matched_team.get("agents", {}),
            "pipeline_order": matched_team.get("pipeline_order", []),
        },
        "status": "routed",
        "events": state.get("events", []) + [{
            "type": "team_routed",
            "team_name": routing.get("team_name"),
            "reasoning": routing.get("reasoning"),
        }],
    }
