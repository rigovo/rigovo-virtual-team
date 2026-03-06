"""Unit tests for classify and assemble graph nodes."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import NAMESPACE_DNS, uuid4, uuid5

from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.route_team import route_team_node
from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import (
    AgentAssignment,
    StaffingPlan,
)
from rigovo.application.master.router import RoutingResult
from rigovo.domain.entities.task import TaskComplexity, TaskType
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

        # workspace_type is derived and added when not present in LLM response
        expected = {**classification, "workspace_type": "existing_project"}
        assert result["classification"] == expected
        assert result["status"] == "classified"
        assert "cost_accumulator" in result
        assert "classifier" in result["cost_accumulator"]
        assert result["cost_accumulator"]["classifier"]["tokens"] == 150
        # 2 events: deterministic_classified (instant) + task_classified (LLM)
        assert len(result["events"]) == 2
        event_types = [e["type"] for e in result["events"]]
        assert "deterministic_classified" in event_types
        assert "task_classified" in event_types
        assert result["supervisory_decisions"] == []
        # Find the task_classified event and verify its fields
        task_event = next(e for e in result["events"] if e["type"] == "task_classified")
        assert task_event["task_type"] == "feature"
        assert task_event["complexity"] == "high"

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
        # 2 events: deterministic_classified (instant) + task_classified (LLM)
        assert len(result["events"]) == 2
        event_types = [e["type"] for e in result["events"]]
        assert "deterministic_classified" in event_types
        assert "task_classified" in event_types

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

    async def test_classify_node_uses_master_classifier_when_provided(self):
        # Use a description without specific keywords so the deterministic brain
        # returns low confidence and the master classifier is invoked.
        # (Fast-path triggers only when confidence >= 0.85.)
        state: TaskState = {
            "task_id": "task-1",
            "description": (
                "The authentication flow has inconsistencies across different client platforms"
            ),
            "events": [],
        }
        mock_llm = AsyncMock()
        mock_classifier = AsyncMock()
        mock_classifier.analyze.return_value = StaffingPlan(
            task_type=TaskType.BUG,
            complexity=TaskComplexity.HIGH,
            workspace_type="existing_project",
            domain_analysis="Authentication bug fix",
            architecture_notes="Follow existing patterns",
            agents=[
                AgentAssignment(
                    instance_id="coder-1",
                    role="coder",
                    specialisation="fullstack",
                    assignment="Fix login bug",
                    depends_on=[],
                    verification="Tests pass",
                ),
            ],
            risks=[],
            acceptance_criteria=["Login works"],
            reasoning="Cross-cutting auth fixes",
        )

        result = await classify_node(state, mock_llm, classifier=mock_classifier)
        assert result["classification"]["task_type"] == "bug"
        assert result["classification"]["complexity"] == "high"
        assert result["cost_accumulator"]["master_agent"]["tokens"] == 0
        assert "staffing_plan" in result
        assert result["staffing_plan"]["execution_mode"] == "linear"
        assert isinstance(result["staffing_plan"]["consultation_requirements"], list)
        # enforce_minimum_team guarantees bug minimum team [coder, reviewer]
        # Mock plan had [coder-1] → enforce adds reviewer → 2 agents
        agents = result["staffing_plan"]["agents"]
        assert len(agents) >= 2, (
            f"Expected >=2 agents (minimum bug team), got {len(agents)}: "
            f"{[a['role'] for a in agents]}"
        )
        agent_roles = {a["role"] for a in agents}
        assert "coder" in agent_roles, "Bug minimum team must include coder"
        assert "reviewer" in agent_roles, "Bug minimum team must include reviewer"
        # Verify deterministic classification also present
        # With an ambiguous description the deterministic brain falls back to "feature"
        # (no keyword match) — the master classifier then upgrades it to "bug".
        assert "deterministic_classification" in result
        assert result["deterministic_classification"]["task_type"] in (
            "bug",
            "feature",
            "investigation",
        )
        # Verify deterministic_classified event fires BEFORE task_classified
        event_types = [e["type"] for e in result["events"]]
        assert "deterministic_classified" in event_types
        assert "task_classified" in event_types
        assert "master_decision" in event_types
        assert len(result["supervisory_decisions"]) == 1
        mock_llm.invoke.assert_not_called()

    async def test_classify_node_still_uses_master_classifier_for_deterministic_new_project(self):
        state: TaskState = {
            "task_id": "task-1",
            "description": "Create auth identity SaaS in Python",
            "events": [],
        }
        mock_llm = AsyncMock()
        mock_classifier = AsyncMock()
        mock_classifier.analyze.return_value = StaffingPlan(
            task_type="new_project",
            complexity=TaskComplexity.HIGH,
            workspace_type="new_project",
            domain_analysis="Greenfield auth SaaS",
            architecture_notes="Start from empty workspace",
            agents=[
                AgentAssignment(
                    instance_id="lead-1",
                    role="lead",
                    specialisation="architecture",
                    assignment="Own architecture and staffing review",
                    depends_on=[],
                    verification="Architecture approved",
                ),
                AgentAssignment(
                    instance_id="planner-1",
                    role="planner",
                    specialisation="requirements",
                    assignment="Plan the greenfield build",
                    depends_on=["lead-1"],
                    verification="Plan approved",
                ),
                AgentAssignment(
                    instance_id="coder-1",
                    role="coder",
                    specialisation="backend-api",
                    assignment="Implement the auth SaaS",
                    depends_on=["planner-1"],
                    verification="Build and tests pass",
                ),
            ],
            risks=["Greenfield drift"],
            acceptance_criteria=["Project boots from scratch"],
            reasoning="Master Brain must review greenfield product asks.",
        )

        result = await classify_node(state, mock_llm, classifier=mock_classifier)

        mock_classifier.analyze.assert_awaited_once()
        assert result["classification"]["task_type"] == "new_project"
        assert result["classification"]["workspace_type"] == "new_project"
        assert (
            result["staffing_plan"]["reasoning"]
            == "Master Brain must review greenfield product asks."
        )
        assert result["staffing_plan"]["task_type"] == "new_project"
        assert "lead" in {agent["role"] for agent in result["staffing_plan"]["agents"]}
        assert result["cost_accumulator"]["master_agent"]["tokens"] == 0
        assert result["events"][-1].get("fast_path") is not True
        assert result["supervisory_decisions"][0]["workspace_type"] == "new_project"

    async def test_classify_node_greenfield_existing_workspace_uses_new_subfolder_target(self):
        state: TaskState = {
            "task_id": "task-1",
            "description": "Create Identity api saas",
            "project_root": "/tmp/existing-repo",
            "workspace_root": "/tmp/existing-repo",
            "events": [],
            "project_snapshot": type("Snapshot", (), {"workspace_type": "existing_project"})(),
        }
        mock_llm = AsyncMock()
        mock_classifier = AsyncMock()
        mock_classifier.analyze.return_value = StaffingPlan(
            task_type=TaskType.NEW_PROJECT,
            complexity=TaskComplexity.HIGH,
            workspace_type="existing_project",
            domain_analysis="Greenfield identity api",
            architecture_notes="Use a child folder in the mounted workspace.",
            agents=[
                AgentAssignment(
                    instance_id="planner-1",
                    role="planner",
                    specialisation="requirements",
                    assignment="Plan a new identity api product",
                    depends_on=[],
                    verification="Plan approved",
                )
            ],
            risks=[],
            acceptance_criteria=["Scaffolded in a child folder"],
            reasoning="Greenfield intent inside an existing mounted boundary.",
        )

        result = await classify_node(state, mock_llm, classifier=mock_classifier)

        assert result["classification"]["workspace_type"] == "new_subfolder_project"
        assert result["classification"]["task_type"] == "new_project"
        assert result["target_mode"] == "new_subfolder_project"
        assert result["target_root"].endswith("identity-api-saas")
        assert "existing-repo/identity-api-saas" in result["target_root"]


class TestRouteTeamNode(unittest.IsolatedAsyncioTestCase):
    async def test_route_team_node_uses_master_router_when_provided(self):
        state: TaskState = {
            "task_id": "task-1",
            "workspace_id": str(uuid4()),
            "description": "Fix login issue",
            "classification": {"task_type": "bug", "complexity": "medium"},
            "events": [],
        }
        available_teams = [
            {
                "id": "engineering",
                "name": "Engineering",
                "domain": "engineering",
                "agents": {},
                "pipeline_order": [],
            },
            {
                "id": "content",
                "name": "Content",
                "domain": "content",
                "agents": {},
                "pipeline_order": [],
            },
        ]
        mock_llm = AsyncMock()
        mock_router = AsyncMock()
        engineering_uuid = uuid5(NAMESPACE_DNS, "engineering")
        mock_router.route.return_value = RoutingResult(
            team_id=engineering_uuid,
            confidence=0.96,
            reasoning="Engineering owns bug fixes",
        )

        result = await route_team_node(
            state,
            mock_llm,
            available_teams,
            router=mock_router,
        )
        assert result["team_config"]["team_id"] == "engineering"
        assert result["events"][0]["type"] == "team_routed"
        assert "confidence" in result["events"][0]
        mock_llm.invoke.assert_not_called()


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
        agent1.instance_id = "backend"
        agent1.system_prompt = "You are a backend engineer."
        agent1.llm_model = "claude-sonnet-4-6"
        agent1.tools = []
        agent1.depends_on = []
        agent1.input_contract = {}
        agent1.output_contract = {}
        agent1.enrichment = MagicMock()
        agent1.enrichment.to_prompt_section.return_value = "Backend context"

        agent2 = MagicMock(spec=Agent)
        agent2.id = "agent-2"
        agent2.name = "Frontend Engineer"
        agent2.role = "frontend"
        agent2.instance_id = "frontend"
        agent2.system_prompt = "You are a frontend engineer."
        agent2.llm_model = "claude-sonnet-4-6"
        agent2.tools = []
        agent2.depends_on = []
        agent2.input_contract = {}
        agent2.output_contract = {}
        agent2.enrichment = MagicMock()
        agent2.enrichment.to_prompt_section.return_value = "Frontend context"

        # Mock assembler service — assembler returns itself as pipeline to reduce mock count
        mock_assembler = MagicMock()
        mock_assembler.assemble.return_value = mock_assembler
        mock_assembler.agents = [agent1, agent2]
        mock_assembler.agent_count = 2
        mock_assembler.roles = ["backend", "frontend"]
        mock_assembler.gates_after = ["backend"]
        mock_assembler.instance_assignments = {}
        mock_assembler.instance_verifications = {}
        mock_assembler.instance_specialisations = {}
        mock_assembler.execution_dag = {}
        mock_assembler.parallel_groups = []

        result = await assemble_node(state, agents=[agent1, agent2], assembler=mock_assembler)

        assert "team_config" in result
        assert result["team_config"]["pipeline_order"] == ["backend", "frontend"]
        assert result["team_config"]["execution_dag"]["backend"] == []
        assert result["team_config"]["execution_dag"]["frontend"] == ["backend"]
        assert result["ready_roles"] == ["backend"]
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
        mock_pipeline.execution_dag = {}
        mock_pipeline.parallel_groups = []
        mock_pipeline.instance_assignments = {}
        mock_pipeline.instance_verifications = {}
        mock_pipeline.instance_specialisations = {}
        mock_assembler.assemble.return_value = mock_pipeline

        result = await assemble_node(state, agents=[], assembler=mock_assembler)

        assert result["team_config"]["pipeline_order"] == []
        assert result["team_config"]["execution_dag"] == {}
        assert result["ready_roles"] == []
        assert result["current_agent_role"] == ""


if __name__ == "__main__":
    unittest.main()
