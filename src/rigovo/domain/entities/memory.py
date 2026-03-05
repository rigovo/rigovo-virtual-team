"""Memory — workspace-level knowledge extracted from task execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from rigovo.domain._compat import StrEnum


class MemoryType(StrEnum):
    """Categories of learned knowledge."""

    TASK_OUTCOME = "task_outcome"  # What happened, what worked
    PATTERN = "pattern"  # Recurring patterns (e.g., "CSRF always missed on POST")
    ERROR_FIX = "error_fix"  # How a specific error was resolved
    TECH_STACK = "tech_stack"  # Technology conventions ("uses Stripe SDK v12")
    CONVENTION = "convention"  # Code/team conventions ("always use useCallback in React")
    DOMAIN_KNOWLEDGE = (
        "domain_knowledge"  # Domain-specific facts ("PCI requires encryption at rest")
    )
    GATE_LEARNING = "gate_learning"  # Quality gate violations and fixes learned
    TEAM_PERFORMANCE = "team_performance"  # Which role combinations worked best
    ARCHITECTURE = "architecture"  # Architectural patterns and insights discovered
    TASK_MEMORY = "task_memory"  # Ephemeral task-scoped memory
    WORKSPACE_MEMORY = "workspace_memory"  # Long-lived workspace memory
    AGENT_SKILL_MEMORY = "agent_skill_memory"  # Role/persona-specific skill update


@dataclass
class Memory:
    """
    A piece of learned knowledge stored at the workspace level.

    Memories are extracted by the Master Agent after task completion.
    They are searchable via embedding similarity (pgvector in cloud,
    local similarity scoring in CLI).

    Memories flow across projects — a lesson from Project A helps Project B.
    """

    workspace_id: UUID
    content: str
    memory_type: MemoryType

    id: UUID = field(default_factory=uuid4)
    source_project_id: UUID | None = None
    source_task_id: UUID | None = None
    source_agent_id: UUID | None = None

    # Embedding for semantic search (1536-dim for OpenAI, variable for others)
    embedding: list[float] | None = None

    # Usage tracking
    usage_count: int = 0
    cross_project_usage: int = 0  # Times used outside the source project
    last_used_at: datetime | None = None

    created_at: datetime = field(default_factory=datetime.utcnow)

    def record_usage(self, project_id: UUID | None = None) -> None:
        """Track that this memory was used in a task."""
        self.usage_count += 1
        self.last_used_at = datetime.utcnow()

        if project_id and project_id != self.source_project_id:
            self.cross_project_usage += 1

    @property
    def is_cross_project(self) -> bool:
        """Whether this memory has been useful across multiple projects."""
        return self.cross_project_usage > 0
