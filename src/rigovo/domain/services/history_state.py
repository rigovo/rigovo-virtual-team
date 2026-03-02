"""History State — checkpoint timeline and resume intelligence.

This module provides the structural foundation for resuming interrupted
tasks. Instead of treating checkpoints as a single "current_checkpoint"
string, we build a **checkpoint timeline** — every significant state
transition is recorded with a lightweight snapshot so that:

1. We can resume from any checkpoint (not just the last one)
2. We can inject "resume context" into agents so they know what happened
3. We can detect and recover interrupted tasks automatically
4. The sequential fallback path can skip already-completed agents

Five components:
- CheckpointRecord: A single checkpoint in the timeline
- CheckpointTimeline: Ordered history of checkpoints for a task
- ResumeContext: Assembled context injected when resuming
- HeartbeatTracker: Detects stale/interrupted tasks
- HistoryStateManager: Orchestrator that ties everything together
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# --- Configuration ---
HEARTBEAT_INTERVAL_SECONDS = 30
STALE_TASK_THRESHOLD_SECONDS = 120  # 2 minutes without heartbeat = stale
MAX_CHECKPOINT_SNAPSHOTS = 50  # Don't keep more than 50 checkpoints per task


# --- Checkpoint types ---


class CheckpointType:
    """Types of checkpoints that can be recorded."""

    AGENT_COMPLETED = "agent_completed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    GATE_PASSED = "gate_passed"
    GATE_FAILED = "gate_failed"
    RECLASSIFIED = "reclassified"
    REPLANNED = "replanned"
    DEBATE_ROUND = "debate_round"
    TASK_STARTED = "task_started"
    TASK_RESUMED = "task_resumed"


@dataclass
class CheckpointRecord:
    """A single checkpoint in the task's history timeline.

    Contains a lightweight snapshot of key state fields — not the
    full TaskState (that's in LangGraph's checkpoint DB), but enough
    to understand what happened and make resume decisions.
    """

    checkpoint_id: str  # Unique ID (e.g., "ckpt-001")
    checkpoint_type: str  # From CheckpointType
    checkpoint_name: str  # Human-readable (e.g., "planner-1 completed")
    timestamp: float  # epoch seconds

    # What happened at this checkpoint
    agent_role: str = ""  # Which agent was active
    instance_id: str = ""  # Which agent instance
    phase: str = ""  # Which pipeline phase (classify, execute, gate, etc.)

    # Lightweight state snapshot
    completed_roles: list[str] = field(default_factory=list)
    agent_outputs_summary: dict[str, str] = field(default_factory=dict)
    files_changed: list[str] = field(default_factory=list)
    gate_passed: bool | None = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0

    # Approval context (if approval checkpoint)
    approval_status: str = ""  # pending, approved, rejected
    approval_feedback: str = ""

    # Error context (if failure checkpoint)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_type": self.checkpoint_type,
            "checkpoint_name": self.checkpoint_name,
            "timestamp": self.timestamp,
            "agent_role": self.agent_role,
            "instance_id": self.instance_id,
            "phase": self.phase,
            "completed_roles": self.completed_roles,
            "agent_outputs_summary": self.agent_outputs_summary,
            "files_changed": self.files_changed,
            "gate_passed": self.gate_passed,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "approval_status": self.approval_status,
            "approval_feedback": self.approval_feedback,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckpointRecord:
        """Deserialize from dict."""
        return cls(
            checkpoint_id=data.get("checkpoint_id", ""),
            checkpoint_type=data.get("checkpoint_type", ""),
            checkpoint_name=data.get("checkpoint_name", ""),
            timestamp=data.get("timestamp", 0.0),
            agent_role=data.get("agent_role", ""),
            instance_id=data.get("instance_id", ""),
            phase=data.get("phase", ""),
            completed_roles=data.get("completed_roles", []),
            agent_outputs_summary=data.get("agent_outputs_summary", {}),
            files_changed=data.get("files_changed", []),
            gate_passed=data.get("gate_passed"),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            approval_status=data.get("approval_status", ""),
            approval_feedback=data.get("approval_feedback", ""),
            error=data.get("error", ""),
        )


@dataclass
class CheckpointTimeline:
    """Ordered history of checkpoints for a single task.

    This is the queryable, inspectable record of everything that
    happened during task execution. Unlike the opaque LangGraph
    checkpoint blob, this is designed for:
    - UI display ("show me the task timeline")
    - Resume decisions ("which agents already completed?")
    - Debugging ("where exactly did it fail?")
    """

    task_id: str
    records: list[CheckpointRecord] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)

    @property
    def last(self) -> CheckpointRecord | None:
        return self.records[-1] if self.records else None

    @property
    def completed_agents(self) -> list[str]:
        """All agent instance IDs that completed successfully."""
        completed: list[str] = []
        seen: set[str] = set()
        for record in self.records:
            if (
                record.checkpoint_type == CheckpointType.AGENT_COMPLETED
                and record.instance_id
                and record.instance_id not in seen
            ):
                completed.append(record.instance_id)
                seen.add(record.instance_id)
        return completed

    @property
    def last_successful_phase(self) -> str:
        """The last phase that completed successfully."""
        for record in reversed(self.records):
            if record.checkpoint_type in (
                CheckpointType.AGENT_COMPLETED,
                CheckpointType.GATE_PASSED,
                CheckpointType.APPROVAL_GRANTED,
            ):
                return record.phase
        return ""

    @property
    def all_files_changed(self) -> list[str]:
        """Accumulated files changed across all checkpoints."""
        files: list[str] = []
        seen: set[str] = set()
        for record in self.records:
            for f in record.files_changed:
                if f not in seen:
                    files.append(f)
                    seen.add(f)
        return files

    def record(
        self,
        checkpoint_type: str,
        checkpoint_name: str,
        state: dict[str, Any],
        *,
        agent_role: str = "",
        instance_id: str = "",
        phase: str = "",
        error: str = "",
    ) -> CheckpointRecord:
        """Record a new checkpoint from current task state.

        Extracts a lightweight snapshot from the full state dict.
        """
        # Generate sequential checkpoint ID
        seq = len(self.records) + 1
        checkpoint_id = f"ckpt-{seq:03d}"

        # Extract snapshot from state
        completed_roles = list(state.get("completed_roles", []))

        # Build summary of agent outputs (just the summaries, not full output)
        agent_outputs = state.get("agent_outputs", {})
        agent_summaries: dict[str, str] = {}
        if isinstance(agent_outputs, dict):
            for role, output in agent_outputs.items():
                summary = ""
                if isinstance(output, dict):
                    summary = str(output.get("summary", ""))[:200]
                agent_summaries[role] = summary

        # Collect files changed
        files_changed: list[str] = []
        if isinstance(agent_outputs, dict):
            seen: set[str] = set()
            for output in agent_outputs.values():
                if isinstance(output, dict):
                    for f in output.get("files_changed", []):
                        if f not in seen:
                            files_changed.append(f)
                            seen.add(f)

        # Gate status
        gate_results = state.get("gate_results", {})
        gate_passed = gate_results.get("passed") if isinstance(gate_results, dict) else None

        # Cost accumulator
        cost_acc = state.get("cost_accumulator", {})
        total_tokens = (
            sum(v.get("tokens", 0) for v in cost_acc.values()) if isinstance(cost_acc, dict) else 0
        )
        total_cost = (
            round(sum(v.get("cost", 0.0) for v in cost_acc.values()), 6)
            if isinstance(cost_acc, dict)
            else 0.0
        )

        record = CheckpointRecord(
            checkpoint_id=checkpoint_id,
            checkpoint_type=checkpoint_type,
            checkpoint_name=checkpoint_name,
            timestamp=time.time(),
            agent_role=agent_role,
            instance_id=instance_id,
            phase=phase,
            completed_roles=completed_roles,
            agent_outputs_summary=agent_summaries,
            files_changed=files_changed,
            gate_passed=gate_passed,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            approval_status=str(state.get("approval_status", "")),
            approval_feedback=str(state.get("approval_feedback", "")),
            error=error,
        )

        self.records.append(record)

        # Enforce max checkpoint limit
        if len(self.records) > MAX_CHECKPOINT_SNAPSHOTS:
            self.records = self.records[-MAX_CHECKPOINT_SNAPSHOTS:]

        return record

    def to_list(self) -> list[dict[str, Any]]:
        """Serialize all records for JSON storage."""
        return [r.to_dict() for r in self.records]

    @classmethod
    def from_list(cls, task_id: str, data: list[dict[str, Any]]) -> CheckpointTimeline:
        """Deserialize from stored list."""
        return cls(
            task_id=task_id,
            records=[CheckpointRecord.from_dict(d) for d in data],
        )


@dataclass
class ResumeContext:
    """Context assembled specifically for resumed task execution.

    This is injected into the pipeline so that:
    1. Sequential path knows which agents to skip
    2. Agents know they're resuming and what already happened
    3. Cost/token tracking continues from where it left off
    """

    is_resuming: bool = False
    resumed_from_checkpoint: str = ""  # checkpoint_id or checkpoint_name
    completed_agents: list[str] = field(default_factory=list)
    last_successful_phase: str = ""
    files_already_changed: list[str] = field(default_factory=list)
    previous_agent_summaries: dict[str, str] = field(default_factory=dict)
    accumulated_tokens: int = 0
    accumulated_cost: float = 0.0

    def to_context_section(self) -> str:
        """Build a context string for injection into agent prompts."""
        if not self.is_resuming:
            return ""

        parts = ["--- RESUME CONTEXT (this task was interrupted and is being resumed) ---"]

        if self.resumed_from_checkpoint:
            parts.append(f"Resumed from: {self.resumed_from_checkpoint}")

        if self.completed_agents:
            parts.append(f"Already completed agents: {', '.join(self.completed_agents)}")

        if self.previous_agent_summaries:
            parts.append("\nPrevious agent outputs (before interruption):")
            for role, summary in self.previous_agent_summaries.items():
                if summary:
                    parts.append(f"  [{role}]: {summary[:150]}")

        if self.files_already_changed:
            parts.append(f"\nFiles already modified: {', '.join(self.files_already_changed[:20])}")

        parts.append(
            "\nIMPORTANT: Do NOT repeat work already completed by previous agents. "
            "Build upon their outputs. Check which files already exist before creating new ones."
        )

        return "\n".join(parts)


@dataclass
class HeartbeatTracker:
    """Tracks task liveness via heartbeat timestamps.

    Detects tasks that are "running" but haven't sent a heartbeat
    recently — these are interrupted/crashed tasks that need recovery.
    """

    task_id: str
    last_heartbeat: float = 0.0  # epoch seconds
    heartbeat_count: int = 0

    def beat(self) -> None:
        """Record a heartbeat."""
        self.last_heartbeat = time.time()
        self.heartbeat_count += 1

    @property
    def is_stale(self) -> bool:
        """Check if task is stale (no heartbeat recently)."""
        if self.last_heartbeat == 0.0:
            return False  # Never started — not stale
        return (time.time() - self.last_heartbeat) > STALE_TASK_THRESHOLD_SECONDS

    @property
    def seconds_since_heartbeat(self) -> float:
        """Seconds since last heartbeat."""
        if self.last_heartbeat == 0.0:
            return 0.0
        return time.time() - self.last_heartbeat


class HistoryStateManager:
    """Orchestrator for checkpoint timeline and resume operations.

    This is the central service that graph nodes call to record
    checkpoints and that the resume command queries to build context.
    """

    def __init__(self) -> None:
        self._timelines: dict[str, CheckpointTimeline] = {}
        self._heartbeats: dict[str, HeartbeatTracker] = {}

    def get_or_create_timeline(self, task_id: str) -> CheckpointTimeline:
        """Get existing timeline or create a new one."""
        if task_id not in self._timelines:
            self._timelines[task_id] = CheckpointTimeline(task_id=task_id)
        return self._timelines[task_id]

    def load_timeline(self, task_id: str, data: list[dict[str, Any]]) -> CheckpointTimeline:
        """Load a timeline from persisted data (e.g., from SQLite)."""
        timeline = CheckpointTimeline.from_list(task_id, data)
        self._timelines[task_id] = timeline
        return timeline

    def record_checkpoint(
        self,
        task_id: str,
        checkpoint_type: str,
        checkpoint_name: str,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> CheckpointRecord:
        """Record a checkpoint for a task."""
        timeline = self.get_or_create_timeline(task_id)
        record = timeline.record(
            checkpoint_type=checkpoint_type,
            checkpoint_name=checkpoint_name,
            state=state,
            **kwargs,
        )
        logger.debug(
            "Checkpoint recorded: task=%s type=%s name=%s",
            task_id,
            checkpoint_type,
            checkpoint_name,
        )
        return record

    def build_resume_context(self, task_id: str) -> ResumeContext:
        """Build resume context from checkpoint timeline.

        Called when a task is being resumed after interruption.
        Returns everything the pipeline needs to continue intelligently.
        """
        timeline = self._timelines.get(task_id)
        if not timeline or timeline.count == 0:
            return ResumeContext(is_resuming=True)

        last = timeline.last
        return ResumeContext(
            is_resuming=True,
            resumed_from_checkpoint=last.checkpoint_name if last else "",
            completed_agents=timeline.completed_agents,
            last_successful_phase=timeline.last_successful_phase,
            files_already_changed=timeline.all_files_changed,
            previous_agent_summaries=(last.agent_outputs_summary if last else {}),
            accumulated_tokens=last.total_tokens if last else 0,
            accumulated_cost=last.total_cost_usd if last else 0.0,
        )

    def heartbeat(self, task_id: str) -> None:
        """Record a heartbeat for a running task."""
        if task_id not in self._heartbeats:
            self._heartbeats[task_id] = HeartbeatTracker(task_id=task_id)
        self._heartbeats[task_id].beat()

    def get_stale_tasks(self) -> list[str]:
        """Return task IDs that appear to be interrupted (stale heartbeat)."""
        return [task_id for task_id, tracker in self._heartbeats.items() if tracker.is_stale]

    def clear_task(self, task_id: str) -> None:
        """Clean up tracking for a completed/failed task."""
        self._timelines.pop(task_id, None)
        self._heartbeats.pop(task_id, None)

    def get_skip_set(self, task_id: str) -> set[str]:
        """Get set of agent instance IDs to skip on resume.

        This is used by the sequential fallback path to skip
        agents that already completed before the interruption.
        """
        timeline = self._timelines.get(task_id)
        if not timeline:
            return set()
        return set(timeline.completed_agents)
