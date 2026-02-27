"""Master Agent — Team Router.

Routes tasks to the appropriate team based on domain analysis.
When a workspace has multiple teams (e.g., engineering + content),
the router decides which team handles each task.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from rigovo.domain.entities.team import Team
from rigovo.domain.interfaces.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """\
You are a task router for a virtual team platform.

Given a task description and a list of available teams (each with
their domain and capabilities), decide which team should handle it.

If there is only one team, route to it.
If the task clearly matches a domain, route to that team.
If ambiguous, pick the best fit and explain why.

Respond ONLY with valid JSON:
{"team_id": "...", "confidence": 0.95, "reasoning": "one sentence why"}
"""


@dataclass
class RoutingResult:
    """Result of routing a task to a team."""

    team_id: UUID
    confidence: float
    reasoning: str


class TeamRouter:
    """
    Routes tasks to the appropriate team.

    Uses LLM analysis when multiple teams exist,
    direct routing when there's only one team.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def route(
        self,
        description: str,
        teams: list[Team],
    ) -> RoutingResult:
        """Route a task to the best team."""
        if not teams:
            raise ValueError("No teams available for routing")

        # Fast path: single team
        if len(teams) == 1:
            return RoutingResult(
                team_id=teams[0].id,
                confidence=1.0,
                reasoning="Only one team available",
            )

        # Multi-team: use LLM to decide
        return await self._llm_route(description, teams)

    async def _llm_route(
        self,
        description: str,
        teams: list[Team],
    ) -> RoutingResult:
        """Use LLM to route among multiple teams."""
        teams_desc = "\n".join(
            f"- Team ID: {t.id} | Domain: {t.domain} | Name: {t.name}" for t in teams
        )

        response = await self._llm.invoke(
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Available Teams:\n{teams_desc}\n\nTask Description:\n{description}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=256,
        )

        return self._parse_response(response.content, teams)

    def _parse_response(
        self,
        content: str,
        teams: list[Team],
    ) -> RoutingResult:
        """Parse LLM routing response."""
        try:
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)
            team_id = UUID(data["team_id"])
            confidence = float(data.get("confidence", 0.8))
            reasoning = data.get("reasoning", "")

            # Validate team_id exists
            valid_ids = {t.id for t in teams}
            if team_id not in valid_ids:
                logger.warning("LLM returned invalid team_id: %s", team_id)
                return RoutingResult(
                    team_id=teams[0].id,
                    confidence=0.5,
                    reasoning=f"LLM returned invalid team, defaulting to {teams[0].name}",
                )

            return RoutingResult(
                team_id=team_id,
                confidence=min(1.0, max(0.0, confidence)),
                reasoning=reasoning,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse routing: %s — %s", e, content[:200])
            return RoutingResult(
                team_id=teams[0].id,
                confidence=0.5,
                reasoning=f"Parse failed, defaulting to {teams[0].name}",
            )
