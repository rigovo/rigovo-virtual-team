"""Tests for plugin manifest parsing and discovery."""

from __future__ import annotations

from pathlib import Path

from rigovo.infrastructure.plugins.loader import PluginRegistry, discover_plugins
from rigovo.infrastructure.plugins.manifest import PluginManifest
import pytest


def test_manifest_auto_capabilities() -> None:
    manifest = PluginManifest.model_validate(
        {
            "id": "slack-connector",
            "name": "Slack Connector",
            "version": "1.0.0",
            "connectors": [{"id": "slack", "provider": "slack"}],
            "skills": [{"id": "incident", "description": "Incident triage", "path": "skills/incident"}],
        }
    )
    assert "connector" in manifest.capabilities
    assert "skill" in manifest.capabilities


def test_discover_plugins_from_paths(tmp_path: Path) -> None:
    plugin_root = tmp_path / ".rigovo" / "plugins"
    plugin_dir = plugin_root / "acme-slack"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        (
            "schema_version: rigovo.plugin.v1\n"
            "id: acme-slack\n"
            "name: ACME Slack\n"
            "version: 0.1.0\n"
            "trust_level: internal\n"
            "connectors:\n"
            "  - id: slack\n"
            "    provider: slack\n"
            "mcp_servers:\n"
            "  - id: kb\n"
            "    transport: stdio\n"
            "    command: python\n"
            "    args: [mcp_server.py]\n"
        ),
        encoding="utf-8",
    )

    manifests = discover_plugins([plugin_root])
    assert len(manifests) == 1
    m = manifests[0]
    assert m.id == "acme-slack"
    assert m.trust_level == "internal"
    assert "connector" in m.capabilities
    assert "mcp" in m.capabilities


def test_plugin_registry_honors_enabled_list(tmp_path: Path) -> None:
    plugin_root = tmp_path / ".rigovo" / "plugins"
    plugin_a = plugin_root / "a"
    plugin_b = plugin_root / "b"
    plugin_a.mkdir(parents=True)
    plugin_b.mkdir(parents=True)

    (plugin_a / "plugin.yaml").write_text(
        "id: plugin-a\nname: A\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    (plugin_b / "plugin.yaml").write_text(
        "id: plugin-b\nname: B\nversion: 1.0.0\n",
        encoding="utf-8",
    )

    registry = PluginRegistry(
        project_root=tmp_path,
        plugin_paths=[".rigovo/plugins"],
        enabled_plugins=["plugin-b"],
    )
    plugins = registry.load(include_disabled=True)
    enabled = {p.id: p.enabled for p in plugins}
    assert enabled["plugin-a"] is False
    assert enabled["plugin-b"] is True


def test_manifest_rejects_invalid_trust_level() -> None:
    with pytest.raises(ValueError):
        PluginManifest.model_validate(
            {
                "id": "bad-plugin",
                "name": "Bad",
                "version": "1.0.0",
                "trust_level": "unknown",
            }
        )
