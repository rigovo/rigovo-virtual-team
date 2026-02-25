"""Integration tests for multiple graph nodes working together."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.nodes.execute_agent import execute_agent_node
from rigovo.application.graph.nodes.finalize import finalize_node
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


class TestNodeIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for multiple nodes working together."""

    async def test_classify_to_assemble_flow(self):
        """Test classification and assembly flow."""
        # 1. Classify
        initial_state: TaskState = {
            "task_id": "task-1",
            "description": "Add user authentication",
            "events": [],
        }

        classification = {
            "task_type": "feature",
            "complexity": "high",
            "reasoning": "Security implementation",
        }
        mock_llm = MockLLMProvider(response_content=json.dumps(classification))

        classify_result = await classify_node(initial_state, mock_llm)

        # 2. Assemble based on classification
        state_after_classify: TaskState = {
            **initial_state,
            **classify_result,
        }

        from rigovo.domain.entities.agent import Agent

        agent = MagicMock(spec=Agent)
        agent.id = "agent-1"
        agent.name = "Engineer"
        agent.role = "engineer"
        agent.system_prompt = "You are an engineer."
        agent.llm_model = "claude-sonnet-4-5-20250929"
        agent.tools = []
        agent.enrichment = MagicMock()
        agent.enrichment.to_prompt_section.return_value = "Context"

        mock_assembler = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.agents = [agent]
        mock_pipeline.agent_count = 1
        mock_pipeline.roles = ["engineer"]
        mock_pipeline.gates_after = []
        mock_assembler.assemble.return_value = mock_pipeline

        assemble_result = await assemble_node(
            state_after_classify, [agent], assembler=mock_assembler
        )

        # Verify flow
        assert assemble_result["status"] == "assembled"
        assert assemble_result["current_agent_role"] == "engineer"
        # Events include task_classified from classify_node + pipeline_assembled from assemble_node
        assert len(assemble_result["events"]) == 2
        assert assemble_result["events"][-1]["type"] == "pipeline_assembled"

    async def test_execute_to_finalize_flow(self):
        """Test execution to finalization flow."""
        initial_state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "Prompt",
                        "llm_model": "claude-sonnet-4-5-20250929",
                        "tools": [],
                    }
                }
            },
            "current_agent_role": "backend",
            "agent_outputs": {},
            "events": [],
        }

        # Execute agent
        mock_response = LLMResponse(
            content="Completed",
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            model="claude-sonnet-4-5-20250929",
        )
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_factory(model: str):
            return mock_llm

        mock_cost_calc = MagicMock()
        mock_cost_calc.calculate.return_value = 0.05

        execute_result = await execute_agent_node(initial_state, mock_factory, mock_cost_calc)

        # Finalize
        state_after_execute: TaskState = {
            **initial_state,
            **execute_result,
        }

        finalize_result = await finalize_node(state_after_execute)

        assert finalize_result["status"] == "completed"
        # Events: agent_started + agent_complete + task_finalized
        assert len(finalize_result["events"]) == 3
        assert finalize_result["events"][-1]["type"] == "task_finalized"


if __name__ == "__main__":
    unittest.main()
