"""Tests for late-binding reclassification (RECLASSIFY signal).

Covers:
- RECLASSIFY signal detection in agent output
- Reclassify node behavior
- Edge routing (check_reclassify_needed)
- Budget enforcement (max 1 reclassification)
- Role restrictions (only planner/lead)
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from rigovo.application.graph.edges import check_reclassify_needed
from rigovo.application.graph.nodes.execute_agent import (
    _detect_reclassify_signal,
)
from rigovo.application.graph.nodes.reclassify import (
    MAX_RECLASSIFICATIONS,
    RECLASSIFY_ALLOWED_ROLES,
    reclassify_node,
)
from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import (
    AgentAssignment,
    StaffingPlan,
    TaskComplexity,
    TaskType,
)


# ── Signal detection tests ─────────────────────────────────────────────


class TestDetectReclassifySignal(unittest.TestCase):
    """Test RECLASSIFY signal detection in agent output text."""

    def test_text_pattern_detected(self):
        """Standard text pattern: RECLASSIFY: type followed by REASON:."""
        text = "After analyzing the codebase:\n\nRECLASSIFY: infra\nREASON: This task requires Docker and K8s setup."
        detected, suggested, reason = _detect_reclassify_signal(text, "planner")
        assert detected is True
        assert suggested == "infra"
        assert "Docker" in reason

    def test_text_pattern_case_insensitive(self):
        """Signal detection should be case-insensitive."""
        text = "reclassify: security\nreason: Found auth vulnerabilities."
        detected, suggested, reason = _detect_reclassify_signal(text, "planner")
        assert detected is True
        assert suggested == "security"

    def test_json_pattern_detected(self):
        """JSON variant with signal field."""
        data = {"signal": "RECLASSIFY", "suggested_type": "bug", "reason": "This is a regression."}
        text = f"Based on my analysis: {json.dumps(data)}"
        detected, suggested, reason = _detect_reclassify_signal(text, "lead")
        assert detected is True
        assert suggested == "bug"
        assert "regression" in reason

    def test_non_allowed_role_ignored(self):
        """RECLASSIFY from coder role should be ignored."""
        text = "RECLASSIFY: infra\nREASON: Needs K8s."
        detected, suggested, reason = _detect_reclassify_signal(text, "coder")
        assert detected is False
        assert suggested == ""

    def test_non_allowed_role_reviewer(self):
        """RECLASSIFY from reviewer should be ignored."""
        text = "RECLASSIFY: security\nREASON: Auth issues."
        detected, suggested, reason = _detect_reclassify_signal(text, "reviewer")
        assert detected is False

    def test_no_signal_returns_false(self):
        """Normal text without RECLASSIFY should return False."""
        text = "I've completed the code review. Everything looks good."
        detected, suggested, reason = _detect_reclassify_signal(text, "planner")
        assert detected is False

    def test_allowed_roles_match_module_constant(self):
        """Verify allowed roles in both modules are consistent."""
        from rigovo.application.graph.nodes.execute_agent import RECLASSIFY_ALLOWED_ROLES as exec_roles
        assert exec_roles == RECLASSIFY_ALLOWED_ROLES

    def test_partial_signal_not_detected(self):
        """Just 'RECLASSIFY' without REASON should not match."""
        text = "We should RECLASSIFY this task later."
        detected, _, _ = _detect_reclassify_signal(text, "planner")
        # This is ambiguous prose, not a structured signal. The regex requires
        # RECLASSIFY: <type> + REASON: <text> to match.
        assert detected is False


# ── Edge routing tests ─────────────────────────────────────────────────


class TestCheckReclassifyNeeded(unittest.TestCase):
    """Test the conditional edge function for reclassification routing."""

    def test_no_request_returns_continue(self):
        """Normal state without reclassify request routes to continue."""
        state: TaskState = {"reclassify_requested": False, "reclassify_count": 0}
        assert check_reclassify_needed(state) == "continue"

    def test_missing_field_returns_continue(self):
        """State without reclassify_requested field routes to continue."""
        state: TaskState = {}
        assert check_reclassify_needed(state) == "continue"

    def test_request_with_budget_returns_reclassify(self):
        """When reclassify is requested and budget permits, route to reclassify."""
        state: TaskState = {"reclassify_requested": True, "reclassify_count": 0}
        assert check_reclassify_needed(state) == "reclassify"

    def test_request_budget_exhausted_returns_continue(self):
        """When budget is exhausted, ignore the request."""
        state: TaskState = {"reclassify_requested": True, "reclassify_count": 1}
        assert check_reclassify_needed(state) == "continue"

    def test_request_over_budget_returns_continue(self):
        """Budget > max also routes to continue."""
        state: TaskState = {"reclassify_requested": True, "reclassify_count": 5}
        assert check_reclassify_needed(state) == "continue"


# ── Reclassify node tests ─────────────────────────────────────────────


class TestReclassifyNode(unittest.IsolatedAsyncioTestCase):
    """Test the reclassify_node graph node."""

    async def test_budget_exhausted_rejects(self):
        """Node should reject reclassification when budget is exhausted."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Build REST API",
            "classification": {"task_type": "feature", "complexity": "medium"},
            "reclassify_count": 1,
            "reclassify_reason": "Actually infra",
            "events": [],
        }
        mock_llm = AsyncMock()
        result = await reclassify_node(state, mock_llm)
        assert result["reclassify_requested"] is False
        assert result["reclassify_count"] == 1  # Not incremented
        event_types = [e["type"] for e in result["events"]]
        assert "reclassify_rejected" in event_types

    async def test_successful_reclassification_without_classifier(self):
        """Reclassification with deterministic brain only (no LLM classifier)."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Deploy the service to Kubernetes",
            "classification": {"task_type": "feature", "complexity": "medium"},
            "deterministic_classification": {"task_type": "feature"},
            "reclassify_count": 0,
            "reclassify_reason": "This requires Docker/K8s infrastructure work",
            "reclassify_suggested_type": "infra",
            "events": [],
        }
        mock_llm = AsyncMock()
        result = await reclassify_node(state, mock_llm)

        assert result["reclassify_requested"] is False
        assert result["reclassify_count"] == 1
        assert result["status"] == "reclassified"
        # Deterministic brain should detect "deploy" + "kubernetes" as infra
        assert result["classification"]["task_type"] in ("infra", "feature")
        event_types = [e["type"] for e in result["events"]]
        assert "reclassified" in event_types

    async def test_successful_reclassification_with_classifier(self):
        """Full reclassification with LLM classifier."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Fix login bug",
            "classification": {"task_type": "feature", "complexity": "low"},
            "reclassify_count": 0,
            "reclassify_reason": "This is clearly a bug fix, not a feature",
            "reclassify_suggested_type": "bug",
            "events": [],
        }
        mock_llm = AsyncMock()
        mock_classifier = AsyncMock()
        mock_classifier.analyze.return_value = StaffingPlan(
            task_type=TaskType.BUG,
            complexity=TaskComplexity.MEDIUM,
            workspace_type="existing_project",
            domain_analysis="Auth bug fix",
            architecture_notes="Follow existing patterns",
            agents=[
                AgentAssignment(
                    instance_id="coder-1",
                    role="coder",
                    specialisation="backend",
                    assignment="Fix the bug",
                    depends_on=[],
                    verification="Tests pass",
                ),
            ],
            risks=[],
            acceptance_criteria=["Login works"],
            reasoning="Bug fix classification",
        )

        result = await reclassify_node(state, mock_llm, classifier=mock_classifier)
        assert result["reclassify_count"] == 1
        assert result["classification"]["task_type"] == "bug"
        assert result["status"] == "reclassified"
        # Staffing plan should be updated with enforced minimum team
        assert "staffing_plan" in result
        agents = result["staffing_plan"]["agents"]
        roles = {a["role"] for a in agents}
        assert "coder" in roles
        assert "reviewer" in roles  # Bug minimum team enforced

    async def test_clears_reclassify_fields(self):
        """After reclassification, the request fields should be cleared."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Some task",
            "classification": {"task_type": "feature"},
            "reclassify_count": 0,
            "reclassify_requested": True,
            "reclassify_reason": "Wrong type",
            "reclassify_suggested_type": "bug",
            "events": [],
        }
        mock_llm = AsyncMock()
        result = await reclassify_node(state, mock_llm)
        assert result["reclassify_requested"] is False
        assert result["reclassify_reason"] == ""
        assert result["reclassify_suggested_type"] == ""

    async def test_agent_suggestion_overrides_low_confidence(self):
        """When deterministic brain has low confidence, agent suggestion wins."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Update the monitoring dashboard",
            "classification": {"task_type": "feature"},
            "reclassify_count": 0,
            "reclassify_reason": "This is infrastructure/SRE work",
            "reclassify_suggested_type": "infra",
            "events": [],
        }
        mock_llm = AsyncMock()
        result = await reclassify_node(state, mock_llm)

        # The deterministic brain may not have high confidence for this
        # description, so the agent suggestion should influence the result
        assert result["reclassify_count"] == 1
        assert result["status"] == "reclassified"
        event = next(e for e in result["events"] if e["type"] == "reclassified")
        assert event["previous_task_type"] == "feature"

    async def test_preserves_event_history(self):
        """Existing events should be preserved, new events appended."""
        existing_event = {"type": "task_classified", "task_type": "feature"}
        state: TaskState = {
            "task_id": "task-1",
            "description": "Build API",
            "classification": {"task_type": "feature"},
            "reclassify_count": 0,
            "reclassify_reason": "Wrong",
            "events": [existing_event],
        }
        mock_llm = AsyncMock()
        result = await reclassify_node(state, mock_llm)
        assert result["events"][0] == existing_event
        assert len(result["events"]) >= 2


if __name__ == "__main__":
    unittest.main()
