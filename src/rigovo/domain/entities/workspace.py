"""Workspace — the tenant root. One workspace = one company."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from rigovo.domain._compat import StrEnum


class Plan(StrEnum):
    """Workspace billing plan."""

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class Workspace:
    """
    Top-level tenant representing a company or organisation.

    A workspace owns teams, agents, projects, and memories.
    The Master Agent is scoped to a workspace — one brain per company.
    """

    name: str
    slug: str
    owner_id: str

    id: UUID = field(default_factory=uuid4)
    plan: Plan = Plan.FREE
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # Cloud sync
    cloud_synced: bool = False
    last_synced_at: datetime | None = None

    def is_enterprise(self) -> bool:
        return self.plan == Plan.ENTERPRISE
