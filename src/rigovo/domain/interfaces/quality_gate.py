"""Quality gate interface — deterministic code analysis contracts."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

from rigovo.domain.entities.quality import GateResult


@dataclass
class GateInput:
    """
    Input to a quality gate.

    Deliberately minimal — gates don't need the full TaskState.
    Interface Segregation: gates depend on what they need, nothing more.
    """

    project_root: str
    files_changed: list[str]
    agent_role: str
    deep: bool = False
    pro: bool = False


class QualityGate(ABC):
    """
    Abstract quality gate.

    Liskov Substitution: any QualityGate subclass (RigourGate,
    ConsistencyGate, SchemaGate) can be used wherever QualityGate
    is expected.

    Strategy Pattern: the orchestration graph calls gates through
    this interface. The concrete implementation is injected by the
    domain plugin.
    """

    @property
    @abstractmethod
    def gate_id(self) -> str:
        """Unique identifier for this gate (e.g. 'rigour', 'consistency')."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""
        ...

    @abstractmethod
    async def run(self, gate_input: GateInput) -> GateResult:
        """
        Execute the quality gate on the given input.

        Returns a deterministic GateResult. No LLM opinions.
        Same input ALWAYS produces the same output.
        """
        await asyncio.sleep(0)  # abstract — subclasses must override
        raise NotImplementedError
