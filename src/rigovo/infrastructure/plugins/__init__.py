"""Plugin infrastructure — manifest schema + local discovery."""

from rigovo.infrastructure.plugins.loader import PluginRegistry, discover_plugins
from rigovo.infrastructure.plugins.manifest import PluginManifest

__all__ = ["PluginManifest", "PluginRegistry", "discover_plugins"]

