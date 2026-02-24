"""CostEntry — granular token-to-dollar tracking per agent per task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class CostEntry:
    """
    Records the cost of a single LLM call.

    Every LLM invocation during a task produces a CostEntry.
    These are aggregated per agent, per team, per workspace for
    the CTO dashboard.
    """

    workspace_id: UUID
    llm_model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    id: UUID = field(default_factory=uuid4)
    team_id: UUID | None = None
    agent_id: UUID | None = None
    task_id: UUID | None = None
    project_id: UUID | None = None

    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
