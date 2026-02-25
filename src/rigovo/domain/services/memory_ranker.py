"""Memory ranker — scores and filters memories for relevance to a task."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from rigovo.domain.entities.memory import Memory, MemoryType


@dataclass
class ScoredMemory:
    """A memory with its computed relevance score."""

    memory: Memory
    score: float  # 0.0 to 1.0


class MemoryRanker:
    """
    Ranks memories by relevance to a given task context.

    Combines semantic similarity (embedding distance) with recency
    and cross-project utility signals.

    Pure domain logic — no I/O.
    """

    # Weights for composite scoring
    SIMILARITY_WEIGHT = 0.6
    RECENCY_WEIGHT = 0.2
    UTILITY_WEIGHT = 0.2

    # Recency half-life in days (older memories decay)
    RECENCY_HALF_LIFE_DAYS = 30.0

    def rank(
        self,
        memories: list[Memory],
        similarity_scores: list[float],
        now: datetime | None = None,
    ) -> list[ScoredMemory]:
        """
        Rank memories by composite relevance score.

        Args:
            memories: Candidate memories (pre-filtered by embedding search).
            similarity_scores: Cosine similarity scores from embedding search
                               (same order as memories).
            now: Current timestamp for recency calculation.

        Returns:
            Memories sorted by composite score, highest first.
        """
        now = now or datetime.utcnow()
        scored: list[ScoredMemory] = []

        for memory, sim_score in zip(memories, similarity_scores):
            recency = self._recency_score(memory, now)
            utility = self._utility_score(memory)

            composite = (
                self.SIMILARITY_WEIGHT * sim_score
                + self.RECENCY_WEIGHT * recency
                + self.UTILITY_WEIGHT * utility
            )

            scored.append(ScoredMemory(memory=memory, score=composite))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def _recency_score(self, memory: Memory, now: datetime) -> float:
        """Exponential decay based on age. Recent memories score higher."""
        ref_time = memory.last_used_at or memory.created_at
        age_days = (now - ref_time).total_seconds() / 86400

        # Exponential decay: score = 0.5^(age / half_life)
        return math.pow(0.5, age_days / self.RECENCY_HALF_LIFE_DAYS)

    def _utility_score(self, memory: Memory) -> float:
        """Score based on how useful this memory has been."""
        # Cross-project memories are highly valuable
        cross_project_bonus = min(memory.cross_project_usage * 0.1, 0.5)

        # Usage frequency (capped at 1.0)
        usage_score = min(memory.usage_count * 0.05, 0.5)

        return min(cross_project_bonus + usage_score, 1.0)
