"""Server-side handle on the overlay helper.

``NullOverlay`` does nothing and is what Dobby uses when the overlay is off,
on Linux/Windows, in tests and in cassette replay. ``OverlayClient`` spawns
``python -m dobby.overlay`` lazily and talks JSON lines to it. Any failure
(helper missing, crashed, too slow) disables the client for the rest of the
session: the overlay must never block or break an action.

The helper also talks back: the control bar, Dobby's menu, the hotkeys and
user take-over send events that :meth:`OverlayClient.checkpoint` turns into a
pause, an :class:`OverlayStopped` or an :class:`OverlayInterrupted` before the
next action.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import protocol

log = logging.getLogger(__name__)


class OverlayStopped(RuntimeError):
    """Raised before an action when the user pressed Stop or denied a step."""


class OverlayInterrupted(OverlayStopped):
    """The user took over while Dobby worked: the screen may have changed.

    The pending action is dropped; the agent should take a fresh screenshot
    and decide again. Retrying the same coordinates blindly is unsafe.
    """


class NullOverlay:
    """No-op overlay. Every method returns quickly and reports success."""

    active = False
    pid: Optional[int] = None
    awake = False  # the user woke Dobby from the control bar

    def on_wake(self, cb: Callable[[], None]) -> None:
        """Call ``cb`` (on the reader thread) when the user wakes Dobby."""

    def move(self, x: float, y: float, ms: Optional[int] = None, wait: bool = True,
             verb: Optional[str] = None, probe: bool = False) -> bool:
        return True

    def click(self, button: str = "left", count: int = 1) -> bool:
        return True

    def state(self, state: str) -> bool:
        return True

    def intent(self, text: str, ms: Optional[int] = None) -> bool:
        return True

    def box(self, x: float, y: float, w: float, h: float) -> bool:
        return True

    def clear_box(self) -> bool:
        return True

    def risk(self, level: str) -> bool:
        return True

    def scan(self, rect: Optional[tuple] = None) -> bool:
        return True

    def trail_clear(self) -> bool:
        return True

    def set_visible(self, on: bool) -> bool:
        return True

    def confirm(self, text: str, secs: float = 30.0) -> bool:
        return True  # no overlay, no one to ask: keep the old behaviour

    def checkpoint(self, max_wait: float = 120.0) -> None:
        return None

    def track(self, window_id: Any = None, pid: Optional[int] = None) -> bool:
        return True

    def clear(self) -> bool:
        return True

    def hide(self) -> bool:
        return True

    def show(self) -> bool:
        return True

    def close(self) -> None:
        return None


class OverlayClient(NullOverlay):
    def __init__(
        self,
        cmd: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
        ack_timeout: float = 1.5,
        startup_timeout: float = 8.0,
        log_path: Optional[Path] = None,
        track_dir: Optional[Path] = None,
    ) -> None:
        self.cmd = cmd or [sys.executable, "-m", "dobby.overlay"]
        self.config = dict(config or {})
        self.ack_timeout = ack_timeout
        self.startup_timeout = startup_timeout
        self.log_path = log_path
        self.track_dir = track_dir
        self.track_path: Optional[Path] = None
        self._track = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._start_lock = threading.RLock()  # one helper even with an eager start
        self._next_id = 1
        self._waiters: Dict[int, threading.Event] = {}
        self._results: Dict[int, bool] = {}
        self._ready = threading.Event()
        self._disabled = False
        # Control state driven by helper events.
        self._cond = threading.Condition()
        self._stop_requested = False
        self._paused = False
        self._user_active = False
        self._user_input_seen = False
        self.awake = False
        self._wake_callbacks: List[Callable[[], None]] = []
        atexit.register(self.close)

    # ----------------------------------------------------------------- state
    @property
    def active(self) -> bool:  # type: ignore[override]
        return not self._disabled and self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> Optional[int]:  # type: ignore[override]
        return self._proc.pid if self._proc else None

    def _release_waits(self) -> None:
        with self._cond:
            self._paused = self._user_active = False
            self._cond.notify_all()

    def _disable(self, why: str) -> None:
        if not self._disabled:
            log.warning("overlay disabled: %s", why)
        self._disabled = True
        self._release_waits()

    # --------------------------------------------------------------- process
    def start_async(self) -> None:
        """Start the helper in the background (instead of on the first action)."""
        threading.Thread(target=self._start_quietly, name="dobby-overlay-start", daemon=True).start()

    def _start_quietly(self) -> None:
        try:
            self._ensure_started()
        except Exception as exc:  # noqa: BLE001 - cosmetic
            log.debug("overlay eager start failed: %s", exc)

    # --------------------------------------------------------------- process
    def _ensure_started(self) -> bool:
        with self._start_lock:
            return self._ensure_started_locked()

    def _ensure_started_locked(self) -> bool:
        if self._disabled:
            return False
        if self._proc is not None:
            if self._proc.poll() is None:
                return True
            self._disable(f"helper exited with code {self._proc.returncode}")
            return False
        env = dict(os.environ)
        env["DOBBY_OVERLAY_CONFIG"] = json.dumps(self.config)
        env["DOBBY_SERVER_PID"] = str(os.getpid())
        stderr: Any = subprocess.DEVNULL
        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                stderr = open(self.log_path, "a", buffering=1)
            except OSError:
                stderr = subprocess.DEVNULL
        try:
            self._proc = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            self._disable(f"cannot start helper: {exc}")
            return False
        self._open_track()
        threading.Thread(target=self._read_loop, name="dobby-overlay-reader", daemon=True).start()
        return True

    def _open_track(self) -> None:
        if self.track_dir is None:
            return
        try:
            self.track_dir.mkdir(parents=True, exist_ok=True)
            name = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}.jsonl"
            self.track_path = self.track_dir / name
            self._track = open(self.track_path, "a", buffering=1)
        except OSError as exc:
            log.debug("overlay: no track log: %s", exc)
            self._track = None

    def _log_track(self, line: str) -> None:
        if self._track is None:
            return
        try:
            msg = json.loads(line)
            msg.pop("id", None)
            if msg.get("op") in ("hide", "show", "ping", "confirm.cancel", "bye"):
                return
            self._track.write(json.dumps({"ts": round(time.time(), 3), **msg}, separators=(",", ":")) + "\n")
        except (OSError, ValueError):
            pass

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("ready"):
                if msg.get("version") != protocol.PROTOCOL_VERSION:
                    self._disable(f"helper protocol {msg.get('version')} != {protocol.PROTOCOL_VERSION}")
                self._ready.set()
            elif "ack" in msg:
                ev = self._waiters.pop(msg["ack"], None)
                self._results[msg["ack"]] = bool(msg.get("ok"))
                if ev:
                    ev.set()
            elif "event" in msg:
                self._on_event(str(msg["event"]))
        # stdout closed: helper is gone
        self._ready.set()
        for ev in list(self._waiters.values()):
            ev.set()
        self._release_waits()

    def _on_event(self, name: str) -> None:
        with self._cond:
            if name == "stop":
                self._stop_requested = True
                self._paused = False
            elif name == "pause":
                self._paused = True
            elif name == "resume":
                self._paused = False
            elif name == "user_input":
                self._user_active = True
                self._user_input_seen = True
            elif name == "user_idle":
                self._user_active = False
            elif name == "wake":
                self.awake = True
            elif name == "sleep":
                self.awake = False
            self._cond.notify_all()
        if name == "wake":
            for cb in list(self._wake_callbacks):
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    log.exception("overlay: wake callback failed")

    def on_wake(self, cb: Callable[[], None]) -> None:  # type: ignore[override]
        """Call ``cb`` (on the reader thread) when the user wakes Dobby."""
        self._wake_callbacks.append(cb)

    def _send(self, op: str, wait: bool = False, timeout: Optional[float] = None, **fields: Any) -> bool:
        if not self._ensure_started():
            return False
        with self._lock:
            msg_id = self._next_id if wait else None
            if wait:
                self._next_id += 1
            try:
                line = protocol.encode(op, msg_id, **fields)
            except protocol.ProtocolError as exc:
                log.debug("overlay: dropped bad message: %s", exc)
                return False
            ev = threading.Event()
            if msg_id is not None:
                self._waiters[msg_id] = ev
            try:
                assert self._proc is not None and self._proc.stdin is not None
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._disable(f"write failed: {exc}")
                return False
            self._log_track(line)
        if msg_id is None:
            return True
        if not self._ready.is_set() and not self._ready.wait(self.startup_timeout):
            self._disable("helper did not become ready")
            return False
        if not ev.wait(timeout if timeout is not None else self.ack_timeout):
            self._waiters.pop(msg_id, None)
            log.debug("overlay: ack timeout for %s", op)
            return False
        return self._results.pop(msg_id, False)

    # ------------------------------------------------------------- control
    def checkpoint(self, max_wait: float = 120.0) -> None:
        """Call before each action: raise if stopped, wait while paused.

        * Stop (bar, menu, hotkey) -> :class:`OverlayStopped`.
        * Pause (bar, menu, hotkey) or user take-over (real mouse or
          keyboard input while Dobby works) -> wait here until resumed, or the
          user has been idle for a moment (auto mode), for at most
          ``max_wait`` seconds.
        * If the user touched anything since the last action -> after the
          wait, :class:`OverlayInterrupted`, so the agent looks again instead
          of replaying a click on a screen that may have changed.
        """
        if not self.active:
            return
        deadline = time.monotonic() + max_wait
        shown_wait = False
        with self._cond:
            while True:
                if self._stop_requested:
                    self._stop_requested = False
                    self._user_input_seen = False
                    raise OverlayStopped("Stopped by the user from the Dobby overlay")
                if not (self._paused or self._user_active):
                    break
                if not shown_wait:
                    shown_wait = True
                    self._cond.release()
                    try:
                        self.state("waiting_user")
                    finally:
                        self._cond.acquire()
                    continue
                left = deadline - time.monotonic()
                if left <= 0:
                    raise OverlayStopped("Dobby stayed paused too long; stopping")
                self._cond.wait(min(left, 0.25))
            interrupted = self._user_input_seen
            self._user_input_seen = False
        if shown_wait:
            self.state("idle")
        if interrupted:
            raise OverlayInterrupted(
                "The user used the mouse or keyboard while Dobby was working. "
                "This step was skipped: take a new screenshot and decide again."
            )

    def confirm(self, text: str, secs: float = 30.0) -> bool:
        """Ask the user Allow/Deny on the pill. False on deny or timeout."""
        if not self._ensure_started():
            return True  # helper unusable: behave like NullOverlay
        ok = self._send("confirm", wait=True, timeout=secs + 1.0, text=text, secs=secs)
        if not ok:
            self._send("confirm.cancel")
        return ok

    # ------------------------------------------------------------------- API
    def move(self, x: float, y: float, ms: Optional[int] = None, wait: bool = True,
             verb: Optional[str] = None, probe: bool = False) -> bool:
        # With ms=None the helper picks the glide time (<= 450 ms) and may
        # do an AX hit test first, so allow for that in the ack timeout.
        timeout = self.ack_timeout + (ms if ms is not None else 450) / 1000.0
        return self._send("cursor.move", wait=wait, timeout=timeout, x=x, y=y, ms=ms,
                          verb=verb, probe=True if probe else None)

    def click(self, button: str = "left", count: int = 1) -> bool:
        return self._send("cursor.click", button=button, count=count)

    def state(self, state: str) -> bool:
        return self._send("cursor.state", state=state)

    def intent(self, text: str, ms: Optional[int] = None) -> bool:
        return self._send("intent", text=text, ms=ms)

    def box(self, x: float, y: float, w: float, h: float) -> bool:
        return self._send("target.box", x=x, y=y, w=w, h=h)

    def clear_box(self) -> bool:
        return self._send("target.clear")

    def risk(self, level: str) -> bool:
        return self._send("risk", level=level)

    def scan(self, rect: Optional[tuple] = None) -> bool:
        if rect is None:
            return self._send("scan")
        x, y, w, h = rect
        return self._send("scan", x=x, y=y, w=w, h=h)

    def trail_clear(self) -> bool:
        return self._send("trail.clear")

    def set_visible(self, on: bool) -> bool:
        return self._send("overlay.visible", on=bool(on))

    def track(self, window_id: Any = None, pid: Optional[int] = None) -> bool:
        wid = protocol.window_id_int(window_id)
        if wid is None and pid is None:
            return False
        return self._send("glow.track", window_id=wid, pid=pid)

    def clear(self) -> bool:
        return self._send("glow.clear")

    def hide(self) -> bool:
        if not self.active:
            return True
        return self._send("hide", wait=True)

    def show(self) -> bool:
        if not self.active:
            return True
        return self._send("show")

    def close(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                self._send("bye")
                proc.stdin.close()  # type: ignore[union-attr]
                proc.wait(timeout=1.0)
            except Exception:  # noqa: BLE001 - best effort shutdown
                proc.kill()
        if self._track is not None:
            try:
                self._track.close()
            except OSError:
                pass
            self._track = None
