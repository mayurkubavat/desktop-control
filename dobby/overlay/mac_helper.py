"""macOS overlay helper: agent pointer, window glow, controls.

Runs as its own process (``python -m dobby.overlay``), started by
:class:`dobby.overlay.client.OverlayClient`. Draws into one transparent,
click-through, non-activating panel per screen, above normal windows and on
every Space. Reads JSON-line commands on stdin (see ``protocol.py``) and exits
when stdin closes, so it never outlives the Dobby server.

What it shows:

* the violet pointer with a name tag that says what Dobby is about to do,
  a box around the target element (found by an Accessibility hit test),
  click ripples and a numbered trail of recent clicks;
* a breathing glow around the window being worked on, dimmed when covered;
* a "looking" shimmer while Dobby reads the screen;
* risk colours: violet (ok), amber (caution), red (danger);
* Turbo mode (config, or the menu bar): risky steps are allowed without a
  prompt and user input does not pause Dobby; only Stop / Pause do;
* a small pill at the top of the screen (Pause / Resume / Stop, or
  Allow / Deny for risky steps) and a menu bar icon with recent steps.

It also watches for real user input while Dobby works (take-over) and the
hotkeys Ctrl+Option+Esc (stop) and Ctrl+Option+P (pause / resume), and sends
events back on stdout.

All drawing is Core Animation; animations run in the window server, so Python
speed does not affect smoothness.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationDidChangeScreenParametersNotification,
    NSAppearance,
    NSAppearanceNameDarkAqua,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventMaskLeftMouseDown,
    NSEventMaskLeftMouseDragged,
    NSEventMaskMouseMoved,
    NSEventMaskRightMouseDown,
    NSEventMaskScrollWheel,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSStatusBar,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowSharingNone,
    NSWindowSharingReadOnly,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
)
from Foundation import NSNotificationCenter, NSObject, NSTimer
from PyObjCTools import AppHelper
from Quartz import (
    CABasicAnimation,
    CACurrentMediaTime,
    CAGradientLayer,
    CALayer,
    CAMediaTimingFunction,
    CAShapeLayer,
    CATextLayer,
    CATransaction,
    CGColorCreateGenericRGB,
    CGEventGetIntegerValueField,
    CGPathAddLineToPoint,
    CGPathCloseSubpath,
    CGPathCreateMutable,
    CGPathCreateWithEllipseInRect,
    CGPathCreateWithRoundedRect,
    CGPathMoveToPoint,
    CGRectMake,
    CGWindowListCopyWindowInfo,
    kCAMediaTimingFunctionEaseInEaseOut,
    kCAMediaTimingFunctionLinear,
    kCGEventSourceUnixProcessID,
    kCGNullWindowID,
    kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionIncludingWindow,
    kCGWindowListOptionOnScreenOnly,
)

from . import geometry, protocol

DEFAULT_CONFIG: Dict[str, Any] = {
    "color": "#7C5CFF",  # Dobby violet; deliberately not Claude's orange
    "caution_color": "#F5A524",
    "danger_color": "#F04438",
    "label": "Dobby",
    "speed": 1.0,
    "glow_width": 3.0,
    "glow_radius": 11.0,
    "glow_blur": 18.0,
    "track_hz": 10.0,
    "capture_visible": True,  # False = hidden from every capture (macOS 27+)
    "trail": True,
    "trail_len": 5,
    "intent_ms": 1600,
    "takeover_resume": "auto",  # or "manual"
    "idle_secs": 2.0,
    "active_secs": 8.0,  # pill and take-over watch stay on this long after an action
    "pill": True,
    "menu_bar": True,
    # Turbo: no Allow/Deny prompts and no take-over pause; only Stop/Pause
    # (pill, menu bar, hotkeys) halt Dobby. Risky steps still flash red.
    "turbo": False,
}

BADGES = {"idle": "", "thinking": " •••", "typing": " ⌨", "waiting_user": " ✋"}

# Classic arrow, flipped coordinates (y down), tip at (0, 0); scaled at build.
_ARROW = [(0, 0), (0, 18), (4.5, 14), (8, 21.5), (10.5, 20.5), (7, 13), (13, 13)]
_ARROW_SCALE = 1.25
_ARROW_H = 21.5 * _ARROW_SCALE
_ARROW_W = 13 * _ARROW_SCALE

_KEY_ESC, _KEY_P = 53, 35
_HOTKEY_MODS = NSEventModifierFlagControl | NSEventModifierFlagOption


def _hex_rgb(value: str) -> Tuple[float, float, float]:
    s = str(value).lstrip("#")
    if len(s) != 6:
        s = "7C5CFF"
    try:
        return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0x7C / 255.0, 0x5C / 255.0, 1.0)


def _cg(rgb: Tuple[float, float, float], alpha: float = 1.0):
    return CGColorCreateGenericRGB(rgb[0], rgb[1], rgb[2], alpha)


def _reduce_motion() -> bool:
    try:
        return bool(NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:  # noqa: BLE001
        return False


def _short(text: str, limit: int = 42) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------- AX
class _AXProbe:
    """Accessibility hit test: what element is at a point, and its frame."""

    def __init__(self) -> None:
        self.ok = False
        try:
            import ApplicationServices as AS  # noqa: N812

            self.AS = AS
            self.system = AS.AXUIElementCreateSystemWide()
            AS.AXUIElementSetMessagingTimeout(self.system, 0.25)
            self.ok = True
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"dobby.overlay: AX probe unavailable: {exc}\n")

    def _attr(self, el, name: str):
        try:
            err, value = self.AS.AXUIElementCopyAttributeValue(el, name, None)
            return value if err == 0 else None
        except Exception:  # noqa: BLE001
            return None

    def _point(self, value, kind):
        try:
            ok, pt = self.AS.AXValueGetValue(value, kind, None)
            return pt if ok else None
        except Exception:  # noqa: BLE001
            return None

    def at(self, x: float, y: float) -> Tuple[Optional[str], Optional[geometry.Rect]]:
        if not self.ok:
            return None, None
        try:
            err, el = self.AS.AXUIElementCopyElementAtPosition(self.system, float(x), float(y), None)
        except Exception:  # noqa: BLE001
            return None, None
        if err != 0 or el is None:
            return None, None
        try:
            perr, pid = self.AS.AXUIElementGetPid(el, None)
            if perr == 0 and pid == os.getpid():
                return None, None
        except Exception:  # noqa: BLE001
            pass
        name = None
        for attr in ("AXTitle", "AXDescription", "AXValue", "AXHelp"):
            v = self._attr(el, attr)
            if isinstance(v, str) and v.strip() and len(v.strip()) <= 60:
                name = v.strip()
                break
        if name is None:
            role = self._attr(el, "AXRoleDescription")
            if isinstance(role, str) and role.strip():
                name = role.strip()
        frame = None
        pos, size = self._attr(el, "AXPosition"), self._attr(el, "AXSize")
        if pos is not None and size is not None:
            p = self._point(pos, self.AS.kAXValueCGPointType)
            s = self._point(size, self.AS.kAXValueCGSizeType)
            if p is not None and s is not None:
                frame = (float(p.x), float(p.y), float(s.width), float(s.height))
        return name, frame


# ---------------------------------------------------------------- ObjC glue
class _Target(NSObject):
    """Objective-C target that forwards timers, notifications and clicks."""

    def initWithOwner_(self, owner):
        self = objc.super(_Target, self).init()
        if self is None:
            return None
        self.owner = owner
        return self

    def tick_(self, _timer):
        self.owner.on_tick()

    def screensChanged_(self, _note):
        self.owner.rebuild_panels()

    def pillPrimary_(self, _sender):
        self.owner.on_pill("primary")

    def pillSecondary_(self, _sender):
        self.owner.on_pill("secondary")

    def menuPauseToggle_(self, _sender):
        self.owner.toggle_pause()

    def menuStop_(self, _sender):
        self.owner.request_stop()

    def menuToggleOverlay_(self, _sender):
        self.owner.toggle_overlay()

    def menuToggleTrail_(self, _sender):
        self.owner.toggle_trail()

    def menuClearTrail_(self, _sender):
        self.owner.clear_trail()

    def menuToggleTurbo_(self, _sender):
        self.owner.toggle_turbo()


class _PillButton(NSButton):
    def acceptsFirstMouse_(self, _event):
        return True  # one click works even though the pill never becomes key

    def set_label(self, text: str) -> None:
        # The helper app is never active, so plain titles draw in the dim
        # inactive colour and vanish on the dark pill; force white.
        attrs = {NSForegroundColorAttributeName: NSColor.whiteColor(), NSFontAttributeName: self.font()}
        self.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(text, attrs))


def _configure_overlay_window(win, cfg: Dict[str, Any], click_through: bool) -> None:
    win.setTitle_(protocol.OVERLAY_WINDOW_TITLE)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setHasShadow_(False)
    win.setIgnoresMouseEvents_(click_through)
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorFullScreenAuxiliary
        | NSWindowCollectionBehaviorIgnoresCycle
    )
    # Visible to screen recordings and screen sharing by default; Dobby's
    # own captures hide the overlay via the hide/show handshake instead.
    win.setSharingType_(NSWindowSharingReadOnly if cfg["capture_visible"] else NSWindowSharingNone)
    win.setReleasedWhenClosed_(False)
    win.setHidesOnDeactivate_(False)
    win.setFloatingPanel_(True)
    win.setBecomesKeyOnlyIfNeeded_(True)
    # After setFloatingPanel_, which resets the level to floating (3) and
    # would put the overlay under the menu bar and open menus.
    win.setLevel_(NSScreenSaverWindowLevel)


# ------------------------------------------------------------------ panels
class _Panel:
    """One click-through overlay window covering one screen."""

    def __init__(self, screen, cfg: Dict[str, Any], rgb) -> None:
        self.screen = screen
        fr = screen.frame()
        self.frame = (fr.origin.x, fr.origin.y, fr.size.width, fr.size.height)
        self.scale = float(screen.backingScaleFactor())
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(fr, style, NSBackingStoreBuffered, False)
        win.setFrame_display_(fr, False)
        _configure_overlay_window(win, cfg, click_through=True)

        view = NSView.alloc().initWithFrame_(((0, 0), (fr.size.width, fr.size.height)))
        view.setWantsLayer_(True)
        win.setContentView_(view)
        root = view.layer()

        # Glow: stroke + same-colour shadow, breathing.
        glow = CAShapeLayer.layer()
        glow.setContentsScale_(self.scale)
        glow.setFillColor_(None)
        glow.setLineWidth_(cfg["glow_width"])
        glow.setShadowOffset_((0, 0))
        glow.setShadowRadius_(cfg["glow_blur"])
        glow.setShadowOpacity_(0.55)
        glow.setOpacity_(0.0)
        root.addSublayer_(glow)

        # Target box around the element about to be clicked.
        box = CAShapeLayer.layer()
        box.setContentsScale_(self.scale)
        box.setLineWidth_(2.0)
        box.setOpacity_(0.0)
        root.addSublayer_(box)

        # Containers for transient layers.
        trail = CALayer.layer()
        trail.setContentsScale_(self.scale)
        root.addSublayer_(trail)
        effects = CALayer.layer()
        effects.setContentsScale_(self.scale)
        root.addSublayer_(effects)

        # Pointer: arrow + name tag; anchor at the arrow tip.
        pointer = CALayer.layer()
        pointer.setContentsScale_(self.scale)
        pointer.setBounds_(CGRectMake(0, 0, _ARROW_W, _ARROW_H))
        pointer.setAnchorPoint_((0.0, 1.0))
        pointer.setOpacity_(0.0)
        arrow = CAShapeLayer.layer()
        arrow.setContentsScale_(self.scale)
        path = CGPathCreateMutable()
        for i, (x, y) in enumerate(_ARROW):
            px, py = x * _ARROW_SCALE, _ARROW_H - y * _ARROW_SCALE
            if i == 0:
                CGPathMoveToPoint(path, None, px, py)
            else:
                CGPathAddLineToPoint(path, None, px, py)
        CGPathCloseSubpath(path)
        arrow.setPath_(path)
        arrow.setStrokeColor_(_cg((1, 1, 1)))
        arrow.setLineWidth_(1.5)
        arrow.setLineJoin_("round")
        arrow.setShadowColor_(_cg((0, 0, 0)))
        arrow.setShadowOpacity_(0.35)
        arrow.setShadowRadius_(2.0)
        arrow.setShadowOffset_((0, -1))
        pointer.addSublayer_(arrow)

        tag = CATextLayer.layer()
        tag.setContentsScale_(self.scale)
        tag.setFontSize_(11.0)
        tag.setForegroundColor_(_cg((1, 1, 1)))
        tag.setCornerRadius_(5.0)
        tag.setAlignmentMode_("center")
        pointer.addSublayer_(tag)
        root.addSublayer_(pointer)

        self.window, self.view, self.root = win, view, root
        self.glow, self.box, self.trail, self.effects = glow, box, trail, effects
        self.pointer, self.arrow, self.tag = pointer, arrow, tag
        self.apply_color(rgb)
        win.orderFrontRegardless()

    def apply_color(self, rgb) -> None:
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.2)
        self.arrow.setFillColor_(_cg(rgb))
        self.tag.setBackgroundColor_(_cg(rgb))
        self.glow.setStrokeColor_(_cg(rgb, 0.95))
        self.glow.setShadowColor_(_cg(rgb))
        self.box.setStrokeColor_(_cg(rgb))
        self.box.setFillColor_(_cg(rgb, 0.08))
        CATransaction.commit()

    def set_tag(self, text: str) -> None:
        width = 6.6 * len(text) + 14
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self.tag.setString_(text)
        self.tag.setFrame_(CGRectMake(_ARROW_W - 2, -18, width, 17))
        CATransaction.commit()

    def close(self) -> None:
        self.window.orderOut_(None)
        self.window.close()


class _Pill:
    """Small clickable bar at the top of the main screen."""

    H = 34.0

    def __init__(self, cfg: Dict[str, Any], target) -> None:
        self.cfg = cfg
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (300, self.H)), style, NSBackingStoreBuffered, False
        )
        _configure_overlay_window(win, cfg, click_through=False)
        win.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        view = NSView.alloc().initWithFrame_(((0, 0), (300, self.H)))
        view.setWantsLayer_(True)
        view.layer().setBackgroundColor_(_cg((0.11, 0.09, 0.16), 0.94))
        view.layer().setCornerRadius_(self.H / 2)
        view.layer().setBorderWidth_(1.0)
        win.setContentView_(view)
        self.label = NSTextField.labelWithString_("")
        self.label.setTextColor_(NSColor.whiteColor())
        self.label.setFont_(NSFont.systemFontOfSize_(12.5))
        view.addSubview_(self.label)
        self.primary = _PillButton.buttonWithTitle_target_action_("Pause", target, "pillPrimary:")
        self.secondary = _PillButton.buttonWithTitle_target_action_("Stop", target, "pillSecondary:")
        for b in (self.primary, self.secondary):
            b.setFont_(NSFont.systemFontOfSize_(12.0))
            view.addSubview_(b)
        self.dot = CALayer.layer()
        view.layer().addSublayer_(self.dot)
        self.window, self.view = win, view
        self.mode = "hidden"
        self.ducked = False

    def show(self, mode: str, text: str, primary: str, secondary: str, rgb) -> None:
        self.mode = mode
        self.label.setStringValue_(text)
        self.label.sizeToFit()
        self.primary.set_label(primary)
        self.secondary.set_label(secondary)
        self.primary.sizeToFit()
        self.secondary.sizeToFit()
        lw = self.label.frame().size.width
        pw, sw = self.primary.frame().size.width, self.secondary.frame().size.width
        w = 28 + lw + 14 + pw + 6 + sw + 12
        self.dot.setFrame_(CGRectMake(14, self.H / 2 - 4, 8, 8))
        self.dot.setCornerRadius_(4)
        self.dot.setBackgroundColor_(_cg(rgb))
        self.view.layer().setBorderColor_(_cg(rgb, 0.7))
        self.label.setFrameOrigin_((28, (self.H - self.label.frame().size.height) / 2))
        x = 28 + lw + 14
        self.primary.setFrameOrigin_((x, (self.H - self.primary.frame().size.height) / 2))
        self.secondary.setFrameOrigin_((x + pw + 6, (self.H - self.secondary.frame().size.height) / 2))
        screens = NSScreen.screens() or []
        if screens:
            vf = screens[0].visibleFrame()
            fx = vf.origin.x + (vf.size.width - w) / 2
            fy = vf.origin.y + vf.size.height - self.H - 8
            self.window.setFrame_display_(((fx, fy), (w, self.H)), True)
            self.view.setFrame_(((0, 0), (w, self.H)))
        self._apply_visibility()

    def hide(self) -> None:
        self.mode = "hidden"
        self._apply_visibility()

    def duck(self, ducked: bool) -> None:
        """Get out of the way while Dobby's pointer is near the pill."""
        if ducked != self.ducked:
            self.ducked = ducked
            self._apply_visibility()

    def _apply_visibility(self) -> None:
        if self.mode == "hidden" or (self.ducked and self.mode in ("working", "stopped")):
            self.window.setIgnoresMouseEvents_(True)
            self.window.orderOut_(None)
        else:
            self.window.setIgnoresMouseEvents_(False)
            self.window.orderFrontRegardless()

    def near(self, cocoa_pt: Tuple[float, float], margin: float = 60.0) -> bool:
        f = self.window.frame()
        return (f.origin.x - margin <= cocoa_pt[0] <= f.origin.x + f.size.width + margin
                and f.origin.y - margin <= cocoa_pt[1] <= f.origin.y + f.size.height + margin)

    def close(self) -> None:
        self.window.orderOut_(None)
        self.window.close()


# -------------------------------------------------------------- controller
class OverlayController:
    def __init__(self, cfg: Dict[str, Any], out=sys.stdout, interactive: bool = True) -> None:
        self.cfg = dict(DEFAULT_CONFIG)
        self.cfg.update(cfg)
        self.colors = {
            "ok": _hex_rgb(self.cfg["color"]),
            "caution": _hex_rgb(self.cfg["caution_color"]),
            "danger": _hex_rgb(self.cfg["danger_color"]),
        }
        self.risk_level = "ok"
        self.rgb = self.colors["ok"]
        self.reduce_motion = _reduce_motion()
        self.out = out
        self.out_lock = threading.Lock()
        self.server_pid = int(os.environ.get("DOBBY_SERVER_PID", "0") or 0)
        self.panels: List[_Panel] = []
        self.primary_h = 0.0
        self.cursor: Optional[Tuple[float, float]] = None
        self.cursor_state = "idle"
        self.intent_text = ""
        self.intent_until = 0.0
        self.track_wid: Optional[int] = None
        self.track_pid: Optional[int] = None
        self.glow_rect: Optional[geometry.Rect] = None
        self.glow_dim = False
        self.trail_points: List[Tuple[int, Tuple[float, float]]] = []
        self.step_no = 0
        self.steps: List[str] = []
        self.user_visible = True
        self.capture_hidden = False
        self.trail_on = bool(self.cfg["trail"])
        self.turbo = bool(self.cfg["turbo"])
        # control state
        self.last_action = 0.0
        self.paused = False
        self.takeover = False
        self.takeover_reported = False
        self.last_user_input = 0.0
        self.pending_confirm: Optional[Tuple[Any, float]] = None  # (msg id, deadline)
        self.stopped_until = 0.0
        self.probe = _AXProbe()
        self.target = _Target.alloc().initWithOwner_(self)
        self.pill = _Pill(self.cfg, self.target) if self.cfg["pill"] else None
        self.status_item = None
        self.rebuild_panels()
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.target, "screensChanged:", NSApplicationDidChangeScreenParametersNotification, None
        )
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / float(self.cfg["track_hz"]), self.target, "tick:", None, True
        )
        self.monitors: List[Any] = []
        if interactive:
            self._install_monitors()
            if self.cfg["menu_bar"]:
                self._install_status_item()

    # --------------------------------------------------------------- output
    def _write(self, text: str) -> None:
        with self.out_lock:
            try:
                self.out.write(text)
                self.out.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass

    def emit(self, obj: Dict[str, Any]) -> None:
        self._write(json.dumps(obj, separators=(",", ":")) + "\n")

    def send_event(self, name: str) -> None:
        self._write(protocol.event(name))

    def ack(self, msg_id: Any, ok: bool = True, error: Optional[str] = None) -> None:
        if msg_id is None:
            return
        self._write(protocol.ack(msg_id, ok, error))

    # --------------------------------------------------------------- panels
    def rebuild_panels(self) -> None:
        for p in self.panels:
            p.close()
        screens = list(NSScreen.screens() or [])
        self.primary_h = float(screens[0].frame().size.height) if screens else 0.0
        self.panels = [_Panel(s, self.cfg, self.rgb) for s in screens]
        for p in self.panels:
            p.set_tag(self._tag_text())
        if self.cursor is not None:
            self._place_pointer(self.cursor, 0)
            self._set_pointer_visible(True)
        if self.glow_rect is not None:
            self._place_glow(self.glow_rect, 0)
        self._redraw_trail()
        self._apply_alpha()

    def _apply_alpha(self) -> None:
        alpha = 1.0 if (self.user_visible and not self.capture_hidden) else 0.0
        for p in self.panels:
            p.window.setAlphaValue_(alpha)
        if self.pill is not None:
            self.pill.window.setAlphaValue_(0.0 if self.capture_hidden else 1.0)

    def _duration(self, ms: Optional[float]) -> float:
        if self.reduce_motion or not ms:
            return 0.0
        return max(0.0, float(ms) / 1000.0)

    def _tag_text(self) -> str:
        if self.intent_text and time.monotonic() < self.intent_until:
            return self.intent_text
        return self.cfg["label"] + BADGES.get(self.cursor_state, "")

    def _refresh_tag(self) -> None:
        text = self._tag_text()
        for p in self.panels:
            p.set_tag(text)

    def _set_risk(self, level: str) -> None:
        self.risk_level = level
        self.rgb = self.colors.get(level, self.colors["ok"])
        for p in self.panels:
            p.apply_color(self.rgb)
        self._refresh_pill()

    def _place_pointer(self, pt: Tuple[float, float], ms: Optional[float]) -> None:
        dur = self._duration(ms)
        CATransaction.begin()
        if dur <= 0:
            CATransaction.setDisableActions_(True)
        else:
            CATransaction.setAnimationDuration_(dur)
            CATransaction.setAnimationTimingFunction_(
                CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseInEaseOut)
            )
        for p in self.panels:
            p.pointer.setPosition_(geometry.global_point_to_local(pt, p.frame, self.primary_h))
        CATransaction.commit()
        if self.pill is not None:
            self.pill.duck(self.pill.near((pt[0], self.primary_h - pt[1])))

    def _set_pointer_visible(self, visible: bool) -> None:
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.15)
        for p in self.panels:
            p.pointer.setOpacity_(1.0 if visible else 0.0)
        CATransaction.commit()

    def _place_glow(self, rect: geometry.Rect, ms: float) -> None:
        r = float(self.cfg["glow_radius"])
        inset = float(self.cfg["glow_width"]) / 2.0
        CATransaction.begin()
        if ms <= 0:
            CATransaction.setDisableActions_(True)
        else:
            CATransaction.setAnimationDuration_(ms / 1000.0)
            CATransaction.setAnimationTimingFunction_(
                CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionLinear)
            )
        for p in self.panels:
            x, y, w, h = geometry.global_rect_to_local(rect, p.frame, self.primary_h)
            box = CGRectMake(x - inset, y - inset, w + 2 * inset, h + 2 * inset)
            p.glow.setPath_(CGPathCreateWithRoundedRect(box, r, r, None))
        CATransaction.commit()

    def _set_glow_opacity(self, opacity: float) -> None:
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.2)
        for p in self.panels:
            p.glow.setOpacity_(opacity)
            if opacity > 0 and not self.reduce_motion and p.glow.animationForKey_("breathe") is None:
                anim = CABasicAnimation.animationWithKeyPath_("shadowOpacity")
                anim.setFromValue_(0.35)
                anim.setToValue_(0.75)
                anim.setDuration_(1.25)
                anim.setAutoreverses_(True)
                anim.setRepeatCount_(1e9)
                p.glow.addAnimation_forKey_(anim, "breathe")
        CATransaction.commit()

    def _show_box(self, rect: geometry.Rect) -> None:
        for p in self.panels:
            x, y, w, h = geometry.global_rect_to_local(rect, p.frame, self.primary_h)
            CATransaction.begin()
            CATransaction.setDisableActions_(True)
            p.box.setPath_(CGPathCreateWithRoundedRect(CGRectMake(x - 3, y - 3, w + 6, h + 6), 6, 6, None))
            CATransaction.commit()
            CATransaction.begin()
            CATransaction.setAnimationDuration_(0.12)
            p.box.setOpacity_(1.0)
            CATransaction.commit()

    def _clear_box(self) -> None:
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.25)
        for p in self.panels:
            p.box.setOpacity_(0.0)
        CATransaction.commit()

    def _ripple(self, count: int) -> None:
        if self.cursor is None:
            return
        for p in self.panels:
            cx, cy = geometry.global_point_to_local(self.cursor, p.frame, self.primary_h)
            for i in range(max(1, min(int(count), 3))):
                ring = CAShapeLayer.layer()
                ring.setContentsScale_(p.scale)
                ring.setFrame_(CGRectMake(cx - 14, cy - 14, 28, 28))
                ring.setPath_(CGPathCreateWithEllipseInRect(CGRectMake(0, 0, 28, 28), None))
                ring.setFillColor_(None)
                ring.setStrokeColor_(_cg(self.rgb))
                ring.setLineWidth_(2.0)
                ring.setOpacity_(0.0)
                p.effects.addSublayer_(ring)
                CATransaction.begin()
                CATransaction.setCompletionBlock_(ring.removeFromSuperlayer)
                scale = CABasicAnimation.animationWithKeyPath_("transform.scale")
                scale.setFromValue_(0.3)
                scale.setToValue_(1.0)
                fade = CABasicAnimation.animationWithKeyPath_("opacity")
                fade.setFromValue_(0.9)
                fade.setToValue_(0.0)
                for a in (scale, fade):
                    a.setDuration_(0.3)
                    if i:
                        a.setBeginTime_(CACurrentMediaTime() + 0.12 * i)
                    ring.addAnimation_forKey_(a, a.keyPath())
                CATransaction.commit()

    def _scan(self, rect: Optional[geometry.Rect]) -> None:
        rect = rect or self.glow_rect
        if rect is None or rect[2] < 8 or rect[3] < 8:
            return
        for p in self.panels:
            x, y, w, h = geometry.global_rect_to_local(rect, p.frame, self.primary_h)
            holder = CALayer.layer()
            holder.setContentsScale_(p.scale)
            holder.setFrame_(CGRectMake(x, y, w, h))
            holder.setMasksToBounds_(True)
            holder.setCornerRadius_(float(self.cfg["glow_radius"]))
            p.effects.addSublayer_(holder)
            CATransaction.begin()
            CATransaction.setCompletionBlock_(holder.removeFromSuperlayer)
            if self.reduce_motion:
                holder.setBackgroundColor_(_cg(self.rgb, 0.10))
                fade = CABasicAnimation.animationWithKeyPath_("opacity")
                fade.setFromValue_(1.0)
                fade.setToValue_(0.0)
                fade.setDuration_(0.5)
                holder.setOpacity_(0.0)
                holder.addAnimation_forKey_(fade, "fade")
            else:
                band = max(80.0, w * 0.3)
                grad = CAGradientLayer.layer()
                grad.setContentsScale_(p.scale)
                grad.setFrame_(CGRectMake(-band, 0, band, h))
                tint = tuple(min(1.0, c * 0.4 + 0.6) for c in self.rgb)
                grad.setColors_([_cg(tint, 0.0), _cg(tint, 0.22), _cg(tint, 0.0)])
                grad.setStartPoint_((0.0, 0.5))
                grad.setEndPoint_((1.0, 0.5))
                holder.addSublayer_(grad)
                sweep = CABasicAnimation.animationWithKeyPath_("position.x")
                sweep.setFromValue_(-band / 2)
                sweep.setToValue_(w + band / 2)
                sweep.setDuration_(0.9)
                sweep.setTimingFunction_(CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseInEaseOut))
                grad.setPosition_((w + band / 2, h / 2))
                grad.addAnimation_forKey_(sweep, "sweep")
            CATransaction.commit()

    def _redraw_trail(self) -> None:
        for p in self.panels:
            for sub in list(p.trail.sublayers() or []):
                sub.removeFromSuperlayer()
            if not self.trail_on:
                continue
            n = len(self.trail_points)
            for idx, (num, pt) in enumerate(self.trail_points):
                age = n - 1 - idx
                cx, cy = geometry.global_point_to_local(pt, p.frame, self.primary_h)
                dot = CATextLayer.layer()
                dot.setContentsScale_(p.scale)
                dot.setFrame_(CGRectMake(cx - 9, cy - 9, 18, 18))
                dot.setCornerRadius_(9)
                dot.setBackgroundColor_(_cg(self.colors["ok"], 0.85))
                dot.setForegroundColor_(_cg((1, 1, 1)))
                dot.setFontSize_(10.0)
                dot.setAlignmentMode_("center")
                dot.setString_(str(num))
                dot.setOpacity_(max(0.2, 0.85 - 0.17 * age))
                p.trail.addSublayer_(dot)

    def _add_step(self, text: str) -> None:
        if not text:
            return
        self.step_no += 1
        self.steps.append(f"{self.step_no}. {text}")
        self.steps = self.steps[-10:]
        self._refresh_menu()

    # ------------------------------------------------------------- tracking
    def _window_list(self, option: int, wid: int = kCGNullWindowID) -> List[Dict[str, Any]]:
        return list(CGWindowListCopyWindowInfo(option, wid) or [])

    @staticmethod
    def _bounds(info: Dict[str, Any]) -> geometry.Rect:
        b = info.get("kCGWindowBounds") or {}
        return (float(b.get("X", 0)), float(b.get("Y", 0)), float(b.get("Width", 0)), float(b.get("Height", 0)))

    def on_tick(self) -> None:
        now = time.monotonic()
        if self.intent_text and now >= self.intent_until:
            self.intent_text = ""
            self._refresh_tag()
        if self.pending_confirm is not None and now >= self.pending_confirm[1]:
            self._answer_confirm(False)
        if (self.takeover and self.cfg["takeover_resume"] == "auto"
                and now - self.last_user_input >= float(self.cfg["idle_secs"])):
            self.takeover = False
            self.send_event("user_idle")
            self._refresh_pill()
        if self.pill is not None:
            if self.pill.mode == "working" and now - self.last_action > float(self.cfg["active_secs"]):
                self.pill.hide()
                self._refresh_menu()
            elif self.pill.mode == "stopped" and now >= self.stopped_until:
                self.pill.hide()
        self._track_tick()

    def _track_tick(self) -> None:
        if self.track_wid is None and self.track_pid is None:
            return
        onscreen = self._window_list(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements)
        me = os.getpid()
        wid = self.track_wid
        if wid is None:
            for info in onscreen:
                if info.get("kCGWindowOwnerPID") == self.track_pid and info.get("kCGWindowLayer", 0) == 0:
                    wid = int(info["kCGWindowNumber"])
                    break
        index = next((i for i, info in enumerate(onscreen) if info.get("kCGWindowNumber") == wid), None)
        if wid is None or index is None:
            if self.glow_rect is not None:
                self.glow_rect = None
                self._set_glow_opacity(0.0)
            if (wid is not None and self.track_pid is None
                    and not self._window_list(kCGWindowListOptionIncludingWindow, wid)):
                self.track_wid = None
            return
        rect = self._bounds(onscreen[index])
        above = [
            self._bounds(info) for info in onscreen[:index]
            if info.get("kCGWindowLayer", 0) == 0 and info.get("kCGWindowOwnerPID") != me
            and float(info.get("kCGWindowAlpha", 1)) > 0
        ]
        dim = geometry.occluded(rect, above)
        first = self.glow_rect is None
        if rect != self.glow_rect:
            self._place_glow(rect, 0 if first else 1000.0 / float(self.cfg["track_hz"]))
            self.glow_rect = rect
        if first or dim != self.glow_dim:
            self.glow_dim = dim
            self._set_glow_opacity(0.3 if dim else 1.0)

    # ------------------------------------------------------ controls: pill
    def _mark_active(self) -> None:
        self.last_action = time.monotonic()
        if self.pill is not None and self.pill.mode == "hidden":
            self._refresh_pill()

    def _refresh_pill(self) -> None:
        if self.pill is None or self.pending_confirm is not None:
            self._refresh_menu()
            return
        if self.paused:
            self.pill.show("paused", "Dobby is paused", "Resume", "Stop", self.colors["caution"])
        elif self.takeover:
            text = ("You're in control · Dobby waits until you stop"
                    if self.cfg["takeover_resume"] == "auto" else "You're in control")
            self.pill.show("takeover", text, "Resume now", "Stop", self.colors["caution"])
        elif time.monotonic() - self.last_action <= float(self.cfg["active_secs"]):
            label = "Dobby ⚡ Turbo" if self.turbo else "Dobby is working"
            self.pill.show("working", label + " · ⌃⌥⎋ stops", "Pause", "Stop", self.rgb)
        elif self.pill.mode != "stopped":
            self.pill.hide()
        self._refresh_menu()

    def on_pill(self, which: str) -> None:
        if self.pill is None:
            return
        mode = self.pill.mode
        if mode == "confirm":
            self._answer_confirm(which == "primary")
        elif mode == "stopped":
            self.pill.hide()
        elif which == "secondary":
            self.request_stop()
        elif mode == "working":
            self.set_paused(True)
        elif mode in ("paused", "takeover"):
            self.resume()

    def set_paused(self, paused: bool) -> None:
        if paused == self.paused:
            return
        self.paused = paused
        self.takeover_reported = False
        self.send_event("pause" if paused else "resume")
        self._refresh_pill()

    def toggle_pause(self) -> None:
        if self.paused or self.takeover:
            self.resume()
        else:
            self.set_paused(True)

    def resume(self) -> None:
        if self.takeover:
            self.takeover = False
            self.send_event("user_idle")
        if self.paused:
            self.set_paused(False)
        self._mark_active()
        self._refresh_pill()

    def request_stop(self) -> None:
        if self.pending_confirm is not None:
            self._answer_confirm(False)
        self.paused = False
        self.takeover = False
        self.send_event("stop")
        self.send_event("user_idle")
        self.intent_text = "Stopped"
        self.intent_until = time.monotonic() + 1.5
        self._refresh_tag()
        if self.pill is not None:
            self.pill.show("stopped", "Dobby stopped", "OK", "Hide", self.colors["danger"])
            self.stopped_until = time.monotonic() + 2.0
        self._refresh_menu()

    def _start_confirm(self, msg_id: Any, text: str, secs: float) -> None:
        if self.pending_confirm is not None:
            self._answer_confirm(False)
        if self.turbo:
            self._add_step("Turbo allowed: " + _short(text, 50))
            self.ack(msg_id, True)
            return
        self.pending_confirm = (msg_id, time.monotonic() + max(1.0, secs))
        if self.pill is None:
            self._answer_confirm(False)  # no way to ask: deny
            return
        self.pill.show("confirm", _short(text, 70), "Allow", "Deny", self.colors["danger"])

    def _answer_confirm(self, ok: bool) -> None:
        if self.pending_confirm is None:
            return
        msg_id, _ = self.pending_confirm
        self.pending_confirm = None
        self.ack(msg_id, ok)
        self._mark_active()
        self._refresh_pill()

    # ------------------------------------------- controls: input + hotkeys
    def _install_monitors(self) -> None:
        mask = (NSEventMaskKeyDown | NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown
                | NSEventMaskMouseMoved | NSEventMaskLeftMouseDragged | NSEventMaskScrollWheel)
        try:
            mon = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self._on_global_event)
            if mon is not None:
                self.monitors.append(mon)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"dobby.overlay: no input monitor: {exc}\n")

    def _event_pid(self, event) -> int:
        try:
            cg = event.CGEvent()
            return int(CGEventGetIntegerValueField(cg, kCGEventSourceUnixProcessID)) if cg is not None else 0
        except Exception:  # noqa: BLE001
            return 0

    def _on_global_event(self, event) -> None:
        try:
            pid = self._event_pid(event)
            if pid and pid in (self.server_pid, os.getpid()):
                return  # Dobby's own synthetic input
            etype = int(event.type())
            if etype == 10:  # NSEventTypeKeyDown
                flags = int(event.modifierFlags()) & _HOTKEY_MODS
                if flags == _HOTKEY_MODS and int(event.keyCode()) == _KEY_ESC:
                    self.request_stop()
                    return
                if flags == _HOTKEY_MODS and int(event.keyCode()) == _KEY_P:
                    self.toggle_pause()
                    return
            if etype == 5:  # mouse moved: ignore tiny jitter
                if abs(float(event.deltaX())) + abs(float(event.deltaY())) < 2.0:
                    return
            self._on_user_input()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"dobby.overlay: input monitor: {exc}\n")

    def _on_user_input(self) -> None:
        now = time.monotonic()
        working = now - self.last_action <= float(self.cfg["active_secs"])
        if not (working or self.paused or self.takeover):
            return  # Dobby idle: the user is just using their Mac
        if self.turbo and not self.paused:
            return  # Turbo: only Stop / Pause halt Dobby
        self.last_user_input = now
        if self.paused:
            if not self.takeover_reported:
                self.takeover_reported = True
                self.send_event("user_input")
                self.send_event("user_idle")  # the pause already holds Dobby
            return
        if not self.takeover:
            self.send_event("user_input")
            if self.cfg["takeover_resume"] == "manual":
                self.paused = True
                self.takeover_reported = True
                self.send_event("pause")
                self.send_event("user_idle")
            else:
                self.takeover = True
            self._refresh_pill()

    # ------------------------------------------------- controls: menu bar
    def _install_status_item(self) -> None:
        try:
            self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1.0)
            self._refresh_menu()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"dobby.overlay: no menu bar item: {exc}\n")
            self.status_item = None

    def _menu_item(self, menu, title: str, action: Optional[str] = None, state: Optional[bool] = None):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            item.setTarget_(self.target)
        item.setEnabled_(action is not None)
        if state is not None:
            item.setState_(1 if state else 0)
        menu.addItem_(item)
        return item

    def _refresh_menu(self) -> None:
        if self.status_item is None:
            return
        working = time.monotonic() - self.last_action <= float(self.cfg["active_secs"])
        if self.paused:
            status, title = "Paused", "‖ Dobby"
        elif self.takeover:
            status, title = "You're in control", "✋ Dobby"
        elif working:
            status, title = "Working", "◆ Dobby · working"
        else:
            status, title = "Idle", "◆ Dobby"
        if self.turbo:
            status += " (Turbo)"
            title = title.replace("◆", "⚡")
        try:
            self.status_item.button().setTitle_(title)
            menu = NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)
            self._menu_item(menu, f"Dobby: {status}")
            menu.addItem_(NSMenuItem.separatorItem())
            self._menu_item(menu, "Recent steps")
            for line in (list(reversed(self.steps)) or ["(none yet)"]):
                self._menu_item(menu, "   " + _short(line, 60))
            menu.addItem_(NSMenuItem.separatorItem())
            self._menu_item(menu, "Resume" if (self.paused or self.takeover) else "Pause", "menuPauseToggle:")
            self._menu_item(menu, "Stop", "menuStop:")
            menu.addItem_(NSMenuItem.separatorItem())
            self._menu_item(menu, "Turbo mode (no prompts, ignores take-over)", "menuToggleTurbo:", self.turbo)
            self._menu_item(menu, "Show overlay", "menuToggleOverlay:", self.user_visible)
            self._menu_item(menu, "Show step trail", "menuToggleTrail:", self.trail_on)
            self._menu_item(menu, "Clear step trail", "menuClearTrail:")
            self.status_item.setMenu_(menu)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"dobby.overlay: menu: {exc}\n")

    def toggle_overlay(self) -> None:
        self.user_visible = not self.user_visible
        self._apply_alpha()
        self._refresh_menu()

    def toggle_turbo(self) -> None:
        self.turbo = not self.turbo
        if self.turbo and self.takeover:
            self.takeover = False
            self.send_event("user_idle")
        self._refresh_pill()

    def toggle_trail(self) -> None:
        self.trail_on = not self.trail_on
        self._redraw_trail()
        self._refresh_menu()

    def clear_trail(self) -> None:
        self.trail_points = []
        self._redraw_trail()

    # ------------------------------------------------------------- commands
    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        msg_id = None
        try:
            raw = json.loads(line)
            msg_id = raw.get("id") if isinstance(raw, dict) else None
            msg = protocol.validate(raw)
            self.handle(msg)
        except Exception as exc:  # noqa: BLE001 - never die on one bad message
            sys.stderr.write(f"dobby.overlay: {exc}\n")
            self.ack(msg_id, False, str(exc))

    def _set_intent(self, text: str, ms: Optional[float] = None) -> None:
        self.intent_text = _short(text) if text else ""
        dur = float(ms if ms is not None else self.cfg["intent_ms"]) / 1000.0
        self.intent_until = time.monotonic() + dur if text else 0.0
        self._refresh_tag()

    def handle(self, msg: Dict[str, Any]) -> None:
        op, msg_id = msg["op"], msg.get("id")
        if op == "cursor.move":
            self._mark_active()
            target = (float(msg["x"]), float(msg["y"]))
            verb = msg.get("verb")
            if msg.get("probe"):
                name, frame = self.probe.at(*target)
                if (frame is not None and 3 <= frame[2] <= 1600 and 3 <= frame[3] <= 900
                        and geometry.contains(frame, target)):
                    self._show_box(frame)
                else:
                    self._clear_box()
                if verb:
                    text = f"{verb} ‘{_short(name, 32)}’" if name else verb
                    self._set_intent(text)
                    self._add_step(text)
            elif verb and verb != "Move":
                self._set_intent(verb)
                self._add_step(verb)
            if self.cursor is None:
                start = self._real_mouse()
                self._place_pointer(start, 0)
                self._set_pointer_visible(True)
                self.cursor = start
            ms = msg.get("ms")
            if ms is None:
                ms = geometry.glide_ms(self.cursor, target, speed=float(self.cfg["speed"]))
            dur = self._duration(ms)
            if self.cursor_state == "thinking":
                self.cursor_state = "idle"
                self._refresh_tag()
            self._place_pointer(target, ms)
            self.cursor = target
            if msg_id is not None:
                AppHelper.callLater(dur, self.ack, msg_id)
        elif op == "cursor.click":
            self._mark_active()
            self._ripple(int(msg.get("count", 1)))
            if self.cursor is not None:
                self.trail_points.append((self.step_no or len(self.trail_points) + 1, self.cursor))
                self.trail_points = self.trail_points[-int(self.cfg["trail_len"]):]
                self._redraw_trail()
            AppHelper.callLater(0.5, self._clear_box)
            self.ack(msg_id)
        elif op == "cursor.state":
            self.cursor_state = msg["state"]
            if self.cursor_state in ("typing", "thinking"):
                self._mark_active()
            self._refresh_tag()
            self.ack(msg_id)
        elif op == "cursor.hide":
            self._set_pointer_visible(False)
            self.cursor = None
            self.ack(msg_id)
        elif op == "intent":
            self._mark_active()
            text = msg["text"]
            self._set_intent(text, msg.get("ms"))
            if text:
                self._add_step(_short(text, 60))
            self.ack(msg_id)
        elif op == "target.box":
            self._show_box((float(msg["x"]), float(msg["y"]), float(msg["w"]), float(msg["h"])))
            self.ack(msg_id)
        elif op == "target.clear":
            self._clear_box()
            self.ack(msg_id)
        elif op == "risk":
            self._set_risk(msg["level"])
            self.ack(msg_id)
        elif op == "scan":
            rect = None
            if "x" in msg:
                rect = (float(msg["x"]), float(msg["y"]), float(msg["w"]), float(msg["h"]))
            self._scan(rect)
            self.ack(msg_id)
        elif op == "trail.clear":
            self.clear_trail()
            self.ack(msg_id)
        elif op == "confirm":
            self._mark_active()
            self._start_confirm(msg_id, msg["text"], float(msg.get("secs", 30.0)))
        elif op == "confirm.cancel":
            if self.pending_confirm is not None:
                self._answer_confirm(False)
            self.ack(msg_id)
        elif op == "overlay.visible":
            self.user_visible = bool(msg["on"])
            self._apply_alpha()
            self._refresh_menu()
            self.ack(msg_id)
        elif op == "glow.track":
            self.track_wid = protocol.window_id_int(msg.get("window_id"))
            self.track_pid = msg.get("pid")
            self.glow_rect = None
            self._track_tick()
            self.ack(msg_id)
        elif op == "glow.clear":
            self.track_wid = self.track_pid = None
            self.glow_rect = None
            self._set_glow_opacity(0.0)
            self.ack(msg_id)
        elif op == "hide":
            self.capture_hidden = True
            self._apply_alpha()
            CATransaction.flush()
            # Give the window server a couple of frames to composite.
            AppHelper.callLater(0.05, self.ack, msg_id)
        elif op == "show":
            self.capture_hidden = False
            self._apply_alpha()
            self.ack(msg_id)
        elif op == "ping":
            self.ack(msg_id)
        elif op == "bye":
            self.ack(msg_id)
            self.quit()

    def _real_mouse(self) -> Tuple[float, float]:
        loc = NSEvent.mouseLocation()  # Cocoa global, bottom-left origin
        return (float(loc.x), self.primary_h - float(loc.y))

    def quit(self) -> None:
        try:
            self.timer.invalidate()
        except Exception:  # noqa: BLE001
            pass
        for mon in self.monitors:
            try:
                NSEvent.removeMonitor_(mon)
            except Exception:  # noqa: BLE001
                pass
        if self.pending_confirm is not None:
            self._answer_confirm(False)
        for p in self.panels:
            p.close()
        if self.pill is not None:
            self.pill.close()
        if self.status_item is not None:
            try:
                NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
            except Exception:  # noqa: BLE001
                pass
        AppHelper.stopEventLoop()


# ------------------------------------------------------------ entry points
def _stdin_loop(controller: OverlayController) -> None:
    for line in sys.stdin:
        AppHelper.callAfter(controller.handle_line, line)
    AppHelper.callAfter(controller.quit)


def _schedule(controller: OverlayController, steps: List[Tuple[float, Dict[str, Any]]], tail: float) -> None:
    for delay, msg in steps:
        AppHelper.callLater(delay, controller.handle, msg)
    end = (steps[-1][0] if steps else 0.0) + tail
    AppHelper.callLater(end, controller.quit)


def _demo(controller: OverlayController) -> None:
    screen = NSScreen.mainScreen().frame()
    w, h = float(screen.size.width), float(screen.size.height)
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = int(front.processIdentifier()) if front else None
    steps: List[Tuple[float, Dict[str, Any]]] = [
        (0.2, {"op": "cursor.move", "x": w * 0.3, "y": h * 0.3, "verb": "Click", "probe": True}),
        (0.9, {"op": "cursor.click"}),
        (1.4, {"op": "scan"}),
        (1.4, {"op": "cursor.state", "state": "thinking"}),
        (2.4, {"op": "cursor.move", "x": w * 0.7, "y": h * 0.4, "verb": "Double-click", "probe": True}),
        (3.1, {"op": "cursor.click", "count": 2}),
        (3.5, {"op": "intent", "text": "Type “hello”"}),
        (3.5, {"op": "cursor.state", "state": "typing"}),
        (4.6, {"op": "cursor.state", "state": "idle"}),
        (4.8, {"op": "risk", "level": "caution"}),
        (4.8, {"op": "intent", "text": "Check before saving"}),
        (5.0, {"op": "cursor.move", "x": w * 0.5, "y": h * 0.6, "verb": "Click", "probe": True}),
        (5.7, {"op": "cursor.click"}),
        (6.2, {"op": "risk", "level": "danger"}),
        (6.2, {"op": "intent", "text": "Press ⌘Q (quit the app)", "ms": 2500}),
        (8.4, {"op": "risk", "level": "ok"}),
        (8.6, {"op": "cursor.move", "x": w * 0.45, "y": h * 0.35, "verb": "Click", "probe": True}),
        (9.3, {"op": "cursor.click"}),
    ]
    if pid is not None:
        steps.insert(0, (0.1, {"op": "glow.track", "pid": pid}))
    _schedule(controller, steps, tail=3.0)


def load_track(path: str) -> List[Dict[str, Any]]:
    events = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


_REPLAY_SKIP = ("confirm", "confirm.cancel", "hide", "show", "bye", "ping")


def _replay(controller: OverlayController, path: str, speed: float) -> None:
    steps = []
    t0 = None
    for e in load_track(path):
        if "ts" not in e or e.get("op") in _REPLAY_SKIP:
            continue
        msg = {k: v for k, v in e.items() if k != "ts"}
        try:
            protocol.validate(msg)
        except protocol.ProtocolError:
            continue
        t0 = float(e["ts"]) if t0 is None else t0
        steps.append(((float(e["ts"]) - t0) / max(speed, 0.05), msg))
    if not steps:
        sys.stderr.write(f"dobby.overlay: nothing to replay in {path}\n")
        AppHelper.callLater(0.1, controller.quit)
        return
    _schedule(controller, steps, tail=2.0)


def _arg(argv: List[str], name: str) -> Optional[str]:
    if name in argv and argv.index(name) + 1 < len(argv):
        return argv[argv.index(name) + 1]
    return None


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or [])
    cfg: Dict[str, Any] = {}
    raw = os.environ.get("DOBBY_OVERLAY_CONFIG")
    if raw:
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError:
            cfg = {}
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    demo = "--demo" in argv
    replay = _arg(argv, "--replay")
    try:
        speed = float(_arg(argv, "--speed") or 1.0)
    except ValueError:
        speed = 1.0
    controller = OverlayController(cfg, interactive=not (demo or replay))
    if demo:
        _demo(controller)
    elif replay:
        _replay(controller, replay, speed)
    else:
        threading.Thread(target=_stdin_loop, args=(controller,), name="stdin", daemon=True).start()
    controller.emit({"ready": True, "version": protocol.PROTOCOL_VERSION, "pid": os.getpid()})
    AppHelper.runEventLoop(installInterrupt=True)
    return 0
