"""Pytest fixtures and mock classes for Vision Control MCP tests."""

import pytest
from typing import Tuple, List, Optional
from PIL import Image

from dobby.hal.base import IDesktopHAL
from dobby.types import WindowInfo, BoundingBox


class MockDesktopHAL(IDesktopHAL):
    """Deterministic mock HAL for automated unit and headless testing."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self.width = width
        self.height = height
        self.cursor_x = 100
        self.cursor_y = 100
        self.typed_text: List[str] = []
        self.clicks: List[Tuple[int, int, str, int]] = []
        self.hotkeys: List[List[str]] = []
        self.scrolls: List[Tuple[int, int]] = []

    def get_screen_size(self) -> Tuple[int, int]:
        return self.width, self.height

    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        w = region[2] if region else self.width
        h = region[3] if region else self.height
        return Image.new("RGB", (w, h), color=(40, 44, 52))

    def get_cursor_position(self) -> Tuple[int, int]:
        return self.cursor_x, self.cursor_y

    def mouse_move(self, x: int, y: int) -> None:
        self.cursor_x = x
        self.cursor_y = y

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        self.mouse_move(x, y)
        self.clicks.append((x, y, button, click_count))

    def mouse_drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3) -> None:
        self.mouse_move(end_x, end_y)

    def mouse_scroll(self, dx: int, dy: int) -> None:
        self.scrolls.append((dx, dy))

    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        self.typed_text.append(text)

    def keyboard_press_key(self, key_name: str) -> None:
        self.typed_text.append(f"<{key_name}>")

    def keyboard_hotkey(self, keys: List[str]) -> None:
        self.hotkeys.append(keys)

    def list_windows(self) -> List[WindowInfo]:
        return [
            WindowInfo(
                window_id="0x1000",
                title="Mock Terminal",
                bbox=BoundingBox(x=50, y=50, width=800, height=600),
                is_active=True,
                app_name="gnome-terminal",
            ),
            WindowInfo(
                window_id="0x2000",
                title="Mock Web Browser",
                bbox=BoundingBox(x=900, y=50, width=950, height=1000),
                is_active=False,
                app_name="firefox",
            ),
        ]

    def get_active_window(self) -> Optional[WindowInfo]:
        for win in self.list_windows():
            if win.is_active:
                return win
        return None

    def focus_window(self, window_id: str) -> bool:
        return window_id in ("0x1000", "0x2000")


@pytest.fixture
def mock_hal() -> MockDesktopHAL:
    return MockDesktopHAL()
