"""Unit tests for GET /v1/ping health-check endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rigovo.api.control_plane import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Create a TestClient backed by a temporary project root."""
    rigovo_dir = tmp_path / ".rigovo"
    rigovo_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(project_root=tmp_path)
    return TestClient(app)


class TestPingEndpoint:
    """Verify GET /v1/ping returns a valid liveness response."""

    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/v1/ping")
        assert response.status_code == 200

    def test_status_is_ok(self, client: TestClient) -> None:
        response = client.get("/v1/ping")
        body = response.json()
        assert body["status"] == "ok"

    def test_timestamp_is_iso8601_utc(self, client: TestClient) -> None:
        response = client.get("/v1/ping")
        body = response.json()
        ts = datetime.fromisoformat(body["timestamp"])
        assert ts.tzinfo is not None, "timestamp must be timezone-aware"
        offset_seconds = ts.utcoffset().total_seconds()  # type: ignore[union-attr]
        assert offset_seconds == 0, "timestamp must be UTC"

    def test_no_extra_fields(self, client: TestClient) -> None:
        response = client.get("/v1/ping")
        assert set(response.json().keys()) == {"status", "timestamp"}

    def test_content_type_is_json(self, client: TestClient) -> None:
        response = client.get("/v1/ping")
        assert "application/json" in response.headers["content-type"]
