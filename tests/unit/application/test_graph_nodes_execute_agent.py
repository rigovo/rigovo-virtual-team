"""Unit tests for execute agent graph node."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from rigovo.application.graph.nodes.execute_agent import execute_agent_node
from rigovo.application.graph.state import TaskState
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


class TestExecuteAgentNode(unittest.IsolatedAsyncioTestCase):
    """Test the execute_agent_node function."""

    async def test_execute_agent_node_basic_execution(self):
        """Test execute_agent_node executes agent with context."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Fix the login bug",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "You are a backend engineer.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                        "enrichment_context": "Context here",
                    }
                }
            },
            "current_agent_role": "backend",
            "agent_outputs": {},
            "events": [],
        }

        mock_response = LLMResponse(
            content="Fixed the login issue",
            usage=LLMUsage(input_tokens=200, output_tokens=100),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.10

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        assert "agent_outputs" in result
        assert "backend" in result["agent_outputs"]
        output = result["agent_outputs"]["backend"]
        assert output["summary"] == "Fixed the login issue"
        assert output["tokens"] == 300
        assert output["cost"] == 0.10
        assert "agent_backend_complete" in result["status"]
        assert len(result["events"]) == 2  # agent_started + agent_complete
        assert result["events"][0]["type"] == "agent_started"
        assert result["events"][1]["type"] == "agent_complete"

    async def test_execute_agent_node_with_previous_outputs(self):
        """Test execute_agent_node includes previous agent outputs in context."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Implement feature",
            "team_config": {
                "agents": {
                    "frontend": {
                        "id": "agent-2",
                        "name": "Frontend",
                        "role": "frontend",
                        "system_prompt": "You are a frontend engineer.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                        "enrichment_context": "",
                    }
                }
            },
            "current_agent_role": "frontend",
            "agent_outputs": {
                "backend": {
                    "summary": "Backend API ready at /api/feature",
                }
            },
            "events": [],
        }

        mock_response = LLMResponse(
            content="UI implemented",
            usage=LLMUsage(input_tokens=250, output_tokens=75),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.07

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        # Verify the mock was called with messages including previous output
        call_args = mock_llm.invoke.call_args
        messages = call_args.kwargs["messages"]

        # System prompt should contain previous outputs via ContextBuilder
        # Previous outputs are now injected into system prompt, not as separate messages
        assert len(messages) >= 2  # system + user task
        system_content = messages[0]["content"]
        assert "BACKEND" in system_content
        assert "Backend API ready" in system_content

    async def test_execute_agent_node_with_fix_packet(self):
        """Test execute_agent_node includes fix packet in retry context."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Fix code",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "Fix the code.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    }
                }
            },
            "current_agent_role": "backend",
            "agent_outputs": {},
            "fix_packets": ["Fix violation in src/app.py line 15"],
            "events": [],
        }

        mock_response = LLMResponse(
            content="Fixed",
            usage=LLMUsage(input_tokens=300, output_tokens=50),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.08

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        call_args = mock_llm.invoke.call_args
        messages = call_args.kwargs["messages"]

        # Should include fix packet
        assert any("[FIX REQUIRED]" in msg.get("content", "") for msg in messages)

    async def test_execute_agent_node_updates_cost_accumulator(self):
        """Test execute_agent_node updates cost accumulator."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "Prompt",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    }
                }
            },
            "current_agent_role": "backend",
            "cost_accumulator": {"previous": {"tokens": 100, "cost": 0.02}},
            "events": [],
        }

        mock_response = LLMResponse(
            content="Output",
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.05

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        assert "previous" in result["cost_accumulator"]
        assert "agent-1" in result["cost_accumulator"]
        assert result["cost_accumulator"]["agent-1"]["tokens"] == 150


if __name__ == "__main__":
    unittest.main()
