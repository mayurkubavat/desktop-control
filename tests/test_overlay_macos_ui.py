"""Native checks of the overlay helper's controls on macOS (skipped elsewhere).

Builds a real OverlayController (windows are created but no event loop runs)
and drives the control bar, the clickable name tag and Turbo directly.
"""

from __future__ import annotations

import io
import json
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS AppKit")


@pytest.fixture
def make(tmp_path):
    AppKit = pytest.importorskip("AppKit")
    AppKit.NSApplication.sharedApplication()
    from dobby.overlay import mac_helper

    made = []

    def _make(**cfg):
        out = io.StringIO()
        base = {"menu_bar": False, "bar_lock": str(tmp_path / "bar.lock")}
        base.update(cfg)
        c = mac_helper.OverlayController(base, out=out, interactive=False)
        c._claim_bar()
        made.append(c)
        return c, out

    yield _make
    for c in made:
        for p in c.panels:
            p.close()
        if c.hotspot is not None:
            c.hotspot.close()
        if c.pill is not None:
            c.pill.close()
        c.bar_owner.release()


def _lines(out):
    return [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]


def _events(out):
    return [m["event"] for m in _lines(out) if "event" in m]


# ------------------------------------------------------------ control bar
def test_bar_shows_ready_at_start_and_stays(make):
    c, _ = make()
    assert c.pill.mode == "ready" and c.pill.visible
    assert c.pill.window.isVisible()
    c.last_action = time.monotonic() - 3600  # long idle
    c.on_tick()
    assert c.pill.mode == "ready" and c.pill.window.isVisible()


def test_bar_hidden_from_captures_by_default(make):
    from AppKit import NSWindowSharingNone

    c, _ = make()
    assert c.pill.window.sharingType() == NSWindowSharingNone
    # Dobby's own capture handshake no longer blinks the bar
    c.capture_hidden = True
    c._apply_alpha()
    assert c.pill.window.alphaValue() == 1.0


def test_bar_hide_and_show_again(make):
    c, _ = make()
    assert c.pill.label.stringValue() == "Dobby is sleeping"
    c.set_pill_hidden(True)
    assert not c.pill.window.isVisible()
    c.set_pill_hidden(False)
    assert c.pill.window.isVisible()


def test_hidden_bar_comes_back_when_dobby_wakes_up(make):
    c, _ = make()
    c.last_action = time.monotonic() - 3600  # sleeping
    c.set_pill_hidden(True)
    c._mark_active()  # Dobby starts working
    assert c.pill.window.isVisible() and c.pill.mode == "working"


def test_bar_hidden_while_working_stays_hidden_until_next_wake(make):
    c, _ = make()
    c._mark_active()
    c.set_pill_hidden(True)
    c._mark_active()  # still the same burst of work
    assert not c.pill.window.isVisible()
    c.last_action = time.monotonic() - 3600
    c.on_tick()  # falls asleep, still hidden
    assert not c.pill.window.isVisible()
    c._mark_active()  # wakes up
    assert c.pill.window.isVisible()


def test_allow_deny_shows_even_when_bar_hidden(make):
    c, out = make()
    c.set_pill_hidden(True)
    c._start_confirm(7, "Allow Dobby to quit?", 5)
    assert c.pill.mode == "confirm" and c.pill.window.isVisible()
    assert c.pill.hide_btn.isHidden()  # can't hide a pending question
    c.on_pill("secondary")
    assert {"ack": 7, "ok": False} in _lines(out)
    assert not c.pill.window.isVisible()


def test_second_helper_does_not_stack_an_idle_bar(make):
    a, _ = make()
    b, _ = make()
    assert a.bar_owner.owned and not b.bar_owner.owned
    assert a.pill.window.isVisible() and not b.pill.window.isVisible()
    b.last_action = time.monotonic()
    b._refresh_pill()
    assert b.pill.window.isVisible()  # but it shows while working
    a.bar_owner.release()
    b._claim_bar()
    assert b.bar_owner.owned


def test_bar_fades_instead_of_vanishing_near_dobbys_pointer(make):
    c, _ = make()
    c.pill.duck(True)
    assert c.pill.window.isVisible()
    assert c.pill.window.ignoresMouseEvents()
    assert c.pill.view.alphaValue() < 0.5
    c.pill.duck(False)
    assert not c.pill.window.ignoresMouseEvents() and c.pill.view.alphaValue() == 1.0


def test_pause_resume_and_stop_from_bar(make):
    c, out = make()
    c.on_pill("primary")  # ready -> pause
    assert c.paused and c.pill.mode == "paused"
    c.on_pill("primary")  # resume
    assert not c.paused
    c.on_pill("secondary")  # stop
    assert c.pill.mode == "stopped"
    assert _events(out)[:3] == ["pause", "resume", "stop"]
    c.stopped_until = 0
    c.last_action = 0
    c.on_tick()
    assert c.pill.mode == "ready"


def test_turbo_auto_allows_and_labels_bar(make):
    c, out = make(turbo=True)
    c._start_confirm(3, "Allow Dobby to quit?", 5)
    assert {"ack": 3, "ok": True} in _lines(out)
    assert c.pill.mode != "confirm"
    assert "Turbo" in c.pill.label.stringValue()


def test_bar_off_and_auto_modes(make):
    off, _ = make(pill="off")
    assert off.pill is None
    auto, _ = make(pill="auto")
    assert not auto.pill.window.isVisible()


# ----------------------------------------------------- waking Dobby up
def _asleep(c):
    c.last_action = time.monotonic() - 3600
    c._refresh_pill()
    assert c.pill.mode == "ready"


def test_click_sleeping_bar_wakes_dobby(make):
    c, out = make()
    _asleep(c)
    assert c.pill.view.toolTip() == "Click to wake Dobby"
    w0 = c.pill.window.frame().size.width
    c.on_pill_label()
    assert c.pill.mode == "awake" and c.pill.label.stringValue().startswith("Dobby is awake")
    assert c.pill.view.toolTip() == "Click to put Dobby to sleep"
    assert c.pill.window.frame().size.width > w0
    assert _events(out) == ["wake"]
    assert c.pointer_visible and c.cursor is not None
    assert all(p.pointer.opacity() == 1.0 for p in c.panels)
    assert not c.pill.ducked  # the pointer lands clear of the bar


def test_wake_shows_a_hidden_bar(make):
    c, _ = make()
    _asleep(c)
    c.set_pill_hidden(True)
    c.wake()
    assert c.pill.window.isVisible() and c.pill.mode == "awake"


def test_wake_keeps_an_existing_pointer_where_it_is(make):
    c, _ = make()
    _asleep(c)
    c.cursor = (321.0, 456.0)
    c.wake()
    assert c.cursor == (321.0, 456.0) and c.pointer_visible


def test_awake_falls_back_asleep(make):
    c, out = make()
    _asleep(c)
    c.on_pill_label()
    c.awake_until = time.monotonic() - 1
    c.on_tick()
    assert c.pill.mode == "ready" and _events(out) == ["wake", "sleep"]
    assert not c.pointer_visible and c.cursor is None  # the wake pointer fades out


def test_click_awake_bar_puts_dobby_to_sleep(make):
    c, out = make()
    _asleep(c)
    c.on_pill_label()
    c.on_pill_label()
    assert c.pill.mode == "ready" and _events(out) == ["wake", "sleep"]


def test_work_ends_awake_and_then_dobby_sleeps(make):
    c, out = make()
    _asleep(c)
    c.wake()
    c._mark_active()
    assert c.pill.mode == "working" and c.awake_until == 0
    assert _events(out) == ["wake", "sleep"]
    c.last_action = time.monotonic() - 3600  # the work burst ends
    c.on_tick()
    assert c.pill.mode == "ready"


def test_stop_while_awake_goes_back_to_sleep(make):
    c, _ = make()
    _asleep(c)
    c.wake()
    c.request_stop()
    c.stopped_until = 0
    c.on_tick()
    assert c.pill.mode == "ready"


def test_menu_offers_wake_and_sleep(make):
    c, _ = make()
    _asleep(c)
    def titles():
        menu = c._build_menu("Idle")
        return [menu.itemAtIndex_(i) for i in range(menu.numberOfItems())]
    wake = next(i for i in titles() if i.title() == "Wake Dobby")
    assert wake.target() is c.target and wake.action() == "menuWake:"
    c.target.menuWake_(None)
    assert c.pill.mode == "awake"
    sleep = next(i for i in titles() if i.title() == "Put Dobby to sleep")
    assert sleep.action() == "menuSleep:"
    c.target.menuSleep_(None)
    assert c.pill.mode == "ready"


def test_non_owner_helper_shows_awake(make):
    a, _ = make()
    b, _ = make()
    assert not b.bar_owner.owned and not b.pill.window.isVisible()
    b.wake()
    assert b.pill.mode == "awake" and b.pill.window.isVisible()


# ----------------------------------------------- clickable tag (the ▾)
def _show_pointer(c, x=400.0, y=300.0):
    c.cursor = (x, y)
    c._set_pointer_visible(True)
    c._refresh_tag()


def test_tag_is_clickable_where_it_is_drawn(make):
    c, _ = make()
    _show_pointer(c)
    hs = c.hotspot
    assert hs.shown and hs.window.isVisible()
    assert not hs.window.ignoresMouseEvents()
    x, y, w, h = hs.rect
    assert w == pytest.approx(max(p.tag.width for p in c.panels), abs=1.0) and w > 30  # snapped to points
    f = hs.window.frame()
    assert (f.origin.x, f.size.width) == pytest.approx((x, w))
    assert f.origin.y == pytest.approx(c.primary_h - y - h)
    # never over the tip, where Dobby clicks
    from dobby.overlay import geometry

    assert not geometry.contains(hs.rect, c.cursor)


def test_tag_click_area_grows_with_step_text(make):
    c, _ = make()
    _show_pointer(c)
    w0 = c.hotspot.rect[2]
    c.intent_text, c.intent_until = "Click 'Run Synthesis'", time.monotonic() + 5
    c._refresh_tag()
    assert c.hotspot.rect[2] > w0 + 40


def test_tag_click_area_hidden_with_pointer_and_during_capture(make):
    c, _ = make()
    _show_pointer(c)
    c.capture_hidden = True
    c._apply_alpha()
    assert not c.hotspot.shown
    c.capture_hidden = False
    c._apply_alpha()
    assert c.hotspot.shown
    c._set_pointer_visible(False)
    assert not c.hotspot.shown


def test_tag_menu_matches_menu_bar_menu(make):
    c, _ = make()
    menu = c._build_menu("Idle")
    titles = [menu.itemAtIndex_(i).title() for i in range(menu.numberOfItems())]
    assert titles[0] == "Dobby: Idle"
    for want in ("Pause", "Stop", "Show control bar (⌃⌥H)", "Show overlay"):
        assert want in titles
    stop = menu.itemAtIndex_(titles.index("Stop"))
    assert stop.target() is c.target and stop.action() == "menuStop:"
