"""Memory retriever — fetches relevant past learnings for agents.

This is the LEARNING layer. Before an agent executes, we search
for memories from past tasks that are relevant to the current one.

Memories are ranked by: similarity (60%) + recency (20%) + utility (20%).
This means recent, frequently-reused knowledge floats to the top.

A chatbot has no memory. An intelligent agent REMEMBERS.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.services.memory_ranker import MemoryRanker, ScoredMemory

logger = logging.getLogger(__name__)

# --- Retrieval limits ---
MAX_MEMORIES_PER_AGENT = 8
MAX_MEMORIES_FOR_MASTER = 15  # Master Agent gets more context for cross-project learning
MAX_MEMORY_CONTENT_LENGTH = 500
MIN_RELEVANCE_SCORE = 0.3  # Don't inject low-relevance memories

# How memory types map to agent roles (which memories are most useful)
ROLE_MEMORY_PREFERENCES: dict[str, list[MemoryType]] = {
    "planner": [MemoryType.DOMAIN_KNOWLEDGE, MemoryType.ERROR_FIX, MemoryType.TASK_OUTCOME, MemoryType.PATTERN, MemoryType.CONVENTION],
    "coder": [MemoryType.ERROR_FIX, MemoryType.PATTERN, MemoryType.CONVENTION],
    "reviewer": [MemoryType.PATTERN, MemoryType.CONVENTION, MemoryType.TASK_OUTCOME],
    "security": [MemoryType.ERROR_FIX, MemoryType.DOMAIN_KNOWLEDGE],
    "qa": [MemoryType.ERROR_FIX, MemoryType.PATTERN, MemoryType.TASK_OUTCOME],
    "devops": [MemoryType.CONVENTION, MemoryType.PATTERN],
    "sre": [MemoryType.ERROR_FIX, MemoryType.CONVENTION],
    "lead": [MemoryType.PATTERN, MemoryType.DOMAIN_KNOWLEDGE, MemoryType.TASK_OUTCOME],
    "master": [
        MemoryType.GATE_LEARNING,
        MemoryType.TEAM_PERFORMANCE,
        MemoryType.ARCHITECTURE,
        MemoryType.TASK_OUTCOME,
        MemoryType.DOMAIN_KNOWLEDGE,
    ],  # Master Agent gets comprehensive insights
}


@dataclass
class RetrievedMemories:
    """Memories retrieved for a specific agent execution."""

    memories: list[ScoredMemory] = field(default_factory=list)
    role: str = ""
    query: str = ""

    @property
    def count(self) -> int:
        return len(self.memories)

    def to_context_section(self) -> str:
        """Render as a context section for injection into agent prompts."""
        if not self.memories:
            return ""

        parts = [
            "--- MEMORIES (lessons from past tasks) ---",
            f"Retrieved {self.count} relevant memories for {self.role}:\n",
        ]

        for i, scored in enumerate(self.memories, 1):
            content = scored.memory.content
            if len(content) > MAX_MEMORY_CONTENT_LENGTH:
                content = content[:MAX_MEMORY_CONTENT_LENGTH] + "..."

            mem_type = scored.memory.memory_type.value
            score = f"{scored.score:.2f}"
            parts.append(f"{i}. [{mem_type}] (relevance: {score}) {content}")

        return "\n".join(parts)


class MemoryRetriever:
    """Retrieves and ranks relevant memories for agent execution.

    This bridges the memory repository (storage) and the memory
    ranker (scoring) into a single retrieval interface used by
    the context builder.
    """

    def __init__(self, ranker: MemoryRanker | None = None) -> None:
        self._ranker = ranker or MemoryRanker()

    async def retrieve(
        self,
        task_description: str,
        role: str,
        memories: list[Memory],
        similarity_scores: list[float],
    ) -> RetrievedMemories:
        """Retrieve and rank memories for an agent role.

        Args:
            task_description: Current task being executed.
            role: Agent role (coder, reviewer, etc.).
            memories: Raw memories from repository search.
            similarity_scores: Cosine similarity for each memory.

        Returns:
            Ranked, filtered memories ready for context injection.
        """
        await asyncio.sleep(0)  # Yield to event loop
        if not memories:
            return RetrievedMemories(role=role, query=task_description)

        # Rank all memories
        scored = self._ranker.rank(memories, similarity_scores)

        # Filter by minimum relevance
        scored = [s for s in scored if s.score >= MIN_RELEVANCE_SCORE]

        # Boost memories matching this role's preferred types
        preferred_types = ROLE_MEMORY_PREFERENCES.get(role, [])
        if preferred_types:
            scored = self._boost_preferred(scored, preferred_types)

        # Cap at max per agent
        scored = scored[:MAX_MEMORIES_PER_AGENT]

        return RetrievedMemories(
            memories=scored,
            role=role,
            query=task_description,
        )

    async def retrieve_for_master(
        self,
        task_description: str,
        memories: list[Memory],
        similarity_scores: list[float],
    ) -> RetrievedMemories:
        """Retrieve and rank memories specifically for the Master Agent.

        The Master Agent is the Distinguished Engineer who learns from every
        execution across the workspace. It gets more memories (15 vs 8) and
        focuses on:
        - Gate learnings (violations and fixes)
        - Team performance insights (role combinations)
        - Architectural patterns discovered
        - Task outcomes and domain knowledge

        Args:
            task_description: The task the Master Agent is analyzing.
            memories: Workspace-level memories to filter.
            similarity_scores: Cosine similarity for each memory.

        Returns:
            Ranked, filtered memories optimized for Master Agent analysis.
        """
        await asyncio.sleep(0)  # Yield to event loop
        if not memories:
            return RetrievedMemories(role="master", query=task_description)

        # Rank all memories
        scored = self._ranker.rank(memories, similarity_scores)

        # Filter by minimum relevance
        scored = [s for s in scored if s.score >= MIN_RELEVANCE_SCORE]

        # Filter for Master Agent's preferred memory types
        master_types = ROLE_MEMORY_PREFERENCES.get("master", [])
        if master_types:
            # Keep only memories that match master's preferred types
            scored = [s for s in scored if s.memory.memory_type in master_types]

        # If we filtered too aggressively, relax to include all types
        if not scored and similarity_scores:
            scored = self._ranker.rank(memories, similarity_scores)
            scored = [s for s in scored if s.score >= MIN_RELEVANCE_SCORE]

        # Boost cross-project memories (they're more generally useful)
        scored = sorted(
            scored,
            key=lambda s: (-int(s.memory.is_cross_project), -s.score),
        )

        # Cap at higher limit for Master Agent (company-level context)
        scored = scored[:MAX_MEMORIES_FOR_MASTER]

        return RetrievedMemories(
            memories=scored,
            role="master",
            query=task_description,
        )

    def _boost_preferred(
        self,
        scored: list[ScoredMemory],
        preferred: list[MemoryType],
    ) -> list[ScoredMemory]:
        """Boost scores for memories matching the role's preferred types.

        This doesn't change the composite score — it re-sorts by giving
        preferred types a tiebreaker advantage.
        """
        preferred_set = set(preferred)

        def _sort_key(sm: ScoredMemory) -> tuple[bool, float]:
            is_preferred = sm.memory.memory_type in preferred_set
            return (not is_preferred, -sm.score)  # preferred first, then by score

        return sorted(scored, key=_sort_key)
