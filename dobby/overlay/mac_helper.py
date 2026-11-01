"""macOS overlay helper: agent pointer + glowing border around a window.

Runs as its own process (``python -m dobby.overlay``), started by
:class:`dobby.overlay.client.OverlayClient`. Draws into one transparent,
click-through, non-activating panel per screen, above normal windows and on
every Space. Reads JSON-line commands on stdin (see ``protocol.py``) and exits
when stdin closes, so it never outlives the Dobby server.

All drawing is Core Animation; animations run in the window server, so Python
speed does not affect smoothness.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationDidChangeScreenParametersNotification,
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSPanel,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowSharingNone,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
)
from Foundation import NSNotificationCenter, NSObject, NSTimer
from PyObjCTools import AppHelper
from Quartz import (
    CABasicAnimation,
    CALayer,
    CAMediaTimingFunction,
    CAShapeLayer,
    CATextLayer,
    CACurrentMediaTime,
    CATransaction,
    CGColorCreateGenericRGB,
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
    kCGNullWindowID,
    kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionIncludingWindow,
    kCGWindowListOptionOnScreenOnly,
)

from . import geometry, protocol

DEFAULT_CONFIG: Dict[str, Any] = {
    "color": "#7C5CFF",  # Dobby violet; deliberately not Claude's orange
    "label": "Dobby",
    "speed": 1.0,
    "glow_width": 3.0,
    "glow_radius": 11.0,
    "glow_blur": 18.0,
    "track_hz": 10.0,
}

BADGES = {"idle": "", "thinking": " •••", "typing": " ⌨", "waiting_user": " ✋"}

# Classic arrow, flipped coordinates (y down), tip at (0, 0); scaled at build.
_ARROW = [(0, 0), (0, 18), (4.5, 14), (8, 21.5), (10.5, 20.5), (7, 13), (13, 13)]
_ARROW_SCALE = 1.25
_ARROW_H = 21.5 * _ARROW_SCALE
_ARROW_W = 13 * _ARROW_SCALE


def _hex_rgb(value: str) -> Tuple[float, float, float]:
    s = value.lstrip("#")
    if len(s) != 6:
        s = "7C5CFF"
    return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _cg(rgb: Tuple[float, float, float], alpha: float = 1.0):
    return CGColorCreateGenericRGB(rgb[0], rgb[1], rgb[2], alpha)


def _reduce_motion() -> bool:
    try:
        return bool(NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:  # noqa: BLE001
        return False


class _Target(NSObject):
    """Objective-C target that forwards timer and notification callbacks."""

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
        win.setTitle_(protocol.OVERLAY_WINDOW_TITLE)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(False)
        win.setIgnoresMouseEvents_(True)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        win.setSharingType_(NSWindowSharingNone)  # best effort only
        win.setReleasedWhenClosed_(False)
        win.setHidesOnDeactivate_(False)
        win.setFloatingPanel_(True)
        win.setBecomesKeyOnlyIfNeeded_(True)
        # After setFloatingPanel_, which resets the level to floating (3) and
        # would put the overlay under the menu bar and open menus.
        win.setLevel_(NSScreenSaverWindowLevel)

        view = NSView.alloc().initWithFrame_(((0, 0), (fr.size.width, fr.size.height)))
        view.setWantsLayer_(True)
        win.setContentView_(view)
        root = view.layer()

        # Glow: stroke + same-colour shadow, breathing.
        glow = CAShapeLayer.layer()
        glow.setContentsScale_(self.scale)
        glow.setFillColor_(None)
        glow.setStrokeColor_(_cg(rgb, 0.95))
        glow.setLineWidth_(cfg["glow_width"])
        glow.setShadowColor_(_cg(rgb))
        glow.setShadowOffset_((0, 0))
        glow.setShadowRadius_(cfg["glow_blur"])
        glow.setShadowOpacity_(0.55)
        glow.setOpacity_(0.0)
        root.addSublayer_(glow)

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
        arrow.setFillColor_(_cg(rgb))
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
        tag.setBackgroundColor_(_cg(rgb))
        tag.setCornerRadius_(5.0)
        tag.setAlignmentMode_("center")
        pointer.addSublayer_(tag)
        root.addSublayer_(pointer)

        self.window, self.view, self.root = win, view, root
        self.glow, self.pointer, self.arrow, self.tag = glow, pointer, arrow, tag
        win.orderFrontRegardless()

    def set_tag(self, text: str) -> None:
        width = 7.0 * len(text) + 14
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self.tag.setString_(text)
        self.tag.setFrame_(CGRectMake(_ARROW_W - 2, -18, width, 17))
        CATransaction.commit()

    def close(self) -> None:
        self.window.orderOut_(None)
        self.window.close()


class OverlayController:
    def __init__(self, cfg: Dict[str, Any], out=sys.stdout) -> None:
        self.cfg = dict(DEFAULT_CONFIG)
        self.cfg.update(cfg)
        self.rgb = _hex_rgb(str(self.cfg["color"]))
        self.reduce_motion = _reduce_motion()
        self.out = out
        self.out_lock = threading.Lock()
        self.panels: List[_Panel] = []
        self.primary_h = 0.0
        self.cursor: Optional[Tuple[float, float]] = None
        self.cursor_state = "idle"
        self.track_wid: Optional[int] = None
        self.track_pid: Optional[int] = None
        self.glow_rect: Optional[geometry.Rect] = None
        self.glow_dim = False
        self.target = _Target.alloc().initWithOwner_(self)
        self.rebuild_panels()
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.target, "screensChanged:", NSApplicationDidChangeScreenParametersNotification, None
        )
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / float(self.cfg["track_hz"]), self.target, "tick:", None, True
        )

    # --------------------------------------------------------------- output
    def emit(self, obj: Dict[str, Any]) -> None:
        with self.out_lock:
            try:
                self.out.write(json.dumps(obj, separators=(",", ":")) + "\n")
                self.out.flush()
            except (BrokenPipeError, OSError):
                pass

    def ack(self, msg_id: Any, ok: bool = True, error: Optional[str] = None) -> None:
        if msg_id is None:
            return
        with self.out_lock:
            try:
                self.out.write(protocol.ack(msg_id, ok, error))
                self.out.flush()
            except (BrokenPipeError, OSError):
                pass

    # --------------------------------------------------------------- panels
    def rebuild_panels(self) -> None:
        for p in self.panels:
            p.close()
        screens = list(NSScreen.screens() or [])
        self.primary_h = float(screens[0].frame().size.height) if screens else 0.0
        self.panels = [_Panel(s, self.cfg, self.rgb) for s in screens]
        label = self.cfg["label"] + BADGES.get(self.cursor_state, "")
        for p in self.panels:
            p.set_tag(label)
        if self.cursor is not None:
            self._place_pointer(self.cursor, 0)
            self._set_pointer_visible(True)
        if self.glow_rect is not None:
            self._place_glow(self.glow_rect, 0)

    def _duration(self, ms: Optional[float]) -> float:
        if self.reduce_motion or not ms:
            return 0.0
        return max(0.0, float(ms) / 1000.0)

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
                p.root.addSublayer_(ring)
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

    # ------------------------------------------------------------- tracking
    def _window_list(self, option: int, wid: int = kCGNullWindowID) -> List[Dict[str, Any]]:
        return list(CGWindowListCopyWindowInfo(option, wid) or [])

    @staticmethod
    def _bounds(info: Dict[str, Any]) -> geometry.Rect:
        b = info.get("kCGWindowBounds") or {}
        return (float(b.get("X", 0)), float(b.get("Y", 0)), float(b.get("Width", 0)), float(b.get("Height", 0)))

    def on_tick(self) -> None:
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
            # Gone, minimised or on another Space.
            if self.glow_rect is not None:
                self.glow_rect = None
                self._set_glow_opacity(0.0)
            if wid is not None and not self._window_list(kCGWindowListOptionIncludingWindow, wid):
                self.track_wid = None if self.track_pid is None else self.track_wid
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

    def handle(self, msg: Dict[str, Any]) -> None:
        op, msg_id = msg["op"], msg.get("id")
        if op == "cursor.move":
            target = (float(msg["x"]), float(msg["y"]))
            if self.cursor is None:
                start = self._real_mouse()
                self._place_pointer(start, 0)
                self._set_pointer_visible(True)
                self.cursor = start
            ms = msg.get("ms")
            if ms is None:
                ms = geometry.glide_ms(self.cursor, target, speed=float(self.cfg["speed"]))
            dur = self._duration(ms)
            self._place_pointer(target, ms)
            self.cursor = target
            if msg_id is not None:
                AppHelper.callLater(dur, self.ack, msg_id)
        elif op == "cursor.click":
            self._ripple(int(msg.get("count", 1)))
            self.ack(msg_id)
        elif op == "cursor.state":
            self.cursor_state = msg["state"]
            label = self.cfg["label"] + BADGES.get(self.cursor_state, "")
            for p in self.panels:
                p.set_tag(label)
            self.ack(msg_id)
        elif op == "cursor.hide":
            self._set_pointer_visible(False)
            self.cursor = None
            self.ack(msg_id)
        elif op == "glow.track":
            self.track_wid = protocol.window_id_int(msg.get("window_id"))
            self.track_pid = msg.get("pid")
            self.glow_rect = None
            self.on_tick()
            self.ack(msg_id)
        elif op == "glow.clear":
            self.track_wid = self.track_pid = None
            self.glow_rect = None
            self._set_glow_opacity(0.0)
            self.ack(msg_id)
        elif op == "hide":
            for p in self.panels:
                p.window.setAlphaValue_(0.0)
            CATransaction.flush()
            # Give the window server a couple of frames to composite.
            AppHelper.callLater(0.05, self.ack, msg_id)
        elif op == "show":
            for p in self.panels:
                p.window.setAlphaValue_(1.0)
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
        for p in self.panels:
            p.close()
        AppHelper.stopEventLoop()


def _stdin_loop(controller: OverlayController) -> None:
    for line in sys.stdin:
        AppHelper.callAfter(controller.handle_line, line)
    AppHelper.callAfter(controller.quit)


def _demo(controller: OverlayController) -> None:
    screen = NSScreen.mainScreen().frame()
    w, h = float(screen.size.width), float(screen.size.height)
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = int(front.processIdentifier()) if front else None
    steps = [
        (0.2, {"op": "cursor.move", "x": w * 0.3, "y": h * 0.3}),
        (0.9, {"op": "cursor.click"}),
        (1.3, {"op": "cursor.move", "x": w * 0.7, "y": h * 0.4}),
        (2.0, {"op": "cursor.click", "count": 2}),
        (2.4, {"op": "cursor.state", "state": "typing"}),
        (3.6, {"op": "cursor.state", "state": "thinking"}),
        (4.2, {"op": "cursor.move", "x": w * 0.5, "y": h * 0.6}),
        (4.8, {"op": "cursor.state", "state": "idle"}),
    ]
    if pid is not None:
        steps.insert(0, (0.1, {"op": "glow.track", "pid": pid}))
    for delay, msg in steps:
        AppHelper.callLater(delay, controller.handle, msg)
    AppHelper.callLater(8.0, controller.quit)


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
    controller = OverlayController(cfg)
    if "--demo" in argv:
        _demo(controller)
    else:
        threading.Thread(target=_stdin_loop, args=(controller,), name="stdin", daemon=True).start()
    controller.emit({"ready": True, "version": protocol.PROTOCOL_VERSION, "pid": os.getpid()})
    AppHelper.runEventLoop(installInterrupt=True)
    return 0
