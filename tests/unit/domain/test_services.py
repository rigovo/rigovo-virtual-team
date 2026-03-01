"""Tests for domain services — pure logic, no mocking."""

from datetime import datetime, timedelta
from uuid import uuid4

from rigovo.domain.entities.agent import Agent, AgentRole
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.entities.task import TaskType, TaskComplexity
from rigovo.domain.services.cost_calculator import CostCalculator, ModelPricing
from rigovo.domain.services.team_assembler import TeamAssemblerService, PipelineConfig
from rigovo.domain.services.memory_ranker import MemoryRanker, ScoredMemory


class TestCostCalculator:
    def setup_method(self):
        self.calc = CostCalculator()

    def test_claude_sonnet_cost(self):
        # 1000 input + 500 output at Sonnet pricing ($3/M input, $15/M output)
        cost = self.calc.calculate("claude-sonnet-4-6", 1000, 500)
        expected = (1000 / 1_000_000) * 3.00 + (500 / 1_000_000) * 15.00
        assert cost == round(expected, 6)

    def test_gpt4o_cost(self):
        cost = self.calc.calculate("gpt-4o", 2000, 1000)
        # GPT-4o pricing: $5.00/M input, $15.00/M output (Feb 2026)
        expected = (2000 / 1_000_000) * 5.00 + (1000 / 1_000_000) * 15.00
        assert cost == round(expected, 6)

    def test_unknown_model_uses_default(self):
        cost = self.calc.calculate("some-unknown-model", 1000, 500)
        expected = (1000 / 1_000_000) * 5.00 + (500 / 1_000_000) * 15.00
        assert cost == round(expected, 6)

    def test_ollama_free(self):
        cost = self.calc.calculate("ollama/llama3", 10000, 5000)
        assert cost == 0.0

    def test_estimate_task_cost(self):
        estimate = self.calc.estimate_task_cost(
            model="claude-sonnet-4-6",
            agent_count=3,
            avg_tokens_per_agent=4000,
        )
        assert estimate > 0
        assert isinstance(estimate, float)


class TestTeamAssembler:
    def setup_method(self):
        self.assembler = TeamAssemblerService()
        self.workspace_id = uuid4()
        self.team_id = uuid4()

    def _make_agent(self, role: str, order: int) -> Agent:
        return Agent(
            team_id=self.team_id,
            workspace_id=self.workspace_id,
            role=role,
            name=f"{role.title()} Agent",
            pipeline_order=order,
        )

    def test_feature_task_assembles_full_pipeline(self):
        agents = [
            self._make_agent("planner", 0),
            self._make_agent("coder", 1),
            self._make_agent("reviewer", 2),
            self._make_agent("qa", 3),
            self._make_agent("security", 4),
        ]

        pipeline = self.assembler.assemble(agents, TaskType.FEATURE, TaskComplexity.MEDIUM)

        assert pipeline.agent_count == 4  # planner, coder, reviewer, qa
        assert pipeline.roles == ["planner", "coder", "reviewer", "qa"]
        # gates_after uses instance_ids (e.g. "coder-1") not bare role names
        assert any(g.startswith("coder") for g in pipeline.gates_after)

    def test_bug_task_minimal_pipeline(self):
        agents = [
            self._make_agent("planner", 0),
            self._make_agent("coder", 1),
            self._make_agent("reviewer", 2),
            self._make_agent("qa", 3),
        ]

        pipeline = self.assembler.assemble(agents, TaskType.BUG, TaskComplexity.LOW)

        assert pipeline.roles == ["coder", "reviewer"]

    def test_high_complexity_adds_lead(self):
        agents = [
            self._make_agent("lead", 0),
            self._make_agent("coder", 1),
            self._make_agent("reviewer", 2),
            self._make_agent("qa", 3),
        ]

        pipeline = self.assembler.assemble(agents, TaskType.FEATURE, TaskComplexity.HIGH)

        assert "lead" in pipeline.roles
        assert pipeline.roles[0] == "lead"  # Lead goes first

    def test_critical_complexity_adds_security(self):
        agents = [
            self._make_agent("lead", 0),
            self._make_agent("coder", 1),
            self._make_agent("reviewer", 2),
            self._make_agent("qa", 3),
            self._make_agent("security", 4),
        ]

        pipeline = self.assembler.assemble(agents, TaskType.FEATURE, TaskComplexity.CRITICAL)

        assert "security" in pipeline.roles
        assert "lead" in pipeline.roles

    def test_missing_roles_graceful_fallback(self):
        # Team only has a coder
        agents = [self._make_agent("coder", 0)]

        pipeline = self.assembler.assemble(agents, TaskType.FEATURE, TaskComplexity.MEDIUM)

        assert pipeline.agent_count == 1
        assert pipeline.roles == ["coder"]

    def test_gates_only_after_code_producing_roles(self):
        agents = [
            self._make_agent("planner", 0),
            self._make_agent("coder", 1),
            self._make_agent("reviewer", 2),
            self._make_agent("devops", 3),
        ]

        pipeline = self.assembler.assemble(agents, TaskType.INFRA, TaskComplexity.MEDIUM)

        # Gates should trigger after code-producing roles, not reviewer
        # gates_after uses instance_ids (e.g. "coder-1", "devops-1")
        for instance_id in pipeline.gates_after:
            base_role = instance_id.rsplit("-", 1)[0] if "-" in instance_id else instance_id
            assert base_role in ("coder", "devops", "sre")


class TestMemoryRanker:
    def setup_method(self):
        self.ranker = MemoryRanker()
        self.workspace_id = uuid4()

    def test_ranking_prefers_high_similarity(self):
        now = datetime.utcnow()
        memories = [
            Memory(workspace_id=self.workspace_id, content="Low relevance", memory_type=MemoryType.PATTERN, created_at=now),
            Memory(workspace_id=self.workspace_id, content="High relevance", memory_type=MemoryType.PATTERN, created_at=now),
        ]
        similarities = [0.3, 0.9]

        ranked = self.ranker.rank(memories, similarities, now=now)

        assert ranked[0].memory.content == "High relevance"
        assert ranked[0].score > ranked[1].score

    def test_recent_memories_preferred(self):
        now = datetime.utcnow()
        old = now - timedelta(days=90)

        memories = [
            Memory(workspace_id=self.workspace_id, content="Old", memory_type=MemoryType.PATTERN, created_at=old),
            Memory(workspace_id=self.workspace_id, content="New", memory_type=MemoryType.PATTERN, created_at=now),
        ]
        similarities = [0.7, 0.7]  # Same similarity

        ranked = self.ranker.rank(memories, similarities, now=now)

        assert ranked[0].memory.content == "New"

    def test_cross_project_usage_boosts_score(self):
        now = datetime.utcnow()

        heavily_used = Memory(
            workspace_id=self.workspace_id, content="Cross-project gem",
            memory_type=MemoryType.PATTERN, created_at=now,
        )
        heavily_used.usage_count = 20
        heavily_used.cross_project_usage = 5

        fresh = Memory(
            workspace_id=self.workspace_id, content="Fresh but unused",
            memory_type=MemoryType.PATTERN, created_at=now,
        )

        memories = [fresh, heavily_used]
        similarities = [0.7, 0.7]  # Same similarity

        ranked = self.ranker.rank(memories, similarities, now=now)

        assert ranked[0].memory.content == "Cross-project gem"
