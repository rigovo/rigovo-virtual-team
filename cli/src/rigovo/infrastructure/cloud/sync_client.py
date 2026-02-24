"""Cloud sync client — pushes metadata to rigovo.com API.

Local-first: all operations work offline. When online, metadata
(task summaries, costs, audit logs) syncs to the CTO dashboard.
No source code ever leaves the developer's machine.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.rigovo.com"
SYNC_TIMEOUT = 30  # seconds
MAX_BATCH_SIZE = 100


class SyncPriority(IntEnum):
    """Priority levels for sync queue items."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class SyncItem:
    """An item waiting to be synced to the cloud."""

    id: str
    entity_type: str  # "task", "cost", "audit", "agent_stats"
    operation: str  # "create", "update", "delete"
    payload: dict[str, Any]
    priority: SyncPriority = SyncPriority.NORMAL
    created_at: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0
    last_error: str | None = None


@dataclass
class SyncResult:
    """Result of a sync operation."""

    synced: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class CloudSyncClient:
    """
    HTTP client for syncing metadata to the Rigovo cloud API.

    Design principles:
    - Never syncs source code or file contents
    - All syncs are idempotent (safe to retry)
    - Queue-based: items are queued locally, flushed when online
    - Batch operations for efficiency
    - Graceful degradation: sync failures never block local work
    """

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        api_key: str | None = None,
        workspace_id: UUID | None = None,
        timeout: int = SYNC_TIMEOUT,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Whether cloud sync is configured with valid credentials."""
        return bool(self._api_key and self._workspace_id)

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client."""
        if self._client is None:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "rigovo-cli/0.1.0",
            }
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            self._client = httpx.AsyncClient(
                base_url=self._api_url,
                headers=headers,
                timeout=self._timeout,
            )
        return self._client

    async def sync_batch(self, items: list[SyncItem]) -> SyncResult:
        """
        Sync a batch of items to the cloud.

        Groups items by entity_type and sends them in batches.
        Returns counts of synced/failed items.
        """
        if not self.is_configured:
            return SyncResult(failed=len(items), errors=["Cloud sync not configured"])

        result = SyncResult()

        # Group by entity type for batch endpoints
        groups: dict[str, list[SyncItem]] = {}
        for item in items:
            groups.setdefault(item.entity_type, []).append(item)

        for entity_type, group_items in groups.items():
            # Process in chunks
            for i in range(0, len(group_items), MAX_BATCH_SIZE):
                chunk = group_items[i : i + MAX_BATCH_SIZE]
                try:
                    await self._sync_entity_batch(entity_type, chunk)
                    result.synced += len(chunk)
                except Exception as e:
                    logger.warning("Sync batch failed for %s: %s", entity_type, e)
                    result.failed += len(chunk)
                    result.errors.append(f"{entity_type}: {e}")

        return result

    async def _sync_entity_batch(
        self, entity_type: str, items: list[SyncItem]
    ) -> None:
        """Sync a batch of items of the same entity type."""
        client = await self._get_client()
        endpoint = f"/v1/workspaces/{self._workspace_id}/sync/{entity_type}"

        payload = {
            "items": [
                {
                    "id": item.id,
                    "operation": item.operation,
                    "data": item.payload,
                    "timestamp": item.created_at.isoformat(),
                }
                for item in items
            ]
        }

        response = await client.post(endpoint, json=payload)
        response.raise_for_status()

    async def sync_task_summary(
        self,
        task_id: UUID,
        status: str,
        task_type: str | None,
        complexity: str | None,
        total_tokens: int,
        total_cost_usd: float,
        duration_ms: int,
        pipeline_summary: list[dict[str, Any]],
    ) -> bool:
        """Sync a task summary (no code, just metrics)."""
        if not self.is_configured:
            return False

        try:
            client = await self._get_client()
            response = await client.post(
                f"/v1/workspaces/{self._workspace_id}/tasks/{task_id}/summary",
                json={
                    "status": status,
                    "task_type": task_type,
                    "complexity": complexity,
                    "total_tokens": total_tokens,
                    "total_cost_usd": total_cost_usd,
                    "duration_ms": duration_ms,
                    "pipeline": pipeline_summary,
                },
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Failed to sync task summary: %s", e)
            return False

    async def sync_cost_entries(self, entries: list[dict[str, Any]]) -> bool:
        """Sync cost ledger entries for the CTO dashboard."""
        if not self.is_configured:
            return False

        try:
            client = await self._get_client()
            response = await client.post(
                f"/v1/workspaces/{self._workspace_id}/costs/batch",
                json={"entries": entries},
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Failed to sync costs: %s", e)
            return False

    async def sync_audit_entries(self, entries: list[dict[str, Any]]) -> bool:
        """Sync audit log entries."""
        if not self.is_configured:
            return False

        try:
            client = await self._get_client()
            response = await client.post(
                f"/v1/workspaces/{self._workspace_id}/audit/batch",
                json={"entries": entries},
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Failed to sync audit: %s", e)
            return False

    async def check_health(self) -> bool:
        """Check if the cloud API is reachable."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def authenticate(self, api_key: str) -> dict[str, Any] | None:
        """Validate API key and return workspace info."""
        try:
            client = await self._get_client()
            response = await client.post(
                "/v1/auth/validate",
                json={"api_key": api_key},
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.warning("Authentication failed: %s", e)
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
