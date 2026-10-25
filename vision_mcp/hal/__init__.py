"""Hardware Abstraction Layer (HAL) for Desktop OS Control."""

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.hal.factory import get_desktop_hal

__all__ = ["IDesktopHAL", "get_desktop_hal"]
