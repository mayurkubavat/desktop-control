"""Hardware Abstraction Layer (HAL) Protocol Definitions.

Defines zero-dependency, runtime-checkable protocol contracts isolating OS platform
implementations (macOS Quartz/CGEvent, Linux X11/XDamage, Windows pywin32) from the core
reasoning and agent loop.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable
from PIL import Image
from vision_mcp.types import WindowInfo


@runtime_checkable
class IScreenCapture(Protocol):
    """Protocol for display capture and resolution metrics."""

    def get_screen_size(self) -> Tuple[int, int]:
        """Returns primary screen resolution as (width, height) in physical pixels."""
        ...

    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """Captures display or sub-region as a PIL RGB Image."""
        ...


@runtime_checkable
class IInputDriver(Protocol):
    """Protocol for low-level mouse and keyboard input simulation."""

    def get_cursor_position(self) -> Tuple[int, int]:
        """Returns current mouse pointer coordinates (x, y)."""
        ...

    def mouse_move(self, x: int, y: int) -> None:
        """Moves cursor to absolute coordinates (x, y)."""
        ...

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        """Clicks at target coordinates."""
        ...

    def mouse_drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3
    ) -> None:
        """Smoothly drags cursor from start to end coordinates."""
        ...

    def mouse_scroll(self, dx: int, dy: int) -> None:
        """Emulates mouse wheel scroll (dy: positive=up, negative=down)."""
        ...

    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        """Types string of text with keystroke interval."""
        ...

    def keyboard_press_key(self, key_name: str) -> None:
        """Presses and releases a single key."""
        ...

    def keyboard_hotkey(self, keys: List[str]) -> None:
        """Presses multiple keys simultaneously and releases in reverse order."""
        ...


@runtime_checkable
class IWindowManager(Protocol):
    """Protocol for window enumeration, inspection, and focus management."""

    def list_windows(self) -> List[WindowInfo]:
        """Lists active top-level windows."""
        ...

    def get_active_window(self) -> Optional[WindowInfo]:
        """Returns currently focused top-level window."""
        ...

    def focus_window(self, window_id: str) -> bool:
        """Brings the window identified by window_id to foreground."""
        ...


@runtime_checkable
class IAXTreeDriver(Protocol):
    """Protocol for native OS accessibility tree inspection and diffing."""

    def get_accessibility_tree(
        self,
        app_filter: Optional[str] = None,
        max_depth: Optional[int] = None,
        diff_only: bool = False,
    ) -> Dict[str, Any]:
        """Extracts accessibility node hierarchy or diff."""
        ...


@runtime_checkable
class IDesktopHALProtocol(IScreenCapture, IInputDriver, IWindowManager, Protocol):
    """Composite protocol representing the full Desktop Hardware Abstraction Layer."""
    ...
