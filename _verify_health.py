"""Verify /health still works after changes."""
import sys

try:
    from rigovo.api.control_plane import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    print(f"Status: {resp.status_code}")
    print(f"Body: {resp.text}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    print("PASS: /health still works")
except Exception as exc:
    print(f"FAIL: {exc}")
    sys.exit(1)
