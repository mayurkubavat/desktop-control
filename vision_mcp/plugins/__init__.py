"""UI Application Plugins Package for Vision MCP."""

from vision_mcp.plugins.base import BaseUIAppPlugin
from vision_mcp.plugins.chrome import ChromeBrowserPlugin
from vision_mcp.plugins.registry import PluginRegistry

# Default global registry singleton
PLUGIN_REGISTRY = PluginRegistry()

__all__ = [
    "BaseUIAppPlugin",
    "ChromeBrowserPlugin",
    "PluginRegistry",
    "PLUGIN_REGISTRY",
]
