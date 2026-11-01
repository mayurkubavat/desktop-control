"""Server-side handle on the overlay helper.

``NullOverlay`` does nothing and is what Dobby uses when the overlay is off,
on Linux/Windows, in tests and in cassette replay. ``OverlayClient`` spawns
``python -m dobby.overlay`` lazily and talks JSON lines to it. Any failure
(helper missing, crashed, too slow) disables the client for the rest of the
session: the overlay must never block or break an action.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import protocol

log = logging.getLogger(__name__)


class NullOverlay:
    """No-op overlay. Every method returns quickly and reports success."""

    active = False
    pid: Optional[int] = None

    def move(self, x: float, y: float, ms: Optional[int] = None, wait: bool = True) -> bool:
        return True

    def click(self, button: str = "left", count: int = 1) -> bool:
        return True

    def state(self, state: str) -> bool:
        return True

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
    ) -> None:
        self.cmd = cmd or [sys.executable, "-m", "dobby.overlay"]
        self.config = dict(config or {})
        self.ack_timeout = ack_timeout
        self.startup_timeout = startup_timeout
        self.log_path = log_path
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._waiters: Dict[int, threading.Event] = {}
        self._results: Dict[int, bool] = {}
        self._ready = threading.Event()
        self._disabled = False
        self._cursor: Optional[tuple] = None
        atexit.register(self.close)

    # ----------------------------------------------------------------- state
    @property
    def active(self) -> bool:  # type: ignore[override]
        return not self._disabled and self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> Optional[int]:  # type: ignore[override]
        return self._proc.pid if self._proc else None

    def _disable(self, why: str) -> None:
        if not self._disabled:
            log.warning("overlay disabled: %s", why)
        self._disabled = True

    # --------------------------------------------------------------- process
    def _ensure_started(self) -> bool:
        if self._disabled:
            return False
        if self._proc is not None:
            if self._proc.poll() is None:
                return True
            self._disable(f"helper exited with code {self._proc.returncode}")
            return False
        env = dict(os.environ)
        env["DOBBY_OVERLAY_CONFIG"] = json.dumps(self.config)
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
        threading.Thread(target=self._read_loop, name="dobby-overlay-reader", daemon=True).start()
        return True

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
        # stdout closed: helper is gone
        self._ready.set()
        for ev in list(self._waiters.values()):
            ev.set()

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

    # ------------------------------------------------------------------- API
    def move(self, x: float, y: float, ms: Optional[int] = None, wait: bool = True) -> bool:
        timeout = None if ms is None else self.ack_timeout + ms / 1000.0
        self._cursor = (x, y)
        return self._send("cursor.move", wait=wait, timeout=timeout, x=x, y=y, ms=ms)

    def click(self, button: str = "left", count: int = 1) -> bool:
        return self._send("cursor.click", button=button, count=count)

    def state(self, state: str) -> bool:
        return self._send("cursor.state", state=state)

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
        if proc is None or proc.poll() is not None:
            return
        try:
            self._send("bye")
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=1.0)
        except Exception:  # noqa: BLE001 - best effort shutdown
            proc.kill()
