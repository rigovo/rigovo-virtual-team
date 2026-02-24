"""Domain entities — pure dataclasses representing business concepts."""

from rigovo.domain.entities.workspace import Workspace
from rigovo.domain.entities.team import Team
from rigovo.domain.entities.agent import Agent, AgentRole, AgentStats, EnrichmentContext
from rigovo.domain.entities.task import Task, TaskStatus, TaskType, TaskComplexity, PipelineStep
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.entities.cost_entry import CostEntry
from rigovo.domain.entities.audit_entry import AuditEntry, AuditAction
from rigovo.domain.entities.quality import (
    GateResult,
    GateStatus,
    Violation,
    ViolationSeverity,
    FixPacket,
    FixItem,
)

__all__ = [
    "Workspace",
    "Team",
    "Agent",
    "AgentRole",
    "AgentStats",
    "EnrichmentContext",
    "Task",
    "TaskStatus",
    "TaskType",
    "TaskComplexity",
    "PipelineStep",
    "Memory",
    "MemoryType",
    "CostEntry",
    "AuditEntry",
    "AuditAction",
    "GateResult",
    "GateStatus",
    "Violation",
    "ViolationSeverity",
    "FixPacket",
    "FixItem",
]
