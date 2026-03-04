"""Verify GET /v1/ping returns HTTP 200 with valid JSON."""
import json
import sys
from datetime import datetime

try:
    from rigovo.api.control_plane import create_app
except Exception as exc:
    print(f"SKIP: Cannot import create_app: {exc}")
    sys.exit(0)

try:
    from fastapi.testclient import TestClient
except ImportError:
    print("SKIP: fastapi.testclient not available")
    sys.exit(0)

try:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/v1/ping")
    print(f"Status: {resp.status_code}")
    print(f"Body: {resp.text}")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    body = resp.json()
    assert body["status"] == "ok", f"Expected status 'ok', got {body['status']}"
    assert "timestamp" in body, "Missing 'timestamp' field"

    # Verify timestamp is parseable ISO 8601
    ts = datetime.fromisoformat(body["timestamp"])
    print(f"Parsed timestamp: {ts}")
    print("PASS: All checks passed")
except Exception as exc:
    print(f"FAIL: {exc}")
    sys.exit(1)
