"""Shared cache helpers for deterministic keying and usage normalization."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rigovo.domain.interfaces.llm_provider import LLMUsage


CACHE_VERSION = "v1"


def stable_json(value: Any) -> str:
    """Return stable JSON string for hashing/cache keys."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def stable_hash(value: Any) -> str:
    """SHA256 hash of stable JSON representation."""
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def usage_to_dict(usage: LLMUsage | dict[str, Any] | None) -> dict[str, Any]:
    """Serialize usage for cache records and telemetry."""
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "cached_input_tokens": int(usage.get("cached_input_tokens", 0) or 0),
            "cache_write_tokens": int(usage.get("cache_write_tokens", 0) or 0),
            "cache_source": str(usage.get("cache_source", "none") or "none"),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }
    return {
        "input_tokens": int(usage.input_tokens or 0),
        "output_tokens": int(usage.output_tokens or 0),
        "cached_input_tokens": int(usage.cached_input_tokens or 0),
        "cache_write_tokens": int(usage.cache_write_tokens or 0),
        "cache_source": str(usage.cache_source or "none"),
        "total_tokens": int(usage.total_tokens or 0),
    }


def usage_from_dict(payload: dict[str, Any] | None) -> LLMUsage:
    """Deserialize a usage payload into LLMUsage."""
    data = payload or {}
    return LLMUsage(
        input_tokens=int(data.get("input_tokens", 0) or 0),
        output_tokens=int(data.get("output_tokens", 0) or 0),
        cached_input_tokens=int(data.get("cached_input_tokens", 0) or 0),
        cache_write_tokens=int(data.get("cache_write_tokens", 0) or 0),
        cache_source=str(data.get("cache_source", "none") or "none"),
    )
