"""Domain plugin interface — extensibility point for different verticals."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from rigovo.domain.interfaces.quality_gate import QualityGate


@dataclass
class AgentRoleDefinition:
    """Defines an available agent role within a domain."""

    role_id: str  # 'coder', 'reviewer', 'annotator', etc.
    name: str  # "Software Engineer", "Data Annotator"
    description: str = ""
    default_system_prompt: str = ""
    default_tools: list[str] = field(default_factory=list)
    default_llm_model: str = ""  # Empty = use configured default
    preferred_tier: str = "standard"  # budget | standard | premium
    pipeline_order: int = 0  # Default execution order
    produces_code: bool = False  # Whether gates should run on this role's output


@dataclass
class TaskTypeDefinition:
    """Defines a task type that this domain handles."""

    type_id: str  # 'feature', 'bug', 'annotation', etc.
    name: str
    description: str = ""
    default_complexity: str = "medium"


class DomainPlugin(ABC):
    """
    Extensibility point for domain-specific configuration.

    Open/Closed Principle: new domains are added by implementing this
    interface, NOT by modifying the core orchestration.

    The framework (orchestration, teams, memory, cost, approval, audit)
    stays identical. The domain is plugged in via this interface.

    Engineering, LLM Training, Content — all implement DomainPlugin.
    """

    @property
    @abstractmethod
    def domain_id(self) -> str:
        """Unique domain identifier (e.g. 'engineering', 'llm_training')."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable domain name."""
        ...

    @abstractmethod
    def get_agent_roles(self) -> list[AgentRoleDefinition]:
        """Available agent roles in this domain."""
        ...

    @abstractmethod
    def get_task_types(self) -> list[TaskTypeDefinition]:
        """Task types this domain handles."""
        ...

    @abstractmethod
    def get_quality_gates(self) -> list[QualityGate]:
        """Domain-specific quality gates."""
        ...

    @abstractmethod
    def get_tools(self, role_id: str) -> list[dict[str, Any]]:
        """Tool definitions available to an agent of this role."""
        ...

    @abstractmethod
    def build_system_prompt(self, role_id: str, enrichment_context: str = "") -> str:
        """
        Construct the full system prompt for an agent role.

        Combines the role's base prompt with enrichment and domain context.
        """
        ...
