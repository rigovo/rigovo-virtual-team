"""Repository interfaces — abstract data access contracts.

Domain layer defines WHAT data operations are needed.
Infrastructure layer decides HOW (SQLite, Postgres, HTTP, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

# --- Default pagination limits ---
DEFAULT_PAGE_SIZE = 50
DEFAULT_MEMORY_SEARCH_LIMIT = 10
DEFAULT_AUDIT_PAGE_SIZE = 100

from rigovo.domain.entities.workspace import Workspace
from rigovo.domain.entities.team import Team
from rigovo.domain.entities.agent import Agent, EnrichmentContext
from rigovo.domain.entities.task import Task
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.entities.cost_entry import CostEntry
from rigovo.domain.entities.audit_entry import AuditEntry, AuditAction


class WorkspaceRepository(ABC):
    """Workspace CRUD operations."""

    @abstractmethod
    async def get_by_id(self, workspace_id: UUID) -> Workspace | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_slug(self, slug: str) -> Workspace | None:
        raise NotImplementedError

    @abstractmethod
    async def save(self, workspace: Workspace) -> Workspace:
        raise NotImplementedError


class TeamRepository(ABC):
    """Team CRUD + queries."""

    @abstractmethod
    async def get_by_id(self, team_id: UUID) -> Team | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> list[Team]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_domain(self, workspace_id: UUID, domain: str) -> list[Team]:
        raise NotImplementedError

    @abstractmethod
    async def save(self, team: Team) -> Team:
        raise NotImplementedError


class AgentRepository(ABC):
    """Agent CRUD + performance queries."""

    @abstractmethod
    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_team(self, team_id: UUID) -> list[Agent]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> list[Agent]:
        raise NotImplementedError

    @abstractmethod
    async def save(self, agent: Agent) -> Agent:
        raise NotImplementedError

    @abstractmethod
    async def update_enrichment(
        self, agent_id: UUID, enrichment: EnrichmentContext,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update_stats(self, agent: Agent) -> None:
        raise NotImplementedError


class TaskRepository(ABC):
    """Task lifecycle operations."""

    @abstractmethod
    async def get_by_id(self, task_id: UUID) -> Task | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID, limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Task]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_team(
        self, team_id: UUID, limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Task]:
        raise NotImplementedError

    @abstractmethod
    async def save(self, task: Task) -> Task:
        raise NotImplementedError

    @abstractmethod
    async def update_status(self, task: Task) -> None:
        raise NotImplementedError


class MemoryRepository(ABC):
    """Memory storage and retrieval with semantic search."""

    @abstractmethod
    async def save(self, memory: Memory) -> Memory:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        workspace_id: UUID,
        query_embedding: list[float],
        limit: int = DEFAULT_MEMORY_SEARCH_LIMIT,
        memory_types: list[MemoryType] | None = None,
    ) -> list[Memory]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID, limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Memory]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_task(self, task_id: UUID) -> list[Memory]:
        raise NotImplementedError


class CostRepository(ABC):
    """Cost tracking operations."""

    @abstractmethod
    async def save(self, entry: CostEntry) -> CostEntry:
        raise NotImplementedError

    @abstractmethod
    async def save_batch(self, entries: list[CostEntry]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def total_by_workspace(self, workspace_id: UUID) -> float:
        raise NotImplementedError

    @abstractmethod
    async def total_by_team(self, team_id: UUID) -> float:
        raise NotImplementedError

    @abstractmethod
    async def total_by_agent(self, agent_id: UUID) -> float:
        raise NotImplementedError

    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> list[CostEntry]:
        raise NotImplementedError


class AuditRepository(ABC):
    """Immutable audit log operations."""

    @abstractmethod
    async def append(self, entry: AuditEntry) -> AuditEntry:
        raise NotImplementedError

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID, limit: int = DEFAULT_AUDIT_PAGE_SIZE,
    ) -> list[AuditEntry]:
        raise NotImplementedError

    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> list[AuditEntry]:
        raise NotImplementedError
