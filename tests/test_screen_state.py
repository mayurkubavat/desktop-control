"""Screen state: AX + OCR merge, valid operations, re-binding, act and decide with fakes."""

import math
from types import SimpleNamespace

import pytest

from vision_mcp.gemma.client import GemmaClient
from vision_mcp.gemma.decide import GemmaDecider
from vision_mcp.perception.ocr import OCRLine
from vision_mcp.screen_state import StateTracker, build_state, rebind
from vision_mcp.screen_state.observe import act_on_element, decide_next_element, observe
from vision_mcp.screen_state.state import coarse_position
from vision_mcp.types import BoundingBox, WindowInfo

WIN = WindowInfo(window_id="1", title="Untitled", bbox=BoundingBox(x=0, y=0, width=900, height=600),
                 is_active=True, app_name="TextEdit")


def node(role, name, x, y, w=80, h=24, states=("enabled",), interactable=True):
    return {"role": role, "name": name, "bbox": {"x": x, "y": y, "width": w, "height": h},
            "states": list(states), "interactable": interactable}


# ------------------------------------------------------------------- build


def test_build_state_numbers_orders_and_positions():
    s = build_state(
        [node("push button", "Save", 780, 550), node("push button", "Cancel", 680, 550), node("menu item", "File", 10, 5)],
        window=WIN, generation=3,
    )
    assert [e.label for e in s.elements] == ["File", "Cancel", "Save"]
    assert [e.eid for e in s.elements] == ["e1", "e2", "e3"]
    assert s.elements[0].position == "top left" and s.elements[2].position == "bottom right"
    assert s.generation == 3 and s.app == "TextEdit" and s.window_title == "Untitled"


def test_empty_ax_label_is_filled_from_ocr_and_ocr_only_text_becomes_element():
    ocr = [OCRLine("Message", 110, 305, 60, 14, 0.95), OCRLine("Synthesis Completed", 300, 100, 150, 16, 0.9)]
    s = build_state([node("entry", "", 100, 300, 400, 30)], ocr, window=WIN)
    entry = next(e for e in s.elements if e.role == "entry")
    assert entry.label == "Message" and entry.source == "ax+ocr"
    text = next(e for e in s.elements if e.role == "text")
    assert text.label == "Synthesis Completed" and text.source == "ocr"
    assert "Message" not in s.text  # consumed by the entry


def test_low_confidence_ocr_dropped_and_overflow_goes_to_text():
    ocr = [OCRLine(f"line {i}", 10, 40 + 20 * i, 50, 12, 0.9) for i in range(5)] + [OCRLine("noise", 500, 500, 40, 10, 0.1)]
    s = build_state([], ocr, window=WIN, max_ocr_elements=2)
    assert len(s.elements) == 2 and s.text == ["line 2", "line 3", "line 4"]


def test_type_offered_only_for_focused_editable_non_secure():
    plain = build_state([node("push button", "OK", 10, 10)], window=WIN)
    assert "type" not in plain.operations
    focused = build_state([node("entry", "Name", 10, 10, states=("focused", "enabled"))], window=WIN)
    assert "type" in focused.operations and not focused.secure_input
    pw = build_state([node("password text", "Password", 10, 10, states=("focused", "enabled"))], window=WIN)
    assert "type" not in pw.operations and pw.secure_input
    labelled = build_state([node("entry", "API key", 10, 10, states=("focused", "enabled"))], window=WIN)
    assert labelled.secure_input
    scroll = build_state([node("scroll pane", "", 0, 0, 900, 600, interactable=False), node("push button", "OK", 10, 10)], window=WIN)
    assert "scroll" in scroll.operations


def test_to_text_is_compact_and_marks_state():
    s = build_state([node("push button", "Save", 780, 550, states=("disabled",)),
                     node("entry", "Name", 10, 100, states=("focused", "enabled"))], window=WIN, generation=1)
    t = s.to_text()
    assert 'Window: TextEdit - "Untitled"' in t
    assert "Focused: e1 entry" in t
    assert 'e2 push button "Save" (bottom right, disabled)' in t
    assert "Available operations: click, type" in t


def test_coarse_position():
    assert coarse_position(450, 300, (0, 0, 900, 600)) == "center"
    assert coarse_position(10, 590, (0, 0, 900, 600)) == "bottom left"
    assert coarse_position(10, 10, None) == ""


# ------------------------------------------------------------------ rebind


def test_rebind_follows_moved_element_and_refuses_vanished():
    old = build_state([node("push button", "Save", 780, 550)], window=WIN).elements[0]
    moved = build_state([node("push button", "Save", 760, 540), node("push button", "Save", 100, 100)], window=WIN)
    got = rebind(old, moved)
    assert got is not None and (got.x, got.y) == (760, 540)  # nearest of the two Saves
    gone = build_state([node("push button", "Cancel", 780, 550)], window=WIN)
    assert rebind(old, gone) is None
    far = build_state([node("push button", "Save", 0, 0)], window=WIN)
    assert rebind(old, far) is None


def test_rebind_unlabelled_by_role_and_distance():
    old = build_state([node("push button", "", 300, 300)], window=WIN).elements[0]
    near = build_state([node("push button", "", 310, 305)], window=WIN)
    assert rebind(old, near) is not None
    assert rebind(old, build_state([node("push button", "", 800, 50)], window=WIN)) is None


def test_tracker_generations_and_freshness():
    t = StateTracker(keep=2)
    gens = [t.next_generation() for _ in range(3)]
    assert gens == [1, 2, 3]
    for g in gens:
        t.remember(build_state([], window=WIN, generation=g, captured_at=float(g)))
    assert t.get(1) is None and t.latest.generation == 3
    t.last_action_at = 2.5
    assert t.is_fresh(t.get(3)) and not t.is_fresh(t.get(2))


# --------------------------------------------------------- observe and act


class FakeHAL:
    def __init__(self):
        self.clicks, self.typed, self.keys = [], [], []

    def get_active_window(self):
        return WIN

    def mouse_click(self, x, y, button="left", click_count=1):
        self.clicks.append((x, y, click_count))

    def keyboard_type(self, text, delay_ms=12.0):
        self.typed.append(text)

    def keyboard_press_key(self, key):
        self.keys.append(key)


class FakeController:
    """Serves a sequence of AX trees, one per observation (the last one repeats)."""

    def __init__(self, trees, lines=None):
        self.trees = list(trees)
        self.lines = lines or []
        self.hal = FakeHAL()
        self.actions = []

    def get_accessibility_tree(self, app_name_filter=None, filter_interactable=True):
        return self.trees.pop(0) if len(self.trees) > 1 else self.trees[0]

    def read_screen_lines(self, region=None):
        return list(self.lines)

    def execute_with_verification(self, action_name, action_func, verify_delta=True, **kw):
        self.actions.append(action_name)
        action_func()
        return SimpleNamespace(model_dump=lambda: {"success": True, "delta_detected": True, "change_ratio": 0.2, "message": ""})


def test_observe_clips_to_window():
    ctl = FakeController([[node("push button", "OK", 10, 10), node("push button", "Off", 2000, 2000)]])
    s = observe(ctl, StateTracker())
    assert [e.label for e in s.elements] == ["OK"]


def test_act_rebinds_then_clicks_and_reports_change():
    ctl = FakeController([
        [node("push button", "Save", 780, 550)],                       # observation the caller saw
        [node("push button", "Save", 770, 548)],                       # fresh frame before acting (moved)
        [node("label", "Saved", 300, 300, interactable=True)],         # after
    ])
    t = StateTracker()
    s = observe(ctl, t)
    res = act_on_element(ctl, t, s.elements[0].eid, s.generation)
    assert res["ok"] and ctl.hal.clicks == [(810, 560, 1)]
    assert res["change"]["changed"] and res["generation"] == 3 and res["fresh_after_action"]


def test_act_refuses_stale_disabled_and_secure():
    t = StateTracker()
    ctl = FakeController([[node("push button", "Save", 780, 550)], [node("push button", "Cancel", 780, 550)]])
    s = observe(ctl, t)
    res = act_on_element(ctl, t, "e1", s.generation)
    assert not res["ok"] and "gone or moved" in res["reason"] and ctl.hal.clicks == []

    ctl2 = FakeController([[node("push button", "Save", 780, 550, states=("disabled",))]])
    s2 = observe(ctl2, t)
    assert "disabled" in act_on_element(ctl2, t, "e1", s2.generation)["reason"]

    ctl3 = FakeController([[node("password text", "Password", 100, 100, states=("enabled",))]])
    s3 = observe(ctl3, t)
    res3 = act_on_element(ctl3, t, "e1", s3.generation, action="type", text="hunter2")
    assert not res3["ok"] and "secure" in res3["reason"] and ctl3.hal.typed == []

    assert "unknown generation" in act_on_element(ctl3, t, "e1", 999)["reason"]


def test_act_type_clicks_then_types_without_enter_by_default():
    t = StateTracker()
    ctl = FakeController([[node("entry", "Name", 100, 100, 200, 30)]])
    s = observe(ctl, t)
    res = act_on_element(ctl, t, "e1", s.generation, action="type", text="hello")
    assert res["ok"] and ctl.hal.typed == ["hello"] and ctl.hal.keys == []


class FakeLogprobOllama:
    def __init__(self, top):
        self.top = top

    def __call__(self, method, url, body, timeout):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "gemma3:4b"}]}
        self.body = body
        return {"message": {"content": self.top[0][0]},
                "logprobs": [{"token": self.top[0][0], "logprob": self.top[0][1],
                              "top_logprobs": [{"token": t, "logprob": lp} for t, lp in self.top]}]}


def test_decide_next_element_maps_choice_to_eid_and_gates():
    ctl = FakeController([[node("push button", "Cancel", 680, 550), node("push button", "Save", 780, 550),
                           node("menu item", "File", 10, 5)]])
    fake = FakeLogprobOllama([("A", math.log(0.9)), ("B", math.log(0.1))])
    decider = GemmaDecider(GemmaClient(transport=fake))
    out = decide_next_element(ctl, StateTracker(), decider, "save the document", verb="click", k=2)
    # shortlist puts "Save" first (word overlap), so option A = Save
    assert out["element"]["label"] == "Save" and out["eid"] == "e3"
    assert out["gate"]["verdict"] == "act"
    assert "Goal: save the document" in fake.body["messages"][1]["content"]
    out2 = decide_next_element(ctl, StateTracker(), decider, "save the document", verb="delete")
    assert out2["gate"]["verdict"] == "stop"  # consequential without authorization
