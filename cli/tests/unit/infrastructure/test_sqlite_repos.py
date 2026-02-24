"""Tests for SQLite repository implementations."""

from __future__ import annotations

import pytest
from uuid import uuid4

from rigovo.domain.entities.task import Task, TaskStatus, TaskType, TaskComplexity
from rigovo.domain.entities.cost_entry import CostEntry
from rigovo.domain.entities.audit_entry import AuditEntry, AuditAction
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase
from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository
from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository
from rigovo.infrastructure.persistence.sqlite_memory_repo import SqliteMemoryRepository


@pytest.fixture
def db(tmp_path):
    """SQLite database with schema initialized."""
    from pathlib import Path
    db_path = tmp_path / "test.db"
    database = LocalDatabase(db_path)
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def workspace_id():
    return uuid4()


# --- Task Repository ---

class TestSqliteTaskRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, db, workspace_id):
        repo = SqliteTaskRepository(db)
        task = Task(workspace_id=workspace_id, description="Test task")
        task.classify(TaskType.FEATURE, TaskComplexity.MEDIUM)
        await repo.save(task)

        fetched = await repo.get_by_id(task.id)
        assert fetched is not None
        assert fetched.description == "Test task"
        assert fetched.task_type == TaskType.FEATURE

    @pytest.mark.asyncio
    async def test_list_by_workspace(self, db, workspace_id):
        repo = SqliteTaskRepository(db)
        for i in range(5):
            await repo.save(Task(workspace_id=workspace_id, description=f"Task {i}"))
        tasks = await repo.list_by_workspace(workspace_id, limit=10)
        assert len(tasks) == 5

    @pytest.mark.asyncio
    async def test_update_status(self, db, workspace_id):
        repo = SqliteTaskRepository(db)
        task = Task(workspace_id=workspace_id, description="Status test")
        await repo.save(task)
        task.start()
        task.complete()
        await repo.update_status(task)
        fetched = await repo.get_by_id(task.id)
        assert fetched.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db):
        repo = SqliteTaskRepository(db)
        assert await repo.get_by_id(uuid4()) is None


# --- Cost Repository ---

class TestSqliteCostRepository:

    @pytest.mark.asyncio
    async def test_save_and_total(self, db, workspace_id):
        repo = SqliteCostRepository(db)
        await repo.save(CostEntry(
            workspace_id=workspace_id, llm_model="claude-sonnet",
            input_tokens=1000, output_tokens=500, cost_usd=0.0045,
        ))
        total = await repo.total_by_workspace(workspace_id)
        assert total == pytest.approx(0.0045)

    @pytest.mark.asyncio
    async def test_batch_save(self, db, workspace_id):
        repo = SqliteCostRepository(db)
        entries = [CostEntry(
            workspace_id=workspace_id, llm_model="claude-sonnet",
            input_tokens=1000, output_tokens=500, cost_usd=0.005,
        ) for _ in range(10)]
        await repo.save_batch(entries)
        assert await repo.total_by_workspace(workspace_id) == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_total_by_team(self, db, workspace_id):
        repo = SqliteCostRepository(db)
        team_id = uuid4()
        await repo.save(CostEntry(
            workspace_id=workspace_id, team_id=team_id, llm_model="gpt-4o",
            input_tokens=2000, output_tokens=1000, cost_usd=0.01,
        ))
        assert await repo.total_by_team(team_id) == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_empty_workspace_returns_zero(self, db):
        assert await SqliteCostRepository(db).total_by_workspace(uuid4()) == 0.0


# --- Audit Repository ---

class TestSqliteAuditRepository:

    @pytest.mark.asyncio
    async def test_append_and_list(self, db, workspace_id):
        repo = SqliteAuditRepository(db)
        await repo.append(AuditEntry(
            workspace_id=workspace_id, action=AuditAction.TASK_CREATED,
            agent_role="system", summary="Task created", metadata={"key": "value"},
        ))
        entries = await repo.list_by_workspace(workspace_id)
        assert len(entries) == 1
        assert entries[0].action == AuditAction.TASK_CREATED

    @pytest.mark.asyncio
    async def test_list_by_task(self, db, workspace_id):
        repo = SqliteAuditRepository(db)
        task_id = uuid4()
        for action in [AuditAction.TASK_CREATED, AuditAction.TASK_STARTED, AuditAction.TASK_COMPLETED]:
            await repo.append(AuditEntry(
                workspace_id=workspace_id, task_id=task_id, action=action,
                agent_role="system", summary=f"Action: {action.value}",
            ))
        assert len(await repo.list_by_task(task_id)) == 3


# --- Memory Repository ---

class TestSqliteMemoryRepository:

    @pytest.mark.asyncio
    async def test_save_and_list(self, db, workspace_id):
        repo = SqliteMemoryRepository(db)
        await repo.save(Memory(
            workspace_id=workspace_id,
            content="Always use type hints in Python",
            memory_type=MemoryType.PATTERN,
        ))
        memories = await repo.list_by_workspace(workspace_id)
        assert len(memories) == 1
        assert memories[0].content == "Always use type hints in Python"

    @pytest.mark.asyncio
    async def test_search_by_similarity(self, db, workspace_id):
        repo = SqliteMemoryRepository(db)
        for i, content in enumerate(["Python type hints", "JavaScript testing", "Database indexing"]):
            embedding = [0.0] * 10
            embedding[i] = 1.0
            await repo.save(Memory(
                workspace_id=workspace_id, content=content,
                memory_type=MemoryType.PATTERN, embedding=embedding,
            ))
        query = [0.0] * 10
        query[0] = 1.0
        results = await repo.search(workspace_id, query, limit=2)
        assert len(results) <= 2
        assert results[0].content == "Python type hints"

    @pytest.mark.asyncio
    async def test_get_by_task(self, db, workspace_id):
        repo = SqliteMemoryRepository(db)
        task_id = uuid4()
        await repo.save(Memory(
            workspace_id=workspace_id, source_task_id=task_id,
            content="Learned something", memory_type=MemoryType.DOMAIN_KNOWLEDGE,
        ))
        assert len(await repo.get_by_task(task_id)) == 1
