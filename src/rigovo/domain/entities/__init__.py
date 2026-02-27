"""Domain entities — pure dataclasses representing business concepts."""

from rigovo.domain.entities.agent import Agent, AgentRole, AgentStats, EnrichmentContext
from rigovo.domain.entities.audit_entry import AuditAction, AuditEntry
from rigovo.domain.entities.cost_entry import CostEntry
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.entities.quality import (
    FixItem,
    FixPacket,
    GateResult,
    GateStatus,
    Violation,
    ViolationSeverity,
)
from rigovo.domain.entities.task import PipelineStep, Task, TaskComplexity, TaskStatus, TaskType
from rigovo.domain.entities.team import Team
from rigovo.domain.entities.workspace import Workspace

__all__ = [
    "Agent",
    "AgentRole",
    "AgentStats",
    "AuditAction",
    "AuditEntry",
    "CostEntry",
    "EnrichmentContext",
    "FixItem",
    "FixPacket",
    "GateResult",
    "GateStatus",
    "Memory",
    "MemoryType",
    "PipelineStep",
    "Task",
    "TaskComplexity",
    "TaskStatus",
    "TaskType",
    "Team",
    "Violation",
    "ViolationSeverity",
    "Workspace",
]
