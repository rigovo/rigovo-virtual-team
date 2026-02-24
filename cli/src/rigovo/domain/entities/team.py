"""Team — a persistent department within a workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Team:
    """
    A persistent group of agents that handles a domain of work.

    Teams are reusable across projects. A workspace can have multiple teams
    (Payment Team, Frontend Team, Data Team, etc.) each configured with
    domain-specific agents.

    The team defines the pipeline order — which agents execute in what
    sequence for a given task.
    """

    workspace_id: UUID
    name: str
    domain: str  # 'engineering', 'llm_training', 'content', etc.

    id: UUID = field(default_factory=uuid4)
    description: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.utcnow()
