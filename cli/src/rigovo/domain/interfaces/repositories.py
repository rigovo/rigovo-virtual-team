"""Repository interfaces — abstract data access contracts.

Domain layer defines WHAT data operations are needed.
Infrastructure layer decides HOW (SQLite, Postgres, HTTP, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

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
    async def get_by_id(self, workspace_id: UUID) -> Workspace | None: ...

    @abstractmethod
    async def get_by_slug(self, slug: str) -> Workspace | None: ...

    @abstractmethod
    async def save(self, workspace: Workspace) -> Workspace: ...


class TeamRepository(ABC):
    """Team CRUD + queries."""

    @abstractmethod
    async def get_by_id(self, team_id: UUID) -> Team | None: ...

    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> list[Team]: ...

    @abstractmethod
    async def get_by_domain(self, workspace_id: UUID, domain: str) -> list[Team]: ...

    @abstractmethod
    async def save(self, team: Team) -> Team: ...


class AgentRepository(ABC):
    """Agent CRUD + performance queries."""

    @abstractmethod
    async def get_by_id(self, agent_id: UUID) -> Agent | None: ...

    @abstractmethod
    async def list_by_team(self, team_id: UUID) -> list[Agent]: ...

    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> list[Agent]: ...

    @abstractmethod
    async def save(self, agent: Agent) -> Agent: ...

    @abstractmethod
    async def update_enrichment(
        self, agent_id: UUID, enrichment: EnrichmentContext,
    ) -> None: ...

    @abstractmethod
    async def update_stats(self, agent: Agent) -> None: ...


class TaskRepository(ABC):
    """Task lifecycle operations."""

    @abstractmethod
    async def get_by_id(self, task_id: UUID) -> Task | None: ...

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID, limit: int = 50,
    ) -> list[Task]: ...

    @abstractmethod
    async def list_by_team(
        self, team_id: UUID, limit: int = 50,
    ) -> list[Task]: ...

    @abstractmethod
    async def save(self, task: Task) -> Task: ...

    @abstractmethod
    async def update_status(self, task: Task) -> None: ...


class MemoryRepository(ABC):
    """Memory storage and retrieval with semantic search."""

    @abstractmethod
    async def save(self, memory: Memory) -> Memory: ...

    @abstractmethod
    async def search(
        self,
        workspace_id: UUID,
        query_embedding: list[float],
        limit: int = 10,
        memory_types: list[MemoryType] | None = None,
    ) -> list[Memory]: ...

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID, limit: int = 50,
    ) -> list[Memory]: ...

    @abstractmethod
    async def get_by_task(self, task_id: UUID) -> list[Memory]: ...


class CostRepository(ABC):
    """Cost tracking operations."""

    @abstractmethod
    async def save(self, entry: CostEntry) -> CostEntry: ...

    @abstractmethod
    async def save_batch(self, entries: list[CostEntry]) -> None: ...

    @abstractmethod
    async def total_by_workspace(self, workspace_id: UUID) -> float: ...

    @abstractmethod
    async def total_by_team(self, team_id: UUID) -> float: ...

    @abstractmethod
    async def total_by_agent(self, agent_id: UUID) -> float: ...

    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> list[CostEntry]: ...


class AuditRepository(ABC):
    """Immutable audit log operations."""

    @abstractmethod
    async def append(self, entry: AuditEntry) -> AuditEntry: ...

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID, limit: int = 100,
    ) -> list[AuditEntry]: ...

    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> list[AuditEntry]: ...
