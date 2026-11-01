"""Dobby's control menu, opened from the control bar's ▾ (and, when enabled,
the menu bar icon or the name tag's ▾).

Pure data (no AppKit) so it can be tested anywhere; ``mac_helper`` turns the
entries into an NSMenu.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

Entry = Tuple[str, Optional[str], Optional[bool]]  # title, action selector, checkmark
SEPARATOR: Entry = ("-", None, None)


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def status_of(paused: bool, takeover: bool, working: bool, turbo: bool) -> Tuple[str, str]:
    """(status text, one-glyph menu bar title). One glyph fits beside the notch."""
    if paused:
        status, title = "Paused", "‖"
    elif takeover:
        status, title = "You're in control", "✋"
    elif working:
        status, title = "Working", "◆"
    else:
        status, title = "Idle", "◇"
    if turbo:
        status += " (Turbo)"
        title = "⚡" if title in ("◆", "◇") else title
    return status, title


def menu_entries(status: str, steps: Iterable[str], halted: bool, turbo: bool, overlay_on: bool,
                 trail_on: bool, bar_shown: Optional[bool], awake: Optional[bool] = False) -> List[Entry]:
    """Menu items, top to bottom. ``bar_shown`` is None when there is no control bar.

    ``awake`` is None while Dobby works (no wake/sleep entry then).
    """
    out: List[Entry] = [(f"Dobby: {status}", None, None), SEPARATOR]
    if awake is not None:
        out.append(("Put Dobby to sleep", "menuSleep:", None) if awake else ("Wake Dobby", "menuWake:", None))
    out.append(("Recent steps", None, None))
    recent = list(reversed(list(steps)))
    out += [("   " + _short(line, 60), None, None) for line in (recent or ["(none yet)"])]
    out += [SEPARATOR,
            ("Resume" if halted else "Pause", "menuPauseToggle:", None),
            ("Stop", "menuStop:", None),
            SEPARATOR,
            ("Turbo mode (no prompts, ignores take-over)", "menuToggleTurbo:", turbo),
            ("Show overlay", "menuToggleOverlay:", overlay_on)]
    if bar_shown is not None:
        out.append(("Show control bar (⌃⌥H)", "menuTogglePill:", bar_shown))
    out += [("Show step trail", "menuToggleTrail:", trail_on),
            ("Clear step trail", "menuClearTrail:", None)]
    return out


# ---------------------------------------------------------- Dobby picker
# (title, pid, [(item title, action selector)])
PickerGroup = Tuple[str, int, List[Tuple[str, str]]]


def picker_groups(agents: Iterable[dict], own_pid: int, own_paused: bool = False) -> List[PickerGroup]:
    """One submenu per running Dobby, when more than one runs.

    ``agents`` come from ``dobby.control.commands.overview``. Each submenu
    pauses or resumes, or stops, just that Dobby. The last group pauses or
    resumes all of them (pid 0).
    """
    agents = list(agents)
    if len(agents) < 2:
        return []
    groups: List[PickerGroup] = []
    any_running = False
    for a in agents:
        pid = int(a.get("pid", 0))
        paused = bool(a.get("paused")) or (pid == own_pid and own_paused)
        any_running = any_running or not paused
        notes = []
        if pid == own_pid:
            notes.append("this bar")
        if paused:
            notes.append("paused")
        elif a.get("holding"):
            notes.append("in control")
        elif a.get("waiting"):
            notes.append("waiting")
        title = _short(str(a.get("name") or f"Dobby-{pid}"), 28)
        if notes:
            title += "  · " + ", ".join(notes)
        groups.append((title, pid, [("Resume" if paused else "Pause", "menuAgentPauseToggle:"),
                                    ("Stop", "menuAgentStop:")]))
    groups.append(("All Dobbys", 0, [("Pause all", "menuAllPause:"), ("Resume all", "menuAllResume:")]))
    return groups


# ------------------------------------------------------------ control bar
# (mode, text, primary button, secondary button, colour key, dot alpha)
BarView = Tuple[str, str, str, str, str, float]


def bar_view(*, paused: bool, takeover: bool, takeover_resume: str, working: bool, turbo: bool,
             current_mode: str, bar_mode: str, owner: bool, awake: bool = False,
             ai_waiting: bool = False, handoff: bool = False,
             other_waiting: bool = False) -> Optional[BarView]:
    """What the control bar shows, or None to hide it.

    Colour keys: "caution", "ok", or "risk" (the current risk colour).
    ``current_mode`` "stopped" is kept until the helper's timer clears it.
    ``awake``: the user woke Dobby from the bar; any helper shows it.
    ``handoff``: that wake went to an AI waiting in ``wait_for_wake``;
    otherwise no AI was waiting and the bar says so briefly.
    ``ai_waiting``: this helper's AI waits for a wake; any helper shows it, so
    the click reaches the AI that waits. ``other_waiting``: another helper's AI
    waits, so the bar owner hides its plain idle bar instead of stacking on it.
    An Allow/Deny prompt is shown separately and is never hidden.
    """
    if paused:
        return ("paused", "Dobby is paused", "Resume", "Stop", "caution", 1.0)
    if takeover:
        text = "You're in control · Dobby waits until you stop" if takeover_resume == "auto" else "You're in control"
        return ("takeover", text, "Resume now", "Stop", "caution", 1.0)
    if current_mode == "stopped":
        return ("stopped", "Dobby stopped", "OK", "Hide", "danger", 1.0)
    if working:
        label = "Dobby ⚡ Turbo" if turbo else "Dobby is working"
        return ("working", label + " · ⌃⌥⎋ stops", "Pause", "Stop", "risk", 1.0)
    if awake:
        if handoff:
            label = "Dobby ⚡ Turbo · awake · handing back to the AI" if turbo else "Dobby is awake · handing back to the AI"
        else:
            label = "Dobby is awake · no AI is waiting — ask your AI for a task"
        return ("awake", label, "Pause", "Stop", "ok", 1.0)
    if ai_waiting:
        label = "Dobby ⚡ Turbo · sleeping · click to wake" if turbo else "Dobby is sleeping · click to wake"
        return ("ready", label, "Pause", "Stop", "ok", 0.45)
    if bar_mode == "always" and owner and not other_waiting:
        label = "Dobby ⚡ Turbo · sleeping" if turbo else "Dobby is sleeping"
        return ("ready", label, "Pause", "Stop", "ok", 0.45)
    return None


def bar_click(mode: str, which: str) -> str:
    """Action for a click on the bar's "primary" or "secondary" button."""
    if mode == "confirm":
        return "allow" if which == "primary" else "deny"
    if mode == "stopped":
        return "hide" if which == "secondary" else "dismiss"
    if which == "secondary":
        return "stop"
    if mode in ("working", "ready", "awake"):
        return "pause"
    if mode in ("paused", "takeover"):
        return "resume"
    return "none"


def bar_tip(mode: str, ai_waiting: bool = False, reason: str = "") -> Optional[str]:
    """Tooltip for the bar itself (clicking it wakes Dobby or puts it to sleep)."""
    if mode == "ready":
        if not ai_waiting:
            return "Click to wake Dobby"
        tip = "Click to wake Dobby: your AI is waiting for you"
        return tip + (f" ({_short(reason, 80)})" if reason.strip() else "")
    if mode == "awake":
        return "Click to put Dobby to sleep"
    return None


def label_click(mode: str) -> str:
    """Action for a click on the bar itself, away from its buttons."""
    return {"ready": "wake", "awake": "sleep"}.get(mode, "none")
