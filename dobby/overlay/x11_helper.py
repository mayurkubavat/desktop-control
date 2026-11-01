"""Overlay helper for Linux X11: ``python -m dobby.overlay`` when DISPLAY is set.

Speaks the same JSON-lines protocol as ``mac_helper`` (see ``protocol.py``),
drawn with GTK 3 + cairo through PyGObject (Debian/Ubuntu: python3-gi,
python3-gi-cairo, gir1.2-gtk-3.0).

What it draws:

* the agent pointer (violet arrow) gliding to each target, with a ripple on
  clicks when a compositor is running;
* a capsule tag next to the pointer with the label, state and current intent;
* a glow frame around the tracked window and a thinner box around the target
  element (from the AT-SPI hit test when a move asks for a probe);
* an Allow / Deny window for ``confirm``.

Every panel except the confirm window is an override-redirect popup with an
empty input shape, so clicks go straight through. Without a compositor the
pointer and tag are cut to their drawn shape with XShape, and the frames use
four thin edge windows, so nothing opaque covers the screen.

Controls: Ctrl+Alt+Esc sends ``stop``; Ctrl+Alt+P toggles ``pause`` /
``resume`` (global key grabs on the root window).

Not ported from macOS yet: the numbered step trail, the scan sweep, the menu
bar item and user take-over detection. Their ops are accepted and acked so the
server behaves the same.
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
import cairo  # noqa: E402
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import geometry, protocol  # noqa: E402

DEFAULT_CONFIG: Dict[str, Any] = {
    "color": "#7C5CFF",
    "caution_color": "#F5A524",
    "danger_color": "#F04438",
    "label": "Dobby",
    "speed": 1.0,
    "glow_width": 3,
    "box_width": 2,
    "track_hz": 5.0,
    "intent_ms": 1600,
    "turbo": False,
}

# Classic arrow, y down, tip at (0, 0) (same outline as the macOS helper).
_ARROW = [(0, 0), (0, 18), (4.5, 14), (8, 21.5), (10.5, 20.5), (7, 13), (13, 13)]
_STATE_ICON = {"idle": "", "thinking": "…", "typing": "⌨", "waiting_user": "?"}


def _rgb(value: str) -> Tuple[float, float, float]:
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _short(text: str, n: int = 48) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


class _Panel(Gtk.Window):
    """Click-through override-redirect window drawn with cairo."""

    def __init__(self, composited: bool, w: int, h: int, painter=None) -> None:
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_title(protocol.OVERLAY_WINDOW_TITLE)
        self.set_app_paintable(True)
        self.set_accept_focus(False)
        self.set_keep_above(True)
        self.composited = composited
        if composited:
            visual = self.get_screen().get_rgba_visual()
            if visual is not None:
                self.set_visual(visual)
        self.painter = painter
        self.set_default_size(w, h)
        self.resize(w, h)
        self.connect("draw", self._on_draw)
        self.connect("realize", self._on_realize)

    def _on_realize(self, *_a) -> None:
        # Empty input region: every click falls through to the app below.
        self.input_shape_combine_region(cairo.Region())

    def _on_draw(self, _w, cr) -> bool:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self.painter is not None:
            self.painter(cr, self.get_allocated_width(), self.get_allocated_height())
        return False

    def reshape(self) -> None:
        """Without a compositor, cut the window to what the painter draws."""
        if self.composited or self.painter is None:
            return
        w, h = self.get_size()
        surf = cairo.ImageSurface(cairo.FORMAT_A1, max(w, 1), max(h, 1))
        cr = cairo.Context(surf)
        self.painter(cr, w, h)
        region = Gdk.cairo_region_create_from_surface(surf)
        self.shape_combine_region(region)


class _Frame:
    """A rectangle outline made of four solid edge windows (needs no compositor)."""

    def __init__(self, width: int) -> None:
        self.width = width
        self.color = (0.5, 0.4, 1.0)
        self.edges: List[_Panel] = []
        for _ in range(4):
            p = _Panel(False, 1, 1, painter=self._paint)
            self.edges.append(p)
        self.rect: Optional[Tuple[int, int, int, int]] = None
        self.visible = False

    def _paint(self, cr, w, h) -> None:
        cr.set_source_rgb(*self.color)
        cr.rectangle(0, 0, w, h)
        cr.fill()

    def set_color(self, rgb) -> None:
        self.color = rgb
        for e in self.edges:
            e.queue_draw()

    def place(self, rect: Optional[Tuple[int, int, int, int]]) -> None:
        self.rect = rect
        if rect is None:
            self.hide()
            return
        x, y, w, h = (int(v) for v in rect)
        t = self.width
        boxes = [
            (x - t, y - t, w + 2 * t, t),  # top
            (x - t, y + h, w + 2 * t, t),  # bottom
            (x - t, y, t, h),              # left
            (x + w, y, t, h),              # right
        ]
        for edge, (bx, by, bw, bh) in zip(self.edges, boxes):
            edge.resize(max(bw, 1), max(bh, 1))
            edge.move(bx, by)
        self.show()

    def show(self) -> None:
        if self.rect is None:
            return
        self.visible = True
        for e in self.edges:
            e.show_all()

    def hide(self) -> None:
        self.visible = False
        for e in self.edges:
            e.hide()


class X11Overlay:
    def __init__(self, cfg: Dict[str, Any], out=None) -> None:
        self.cfg = dict(DEFAULT_CONFIG)
        self.cfg.update(cfg or {})
        self.out = out or sys.stdout
        self._wlock = threading.Lock()
        screen = Gdk.Screen.get_default()
        self.composited = bool(screen is not None and screen.is_composited())

        self.risk = "ok"
        self.state = "idle"
        self.intent = ""
        self.intent_until = 0.0
        self.cursor: Optional[Tuple[float, float]] = None
        self._anim_id: Optional[int] = None
        self.user_visible = True
        self.capture_hidden = False
        self.paused = False
        self.pending_confirm: Optional[Tuple[Any, Gtk.Window, int]] = None
        self.track_wid: Optional[int] = None
        self.track_pid: Optional[int] = None

        self.pointer = _Panel(self.composited, 26, 28, painter=self._paint_pointer)
        self.tag = _Panel(self.composited, 120, 26, painter=self._paint_tag)
        self.ripple = _Panel(True, 48, 48, painter=self._paint_ripple) if self.composited else None
        self._ripple_t = 1.0
        self.glow = _Frame(int(self.cfg["glow_width"]))
        self.box = _Frame(int(self.cfg["box_width"]))
        self._apply_colors()

        self._hal = None
        self._probe = None
        GLib.timeout_add(int(1000 / max(float(self.cfg["track_hz"]), 0.5)), self._track_tick)
        GLib.timeout_add(200, self._tag_tick)

    # ------------------------------------------------------------- output
    def _write(self, text: str) -> None:
        with self._wlock:
            try:
                self.out.write(text)
                self.out.flush()
            except (BrokenPipeError, ValueError):
                GLib.idle_add(self.quit)

    def emit(self, obj: Dict[str, Any]) -> None:
        self._write(json.dumps(obj, separators=(",", ":")) + "\n")

    def send_event(self, name: str) -> None:
        self._write(protocol.event(name))

    def ack(self, msg_id: Any, ok: bool = True, error: Optional[str] = None) -> bool:
        if msg_id is not None:
            self._write(protocol.ack(msg_id, ok, error))
        return False  # usable as a one-shot GLib callback

    # ------------------------------------------------------------- colors
    def _color(self) -> Tuple[float, float, float]:
        key = {"caution": "caution_color", "danger": "danger_color"}.get(self.risk, "color")
        return _rgb(self.cfg[key])

    def _apply_colors(self) -> None:
        c = self._color()
        self.glow.set_color(c)
        self.box.set_color(tuple(min(1.0, v * 0.6 + 0.4) for v in c))
        self.pointer.queue_draw()
        self.tag.queue_draw()

    # ------------------------------------------------------------ painters
    def _paint_pointer(self, cr, w, h) -> None:
        s = 1.15
        cr.translate(2, 2)
        cr.move_to(*_ARROW[0])
        for x, y in _ARROW[1:]:
            cr.line_to(x * s, y * s)
        cr.close_path()
        cr.set_source_rgb(*self._color())
        cr.fill_preserve()
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(1.6)
        cr.stroke()

    def _tag_text(self) -> str:
        parts = [self.cfg["label"]]
        icon = _STATE_ICON.get(self.state, "")
        if self.paused:
            icon = "⏸"
        if icon:
            parts.append(icon)
        if self.intent and time.monotonic() < self.intent_until:
            parts.append(self.intent)
        return "  ".join(parts)

    def _paint_tag(self, cr, w, h) -> None:
        r = h / 2.0
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, math.pi / 2)
        cr.arc(r, r, r, math.pi / 2, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgb(*self._color())
        cr.fill()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(10, h / 2.0 + 4.5)
        cr.show_text(self._tag_text())

    def _paint_ripple(self, cr, w, h) -> None:
        t = self._ripple_t
        if t >= 1.0:
            return
        r, g, b = self._color()
        cr.set_source_rgba(r, g, b, 0.8 * (1 - t))
        cr.set_line_width(3)
        cr.arc(w / 2, h / 2, 6 + t * (w / 2 - 8), 0, 2 * math.pi)
        cr.stroke()

    # ------------------------------------------------------------ layout
    def _overlay_shown(self) -> bool:
        return self.user_visible and not self.capture_hidden

    def _layout_tag(self) -> None:
        if self.cursor is None or not self._overlay_shown():
            self.tag.hide()
            return
        text = self._tag_text()
        probe = cairo.Context(cairo.ImageSurface(cairo.FORMAT_A1, 1, 1))
        probe.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        probe.set_font_size(12)
        width = int(probe.text_extents(text).x_advance) + 22
        self.tag.resize(width, 24)
        self.tag.move(int(self.cursor[0]) + 18, int(self.cursor[1]) + 20)
        self.tag.queue_draw()
        self.tag.show_all()
        GLib.idle_add(self._reshape_later, self.tag)

    @staticmethod
    def _reshape_later(panel: _Panel) -> bool:
        panel.reshape()
        return False

    def _place_pointer(self, pt: Tuple[float, float]) -> None:
        self.cursor = pt
        if not self._overlay_shown():
            return
        self.pointer.move(int(pt[0]), int(pt[1]))
        if not self.pointer.get_visible():
            self.pointer.show_all()
            self.pointer.reshape()
        self._layout_tag()

    def _apply_visibility(self) -> None:
        shown = self._overlay_shown()
        panels = [self.pointer, self.tag] + ([self.ripple] if self.ripple else [])
        if not shown:
            for p in panels:
                p.hide()
            self.glow.hide()
            self.box.hide()
            return
        if self.cursor is not None:
            self._place_pointer(self.cursor)
        if self.glow.rect is not None:
            self.glow.show()
        if self.box.rect is not None:
            self.box.show()

    # ------------------------------------------------------------- motion
    def _duration(self, ms: Optional[float]) -> float:
        speed = float(self.cfg["speed"])
        if speed <= 0 or not ms:
            return 0.0
        return float(ms) / 1000.0

    def _glide(self, target: Tuple[float, float], dur: float, msg_id: Any) -> None:
        if self._anim_id is not None:
            GLib.source_remove(self._anim_id)
            self._anim_id = None
        start = self.cursor or target
        if dur <= 0:
            self._place_pointer(target)
            self.ack(msg_id)
            return
        t0 = time.monotonic()

        def step() -> bool:
            f = min((time.monotonic() - t0) / dur, 1.0)
            e = 1 - (1 - f) ** 3  # ease-out cubic
            self._place_pointer((start[0] + (target[0] - start[0]) * e, start[1] + (target[1] - start[1]) * e))
            if f >= 1.0:
                self._anim_id = None
                self.ack(msg_id)
                return False
            return True

        self._anim_id = GLib.timeout_add(16, step)

    def _ripple_at(self) -> None:
        if self.ripple is None or self.cursor is None or not self._overlay_shown():
            return
        self.ripple.move(int(self.cursor[0]) - 24, int(self.cursor[1]) - 24)
        self.ripple.show_all()
        t0 = time.monotonic()

        def step() -> bool:
            self._ripple_t = min((time.monotonic() - t0) / 0.35, 1.0)
            self.ripple.queue_draw()
            if self._ripple_t >= 1.0:
                self.ripple.hide()
                return False
            return True

        GLib.timeout_add(16, step)

    # ------------------------------------------------------------ tracking
    def _get_hal(self):
        if self._hal is None:
            try:
                from dobby.hal.linux import LinuxHAL

                self._hal = LinuxHAL()
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"dobby.overlay: no X11 HAL: {exc}\n")
                self._hal = False
        return self._hal or None

    def _tracked_rect(self) -> Optional[Tuple[int, int, int, int]]:
        hal = self._get_hal()
        if hal is None:
            return None
        try:
            windows = hal.list_windows()
        except Exception:
            return None
        for w in windows:
            wid = protocol.window_id_int(w.window_id)
            if self.track_wid is not None and wid == self.track_wid:
                b = w.bbox
                return (b.x, b.y, b.width, b.height)
        if self.track_pid is not None:
            for w in windows:  # front to back: the pid's topmost window
                if hal.window_pid(w.window_id) == self.track_pid:
                    b = w.bbox
                    return (b.x, b.y, b.width, b.height)
        return None

    def _track_tick(self) -> bool:
        if self.track_wid is None and self.track_pid is None:
            return True
        rect = self._tracked_rect()
        if rect != self.glow.rect:
            self.glow.place(rect)
            if not self._overlay_shown():
                self.glow.hide()
        return True

    def _tag_tick(self) -> bool:
        if self.intent and time.monotonic() >= self.intent_until:
            self.intent = ""
            self._layout_tag()
        return True

    def _probe_at(self, x: float, y: float) -> Tuple[str, Optional[Tuple[int, int, int, int]]]:
        if self._probe is None:
            try:
                from dobby.perception.atspi import ATSPIInspector

                insp = ATSPIInspector(hal=self._get_hal())
                self._probe = insp if insp.is_available else False
            except Exception:  # noqa: BLE001
                self._probe = False
        if not self._probe:
            return "", None
        hit = self._probe.hit_test(int(x), int(y))
        if not hit or not hit.get("bbox"):
            return "", None
        b = hit["bbox"]
        return hit.get("name") or "", (b["x"], b["y"], b["width"], b["height"])

    # ------------------------------------------------------------- confirm
    def _start_confirm(self, msg_id: Any, text: str, secs: float) -> None:
        if self.cfg.get("turbo"):
            self.ack(msg_id, True)
            return
        if self.pending_confirm is not None:
            self._answer_confirm(False)
        win = Gtk.Window(title=protocol.OVERLAY_WINDOW_TITLE)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.set_position(Gtk.WindowPosition.CENTER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
        label = Gtk.Label(label=f"{self.cfg['label']} wants to: {text}")
        label.set_line_wrap(True)
        label.set_max_width_chars(48)
        box.pack_start(label, True, True, 0)
        row = Gtk.Box(spacing=8)
        deny = Gtk.Button(label="Deny")
        allow = Gtk.Button(label="Allow")
        deny.connect("clicked", lambda *_: self._answer_confirm(False))
        allow.connect("clicked", lambda *_: self._answer_confirm(True))
        row.pack_end(allow, False, False, 0)
        row.pack_end(deny, False, False, 0)
        box.pack_start(row, False, False, 0)
        win.add(box)
        win.connect("delete-event", lambda *_: (self._answer_confirm(False), True)[1])
        win.show_all()
        timer = GLib.timeout_add(int(max(secs, 1.0) * 1000), lambda: (self._answer_confirm(False), False)[1])
        self.pending_confirm = (msg_id, win, timer)

    def _answer_confirm(self, ok: bool) -> None:
        if self.pending_confirm is None:
            return
        msg_id, win, timer = self.pending_confirm
        self.pending_confirm = None
        try:
            GLib.source_remove(timer)
        except Exception:  # noqa: BLE001 - already fired
            pass
        win.destroy()
        self.ack(msg_id, ok)

    # --------------------------------------------------------------- input
    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        msg_id = None
        try:
            raw = json.loads(line)
            msg_id = raw.get("id") if isinstance(raw, dict) else None
            self.handle(protocol.validate(raw))
        except Exception as exc:  # noqa: BLE001 - never die on one bad message
            sys.stderr.write(f"dobby.overlay: {exc}\n")
            self.ack(msg_id, False, str(exc))

    def handle(self, msg: Dict[str, Any]) -> None:
        op, msg_id = msg["op"], msg.get("id")
        if op == "cursor.move":
            target = (float(msg["x"]), float(msg["y"]))
            verb = msg.get("verb")
            if msg.get("probe"):
                name, frame = self._probe_at(*target)
                if frame is not None and 3 <= frame[2] <= 1600 and 3 <= frame[3] <= 900 \
                        and geometry.contains(frame, target):
                    self.box.place(frame)
                    if not self._overlay_shown():
                        self.box.hide()
                else:
                    self.box.place(None)
                if verb:
                    self._set_intent(f"{verb} ‘{_short(name, 32)}’" if name else verb)
            elif verb and verb != "Move":
                self._set_intent(verb)
            if self.cursor is None:
                start = self._real_mouse()
                self._place_pointer(start)
            ms = msg.get("ms")
            if ms is None:
                ms = geometry.glide_ms(self.cursor, target, speed=float(self.cfg["speed"]))
            if self.state == "thinking":
                self.state = "idle"
            self._glide(target, self._duration(ms), msg_id)
        elif op == "cursor.click":
            self._ripple_at()
            GLib.timeout_add(500, lambda: (self.box.place(None), False)[1])
            self.ack(msg_id)
        elif op == "cursor.state":
            self.state = msg["state"]
            self._layout_tag()
            self.ack(msg_id)
        elif op == "cursor.hide":
            self.pointer.hide()
            self.tag.hide()
            self.cursor = None
            self.ack(msg_id)
        elif op == "intent":
            self._set_intent(msg["text"], msg.get("ms"))
            self.ack(msg_id)
        elif op == "target.box":
            self.box.place((float(msg["x"]), float(msg["y"]), float(msg["w"]), float(msg["h"])))
            if not self._overlay_shown():
                self.box.hide()
            self.ack(msg_id)
        elif op == "target.clear":
            self.box.place(None)
            self.ack(msg_id)
        elif op == "risk":
            self.risk = msg["level"]
            self._apply_colors()
            self._layout_tag()
            self.ack(msg_id)
        elif op in ("scan", "trail.clear"):
            self.ack(msg_id)  # not drawn on Linux yet
        elif op == "confirm":
            self._start_confirm(msg_id, msg["text"], float(msg.get("secs", 30.0)))
        elif op == "confirm.cancel":
            self._answer_confirm(False)
            self.ack(msg_id)
        elif op == "overlay.visible":
            self.user_visible = bool(msg["on"])
            self._apply_visibility()
            self.ack(msg_id)
        elif op == "glow.track":
            self.track_wid = protocol.window_id_int(msg.get("window_id"))
            self.track_pid = msg.get("pid")
            self.glow.rect = None
            self._track_tick()
            self.ack(msg_id)
        elif op == "glow.clear":
            self.track_wid = self.track_pid = None
            self.glow.place(None)
            self.ack(msg_id)
        elif op == "hide":
            self.capture_hidden = True
            self._apply_visibility()
            Gdk.flush()
            # Give the X server a moment to unmap before the capture.
            GLib.timeout_add(50, self.ack, msg_id)
        elif op == "show":
            self.capture_hidden = False
            self._apply_visibility()
            self.ack(msg_id)
        elif op == "ping":
            self.ack(msg_id)
        elif op == "bye":
            self.ack(msg_id)
            self.quit()

    def _set_intent(self, text: str, ms: Optional[float] = None) -> None:
        self.intent = _short(text) if text else ""
        dur = float(ms if ms is not None else self.cfg["intent_ms"]) / 1000.0
        self.intent_until = time.monotonic() + dur if text else 0.0
        self._layout_tag()

    def _real_mouse(self) -> Tuple[float, float]:
        try:
            seat = Gdk.Display.get_default().get_default_seat()
            _screen, x, y = seat.get_pointer().get_position()
            return (float(x), float(y))
        except Exception:  # noqa: BLE001
            return (0.0, 0.0)

    # ------------------------------------------------------------- hotkeys
    def start_hotkeys(self) -> None:
        threading.Thread(target=self._hotkey_loop, name="hotkeys", daemon=True).start()

    def _hotkey_loop(self) -> None:
        try:
            from Xlib import X, XK, display as xdisplay

            d = xdisplay.Display()
            root = d.screen().root
            mods = X.ControlMask | X.Mod1Mask
            keys = {
                d.keysym_to_keycode(XK.string_to_keysym("Escape")): "stop",
                d.keysym_to_keycode(XK.string_to_keysym("p")): "pause",
            }
            # Also grab with NumLock (Mod2) and CapsLock (Lock) on, which X counts as modifiers.
            for code in keys:
                for extra in (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask):
                    root.grab_key(code, mods | extra, True, X.GrabModeAsync, X.GrabModeAsync)
            d.sync()
            while True:
                ev = d.next_event()
                if ev.type == X.KeyPress and (ev.state & mods) == mods and ev.detail in keys:
                    GLib.idle_add(self._on_hotkey, keys[ev.detail])
        except Exception as exc:  # noqa: BLE001 - hotkeys are a convenience
            sys.stderr.write(f"dobby.overlay: hotkeys unavailable: {exc}\n")

    def _on_hotkey(self, which: str) -> bool:
        if which == "stop":
            self.paused = False
            self.send_event("stop")
            self.send_event("user_idle")
        else:
            self.paused = not self.paused
            self.send_event("pause" if self.paused else "resume")
        self._layout_tag()
        return False

    # ---------------------------------------------------------------- life
    def quit(self) -> bool:
        if self.pending_confirm is not None:
            self._answer_confirm(False)
        Gtk.main_quit()
        return False


def _stdin_watch(overlay: X11Overlay) -> None:
    buf = {"data": b""}

    def on_input(fd, cond) -> bool:
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            chunk = b""
        else:
            chunk = os.read(fd, 65536)
        if not chunk:
            overlay.quit()  # server went away
            return False
        buf["data"] += chunk
        while b"\n" in buf["data"]:
            line, buf["data"] = buf["data"].split(b"\n", 1)
            overlay.handle_line(line.decode("utf-8", "replace"))
        return True

    GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, on_input)


def _demo(overlay: X11Overlay) -> None:
    screen = Gdk.Screen.get_default()
    w, h = screen.get_width(), screen.get_height()
    steps = [
        (0.2, {"op": "cursor.move", "x": w * 0.3, "y": h * 0.3, "verb": "Click"}),
        (0.9, {"op": "cursor.click"}),
        (1.4, {"op": "cursor.state", "state": "thinking"}),
        (2.2, {"op": "cursor.move", "x": w * 0.7, "y": h * 0.4, "verb": "Double-click"}),
        (2.9, {"op": "cursor.click", "count": 2}),
        (3.3, {"op": "intent", "text": "Type “hello”"}),
        (3.3, {"op": "cursor.state", "state": "typing"}),
        (4.4, {"op": "cursor.state", "state": "idle"}),
        (4.6, {"op": "risk", "level": "caution"}),
        (4.8, {"op": "target.box", "x": w * 0.45, "y": h * 0.55, "w": 160, "h": 40}),
        (4.8, {"op": "cursor.move", "x": w * 0.5, "y": h * 0.58, "verb": "Click"}),
        (5.6, {"op": "cursor.click"}),
        (6.0, {"op": "risk", "level": "danger"}),
        (6.0, {"op": "intent", "text": "Press Ctrl+Q (quit the app)", "ms": 2000}),
        (8.0, {"op": "risk", "level": "ok"}),
        (9.0, {"op": "bye"}),
    ]
    for delay, msg in steps:
        GLib.timeout_add(int(delay * 1000), lambda m=msg: (overlay.handle(m), False)[1])


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or [])
    cfg: Dict[str, Any] = {}
    raw = os.environ.get("DOBBY_OVERLAY_CONFIG")
    if raw:
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError:
            cfg = {}
    if not Gtk.init_check(sys.argv)[0]:
        sys.stderr.write("dobby.overlay: cannot open the X display\n")
        return 2
    overlay = X11Overlay(cfg)
    if "--demo" in argv:
        _demo(overlay)
    else:
        _stdin_watch(overlay)
        overlay.start_hotkeys()
    overlay.emit({"ready": True, "version": protocol.PROTOCOL_VERSION, "pid": os.getpid()})
    Gtk.main()
    return 0
