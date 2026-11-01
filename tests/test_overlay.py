"""Tests for dobby.overlay that run anywhere (no AppKit needed)."""

import json
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from dobby.overlay import (
    NullOverlay,
    OverlayClient,
    OverlayHAL,
    overlay_enabled,
    unwrap,
    wrap_hal,
)
from dobby.overlay import geometry as g
from dobby.overlay import protocol as p
from dobby.overlay import overlay_config


# --------------------------------------------------------------- protocol
def test_encode_decode_roundtrip():
    line = p.encode("cursor.move", 7, x=10, y=20.5, ms=300)
    assert line.endswith("\n")
    assert p.decode(line) == {"op": "cursor.move", "x": 10, "y": 20.5, "ms": 300, "id": 7}


def test_encode_drops_none_fields():
    assert json.loads(p.encode("cursor.move", None, x=1, y=2, ms=None)) == {"op": "cursor.move", "x": 1, "y": 2}


@pytest.mark.parametrize("msg", [
    {"op": "nope"},
    {"op": "cursor.move", "x": 1},
    {"op": "cursor.move", "x": "1", "y": 2},
    {"op": "cursor.state", "state": "dancing"},
    {"op": "glow.track"},
    {"op": "hide", "extra": 1},
    [],
])
def test_validate_rejects(msg):
    with pytest.raises(p.ProtocolError):
        p.validate(msg)


def test_decode_bad_json():
    with pytest.raises(p.ProtocolError):
        p.decode("{not json")


@pytest.mark.parametrize("raw,expected", [(42, 42), ("42", 42), ("0x2a", 42), ("abc", None), (None, None)])
def test_window_id_int(raw, expected):
    assert p.window_id_int(raw) == expected


# --------------------------------------------------------------- geometry
PRIMARY = (0.0, 0.0, 1440.0, 900.0)  # Cocoa frame of the primary display


def test_point_on_primary():
    # Global (top-left) 100,100 is 800 up from the bottom on a 900-high screen.
    assert g.global_point_to_local((100, 100), PRIMARY, 900) == (100, 800)


def test_rect_on_primary():
    assert g.global_rect_to_local((100, 100, 200, 50), PRIMARY, 900) == (100, 750, 200, 50)


def test_secondary_display_left_and_above():
    # Second display 1920x1080 to the left, its bottom 200 pt above primary's top.
    sec = (-1920.0, 1100.0, 1920.0, 1080.0)
    # Global y for that display's top-left: 900 - (1100 + 1080) = -1280.
    assert g.global_point_to_local((-1920, -1280), sec, 900) == (0, 1080)
    assert g.cocoa_rect_to_global(sec, 900) == (-1920, -1280, 1920, 1080)


def test_screen_index_for_point():
    frames = [(0, 0, 1440, 900), (1440, 0, 1920, 1080)]
    assert g.screen_index_for_point((10, 10), frames) == 0
    assert g.screen_index_for_point((1500, 1000), frames) == 1
    assert g.screen_index_for_point((-5, 0), frames) is None


def test_pixels_to_points():
    assert g.pixels_to_points((2880, 1800), 2.0) == (1440, 900)
    with pytest.raises(ValueError):
        g.pixels_to_points((1, 1), 0)


def test_glide_ms():
    assert g.glide_ms((0, 0), (0, 0)) == 0
    assert g.glide_ms((0, 0), (10, 0)) == pytest.approx(252, abs=2)
    assert g.glide_ms((0, 0), (5000, 0)) == 450
    assert g.glide_ms((0, 0), (500, 0), speed=0) == 0
    assert g.glide_ms((0, 0), (5000, 0), speed=2) == 225


def test_occluded():
    target = (0, 0, 100, 100)
    assert not g.occluded(target, [])
    assert not g.occluded(target, [(90, 90, 50, 50)])
    assert g.occluded(target, [(0, 0, 60, 60)])
    assert not g.occluded((0, 0, 0, 0), [(0, 0, 10, 10)])
    assert g.intersects((0, 0, 10, 10), (5, 5, 10, 10))
    assert not g.intersects((0, 0, 10, 10), (10, 0, 10, 10))


# --------------------------------------------------------------- enabling
def test_overlay_enabled_rules():
    assert not overlay_enabled({}, platform="linux")
    assert not overlay_enabled({"DOBBY_OVERLAY": "1"}, platform="linux")
    assert overlay_enabled({}, platform="darwin")
    assert not overlay_enabled({"DOBBY_OVERLAY": "0"}, platform="darwin")
    assert not overlay_enabled({"PYTEST_CURRENT_TEST": "x"}, platform="darwin")
    assert overlay_enabled({"PYTEST_CURRENT_TEST": "x", "DOBBY_OVERLAY": "1"}, platform="darwin")
    assert not overlay_enabled({"DOBBY_REPLAY": "1"}, platform="darwin")


def test_overlay_config():
    cfg = overlay_config({"DOBBY_OVERLAY_COLOR": "#00ff00", "DOBBY_OVERLAY_SPEED": "0", "DOBBY_OVERLAY_LABEL": "D"})
    assert cfg == {"color": "#00ff00", "speed": 0.0, "label": "D"}
    assert overlay_config({"DOBBY_OVERLAY_SPEED": "fast"}) == {}


def test_wrap_hal_is_noop_when_disabled():
    hal = object()
    assert wrap_hal(hal, overlay=NullOverlay()) is hal


# --------------------------------------------------------------- client
FAKE_HELPER = textwrap.dedent("""
    import json, sys
    log = open(sys.argv[1], "a")
    print(json.dumps({"ready": True, "version": %d}), flush=True)
    for line in sys.stdin:
        log.write(line); log.flush()
        msg = json.loads(line)
        if msg.get("op") == "cursor.move" and msg.get("x") == 666:
            continue  # simulate a lost ack
        if "id" in msg:
            print(json.dumps({"ack": msg["id"], "ok": True}), flush=True)
        if msg.get("op") == "bye":
            break
""") % p.PROTOCOL_VERSION


@pytest.fixture
def fake_client(tmp_path):
    script = tmp_path / "helper.py"
    script.write_text(FAKE_HELPER)
    log = tmp_path / "log.jsonl"
    client = OverlayClient(cmd=[sys.executable, str(script), str(log)], ack_timeout=0.5, startup_timeout=5)
    yield client, log
    client.close()


def _ops(log):
    return [json.loads(line)["op"] for line in log.read_text().splitlines()]


def test_client_roundtrip(fake_client):
    client, log = fake_client
    assert not client.active
    assert client.move(10, 20, ms=0) is True
    assert client.active and client.pid
    assert client.click() is True
    assert client.state("typing") is True
    assert client.track(window_id="0x10") is True
    assert client.track() is False  # needs an id or pid
    assert client.hide() is True
    assert client.show() is True
    client.close()
    assert _ops(log) == ["cursor.move", "cursor.click", "cursor.state", "glow.track", "hide", "show", "bye"]


def test_client_ack_timeout_does_not_block(fake_client):
    client, _ = fake_client
    t0 = time.monotonic()
    assert client.move(666, 1, ms=0) is False
    assert time.monotonic() - t0 < 2.0
    assert client.move(1, 1, ms=0) is True  # still usable afterwards


def test_client_disables_when_helper_missing(tmp_path):
    client = OverlayClient(cmd=[str(tmp_path / "does-not-exist")])
    assert client.move(1, 2) is False
    assert client.click() is False
    assert not client.active
    assert client.hide() is True  # inactive overlay never blocks capture


def test_client_disables_on_protocol_mismatch(tmp_path):
    script = tmp_path / "old.py"
    script.write_text("import json,sys\nprint(json.dumps({'ready': True, 'version': 999}), flush=True)\n"
                      "[None for _ in sys.stdin]\n")
    client = OverlayClient(cmd=[sys.executable, str(script)], ack_timeout=0.3)
    client.move(1, 1)
    time.sleep(0.2)
    assert not client.active
    client.close()


def test_client_disables_when_helper_dies(tmp_path):
    script = tmp_path / "dies.py"
    script.write_text("import sys\nsys.exit(3)\n")
    client = OverlayClient(cmd=[sys.executable, str(script)], ack_timeout=0.3, startup_timeout=1)
    client.move(1, 1)
    time.sleep(0.3)
    assert client.move(2, 2) is False
    assert not client.active


# --------------------------------------------------------------- HAL wrapper
class RecordingOverlay(NullOverlay):
    active = True

    def __init__(self):
        self.calls = []

    def move(self, x, y, ms=None, wait=True):
        self.calls.append(("move", x, y, ms, wait))
        return True

    def click(self, button="left", count=1):
        self.calls.append(("click", button, count))
        return True

    def state(self, state):
        self.calls.append(("state", state))
        return True

    def track(self, window_id=None, pid=None):
        self.calls.append(("track", window_id))
        return True

    def hide(self):
        self.calls.append(("hide",))
        return True

    def show(self):
        self.calls.append(("show",))
        return True


class FakeHAL:
    def __init__(self, events):
        self.events = events

    def mouse_move(self, x, y):
        self.events.append(("hal.move", x, y))

    def mouse_click(self, x, y, button="left", click_count=1):
        self.events.append(("hal.click", x, y, button, click_count))
        return "clicked"

    def mouse_drag(self, sx, sy, ex, ey, duration_sec=0.3):
        self.events.append(("hal.drag", sx, sy, ex, ey))

    def keyboard_type(self, text, delay_ms=12.0):
        self.events.append(("hal.type", text))
        if text == "boom":
            raise RuntimeError("boom")

    def focus_window(self, window_id):
        self.events.append(("hal.focus", window_id))
        return window_id != "missing"

    def list_windows(self):
        return [SimpleNamespace(title="Vivado"), SimpleNamespace(title=p.OVERLAY_WINDOW_TITLE + " - Python")]

    def capture_screen(self, region=None):
        self.events.append(("hal.capture", region))
        return "image"

    def get_screen_size(self):
        return (1440, 900)


@pytest.fixture
def wrapped():
    ov = RecordingOverlay()
    events = ov.calls  # one shared timeline for overlay and HAL calls
    return OverlayHAL(FakeHAL(events), ov), events


def test_click_points_first_then_acts_then_ripples(wrapped):
    hal, ev = wrapped
    assert hal.mouse_click(5, 6, "right", 2) == "clicked"
    assert ev == [("move", 5, 6, None, True), ("hal.click", 5, 6, "right", 2), ("click", "right", 2)]


def test_coordinate_converter_applies_to_overlay_only():
    ov = RecordingOverlay()
    hal = OverlayHAL(FakeHAL(ov.calls), ov, to_points=lambda x, y: (x / 2, y / 2))
    hal.mouse_move(100, 50)
    assert ov.calls == [("move", 50.0, 25.0, None, True), ("hal.move", 100, 50)]


def test_drag_follows_in_parallel(wrapped):
    hal, ev = wrapped
    hal.mouse_drag(0, 0, 10, 10, 0.5)
    assert ev == [("move", 0, 0, None, True), ("move", 10, 10, 500, False), ("hal.drag", 0, 0, 10, 10)]


def test_typing_badge_reset_even_on_error(wrapped):
    hal, ev = wrapped
    with pytest.raises(RuntimeError):
        hal.keyboard_type("boom")
    assert ev == [("state", "typing"), ("hal.type", "boom"), ("state", "idle")]


def test_focus_tracks_only_on_success(wrapped):
    hal, ev = wrapped
    assert hal.focus_window("0x1") is True
    assert hal.focus_window("missing") is False
    assert ev == [("hal.focus", "0x1"), ("track", "0x1"), ("hal.focus", "missing")]


def test_capture_hides_overlay(wrapped):
    hal, ev = wrapped
    assert hal.capture_screen((0, 0, 10, 10)) == "image"
    assert ev == [("hide",), ("hal.capture", (0, 0, 10, 10)), ("show",)]


def test_capture_skips_handshake_when_inactive():
    ov = RecordingOverlay()
    ov.active = False
    hal = OverlayHAL(FakeHAL(ov.calls), ov)
    hal.capture_screen()
    assert ov.calls == [("hal.capture", None)]


def test_list_windows_filters_overlay(wrapped):
    hal, _ = wrapped
    assert [w.title for w in hal.list_windows()] == ["Vivado"]


def test_passthrough_and_unwrap(wrapped):
    hal, _ = wrapped
    assert hal.get_screen_size() == (1440, 900)
    assert isinstance(unwrap(hal), FakeHAL)
    assert wrap_hal(hal) is hal  # never double-wrapped


def test_click_moves_glow_to_active_window_once():
    ov = RecordingOverlay()
    inner = FakeHAL(ov.calls)
    inner.get_active_window = lambda: SimpleNamespace(window_id="77")
    hal = OverlayHAL(inner, ov)
    hal.mouse_click(1, 1)
    hal.mouse_click(2, 2)
    assert [c for c in ov.calls if c[0] == "track"] == [("track", "77")]


def test_active_window_errors_are_ignored():
    ov = RecordingOverlay()
    inner = FakeHAL(ov.calls)

    def broken():
        raise RuntimeError("no AX")

    inner.get_active_window = broken
    assert OverlayHAL(inner, ov).mouse_click(1, 1) == "clicked"
