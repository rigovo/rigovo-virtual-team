"""Task — a unit of work that flows through a team's pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from rigovo.domain._compat import StrEnum


class TaskStatus(StrEnum):
    """Task lifecycle states. Matches LangGraph node progression."""

    PENDING = "pending"
    CLASSIFYING = "classifying"
    ROUTING = "routing"
    ASSEMBLING = "assembling"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    QUALITY_CHECK = "quality_check"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"  # User rejected at approval gate


class TaskType(StrEnum):
    """Classification of what kind of work the task represents."""

    FEATURE = "feature"
    BUG = "bug"
    REFACTOR = "refactor"
    TEST = "test"
    DOCS = "docs"
    INFRA = "infra"
    SECURITY = "security"
    PERFORMANCE = "performance"
    INVESTIGATION = "investigation"


class TaskComplexity(StrEnum):
    """Estimated complexity, affects cost estimation and agent count."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PipelineStep:
    """Record of a single agent's execution within the task pipeline."""

    agent_id: UUID
    agent_role: str
    agent_name: str

    status: str = "pending"  # pending, running, completed, failed, skipped
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int = 0

    # LLM usage
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    # Output summary (no code, no chain-of-thought — just the result)
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)

    # Gate results for this step (if applicable)
    gate_passed: bool | None = None
    gate_score: float | None = None
    retry_count: int = 0

    # Structured gate violations (Phase 8: persisted for UI rendering)
    # Each entry: {gate, passed, message, severity, violation_count, gates_run, deep, pro}
    gate_violations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Task:
    """
    A unit of work assigned to a team.

    Tasks are the primary work item. They flow through the LangGraph
    orchestration: classify → route → assemble → approve → execute → gate → finalize.

    Each task is an independent LangGraph thread with its own checkpoint history.
    """

    workspace_id: UUID
    description: str

    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    team_id: UUID | None = None
    tier: str = "auto"  # "auto" | "notify" | "approve" — persisted so resume restores it

    # Classification (set by Master Agent)
    task_type: TaskType | None = None
    complexity: TaskComplexity | None = None

    # Lifecycle
    status: TaskStatus = TaskStatus.PENDING

    # Approval
    current_checkpoint: str | None = None  # 'plan_ready', 'code_ready', etc.
    approval_data: dict[str, Any] = field(default_factory=dict)

    # Pipeline execution
    pipeline_steps: list[PipelineStep] = field(default_factory=list)

    # Aggregated results
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    retries: int = 0

    # LangGraph persistence
    langgraph_thread_id: str | None = None

    # User interaction
    rejected_at: str | None = None  # Which checkpoint was rejected
    user_feedback: str | None = None

    # Timestamps
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    # --- Domain Logic ---

    def classify(self, task_type: TaskType, complexity: TaskComplexity) -> None:
        """Set classification from Master Agent analysis."""
        self.task_type = task_type
        self.complexity = complexity
        self.status = TaskStatus.CLASSIFYING

    def assign_team(self, team_id: UUID) -> None:
        """Route this task to a specific team."""
        self.team_id = team_id
        self.status = TaskStatus.ROUTING

    def start(self) -> None:
        """Mark task as actively running."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.utcnow()

    def await_approval(self, checkpoint: str, data: dict[str, Any]) -> None:
        """Pause for human approval at a checkpoint."""
        self.status = TaskStatus.AWAITING_APPROVAL
        self.current_checkpoint = checkpoint
        self.approval_data = data

    def approve(self) -> None:
        """Resume after user approves."""
        self.status = TaskStatus.RUNNING
        self.current_checkpoint = None
        self.approval_data = {}

    def reject(self, feedback: str = "") -> None:
        """User rejects at a checkpoint."""
        self.status = TaskStatus.REJECTED
        self.rejected_at = self.current_checkpoint
        self.user_feedback = feedback
        self.completed_at = datetime.utcnow()

    def complete(self) -> None:
        """Mark task as successfully completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self._aggregate_pipeline()

    def fail(self, reason: str = "") -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.user_feedback = reason
        self.completed_at = datetime.utcnow()
        self._aggregate_pipeline()

    def add_step(self, step: PipelineStep) -> None:
        """Add a pipeline step record."""
        self.pipeline_steps.append(step)

    def _aggregate_pipeline(self) -> None:
        """Roll up token/cost/duration from all pipeline steps."""
        self.total_tokens = sum(s.total_tokens for s in self.pipeline_steps)
        self.total_cost_usd = sum(s.cost_usd for s in self.pipeline_steps)
        self.duration_ms = sum(s.duration_ms for s in self.pipeline_steps)
        self.retries = sum(s.retry_count for s in self.pipeline_steps)

    @property
    def is_terminal(self) -> bool:
        """Whether the task has reached a final state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.REJECTED,
        )
