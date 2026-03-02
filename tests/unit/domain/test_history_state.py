"""Tests for History State — checkpoint timeline and resume intelligence.

Covers:
- CheckpointRecord creation and serialization
- CheckpointTimeline recording, querying, and serialization
- ResumeContext building and context section generation
- HeartbeatTracker stale detection
- HistoryStateManager orchestration
- Sequential resume skip set computation
- Edge cases (empty timeline, max checkpoints, missing fields)
"""

from __future__ import annotations

import time
import unittest

from rigovo.domain.services.history_state import (
    STALE_TASK_THRESHOLD_SECONDS,
    MAX_CHECKPOINT_SNAPSHOTS,
    CheckpointRecord,
    CheckpointTimeline,
    CheckpointType,
    HeartbeatTracker,
    HistoryStateManager,
    ResumeContext,
)


# ── CheckpointRecord tests ─────────────────────────────────────────────


class TestCheckpointRecord(unittest.TestCase):
    """Test CheckpointRecord creation and serialization."""

    def test_create_minimal_record(self):
        """Minimal record with required fields only."""
        record = CheckpointRecord(
            checkpoint_id="ckpt-001",
            checkpoint_type=CheckpointType.AGENT_COMPLETED,
            checkpoint_name="planner-1 completed",
            timestamp=1000.0,
        )
        assert record.checkpoint_id == "ckpt-001"
        assert record.agent_role == ""
        assert record.completed_roles == []
        assert record.gate_passed is None

    def test_to_dict_roundtrip(self):
        """Serialization and deserialization should preserve all fields."""
        record = CheckpointRecord(
            checkpoint_id="ckpt-002",
            checkpoint_type=CheckpointType.GATE_PASSED,
            checkpoint_name="coder-1 gate passed",
            timestamp=2000.0,
            agent_role="coder",
            instance_id="backend-engineer-1",
            phase="execute_agent",
            completed_roles=["planner-1", "backend-engineer-1"],
            agent_outputs_summary={"planner-1": "Created plan"},
            files_changed=["src/app.py"],
            gate_passed=True,
            total_tokens=5000,
            total_cost_usd=0.05,
            approval_status="approved",
            error="",
        )

        data = record.to_dict()
        restored = CheckpointRecord.from_dict(data)

        assert restored.checkpoint_id == "ckpt-002"
        assert restored.checkpoint_type == CheckpointType.GATE_PASSED
        assert restored.agent_role == "coder"
        assert restored.instance_id == "backend-engineer-1"
        assert restored.completed_roles == ["planner-1", "backend-engineer-1"]
        assert restored.files_changed == ["src/app.py"]
        assert restored.gate_passed is True
        assert restored.total_tokens == 5000

    def test_from_dict_missing_fields(self):
        """Deserialization with missing fields should use defaults."""
        record = CheckpointRecord.from_dict({"checkpoint_id": "ckpt-x"})
        assert record.checkpoint_type == ""
        assert record.completed_roles == []
        assert record.total_tokens == 0


# ── CheckpointTimeline tests ──────────────────────────────────────────


class TestCheckpointTimeline(unittest.TestCase):
    """Test CheckpointTimeline recording, querying, and serialization."""

    def _make_state(self, **overrides):
        """Build a minimal state dict for testing."""
        base = {
            "completed_roles": [],
            "agent_outputs": {},
            "gate_results": {},
            "cost_accumulator": {},
            "approval_status": "",
            "approval_feedback": "",
        }
        base.update(overrides)
        return base

    def test_empty_timeline(self):
        """New timeline should be empty."""
        tl = CheckpointTimeline(task_id="task-1")
        assert tl.count == 0
        assert tl.last is None
        assert tl.completed_agents == []
        assert tl.last_successful_phase == ""
        assert tl.all_files_changed == []

    def test_record_creates_sequential_ids(self):
        """Records should get sequential checkpoint IDs."""
        tl = CheckpointTimeline(task_id="task-1")
        state = self._make_state()

        r1 = tl.record(CheckpointType.TASK_STARTED, "Task started", state)
        r2 = tl.record(CheckpointType.AGENT_COMPLETED, "planner-1 done", state)

        assert r1.checkpoint_id == "ckpt-001"
        assert r2.checkpoint_id == "ckpt-002"
        assert tl.count == 2

    def test_completed_agents_tracking(self):
        """completed_agents should track unique agent completions."""
        tl = CheckpointTimeline(task_id="task-1")
        state = self._make_state(completed_roles=["planner-1"])

        tl.record(
            CheckpointType.AGENT_COMPLETED, "planner-1 done", state,
            instance_id="planner-1",
        )
        tl.record(
            CheckpointType.AGENT_COMPLETED, "coder-1 done", state,
            instance_id="coder-1",
        )
        # Duplicate should not appear twice
        tl.record(
            CheckpointType.AGENT_COMPLETED, "planner-1 retry", state,
            instance_id="planner-1",
        )

        assert tl.completed_agents == ["planner-1", "coder-1"]

    def test_last_successful_phase(self):
        """Should return the last phase that succeeded."""
        tl = CheckpointTimeline(task_id="task-1")
        state = self._make_state()

        tl.record(CheckpointType.AGENT_COMPLETED, "agent done", state, phase="execute_agent")
        tl.record(CheckpointType.GATE_PASSED, "gate passed", state, phase="quality_check")
        tl.record(CheckpointType.GATE_FAILED, "gate failed", state, phase="quality_check")

        # GATE_FAILED is not in the "successful" list, so last is GATE_PASSED
        assert tl.last_successful_phase == "quality_check"

    def test_all_files_changed(self):
        """Should accumulate files across all checkpoints without duplicates."""
        tl = CheckpointTimeline(task_id="task-1")
        state1 = self._make_state(
            agent_outputs={"coder-1": {"files_changed": ["a.py", "b.py"]}}
        )
        state2 = self._make_state(
            agent_outputs={
                "coder-1": {"files_changed": ["a.py", "b.py"]},
                "reviewer-1": {"files_changed": ["b.py", "c.py"]},
            }
        )

        tl.record(CheckpointType.AGENT_COMPLETED, "coder done", state1)
        tl.record(CheckpointType.AGENT_COMPLETED, "reviewer done", state2)

        files = tl.all_files_changed
        assert "a.py" in files
        assert "b.py" in files
        assert "c.py" in files
        assert len(files) == 3

    def test_serialization_roundtrip(self):
        """Timeline should survive to_list → from_list roundtrip."""
        tl = CheckpointTimeline(task_id="task-1")
        state = self._make_state(completed_roles=["planner-1"])

        tl.record(CheckpointType.TASK_STARTED, "started", state)
        tl.record(
            CheckpointType.AGENT_COMPLETED, "planner done", state,
            instance_id="planner-1",
        )

        data = tl.to_list()
        restored = CheckpointTimeline.from_list("task-1", data)

        assert restored.count == 2
        assert restored.completed_agents == ["planner-1"]
        assert restored.records[0].checkpoint_type == CheckpointType.TASK_STARTED

    def test_max_checkpoints_enforced(self):
        """Timeline should enforce MAX_CHECKPOINT_SNAPSHOTS limit."""
        tl = CheckpointTimeline(task_id="task-1")
        state = self._make_state()

        for idx in range(MAX_CHECKPOINT_SNAPSHOTS + 10):
            tl.record(CheckpointType.AGENT_COMPLETED, f"agent-{idx}", state)

        assert tl.count <= MAX_CHECKPOINT_SNAPSHOTS

    def test_record_captures_cost_accumulator(self):
        """Record should capture cost data from state."""
        tl = CheckpointTimeline(task_id="task-1")
        state = self._make_state(
            cost_accumulator={
                "coder-1": {"tokens": 3000, "cost": 0.03},
                "reviewer-1": {"tokens": 1000, "cost": 0.01},
            }
        )

        record = tl.record(CheckpointType.AGENT_COMPLETED, "done", state)
        assert record.total_tokens == 4000
        assert abs(record.total_cost_usd - 0.04) < 0.001


# ── ResumeContext tests ──────────────────────────────────────────────


class TestResumeContext(unittest.TestCase):
    """Test ResumeContext building and context section generation."""

    def test_non_resuming_returns_empty_section(self):
        """Non-resuming context should produce empty section."""
        ctx = ResumeContext(is_resuming=False)
        assert ctx.to_context_section() == ""

    def test_resuming_produces_context(self):
        """Resuming context should include key information."""
        ctx = ResumeContext(
            is_resuming=True,
            resumed_from_checkpoint="coder-1 completed",
            completed_agents=["planner-1", "coder-1"],
            files_already_changed=["src/app.py"],
            previous_agent_summaries={"planner-1": "Created execution plan"},
        )

        section = ctx.to_context_section()
        assert "RESUME CONTEXT" in section
        assert "coder-1 completed" in section
        assert "planner-1, coder-1" in section
        assert "src/app.py" in section
        assert "Created execution plan" in section
        assert "Do NOT repeat work" in section

    def test_minimal_resume_context(self):
        """Resume with no prior data still produces useful section."""
        ctx = ResumeContext(is_resuming=True)
        section = ctx.to_context_section()
        assert "RESUME CONTEXT" in section
        assert "Do NOT repeat work" in section


# ── HeartbeatTracker tests ──────────────────────────────────────────


class TestHeartbeatTracker(unittest.TestCase):
    """Test HeartbeatTracker stale detection."""

    def test_new_tracker_not_stale(self):
        """Fresh tracker should not be stale."""
        tracker = HeartbeatTracker(task_id="task-1")
        assert not tracker.is_stale
        assert tracker.seconds_since_heartbeat == 0.0

    def test_recent_heartbeat_not_stale(self):
        """Recently beaten tracker should not be stale."""
        tracker = HeartbeatTracker(task_id="task-1")
        tracker.beat()
        assert not tracker.is_stale
        assert tracker.heartbeat_count == 1

    def test_old_heartbeat_is_stale(self):
        """Tracker with old heartbeat should be stale."""
        tracker = HeartbeatTracker(task_id="task-1")
        tracker.last_heartbeat = time.time() - STALE_TASK_THRESHOLD_SECONDS - 10
        assert tracker.is_stale

    def test_beat_updates_timestamp(self):
        """Each beat should update the timestamp."""
        tracker = HeartbeatTracker(task_id="task-1")
        tracker.last_heartbeat = time.time() - 1000  # Old
        assert tracker.is_stale

        tracker.beat()
        assert not tracker.is_stale
        assert tracker.heartbeat_count == 1


# ── HistoryStateManager tests ──────────────────────────────────────


class TestHistoryStateManager(unittest.TestCase):
    """Test HistoryStateManager orchestration."""

    def _make_state(self, **overrides):
        base = {
            "completed_roles": [],
            "agent_outputs": {},
            "gate_results": {},
            "cost_accumulator": {},
            "approval_status": "",
            "approval_feedback": "",
        }
        base.update(overrides)
        return base

    def test_get_or_create_timeline(self):
        """Should create timeline on first access."""
        mgr = HistoryStateManager()
        tl = mgr.get_or_create_timeline("task-1")
        assert tl.task_id == "task-1"
        assert tl.count == 0

        # Second access should return same timeline
        tl2 = mgr.get_or_create_timeline("task-1")
        assert tl2 is tl

    def test_record_checkpoint(self):
        """Should record checkpoint and return record."""
        mgr = HistoryStateManager()
        state = self._make_state()

        record = mgr.record_checkpoint(
            "task-1",
            CheckpointType.TASK_STARTED,
            "Task started",
            state,
        )

        assert record.checkpoint_type == CheckpointType.TASK_STARTED
        tl = mgr.get_or_create_timeline("task-1")
        assert tl.count == 1

    def test_build_resume_context_empty_timeline(self):
        """Resume context for unknown task should indicate resuming but be empty."""
        mgr = HistoryStateManager()
        ctx = mgr.build_resume_context("unknown-task")
        assert ctx.is_resuming is True
        assert ctx.completed_agents == []

    def test_build_resume_context_with_history(self):
        """Resume context should use data from checkpoint timeline."""
        mgr = HistoryStateManager()
        state = self._make_state(
            completed_roles=["planner-1"],
            agent_outputs={"planner-1": {"summary": "Plan created", "files_changed": ["plan.md"]}},
            cost_accumulator={"planner-1": {"tokens": 2000, "cost": 0.02}},
        )

        mgr.record_checkpoint(
            "task-1",
            CheckpointType.AGENT_COMPLETED,
            "planner-1 completed",
            state,
            instance_id="planner-1",
            phase="execute_agent",
        )

        ctx = mgr.build_resume_context("task-1")
        assert ctx.is_resuming is True
        assert "planner-1" in ctx.completed_agents
        assert ctx.resumed_from_checkpoint == "planner-1 completed"
        assert ctx.accumulated_tokens == 2000

    def test_heartbeat_and_stale_detection(self):
        """Heartbeat should prevent stale detection."""
        mgr = HistoryStateManager()
        mgr.heartbeat("task-1")
        assert mgr.get_stale_tasks() == []

        # Manually make it stale
        mgr._heartbeats["task-1"].last_heartbeat = (
            time.time() - STALE_TASK_THRESHOLD_SECONDS - 10
        )
        assert "task-1" in mgr.get_stale_tasks()

    def test_clear_task(self):
        """Clearing should remove timeline and heartbeat."""
        mgr = HistoryStateManager()
        mgr.get_or_create_timeline("task-1")
        mgr.heartbeat("task-1")

        mgr.clear_task("task-1")
        assert "task-1" not in mgr._timelines
        assert "task-1" not in mgr._heartbeats

    def test_get_skip_set(self):
        """Skip set should match completed agents from timeline."""
        mgr = HistoryStateManager()
        state = self._make_state(completed_roles=["planner-1", "coder-1"])

        mgr.record_checkpoint(
            "task-1", CheckpointType.AGENT_COMPLETED, "planner done", state,
            instance_id="planner-1",
        )
        mgr.record_checkpoint(
            "task-1", CheckpointType.AGENT_COMPLETED, "coder done", state,
            instance_id="coder-1",
        )

        skip = mgr.get_skip_set("task-1")
        assert skip == {"planner-1", "coder-1"}

    def test_get_skip_set_empty(self):
        """Skip set for unknown task should be empty."""
        mgr = HistoryStateManager()
        assert mgr.get_skip_set("unknown") == set()

    def test_load_timeline_from_persisted_data(self):
        """Should restore timeline from serialized data."""
        mgr = HistoryStateManager()

        data = [
            {
                "checkpoint_id": "ckpt-001",
                "checkpoint_type": CheckpointType.AGENT_COMPLETED,
                "checkpoint_name": "planner done",
                "timestamp": 1000.0,
                "instance_id": "planner-1",
                "completed_roles": ["planner-1"],
            },
            {
                "checkpoint_id": "ckpt-002",
                "checkpoint_type": CheckpointType.AGENT_COMPLETED,
                "checkpoint_name": "coder done",
                "timestamp": 2000.0,
                "instance_id": "coder-1",
                "completed_roles": ["planner-1", "coder-1"],
            },
        ]

        tl = mgr.load_timeline("task-1", data)
        assert tl.count == 2
        assert tl.completed_agents == ["planner-1", "coder-1"]

        # Verify resume context works with loaded timeline
        ctx = mgr.build_resume_context("task-1")
        assert "planner-1" in ctx.completed_agents
        assert "coder-1" in ctx.completed_agents


# ── Sequential resume integration tests ────────────────────────────


class TestSequentialResumeSkipSet(unittest.TestCase):
    """Test that sequential runner skip set computation works correctly."""

    def test_skip_set_from_state(self):
        """State with completed_roles should produce correct skip set."""
        state = {
            "is_resuming": True,
            "completed_roles": ["planner-1", "backend-engineer-1"],
        }
        skip_set = set(state.get("completed_roles", []))
        assert "planner-1" in skip_set
        assert "backend-engineer-1" in skip_set
        assert "reviewer-1" not in skip_set

    def test_no_skip_when_not_resuming(self):
        """Fresh execution should have empty skip set."""
        state = {"is_resuming": False, "completed_roles": []}
        if state.get("is_resuming"):
            skip_set = set(state.get("completed_roles", []))
        else:
            skip_set = set()
        assert skip_set == set()

    def test_pipeline_order_with_skips(self):
        """Simulates sequential runner skipping completed agents."""
        pipeline_order = ["planner-1", "backend-engineer-1", "reviewer-1", "qa-1"]
        skip_set = {"planner-1", "backend-engineer-1"}

        executed = []
        for instance_id in pipeline_order:
            if instance_id in skip_set:
                continue
            executed.append(instance_id)

        assert executed == ["reviewer-1", "qa-1"]


# ── Context builder resume section tests ─────────────────────────────


class TestContextBuilderResumeSection(unittest.TestCase):
    """Test that resume context integrates with context builder."""

    def test_resume_section_in_context_builder(self):
        """ContextBuilder should include resume section when provided."""
        from rigovo.application.context.context_builder import ContextBuilder

        builder = ContextBuilder()
        ctx = builder.build(
            role="coder",
            resume_context={
                "is_resuming": True,
                "resumed_from_checkpoint": "planner-1 completed",
                "completed_agents": ["planner-1"],
                "previous_agent_summaries": {"planner-1": "Created plan"},
                "files_already_changed": ["src/main.py"],
            },
        )

        full = ctx.to_full_context()
        assert "RESUME CONTEXT" in full
        assert "planner-1 completed" in full
        assert "Do NOT repeat work" in full

    def test_no_resume_section_when_not_resuming(self):
        """ContextBuilder should not include resume section for fresh tasks."""
        from rigovo.application.context.context_builder import ContextBuilder

        builder = ContextBuilder()
        ctx = builder.build(role="coder")

        full = ctx.to_full_context()
        assert "RESUME CONTEXT" not in full

    def test_resume_section_with_none_context(self):
        """None resume_context should not cause errors."""
        from rigovo.application.context.context_builder import ContextBuilder

        builder = ContextBuilder()
        ctx = builder.build(role="coder", resume_context=None)

        full = ctx.to_full_context()
        assert "RESUME CONTEXT" not in full


if __name__ == "__main__":
    unittest.main()
