"""Tests for team routing functionality.

Covers:
- Single team routing (direct path)
- Multi-team routing with LLM decision
- Error handling and fallbacks
- Confidence scoring
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from rigovo.application.master.router import TeamRouter, RoutingResult
from rigovo.domain.entities.team import Team
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage


@pytest.fixture
def mock_llm():
    """Mock LLM provider."""
    llm = AsyncMock()
    llm.invoke = AsyncMock()
    return llm


@pytest.fixture
def workspace_id():
    return uuid4()


@pytest.fixture
def engineering_team(workspace_id):
    """Engineering team."""
    return Team(
        workspace_id=workspace_id,
        name="Engineering",
        domain="engineering",
    )


@pytest.fixture
def content_team(workspace_id):
    """Content team."""
    return Team(
        workspace_id=workspace_id,
        name="Content",
        domain="content",
    )


@pytest.fixture
def devops_team(workspace_id):
    """DevOps team."""
    return Team(
        workspace_id=workspace_id,
        name="DevOps",
        domain="devops",
    )


def _llm_response(content: str) -> LLMResponse:
    """Create a mock LLM response."""
    return LLMResponse(
        content=content,
        usage=LLMUsage(input_tokens=100, output_tokens=50),
        model="test-model",
    )


class TestTeamRouterSingleTeam:
    """Test routing when only one team is available."""

    async def test_single_team_routes_directly(self, mock_llm, engineering_team):
        """Single team should route directly without LLM call."""
        router = TeamRouter(mock_llm)
        result = await router.route("Add user authentication", [engineering_team])

        assert result.team_id == engineering_team.id
        assert result.confidence == 1.0
        assert result.reasoning == "Only one team available"
        # LLM should not be called
        mock_llm.invoke.assert_not_called()

    async def test_single_team_any_description(self, mock_llm, content_team):
        """Single team routes regardless of task description."""
        router = TeamRouter(mock_llm)
        result = await router.route("Write blog post about AI", [content_team])

        assert result.team_id == content_team.id
        assert result.confidence == 1.0


class TestTeamRouterMultiTeam:
    """Test routing when multiple teams are available."""

    async def test_multi_team_uses_llm(self, mock_llm, engineering_team, content_team):
        """Multiple teams should use LLM to decide."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(engineering_team.id),
                "confidence": 0.95,
                "reasoning": "Task is code-related",
            })
        )

        result = await router.route(
            "Add user authentication",
            [engineering_team, content_team],
        )

        assert result.team_id == engineering_team.id
        assert result.confidence == 0.95
        assert result.reasoning == "Task is code-related"
        mock_llm.invoke.assert_called_once()

    async def test_multi_team_routes_to_content(self, mock_llm, engineering_team, content_team):
        """LLM can route to content team."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(content_team.id),
                "confidence": 0.88,
                "reasoning": "Task is content-related",
            })
        )

        result = await router.route(
            "Write documentation for API",
            [engineering_team, content_team],
        )

        assert result.team_id == content_team.id
        assert result.confidence == 0.88

    async def test_multi_team_three_teams(self, mock_llm, engineering_team, content_team, devops_team):
        """Routing works with three teams."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(devops_team.id),
                "confidence": 0.92,
                "reasoning": "Infrastructure task",
            })
        )

        result = await router.route(
            "Set up Kubernetes cluster",
            [engineering_team, content_team, devops_team],
        )

        assert result.team_id == devops_team.id
        assert result.confidence == 0.92


class TestTeamRouterErrorHandling:
    """Test error handling and fallback behavior."""

    async def test_no_teams_raises(self, mock_llm):
        """Routing with no teams should raise ValueError."""
        router = TeamRouter(mock_llm)
        with pytest.raises(ValueError, match="No teams available"):
            await router.route("Some task", [])

    async def test_invalid_team_id_falls_back(self, mock_llm, engineering_team, content_team):
        """LLM returns invalid team ID -> fallback to first team."""
        router = TeamRouter(mock_llm)
        invalid_id = uuid4()
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(invalid_id),
                "confidence": 0.5,
                "reasoning": "Invalid team",
            })
        )

        result = await router.route(
            "Some task",
            [engineering_team, content_team],
        )

        # Should fallback to first team
        assert result.team_id == engineering_team.id
        assert result.confidence == 0.5
        assert "defaulting" in result.reasoning.lower()

    async def test_bad_json_response_falls_back(self, mock_llm, engineering_team, content_team):
        """LLM returns invalid JSON -> fallback to first team."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response("I'm not sure what to do")

        result = await router.route(
            "Some task",
            [engineering_team, content_team],
        )

        assert result.team_id == engineering_team.id
        assert result.confidence == 0.5
        assert "defaulting" in result.reasoning.lower()

    async def test_code_fence_json_parsing(self, mock_llm, engineering_team, content_team):
        """LLM response wrapped in code fence should be parsed."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            f'```json\n{{"team_id": "{engineering_team.id}", "confidence": 0.9, "reasoning": "Code task"}}\n```'
        )

        result = await router.route(
            "Add feature",
            [engineering_team, content_team],
        )

        assert result.team_id == engineering_team.id
        assert result.confidence == 0.9

    async def test_confidence_clamped_to_0_1(self, mock_llm, engineering_team, content_team):
        """Confidence values outside [0, 1] should be clamped."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(engineering_team.id),
                "confidence": 1.5,  # Invalid: > 1.0
                "reasoning": "Test",
            })
        )

        result = await router.route(
            "Some task",
            [engineering_team, content_team],
        )

        assert result.confidence == 1.0

    async def test_negative_confidence_clamped(self, mock_llm, engineering_team, content_team):
        """Negative confidence should be clamped to 0."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(engineering_team.id),
                "confidence": -0.5,  # Invalid: < 0.0
                "reasoning": "Test",
            })
        )

        result = await router.route(
            "Some task",
            [engineering_team, content_team],
        )

        assert result.confidence == 0.0


class TestTeamRouterEdgeCases:
    """Test edge cases and boundary conditions."""

    async def test_empty_description(self, mock_llm, engineering_team):
        """Empty task description should still route."""
        router = TeamRouter(mock_llm)
        result = await router.route("", [engineering_team])

        assert result.team_id == engineering_team.id
        assert result.confidence == 1.0

    async def test_very_long_description(self, mock_llm, engineering_team, content_team):
        """Very long task description should be handled."""
        router = TeamRouter(mock_llm)
        long_desc = "Add feature " * 1000  # Very long
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(engineering_team.id),
                "confidence": 0.8,
                "reasoning": "Code task",
            })
        )

        result = await router.route(long_desc, [engineering_team, content_team])
        assert result.team_id == engineering_team.id

    async def test_missing_confidence_field(self, mock_llm, engineering_team, content_team):
        """Missing confidence field should default to 0.8."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(engineering_team.id),
                "reasoning": "Code task",
                # confidence field missing
            })
        )

        result = await router.route(
            "Some task",
            [engineering_team, content_team],
        )

        assert result.confidence == 0.8

    async def test_missing_reasoning_field(self, mock_llm, engineering_team, content_team):
        """Missing reasoning field should default to empty string."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(engineering_team.id),
                "confidence": 0.9,
                # reasoning field missing
            })
        )

        result = await router.route(
            "Some task",
            [engineering_team, content_team],
        )

        assert result.reasoning == ""

    async def test_llm_invoke_called_with_correct_params(self, mock_llm, engineering_team, content_team):
        """LLM invoke should be called with correct parameters."""
        router = TeamRouter(mock_llm)
        mock_llm.invoke.return_value = _llm_response(
            json.dumps({
                "team_id": str(engineering_team.id),
                "confidence": 0.9,
                "reasoning": "Test",
            })
        )

        await router.route(
            "Add feature",
            [engineering_team, content_team],
        )

        # Verify LLM was called with correct parameters
        mock_llm.invoke.assert_called_once()
        call_kwargs = mock_llm.invoke.call_args[1]
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["max_tokens"] == 256
        assert "messages" in call_kwargs


class TestRoutingResultDataclass:
    """Test RoutingResult dataclass."""

    def test_routing_result_creation(self):
        """RoutingResult should be creatable with required fields."""
        team_id = uuid4()
        result = RoutingResult(
            team_id=team_id,
            confidence=0.95,
            reasoning="Test routing",
        )

        assert result.team_id == team_id
        assert result.confidence == 0.95
        assert result.reasoning == "Test routing"

    def test_routing_result_equality(self):
        """RoutingResult instances with same values should be equal."""
        team_id = uuid4()
        result1 = RoutingResult(
            team_id=team_id,
            confidence=0.95,
            reasoning="Test",
        )
        result2 = RoutingResult(
            team_id=team_id,
            confidence=0.95,
            reasoning="Test",
        )

        assert result1 == result2
