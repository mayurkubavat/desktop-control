"""Linux Desktop Hardware Abstraction Layer implementation."""

import os
import time
from typing import Tuple, List, Optional
from PIL import Image
import mss
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key
from Xlib import X, display, error as xlib_error
from Xlib.protocol import event as protocol_event

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.types import WindowInfo, BoundingBox
from vision_mcp.config import CONFIG


class LinuxHAL(IDesktopHAL):
    """
    Linux Desktop HAL supporting X11 natively and Wayland via compatible protocols.
    Uses mss for high-speed screen capture, pynput for mouse/keyboard injection,
    and python-xlib for window hierarchy querying.
    """

    def __init__(self) -> None:
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self._sct = mss.MSS()
        self._is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        self._x_display: Optional[display.Display] = None

        if not self._is_wayland:
            try:
                self._x_display = display.Display()
            except Exception:
                self._x_display = None

    def _check_failsafe(self, x: int, y: int) -> None:
        """Emergency abort if pointer is directed to top-left (0, 0)."""
        if CONFIG.failsafe_corner and x == 0 and y == 0:
            raise RuntimeError("VisionMCP Failsafe Triggered: Cursor moved to (0, 0). Aborting execution.")

    def get_screen_size(self) -> Tuple[int, int]:
        """Returns primary monitor dimensions in pixels."""
        if len(self._sct.monitors) > 1:
            # Monitor 1 is the primary monitor in mss
            mon = self._sct.monitors[1]
            return mon["width"], mon["height"]
        mon = self._sct.monitors[0]
        return mon["width"], mon["height"]

    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """Captures full screen or region (x, y, width, height)."""
        if region:
            x, y, w, h = region
            bbox = {"top": y, "left": x, "width": w, "height": h}
            raw = self._sct.grab(bbox)
        else:
            mon = self._sct.monitors[1] if len(self._sct.monitors) > 1 else self._sct.monitors[0]
            raw = self._sct.grab(mon)

        # Convert raw BGRA bytes to RGB PIL Image
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return img

    def get_cursor_position(self) -> Tuple[int, int]:
        """Returns current pointer position."""
        pos = self.mouse.position
        return int(pos[0]), int(pos[1])

    def mouse_move(self, x: int, y: int) -> None:
        """Moves cursor to absolute coordinates."""
        self._check_failsafe(x, y)
        self.mouse.position = (x, y)
        time.sleep(CONFIG.action_cooldown_ms / 1000.0)

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        """Moves cursor and executes button click(s)."""
        self.mouse_move(x, y)
        btn = Button.left if button == "left" else (Button.right if button == "right" else Button.middle)
        self.mouse.click(btn, click_count)
        time.sleep(CONFIG.action_cooldown_ms / 1000.0)

    def mouse_drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3) -> None:
        """Smoothly drags cursor between two points."""
        self.mouse_move(start_x, start_y)
        self.mouse.press(Button.left)
        try:
            steps = max(int(duration_sec * 60), 10)
            step_delay = duration_sec / steps
            for i in range(1, steps + 1):
                cur_x = int(start_x + (end_x - start_x) * (i / steps))
                cur_y = int(start_y + (end_y - start_y) * (i / steps))
                self.mouse.position = (cur_x, cur_y)
                time.sleep(step_delay)
        finally:
            self.mouse.release(Button.left)
            time.sleep(CONFIG.action_cooldown_ms / 1000.0)

    def mouse_scroll(self, dx: int, dy: int) -> None:
        """Scrolls wheel."""
        self.mouse.scroll(dx, dy)
        time.sleep(CONFIG.action_cooldown_ms / 1000.0)

    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        """Types string with natural timing."""
        delay_sec = max(delay_ms / 1000.0, 0.001)
        for char in text:
            self.keyboard.type(char)
            time.sleep(delay_sec)
        time.sleep(CONFIG.action_cooldown_ms / 1000.0)

    def _resolve_key(self, key_str: str) -> Any:
        """Resolves string key names into pynput Key or character."""
        key_map = {
            "enter": Key.enter,
            "return": Key.enter,
            "tab": Key.tab,
            "space": Key.space,
            "backspace": Key.backspace,
            "delete": Key.delete,
            "escape": Key.esc,
            "esc": Key.esc,
            "up": Key.up,
            "down": Key.down,
            "left": Key.left,
            "right": Key.right,
            "home": Key.home,
            "end": Key.end,
            "pageup": Key.page_up,
            "page_up": Key.page_up,
            "pagedown": Key.page_down,
            "page_down": Key.page_down,
            "ctrl": Key.ctrl,
            "control": Key.ctrl,
            "alt": Key.alt,
            "shift": Key.shift,
            "super": Key.cmd,
            "meta": Key.cmd,
            "cmd": Key.cmd,
            "win": Key.cmd,
            "f1": Key.f1,
            "f2": Key.f2,
            "f3": Key.f3,
            "f4": Key.f4,
            "f5": Key.f5,
            "f6": Key.f6,
            "f7": Key.f7,
            "f8": Key.f8,
            "f9": Key.f9,
            "f10": Key.f10,
            "f11": Key.f11,
            "f12": Key.f12,
        }
        low = key_str.lower().strip()
        return key_map.get(low, key_str)

    def keyboard_press_key(self, key_name: str) -> None:
        """Presses and releases a single key."""
        k = self._resolve_key(key_name)
        self.keyboard.press(k)
        time.sleep(0.02)
        self.keyboard.release(k)
        time.sleep(CONFIG.action_cooldown_ms / 1000.0)

    def keyboard_hotkey(self, keys: List[str]) -> None:
        """Sends multi-key chord shortcut."""
        resolved = [self._resolve_key(k) for k in keys]
        for k in resolved:
            self.keyboard.press(k)
            time.sleep(0.01)
        time.sleep(0.05)
        for k in reversed(resolved):
            self.keyboard.release(k)
            time.sleep(0.01)
        time.sleep(CONFIG.action_cooldown_ms / 1000.0)

    def list_windows(self) -> List[WindowInfo]:
        """Lists active top-level windows using X11 EWMH."""
        if not self._x_display:
            return []

        try:
            root = self._x_display.screen().root
            net_client_list = self._x_display.intern_atom("_NET_CLIENT_LIST")
            net_wm_name = self._x_display.intern_atom("_NET_WM_NAME")
            net_active_win = self._x_display.intern_atom("_NET_ACTIVE_WINDOW")
            wm_name = self._x_display.intern_atom("WM_NAME")

            client_list = root.get_full_property(net_client_list, X.AnyPropertyType)
            active_prop = root.get_full_property(net_active_win, X.AnyPropertyType)
            active_id = active_prop.value[0] if active_prop and active_prop.value else None

            if not client_list:
                return []

            results: List[WindowInfo] = []
            for win_id in client_list.value:
                try:
                    win = self._x_display.create_resource_object("window", win_id)
                    name_prop = win.get_full_property(net_wm_name, 0) or win.get_full_property(wm_name, 0)
                    title = name_prop.value.decode("utf-8", errors="ignore") if name_prop else "Untitled"
                    geom = win.get_geometry()
                    
                    # Convert window coordinates to root coordinates
                    coords = root.translate_coords(win, 0, 0)

                    bbox = BoundingBox(
                        x=coords.x,
                        y=coords.y,
                        width=geom.width,
                        height=geom.height,
                    )
                    
                    results.append(
                        WindowInfo(
                            window_id=hex(win_id),
                            title=title,
                            bbox=bbox,
                            is_active=(win_id == active_id),
                        )
                    )
                except (xlib_error.BadWindow, xlib_error.BadDrawable):
                    continue

            return results
        except Exception:
            return []

    def get_active_window(self) -> Optional[WindowInfo]:
        """Returns the currently active / focused window."""
        windows = self.list_windows()
        for win in windows:
            if win.is_active:
                return win
        return None

    def focus_window(self, window_id: str) -> bool:
        """Focuses target window using _NET_ACTIVE_WINDOW and fallback stack-raising."""
        if not self._x_display:
            return False

        try:
            win_int = int(window_id, 16) if window_id.startswith("0x") else int(window_id)
            root = self._x_display.screen().root
            net_active_win = self._x_display.intern_atom("_NET_ACTIVE_WINDOW")
            
            # 1. Send EWMH _NET_ACTIVE_WINDOW ClientMessage to root window manager
            event = protocol_event.ClientMessage(
                window=win_int,
                client_type=net_active_win,
                data=(32, [1, X.CurrentTime, 0, 0, 0]),
            )
            root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)

            # 2. Direct window map and configure fallback in case WM doesn't redirect
            try:
                win = self._x_display.create_resource_object("window", win_int)
                win.map()
                win.configure(stack_mode=X.Above)
                self._x_display.set_input_focus(win, X.RevertToParent, X.CurrentTime)
            except Exception:
                pass

            self._x_display.sync()
            time.sleep(CONFIG.action_cooldown_ms / 1000.0)
            return True
        except Exception:
            return False
