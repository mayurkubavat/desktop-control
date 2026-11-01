"""Dobby's control menu, shared by the menu bar icon and the name tag's ▾.

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
                 trail_on: bool, bar_shown: Optional[bool]) -> List[Entry]:
    """Menu items, top to bottom. ``bar_shown`` is None when there is no control bar."""
    out: List[Entry] = [(f"Dobby: {status}", None, None), SEPARATOR, ("Recent steps", None, None)]
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


# ------------------------------------------------------------ control bar
# (mode, text, primary button, secondary button, colour key, dot alpha)
BarView = Tuple[str, str, str, str, str, float]


def bar_view(*, paused: bool, takeover: bool, takeover_resume: str, working: bool, turbo: bool,
             current_mode: str, bar_mode: str, owner: bool) -> Optional[BarView]:
    """What the control bar shows, or None to hide it.

    Colour keys: "caution", "ok", or "risk" (the current risk colour).
    ``current_mode`` "stopped" is kept until the helper's timer clears it.
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
    if bar_mode == "always" and owner:
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
    if mode in ("working", "ready"):
        return "pause"
    if mode in ("paused", "takeover"):
        return "resume"
    return "none"
