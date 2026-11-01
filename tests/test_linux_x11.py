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

    def _spawn(kind: str = "--info", extra=(), capture: bool = False):
        _need("zenity")
        title = f"dobby-{uuid.uuid4().hex[:8]}"
        p = subprocess.Popen(
            ["zenity", kind, f"--title={title}", "--text=Dobby test", *extra],
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True,
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


# ---------------------------------------------------------------- AT-SPI

@pytest.fixture(scope="module")
def inspector(hal):
    from dobby.perception.atspi import ATSPIInspector

    insp = ATSPIInspector(hal=hal)
    if not insp.is_available:
        pytest.skip(f"AT-SPI unavailable: {insp.error}")
    return insp


def test_atspi_places_gtk4_widgets_on_screen(hal, inspector, spawn):
    """GTK 4 reports SCREEN extents as 0,0; boxes must still land inside the window."""
    win, _ = spawn("--entry")
    hal.focus_window(win.window_id)
    els = _wait_for(lambda: [e for e in inspector.inspect_desktop() if e.name in ("OK", "Cancel")])
    assert els, "no buttons found"
    slack = 8  # GTK draws button boxes a few pixels into the window edge
    for e in els:
        b = e.bbox
        assert win.bbox.x <= b.x and b.x + b.width <= win.bbox.x + win.bbox.width + slack
        assert win.bbox.y <= b.y and b.y + b.height <= win.bbox.y + win.bbox.height + slack


def test_atspi_defaults_to_active_app(hal, inspector, spawn):
    a, _ = spawn("--entry")
    b, _ = spawn("--info")
    hal.focus_window(b.window_id)
    time.sleep(0.3)
    roles = {e.role for e in inspector.inspect_desktop()}
    assert "text" not in roles  # the --entry dialog belongs to another (inactive) process


def test_atspi_hit_test_finds_button(hal, inspector, spawn):
    win, _ = spawn("--entry")
    hal.focus_window(win.window_id)
    ok = _wait_for(lambda: next((e for e in inspector.inspect_desktop() if e.name == "OK"), None))
    assert ok is not None
    hit = inspector.hit_test(ok.bbox.x + ok.bbox.width // 2, ok.bbox.y + ok.bbox.height // 2)
    assert hit is not None and hit["name"] == "OK"


def test_atspi_hit_test_reports_covering_window(hal, inspector, spawn):
    """The topmost window at a point answers, even when it is not the app being inspected."""
    below, _ = spawn("--entry")
    above, _ = spawn("--info")
    hal.focus_window(above.window_id)
    time.sleep(0.3)
    ab = above.bbox
    # A point inside the front window: the hit must come from inside its box.
    hit = inspector.hit_test(ab.x + ab.width // 2, ab.y + ab.height // 2)
    assert hit is not None
    hb = hit["bbox"]
    assert ab.x <= hb["x"] and hb["x"] + hb["width"] <= ab.x + ab.width + 8


def test_atspi_without_bus_does_not_abort():
    """libatspi aborts the process when the a11y bus is missing; the probe must prevent that."""
    code = (
        "from dobby.perception.atspi import ATSPIInspector\n"
        "i = ATSPIInspector(hal=object())\n"
        "print('available', i.is_available)\n"
        "print(len(i.inspect_desktop()), i.hit_test(10, 10))\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS")}
    env["XDG_RUNTIME_DIR"] = "/nonexistent"
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent/bus"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "available False" in out.stdout
    assert "0 None" in out.stdout


# ---------------------------------------------------------------- input

def _center(b):
    return b.x + b.width // 2, b.y + b.height // 2


def _entry_dialog(hal, inspector, spawn):
    win, proc = spawn("--entry", capture=True)
    hal.focus_window(win.window_id)
    entry = _wait_for(lambda: next((e for e in inspector.inspect_desktop() if e.role == "text"), None))
    assert entry is not None
    return win, proc, entry


def test_type_click_and_submit(hal, inspector, spawn):
    _win, proc, entry = _entry_dialog(hal, inspector, spawn)
    hal.mouse_click(*_center(entry.bbox))
    hal.keyboard_type("hello dobby")
    ok = next(e for e in inspector.inspect_desktop() if e.name == "OK")
    hal.mouse_click(*_center(ok.bbox))
    out, _ = proc.communicate(timeout=5)
    assert out.strip() == "hello dobby"


def test_hotkey_select_all_replaces_and_enter_submits(hal, inspector, spawn):
    _win, proc, entry = _entry_dialog(hal, inspector, spawn)
    hal.mouse_click(*_center(entry.bbox))
    hal.keyboard_type("first")
    hal.keyboard_hotkey(["ctrl", "a"])
    hal.keyboard_type("second")
    hal.keyboard_press_key("enter")
    out, _ = proc.communicate(timeout=5)
    assert out.strip() == "second"


def test_unicode_typing(hal, inspector, spawn):
    _win, proc, entry = _entry_dialog(hal, inspector, spawn)
    hal.mouse_click(*_center(entry.bbox))
    hal.keyboard_type("café ü")
    hal.keyboard_press_key("Return")
    out, _ = proc.communicate(timeout=5)
    assert out.strip() == "café ü"


def test_escape_cancels(hal, inspector, spawn):
    _win, proc, entry = _entry_dialog(hal, inspector, spawn)
    hal.mouse_click(*_center(entry.bbox))
    hal.keyboard_press_key("esc")
    proc.communicate(timeout=5)
    assert proc.returncode == 1  # zenity: cancelled


def test_cursor_position_follows_move(hal):
    hal.mouse_move(321, 234)
    assert hal.get_cursor_position() == (321, 234)


def test_capture_matches_screen_size(hal):
    w, h = hal.get_screen_size()
    img = hal.capture_screen()
    assert img.size == (w, h)
    crop = hal.capture_screen(region=(10, 20, 100, 50))
    assert crop.size == (100, 50)


def test_topology_and_ui_scale(hal):
    topo = hal.display_topology()
    assert topo.displays and topo.displays[0].scale == 1.0
    assert hal.ui_scale > 0


def test_factory_without_display_fails_closed():
    code = (
        "from dobby.hal.factory import get_desktop_hal\n"
        "from dobby.hal.errors import CapabilityUnavailable\n"
        "h = get_desktop_hal()\n"
        "try:\n"
        "    h.capture_screen()\n"
        "except CapabilityUnavailable as e:\n"
        "    print('closed', 'DISPLAY' in str(e))\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DESKTOP_HAL")}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "closed True" in out.stdout


def test_screen_state_loop_end_to_end(hal, spawn):
    """observe -> type -> click, through the same screen-state code the MCP tools use."""
    from dobby.agent_loop.controller import FeedbackLoopController
    from dobby.screen_state import StateTracker
    from dobby.screen_state.observe import act_on_element, observe

    win, proc = spawn("--entry", capture=True)
    hal.focus_window(win.window_id)
    ctl = FeedbackLoopController(hal)
    if not ctl.atspi_inspector.is_available:
        pytest.skip("AT-SPI unavailable")
    tracker = StateTracker()
    state = _wait_for(lambda: (lambda s: s if any(e.label == "OK" for e in s.elements) else None)(
        observe(ctl, tracker, use_ocr=False)))
    assert state is not None
    assert state.app == "zenity" or (state.window_title or "").startswith("dobby-")
    entry = next(e for e in state.elements if e.source == "ax" and e.role == "text")
    assert entry.focused, "the entry starts focused in a zenity --entry dialog"
    assert "type" in state.as_dict()["operations"]

    r = act_on_element(ctl, tracker, entry.eid, state.generation, action="type", text="Dobby")
    assert r["ok"], r
    state2 = observe(ctl, tracker, use_ocr=False)
    ok = next(e for e in state2.elements if e.label == "OK")
    r = act_on_element(ctl, tracker, ok.eid, state2.generation, action="click")
    assert r["ok"], r
    out, _ = proc.communicate(timeout=5)
    assert out.strip() == "Dobby"
