"""Plugin Registry for managing UI Application Plugins in Vision MCP."""

from typing import Dict, List, Optional, Any
from vision_mcp.plugins.base import BaseUIAppPlugin
from vision_mcp.plugins.chrome import ChromeBrowserPlugin
from vision_mcp.types import PluginSummary


class PluginRegistry:
    """
    Central registry for discovering, registering, and routing actions
    to high-feature application plugins.
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, BaseUIAppPlugin] = {}
        self._register_default_plugins()

    def _register_default_plugins(self) -> None:
        """Registers standard out-of-the-box application plugins."""
        self.register(ChromeBrowserPlugin())

    def register(self, plugin: BaseUIAppPlugin) -> None:
        """Registers a new application plugin."""
        self._plugins[plugin.app_id.lower()] = plugin

    def get(self, app_id: str) -> Optional[BaseUIAppPlugin]:
        """Retrieves a registered plugin by app_id."""
        return self._plugins.get(app_id.lower())

    def detect(self, window_title: str, app_name: Optional[str] = None) -> Optional[BaseUIAppPlugin]:
        """
        Matches an application plugin against window title or process name.
        
        Args:
            window_title: Title bar string of desktop window.
            app_name: Optional process binary name.
            
        Returns:
            Matching BaseUIAppPlugin instance or None.
        """
        for plugin in self._plugins.values():
            if plugin.detect(window_title, app_name):
                return plugin
        return None

    def list_all(self, active_window_title: Optional[str] = None) -> List[PluginSummary]:
        """Returns summaries of all registered plugins, marking which is currently active."""
        summaries = []
        for plugin in self._plugins.values():
            is_active = False
            if active_window_title and plugin.detect(active_window_title):
                is_active = True
            summaries.append(plugin.summarize(is_active=is_active))
        return summaries


# Default global registry singleton
PLUGIN_REGISTRY = PluginRegistry()

