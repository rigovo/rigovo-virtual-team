"""SQLite cost repository — local cost tracking."""

from __future__ import annotations

from uuid import UUID

from rigovo.domain.entities.cost_entry import CostEntry
from rigovo.domain.interfaces.repositories import CostRepository
from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase


class SqliteCostRepository(CostRepository):
    """Local cost ledger in SQLite. Synced to cloud for CTO dashboard."""

    def __init__(self, db: LocalDatabase) -> None:
        self._db = db

    async def save(self, entry: CostEntry) -> CostEntry:
        self._db.execute(
            """INSERT INTO cost_ledger
            (id, workspace_id, team_id, agent_id, task_id, project_id,
             llm_model, input_tokens, output_tokens, total_tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(entry.id),
                str(entry.workspace_id),
                str(entry.team_id) if entry.team_id else None,
                str(entry.agent_id) if entry.agent_id else None,
                str(entry.task_id) if entry.task_id else None,
                str(entry.project_id) if entry.project_id else None,
                entry.llm_model,
                entry.input_tokens,
                entry.output_tokens,
                entry.total_tokens,
                entry.cost_usd,
            ),
        )
        self._db.commit()
        return entry

    async def save_batch(self, entries: list[CostEntry]) -> None:
        self._db.executemany(
            """INSERT INTO cost_ledger
            (id, workspace_id, team_id, agent_id, task_id, project_id,
             llm_model, input_tokens, output_tokens, total_tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    str(e.id), str(e.workspace_id),
                    str(e.team_id) if e.team_id else None,
                    str(e.agent_id) if e.agent_id else None,
                    str(e.task_id) if e.task_id else None,
                    str(e.project_id) if e.project_id else None,
                    e.llm_model, e.input_tokens, e.output_tokens,
                    e.total_tokens, e.cost_usd,
                )
                for e in entries
            ],
        )
        self._db.commit()

    async def total_by_workspace(self, workspace_id: UUID) -> float:
        row = self._db.fetchone(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_ledger WHERE workspace_id = ?",
            (str(workspace_id),),
        )
        return row["total"] if row else 0.0

    async def total_by_team(self, team_id: UUID) -> float:
        row = self._db.fetchone(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_ledger WHERE team_id = ?",
            (str(team_id),),
        )
        return row["total"] if row else 0.0

    async def total_by_agent(self, agent_id: UUID) -> float:
        row = self._db.fetchone(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_ledger WHERE agent_id = ?",
            (str(agent_id),),
        )
        return row["total"] if row else 0.0

    async def list_by_task(self, task_id: UUID) -> list[CostEntry]:
        rows = self._db.fetchall(
            "SELECT * FROM cost_ledger WHERE task_id = ? ORDER BY created_at",
            (str(task_id),),
        )
        return [
            CostEntry(
                id=UUID(r["id"]),
                workspace_id=UUID(r["workspace_id"]),
                team_id=UUID(r["team_id"]) if r["team_id"] else None,
                agent_id=UUID(r["agent_id"]) if r["agent_id"] else None,
                task_id=UUID(r["task_id"]) if r["task_id"] else None,
                project_id=UUID(r["project_id"]) if r["project_id"] else None,
                llm_model=r["llm_model"],
                input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"],
                cost_usd=r["cost_usd"],
            )
            for r in rows
        ]
