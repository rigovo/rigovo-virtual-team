"""Domain interfaces — abstract ports that infrastructure implements."""

from rigovo.domain.interfaces.domain_plugin import (
    AgentRoleDefinition,
    DomainPlugin,
    TaskTypeDefinition,
)
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.event_emitter import EventEmitter
from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.interfaces.repositories import (
    AgentRepository,
    AuditRepository,
    CostRepository,
    MemoryRepository,
    TaskRepository,
    TeamRepository,
    WorkspaceRepository,
)

__all__ = [
    "AgentRepository",
    "AgentRoleDefinition",
    "AuditRepository",
    "CostRepository",
    "DomainPlugin",
    "EmbeddingProvider",
    "EventEmitter",
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
    "MemoryRepository",
    "QualityGate",
    "TaskRepository",
    "TaskTypeDefinition",
    "TeamRepository",
    "WorkspaceRepository",
]
