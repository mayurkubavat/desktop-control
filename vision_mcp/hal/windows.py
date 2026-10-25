"""Windows Desktop Hardware Abstraction Layer stub / implementation."""

import sys
from typing import Tuple, List, Optional
from PIL import Image

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.types import WindowInfo, BoundingBox


class WindowsHAL(IDesktopHAL):
    """
    Windows 10/11 Desktop HAL implementation.
    Architected for dxcam (DXGI GPU screen capture), Win32 SendInput (PerMonitorV2 DPI aware),
    and pywinauto / UIA3 window querying.
    """

    def __init__(self) -> None:
        if sys.platform != "win32":
            # Allowed for test environments or cross-compilation mocks
            pass
        else:
            self._init_dpi_awareness()

    def _init_dpi_awareness(self) -> None:
        """Initializes DPI awareness context to avoid coordinate drift on scaled screens."""
        try:
            import ctypes
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        except Exception:
            pass

    def get_screen_size(self) -> Tuple[int, int]:
        if sys.platform != "win32":
            return (1920, 1080)
        import ctypes
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """Captures screen using DXGI / dxcam on Windows."""
        try:
            import dxcam
            camera = dxcam.create(output_color="RGB")
            frame = camera.grab(region=region) if region else camera.grab()
            return Image.fromarray(frame)
        except Exception:
            # Fallback to Pillow ImageGrab
            from PIL import ImageGrab
            bbox = (region[0], region[1], region[0] + region[2], region[1] + region[3]) if region else None
            return ImageGrab.grab(bbox=bbox)

    def get_cursor_position(self) -> Tuple[int, int]:
        if sys.platform != "win32":
            return (0, 0)
        import ctypes
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def mouse_move(self, x: int, y: int) -> None:
        if sys.platform != "win32":
            return
        import ctypes
        ctypes.windll.user32.SetCursorPos(x, y)

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        self.mouse_move(x, y)
        # Windows Win32 SendInput or mouse_event
        import ctypes
        import time
        flags = {
            "left": (0x0002, 0x0004),
            "right": (0x0008, 0x0010),
            "middle": (0x0020, 0x0040),
        }.get(button, (0x0002, 0x0004))
        for _ in range(click_count):
            ctypes.windll.user32.mouse_event(flags[0], 0, 0, 0, 0)
            time.sleep(0.01)
            ctypes.windll.user32.mouse_event(flags[1], 0, 0, 0, 0)
            time.sleep(0.01)

    def mouse_drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3) -> None:
        self.mouse_move(start_x, start_y)
        import ctypes
        import time
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        try:
            steps = 30
            for i in range(1, steps + 1):
                cur_x = int(start_x + (end_x - start_x) * (i / steps))
                cur_y = int(start_y + (end_y - start_y) * (i / steps))
                ctypes.windll.user32.SetCursorPos(cur_x, cur_y)
                time.sleep(duration_sec / steps)
        finally:
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

    def mouse_scroll(self, dx: int, dy: int) -> None:
        if sys.platform != "win32":
            return
        import ctypes
        # MOUSEEVENTF_WHEEL = 0x0800, wheel delta 120 per click
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(dy * 120), 0)

    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        from pynput.keyboard import Controller
        kb = Controller()
        import time
        for char in text:
            kb.type(char)
            time.sleep(delay_ms / 1000.0)

    def keyboard_press_key(self, key_name: str) -> None:
        from pynput.keyboard import Controller
        kb = Controller()
        kb.press(key_name)
        kb.release(key_name)

    def keyboard_hotkey(self, keys: List[str]) -> None:
        from pynput.keyboard import Controller
        kb = Controller()
        for k in keys:
            kb.press(k)
        for k in reversed(keys):
            kb.release(k)

    def list_windows(self) -> List[WindowInfo]:
        """Queries Windows using Win32 EnumWindows or pywinauto."""
        return []

    def focus_window(self, window_id: str) -> bool:
        return False
