"""Factory for obtaining the appropriate Desktop HAL for the host OS."""

import sys
from vision_mcp.hal.base import IDesktopHAL

_HAL_INSTANCE: IDesktopHAL | None = None


def get_desktop_hal() -> IDesktopHAL:
    """Returns the singleton IDesktopHAL instance suited for the runtime platform."""
    global _HAL_INSTANCE
    if _HAL_INSTANCE is None:
        # Platform backends are imported lazily so each OS only needs its own deps
        if sys.platform == "win32":
            from vision_mcp.hal.windows import WindowsHAL

            _HAL_INSTANCE = WindowsHAL()
        elif sys.platform == "darwin":
            from vision_mcp.hal.macos import MacHAL

            _HAL_INSTANCE = MacHAL()
        else:
            from vision_mcp.hal.linux import LinuxHAL

            _HAL_INSTANCE = LinuxHAL()
    return _HAL_INSTANCE
