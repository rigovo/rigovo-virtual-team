"""Plugin discovery/registry for local plugin packages."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from rigovo.infrastructure.plugins.manifest import PluginManifest


def _candidate_manifest_files(plugin_dir: Path) -> list[Path]:
    return [
        plugin_dir / "plugin.yml",
        plugin_dir / "plugin.yaml",
        plugin_dir / "plugin.json",
        plugin_dir / "manifest.yml",
        plugin_dir / "manifest.yaml",
        plugin_dir / "manifest.json",
    ]


def _load_manifest_file(path: Path) -> PluginManifest:
    if path.suffix == ".json":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON plugin manifest: {path}") from exc
    else:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return PluginManifest.model_validate(raw)


def discover_plugins(
    plugin_paths: list[Path],
    enabled_plugin_ids: set[str] | None = None,
    include_disabled: bool = False,
) -> list[PluginManifest]:
    """Discover plugin manifests from configured directories."""
    manifests: list[PluginManifest] = []
    enabled_plugin_ids = enabled_plugin_ids or set()

    for root in plugin_paths:
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            manifest = None
            for manifest_path in _candidate_manifest_files(child):
                if manifest_path.exists() and manifest_path.is_file():
                    manifest = _load_manifest_file(manifest_path)
                    break
            if manifest is None:
                continue

            if enabled_plugin_ids:
                manifest.enabled = manifest.id in enabled_plugin_ids

            if include_disabled or manifest.enabled:
                manifests.append(manifest)

    return manifests


class PluginRegistry:
    """Runtime plugin registry loaded from local filesystem paths."""

    def __init__(
        self,
        project_root: Path,
        plugin_paths: list[str] | None = None,
        enabled_plugins: list[str] | None = None,
    ) -> None:
        self._project_root = project_root
        self._plugin_paths = plugin_paths or [".rigovo/plugins"]
        self._enabled_plugins = set(enabled_plugins or [])
        self._manifests: list[PluginManifest] = []

    def load(self, include_disabled: bool = False) -> list[PluginManifest]:
        paths = [
            (self._project_root / p).resolve() if not Path(p).is_absolute() else Path(p)
            for p in self._plugin_paths
        ]
        self._manifests = discover_plugins(
            plugin_paths=paths,
            enabled_plugin_ids=self._enabled_plugins,
            include_disabled=include_disabled,
        )
        return list(self._manifests)

    @property
    def plugins(self) -> list[PluginManifest]:
        return list(self._manifests)
