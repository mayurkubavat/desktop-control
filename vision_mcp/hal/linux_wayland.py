"""Native Wayland backend.

Selected only when WAYLAND_DISPLAY is set and DISPLAY is not (no XWayland).
Operations fail closed. XWayland sessions keep using the X11 driver.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PIL import Image

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.hal.errors import CapabilityUnavailable
from vision_mcp.types import WindowInfo


_MSG = (
    "Native Wayland capture and input are not available. "
    "Start an XWayland DISPLAY or set DESKTOP_HAL=linux."
)


class WaylandHAL(IDesktopHAL):
    """Fail-closed Wayland driver. It does not silently click through X11."""

    def _unavailable(self) -> None:
        raise CapabilityUnavailable(_MSG)

    def get_screen_size(self) -> Tuple[int, int]:
        self._unavailable()
        return (0, 0)

    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        self._unavailable()
        return Image.new("RGB", (1, 1))

    def get_cursor_position(self) -> Tuple[int, int]:
        self._unavailable()
        return (0, 0)

    def mouse_move(self, x: int, y: int) -> None:
        self._unavailable()

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        self._unavailable()

    def mouse_drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3
    ) -> None:
        self._unavailable()

    def mouse_scroll(self, dx: int, dy: int) -> None:
        self._unavailable()

    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        self._unavailable()

    def keyboard_press_key(self, key_name: str) -> None:
        self._unavailable()

    def keyboard_hotkey(self, keys: List[str]) -> None:
        self._unavailable()

    def list_windows(self) -> List[WindowInfo]:
        self._unavailable()
        return []

    def get_active_window(self) -> Optional[WindowInfo]:
        self._unavailable()
        return None

    def focus_window(self, window_id: str) -> bool:
        self._unavailable()
        return False


def build_hal() -> WaylandHAL:
    return WaylandHAL()
