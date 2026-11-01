"""Base Desktop Hardware Abstraction Layer (HAL) Interface."""

from abc import ABC, abstractmethod
from typing import Tuple, List, Optional
from PIL import Image
from dobby.types import WindowInfo


class IDesktopHAL(ABC):
    """Abstract interface defining required OS desktop navigation and input capabilities."""

    @abstractmethod
    def get_screen_size(self) -> Tuple[int, int]:
        """Returns the primary screen resolution as (width, height) in physical pixels."""
        pass

    @abstractmethod
    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """
        Captures the screen.
        
        Args:
            region: Optional (x, y, width, height) bounding box. If None, captures entire primary desktop.
            
        Returns:
            PIL Image in RGB mode.
        """
        pass

    @abstractmethod
    def get_cursor_position(self) -> Tuple[int, int]:
        """Returns current mouse pointer coordinates (x, y)."""
        pass

    @abstractmethod
    def mouse_move(self, x: int, y: int) -> None:
        """Moves cursor to absolute coordinates (x, y)."""
        pass

    @abstractmethod
    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        """
        Clicks at target coordinates.
        
        Args:
            x: Target X coordinate
            y: Target Y coordinate
            button: 'left', 'right', or 'middle'
            click_count: 1 for single click, 2 for double click, 3 for triple click
        """
        pass

    @abstractmethod
    def mouse_drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3) -> None:
        """Performs a smooth mouse drag from (start_x, start_y) to (end_x, end_y)."""
        pass

    @abstractmethod
    def mouse_scroll(self, dx: int, dy: int) -> None:
        """
        Emulates mouse wheel scroll.
        
        Args:
            dx: Horizontal scroll clicks
            dy: Vertical scroll clicks (positive = scroll up, negative = scroll down)
        """
        pass

    @abstractmethod
    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        """Types string of text with a natural keystroke interval."""
        pass

    @abstractmethod
    def keyboard_press_key(self, key_name: str) -> None:
        """Presses and releases a single key (e.g. 'enter', 'tab', 'esc', 'space', 'backspace')."""
        pass

    @abstractmethod
    def keyboard_hotkey(self, keys: List[str]) -> None:
        """Presses multiple keys simultaneously and releases in reverse order (e.g. ['ctrl', 'c'])."""
        pass

    @abstractmethod
    def list_windows(self) -> List[WindowInfo]:
        """Lists active top-level windows with their IDs, titles, geometries, and focus states."""
        pass

    @abstractmethod
    def get_active_window(self) -> Optional[WindowInfo]:
        """Returns the currently active / focused top-level window if available."""
        pass

    @abstractmethod
    def focus_window(self, window_id: str) -> bool:
        """Brings the window identified by window_id to the foreground."""
        pass
