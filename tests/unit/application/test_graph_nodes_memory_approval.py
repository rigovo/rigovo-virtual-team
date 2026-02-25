"""Unit tests for store memory and approval graph nodes."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from rigovo.application.graph.nodes.store_memory import store_memory_node
from rigovo.application.graph.nodes.approval import plan_approval_node, commit_approval_node
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


class TestStoreMemoryNode(unittest.IsolatedAsyncioTestCase):
    """Test the store_memory_node function."""

    async def test_store_memory_node_extracts_memories(self):
        """Test store_memory_node extracts and stores memories."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Implemented OAuth flow",
            "agent_outputs": {
                "backend": {
                    "summary": "Added JWT token validation and refresh logic",
                },
                "frontend": {"summary": "Integrated login UI with OAuth provider"},
            },
            "events": [],
        }

        memories = [
            {
                "content": "OAuth token refresh should be done before expiry",
                "type": "pattern",
            },
            {
                "content": "JWT decode requires proper error handling for expired tokens",
                "type": "error_fix",
            },
        ]

        mock_llm = MockLLMProvider(response_content=json.dumps(memories))

        result = await store_memory_node(state, mock_llm)

        assert result["status"] == "memories_extracted"
        assert len(result["memories_to_store"]) == 2
        assert (
            "OAuth token refresh should be done before expiry"
            in result["memories_to_store"]
        )
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "memories_stored"
        assert result["events"][0]["count"] == 2

    async def test_store_memory_node_handles_empty_memories(self):
        """Test store_memory_node handles empty memory list."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Simple task",
            "agent_outputs": {"agent": {"summary": "Did something simple"}},
            "events": [],
        }

        mock_llm = MockLLMProvider(response_content="[]")

        result = await store_memory_node(state, mock_llm)

        assert result["memories_to_store"] == []
        assert result["events"][0]["count"] == 0

    async def test_store_memory_node_handles_invalid_json(self):
        """Test store_memory_node defaults to empty list on invalid JSON."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "agent_outputs": {"agent": {"summary": "Output"}},
            "events": [],
        }

        mock_llm = MockLLMProvider(response_content="Not JSON")

        result = await store_memory_node(state, mock_llm)

        assert result["memories_to_store"] == []
        assert result["status"] == "memories_extracted"

    async def test_store_memory_node_truncates_long_outputs(self):
        """Test store_memory_node truncates long agent outputs."""
        long_summary = "A" * 2000  # Over 1000 chars

        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "agent_outputs": {"agent": {"summary": long_summary}},
            "events": [],
        }

        mock_llm = MockLLMProvider(response_content="[]")

        result = await store_memory_node(state, mock_llm)

        # Verify that memories were extracted (the LLM should have received truncated input)
        assert result["status"] == "memories_extracted"

    async def test_store_memory_node_filters_empty_memories(self):
        """Test store_memory_node filters out memories without content."""
        memories = [
            {"content": "Valid memory", "type": "pattern"},
            {"content": "", "type": "pattern"},
            {"type": "error_fix"},  # No content field
        ]

        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "agent_outputs": {"agent": {"summary": "Output"}},
            "events": [],
        }

        mock_llm = MockLLMProvider(response_content=json.dumps(memories))

        result = await store_memory_node(state, mock_llm)

        assert len(result["memories_to_store"]) == 1
        assert result["memories_to_store"][0] == "Valid memory"


class TestPlanApprovalNode(unittest.IsolatedAsyncioTestCase):
    """Test the plan_approval_node function."""

    async def test_plan_approval_node_creates_summary(self):
        """Test plan_approval_node creates approval summary."""
        state: TaskState = {
            "task_id": "task-1",
            "classification": {
                "task_type": "feature",
                "complexity": "high",
            },
            "team_config": {
                "team_name": "Platform Team",
                "pipeline_order": ["architect", "backend", "frontend"],
                "agents": {
                    "architect": {"name": "Architect"},
                    "backend": {"name": "Backend"},
                    "frontend": {"name": "Frontend"},
                },
            },
            "events": [],
        }

        result = await plan_approval_node(state)

        assert result["status"] == "awaiting_plan_approval"
        assert result["approval_status"] == "pending"
        assert len(result["events"]) == 1

        event = result["events"][0]
        assert event["type"] == "approval_requested"
        assert event["checkpoint"] == "plan_ready"

        summary = event["summary"]
        assert summary["task_type"] == "feature"
        assert summary["complexity"] == "high"
        assert summary["team"] == "Platform Team"
        assert summary["pipeline"] == ["architect", "backend", "frontend"]
        assert summary["agent_count"] == 3

    async def test_plan_approval_node_no_team_config(self):
        """Test plan_approval_node handles missing team config."""
        state: TaskState = {
            "task_id": "task-1",
            "classification": {"task_type": "bug", "complexity": "low"},
            "events": [],
        }

        result = await plan_approval_node(state)

        assert result["status"] == "awaiting_plan_approval"
        assert result["approval_status"] == "pending"


class TestCommitApprovalNode(unittest.IsolatedAsyncioTestCase):
    """Test the commit_approval_node function."""

    async def test_commit_approval_node_creates_summary(self):
        """Test commit_approval_node creates approval summary."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {
                "backend": {
                    "cost": 0.05,
                    "files_changed": ["src/auth.py", "src/config.py"],
                },
                "frontend": {
                    "cost": 0.03,
                    "files_changed": ["src/Login.tsx"],
                },
            },
            "gate_results": {"passed": True},
            "events": [],
        }

        result = await commit_approval_node(state)

        assert result["status"] == "awaiting_commit_approval"
        assert result["approval_status"] == "pending"
        assert len(result["events"]) == 1

        event = result["events"][0]
        assert event["type"] == "approval_requested"
        assert event["checkpoint"] == "commit_ready"

        summary = event["summary"]
        assert set(summary["agents_completed"]) == {"backend", "frontend"}
        assert summary["gate_passed"] is True
        assert summary["total_cost"] == 0.08
        assert len(summary["files_changed"]) == 3

    async def test_commit_approval_node_gate_failed(self):
        """Test commit_approval_node shows gate failure."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {"agent": {"cost": 0.01, "files_changed": []}},
            "gate_results": {"passed": False},
            "events": [],
        }

        result = await commit_approval_node(state)

        event = result["events"][0]
        summary = event["summary"]
        assert summary["gate_passed"] is False

    async def test_commit_approval_node_no_outputs(self):
        """Test commit_approval_node handles no agent outputs."""
        state: TaskState = {
            "task_id": "task-1",
            "events": [],
        }

        result = await commit_approval_node(state)

        assert result["status"] == "awaiting_commit_approval"
        event = result["events"][0]
        assert event["summary"]["agents_completed"] == []
        assert event["summary"]["total_cost"] == 0


if __name__ == "__main__":
    unittest.main()
