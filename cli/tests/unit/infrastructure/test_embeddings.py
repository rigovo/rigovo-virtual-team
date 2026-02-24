"""Tests for local embedding provider."""

from __future__ import annotations

import math
import pytest

from rigovo.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider


@pytest.fixture
def provider():
    return LocalEmbeddingProvider()


class TestLocalEmbeddingProvider:

    @pytest.mark.asyncio
    async def test_embed_returns_correct_dimensions(self, provider):
        result = await provider.embed("Hello world, this is a test")
        assert len(result) == 256

    @pytest.mark.asyncio
    async def test_embed_is_normalized(self, provider):
        result = await provider.embed("Python programming best practices")
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_embed_empty_string(self, provider):
        result = await provider.embed("")
        assert len(result) == 256
        assert all(x == 0.0 for x in result)

    @pytest.mark.asyncio
    async def test_similar_texts_have_high_similarity(self, provider):
        a = await provider.embed("Python error handling with try except")
        b = await provider.embed("Python exception handling using try catch")

        sim = sum(x * y for x, y in zip(a, b))
        assert sim > 0.3  # Similar texts should have positive similarity

    @pytest.mark.asyncio
    async def test_different_texts_have_lower_similarity(self, provider):
        a = await provider.embed("Python web development with Flask framework")
        b = await provider.embed("Quantum physics particle entanglement theory")

        sim = sum(x * y for x, y in zip(a, b))
        # Very different topics should have lower similarity
        similar = await provider.embed("Python web development using Django")
        sim_similar = sum(x * y for x, y in zip(a, similar))

        assert sim_similar > sim  # Related topic should be more similar

    @pytest.mark.asyncio
    async def test_embed_is_deterministic(self, provider):
        a = await provider.embed("test input")
        b = await provider.embed("test input")
        assert a == b

    @pytest.mark.asyncio
    async def test_embed_batch(self, provider):
        texts = ["Hello world", "Python programming", "Machine learning"]
        results = await provider.embed_batch(texts)
        assert len(results) == 3
        assert all(len(r) == 256 for r in results)
