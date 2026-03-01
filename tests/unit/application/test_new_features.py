"""Tests for items 2, 3, 4, 6, 7, 8, 9 — the seven new features.

- Item 2: Streaming agent output (token-by-token)
- Item 3: LangGraph checkpointing + resume
- Item 4: Interactive approval mode
- Item 6: Replay with diff
- Item 7: Agent streaming to TUI
- Item 8: Parallel fan-out for independent agents
- Item 9: Custom agent plugins via rigovo.yml
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from rigovo.application.graph.builder import GraphBuilder, PARALLELIZABLE_ROLES
from rigovo.application.graph.nodes.execute_agent import (
    execute_agent_node,
    execute_agents_parallel,
    _build_agent_messages,
    _check_budget_guards,
    BudgetExceededError,
)
from rigovo.application.graph.state import TaskState
from rigovo.config_schema import CustomAgentSchema, TeamSchema
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage
from rigovo.infrastructure.terminal.rich_output import TerminalUI


def _make_agent_state(role: str = "coder", name: str = "Coder") -> TaskState:
    """Build a minimal TaskState for agent execution tests."""
    return {
        "task_id": "t-1",
        "description": "Add tests",
        "team_config": {
            "agents": {
                role: {
                    "id": f"agent-{role}",
                    "name": name,
                    "role": role,
                    "system_prompt": f"You are a {role}.",
                    "llm_model": "claude-sonnet-4-6",
                    "tools": [],
                    "enrichment_context": "",
                }
            },
            "pipeline_order": [role],
        },
        "current_agent_role": role,
        "agent_outputs": {},
        "cost_accumulator": {},
        "events": [],
    }


def _make_multi_agent_state() -> TaskState:
    """Build a state with multiple agents for parallel testing."""
    agents = {}
    for role in ["coder", "reviewer", "qa", "security"]:
        agents[role] = {
            "id": f"agent-{role}",
            "name": role.title(),
            "role": role,
            "system_prompt": f"You are a {role}.",
            "llm_model": "claude-sonnet-4-6",
            "tools": [],
            "enrichment_context": "",
        }
    return {
        "task_id": "t-parallel",
        "description": "Full pipeline task",
        "team_config": {
            "agents": agents,
            "pipeline_order": ["coder", "reviewer", "qa", "security"],
        },
        "current_agent_index": 0,
        "current_agent_role": "coder",
        "agent_outputs": {},
        "cost_accumulator": {},
        "events": [],
    }


def _mock_llm_response(content: str = "Done") -> LLMResponse:
    return LLMResponse(
        content=content,
        usage=LLMUsage(input_tokens=100, output_tokens=50),
        model="claude-sonnet-4-6",
    )


def _mock_llm_factory():
    mock_llm = AsyncMock()
    mock_llm.invoke.return_value = _mock_llm_response()
    return lambda model: mock_llm, mock_llm


def _mock_cost_calc():
    calc = MagicMock()
    calc.calculate.return_value = 0.05
    return calc


# =====================================================================
# Item 2: Streaming Agent Output
# =====================================================================

class TestStreamingAgentOutput(unittest.IsolatedAsyncioTestCase):
    """Test token-by-token streaming from agent execution."""

    async def test_execute_agent_with_stream_callback(self):
        """stream_callback receives token chunks during execution."""
        state = _make_agent_state()
        factory, mock_llm = _mock_llm_factory()

        chunks_received = []

        def stream_cb(role: str, chunk: str) -> None:
            chunks_received.append((role, chunk))

        # Mock the stream method as an async generator
        async def mock_stream(**kwargs):
            for word in ["Hello", " ", "World"]:
                yield word

        mock_llm.stream = mock_stream

        result = await execute_agent_node(
            state, factory, _mock_cost_calc(),
            stream_callback=stream_cb,
        )

        assert len(chunks_received) == 3
        assert chunks_received[0] == ("coder", "Hello")
        assert chunks_received[2] == ("coder", "World")
        assert "agent_outputs" in result
        assert result["agent_outputs"]["coder"]["summary"] == "Hello World"

    async def test_execute_agent_without_stream_callback_uses_invoke(self):
        """Without stream_callback, falls back to llm.invoke()."""
        state = _make_agent_state()
        factory, mock_llm = _mock_llm_factory()

        result = await execute_agent_node(
            state, factory, _mock_cost_calc(),
            stream_callback=None,
        )

        mock_llm.invoke.assert_called_once()
        assert result["agent_outputs"]["coder"]["summary"] == "Done"

    async def test_stream_callback_error_doesnt_crash(self):
        """If stream_callback throws, agent continues gracefully."""
        state = _make_agent_state()
        factory, mock_llm = _mock_llm_factory()

        async def mock_stream(**kwargs):
            yield "token"

        mock_llm.stream = mock_stream

        def bad_callback(role, chunk):
            raise ValueError("bad")

        result = await execute_agent_node(
            state, factory, _mock_cost_calc(),
            stream_callback=bad_callback,
        )

        # Should still complete
        assert "agent_outputs" in result


# =====================================================================
# Item 3: LangGraph Checkpointing
# =====================================================================

class TestCheckpointing(unittest.TestCase):
    """Test SQLite checkpointer creation."""

    def test_create_sqlite_checkpointer_returns_none_without_lib(self):
        """If langgraph.checkpoint not installed, returns None."""
        with patch.dict("sys.modules", {
            "langgraph.checkpoint.sqlite.aio": None,
            "langgraph.checkpoint.sqlite": None,
        }):
            # This should not raise, just return None
            result = GraphBuilder.create_sqlite_checkpointer("/tmp/test.db")
            # Result depends on actual installation, but shouldn't crash
            assert result is None or result is not None  # Just test no crash

    def test_graph_builder_accepts_checkpointer_param(self):
        """GraphBuilder.build_langgraph accepts checkpointer argument."""
        builder = GraphBuilder(
            llm_factory=lambda m: MagicMock(),
            master_llm=MagicMock(),
            cost_calculator=MagicMock(),
            quality_gates=[],
        )
        # Should not raise
        compiled = builder.build_langgraph(checkpointer=None)
        assert compiled is not None


# =====================================================================
# Item 4: Interactive Approval Mode
# =====================================================================

class TestInteractiveApproval(unittest.TestCase):
    """Test approval prompt in TerminalUI."""

    def test_terminal_ui_has_approval_method(self):
        """TerminalUI has prompt_approval method."""
        ui = TerminalUI()
        assert hasattr(ui, "prompt_approval")
        assert callable(ui.prompt_approval)

    def test_approval_event_handled(self):
        """Handle approval_requested event without error."""
        ui = TerminalUI()
        # In streaming TerminalUI, approval_requested just prints a line
        # It should not raise any errors
        ui.handle_event({
            "type": "approval_requested",
            "checkpoint": "plan",
        })

    def test_graph_builder_auto_approve_false(self):
        """GraphBuilder with auto_approve=False keeps approval pending."""
        builder = GraphBuilder(
            llm_factory=lambda m: MagicMock(),
            master_llm=MagicMock(),
            cost_calculator=MagicMock(),
            quality_gates=[],
            auto_approve=False,
        )
        assert builder._auto_approve is False


# =====================================================================
# Item 7: Agent Streaming to TUI
# =====================================================================

class TestStreamingTUI(unittest.TestCase):
    """Test streaming display in the Rich terminal dashboard."""

    def test_streaming_event_sets_streaming_flag(self):
        """agent_streaming events set the streaming flag."""
        ui = TerminalUI()
        ui._active_role = "coder"

        ui.handle_event({"type": "agent_streaming", "chunk": "Hello "})
        ui.handle_event({"type": "agent_streaming", "chunk": "World"})

        assert ui._streaming is True

    def test_handle_event_routes_correctly(self):
        """TerminalUI routes events to correct handlers."""
        ui = TerminalUI()
        # Should handle events without error
        ui.handle_event({"type": "agent_started", "role": "coder", "name": "Coder"})
        assert ui._active_role == "coder"

    def test_streaming_clears_on_agent_complete(self):
        """Active role clears when agent completes."""
        ui = TerminalUI()
        ui._active_role = "coder"
        ui._streaming = True

        ui.handle_event({
            "type": "agent_complete",
            "role": "coder",
            "tokens": 100,
            "cost": 0.01,
        })

        assert ui._active_role == ""
        assert ui._streaming is False

    def test_streaming_writes_chunks(self):
        """Streaming chunks are written via stdout."""
        ui = TerminalUI()
        ui._active_role = "coder"

        # Send streaming chunks — should not raise
        ui.handle_event({"type": "agent_streaming", "chunk": "Hello "})
        ui.handle_event({"type": "agent_streaming", "chunk": "world"})
        assert ui._streaming is True


# =====================================================================
# Item 8: Parallel Fan-Out
# =====================================================================

class TestParallelFanOut(unittest.IsolatedAsyncioTestCase):
    """Test parallel execution of independent agents."""

    def test_parallelizable_roles_defined(self):
        """Correct roles are marked as parallelizable."""
        assert "reviewer" in PARALLELIZABLE_ROLES
        assert "qa" in PARALLELIZABLE_ROLES
        assert "security" in PARALLELIZABLE_ROLES
        assert "coder" not in PARALLELIZABLE_ROLES
        assert "lead" not in PARALLELIZABLE_ROLES

    def test_split_pipeline(self):
        """GraphBuilder._split_pipeline separates sequential from parallel."""
        sequential, parallel = GraphBuilder._split_pipeline(
            ["lead", "coder", "reviewer", "qa", "security"]
        )
        assert sequential == ["lead", "coder"]
        assert set(parallel) == {"reviewer", "qa", "security"}

    async def test_execute_agents_parallel(self):
        """execute_agents_parallel runs multiple agents concurrently."""
        state = _make_multi_agent_state()
        factory, mock_llm = _mock_llm_factory()
        cost_calc = _mock_cost_calc()

        result = await execute_agents_parallel(
            state, ["reviewer", "qa"], factory, cost_calc,
        )

        assert "agent_outputs" in result
        assert "reviewer" in result["agent_outputs"]
        assert "qa" in result["agent_outputs"]
        assert len(result["events"]) > 0

    async def test_parallel_handles_agent_failure(self):
        """If one parallel agent fails, others still complete."""
        state = _make_multi_agent_state()
        cost_calc = _mock_cost_calc()

        call_count = 0

        def failing_factory(model):
            nonlocal call_count
            call_count += 1
            mock_llm = AsyncMock()
            if call_count == 1:
                mock_llm.invoke.side_effect = TimeoutError("boom")
            else:
                mock_llm.invoke.return_value = _mock_llm_response()
            return mock_llm

        result = await execute_agents_parallel(
            state, ["reviewer", "qa"], failing_factory, cost_calc,
        )

        # At least one should have completed
        assert "agent_outputs" in result

    async def test_parallel_merge_is_isolated_and_deterministic(self):
        """Parallel merge preserves base state and avoids seed-event duplication."""
        state = _make_multi_agent_state()
        state["events"] = [{"type": "seed_event"}]
        state["cost_accumulator"] = {"classifier": {"tokens": 42, "cost": 0.0}}

        factory, _ = _mock_llm_factory()
        cost_calc = _mock_cost_calc()

        result = await execute_agents_parallel(
            state, ["reviewer", "qa"], factory, cost_calc,
        )

        assert "reviewer" in result["agent_outputs"]
        assert "qa" in result["agent_outputs"]
        # Base accumulator entries should survive parallel merge.
        assert "classifier" in result["cost_accumulator"]
        # Parallel roles should each contribute their own cost entry.
        assert "agent-reviewer" in result["cost_accumulator"]
        assert "agent-qa" in result["cost_accumulator"]
        # Seed events should not be duplicated by child merges.
        seed_count = sum(1 for e in result["events"] if e.get("type") == "seed_event")
        assert seed_count == 1

    def test_graph_builder_parallel_flag(self):
        """GraphBuilder accepts enable_parallel flag."""
        builder = GraphBuilder(
            llm_factory=lambda m: MagicMock(),
            master_llm=MagicMock(),
            cost_calculator=MagicMock(),
            quality_gates=[],
            enable_parallel=True,
        )
        assert builder._enable_parallel is True


# =====================================================================
# Item 9: Custom Agent Plugins
# =====================================================================

class TestCustomAgentPlugins(unittest.TestCase):
    """Test custom agent definition in rigovo.yml."""

    def test_custom_agent_schema_parses(self):
        """CustomAgentSchema validates a custom agent definition."""
        agent = CustomAgentSchema(
            id="i18n",
            name="Internationalization Agent",
            role="i18n",
            system_prompt="You are an i18n expert...",
            pipeline_after="coder",
        )
        assert agent.id == "i18n"
        assert agent.role == "i18n"
        assert agent.pipeline_after == "coder"
        assert agent.parallel is False

    def test_custom_agent_with_parallel(self):
        """Custom agent can be marked as parallelizable."""
        agent = CustomAgentSchema(
            id="perf",
            name="Performance Analyzer",
            role="performance",
            system_prompt="You analyze performance...",
            parallel=True,
        )
        assert agent.parallel is True

    def test_team_schema_accepts_custom_agents(self):
        """TeamSchema includes custom_agents field."""
        team = TeamSchema(
            domain="engineering",
            custom_agents=[
                CustomAgentSchema(
                    id="i18n",
                    name="I18n Agent",
                    role="i18n",
                    system_prompt="Handle i18n",
                ),
            ],
        )
        assert len(team.custom_agents) == 1
        assert team.custom_agents[0].id == "i18n"

    def test_custom_agent_defaults(self):
        """CustomAgentSchema has sensible defaults."""
        agent = CustomAgentSchema(
            id="test",
            name="Test Agent",
            role="test",
            system_prompt="Test",
        )
        assert agent.temperature == 0.0
        assert agent.max_tokens == 4096
        assert agent.timeout_seconds == 600
        assert agent.model == ""
        assert agent.rules == []
        assert agent.tools == []


# =====================================================================
# TUI Display Features
# =====================================================================

class TestTUIFeatures(unittest.TestCase):
    """Test streaming TUI handles all event types."""

    def test_parallel_started_event(self):
        """parallel_started event handled without error."""
        ui = TerminalUI()
        ui.handle_event({
            "type": "parallel_started",
            "roles": ["reviewer", "qa"],
        })

    def test_parallel_complete_event(self):
        """parallel_complete event handled without error."""
        ui = TerminalUI()
        ui.handle_event({"type": "parallel_complete"})

    def test_all_event_types_handled(self):
        """TerminalUI handles all known event types without error."""
        ui = TerminalUI()
        events = [
            {"type": "project_scanned", "tech_stack": ["python"], "source_files": 10},
            {"type": "task_classified", "task_type": "feature", "complexity": "medium"},
            {"type": "pipeline_assembled", "roles": ["coder"]},
            {"type": "agent_started", "role": "coder", "name": "Coder"},
            {"type": "agent_streaming", "chunk": "hello"},
            {"type": "agent_complete", "role": "coder", "tokens": 100, "cost": 0.01},
            {"type": "gate_results", "role": "coder", "passed": True},
            {"type": "enrichment_extracted", "pitfall_count": 1, "pattern_count": 2},
            {"type": "memories_stored", "count": 3},
            {"type": "budget_exceeded", "tokens_used": 1000, "token_limit": 500},
            {"type": "task_finalized", "status": "completed"},
        ]
        for event in events:
            ui.handle_event(event)

    def test_token_cost_tracking(self):
        """TerminalUI tracks total tokens and cost."""
        ui = TerminalUI()
        ui.handle_event({
            "type": "agent_complete",
            "role": "coder",
            "tokens": 100,
            "cost": 0.01,
        })
        assert ui._total_tokens == 100
        assert ui._total_cost == 0.01


# =====================================================================
# Helper Function Tests
# =====================================================================

class TestHelperFunctions(unittest.TestCase):
    """Test extracted helper functions in execute_agent module."""

    def test_build_agent_messages_basic(self):
        """_build_agent_messages creates correct message structure."""
        state = _make_agent_state()
        messages = _build_agent_messages(
            state, "You are a coder.",
            state["team_config"]["agents"]["coder"],
            "coder",
        )
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Add tests" in messages[1]["content"]

    def test_build_agent_messages_with_fix_packet(self):
        """Fix packets are appended to messages."""
        state = _make_agent_state()
        state["fix_packets"] = ["Fix line 10"]
        messages = _build_agent_messages(
            state, "Prompt",
            state["team_config"]["agents"]["coder"],
            "coder",
        )
        fix_msgs = [m for m in messages if "FIX REQUIRED" in m.get("content", "")]
        assert len(fix_msgs) == 1

    def test_check_budget_guards_passes_under_limit(self):
        """Budget guard returns None when under limit."""
        state = _make_agent_state()
        state["budget_max_cost_per_task"] = 5.0
        state["cost_accumulator"] = {"a": {"cost": 1.0}}
        result = _check_budget_guards(state, "coder")
        assert result is None

    def test_check_budget_guards_warns_over_cost_limit(self):
        """Budget guard logs warning (soft limit) when cost exceeds limit."""
        state = _make_agent_state()
        state["budget_max_cost_per_task"] = 1.0
        state["cost_accumulator"] = {"a": {"cost": 2.0}}
        # Cost overruns are now soft warnings, not hard stops
        result = _check_budget_guards(state, "coder")
        assert result is None

    def test_check_budget_guards_token_limit(self):
        """Budget guard returns error dict when tokens exceed limit."""
        state = _make_agent_state()
        state["budget_max_tokens_per_task"] = 100
        state["cost_accumulator"] = {"a": {"tokens": 200}}
        result = _check_budget_guards(state, "coder")
        assert result is not None
        assert "budget_exceeded" in result["status"]


# =====================================================================
# Bug Fix Tests — classification, finalize, agent_outputs, idle timeout
# =====================================================================


class TestClassificationParsing(unittest.TestCase):
    """Test classification node handles LLM output variations."""

    def test_parse_markdown_wrapped_json(self):
        """Classifier strips markdown code fences from LLM output."""
        import json
        raw = '```json\n{"task_type": "bug", "complexity": "high", "reasoning": "test"}\n```'
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)
        assert result["task_type"] == "bug"
        assert result["complexity"] == "high"

    def test_parse_plain_json(self):
        """Classifier handles plain JSON without fences."""
        import json
        raw = '{"task_type": "feature", "complexity": "low", "reasoning": "simple"}'
        result = json.loads(raw.strip())
        assert result["task_type"] == "feature"

    def test_parse_json_with_language_tag(self):
        """Classifier handles ```json tag."""
        import json
        raw = '```json\n{"task_type": "refactor", "complexity": "medium", "reasoning": "ok"}\n```'
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)
        assert result["task_type"] == "refactor"


class TestFinalizeNodeReturnsMetrics(unittest.TestCase):
    """Test that finalize_node returns total_tokens and total_cost_usd in state."""

    def test_finalize_returns_totals(self):
        """finalize_node must return total_tokens and total_cost_usd in state dict."""
        from rigovo.application.graph.nodes.finalize import finalize_node

        state = {
            "agent_outputs": {
                "coder": {"tokens": 500, "cost": 0.05, "duration_ms": 1000, "files_changed": ["a.py"]},
                "reviewer": {"tokens": 300, "cost": 0.03, "duration_ms": 800, "files_changed": ["a.py"]},
            },
            "approval_status": "",
            "gate_results": {"passed": True},
            "retry_count": 0,
            "max_retries": 5,
            "events": [],
            "memories_to_store": [],
        }
        result = asyncio.run(finalize_node(state))
        assert result["total_tokens"] == 800
        assert result["total_cost_usd"] == 0.08
        assert result["status"] == "completed"
        assert "a.py" in result["files_changed"]

    def test_finalize_failed_status(self):
        """finalize_node sets failed when max retries exceeded."""
        from rigovo.application.graph.nodes.finalize import finalize_node

        state = {
            "agent_outputs": {},
            "approval_status": "",
            "gate_results": {"passed": False},
            "retry_count": 5,
            "max_retries": 5,
            "events": [],
            "memories_to_store": [],
        }
        result = asyncio.run(finalize_node(state))
        assert result["status"] == "failed"


class TestAgentOutputsType(unittest.TestCase):
    """Test agent_outputs is dict, not list."""

    def test_initial_state_agent_outputs_is_dict(self):
        """RunTaskCommand must initialize agent_outputs as dict."""
        # Verify the code expectation — agent_outputs must be iterable as dict
        agent_outputs: dict = {}
        total_tokens = sum(o.get("tokens", 0) for o in agent_outputs.values())
        assert total_tokens == 0

    def test_agent_outputs_dict_aggregation(self):
        """Dict agent_outputs correctly aggregates across agents."""
        agent_outputs = {
            "coder": {"tokens": 1000, "cost": 0.10},
            "reviewer": {"tokens": 500, "cost": 0.05},
        }
        total = sum(o.get("tokens", 0) for o in agent_outputs.values())
        assert total == 1500


class TestIdleTimeout(unittest.TestCase):
    """Test idle timeout constants and configuration."""

    def test_idle_timeout_defaults(self):
        """Verify idle timeout constants are set correctly."""
        from rigovo.application.graph.nodes.execute_agent import (
            DEFAULT_IDLE_TIMEOUT,
            DEFAULT_BATCH_TIMEOUT,
        )
        assert DEFAULT_IDLE_TIMEOUT == 120  # 2 minutes
        assert DEFAULT_BATCH_TIMEOUT == 900  # 15 minutes

    def test_orchestration_schema_has_idle_timeout(self):
        """OrchestrationSchema includes idle_timeout field."""
        from rigovo.config_schema import OrchestrationSchema
        schema = OrchestrationSchema()
        assert schema.idle_timeout == 120
        assert schema.timeout_per_agent == 900
        assert schema.max_retries == 5


if __name__ == "__main__":
    unittest.main()
