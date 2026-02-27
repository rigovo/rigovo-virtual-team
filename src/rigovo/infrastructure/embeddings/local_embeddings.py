"""Local embedding provider — lightweight embeddings without API calls.

Uses a simple TF-IDF-like approach for local memory similarity.
Production deployments use OpenAI/Voyage embeddings via the cloud,
but local needs to work offline with zero external dependencies.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections import Counter

from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider


class LocalEmbeddingProvider(EmbeddingProvider):
    """
    Local embedding provider using bag-of-words hashing.

    This generates deterministic, fixed-dimension embeddings locally
    without any ML model or API call. Good enough for local memory
    similarity (matching patterns, conventions, pitfalls).

    For production semantic search, swap in OpenAI or Voyage embeddings.
    """

    DIMENSIONS = 256  # Fixed embedding size

    @property
    def dimension(self) -> int:
        return self.DIMENSIONS

    STOP_WORDS = frozenset(
        {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "shall",
            "can",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "out",
            "off",
            "over",
            "under",
            "again",
            "further",
            "then",
            "once",
            "and",
            "but",
            "or",
            "nor",
            "not",
            "so",
            "yet",
            "both",
            "each",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "only",
            "own",
            "same",
            "than",
            "too",
            "very",
            "just",
            "because",
            "if",
            "when",
            "while",
            "where",
            "how",
            "what",
            "which",
            "who",
            "whom",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "i",
            "me",
            "my",
            "we",
            "our",
            "you",
            "your",
            "he",
            "him",
            "his",
            "she",
            "her",
            "they",
            "them",
        }
    )

    async def embed(self, text: str) -> list[float]:
        """Generate a fixed-dimension embedding for text."""
        await asyncio.sleep(0)  # Yield to event loop
        return self._hash_embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        await asyncio.sleep(0)  # Yield to event loop
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        """
        Generate embedding via feature hashing (hashing trick).

        Algorithm:
        1. Tokenize and normalize text
        2. For each token, hash to a bucket index (0..DIMENSIONS-1)
        3. Accumulate weighted counts (IDF-like weighting)
        4. L2-normalize the vector
        """
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.DIMENSIONS

        # Count tokens for TF
        tf = Counter(tokens)
        total = len(tokens)

        # Build vector via hashing trick
        vector = [0.0] * self.DIMENSIONS
        for token, count in tf.items():
            # Hash token to bucket
            bucket = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.DIMENSIONS
            # TF weight (log-normalized)
            weight = 1.0 + math.log(count / total + 1e-10)
            # Sign from second hash (reduces collisions)
            sign = 1.0 if int(hashlib.sha256(token.encode()).hexdigest(), 16) % 2 == 0 else -1.0
            vector[bucket] += sign * weight

        # Bigrams for phrase awareness
        for i in range(len(tokens) - 1):
            bigram = f"{tokens[i]}_{tokens[i + 1]}"
            bucket = int(hashlib.sha256(bigram.encode()).hexdigest(), 16) % self.DIMENSIONS
            sign = 1.0 if int(hashlib.sha256(bigram.encode()).hexdigest(), 16) % 2 == 0 else -1.0
            vector[bucket] += sign * 0.5  # Lower weight for bigrams

        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]

        return vector

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into normalized words."""
        # Lowercase and split on non-alphanumeric
        words = re.findall(r"[a-z0-9]+", text.lower())
        # Remove stop words and very short tokens
        return [w for w in words if w not in self.STOP_WORDS and len(w) > 1]
