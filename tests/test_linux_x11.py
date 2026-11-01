"""Live Linux X11 backend tests.

They run only on Linux with an X11 DISPLAY and the test apps installed
(zenity, gedit); everywhere else they skip. The headless rig used for these
is Xvfb + openbox + a session D-Bus + at-spi-bus-launcher.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"),
    reason="needs Linux with an X11 DISPLAY",
)


def _need(app: str) -> None:
    if shutil.which(app) is None:
        pytest.skip(f"{app} not installed")


@pytest.fixture(scope="module")
def hal():
    from dobby.hal.linux import LinuxHAL

    h = LinuxHAL()
    if h.display_server == "none":
        pytest.skip("cannot open the X display")
    return h


def _wait_for(pred, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = pred()
        if got:
            return got
        time.sleep(0.1)
    return None


@pytest.fixture
def spawn(hal):
    """Starts a zenity dialog with a unique title; returns its WindowInfo."""
    procs = []

    def _spawn(kind: str = "--info", extra=()):
        _need("zenity")
        title = f"dobby-{uuid.uuid4().hex[:8]}"
        p = subprocess.Popen(
            ["zenity", kind, f"--title={title}", "--text=Dobby test", *extra],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(p)
        win = _wait_for(lambda: next((w for w in hal.list_windows() if w.title == title), None))
        assert win is not None, f"window {title} never appeared"
        return win, p

    yield _spawn
    for p in procs:
        p.kill()
        p.wait(timeout=5)


# ---------------------------------------------------------------- windows

def test_display_server_reported(hal):
    assert hal.display_server in ("X11", "XWayland")


def test_list_windows_front_to_back_and_focus(hal, spawn):
    a, _ = spawn()
    b, _ = spawn()
    assert hal.focus_window(a.window_id)
    order = [w.window_id for w in hal.list_windows()]
    assert order.index(a.window_id) < order.index(b.window_id)
    assert hal.get_active_window().window_id == a.window_id

    assert hal.focus_window(b.window_id)
    order = [w.window_id for w in hal.list_windows()]
    assert order.index(b.window_id) < order.index(a.window_id)
    active = hal.get_active_window()
    assert active.window_id == b.window_id and active.is_active


def test_window_pid_and_app_name(hal, spawn):
    win, proc = spawn()
    assert hal.window_pid(win.window_id) == proc.pid
    assert (win.app_name or "").lower() == "zenity"
    assert win.bbox.width >= 20 and win.bbox.height >= 20


def test_window_disappears_after_close(hal, spawn):
    win, proc = spawn()
    proc.kill()
    proc.wait(timeout=5)
    gone = _wait_for(lambda: all(w.window_id != win.window_id for w in hal.list_windows()))
    assert gone
    assert hal.window_pid(win.window_id) is None


def test_focus_unknown_window_fails(hal):
    assert hal.focus_window("0x7ffffff0") is False
