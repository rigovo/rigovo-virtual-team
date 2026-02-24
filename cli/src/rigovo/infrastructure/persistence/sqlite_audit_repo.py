"""SQLite audit repository — immutable local audit trail."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from uuid import UUID

from rigovo.domain.entities.audit_entry import AuditEntry, AuditAction
from rigovo.domain.interfaces.repositories import AuditRepository
from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase


class SqliteAuditRepository(AuditRepository):
    """Immutable audit log in local SQLite. Synced to cloud for CTO dashboard."""

    def __init__(self, db: LocalDatabase) -> None:
        self._db = db

    async def append(self, entry: AuditEntry) -> AuditEntry:
        await asyncio.sleep(0)
        self._db.execute(
            """INSERT INTO audit_log
            (id, workspace_id, team_id, agent_id, task_id, action_type,
             agent_role, summary, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(entry.id),
                str(entry.workspace_id),
                str(entry.team_id) if entry.team_id else None,
                str(entry.agent_id) if entry.agent_id else None,
                str(entry.task_id) if entry.task_id else None,
                entry.action.value,
                entry.agent_role,
                entry.summary,
                json.dumps(entry.metadata) if entry.metadata else None,
            ),
        )
        self._db.commit()
        return entry

    async def list_by_workspace(self, workspace_id: UUID, limit: int = 100) -> list[AuditEntry]:
        await asyncio.sleep(0)
        rows = self._db.fetchall(
            "SELECT * FROM audit_log WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (str(workspace_id), limit),
        )
        return [self._row_to_entry(r) for r in rows]

    async def list_by_task(self, task_id: UUID) -> list[AuditEntry]:
        await asyncio.sleep(0)
        rows = self._db.fetchall(
            "SELECT * FROM audit_log WHERE task_id = ? ORDER BY created_at",
            (str(task_id),),
        )
        return [self._row_to_entry(r) for r in rows]

    @staticmethod
    def _row_to_entry(row) -> AuditEntry:
        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except json.JSONDecodeError:
                metadata = {}
        return AuditEntry(
            id=UUID(row["id"]),
            workspace_id=UUID(row["workspace_id"]),
            team_id=UUID(row["team_id"]) if row["team_id"] else None,
            agent_id=UUID(row["agent_id"]) if row["agent_id"] else None,
            task_id=UUID(row["task_id"]) if row["task_id"] else None,
            action=AuditAction(row["action_type"]),
            agent_role=row["agent_role"],
            summary=row["summary"] or "",
            metadata=metadata,
            created_at=datetime.fromisoformat(row["created_at"]),
        )
