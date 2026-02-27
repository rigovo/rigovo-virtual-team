"""AuditEntry — enterprise-grade action logging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from rigovo.domain._compat import StrEnum


class AuditAction(StrEnum):
    """Every trackable action in the system."""

    # Task lifecycle
    TASK_CREATED = "task_created"
    TASK_CLASSIFIED = "task_classified"
    TASK_ASSIGNED = "task_assigned"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_REJECTED = "task_rejected"

    # Agent execution
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_RETRIED = "agent_retried"

    # Quality gates
    GATE_PASSED = "gate_passed"
    GATE_FAILED = "gate_failed"

    # Approval
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    GATE_NOTIFICATION = "gate_notification"  # notify-tier: auto-approved, user informed

    # Master Agent
    ENRICHMENT_STARTED = "enrichment_started"
    ENRICHMENT_COMPLETED = "enrichment_completed"
    MEMORY_STORED = "memory_stored"
    PATTERN_DETECTED = "pattern_detected"
    REPLAN_TRIGGERED = "replan_triggered"
    REPLAN_FAILED = "replan_failed"

    # System
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"


@dataclass
class AuditEntry:
    """
    Immutable audit log entry.

    Every significant action in the system produces an audit entry.
    These are synced to the cloud for the CTO dashboard's audit trail.
    """

    workspace_id: UUID
    action: AuditAction
    summary: str

    id: UUID = field(default_factory=uuid4)
    team_id: UUID | None = None
    agent_id: UUID | None = None
    task_id: UUID | None = None
    agent_role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    created_at: datetime = field(default_factory=datetime.utcnow)
