"""Unit tests for Task entity lifecycle methods.

This test suite validates the domain logic of task state transitions:
- classify: set task type and complexity
- assign_team: route to a team
- start: mark as running
- await_approval: pause for human approval
- approve: resume after approval
- reject: user rejects at checkpoint
- complete: mark as successfully completed
- fail: mark as failed
- is_terminal: check if in final state

These tests ensure the Task entity correctly manages state transitions
and aggregates pipeline metrics.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from rigovo.domain.entities.task import (
    Task, TaskStatus, TaskType, TaskComplexity, PipelineStep,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def workspace_id():
    """Create a workspace ID."""
    return uuid4()


@pytest.fixture
def task(workspace_id):
    """Create a fresh task for testing."""
    return Task(
        workspace_id=workspace_id,
        description="Implement payment gateway",
    )


@pytest.fixture
def team_id():
    """Create a team ID."""
    return uuid4()


@pytest.fixture
def agent_id():
    """Create an agent ID."""
    return uuid4()


# ══════════════════════════════════════════════════════════════════════════════
# Classify Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskClassify:
    """Test Task.classify() method."""

    def test_classify_sets_type_and_complexity(self, task):
        """Test that classify sets task type and complexity."""
        task.classify(TaskType.FEATURE, TaskComplexity.HIGH)
        
        assert task.task_type == TaskType.FEATURE
        assert task.complexity == TaskComplexity.HIGH

    def test_classify_sets_status_to_classifying(self, task):
        """Test that classify sets status to CLASSIFYING."""
        task.classify(TaskType.BUG, TaskComplexity.MEDIUM)
        
        assert task.status == TaskStatus.CLASSIFYING

    def test_classify_all_types(self, task):
        """Test classify with all task types."""
        for task_type in TaskType:
            task.classify(task_type, TaskComplexity.LOW)
            assert task.task_type == task_type

    def test_classify_all_complexities(self, task):
        """Test classify with all complexity levels."""
        for complexity in TaskComplexity:
            task.classify(TaskType.FEATURE, complexity)
            assert task.complexity == complexity

    def test_classify_overwrites_previous_classification(self, task):
        """Test that classify overwrites previous values."""
        task.classify(TaskType.FEATURE, TaskComplexity.LOW)
        task.classify(TaskType.BUG, TaskComplexity.CRITICAL)
        
        assert task.task_type == TaskType.BUG
        assert task.complexity == TaskComplexity.CRITICAL


# ══════════════════════════════════════════════════════════════════════════════
# Assign Team Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskAssignTeam:
    """Test Task.assign_team() method."""

    def test_assign_team_sets_team_id(self, task, team_id):
        """Test that assign_team sets the team ID."""
        task.assign_team(team_id)
        
        assert task.team_id == team_id

    def test_assign_team_sets_status_to_routing(self, task, team_id):
        """Test that assign_team sets status to ROUTING."""
        task.assign_team(team_id)
        
        assert task.status == TaskStatus.ROUTING

    def test_assign_team_overwrites_previous_team(self, task):
        """Test that assign_team overwrites previous team assignment."""
        team1 = uuid4()
        team2 = uuid4()
        
        task.assign_team(team1)
        assert task.team_id == team1
        
        task.assign_team(team2)
        assert task.team_id == team2


# ══════════════════════════════════════════════════════════════════════════════
# Start Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskStart:
    """Test Task.start() method."""

    def test_start_sets_status_to_running(self, task):
        """Test that start sets status to RUNNING."""
        task.start()
        
        assert task.status == TaskStatus.RUNNING

    def test_start_sets_started_at_timestamp(self, task):
        """Test that start sets started_at timestamp."""
        before = datetime.utcnow()
        task.start()
        after = datetime.utcnow()
        
        assert task.started_at is not None
        assert before <= task.started_at <= after

    def test_start_multiple_times_updates_timestamp(self, task):
        """Test that calling start multiple times updates timestamp."""
        task.start()
        first_start = task.started_at
        
        # Small delay to ensure different timestamp
        import time
        time.sleep(0.01)
        
        task.start()
        second_start = task.started_at
        
        assert second_start >= first_start


# ══════════════════════════════════════════════════════════════════════════════
# Approval Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskAwaitApproval:
    """Test Task.await_approval() method."""

    def test_await_approval_sets_status(self, task):
        """Test that await_approval sets status to AWAITING_APPROVAL."""
        task.await_approval("plan_ready", {"plan": "test plan"})
        
        assert task.status == TaskStatus.AWAITING_APPROVAL

    def test_await_approval_sets_checkpoint(self, task):
        """Test that await_approval sets current checkpoint."""
        task.await_approval("code_ready", {})
        
        assert task.current_checkpoint == "code_ready"

    def test_await_approval_sets_approval_data(self, task):
        """Test that await_approval stores approval data."""
        data = {"plan": "implementation plan", "files": ["main.py"]}
        task.await_approval("plan_ready", data)
        
        assert task.approval_data == data

    def test_await_approval_overwrites_previous_checkpoint(self, task):
        """Test that await_approval overwrites previous checkpoint."""
        task.await_approval("plan_ready", {"plan": "v1"})
        task.await_approval("code_ready", {"code": "v2"})
        
        assert task.current_checkpoint == "code_ready"
        assert task.approval_data == {"code": "v2"}

    def test_await_approval_with_empty_data(self, task):
        """Test await_approval with empty approval data."""
        task.await_approval("checkpoint", {})
        
        assert task.approval_data == {}


class TestTaskApprove:
    """Test Task.approve() method."""

    def test_approve_sets_status_to_running(self, task):
        """Test that approve sets status back to RUNNING."""
        task.await_approval("plan_ready", {"plan": "test"})
        task.approve()
        
        assert task.status == TaskStatus.RUNNING

    def test_approve_clears_checkpoint(self, task):
        """Test that approve clears current checkpoint."""
        task.await_approval("plan_ready", {"plan": "test"})
        task.approve()
        
        assert task.current_checkpoint is None

    def test_approve_clears_approval_data(self, task):
        """Test that approve clears approval data."""
        task.await_approval("plan_ready", {"plan": "test"})
        task.approve()
        
        assert task.approval_data == {}

    def test_approve_without_prior_approval_request(self, task):
        """Test approve when no approval was requested."""
        task.approve()
        
        assert task.status == TaskStatus.RUNNING
        assert task.current_checkpoint is None


class TestTaskReject:
    """Test Task.reject() method."""

    def test_reject_sets_status_to_rejected(self, task):
        """Test that reject sets status to REJECTED."""
        task.await_approval("plan_ready", {"plan": "test"})
        task.reject("Plan is incomplete")
        
        assert task.status == TaskStatus.REJECTED

    def test_reject_sets_rejected_at_checkpoint(self, task):
        """Test that reject records which checkpoint was rejected."""
        task.await_approval("plan_ready", {"plan": "test"})
        task.reject()
        
        assert task.rejected_at == "plan_ready"

    def test_reject_stores_feedback(self, task):
        """Test that reject stores user feedback."""
        feedback = "Plan doesn't cover error handling"
        task.await_approval("plan_ready", {})
        task.reject(feedback)
        
        assert task.user_feedback == feedback

    def test_reject_sets_completed_at(self, task):
        """Test that reject sets completed_at timestamp."""
        before = datetime.utcnow()
        task.await_approval("plan_ready", {})
        task.reject()
        after = datetime.utcnow()
        
        assert task.completed_at is not None
        assert before <= task.completed_at <= after

    def test_reject_without_feedback(self, task):
        """Test reject with empty feedback."""
        task.await_approval("plan_ready", {})
        task.reject()
        
        assert task.status == TaskStatus.REJECTED
        assert task.user_feedback == ""


# ══════════════════════════════════════════════════════════════════════════════
# Completion Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskComplete:
    """Test Task.complete() method."""

    def test_complete_sets_status_to_completed(self, task):
        """Test that complete sets status to COMPLETED."""
        task.complete()
        
        assert task.status == TaskStatus.COMPLETED

    def test_complete_sets_completed_at_timestamp(self, task):
        """Test that complete sets completed_at timestamp."""
        before = datetime.utcnow()
        task.complete()
        after = datetime.utcnow()
        
        assert task.completed_at is not None
        assert before <= task.completed_at <= after

    def test_complete_aggregates_pipeline_metrics(self, task, agent_id):
        """Test that complete aggregates metrics from pipeline steps."""
        step1 = PipelineStep(
            agent_id=agent_id,
            agent_role="coder",
            agent_name="Coder",
            total_tokens=100,
            cost_usd=0.50,
            duration_ms=1000,
            retry_count=1,
        )
        step2 = PipelineStep(
            agent_id=agent_id,
            agent_role="reviewer",
            agent_name="Reviewer",
            total_tokens=50,
            cost_usd=0.25,
            duration_ms=500,
            retry_count=0,
        )
        
        task.add_step(step1)
        task.add_step(step2)
        task.complete()
        
        assert task.total_tokens == 150
        assert task.total_cost_usd == 0.75
        assert task.duration_ms == 1500
        assert task.retries == 1


class TestTaskFail:
    """Test Task.fail() method."""

    def test_fail_sets_status_to_failed(self, task):
        """Test that fail sets status to FAILED."""
        task.fail()
        
        assert task.status == TaskStatus.FAILED

    def test_fail_sets_completed_at_timestamp(self, task):
        """Test that fail sets completed_at timestamp."""
        before = datetime.utcnow()
        task.fail()
        after = datetime.utcnow()
        
        assert task.completed_at is not None
        assert before <= task.completed_at <= after

    def test_fail_stores_reason(self, task):
        """Test that fail stores failure reason."""
        reason = "Timeout after 30 seconds"
        task.fail(reason)
        
        assert task.user_feedback == reason

    def test_fail_aggregates_pipeline_metrics(self, task, agent_id):
        """Test that fail aggregates metrics from pipeline steps."""
        step = PipelineStep(
            agent_id=agent_id,
            agent_role="coder",
            agent_name="Coder",
            total_tokens=200,
            cost_usd=1.00,
            duration_ms=2000,
            retry_count=2,
        )
        
        task.add_step(step)
        task.fail("Agent crashed")
        
        assert task.total_tokens == 200
        assert task.total_cost_usd == 1.00
        assert task.duration_ms == 2000
        assert task.retries == 2

    def test_fail_without_reason(self, task):
        """Test fail with empty reason."""
        task.fail()
        
        assert task.status == TaskStatus.FAILED
        assert task.user_feedback == ""


# ══════════════════════════════════════════════════════════════════════════════
# Terminal State Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskIsTerminal:
    """Test Task.is_terminal property."""

    def test_is_terminal_for_completed(self, task):
        """Test that COMPLETED is a terminal state."""
        task.complete()
        
        assert task.is_terminal is True

    def test_is_terminal_for_failed(self, task):
        """Test that FAILED is a terminal state."""
        task.fail()
        
        assert task.is_terminal is True

    def test_is_terminal_for_rejected(self, task):
        """Test that REJECTED is a terminal state."""
        task.await_approval("plan_ready", {})
        task.reject()
        
        assert task.is_terminal is True

    def test_is_terminal_for_pending(self, task):
        """Test that PENDING is not a terminal state."""
        assert task.status == TaskStatus.PENDING
        assert task.is_terminal is False

    def test_is_terminal_for_running(self, task):
        """Test that RUNNING is not a terminal state."""
        task.start()
        
        assert task.is_terminal is False

    def test_is_terminal_for_awaiting_approval(self, task):
        """Test that AWAITING_APPROVAL is not a terminal state."""
        task.await_approval("plan_ready", {})
        
        assert task.is_terminal is False


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline Step Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskPipelineSteps:
    """Test Task pipeline step management."""

    def test_add_step_appends_to_list(self, task, agent_id):
        """Test that add_step appends to pipeline_steps."""
        step = PipelineStep(
            agent_id=agent_id,
            agent_role="coder",
            agent_name="Coder",
        )
        
        task.add_step(step)
        
        assert len(task.pipeline_steps) == 1
        assert task.pipeline_steps[0] == step

    def test_add_multiple_steps(self, task, agent_id):
        """Test adding multiple pipeline steps."""
        step1 = PipelineStep(
            agent_id=agent_id,
            agent_role="coder",
            agent_name="Coder",
        )
        step2 = PipelineStep(
            agent_id=agent_id,
            agent_role="reviewer",
            agent_name="Reviewer",
        )
        
        task.add_step(step1)
        task.add_step(step2)
        
        assert len(task.pipeline_steps) == 2
        assert task.pipeline_steps[0].agent_role == "coder"
        assert task.pipeline_steps[1].agent_role == "reviewer"

    def test_aggregate_pipeline_with_no_steps(self, task):
        """Test aggregation with no pipeline steps."""
        task.complete()
        
        assert task.total_tokens == 0
        assert task.total_cost_usd == 0.0
        assert task.duration_ms == 0
        assert task.retries == 0

    def test_aggregate_pipeline_with_multiple_steps(self, task, agent_id):
        """Test aggregation with multiple steps."""
        steps = [
            PipelineStep(
                agent_id=agent_id,
                agent_role=f"agent{i}",
                agent_name=f"Agent {i}",
                total_tokens=100 * (i + 1),
                cost_usd=0.5 * (i + 1),
                duration_ms=1000 * (i + 1),
                retry_count=i,
            )
            for i in range(3)
        ]
        
        for step in steps:
            task.add_step(step)
        
        task.complete()
        
        assert task.total_tokens == 600  # 100 + 200 + 300
        assert task.total_cost_usd == 3.0  # 0.5 + 1.0 + 1.5
        assert task.duration_ms == 6000  # 1000 + 2000 + 3000
        assert task.retries == 3  # 0 + 1 + 2


# ══════════════════════════════════════════════════════════════════════════════
# State Transition Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskStateTransitions:
    """Test valid state transitions."""

    def test_typical_success_flow(self, task, team_id):
        """Test typical successful task flow."""
        assert task.status == TaskStatus.PENDING
        
        task.classify(TaskType.FEATURE, TaskComplexity.HIGH)
        assert task.status == TaskStatus.CLASSIFYING
        
        task.assign_team(team_id)
        assert task.status == TaskStatus.ROUTING
        
        task.start()
        assert task.status == TaskStatus.RUNNING
        
        task.complete()
        assert task.status == TaskStatus.COMPLETED
        assert task.is_terminal is True

    def test_approval_flow(self, task, team_id):
        """Test task flow with approval checkpoint."""
        task.classify(TaskType.FEATURE, TaskComplexity.MEDIUM)
        task.assign_team(team_id)
        task.start()
        
        task.await_approval("plan_ready", {"plan": "test"})
        assert task.status == TaskStatus.AWAITING_APPROVAL
        
        task.approve()
        assert task.status == TaskStatus.RUNNING
        
        task.complete()
        assert task.is_terminal is True

    def test_rejection_flow(self, task, team_id):
        """Test task flow with rejection."""
        task.classify(TaskType.FEATURE, TaskComplexity.MEDIUM)
        task.assign_team(team_id)
        task.start()
        
        task.await_approval("plan_ready", {"plan": "test"})
        task.reject("Plan incomplete")
        
        assert task.is_terminal is True
        assert task.status == TaskStatus.REJECTED

    def test_failure_flow(self, task, team_id):
        """Test task flow with failure."""
        task.classify(TaskType.BUG, TaskComplexity.LOW)
        task.assign_team(team_id)
        task.start()
        
        task.fail("Timeout")
        
        assert task.is_terminal is True
        assert task.status == TaskStatus.FAILED


# ══════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ══════════════════════════════════════════════════════════════════════════════


class TestTaskEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_task_with_very_long_description(self, workspace_id):
        """Test task with very long description."""
        long_desc = "x" * 10000
        task = Task(workspace_id=workspace_id, description=long_desc)
        
        assert task.description == long_desc

    def test_task_with_special_characters_in_feedback(self, task):
        """Test task with special characters in feedback."""
        feedback = "Failed: timeout (30s), cost: $5.00, error: 'NoneType' object"
        task.fail(feedback)
        
        assert task.user_feedback == feedback

    def test_multiple_state_transitions_in_sequence(self, task, team_id):
        """Test multiple rapid state transitions."""
        for _ in range(3):
            task.classify(TaskType.FEATURE, TaskComplexity.LOW)
            task.assign_team(team_id)
            task.start()
            task.await_approval("checkpoint", {})
            task.approve()
        
        task.complete()
        assert task.is_terminal is True

    def test_task_created_at_timestamp(self, workspace_id):
        """Test that task has created_at timestamp."""
        before = datetime.utcnow()
        task = Task(workspace_id=workspace_id, description="test")
        after = datetime.utcnow()
        
        assert task.created_at is not None
        assert before <= task.created_at <= after

    def test_task_with_zero_cost_steps(self, task, agent_id):
        """Test aggregation with zero-cost steps."""
        step = PipelineStep(
            agent_id=agent_id,
            agent_role="test",
            agent_name="Test",
            total_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
        )
        
        task.add_step(step)
        task.complete()
        
        assert task.total_cost_usd == 0.0
        assert task.total_tokens == 0
