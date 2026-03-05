"""Rigour memory runtime.

Provides explicit remember/recall contracts used by orchestration nodes:
- rigour_recall: retrieve ranked memory context for a role
- rigour_remember: persist curated memory entries with embeddings
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rigovo.application.context.memory_retriever import MemoryRetriever, ROLE_MEMORY_PREFERENCES
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.repositories import MemoryRepository


@dataclass
class RigourRecallResult:
    context_text: str
    retrieval_log: list[dict[str, Any]]
    count: int
    avg_score: float
    top_score: float


class RigourMemoryRuntime:
    """Unified memory interface for Rigovo orchestration."""

    def __init__(
        self,
        memory_repo: MemoryRepository | None,
        embedding_provider: EmbeddingProvider | None,
        memory_retriever: MemoryRetriever | None = None,
    ) -> None:
        self._memory_repo = memory_repo
        self._embedding_provider = embedding_provider
        self._retriever = memory_retriever or MemoryRetriever()

    async def rigour_recall(
        self,
        *,
        workspace_id: UUID,
        task_description: str,
        role: str,
        limit: int = 24,
    ) -> RigourRecallResult:
        """Recall relevant memories for a role and render prompt context."""
        if not self._memory_repo or not self._embedding_provider:
            return RigourRecallResult("", [], 0, 0.0, 0.0)

        query_embedding = await self._embedding_provider.embed(task_description)
        preferred_types = ROLE_MEMORY_PREFERENCES.get(role) or None
        memories = await self._memory_repo.search(
            workspace_id=workspace_id,
            query_embedding=query_embedding,
            limit=limit,
            memory_types=preferred_types,
        )
        similarity_scores = [
            _cosine_similarity(query_embedding, m.embedding or []) for m in memories
        ]
        retrieved = await self._retriever.retrieve(
            task_description=task_description,
            role=role,
            memories=memories,
            similarity_scores=similarity_scores,
        )
        scores = [float(sm.score) for sm in retrieved.memories]
        return RigourRecallResult(
            context_text=retrieved.to_context_section(),
            retrieval_log=[
                {
                    "memory_id": str(sm.memory.id),
                    "score": round(float(sm.score), 6),
                    "memory_type": sm.memory.memory_type.value,
                }
                for sm in retrieved.memories
            ],
            count=retrieved.count,
            avg_score=(sum(scores) / len(scores)) if scores else 0.0,
            top_score=max(scores) if scores else 0.0,
        )

    async def rigour_remember(
        self,
        *,
        workspace_id: UUID,
        source_project_id: UUID | None,
        source_task_id: UUID | None,
        entries: list[dict[str, Any]],
    ) -> list[Memory]:
        """Persist curated memory entries and return saved memory entities."""
        if not self._memory_repo or not self._embedding_provider or not entries:
            return []

        texts = [str(item.get("content", "")).strip() for item in entries]
        embeddings = await self._embedding_provider.embed_batch(texts)
        saved: list[Memory] = []
        for item, embedding in zip(entries, embeddings):
            mem_type = _coerce_memory_type(str(item.get("type", MemoryType.PATTERN.value)))
            memory = Memory(
                workspace_id=workspace_id,
                source_project_id=source_project_id,
                source_task_id=source_task_id,
                content=str(item.get("content", "")).strip(),
                memory_type=mem_type,
                embedding=embedding,
            )
            await self._memory_repo.save(memory)
            saved.append(memory)
        return saved


def _coerce_memory_type(raw: str) -> MemoryType:
    try:
        return MemoryType(raw)
    except ValueError:
        return MemoryType.PATTERN


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
