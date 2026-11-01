"""
Tests for the macOS HAL and AX inspector using fake Quartz / AppKit / AX modules,
so they run on Linux CI. Real-device behaviour is covered by a manual smoke run.
"""

from types import SimpleNamespace

import pytest
from PIL import Image

from dobby.hal.macos import KEYCODES, MacHAL
from dobby.perception.ax import AXInspector


class FakeQuartz:
    def __init__(self, windows=None, screen=(1512, 982)):
        self.posted = []
        self.flags = {}
        self.fields = {}
        self.unicode = {}
        self.windows = windows or []
        self.screen = screen

    # events are plain dicts so tests can inspect them
    def CGEventCreateMouseEvent(self, src, etype, pos, btn):
        return {"kind": "mouse", "type": etype, "pos": tuple(pos), "btn": btn}

    def CGEventCreateKeyboardEvent(self, src, code, down):
        return {"kind": "key", "code": code, "down": down}

    def CGEventCreateScrollWheelEvent(self, src, unit, count, dy, dx):
        return {"kind": "scroll", "dy": dy, "dx": dx}

    def CGEventSetIntegerValueField(self, ev, field, value):
        ev[f"field_{field}"] = value

    def CGEventSetFlags(self, ev, flags):
        ev["flags"] = flags

    def CGEventKeyboardSetUnicodeString(self, ev, n, s):
        ev["unicode"] = s

    def CGEventPost(self, tap, ev):
        self.posted.append(ev)

    def CGEventCreate(self, src):
        return None

    def CGEventGetLocation(self, ev):
        return SimpleNamespace(x=10.6, y=20.2)

    def CGMainDisplayID(self):
        return 1

    def CGDisplayBounds(self, did):
        return SimpleNamespace(size=SimpleNamespace(width=self.screen[0], height=self.screen[1]),
                               origin=SimpleNamespace(x=0, y=0))

    def CGWindowListCopyWindowInfo(self, opts, wid):
        return self.windows


def _win(num, owner, title, pid, x, y, w, h, layer=0):
    return {"kCGWindowNumber": num, "kCGWindowOwnerName": owner, "kCGWindowName": title,
            "kCGWindowOwnerPID": pid, "kCGWindowLayer": layer,
            "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


class FakeAppKit:
    NSApplicationActivateIgnoringOtherApps = 2

    def __init__(self, front_pid=42):
        self.activated = []
        outer = self

        class App:
            def __init__(self, pid):
                self.pid = pid

            def processIdentifier(self):
                return self.pid

            def activateWithOptions_(self, opts):
                outer.activated.append(self.pid)
                return True

        class WS:
            def frontmostApplication(self_inner):
                return App(front_pid)

        self.NSWorkspace = SimpleNamespace(sharedWorkspace=lambda: WS())
        self.NSRunningApplication = SimpleNamespace(runningApplicationWithProcessIdentifier_=lambda pid: App(pid))


@pytest.fixture(autouse=True)
def _no_cooldown(monkeypatch):
    from dobby.config import CONFIG
    monkeypatch.setattr(CONFIG, "action_cooldown_ms", 0)
    monkeypatch.setattr("dobby.hal.macos.time.sleep", lambda s: None)


def _hal(**kw):
    q = FakeQuartz(**kw)
    return MacHAL(quartz=q, appkit=FakeAppKit(), capture_fn=lambda region: Image.new("RGB", (
        (region[2] * 2, region[3] * 2) if region else (3024, 1964)), "white")), q


def test_capture_is_resized_from_retina_to_points():
    hal, _ = _hal()
    assert hal.capture_screen().size == (1512, 982)
    assert hal.capture_screen(region=(100, 50, 400, 300)).size == (400, 300)


def test_click_posts_down_up_with_click_state():
    hal, q = _hal()
    hal.mouse_click(300, 200, click_count=2)
    clicks = [e for e in q.posted if e["kind"] == "mouse" and e["type"] in (1, 2)]
    assert [e["type"] for e in clicks] == [1, 2, 1, 2]
    assert [e["field_1"] for e in clicks] == [1, 1, 2, 2]
    assert all(e["pos"] == (300, 200) for e in clicks)


def test_right_click_and_failsafe():
    hal, q = _hal()
    hal.mouse_click(5, 5, button="right")
    assert {e["type"] for e in q.posted if e["kind"] == "mouse"} >= {3, 4}
    with pytest.raises(RuntimeError):
        hal.mouse_click(0, 0)


def test_hotkey_sets_modifier_flags():
    hal, q = _hal()
    hal.keyboard_hotkey(["cmd", "shift", "s"])
    keys = [e for e in q.posted if e["kind"] == "key"]
    assert [(e["code"], e["down"]) for e in keys] == [(KEYCODES["s"], True), (KEYCODES["s"], False)]
    assert all(e["flags"] == 0x100000 | 0x20000 for e in keys)


def test_press_key_and_unknown_key():
    hal, q = _hal()
    hal.keyboard_press_key("Escape")
    assert [e["code"] for e in q.posted] == [53, 53]
    with pytest.raises(ValueError):
        hal.keyboard_press_key("hyper")


def test_type_text_uses_unicode_events():
    hal, q = _hal()
    hal.keyboard_type("aé\n")
    uni = [e["unicode"] for e in q.posted if "unicode" in e]
    assert uni == ["a", "a", "é", "é"]
    assert [e["code"] for e in q.posted if e["kind"] == "key" and "unicode" not in e] == [36, 36]


def test_list_windows_and_focus():
    wins = [
        _win(1, "Dock", "", 10, 0, 0, 1512, 80, layer=20),     # not a normal window
        _win(7, "Vivado", "project_1", 42, 50, 40, 1200, 800),
        _win(8, "Vivado", "Settings", 42, 100, 100, 600, 400),
        _win(9, "Terminal", "zsh", 77, 0, 0, 800, 600),
        _win(10, "Tiny", "x", 78, 0, 0, 10, 10),               # too small
    ]
    hal, _ = _hal(windows=wins)
    out = hal.list_windows()
    assert [w.window_id for w in out] == ["7", "8", "9"]
    active = hal.get_active_window()
    assert active.window_id == "7" and active.title == "project_1 - Vivado" and active.app_name == "Vivado"
    assert sum(w.is_active for w in out) == 1
    assert hal.focus_window("9") is True
    assert hal._appkit.activated == [77]
    assert hal.focus_window("999") is False


def test_cursor_position_and_screen_size():
    hal, _ = _hal()
    assert hal.get_cursor_position() == (10, 20)
    assert hal.get_screen_size() == (1512, 982)


# ------------------------------------------------------------------- AX


class FakeAX:
    kAXValueCGPointType = 1
    kAXValueCGSizeType = 2

    def __init__(self, tree, trusted=True):
        self.tree = tree  # pid -> root element dict
        self.trusted = trusted
        self.set_calls = []

    def AXIsProcessTrusted(self):
        return self.trusted

    def AXUIElementCreateApplication(self, pid):
        return self.tree[pid]

    def AXUIElementCopyAttributeValue(self, el, name, _):
        if name in el:
            return 0, el[name]
        return -25212, None

    def AXValueGetValue(self, value, kind, _):
        return True, value

    def AXUIElementSetAttributeValue(self, el, name, value):
        self.set_calls.append((name, value))
        if el.get("electron") and name == "AXManualAccessibility":
            el["AXWindows"] = el.pop("_hidden_windows", [])  # Chromium exposes web content now
            return 0
        return -25205  # kAXErrorAttributeUnsupported


def _el(role, frame=None, children=(), **attrs):
    d = {"AXRole": role, "AXChildren": list(children), **attrs}
    if frame:
        x, y, w, h = frame
        d["AXPosition"] = SimpleNamespace(x=x, y=y)
        d["AXSize"] = SimpleNamespace(width=w, height=h)
    return d


def _ax_tree():
    save = _el("AXButton", (100, 100, 80, 24), AXTitle="Save", AXEnabled=True, AXFocused=True)
    tiny = _el("AXButton", (0, 0, 2, 2), AXTitle="dot")
    offscreen = _el("AXButton", (5000, 5000, 80, 24), AXTitle="Hidden")
    field = _el("AXTextField", (100, 140, 200, 22), AXPlaceholderValue="Search", AXEnabled=True)
    label = _el("AXStaticText", (100, 60, 200, 20), AXValue="Discard changes?")
    tab = _el("AXRadioButton", (10, 10, 60, 20), AXTitle="Sources")
    tabs = _el("AXTabGroup", (0, 0, 300, 40), children=[tab])
    dialog = _el("AXWindow", (50, 50, 400, 200), children=[label, save, field, tiny, offscreen, tabs],
                 AXSubrole="AXDialog", AXTitle="Confirm")
    return {42: {"AXWindows": [dialog]}}


def _inspector(**kw):
    return AXInspector(ax=FakeAX(_ax_tree(), **kw), appkit=FakeAppKit(front_pid=42), screen_bounds=(0, 0, 1512, 982))


def test_ax_inspector_maps_roles_and_prunes(monkeypatch):
    insp = _inspector()
    els = insp.inspect_desktop()
    names = {e.name: e for e in els}
    assert set(names) == {"Confirm", "Save", "Search", "Sources"}  # dialog kept, label filtered, tiny/offscreen pruned
    assert names["Confirm"].role == "dialog"
    assert names["Save"].role == "push button" and "focused" in names["Save"].states
    assert names["Search"].role == "entry"
    assert names["Sources"].role == "page tab"

    everything = insp.inspect()
    assert any(e.role == "label" and e.name == "Discard changes?" for e in everything)


def test_ax_inspector_requires_permission():
    insp = _inspector(trusted=False)
    assert insp.is_available is False
    assert "Accessibility" in insp.error
    assert insp.inspect_desktop() == []


def test_ax_inspector_node_budget():
    insp = AXInspector(ax=FakeAX(_ax_tree()), appkit=FakeAppKit(front_pid=42), max_nodes=2)
    assert len(insp.inspect()) <= 2


def test_factory_picks_mac_hal(monkeypatch):
    import dobby.hal.factory as factory
    import dobby.hal.macos as macos

    monkeypatch.setattr(factory, "_HAL_INSTANCE", None)
    monkeypatch.setattr(factory.sys, "platform", "darwin")
    monkeypatch.setattr(macos, "_load_quartz", lambda: FakeQuartz())
    hal = factory.get_desktop_hal()
    backend = getattr(hal, "backend", hal)
    assert isinstance(backend, MacHAL)
    monkeypatch.setattr(factory, "_HAL_INSTANCE", None)


def test_ax_inspector_enables_electron_web_content(monkeypatch):
    from dobby.config import CONFIG

    monkeypatch.setattr(CONFIG, "ax_web_content_settle_seconds", 0)
    send = _el("AXButton", (200, 300, 60, 24), AXTitle="Send", AXEnabled=True)
    web = _el("AXWebArea", (0, 30, 1512, 900), children=[send])
    win = _el("AXWindow", (0, 0, 1512, 982), children=[web], AXTitle="Claude")
    fake = FakeAX({42: {"electron": True, "_hidden_windows": [win]}})
    insp = AXInspector(ax=fake, appkit=FakeAppKit(front_pid=42), screen_bounds=(0, 0, 1512, 982))
    assert [e.name for e in insp.inspect_desktop()] == ["Send"]
    assert insp.web_content_enabled == {42: True}
    insp.inspect_desktop()
    assert fake.set_calls == [("AXManualAccessibility", True)]  # once per pid


def test_ax_inspector_native_app_rejects_flag_harmlessly():
    insp = _inspector()
    assert {e.name for e in insp.inspect_desktop()} >= {"Save"}
    assert insp.web_content_enabled == {42: False}
    insp.inspect_desktop()
    assert insp._ax.set_calls == [("AXManualAccessibility", True)]


def test_ax_inspector_web_content_can_be_disabled(monkeypatch):
    from dobby.config import CONFIG

    monkeypatch.setattr(CONFIG, "ax_enable_web_content", False)
    insp = _inspector()
    insp.inspect_desktop()
    assert insp._ax.set_calls == []


def test_ax_inspector_wrapper_groups_do_not_use_depth():
    leaf = _el("AXButton", (10, 10, 40, 20), AXTitle="Deep")
    node = leaf
    for _ in range(30):
        node = _el("AXGroup", (0, 0, 500, 500), children=[node])
    win = _el("AXWindow", (0, 0, 800, 600), children=[node], AXTitle="W")
    insp = AXInspector(ax=FakeAX({42: {"AXWindows": [win]}}), appkit=FakeAppKit(front_pid=42),
                       screen_bounds=(0, 0, 1512, 982))
    assert [e.name for e in insp.inspect_desktop(max_depth=4)] == ["Deep"]


def test_ax_inspector_includes_top_level_menu_bar(monkeypatch):
    from dobby.config import CONFIG

    item_in_menu = _el("AXMenuItem", (60, 30, 120, 20), AXTitle="New Note")
    menu = _el("AXMenu", (60, 25, 200, 300), children=[item_in_menu])
    file_item = _el("AXMenuBarItem", (60, 0, 40, 24), children=[menu], AXTitle="File", AXEnabled=True)
    bar = _el("AXMenuBar", (0, 0, 1512, 24), children=[file_item])
    win = _el("AXWindow", (0, 30, 800, 600), children=[_el("AXButton", (10, 60, 40, 20), AXTitle="OK")], AXTitle="W")
    tree = {42: {"AXWindows": [win], "AXMenuBar": bar}}
    insp = AXInspector(ax=FakeAX(tree), appkit=FakeAppKit(front_pid=42), screen_bounds=(0, 0, 1512, 982))
    els = insp.inspect_desktop()
    assert [(e.name, e.role) for e in els] == [("File", "menu item"), ("OK", "push button")]  # closed menu not walked
    monkeypatch.setattr(CONFIG, "ax_include_menu_bar", False)
    assert [e.name for e in insp.inspect_desktop()] == ["OK"]
