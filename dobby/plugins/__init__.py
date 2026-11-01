"""UI Application Plugins Package for Vision MCP."""

from dobby.plugins.base import BaseUIAppPlugin
from dobby.plugins.chrome import ChromeBrowserPlugin
from dobby.plugins.registry import PluginRegistry

# Default global registry singleton
PLUGIN_REGISTRY = PluginRegistry()

__all__ = [
    "BaseUIAppPlugin",
    "ChromeBrowserPlugin",
    "PluginRegistry",
    "PLUGIN_REGISTRY",
]
