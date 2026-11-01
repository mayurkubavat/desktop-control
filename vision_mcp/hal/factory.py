"""Factory for obtaining the appropriate Desktop HAL for the host OS."""

import os
import sys
from vision_mcp.hal.base import IDesktopHAL

_HAL_INSTANCE: IDesktopHAL | None = None


def get_desktop_hal() -> IDesktopHAL:
    """Returns the singleton IDesktopHAL instance suited for the runtime platform.

    Supports DESKTOP_HAL=replay environment override for deterministic headless CI.
    """
    global _HAL_INSTANCE
    if _HAL_INSTANCE is None:
        hal_override = os.environ.get("DESKTOP_HAL", "").lower()
        if hal_override == "replay":
            from vision_mcp.hal.mock_replay import MockReplayHAL

            _HAL_INSTANCE = MockReplayHAL()
        # Platform backends are imported lazily so each OS only needs its own deps
        elif sys.platform == "win32":
            from vision_mcp.hal.windows import WindowsHAL

            _HAL_INSTANCE = WindowsHAL()
        elif sys.platform == "darwin":
            from vision_mcp.hal.macos import MacHAL

            _HAL_INSTANCE = MacHAL()
        else:
            from vision_mcp.hal.linux import LinuxHAL

            _HAL_INSTANCE = LinuxHAL()
    return _HAL_INSTANCE
