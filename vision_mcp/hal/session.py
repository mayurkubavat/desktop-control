"""Session facade. Callers keep using HAL methods; drivers stay segregated."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.types import DisplayTopology, WindowInfo


class NullAXDriver:
    """AX is not on this backend. Callers get an explicit empty tree."""

    def get_accessibility_tree(
        self,
        app_filter: Optional[str] = None,
        max_depth: Optional[int] = None,
        diff_only: bool = False,
    ) -> Dict[str, Any]:
        if diff_only:
            return {"available": False, "changed": False, "nodes": []}
        return {"available": False, "nodes": []}


class DesktopSession(IDesktopHAL):
    """IDesktopHAL plus the segregated drivers from IDesktopSession."""

    def __init__(
        self,
        backend: IDesktopHAL,
        topology: DisplayTopology,
        quiescence: Any,
        ax: Any | None = None,
    ) -> None:
        self.backend = backend
        self.capture = backend
        self.input = backend
        self.windows = backend
        self.ax = ax if ax is not None else (
            backend if hasattr(backend, "get_accessibility_tree") else NullAXDriver()
        )
        self.quiescence = quiescence
        self.topology = topology

    def __getattr__(self, name: str) -> Any:
        """Backend-specific attributes (display_server, backing_scale, ...) pass through."""
        if name == "backend":
            raise AttributeError(name)
        return getattr(self.backend, name)

    def get_screen_size(self) -> Tuple[int, int]:
        return self.backend.get_screen_size()

    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        return self.backend.capture_screen(region)

    def get_cursor_position(self) -> Tuple[int, int]:
        return self.backend.get_cursor_position()

    def mouse_move(self, x: int, y: int) -> None:
        self.backend.mouse_move(x, y)

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        self.backend.mouse_click(x, y, button=button, click_count=click_count)

    def mouse_drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3
    ) -> None:
        self.backend.mouse_drag(start_x, start_y, end_x, end_y, duration_sec)

    def mouse_scroll(self, dx: int, dy: int) -> None:
        self.backend.mouse_scroll(dx, dy)

    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        self.backend.keyboard_type(text, delay_ms=delay_ms)

    def keyboard_press_key(self, key_name: str) -> None:
        self.backend.keyboard_press_key(key_name)

    def keyboard_hotkey(self, keys: List[str]) -> None:
        self.backend.keyboard_hotkey(keys)

    def list_windows(self) -> List[WindowInfo]:
        return self.backend.list_windows()

    def get_active_window(self) -> Optional[WindowInfo]:
        return self.backend.get_active_window()

    def focus_window(self, window_id: str) -> bool:
        return self.backend.focus_window(window_id)

    def get_accessibility_tree(
        self,
        app_filter: Optional[str] = None,
        max_depth: Optional[int] = None,
        diff_only: bool = False,
    ) -> Dict[str, Any]:
        return self.ax.get_accessibility_tree(
            app_filter=app_filter, max_depth=max_depth, diff_only=diff_only
        )

    def wait_for_quiescence(self, **kwargs: Any) -> Any:
        return self.quiescence.wait_for_quiescence(**kwargs)
