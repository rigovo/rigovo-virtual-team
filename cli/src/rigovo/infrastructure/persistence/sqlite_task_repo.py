"""SQLite task repository — local task state persistence."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from rigovo.domain.entities.task import (
    Task, TaskStatus, TaskType, TaskComplexity, PipelineStep,
)
from rigovo.domain.interfaces.repositories import TaskRepository
from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase


class SqliteTaskRepository(TaskRepository):
    """Stores task state in local SQLite for crash recovery and history."""

    def __init__(self, db: LocalDatabase) -> None:
        self._db = db

    async def get_by_id(self, task_id: UUID) -> Task | None:
        row = self._db.fetchone("SELECT * FROM tasks WHERE id = ?", (str(task_id),))
        if not row:
            return None
        return self._row_to_task(row)

    async def list_by_workspace(self, workspace_id: UUID, limit: int = 50) -> list[Task]:
        rows = self._db.fetchall(
            "SELECT * FROM tasks WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (str(workspace_id), limit),
        )
        return [self._row_to_task(r) for r in rows]

    async def list_by_team(self, team_id: UUID, limit: int = 50) -> list[Task]:
        rows = self._db.fetchall(
            "SELECT * FROM tasks WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
            (str(team_id), limit),
        )
        return [self._row_to_task(r) for r in rows]

    async def save(self, task: Task) -> Task:
        self._db.execute(
            """INSERT OR REPLACE INTO tasks
            (id, workspace_id, project_id, team_id, description, task_type,
             complexity, status, current_checkpoint, approval_data,
             pipeline_steps, total_tokens, total_cost_usd, duration_ms,
             retries, langgraph_thread_id, rejected_at, user_feedback,
             error, started_at, completed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(task.id),
                str(task.workspace_id),
                str(task.project_id) if task.project_id else None,
                str(task.team_id) if task.team_id else None,
                task.description,
                task.task_type.value if task.task_type else None,
                task.complexity.value if task.complexity else None,
                task.status.value,
                task.current_checkpoint,
                json.dumps(task.approval_data) if task.approval_data else None,
                json.dumps([self._step_to_dict(s) for s in task.pipeline_steps]),
                task.total_tokens,
                task.total_cost_usd,
                task.duration_ms,
                task.retries,
                task.langgraph_thread_id,
                task.rejected_at,
                task.user_feedback,
                None,
                task.started_at.isoformat() if task.started_at else None,
                task.completed_at.isoformat() if task.completed_at else None,
                task.created_at.isoformat(),
            ),
        )
        self._db.commit()
        return task

    async def update_status(self, task: Task) -> None:
        self._db.execute(
            """UPDATE tasks SET status = ?, current_checkpoint = ?,
               total_tokens = ?, total_cost_usd = ?, duration_ms = ?,
               retries = ?, completed_at = ?, rejected_at = ?,
               user_feedback = ?
            WHERE id = ?""",
            (
                task.status.value,
                task.current_checkpoint,
                task.total_tokens,
                task.total_cost_usd,
                task.duration_ms,
                task.retries,
                task.completed_at.isoformat() if task.completed_at else None,
                task.rejected_at,
                task.user_feedback,
                str(task.id),
            ),
        )
        self._db.commit()

    @staticmethod
    def _step_to_dict(step: PipelineStep) -> dict:
        return {
            "agent_id": str(step.agent_id),
            "agent_role": step.agent_role,
            "agent_name": step.agent_name,
            "status": step.status,
            "duration_ms": step.duration_ms,
            "input_tokens": step.input_tokens,
            "output_tokens": step.output_tokens,
            "total_tokens": step.total_tokens,
            "cost_usd": step.cost_usd,
            "summary": step.summary,
            "files_changed": step.files_changed,
            "gate_passed": step.gate_passed,
            "gate_score": step.gate_score,
            "retry_count": step.retry_count,
        }

    @staticmethod
    def _row_to_task(row) -> Task:
        task = Task(
            workspace_id=UUID(row["workspace_id"]),
            description=row["description"],
            id=UUID(row["id"]),
        )
        task.project_id = UUID(row["project_id"]) if row["project_id"] else None
        task.team_id = UUID(row["team_id"]) if row["team_id"] else None
        task.task_type = TaskType(row["task_type"]) if row["task_type"] else None
        task.complexity = TaskComplexity(row["complexity"]) if row["complexity"] else None
        task.status = TaskStatus(row["status"])
        task.current_checkpoint = row["current_checkpoint"]
        task.approval_data = json.loads(row["approval_data"]) if row["approval_data"] else {}
        task.total_tokens = row["total_tokens"] or 0
        task.total_cost_usd = row["total_cost_usd"] or 0.0
        task.duration_ms = row["duration_ms"] or 0
        task.retries = row["retries"] or 0
        task.langgraph_thread_id = row["langgraph_thread_id"]
        task.rejected_at = row["rejected_at"]
        task.user_feedback = row["user_feedback"]
        if row["started_at"]:
            task.started_at = datetime.fromisoformat(row["started_at"])
        if row["completed_at"]:
            task.completed_at = datetime.fromisoformat(row["completed_at"])
        task.created_at = datetime.fromisoformat(row["created_at"])
        return task
