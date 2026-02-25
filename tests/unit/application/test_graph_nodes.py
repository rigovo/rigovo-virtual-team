"""Unit tests for graph nodes — testing orchestration logic in isolation."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.nodes.quality_check import quality_check_node
from rigovo.application.graph.nodes.finalize import finalize_node
from rigovo.application.graph.nodes.execute_agent import execute_agent_node
from rigovo.application.graph.nodes.store_memory import store_memory_node
from rigovo.application.graph.nodes.approval import plan_approval_node, commit_approval_node
from rigovo.application.graph.state import TaskState, AgentOutput
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage
from rigovo.domain.interfaces.quality_gate import GateInput
from rigovo.domain.entities.quality import GateResult, Violation, GateStatus, ViolationSeverity


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


class TestQualityCheckNode(unittest.IsolatedAsyncioTestCase):
    """Test the quality_check_node function."""

    async def test_quality_check_skipped_for_non_code_role(self):
        """Test quality_check_node skips gates for non-code-producing roles."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "architect",
            "team_config": {
                "agents": {},
                "gates_after": ["backend", "frontend"],
            },
            "events": [],
        }

        mock_gate = AsyncMock()

        result = await quality_check_node(state, [mock_gate])

        assert result["gate_results"]["status"] == "skipped"
        assert result["gate_results"]["passed"] is True
        assert "gates_skipped_architect" in result["status"]
        assert len(result["events"]) == 1
        assert result["events"][0]["status"] == "skipped"

    async def test_quality_check_all_gates_passed(self):
        """Test quality_check_node when all gates pass."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "backend",
            "team_config": {
                "agents": {},
                "gates_after": ["backend"],
            },
            "agent_outputs": {
                "backend": {
                    "summary": "Fixed auth issue",
                    "files_changed": ["src/auth.py"],
                }
            },
            "project_root": "/project",
            "events": [],
        }

        # Mock passing gates
        mock_gate1 = AsyncMock()
        mock_gate1.run.return_value = GateResult(
            status="passed",
            gates_run=1,
            gates_passed=1,
            violations=[],
        )

        mock_gate2 = AsyncMock()
        mock_gate2.run.return_value = GateResult(
            status="passed",
            gates_run=1,
            gates_passed=1,
            violations=[],
        )

        result = await quality_check_node(state, [mock_gate1, mock_gate2])

        assert result["gate_results"]["passed"] is True
        assert result["gate_results"]["gates_run"] == 2
        assert result["gate_results"]["gates_passed"] == 2
        assert result["gate_results"]["violation_count"] == 0
        assert "gate_passed_backend" in result["status"]
        assert len(result["events"]) == 1
        assert result["events"][0]["passed"] is True

    async def test_quality_check_gate_failed_builds_fix_packet(self):
        """Test quality_check_node builds fix packet on gate failure."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "backend",
            "team_config": {
                "agents": {},
                "gates_after": ["backend"],
            },
            "agent_outputs": {
                "backend": {
                    "summary": "Made changes",
                    "files_changed": ["src/broken.py"],
                }
            },
            "project_root": "/project",
            "retry_count": 0,
            "max_retries": 3,
            "events": [],
        }

        violation = Violation(
            gate_id="gate-1",
            file_path="src/broken.py",
            message="Syntax error on line 10",
            suggestion="Fix the syntax error",
            severity=ViolationSeverity.ERROR,
            line=10,
        )

        mock_gate = AsyncMock()
        mock_gate.run.return_value = GateResult(
            status=GateStatus.FAILED,
            gates_run=1,
            gates_passed=0,
            violations=[violation],
        )

        result = await quality_check_node(state, [mock_gate])

        assert result["gate_results"]["passed"] is False
        assert result["gate_results"]["violation_count"] == 1
        assert "gate_failed_backend" in result["status"]
        assert result["retry_count"] == 1
        assert "fix_packets" in result
        assert len(result["fix_packets"]) == 1
        assert len(result["events"]) == 1

    async def test_quality_check_accumulates_violations(self):
        """Test quality_check_node accumulates violations from multiple gates."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "backend",
            "team_config": {
                "agents": {},
                "gates_after": ["backend"],
            },
            "agent_outputs": {
                "backend": {"summary": "Changes", "files_changed": ["src/file.py"]}
            },
            "project_root": "/project",
            "retry_count": 1,
            "max_retries": 3,
            "fix_packets": [],
            "events": [],
        }

        v1 = Violation(
            gate_id="gate-1",
            file_path="src/file.py",
            message="Issue 1",
            suggestion="Fix 1",
            severity=ViolationSeverity.ERROR,
            line=5,
        )
        v2 = Violation(
            gate_id="gate-2",
            file_path="src/file.py",
            message="Issue 2",
            suggestion="Fix 2",
            severity=ViolationSeverity.WARNING,
            line=10,
        )

        gate1 = AsyncMock()
        gate1.run.return_value = GateResult(
            status=GateStatus.FAILED,
            gates_run=1,
            gates_passed=0,
            violations=[v1],
        )

        gate2 = AsyncMock()
        gate2.run.return_value = GateResult(
            status=GateStatus.FAILED,
            gates_run=1,
            gates_passed=0,
            violations=[v2],
        )

        result = await quality_check_node(state, [gate1, gate2])

        assert result["gate_results"]["violation_count"] == 2
        assert result["retry_count"] == 2


class TestFinalizeNode(unittest.IsolatedAsyncioTestCase):
    """Test the finalize_node function."""

    async def test_finalize_node_completed_status(self):
        """Test finalize_node sets completed status on success."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {
                "backend": {
                    "tokens": 200,
                    "cost": 0.05,
                    "duration_ms": 5000,
                    "files_changed": ["src/auth.py"],
                },
                "frontend": {
                    "tokens": 150,
                    "cost": 0.03,
                    "duration_ms": 3000,
                    "files_changed": ["src/ui.tsx"],
                },
            },
            "approval_status": "approved",
            "gate_results": {"passed": True},
            "retry_count": 0,
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "completed"
        assert len(result["events"]) == 1
        event = result["events"][0]
        assert event["type"] == "task_finalized"
        assert event["agents_run"] == ["backend", "frontend"]
        assert event["total_tokens"] == 350
        assert event["total_cost"] == 0.08
        assert event["total_duration_ms"] == 8000
        assert len(event["files_changed"]) == 2

    async def test_finalize_node_rejected_status(self):
        """Test finalize_node sets rejected status when approval rejected."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {},
            "approval_status": "rejected",
            "gate_results": {},
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "rejected"
        assert result["events"][0]["status"] == "rejected"

    async def test_finalize_node_failed_status_on_error(self):
        """Test finalize_node sets failed status on error."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {},
            "error": "Agent crashed",
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "failed"

    async def test_finalize_node_failed_status_max_retries_exceeded(self):
        """Test finalize_node sets failed status when max retries exceeded."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {},
            "gate_results": {"passed": False},
            "retry_count": 3,
            "max_retries": 3,
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "failed"

    async def test_finalize_node_aggregates_unique_files(self):
        """Test finalize_node deduplicates files changed."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {
                "agent1": {"files_changed": ["file.py", "config.yml"]},
                "agent2": {"files_changed": ["file.py", "test.py"]},
            },
            "events": [],
        }

        result = await finalize_node(state)

        files = result["events"][0]["files_changed"]
        assert len(files) == 3
        assert "file.py" in files


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
                        "llm_model": "claude-sonnet-4-5-20250929",
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
            model="claude-sonnet-4-5-20250929",
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
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "agent_complete"

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
                        "llm_model": "claude-sonnet-4-5-20250929",
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
            model="claude-sonnet-4-5-20250929",
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

        # Should have system, user task, and previous backend output
        assert len(messages) >= 3
        assert any("[BACKEND output]" in msg.get("content", "") for msg in messages)

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
                        "llm_model": "claude-sonnet-4-5-20250929",
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
            model="claude-sonnet-4-5-20250929",
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
                        "llm_model": "claude-sonnet-4-5-20250929",
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
            model="claude-sonnet-4-5-20250929",
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
        # Events include agent_complete from execute_agent_node + task_finalized from finalize_node
        assert len(finalize_result["events"]) == 2
        assert finalize_result["events"][-1]["type"] == "task_finalized"


if __name__ == "__main__":
    unittest.main()
