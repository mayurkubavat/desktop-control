"""
Live wiring for screen state: observe the active window, decide on an element
with the local decision core, and act on it after re-binding to a fresh frame.

Everything goes through the controller (HAL, AX inspector, OCR, verification),
so cassette replay works unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from dobby.screen_state.state import MENU_BAR_HEIGHT, ScreenState, StateTracker, build_state, rebind

logger = logging.getLogger(__name__)


def _window_region(win: Any) -> Optional[Tuple[int, int, int, int]]:
    try:
        b = win.bbox
        if b.width > 0 and b.height > 0:
            return (b.x, b.y, b.width, b.height)
    except Exception:
        pass
    return None


def _overlaps(box: Dict[str, Any], region: Tuple[int, int, int, int]) -> bool:
    try:
        x, y, w, h = int(box["x"]), int(box["y"]), int(box["width"]), int(box["height"])
    except (KeyError, TypeError, ValueError):
        return False
    rx, ry, rw, rh = region
    return x + w > rx and y + h > ry and x < rx + rw and y < ry + rh


def _in_menu_bar(node: Dict[str, Any]) -> bool:
    """A menu bar item of the frontmost app (outside the window, at the top of the screen)."""
    box = node.get("bbox") or {}
    try:
        return node.get("role") == "menu item" and int(box["y"]) + int(box["height"]) <= MENU_BAR_HEIGHT
    except (KeyError, TypeError, ValueError):
        return False


def observe(
    controller: Any,
    tracker: StateTracker,
    app_name_filter: Optional[str] = None,
    use_ocr: bool = True,
    clip_to_window: bool = True,
) -> ScreenState:
    """One fresh observation of the active window as a numbered :class:`ScreenState`."""
    generation = tracker.next_generation()
    win = None
    try:
        win = controller.hal.get_active_window()
    except Exception as e:
        logger.debug("active window unavailable: %s", e)
    region = _window_region(win) if win is not None else None

    try:
        nodes = controller.get_accessibility_tree(app_name_filter=app_name_filter, filter_interactable=True) or []
    except Exception as e:
        logger.debug("AX tree unavailable: %s", e)
        nodes = []
    nodes = [n.model_dump() if hasattr(n, "model_dump") else n for n in nodes if n]
    if clip_to_window and region is not None:
        # The app's menu bar lives outside its window; keep it so "open the File menu" has a target.
        nodes = [
            n for n in nodes
            if isinstance(n, dict) and (_overlaps(n.get("bbox") or {}, region) or _in_menu_bar(n))
        ]

    lines = []
    if use_ocr:
        try:
            lines = controller.read_screen_lines(region)
        except Exception as e:
            logger.debug("OCR unavailable: %s", e)
            lines = []

    state = build_state(nodes, lines, window=win, generation=generation)
    return tracker.remember(state)


def summarize_change(before: ScreenState, after: ScreenState) -> Dict[str, Any]:
    """What changed between two observations, by (role, label)."""
    b = {(e.role, e.label) for e in before.elements}
    a = {(e.role, e.label) for e in after.elements}
    added = sorted(a - b)[:10]
    removed = sorted(b - a)[:10]
    return {
        "changed": bool(added or removed) or before.window_title != after.window_title,
        "window_changed": before.window_title != after.window_title or before.app != after.app,
        "added": [f"{r} \"{l}\"" for r, l in added],
        "removed": [f"{r} \"{l}\"" for r, l in removed],
    }


def act_on_element(
    controller: Any,
    tracker: StateTracker,
    eid: str,
    generation: int,
    action: str = "click",
    text: Optional[str] = None,
    press_enter: bool = False,
    app_name_filter: Optional[str] = None,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Re-binds ``eid`` from observation ``generation`` on a fresh frame, then acts once.

    ``action`` is ``click``, ``double_click`` or ``type`` (click to focus, then type
    ``text``; Return only when ``press_enter``). Refuses stale, vanished,
    disabled or secure targets instead of clicking where the element used to be.
    """
    old = tracker.get(int(generation))
    if old is None:
        return {"ok": False, "reason": f"unknown generation {generation}: call get_screen_state again"}
    chosen = old.get(eid)
    if chosen is None:
        return {"ok": False, "reason": f"{eid} is not in generation {generation}"}
    if action not in ("click", "double_click", "type"):
        return {"ok": False, "reason": f"unsupported action '{action}'"}
    if action == "type" and not text:
        return {"ok": False, "reason": "type needs text"}

    fresh = observe(controller, tracker, app_name_filter=app_name_filter)
    target = rebind(chosen, fresh)
    if target is None:
        return {
            "ok": False,
            "reason": f"{chosen.describe()} is gone or moved since generation {generation}",
            "generation": fresh.generation,
        }
    if not target.enabled:
        return {"ok": False, "reason": f"{target.describe()} is disabled", "generation": fresh.generation}
    if action == "type" and (target.secure or not target.editable):
        why = "a secure field" if target.secure else "not editable"
        return {"ok": False, "reason": f"{target.describe()} is {why}", "generation": fresh.generation}

    cx, cy = target.center
    hal = controller.hal

    def _do() -> None:
        hal.mouse_click(cx, cy, button="left", click_count=2 if action == "double_click" else 1)
        if action == "type":
            hal.keyboard_type(text)
            if press_enter:
                hal.keyboard_press_key("enter")

    tracker.mark_action()
    try:
        res = controller.execute_with_verification(
            action_name=f"{action}({target.eid} {target.role} '{target.label[:40]}')",
            action_func=_do,
            verify_delta=verify_delta,
        )
        verification = res.model_dump() if hasattr(res, "model_dump") else res
    except Exception as e:
        return {"ok": False, "reason": f"action failed: {e}", "generation": fresh.generation}

    after = observe(controller, tracker, app_name_filter=app_name_filter)
    change = summarize_change(fresh, after)
    return {
        "ok": True,
        "acted_on": target.as_dict(),
        "rebound_from": chosen.eid if chosen.eid != target.eid else None,
        "generation": after.generation,
        "fresh_after_action": tracker.is_fresh(after),
        "change": change,
        "verification": {k: verification.get(k) for k in ("success", "delta_detected", "change_ratio", "message") if isinstance(verification, dict) and k in verification},
    }


def decide_next_element(
    controller: Any,
    tracker: StateTracker,
    decider: Any,
    goal: str,
    verb: str = "click",
    authorized: bool = False,
    k: int = 12,
    app_name_filter: Optional[str] = None,
    confirm: bool = True,
    confirm_at: float = 0.7,
) -> Dict[str, Any]:
    """
    Observes, shortlists elements by the goal, lets the local decider choose one,
    and gates the choice by the verb's risk. Acts on nothing: the caller acts
    only when ``gate.verdict`` is "act" (then :func:`act_on_element`).

    With ``confirm`` a second, overlapping yes/no question checks the pick
    ("using X advances the goal"). A choice is always relative to the
    shortlist, so it stays confident when the right target is missing; the
    yes/no is absolute, so a "no" there downgrades "act" to "escalate".
    """
    from dobby.gemma.decide import shortlist
    from dobby.gemma.gate import GateResult, Verdict, gate

    state = observe(controller, tracker, app_name_filter=app_name_filter)
    candidates = shortlist(goal, state.elements, k=max(1, min(25, k)), text=lambda e: f"{e.role} {e.label}")
    if not candidates:
        return {"generation": state.generation, "eid": None, "gate": {"verdict": "escalate", "reason": "no elements on screen"}}
    ctx = f"Goal: {goal.strip()}\n" + state.to_text(elements=[], max_text_lines=10)
    options = [e.describe() for e in candidates]
    decision = decider.choose(ctx, f"Which element should be used to {verb} next to advance the goal?", options)
    eid = None if decision.is_none else candidates[decision.index].eid
    result = gate(decision, verb, authorized=authorized)
    confirmation = None
    if confirm and eid and result.act:
        target = candidates[decision.index]
        try:
            confirmation = decider.noul(
                f"Goal: {goal.strip()}\n" + state.to_text(max_elements=40, max_text_lines=10),
                f"To {goal.strip()}, the next step is to {verb} {target.describe()}.",
                question_id="confirm_element",
            )
        except Exception as e:  # a failed check must not turn into "act"
            logger.debug("confirmation failed: %s", e)
        if confirmation is None or confirmation.p_true < confirm_at:
            p_txt = "failed" if confirmation is None else f"p={confirmation.p_true:.2f} < {confirm_at:.2f}"
            result = GateResult(Verdict.ESCALATE, f"confirmation disagrees ({p_txt}): target may not be on screen", result.risk)
    return {
        "generation": state.generation,
        "eid": eid,
        "element": candidates[decision.index].as_dict() if eid else None,
        "decision": decision.as_dict(),
        "gate": result.as_dict(),
        "confirmation": confirmation.as_dict() if confirmation is not None else None,
    }
