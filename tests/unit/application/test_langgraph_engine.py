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
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from rigovo.application.graph.builder import GraphBuilder
from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.quality import GateResult, GateStatus, Violation, ViolationSeverity
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage
from rigovo.domain.interfaces.quality_gate import GateInput, QualityGate

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
            # If tools are provided, simulate a write_file tool call on first invocation
            # then return text on follow-up (after tool results)
            has_tool_result = any(
                isinstance(m.get("content"), list)
                and any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in m.get("content", [])
                )
                for m in messages
            )
            if tools and not has_tool_result:
                # First call with tools: return a write_file tool call
                return LLMResponse(
                    content="",
                    usage=LLMUsage(input_tokens=80, output_tokens=40),
                    model=self.model_name,
                    tool_calls=[{
                        "id": "toolu_mock_01",
                        "name": "write_file",
                        "input": {
                            "path": "src/feature.py",
                            "content": "# Implemented feature\ndef feature():\n    pass\n",
                        },
                    }],
                )
            content = "Implemented the requested feature. All files updated."

        return LLMResponse(
            content=content,
            usage=LLMUsage(input_tokens=80, output_tokens=40),
            model=self.model_name,
        )

    async def stream(self, *args: Any, **kwargs: Any) -> list:
        return []


class _AlwaysFailGate(QualityGate):
    @property
    def gate_id(self) -> str:
        return "rigour"

    @property
    def name(self) -> str:
        return "Rigour"

    async def run(self, gate_input: GateInput) -> GateResult:
        return GateResult(
            status=GateStatus.FAILED,
            gates_run=1,
            gates_passed=0,
            violations=[
                Violation(
                    gate_id="rigour-check",
                    message="Missing verification",
                    severity=ViolationSeverity.ERROR,
                    file_path=(gate_input.files_changed or ["src/feature.py"])[0],
                    suggestion="Add verification and tests",
                )
            ],
        )


_ROLE_ORDER = {"lead": 0, "planner": 1, "coder": 2, "reviewer": 3, "qa": 4, "security": 5}


def _make_mock_agent(role: str, name: str) -> Agent:
    """Create a mock Agent entity for testing."""
    # Default tools by role (matching domains/engineering/tools.py)
    default_tools = {
        "coder": ["read_file", "write_file", "list_directory", "search_codebase", "run_command"],
        "planner": ["read_file", "list_directory", "search_codebase"],
        "reviewer": ["read_file", "list_directory", "search_codebase"],
        "qa": ["read_file", "write_file", "list_directory", "search_codebase", "run_command"],
        "security": ["read_file", "search_codebase", "run_command"],
    }
    agent = MagicMock(spec=Agent)
    agent.id = f"agent-{role}"
    agent.name = name
    agent.role = role
    agent.system_prompt = f"You are the {name}."
    agent.llm_model = "mock-model"
    agent.tools = default_tools.get(role, [])
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
            "execute_agent", "verify_execution", "quality_check", "route_next",
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

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="rigovo_test_")

    def _make_initial_state(self) -> TaskState:
        return {
            "task_id": "test-task-001",
            "workspace_id": "ws-001",
            "description": "Add JWT authentication to the API",
            "project_root": self._tmp_dir,
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

    async def test_runtime_risk_approval_uses_approval_handler_and_retries(self):
        """GraphBuilder should pause on risky runtime action and continue after approval."""
        builder = self._make_builder()
        approval_handler = MagicMock(
            return_value={"approval_status": "approved", "approval_feedback": "approved by test"}
        )
        builder._approval_handler = approval_handler
        builder._auto_approve = False

        state = self._make_initial_state()
        state["current_agent_role"] = "coder"
        state["team_config"] = {
            "agents": {
                "coder": {
                    "id": "agent-coder",
                    "name": "Coder",
                    "role": "coder",
                    "system_prompt": "You are a coder.",
                    "llm_model": "mock-model",
                    "tools": ["run_command"],
                }
            }
        }

        first = {
            "status": "awaiting_runtime_approval",
            "approval_status": "pending",
            "approval_data": {
                "checkpoint": "risk_action_required",
                "summary": "Deploy to protected environment",
                "current_role": "coder",
                "tool_name": "run_command",
                "kind": "deploy",
                "requires_human_approval": True,
            },
            "events": [
                {
                    "type": "approval_required",
                    "checkpoint": "risk_action_required",
                    "role": "coder",
                    "summary": "Deploy to protected environment",
                    "tool_name": "run_command",
                    "kind": "deploy",
                }
            ],
            "required_approval_actions": [
                {
                    "type": "approval_required",
                    "checkpoint": "risk_action_required",
                    "role": "coder",
                    "summary": "Deploy to protected environment",
                    "tool_name": "run_command",
                    "kind": "deploy",
                }
            ],
        }
        second = {
            "status": "agent_coder_complete",
            "events": [{"type": "agent_complete", "role": "coder"}],
            "agent_outputs": {"coder": {"summary": "done", "files_changed": ["src/feature.py"]}},
        }

        with patch(
            "rigovo.application.graph.builder.execute_agent_node",
            new=AsyncMock(side_effect=[first, second]),
        ) as mock_execute:
            result = await builder._run_execute_with_budget_approval(state)

        assert result["status"] == "agent_coder_complete"
        assert approval_handler.call_count == 1
        assert any(e.get("type") == "approval_granted" for e in result["events"])
        assert result.get("required_approval_actions") == []
        assert mock_execute.await_count == 2

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

    async def test_golden_remediation_exhausts_with_fix_packet_and_lock(self):
        """A failing gate should drive remediation state and eventually fail deterministically."""
        builder = self._make_builder(quality_gates=[_AlwaysFailGate()])
        compiled = builder.build_langgraph()

        state = self._make_initial_state()
        state["max_retries"] = 2

        result = await compiled.ainvoke(state)

        assert result["status"] == "failed"
        assert result["retry_count"] >= 2
        assert result["active_fix_packet"]["role"] == "coder-1"
        assert result["downstream_lock_reason"] == "awaiting gate remediation by coder-1"
        assert any(
            isinstance(event, dict) and event.get("type") == "fix_packet_created"
            for event in result.get("events", [])
        )

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
        cmd._event_emitter = None  # No emitter in test
        with tempfile.TemporaryDirectory(prefix="rigovo_langgraph_cmd_") as tmp_dir:
            # Use an isolated tiny workspace so scan_project is deterministic and fast.
            cmd._project_root = Path(tmp_dir)
            state: TaskState = {
                "task_id": "t-1",
                "workspace_id": "ws-1",
                "description": "Test task",
                "project_root": tmp_dir,
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
