"""Unit tests for classify and assemble graph nodes."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.state import TaskState, AgentOutput
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage


class MockLLMProvider:
    """Mock LLM provider for testing."""

    def __init__(self, response_content: str = ""):
        self.response_content = response_content
        self.model_name = "test-model"

    async def invoke(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Return a mock response with token counts."""
        await asyncio.sleep(0)  # Yield to event loop as real LLM providers do
        return LLMResponse(
            content=self.response_content,
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            model=self.model_name,
        )

    async def stream(self, *args, **kwargs):
        """Mock stream method."""
        return []


class TestClassifyNode(unittest.IsolatedAsyncioTestCase):
    """Test the classify_node function."""

    async def test_classify_node_valid_json_response(self):
        """Test classify_node with valid JSON response."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Add authentication to the API",
            "events": [],
        }

        classification = {
            "task_type": "feature",
            "complexity": "high",
            "reasoning": "Requires security implementation",
        }
        mock_llm = MockLLMProvider(response_content=json.dumps(classification))

        result = await classify_node(state, mock_llm)

        assert result["classification"] == classification
        assert result["status"] == "classified"
        assert "cost_accumulator" in result
        assert "classifier" in result["cost_accumulator"]
        assert result["cost_accumulator"]["classifier"]["tokens"] == 150
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "task_classified"
        assert result["events"][0]["task_type"] == "feature"
        assert result["events"][0]["complexity"] == "high"

    async def test_classify_node_invalid_json_defaults(self):
        """Test classify_node defaults to feature/medium on invalid JSON."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Some task",
            "events": [],
        }

        mock_llm = MockLLMProvider(response_content="Not valid JSON")

        result = await classify_node(state, mock_llm)

        assert result["classification"]["task_type"] == "feature"
        assert result["classification"]["complexity"] == "medium"
        assert result["status"] == "classified"
        assert len(result["events"]) == 1

    async def test_classify_node_preserves_cost_accumulator(self):
        """Test classify_node preserves existing cost data."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "cost_accumulator": {"previous": {"tokens": 50, "cost": 0.01}},
            "events": [],
        }

        classification = {"task_type": "bug", "complexity": "medium", "reasoning": ""}
        mock_llm = MockLLMProvider(response_content=json.dumps(classification))

        result = await classify_node(state, mock_llm)

        assert "previous" in result["cost_accumulator"]
        assert "classifier" in result["cost_accumulator"]
        assert result["cost_accumulator"]["previous"]["tokens"] == 50


class TestAssembleNode(unittest.IsolatedAsyncioTestCase):
    """Test the assemble_node function."""

    async def test_assemble_node_builds_pipeline(self):
        """Test assemble_node builds pipeline from agents."""
        from rigovo.domain.entities.agent import Agent

        state: TaskState = {
            "task_id": "task-1",
            "classification": {
                "task_type": "feature",
                "complexity": "high",
            },
            "events": [],
        }

        # Create mock agents
        agent1 = MagicMock(spec=Agent)
        agent1.id = "agent-1"
        agent1.name = "Backend Engineer"
        agent1.role = "backend"
        agent1.system_prompt = "You are a backend engineer."
        agent1.llm_model = "claude-sonnet-4-5-20250929"
        agent1.tools = []
        agent1.enrichment = MagicMock()
        agent1.enrichment.to_prompt_section.return_value = "Backend context"

        agent2 = MagicMock(spec=Agent)
        agent2.id = "agent-2"
        agent2.name = "Frontend Engineer"
        agent2.role = "frontend"
        agent2.system_prompt = "You are a frontend engineer."
        agent2.llm_model = "claude-sonnet-4-5-20250929"
        agent2.tools = []
        agent2.enrichment = MagicMock()
        agent2.enrichment.to_prompt_section.return_value = "Frontend context"

        # Mock assembler service — assembler returns itself as pipeline to reduce mock count
        mock_assembler = MagicMock()
        mock_assembler.assemble.return_value = mock_assembler
        mock_assembler.agents = [agent1, agent2]
        mock_assembler.agent_count = 2
        mock_assembler.roles = ["backend", "frontend"]
        mock_assembler.gates_after = ["backend"]

        result = await assemble_node(
            state, agents=[agent1, agent2], assembler=mock_assembler
        )

        assert "team_config" in result
        assert result["team_config"]["pipeline_order"] == ["backend", "frontend"]
        assert result["team_config"]["agents"]["backend"]["name"] == "Backend Engineer"
        assert result["team_config"]["agents"]["frontend"]["name"] == "Frontend Engineer"
        assert result["current_agent_index"] == 0
        assert result["current_agent_role"] == "backend"
        assert result["agent_outputs"] == {}
        assert result["retry_count"] == 0
        assert result["status"] == "assembled"
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "pipeline_assembled"
        assert result["events"][0]["agent_count"] == 2

    async def test_assemble_node_empty_pipeline(self):
        """Test assemble_node with empty pipeline."""
        state: TaskState = {
            "task_id": "task-1",
            "classification": {"task_type": "feature", "complexity": "low"},
            "events": [],
        }

        mock_assembler = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.agents = []
        mock_pipeline.agent_count = 0
        mock_pipeline.roles = []
        mock_pipeline.gates_after = []
        mock_assembler.assemble.return_value = mock_pipeline

        result = await assemble_node(state, agents=[], assembler=mock_assembler)

        assert result["team_config"]["pipeline_order"] == []
        assert result["current_agent_role"] == ""


if __name__ == "__main__":
    unittest.main()
