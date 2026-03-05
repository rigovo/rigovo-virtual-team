"""Unit tests for custom integration registration endpoints."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient
import pytest

from rigovo.api.control_plane import create_app


def _client(tmp_path: Path) -> TestClient:
    rigovo_dir = tmp_path / ".rigovo"
    rigovo_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_add_custom_connector_registers_manifest_and_policy(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/v1/integrations/custom",
        json={
            "plugin_id": "workspace-tools",
            "name": "Workspace Tools",
            "connector": {
                "id": "figma",
                "provider": "figma",
                "outbound_actions": ["figma.read", "figma.comment"],
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["plugin_id"] == "workspace-tools"
    assert body["connector_id"] == "figma"

    manifest_path = tmp_path / ".rigovo" / "plugins" / "workspace-tools" / "plugin.yml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["id"] == "workspace-tools"
    assert "connector" in (manifest.get("capabilities") or [])
    assert manifest["connectors"][0]["id"] == "figma"

    policy = client.get("/v1/integrations/policy")
    assert policy.status_code == 200
    payload = policy.json()
    plugins = payload.get("plugins", [])
    plugin_ids = {p.get("id") or p.get("plugin_id") for p in plugins}
    assert "workspace-tools" in plugin_ids
    assert "figma.read" in payload["policy"]["allowed_connector_operations"]


def test_add_custom_mcp_registers_manifest_and_policy(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/v1/integrations/custom",
        json={
            "plugin_id": "workspace-mcp",
            "name": "Workspace MCP",
            "mcp_server": {
                "id": "figma-mcp",
                "transport": "stdio",
                "command": "npx -y @acme/figma-mcp",
                "operations": ["figma.read_frame"],
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["plugin_id"] == "workspace-mcp"
    assert body["mcp_server_id"] == "figma-mcp"

    manifest_path = tmp_path / ".rigovo" / "plugins" / "workspace-mcp" / "plugin.yml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert "mcp" in (manifest.get("capabilities") or [])
    assert manifest["mcp_servers"][0]["id"] == "figma-mcp"

    policy = client.get("/v1/integrations/policy")
    assert policy.status_code == 200
    payload = policy.json()
    assert "figma.read_frame" in payload["policy"]["allowed_mcp_operations"]


def test_marketplace_catalog_and_install(tmp_path: Path) -> None:
    client = _client(tmp_path)

    catalog = client.get("/v1/integrations/marketplace/catalog")
    assert catalog.status_code == 200
    items = catalog.json().get("items", [])
    assert any(item.get("id") == "figma-read" for item in items)

    install = client.post(
        "/v1/integrations/marketplace/install",
        json={"integration_id": "figma-read"},
    )
    assert install.status_code == 200, install.text
    body = install.json()
    assert body["status"] == "ok"
    assert body["source"] == "marketplace"
    assert body["integration_id"] == "figma-read"

    manifest_path = tmp_path / ".rigovo" / "plugins" / "market-figma-read" / "plugin.yml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["id"] == "market-figma-read"
    assert manifest["connectors"][0]["id"] == "figma"


def test_github_install_rejects_invalid_url(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post(
        "/v1/integrations/github/install",
        json={"github_url": "https://example.com/not-github"},
    )
    assert resp.status_code == 400


def test_github_install_with_mocked_manifest_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)

    class _Resp:
        def __init__(self, status_code: int, text: str) -> None:
            self.status_code = status_code
            self.text = text

    async def _fake_get(self, url: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if url.endswith("/plugin.yml"):
            return _Resp(
                200,
                "\n".join(
                    [
                        "schema_version: rigovo.plugin.v1",
                        "id: gh-plugin",
                        "name: GitHub Plugin",
                        "version: 0.1.0",
                        "trust_level: verified",
                        "connectors:",
                        "  - id: figma",
                        "    provider: figma",
                        "    kind: api",
                        "    outbound_actions:",
                        "      - figma.read",
                    ]
                ),
            )
        return _Resp(404, "")

    monkeypatch.setattr("httpx.AsyncClient.get", _fake_get)

    resp = client.post(
        "/v1/integrations/github/install",
        json={
            "github_url": "https://github.com/acme/tools",
            "ref": "main",
            "plugin_id": "gh-installed",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["source"] == "github"
    assert body["plugin_id"] == "gh-installed"

    manifest_path = tmp_path / ".rigovo" / "plugins" / "gh-installed" / "plugin.yml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["id"] == "gh-installed"
    assert manifest["connectors"][0]["id"] == "figma"
