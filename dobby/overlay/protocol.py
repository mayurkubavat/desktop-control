"""Wire protocol between the Dobby server and the overlay helper.

One JSON object per line on the helper's stdin. Each message has an ``op``
and may carry an ``id``; the helper answers messages that carry an ``id``
with ``{"ack": <id>, "ok": true}`` (or ``"ok": false, "error": "..."``) on
stdout. On start the helper prints ``{"ready": true, "version": N}``.

Coordinates are global screen points with a top-left origin on the primary
display (the Quartz / Accessibility convention), not screenshot pixels.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

PROTOCOL_VERSION = 1

#: Name given to every overlay panel, so window listings can filter them out.
OVERLAY_WINDOW_TITLE = "Dobby Overlay"

CURSOR_STATES = ("idle", "thinking", "typing", "waiting_user")

# op -> (required fields, optional fields)
OPS: Dict[str, tuple] = {
    "cursor.move": (("x", "y"), ("ms",)),
    "cursor.click": ((), ("button", "count")),
    "cursor.state": (("state",), ()),
    "cursor.hide": ((), ()),
    "glow.track": ((), ("window_id", "pid")),
    "glow.clear": ((), ()),
    "hide": ((), ()),
    "show": ((), ()),
    "ping": ((), ()),
    "bye": ((), ()),
}


class ProtocolError(ValueError):
    pass


def validate(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Check a message against :data:`OPS`; return it unchanged or raise."""
    if not isinstance(msg, dict):
        raise ProtocolError("message must be an object")
    op = msg.get("op")
    if op not in OPS:
        raise ProtocolError(f"unknown op: {op!r}")
    required, optional = OPS[op]
    allowed = set(required) | set(optional) | {"op", "id"}
    missing = [k for k in required if k not in msg]
    if missing:
        raise ProtocolError(f"{op}: missing {', '.join(missing)}")
    extra = sorted(set(msg) - allowed)
    if extra:
        raise ProtocolError(f"{op}: unexpected {', '.join(extra)}")
    for k in ("x", "y", "ms"):
        if k in msg and not isinstance(msg[k], (int, float)):
            raise ProtocolError(f"{op}: {k} must be a number")
    if op == "cursor.state" and msg["state"] not in CURSOR_STATES:
        raise ProtocolError(f"cursor.state: unknown state {msg['state']!r}")
    if op == "glow.track" and msg.get("window_id") is None and msg.get("pid") is None:
        raise ProtocolError("glow.track: needs window_id or pid")
    return msg


def encode(op: str, msg_id: Optional[int] = None, **fields: Any) -> str:
    msg: Dict[str, Any] = {"op": op}
    msg.update({k: v for k, v in fields.items() if v is not None})
    if msg_id is not None:
        msg["id"] = msg_id
    validate(msg)
    return json.dumps(msg, separators=(",", ":")) + "\n"


def decode(line: str) -> Dict[str, Any]:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"bad json: {exc}") from exc
    return validate(msg)


def ack(msg_id: Any, ok: bool = True, error: Optional[str] = None) -> str:
    out: Dict[str, Any] = {"ack": msg_id, "ok": ok}
    if error:
        out["error"] = error
    return json.dumps(out, separators=(",", ":")) + "\n"


def window_id_int(window_id: Any) -> Optional[int]:
    """Window ids arrive as int, decimal string or hex string ("0x1a2")."""
    if window_id is None:
        return None
    if isinstance(window_id, int):
        return window_id
    s = str(window_id).strip()
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(s)
    except ValueError:
        return None
