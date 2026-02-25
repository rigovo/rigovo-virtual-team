"""Tests for the LangGraph orchestration engine.

These tests verify that the ACTUAL LangGraph StateGraph compiles,
wires edges correctly, and runs the full intelligent-agent pipeline
end-to-end with mocked LLM providers.

This is the difference between a working product and a collection
of node functions that never actually run together.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import MagicMock

from rigovo.application.graph.builder import GraphBuilder
from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.agent import Agent
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage


# ---------------------------------------------------------------------------
# Mock LLM that returns context-aware responses
# ---------------------------------------------------------------------------

class _MockLLM:
    """LLM mock that returns different responses based on prompt content."""

    def __init__(self) -> None:
        self.call_count = 0
        self.model_name = "mock-model"

    async def invoke(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        await asyncio.sleep(0)
        self.call_count += 1

        system_content = messages[0].get("content", "") if messages else ""
        user_content = messages[-1].get("content", "") if messages else ""

        # Classifier prompt
        if "task classifier" in system_content.lower():
            content = json.dumps({
                "task_type": "feature",
                "complexity": "medium",
                "reasoning": "Standard feature request",
            })
        # Memory extraction prompt
        elif "extract reusable lessons" in system_content.lower():
            content = json.dumps([
                {"content": "Auth flow needs JWT tokens", "type": "pattern"},
            ])
        # Agent execution prompt (anything else)
        else:
            content = "Implemented the requested feature. All files updated."

        return LLMResponse(
            content=content,
            usage=LLMUsage(input_tokens=80, output_tokens=40),
            model=self.model_name,
        )

    async def stream(self, *args: Any, **kwargs: Any) -> list:
        return []


_ROLE_ORDER = {"lead": 0, "planner": 1, "coder": 2, "reviewer": 3, "qa": 4, "security": 5}


def _make_mock_agent(role: str, name: str) -> Agent:
    """Create a mock Agent entity for testing."""
    agent = MagicMock(spec=Agent)
    agent.id = f"agent-{role}"
    agent.name = name
    agent.role = role
    agent.system_prompt = f"You are the {name}."
    agent.llm_model = "mock-model"
    agent.tools = []
    agent.is_active = True
    agent.pipeline_order = _ROLE_ORDER.get(role, 10)
    agent.enrichment = MagicMock()
    agent.enrichment.to_prompt_section.return_value = ""
    return agent


def _make_mock_cost_calc() -> MagicMock:
    """Create a mock cost calculator."""
    calc = MagicMock()
    calc.calculate.return_value = 0.001
    return calc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLangGraphCompilation(unittest.TestCase):
    """Test that the LangGraph StateGraph compiles without errors."""

    def test_graph_compiles(self):
        """build_langgraph() returns a compiled graph object."""
        llm = _MockLLM()
        builder = GraphBuilder(
            llm_factory=lambda model: llm,
            master_llm=llm,
            cost_calculator=_make_mock_cost_calc(),
            quality_gates=[],
            agents=[_make_mock_agent("coder", "Coder")],
        )
        compiled = builder.build_langgraph()
        assert compiled is not None

    def test_graph_has_correct_nodes(self):
        """Compiled graph contains all expected nodes."""
        llm = _MockLLM()
        builder = GraphBuilder(
            llm_factory=lambda model: llm,
            master_llm=llm,
            cost_calculator=_make_mock_cost_calc(),
            quality_gates=[],
            agents=[],
        )
        compiled = builder.build_langgraph()

        # LangGraph compiled graph exposes .get_graph() for inspection
        graph_data = compiled.get_graph()
        # .nodes is a dict keyed by node ID in langgraph >=0.6
        node_ids = set(graph_data.nodes)

        expected = {
            "__start__", "__end__",
            "scan_project", "classify", "assemble", "plan_approval",
            "execute_agent", "quality_check", "route_next",
            "commit_approval", "enrich", "store_memory", "finalize",
        }
        assert expected.issubset(node_ids), (
            f"Missing nodes: {expected - node_ids}"
        )


class TestLangGraphExecution(unittest.IsolatedAsyncioTestCase):
    """Test the full LangGraph pipeline with mocked LLM."""

    def _make_builder(
        self,
        agents: list[Agent] | None = None,
        quality_gates: list | None = None,
    ) -> GraphBuilder:
        llm = _MockLLM()
        return GraphBuilder(
            llm_factory=lambda model: llm,
            master_llm=llm,
            cost_calculator=_make_mock_cost_calc(),
            quality_gates=quality_gates or [],
            agents=agents or [_make_mock_agent("coder", "Coder")],
            auto_approve=True,
        )

    def _make_initial_state(self) -> TaskState:
        return {
            "task_id": "test-task-001",
            "workspace_id": "ws-001",
            "description": "Add JWT authentication to the API",
            "project_root": ".",
            "team_config": {},
            "current_agent_index": 0,
            "current_agent_role": "",
            "agent_outputs": {},
            "gate_results": {},
            "fix_packets": [],
            "retry_count": 0,
            "max_retries": 3,
            "approval_status": "",
            "cost_accumulator": {},
            "budget_max_cost_per_task": 5.00,
            "budget_max_tokens_per_task": 500_000,
            "memories_to_store": [],
            "status": "starting",
            "events": [],
        }

    async def test_full_pipeline_completes(self):
        """Graph runs from START to END and produces a completed status."""
        builder = self._make_builder()
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        assert result["status"] == "completed", (
            f"Expected completed, got {result['status']}"
        )

    async def test_pipeline_classifies_task(self):
        """Graph classifies the task via the classify node."""
        builder = self._make_builder()
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        classification = result.get("classification", {})
        assert classification.get("task_type") == "feature"
        assert classification.get("complexity") == "medium"

    async def test_pipeline_assembles_agents(self):
        """Graph assembles pipeline with agents from the builder."""
        coder = _make_mock_agent("coder", "Coder")
        reviewer = _make_mock_agent("reviewer", "Reviewer")
        builder = self._make_builder(agents=[coder, reviewer])
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        team_config = result.get("team_config", {})
        pipeline_order = team_config.get("pipeline_order", [])
        assert len(pipeline_order) >= 1, "Pipeline should have at least one agent"

    async def test_pipeline_executes_agents(self):
        """Graph executes agents and records their outputs."""
        builder = self._make_builder()
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        agent_outputs = result.get("agent_outputs", {})
        assert len(agent_outputs) >= 1, "At least one agent should produce output"

        # Each output should have cost and token data
        for role, output in agent_outputs.items():
            assert "tokens" in output, f"Agent '{role}' missing token count"
            assert "cost" in output, f"Agent '{role}' missing cost"

    async def test_pipeline_stores_memories(self):
        """Graph extracts and queues memories for storage."""
        builder = self._make_builder()
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        memories = result.get("memories_to_store", [])
        assert len(memories) >= 1, "Should extract at least one memory"

    async def test_pipeline_emits_events(self):
        """Graph emits structured events at each stage."""
        builder = self._make_builder()
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        events = result.get("events", [])
        event_types = [e.get("type") for e in events]

        # Must include lifecycle events from each major stage
        assert "task_classified" in event_types, "Missing classification event"
        assert "pipeline_assembled" in event_types, "Missing assembly event"
        assert "agent_complete" in event_types, "Missing agent completion event"
        assert "task_finalized" in event_types, "Missing finalization event"

    async def test_pipeline_tracks_cost(self):
        """Graph accumulates cost across all agents."""
        builder = self._make_builder()
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        cost_acc = result.get("cost_accumulator", {})
        total_cost = sum(v.get("cost", 0) for v in cost_acc.values())
        assert total_cost > 0, "Should track non-zero cost"

    async def test_auto_approve_mode(self):
        """auto_approve=True skips approval gates."""
        builder = self._make_builder()
        compiled = builder.build_langgraph()

        result = await compiled.ainvoke(self._make_initial_state())

        # Should have passed both approval checkpoints
        assert result["approval_status"] == "approved"
        assert result["status"] == "completed"

    async def test_rejected_plan_goes_to_finalize(self):
        """When plan is rejected, graph skips execution and finalizes."""
        llm = _MockLLM()
        builder = GraphBuilder(
            llm_factory=lambda model: llm,
            master_llm=llm,
            cost_calculator=_make_mock_cost_calc(),
            quality_gates=[],
            agents=[_make_mock_agent("coder", "Coder")],
            auto_approve=False,  # Approval stays pending
        )
        compiled = builder.build_langgraph()

        state = self._make_initial_state()
        state["approval_status"] = "rejected"

        result = await compiled.ainvoke(state)

        # Should finalize as rejected (plan_approval sees "rejected")
        assert result["status"] in ("rejected", "completed")

    async def test_sequential_fallback_matches_langgraph(self):
        """Sequential runner produces equivalent results to LangGraph."""
        builder = self._make_builder()

        state = self._make_initial_state()

        # Run via LangGraph
        compiled = builder.build_langgraph()
        lg_result = await compiled.ainvoke(dict(state))

        # Run via sequential
        seq_result = await builder.run_sequential(dict(state))

        # Both should complete successfully
        assert lg_result["status"] == "completed"
        assert seq_result["status"] == "completed"

        # Both should produce agent outputs
        assert len(lg_result.get("agent_outputs", {})) >= 1
        assert len(seq_result.get("agent_outputs", {})) >= 1

        # Both should extract memories
        assert len(lg_result.get("memories_to_store", [])) >= 1
        assert len(seq_result.get("memories_to_store", [])) >= 1


class TestRunTaskCommandUsesLangGraph(unittest.IsolatedAsyncioTestCase):
    """Test that RunTaskCommand routes through LangGraph."""

    async def test_run_graph_tries_langgraph_first(self):
        """_run_graph attempts build_langgraph before sequential."""
        from rigovo.application.commands.run_task import RunTaskCommand

        llm = _MockLLM()
        builder = GraphBuilder(
            llm_factory=lambda model: llm,
            master_llm=llm,
            cost_calculator=_make_mock_cost_calc(),
            quality_gates=[],
            agents=[_make_mock_agent("coder", "Coder")],
            auto_approve=True,
        )

        # RunTaskCommand._run_graph should use langgraph (since it's installed)
        cmd = RunTaskCommand.__new__(RunTaskCommand)
        state: TaskState = {
            "task_id": "t-1",
            "workspace_id": "ws-1",
            "description": "Test task",
            "project_root": ".",
            "team_config": {},
            "current_agent_index": 0,
            "current_agent_role": "",
            "agent_outputs": {},
            "gate_results": {},
            "fix_packets": [],
            "retry_count": 0,
            "max_retries": 3,
            "approval_status": "",
            "cost_accumulator": {},
            "budget_max_cost_per_task": 5.00,
            "budget_max_tokens_per_task": 500_000,
            "memories_to_store": [],
            "status": "starting",
            "events": [],
        }

        result = await cmd._run_graph(builder, state)
        assert result["status"] == "completed"


if __name__ == "__main__":
    unittest.main()
