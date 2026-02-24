"""SQLite memory repository — local memory cache with basic similarity."""

from __future__ import annotations

import json
import math
from datetime import datetime
from uuid import UUID

from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.interfaces.repositories import MemoryRepository
from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase


class SqliteMemoryRepository(MemoryRepository):
    """
    Local memory store in SQLite.

    For semantic search without pgvector, we store embeddings as JSON
    arrays and compute cosine similarity in Python. This is fine for
    < 10K memories; cloud pgvector handles production scale.
    """

    def __init__(self, db: LocalDatabase) -> None:
        self._db = db

    async def save(self, memory: Memory) -> Memory:
        embedding_json = json.dumps(memory.embedding) if memory.embedding else None
        self._db.execute(
            """INSERT OR REPLACE INTO memories
            (id, workspace_id, source_project_id, source_task_id,
             source_agent_id, content, memory_type, embedding,
             usage_count, cross_project_usage, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(memory.id),
                str(memory.workspace_id),
                str(memory.source_project_id) if memory.source_project_id else None,
                str(memory.source_task_id) if memory.source_task_id else None,
                str(memory.source_agent_id) if memory.source_agent_id else None,
                memory.content,
                memory.memory_type.value,
                embedding_json,
                memory.usage_count,
                memory.cross_project_usage,
                memory.last_used_at.isoformat() if memory.last_used_at else None,
            ),
        )
        self._db.commit()
        return memory

    async def search(
        self,
        workspace_id: UUID,
        query_embedding: list[float],
        limit: int = 10,
        memory_types: list[MemoryType] | None = None,
    ) -> list[Memory]:
        """Search memories by cosine similarity (computed in Python)."""
        type_filter = ""
        params: tuple = (str(workspace_id),)
        if memory_types:
            placeholders = ",".join("?" for _ in memory_types)
            type_filter = f" AND memory_type IN ({placeholders})"
            params = params + tuple(mt.value for mt in memory_types)

        rows = self._db.fetchall(
            f"SELECT * FROM memories WHERE workspace_id = ? AND embedding IS NOT NULL{type_filter}",
            params,
        )

        # Compute cosine similarity in Python
        scored: list[tuple[float, Memory]] = []
        for row in rows:
            embedding = json.loads(row["embedding"])
            sim = self._cosine_similarity(query_embedding, embedding)
            memory = self._row_to_memory(row)
            scored.append((sim, memory))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    async def list_by_workspace(self, workspace_id: UUID, limit: int = 50) -> list[Memory]:
        rows = self._db.fetchall(
            "SELECT * FROM memories WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (str(workspace_id), limit),
        )
        return [self._row_to_memory(r) for r in rows]

    async def get_by_task(self, task_id: UUID) -> list[Memory]:
        rows = self._db.fetchall(
            "SELECT * FROM memories WHERE source_task_id = ? ORDER BY created_at",
            (str(task_id),),
        )
        return [self._row_to_memory(r) for r in rows]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _row_to_memory(row) -> Memory:
        return Memory(
            id=UUID(row["id"]),
            workspace_id=UUID(row["workspace_id"]),
            source_project_id=UUID(row["source_project_id"]) if row["source_project_id"] else None,
            source_task_id=UUID(row["source_task_id"]) if row["source_task_id"] else None,
            source_agent_id=UUID(row["source_agent_id"]) if row["source_agent_id"] else None,
            content=row["content"],
            memory_type=MemoryType(row["memory_type"]),
            embedding=json.loads(row["embedding"]) if row["embedding"] else None,
            usage_count=row["usage_count"] or 0,
            cross_project_usage=row["cross_project_usage"] or 0,
            last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )
