"""Embedding provider interface — for semantic memory search."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """
    Generates vector embeddings for text.

    Used for semantic memory search — encoding task descriptions and
    memory content into vectors for similarity matching.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """The dimensionality of embeddings this provider produces."""
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for multiple texts."""
        ...
