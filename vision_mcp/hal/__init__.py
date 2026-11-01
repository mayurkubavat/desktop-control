"""Hardware Abstraction Layer (HAL) for Desktop OS Control."""

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.hal.factory import get_desktop_hal
from vision_mcp.hal.errors import CassetteMismatch
from vision_mcp.hal.mock_replay import MockReplayHAL, ScreenFrameState, Transition, load_cassette
from vision_mcp.hal.protocols import (
    IAXTreeDriver,
    IDesktopHALProtocol,
    IDesktopSession,
    IInputDriver,
    IQuiescenceMonitor,
    IScreenCapture,
    IWindowManager,
)

__all__ = [
    "IDesktopHAL",
    "get_desktop_hal",
    "IScreenCapture",
    "IInputDriver",
    "IWindowManager",
    "IAXTreeDriver",
    "IDesktopHALProtocol",
    "IDesktopSession",
    "IQuiescenceMonitor",
    "MockReplayHAL",
    "ScreenFrameState",
    "Transition",
    "load_cassette",
    "CassetteMismatch",
]
