"""Tests for Master Agent services (classifier, enricher, evaluator, router)."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from rigovo.domain.entities.agent import Agent, AgentStats, EnrichmentContext
from rigovo.domain.entities.quality import GateResult, GateStatus, Violation, ViolationSeverity
from rigovo.domain.entities.task import TaskComplexity, TaskType
from rigovo.domain.entities.team import Team
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.invoke = AsyncMock()
    return llm


@pytest.fixture
def workspace_id():
    return uuid4()


@pytest.fixture
def sample_agent(workspace_id):
    return Agent(
        workspace_id=workspace_id,
        team_id=uuid4(),
        name="Test Coder",
        role="coder",
        llm_model="claude-sonnet",
        system_prompt="You are a coder.",
    )


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        usage=LLMUsage(input_tokens=100, output_tokens=50),
        model="test-model",
    )


# --- TaskClassifier Tests ---

class TestTaskClassifier:

    @pytest.mark.asyncio
    async def test_classify_feature(self, mock_llm):
        from rigovo.application.master.classifier import TaskClassifier
        mock_llm.invoke.return_value = _llm_response(json.dumps({
            "task_type": "feature", "complexity": "medium", "reasoning": "New endpoint",
        }))
        result = await TaskClassifier(mock_llm).classify("Add user profiles endpoint")
        assert result.task_type == TaskType.FEATURE
        assert result.complexity == TaskComplexity.MEDIUM

    @pytest.mark.asyncio
    async def test_classify_bug_fix(self, mock_llm):
        from rigovo.application.master.classifier import TaskClassifier
        mock_llm.invoke.return_value = _llm_response(json.dumps({
            "task_type": "bug", "complexity": "low", "reasoning": "Simple fix",
        }))
        result = await TaskClassifier(mock_llm).classify("Fix NullPointer in login")
        assert result.task_type == TaskType.BUG
        assert result.complexity == TaskComplexity.LOW

    @pytest.mark.asyncio
    async def test_classify_handles_bad_json(self, mock_llm):
        from rigovo.application.master.classifier import TaskClassifier
        mock_llm.invoke.return_value = _llm_response("I'm not sure")
        result = await TaskClassifier(mock_llm).classify("Do something")
        assert result.task_type == TaskType.FEATURE  # Default fallback

    @pytest.mark.asyncio
    async def test_classify_handles_code_fence(self, mock_llm):
        from rigovo.application.master.classifier import TaskClassifier
        mock_llm.invoke.return_value = _llm_response(
            '```json\n{"task_type": "refactor", "complexity": "high"}\n```'
        )
        result = await TaskClassifier(mock_llm).classify("Restructure auth module")
        assert result.task_type == TaskType.REFACTOR
        assert result.complexity == TaskComplexity.HIGH


# --- AgentEvaluator Tests ---

class TestAgentEvaluator:

    def test_perfect_execution(self, sample_agent):
        from rigovo.application.master.evaluator import AgentEvaluator
        evaluator = AgentEvaluator()
        gate_result = GateResult(status=GateStatus.PASSED, score=100.0, violations=[])
        result = evaluator.evaluate(sample_agent, gate_result, 10_000, 0, 2)
        assert result.quality_score == 100.0
        assert result.speed_score == 100.0
        assert not result.needs_enrichment

    def test_failed_gates_need_enrichment(self, sample_agent):
        from rigovo.application.master.evaluator import AgentEvaluator
        evaluator = AgentEvaluator()
        gate_result = GateResult(
            status=GateStatus.FAILED, score=40.0,
            violations=[Violation(gate_id="test", message="fail", severity=ViolationSeverity.ERROR)],
        )
        result = evaluator.evaluate(sample_agent, gate_result, 30_000, 1, 3)
        assert result.quality_score < 40.0
        assert result.needs_enrichment

    def test_retry_penalty(self, sample_agent):
        from rigovo.application.master.evaluator import AgentEvaluator
        evaluator = AgentEvaluator()
        gate_result = GateResult(status=GateStatus.PASSED, score=80.0, violations=[])
        result = evaluator.evaluate(sample_agent, gate_result, 20_000, 2, 1)
        assert result.quality_score == 50.0  # 80 - (2 * 15)

    def test_no_gates_returns_default(self, sample_agent):
        from rigovo.application.master.evaluator import AgentEvaluator
        result = AgentEvaluator().evaluate(sample_agent, None, 5_000, 0, 0)
        assert result.quality_score == 85.0

    def test_degradation_detection(self, sample_agent):
        from rigovo.application.master.evaluator import AgentEvaluator
        sample_agent.stats = AgentStats()
        sample_agent.stats.first_pass_rate = 0.9
        gate_result = GateResult(status=GateStatus.FAILED, score=50.0,
                                 violations=[Violation(gate_id="x", message="y", severity=ViolationSeverity.ERROR)])
        result = AgentEvaluator().evaluate(sample_agent, gate_result, 60_000, 0, 2)
        assert result.needs_attention

    def test_update_agent_stats(self, sample_agent):
        from rigovo.application.master.evaluator import AgentEvaluator, EvaluationResult
        evaluation = EvaluationResult(
            quality_score=85.0, speed_score=90.0, gate_pass_rate=1.0,
            needs_enrichment=False, needs_attention=False, summary="Good",
        )
        stats = AgentEvaluator().update_agent_stats(sample_agent, evaluation, 15_000, 500, 0.05)
        assert stats.tasks_completed == 1
        assert stats.first_pass_rate == 1.0  # gate_pass_rate=1.0 → passed_first_try=True


# --- ContextEnricher Tests ---

class TestContextEnricher:

    @pytest.mark.asyncio
    async def test_analyze_execution(self, mock_llm, sample_agent):
        from rigovo.application.master.enricher import ContextEnricher
        mock_llm.invoke.return_value = _llm_response(json.dumps({
            "known_pitfalls": ["Missing null checks"],
            "domain_knowledge": ["Uses SQLAlchemy 2.0"],
            "pre_check_rules": ["Validate input types"],
            "workspace_conventions": ["Use snake_case"],
            "reasoning": "Learned from gate failure",
        }))
        result = await ContextEnricher(mock_llm).analyze_execution(
            agent=sample_agent, execution_summary="Wrote user endpoint",
        )
        assert len(result.known_pitfalls) == 1

    def test_merge_enrichment_deduplicates(self):
        from rigovo.application.master.enricher import ContextEnricher, EnrichmentUpdate
        enricher = ContextEnricher(AsyncMock())
        existing = EnrichmentContext(common_mistakes=["Check for None"], domain_knowledge=["Uses FastAPI"])
        update = EnrichmentUpdate(
            known_pitfalls=["Check for None", "Handle timeouts"],
            domain_knowledge=["Uses FastAPI", "PostgreSQL 15"],
        )
        merged = enricher.merge_enrichment(existing, update)
        assert len(merged.common_mistakes) == 2
        assert len(merged.domain_knowledge) == 2

    def test_merge_enrichment_caps_items(self):
        from rigovo.application.master.enricher import ContextEnricher, EnrichmentUpdate
        enricher = ContextEnricher(AsyncMock())
        existing = EnrichmentContext(common_mistakes=[f"Pitfall {i}" for i in range(14)])
        update = EnrichmentUpdate(known_pitfalls=["New pitfall A", "New pitfall B"])
        merged = enricher.merge_enrichment(existing, update, max_items_per_category=15)
        assert len(merged.common_mistakes) == 15


# --- TeamRouter Tests ---

class TestTeamRouter:

    @pytest.mark.asyncio
    async def test_single_team_routes_directly(self, mock_llm, workspace_id):
        from rigovo.application.master.router import TeamRouter
        team = Team(workspace_id=workspace_id, name="Engineering", domain="engineering")
        result = await TeamRouter(mock_llm).route("Fix the login bug", [team])
        assert result.team_id == team.id
        assert result.confidence == 1.0
        mock_llm.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_team_uses_llm(self, mock_llm, workspace_id):
        from rigovo.application.master.router import TeamRouter
        team_eng = Team(workspace_id=workspace_id, name="Engineering", domain="engineering")
        team_content = Team(workspace_id=workspace_id, name="Content", domain="content")
        mock_llm.invoke.return_value = _llm_response(json.dumps({
            "team_id": str(team_eng.id), "confidence": 0.95, "reasoning": "Code task",
        }))
        result = await TeamRouter(mock_llm).route("Fix the login bug", [team_eng, team_content])
        assert result.team_id == team_eng.id
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_no_teams_raises(self, mock_llm):
        from rigovo.application.master.router import TeamRouter
        with pytest.raises(ValueError, match="No teams"):
            await TeamRouter(mock_llm).route("Fix bug", [])

    @pytest.mark.asyncio
    async def test_invalid_team_id_falls_back(self, mock_llm, workspace_id):
        from rigovo.application.master.router import TeamRouter
        team_a = Team(workspace_id=workspace_id, name="Engineering", domain="engineering")
        team_b = Team(workspace_id=workspace_id, name="Content", domain="content")
        mock_llm.invoke.return_value = _llm_response(json.dumps({
            "team_id": str(uuid4()), "confidence": 0.9,
        }))
        result = await TeamRouter(mock_llm).route("Do something", [team_a, team_b])
        assert result.team_id == team_a.id  # Falls back to first team
        assert result.confidence == 0.5
