"""Tests for domain entities — pure logic, no mocking."""

from uuid import uuid4

from rigovo.domain.entities.agent import Agent, AgentRole, AgentStats, EnrichmentContext
from rigovo.domain.entities.task import Task, TaskStatus, TaskType, TaskComplexity, PipelineStep
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.entities.quality import (
    GateResult, GateStatus, Violation, ViolationSeverity, FixPacket, FixItem,
)
from rigovo.domain.entities.workspace import Workspace, Plan


class TestAgentStats:
    def test_record_first_task(self):
        stats = AgentStats()
        stats.record_task(duration_ms=5000, tokens=1200, cost=0.05, passed_first_try=True)

        assert stats.tasks_completed == 1
        assert stats.total_tokens_used == 1200
        assert stats.total_cost_usd == 0.05
        assert stats.first_pass_rate == 1.0
        assert stats.avg_duration_ms == 5000

    def test_record_multiple_tasks(self):
        stats = AgentStats()
        stats.record_task(duration_ms=4000, tokens=1000, cost=0.04, passed_first_try=True)
        stats.record_task(duration_ms=6000, tokens=2000, cost=0.08, passed_first_try=False)

        assert stats.tasks_completed == 2
        assert stats.total_tokens_used == 3000
        assert stats.total_cost_usd == 0.12
        assert stats.first_pass_rate == 0.5
        assert stats.avg_duration_ms == 5000


class TestEnrichmentContext:
    def test_empty_context_produces_empty_prompt(self):
        ctx = EnrichmentContext()
        assert ctx.to_prompt_section() == ""

    def test_context_with_mistakes(self):
        ctx = EnrichmentContext(
            common_mistakes=["Missing error handling on async calls"],
        )
        prompt = ctx.to_prompt_section()
        assert "KNOWN PITFALLS" in prompt
        assert "Missing error handling" in prompt

    def test_full_context(self):
        ctx = EnrichmentContext(
            common_mistakes=["Forget CSRF on POST"],
            domain_knowledge=["Stripe requires idempotency keys"],
            pre_check_rules=["Check PCI compliance"],
            workspace_conventions=["Use Stripe SDK v12+"],
        )
        prompt = ctx.to_prompt_section()
        assert "KNOWN PITFALLS" in prompt
        assert "DOMAIN KNOWLEDGE" in prompt
        assert "PRE-CHECK RULES" in prompt
        assert "WORKSPACE CONVENTIONS" in prompt


class TestAgent:
    def test_build_full_prompt_base_only(self):
        agent = Agent(
            team_id=uuid4(),
            workspace_id=uuid4(),
            role=AgentRole.CODER,
            name="Backend Coder",
            system_prompt="You are a senior backend engineer.",
        )
        prompt = agent.build_full_prompt()
        assert "senior backend engineer" in prompt

    def test_build_full_prompt_with_enrichment(self):
        agent = Agent(
            team_id=uuid4(),
            workspace_id=uuid4(),
            role=AgentRole.CODER,
            name="Backend Coder",
            system_prompt="You are a senior backend engineer.",
            enrichment=EnrichmentContext(
                common_mistakes=["Missing null checks"],
            ),
            custom_rules=["Always use TypeScript strict mode"],
        )
        prompt = agent.build_full_prompt(
            team_context="Payment team — PCI compliant",
            project_context="Node.js + Express + Stripe",
        )
        assert "senior backend engineer" in prompt
        assert "Missing null checks" in prompt
        assert "TypeScript strict mode" in prompt
        assert "Payment team" in prompt
        assert "Node.js" in prompt


class TestTask:
    def test_lifecycle_happy_path(self, task):
        assert task.status == TaskStatus.PENDING

        task.classify(TaskType.FEATURE, TaskComplexity.HIGH)
        assert task.task_type == TaskType.FEATURE

        task.assign_team(uuid4())
        assert task.status == TaskStatus.ROUTING

        task.start()
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None

        task.complete()
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        assert task.is_terminal

    def test_rejection_at_approval(self, task):
        task.await_approval("plan_ready", {"plan": "some plan"})
        assert task.status == TaskStatus.AWAITING_APPROVAL

        task.reject("I want a different approach")
        assert task.status == TaskStatus.REJECTED
        assert task.rejected_at == "plan_ready"
        assert task.user_feedback == "I want a different approach"
        assert task.is_terminal

    def test_pipeline_aggregation(self, task):
        task.add_step(PipelineStep(
            agent_id=uuid4(), agent_role="coder", agent_name="Coder",
            total_tokens=1000, cost_usd=0.04, duration_ms=3000,
        ))
        task.add_step(PipelineStep(
            agent_id=uuid4(), agent_role="reviewer", agent_name="Reviewer",
            total_tokens=500, cost_usd=0.02, duration_ms=2000,
        ))
        task.complete()

        assert task.total_tokens == 1500
        assert task.total_cost_usd == 0.06
        assert task.duration_ms == 5000


class TestMemory:
    def test_usage_tracking(self):
        project_a = uuid4()
        project_b = uuid4()
        memory = Memory(
            workspace_id=uuid4(),
            content="Stripe webhooks need idempotency keys",
            memory_type=MemoryType.PATTERN,
            source_project_id=project_a,
        )

        memory.record_usage(project_a)
        assert memory.usage_count == 1
        assert memory.cross_project_usage == 0

        memory.record_usage(project_b)
        assert memory.usage_count == 2
        assert memory.cross_project_usage == 1
        assert memory.is_cross_project


class TestGateResult:
    def test_passed_result(self):
        result = GateResult(status=GateStatus.PASSED, score=100.0, gates_run=24, gates_passed=24)
        assert result.passed
        assert result.error_count == 0

    def test_failed_result_with_violations(self):
        result = GateResult(
            status=GateStatus.FAILED,
            score=72.5,
            violations=[
                Violation(gate_id="file-size", message="File too large", severity=ViolationSeverity.ERROR),
                Violation(gate_id="complexity", message="High complexity", severity=ViolationSeverity.WARNING),
            ],
            gates_run=24,
            gates_passed=22,
        )
        assert not result.passed
        assert result.error_count == 1
        assert result.warning_count == 1


class TestFixPacket:
    def test_to_prompt(self):
        packet = FixPacket(
            items=[
                FixItem(
                    gate_id="hallucinated-imports",
                    file_path="src/payment.ts",
                    message="Import '@stripe/webhook-utils' does not exist",
                    suggestion="Use '@stripe/stripe-js' instead",
                    severity=ViolationSeverity.ERROR,
                    line=3,
                ),
            ],
            attempt=2,
            max_attempts=3,
        )
        prompt = packet.to_prompt()
        assert "attempt 2/3" in prompt
        assert "hallucinated-imports" in prompt
        assert "src/payment.ts" in prompt
        assert "line 3" in prompt
        assert packet.has_errors
