"""Factory for obtaining the appropriate Desktop HAL for the host OS."""

import sys
from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.hal.linux import LinuxHAL
from vision_mcp.hal.windows import WindowsHAL

_HAL_INSTANCE: IDesktopHAL | None = None


def get_desktop_hal() -> IDesktopHAL:
    """Returns the singleton IDesktopHAL instance suited for the runtime platform."""
    global _HAL_INSTANCE
    if _HAL_INSTANCE is None:
        if sys.platform == "win32":
            _HAL_INSTANCE = WindowsHAL()
        elif sys.platform.startswith("linux"):
            _HAL_INSTANCE = LinuxHAL()
        else:
            # Fallback to Linux-based interface for POSIX
            _HAL_INSTANCE = LinuxHAL()
    return _HAL_INSTANCE
