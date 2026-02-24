"""Domain interfaces — abstract ports that infrastructure implements."""

from rigovo.domain.interfaces.repositories import (
    WorkspaceRepository,
    TeamRepository,
    AgentRepository,
    TaskRepository,
    MemoryRepository,
    CostRepository,
    AuditRepository,
)
from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.interfaces.domain_plugin import DomainPlugin, AgentRoleDefinition, TaskTypeDefinition
from rigovo.domain.interfaces.event_emitter import EventEmitter

__all__ = [
    "WorkspaceRepository",
    "TeamRepository",
    "AgentRepository",
    "TaskRepository",
    "MemoryRepository",
    "CostRepository",
    "AuditRepository",
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
    "EmbeddingProvider",
    "QualityGate",
    "DomainPlugin",
    "AgentRoleDefinition",
    "TaskTypeDefinition",
    "EventEmitter",
]
