"""SQLite cache repository for prompt and artifact caches (local-only)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_utc_after(minutes: int | None) -> str | None:
    if not minutes or minutes <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class SqliteCacheRepository:
    """Persistent cache storage in the local SQLite database.

    SQLite is the only supported cache backend in this runtime path.
    """

    def __init__(self, db: LocalDatabase) -> None:
        self._db = db

    async def get_exact(
        self,
        *,
        workspace_id: str,
        role: str,
        model: str,
        prompt_hash: str,
        context_fingerprint: str,
    ) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        row = self._db.fetchone(
            """
            SELECT response_blob, usage_blob, metadata_blob, ttl_expires_at, created_at, updated_at
            FROM prompt_cache_exact
            WHERE workspace_id = ? AND role = ? AND model = ?
              AND prompt_hash = ? AND context_fingerprint = ?
              AND (ttl_expires_at IS NULL OR julianday(ttl_expires_at) > julianday('now'))
            LIMIT 1
            """,
            (workspace_id, role, model, prompt_hash, context_fingerprint),
        )
        if not row:
            return None
        return {
            "response": _loads(row["response_blob"], {}),
            "usage": _loads(row["usage_blob"], {}),
            "metadata": _loads(row["metadata_blob"], {}),
            "ttl_expires_at": row["ttl_expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    async def put_exact(
        self,
        *,
        workspace_id: str,
        role: str,
        model: str,
        prompt_hash: str,
        context_fingerprint: str,
        response: dict[str, Any],
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        ttl_minutes: int | None = None,
    ) -> None:
        await asyncio.sleep(0)
        now = _iso_utc_now()
        ttl = _iso_utc_after(ttl_minutes)
        self._db.execute(
            """
            INSERT INTO prompt_cache_exact
                (workspace_id, role, model, prompt_hash, context_fingerprint,
                 response_blob, usage_blob, metadata_blob, ttl_expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, role, model, prompt_hash, context_fingerprint)
            DO UPDATE SET
                response_blob = excluded.response_blob,
                usage_blob = excluded.usage_blob,
                metadata_blob = excluded.metadata_blob,
                ttl_expires_at = excluded.ttl_expires_at,
                updated_at = excluded.updated_at
            """,
            (
                workspace_id,
                role,
                model,
                prompt_hash,
                context_fingerprint,
                json.dumps(response, ensure_ascii=True),
                json.dumps(usage or {}, ensure_ascii=True),
                json.dumps(metadata or {}, ensure_ascii=True),
                ttl,
                now,
                now,
            ),
        )
        self._db.commit()

    async def search_semantic(
        self,
        *,
        workspace_id: str,
        role: str,
        model: str,
        query_hash: str,
    ) -> dict[str, Any] | None:
        """Placeholder semantic search by normalized query hash.

        Full vector similarity retrieval is implemented in a later phase.
        """
        await asyncio.sleep(0)
        row = self._db.fetchone(
            """
            SELECT response_blob, usage_blob, metadata_blob, quality_score, ttl_expires_at,
                   created_at, updated_at
            FROM prompt_cache_semantic
            WHERE workspace_id = ? AND role = ? AND model = ? AND query_hash = ?
              AND (ttl_expires_at IS NULL OR julianday(ttl_expires_at) > julianday('now'))
            ORDER BY quality_score DESC, updated_at DESC
            LIMIT 1
            """,
            (workspace_id, role, model, query_hash),
        )
        if not row:
            return None
        return {
            "response": _loads(row["response_blob"], {}),
            "usage": _loads(row["usage_blob"], {}),
            "metadata": _loads(row["metadata_blob"], {}),
            "quality_score": float(row["quality_score"] or 0.0),
            "ttl_expires_at": row["ttl_expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    async def put_semantic(
        self,
        *,
        workspace_id: str,
        role: str,
        model: str,
        query_hash: str,
        query_text_norm: str,
        response: dict[str, Any],
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        quality_score: float = 0.0,
        ttl_minutes: int | None = None,
    ) -> None:
        await asyncio.sleep(0)
        now = _iso_utc_now()
        ttl = _iso_utc_after(ttl_minutes)
        self._db.execute(
            """
            INSERT INTO prompt_cache_semantic
                (workspace_id, role, model, query_hash, query_text_norm,
                 response_blob, usage_blob, metadata_blob, quality_score,
                 ttl_expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                role,
                model,
                query_hash,
                query_text_norm,
                json.dumps(response, ensure_ascii=True),
                json.dumps(usage or {}, ensure_ascii=True),
                json.dumps(metadata or {}, ensure_ascii=True),
                float(quality_score),
                ttl,
                now,
                now,
            ),
        )
        self._db.commit()

    async def get_artifact(
        self,
        *,
        workspace_id: str,
        artifact_type: str,
        workspace_fingerprint: str,
        version: str,
    ) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        row = self._db.fetchone(
            """
            SELECT artifact_blob, metadata_blob, ttl_expires_at, created_at, updated_at
            FROM artifact_cache
            WHERE workspace_id = ? AND artifact_type = ?
              AND workspace_fingerprint = ? AND version = ?
              AND (ttl_expires_at IS NULL OR julianday(ttl_expires_at) > julianday('now'))
            LIMIT 1
            """,
            (workspace_id, artifact_type, workspace_fingerprint, version),
        )
        if not row:
            return None
        return {
            "artifact": _loads(row["artifact_blob"], {}),
            "metadata": _loads(row["metadata_blob"], {}),
            "ttl_expires_at": row["ttl_expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    async def put_artifact(
        self,
        *,
        workspace_id: str,
        artifact_type: str,
        workspace_fingerprint: str,
        version: str,
        artifact: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        ttl_minutes: int | None = None,
    ) -> None:
        await asyncio.sleep(0)
        now = _iso_utc_now()
        ttl = _iso_utc_after(ttl_minutes)
        self._db.execute(
            """
            INSERT INTO artifact_cache
                (workspace_id, artifact_type, workspace_fingerprint, version,
                 artifact_blob, metadata_blob, ttl_expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, artifact_type, workspace_fingerprint, version)
            DO UPDATE SET
                artifact_blob = excluded.artifact_blob,
                metadata_blob = excluded.metadata_blob,
                ttl_expires_at = excluded.ttl_expires_at,
                updated_at = excluded.updated_at
            """,
            (
                workspace_id,
                artifact_type,
                workspace_fingerprint,
                version,
                json.dumps(artifact, ensure_ascii=True),
                json.dumps(metadata or {}, ensure_ascii=True),
                ttl,
                now,
                now,
            ),
        )
        self._db.commit()
