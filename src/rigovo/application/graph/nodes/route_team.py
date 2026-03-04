"""Route team node — Master Agent routes the task to the appropriate team."""

from __future__ import annotations

import json
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from rigovo.application.cache_utils import stable_hash, usage_to_dict
from rigovo.application.graph.state import TaskState
from rigovo.application.master.router import TeamRouter
from rigovo.domain.entities.team import Team
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
    router: TeamRouter | None = None,
    cache_repo: Any | None = None,
) -> dict[str, Any]:
    """Route the task to a team using the Master Agent's LLM."""
    classification = state.get("classification", {})
    workspace_id_str = str(state.get("workspace_id", "") or "")
    events = list(state.get("events", []))
    cache_prompt_hash = stable_hash(
        {
            "v": "route_team_v1",
            "description": state.get("description", ""),
            "classification": classification,
            "teams": [
                {"id": t.get("id"), "name": t.get("name"), "domain": t.get("domain")}
                for t in available_teams
            ],
        }
    )
    cache_context_fingerprint = stable_hash(
        {
            "task_type": classification.get("task_type", "unknown"),
            "complexity": classification.get("complexity", "medium"),
            "requested_team_name": state.get("requested_team_name", ""),
        }
    )

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
            "events": events
            + [
                {
                    "type": "team_routed",
                    "team_name": team["name"],
                    "reasoning": "Only one team available.",
                }
            ],
        }

    if cache_repo is not None and workspace_id_str:
        cached = await cache_repo.get_exact(
            workspace_id=workspace_id_str,
            role="master_route_team",
            model=llm.model_name,
            prompt_hash=cache_prompt_hash,
            context_fingerprint=cache_context_fingerprint,
        )
        if cached and isinstance(cached.get("response"), dict):
            payload = cached["response"]
            cached_team_id = str(payload.get("team_id", "") or "")
            matched_team = next(
                (t for t in available_teams if str(t.get("id", "")) == cached_team_id),
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
                "events": events
                + [
                    {
                        "type": "cache_hit",
                        "cache_source": "rigovo_exact",
                        "role": "master_route_team",
                        "saved_tokens": int((cached.get("usage") or {}).get("total_tokens", 0) or 0),
                    },
                    {
                        "type": "team_routed",
                        "team_name": matched_team.get("name"),
                        "reasoning": payload.get("reasoning", "Routed from exact cache."),
                        "confidence": float(payload.get("confidence", 1.0) or 1.0),
                    },
                ],
            }
        events.append(
            {
                "type": "cache_miss",
                "cache_source": "none",
                "role": "master_route_team",
            }
        )

    if router is not None:
        workspace_uuid = _parse_uuid(state.get("workspace_id")) or UUID(int=0)
        team_entities: list[Team] = []
        uuid_to_team: dict[UUID, dict[str, Any]] = {}
        for t in available_teams:
            team_uuid = uuid5(NAMESPACE_DNS, str(t.get("id", "")))
            team = Team(
                id=team_uuid,
                workspace_id=workspace_uuid,
                name=str(t.get("name", t.get("id", "team"))),
                domain=str(t.get("domain", "engineering")),
            )
            team_entities.append(team)
            uuid_to_team[team_uuid] = t

        routed = await router.route(state["description"], team_entities)
        matched_team = uuid_to_team.get(routed.team_id, available_teams[0])
        if cache_repo is not None and workspace_id_str:
            await cache_repo.put_exact(
                workspace_id=workspace_id_str,
                role="master_route_team",
                model=llm.model_name,
                prompt_hash=cache_prompt_hash,
                context_fingerprint=cache_context_fingerprint,
                response={
                    "team_id": str(matched_team.get("id", "")),
                    "team_name": str(matched_team.get("name", "")),
                    "reasoning": routed.reasoning,
                    "confidence": float(routed.confidence),
                },
                usage={},
                metadata={"router": "master_router"},
                ttl_minutes=180,
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
            "events": events
            + [
                {
                    "type": "team_routed",
                    "team_name": matched_team.get("name"),
                    "reasoning": routed.reasoning,
                    "confidence": routed.confidence,
                }
            ],
        }

    prompt = ROUTING_PROMPT.format(
        teams_json=json.dumps(
            [
                {"id": t["id"], "name": t["name"], "domain": t.get("domain")}
                for t in available_teams
            ],
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
    if cache_repo is not None and workspace_id_str:
        await cache_repo.put_exact(
            workspace_id=workspace_id_str,
            role="master_route_team",
            model=llm.model_name,
            prompt_hash=cache_prompt_hash,
            context_fingerprint=cache_context_fingerprint,
            response={
                "team_id": str(matched_team.get("id", "")),
                "team_name": str(routing.get("team_name", matched_team.get("name", ""))),
                "reasoning": str(routing.get("reasoning", "")),
                "confidence": float(routing.get("confidence", 0.8) or 0.8),
            },
            usage=usage_to_dict(response.usage),
            metadata={"router": "fallback_prompt"},
            ttl_minutes=180,
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
        "events": events
        + [
            {
                "type": "team_routed",
                "team_name": routing.get("team_name"),
                "reasoning": routing.get("reasoning"),
            }
        ],
    }


def _parse_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None
