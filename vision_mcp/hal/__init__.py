"""Hardware Abstraction Layer (HAL) for Desktop OS Control."""

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.hal.factory import get_desktop_hal
from vision_mcp.hal.protocols import (
    IAXTreeDriver,
    IDesktopHALProtocol,
    IInputDriver,
    IScreenCapture,
    IWindowManager,
)
from vision_mcp.hal.mock_replay import MockReplayHAL, ScreenFrameState

__all__ = [
    "IDesktopHAL",
    "get_desktop_hal",
    "IScreenCapture",
    "IInputDriver",
    "IWindowManager",
    "IAXTreeDriver",
    "IDesktopHALProtocol",
    "MockReplayHAL",
    "ScreenFrameState",
]
