"""Linux Desktop Hardware Abstraction Layer implementation.

Native imports (mss, pynput, Xlib) happen on first instantiation, not at
module import, so collecting this module on macOS or Windows does not
require those packages.
"""

import os
import time
from typing import Any, Tuple, List, Optional
from PIL import Image

from dobby.hal.base import IDesktopHAL
from dobby.types import WindowInfo, BoundingBox, DisplayMetrics, DisplayTopology
from dobby.config import CONFIG

_native_loaded = False
mss: Any = None
MouseController: Any = None
Button: Any = None
KeyboardController: Any = None
Key: Any = None
X: Any = None
display: Any = None
xlib_error: Any = None
protocol_event: Any = None


def _load_native() -> None:
    """Imports Linux desktop libraries once."""
    global _native_loaded, mss, MouseController, Button, KeyboardController, Key
    global X, display, xlib_error, protocol_event
    if _native_loaded:
        return
    try:
        import mss as _mss
        from pynput.mouse import Button as _Button
        from pynput.mouse import Controller as _MouseController
        from pynput.keyboard import Controller as _KeyboardController
        from pynput.keyboard import Key as _Key
        from Xlib import X as _X
        from Xlib import display as _display
        from Xlib import error as _xlib_error
        from Xlib.protocol import event as _protocol_event
    except ImportError as exc:
        raise ImportError(
            "Linux HAL needs the 'linux' extra: pip install -e '.[linux]'"
        ) from exc
    mss = _mss
    MouseController = _MouseController
    Button = _Button
    KeyboardController = _KeyboardController
    Key = _Key
    X = _X
    display = _display
    xlib_error = _xlib_error
    protocol_event = _protocol_event
    _native_loaded = True


class LinuxHAL(IDesktopHAL):
    """
    Linux Desktop HAL supporting X11 natively and Wayland via compatible protocols.
    Uses mss for high-speed screen capture, pynput for mouse/keyboard injection,
    and python-xlib for window hierarchy querying.
    """

    def __init__(self) -> None:
        _load_native()
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self._sct = mss.MSS()
        self._is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        self._x_display: Optional[display.Display] = None
        # Open X whenever DISPLAY is set. Under XWayland both DISPLAY and
        # WAYLAND_DISPLAY are set and X11 clients are still reachable.
        if os.environ.get("DISPLAY"):
            try:
                self._x_display = display.Display()
            except Exception:
                self._x_display = None
        if self._x_display is None:
            self.display_server = "none"
        elif self._is_wayland:
            self.display_server = "XWayland"
        else:
            self.display_server = "X11"

    def _check_failsafe(self, x: int, y: int) -> None:
        """Emergency abort if pointer is directed to top-left (0, 0)."""
        if CONFIG.failsafe_corner and x == 0 and y == 0:
            raise RuntimeError("VisionMCP Failsafe Triggered: Cursor moved to (0, 0). Aborting execution.")

    def display_topology(self) -> DisplayTopology:
        """Logical virtual desktop from mss monitors. Monitor 0 is the union."""
        displays: List[DisplayMetrics] = []
        monitors = self._sct.monitors
        indexed = monitors[1:] if len(monitors) > 1 else monitors
        for i, mon in enumerate(indexed):
            displays.append(
                DisplayMetrics(
                    display_id=f"mss-{i + 1}",
                    origin=(int(mon.get("left", 0)), int(mon.get("top", 0))),
                    size=(int(mon["width"]), int(mon["height"])),
                    scale=1.0,
                )
            )
        if not displays:
            displays.append(DisplayMetrics(display_id="primary", origin=(0, 0), size=(0, 0)))
        return DisplayTopology(displays=displays, primary_id=displays[0].display_id)

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

    # ------------------------------------------------------------ windows
    #
    # EWMH (_NET_*) properties set by every mainstream X11 window manager.
    # Under XWayland only X11 clients are visible; native Wayland windows are not.

    _SKIP_TYPES = (
        "_NET_WM_WINDOW_TYPE_DOCK",
        "_NET_WM_WINDOW_TYPE_DESKTOP",
        "_NET_WM_WINDOW_TYPE_NOTIFICATION",
        "_NET_WM_WINDOW_TYPE_TOOLTIP",
    )

    def _atom(self, name: str) -> int:
        cache = self.__dict__.setdefault("_atoms", {})
        if name not in cache:
            cache[name] = self._x_display.intern_atom(name)
        return cache[name]

    def _prop(self, win: Any, name: str) -> Any:
        try:
            p = win.get_full_property(self._atom(name), X.AnyPropertyType)
        except Exception:
            return None
        return p.value if p is not None else None

    def _active_id(self) -> Optional[int]:
        root = self._x_display.screen().root
        val = self._prop(root, "_NET_ACTIVE_WINDOW")
        try:
            wid = int(val[0]) if val is not None and len(val) else 0
        except Exception:
            wid = 0
        return wid or None

    def _stacked_ids(self) -> List[int]:
        """Managed windows, front to back (stacking order when the WM provides it)."""
        root = self._x_display.screen().root
        stacking = self._prop(root, "_NET_CLIENT_LIST_STACKING")
        if stacking is not None and len(stacking):
            return [int(w) for w in reversed(list(stacking))]  # EWMH lists bottom to top
        clients = self._prop(root, "_NET_CLIENT_LIST")
        return [int(w) for w in clients] if clients is not None else []

    def _window_info(self, win_id: int, active_id: Optional[int]) -> Optional[WindowInfo]:
        win = self._x_display.create_resource_object("window", win_id)
        types = self._prop(win, "_NET_WM_WINDOW_TYPE")
        if types is not None:
            skip = {self._atom(t) for t in self._SKIP_TYPES}
            if any(int(t) in skip for t in types):
                return None
        state = self._prop(win, "_NET_WM_STATE")
        if state is not None and self._atom("_NET_WM_STATE_HIDDEN") in [int(a) for a in state]:
            return None  # minimised
        attrs = win.get_attributes()
        if getattr(attrs, "map_state", X.IsViewable) != X.IsViewable:
            return None

        name = self._prop(win, "_NET_WM_NAME")
        if name is None:
            name = self._prop(win, "WM_NAME")
        if isinstance(name, bytes):
            title = name.decode("utf-8", errors="ignore")
        else:
            title = str(name) if name is not None else ""

        app_name = None
        try:
            wm_class = win.get_wm_class()
            if wm_class:
                app_name = wm_class[-1] or wm_class[0]
        except Exception:
            pass

        geom = win.get_geometry()
        root = self._x_display.screen().root
        coords = root.translate_coords(win, 0, 0)
        x, y, w, h = int(coords.x), int(coords.y), int(geom.width), int(geom.height)
        # Include the WM decoration (title bar, borders) so occlusion matches what is drawn.
        extents = self._prop(win, "_NET_FRAME_EXTENTS")
        if extents is not None and len(extents) == 4:
            left, right, top, bottom = (int(v) for v in extents)
            x, y, w, h = x - left, y - top, w + left + right, h + top + bottom
        if w < 20 or h < 20:
            return None

        return WindowInfo(
            window_id=hex(win_id),
            title=title or (app_name or "Untitled"),
            bbox=BoundingBox(x=x, y=y, width=w, height=h),
            is_active=(win_id == active_id),
            app_name=app_name,
        )

    def client_windows(self) -> List[dict]:
        """Front-to-back client areas (no WM frame) with pid and title.

        The AT-SPI inspector uses these to place GTK 4 widgets, which only
        report window-relative coordinates.
        """
        if not self._x_display:
            return []
        out: List[dict] = []
        try:
            root = self._x_display.screen().root
            for win_id in self._stacked_ids():
                try:
                    win = self._x_display.create_resource_object("window", win_id)
                    geom = win.get_geometry()
                    coords = root.translate_coords(win, 0, 0)
                    pid = self._prop(win, "_NET_WM_PID")
                    name = self._prop(win, "_NET_WM_NAME")
                    if name is None:
                        name = self._prop(win, "WM_NAME")
                    title = name.decode("utf-8", "ignore") if isinstance(name, bytes) else str(name or "")
                    out.append({
                        "window_id": hex(win_id),
                        "pid": int(pid[0]) if pid is not None and len(pid) else None,
                        "title": title,
                        "x": int(coords.x), "y": int(coords.y),
                        "width": int(geom.width), "height": int(geom.height),
                    })
                except (xlib_error.BadWindow, xlib_error.BadDrawable, xlib_error.BadMatch):
                    continue
        except Exception:
            return out
        return out

    def list_windows(self) -> List[WindowInfo]:
        """Visible top-level windows, front to back, docks and minimised windows excluded."""
        if not self._x_display:
            return []
        try:
            active_id = self._active_id()
            results: List[WindowInfo] = []
            for win_id in self._stacked_ids():
                try:
                    info = self._window_info(win_id, active_id)
                except (xlib_error.BadWindow, xlib_error.BadDrawable, xlib_error.BadMatch):
                    continue
                if info is not None:
                    results.append(info)
            return results
        except Exception:
            return []

    def get_active_window(self) -> Optional[WindowInfo]:
        """The window named by _NET_ACTIVE_WINDOW, if it is a visible top-level window."""
        if not self._x_display:
            return None
        try:
            active_id = self._active_id()
            if active_id is None:
                return None
            return self._window_info(active_id, active_id)
        except Exception:
            return None

    def window_pid(self, window_id: str) -> Optional[int]:
        """Owning process id from _NET_WM_PID (set by GTK, Qt, Electron and most toolkits)."""
        if not self._x_display:
            return None
        try:
            win = self._x_display.create_resource_object("window", _parse_window_id(window_id))
            val = self._prop(win, "_NET_WM_PID")
            return int(val[0]) if val is not None and len(val) else None
        except Exception:
            return None

    def focus_window(self, window_id: str) -> bool:
        """Activates the window via _NET_ACTIVE_WINDOW and reports whether focus actually moved."""
        if not self._x_display:
            return False
        try:
            win_int = _parse_window_id(window_id)
            root = self._x_display.screen().root
            win = self._x_display.create_resource_object("window", win_int)
            # Source indication 2 = pager/automation: WMs honour it without focus-stealing checks.
            event = protocol_event.ClientMessage(
                window=win,
                client_type=self._atom("_NET_ACTIVE_WINDOW"),
                data=(32, [2, X.CurrentTime, 0, 0, 0]),
            )
            root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            self._x_display.flush()

            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if self._active_id() == win_int:
                    break
                time.sleep(0.02)
            else:
                # No (or a stubborn) window manager: raise and focus directly.
                try:
                    win.map()
                    win.configure(stack_mode=X.Above)
                    self._x_display.set_input_focus(win, X.RevertToParent, X.CurrentTime)
                    self._x_display.sync()
                except Exception:
                    pass
            time.sleep(CONFIG.action_cooldown_ms / 1000.0)
            active = self._active_id()
            return active == win_int or active is None
        except Exception:
            return False


def _parse_window_id(window_id: str) -> int:
    s = str(window_id).strip()
    return int(s, 16) if s.lower().startswith("0x") else int(s)
