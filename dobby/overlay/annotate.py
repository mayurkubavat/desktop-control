"""Annotated replays: draw the overlay back onto recorded screenshots.

Dobby's own screenshots never contain the overlay (it hides for captures).
The overlay client writes a *track* (``~/.dobby/overlay/tracks/*.jsonl``):
every overlay message with a wall-clock ``ts``. This module rebuilds the
overlay state at any moment from a track and draws it onto screenshots with
Pillow, so a session can be turned into a shareable GIF or PNG sequence.

Live replay on the real screen is ``python -m dobby.overlay --replay TRACK``.

CLI::

    python -m dobby.overlay.annotate --track T.jsonl --frames DIR --out run.gif

Frames are images in DIR whose file name contains a Unix timestamp (seconds,
e.g. ``1793560162.25.png``, or milliseconds, ``1793560162250.png``); files
without one use their modification time. ``--scale`` maps points to image
pixels (2 for raw Retina captures; Dobby's own captures are already points).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

Rect = Tuple[float, float, float, float]
Point = Tuple[float, float]

COLORS = {"ok": (124, 92, 255), "caution": (245, 165, 36), "danger": (240, 68, 56)}
INTENT_MS = 1600
TRAIL_LEN = 5

_ARROW = [(0, 0), (0, 18), (4.5, 14), (8, 21.5), (10.5, 20.5), (7, 13), (13, 13)]


@dataclass
class TrackState:
    cursor: Optional[Point] = None
    intent: str = ""
    intent_until: float = 0.0
    box: Optional[Rect] = None
    box_until: float = float("inf")
    risk: str = "ok"
    state: str = "idle"
    trail: List[Tuple[int, Point]] = field(default_factory=list)
    steps: int = 0
    scan_until: float = 0.0
    scan_rect: Optional[Rect] = None


def load_track(path: os.PathLike) -> List[Dict[str, Any]]:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and "ts" in msg and "op" in msg:
                out.append(msg)
    out.sort(key=lambda m: float(m["ts"]))
    return out


def state_at(events: Sequence[Dict[str, Any]], t: float) -> TrackState:
    """Overlay state after replaying every event with ``ts <= t``."""
    s = TrackState()
    for e in events:
        ts = float(e["ts"])
        if ts > t:
            break
        op = e.get("op")
        if op == "cursor.move":
            s.cursor = (float(e["x"]), float(e["y"]))
            if e.get("verb") and e.get("verb") != "Move":
                s.steps += 1
                s.intent, s.intent_until = e["verb"], ts + INTENT_MS / 1000.0
            if not e.get("probe"):
                s.box = None
            if s.state == "thinking":
                s.state = "idle"
        elif op == "cursor.click":
            if s.cursor is not None:
                s.trail = (s.trail + [(s.steps or len(s.trail) + 1, s.cursor)])[-TRAIL_LEN:]
            s.box_until = ts + 0.5
        elif op == "cursor.state":
            s.state = e.get("state", "idle")
        elif op == "intent":
            text = e.get("text", "")
            ms = e.get("ms", INTENT_MS)
            s.intent, s.intent_until = text, ts + float(ms) / 1000.0
            if text:
                s.steps += 1
        elif op == "target.box":
            s.box, s.box_until = (float(e["x"]), float(e["y"]), float(e["w"]), float(e["h"])), float("inf")
        elif op == "target.clear":
            s.box = None
        elif op == "risk":
            s.risk = e.get("level", "ok")
        elif op == "scan":
            s.scan_until = ts + 0.9
            s.scan_rect = (float(e["x"]), float(e["y"]), float(e["w"]), float(e["h"])) if "x" in e else None
        elif op == "trail.clear":
            s.trail = []
        elif op == "cursor.hide":
            s.cursor = None
    if s.intent and t >= s.intent_until:
        s.intent = ""
    if s.box is not None and t >= s.box_until:
        s.box = None
    return s


def _font(size: int):
    for name in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate(img: Image.Image, s: TrackState, scale: float = 1.0, origin: Point = (0.0, 0.0),
             label: str = "Dobby", glow_rect: Optional[Rect] = None, t: Optional[float] = None) -> Image.Image:
    """Return a copy of ``img`` with the overlay drawn as it looked in state ``s``."""
    out = img.convert("RGBA")
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    color = COLORS.get(s.risk, COLORS["ok"])

    def P(x: float, y: float) -> Tuple[float, float]:
        return ((x - origin[0]) * scale, (y - origin[1]) * scale)

    def R(r: Rect, pad: float = 0.0) -> List[float]:
        x0, y0 = P(r[0] - pad, r[1] - pad)
        x1, y1 = P(r[0] + r[2] + pad, r[1] + r[3] + pad)
        return [x0, y0, x1, y1]

    if glow_rect is not None:
        for i, a in enumerate((60, 35, 18)):
            d.rounded_rectangle(R(glow_rect, 2 + 3 * i), radius=11 * scale, outline=color + (a,), width=int(3 * scale))
        d.rounded_rectangle(R(glow_rect, 1.5), radius=11 * scale, outline=color + (240,), width=max(1, int(3 * scale)))
    if s.box is not None:
        d.rounded_rectangle(R(s.box, 3), radius=6 * scale, outline=color + (255,), width=max(1, int(2 * scale)),
                            fill=color + (20,))
    small = _font(int(10 * scale))
    n = len(s.trail)
    for idx, (num, pt) in enumerate(s.trail):
        alpha = int(255 * max(0.2, 0.85 - 0.17 * (n - 1 - idx)))
        cx, cy = P(*pt)
        rad = 9 * scale
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=COLORS["ok"] + (alpha,))
        d.text((cx, cy), str(num), font=small, fill=(255, 255, 255, alpha), anchor="mm")
    if s.cursor is not None:
        tx, ty = P(*s.cursor)
        k = 1.25 * scale
        poly = [(tx + x * k, ty + y * k) for x, y in _ARROW]
        d.polygon(poly, fill=color + (255,), outline=(255, 255, 255, 255))
        badge = {"thinking": " •••", "typing": " ⌨", "waiting_user": " ✋"}.get(s.state, "")
        text = s.intent or (label + badge)
        font = _font(int(11 * scale))
        left = tx + 14 * scale
        top = ty + 22 * scale
        bbox = d.textbbox((left + 7 * scale, top + 2 * scale), text, font=font)
        d.rounded_rectangle([left, top, bbox[2] + 7 * scale, top + 17 * scale], radius=5 * scale, fill=color + (255,))
        d.text((left + 7 * scale, top + 2 * scale), text, font=font, fill=(255, 255, 255, 255))
    return Image.alpha_composite(out, layer).convert("RGB")


_TS = re.compile(r"(\d{13}|\d{10}(?:\.\d+)?)")


def frame_time(path: Path) -> float:
    m = _TS.search(path.stem)
    if m:
        v = float(m.group(1))
        return v / 1000.0 if len(m.group(1)) == 13 else v
    return path.stat().st_mtime


def find_frames(folder: os.PathLike) -> List[Tuple[float, Path]]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    frames = [(frame_time(p), p) for p in Path(folder).iterdir() if p.suffix.lower() in exts]
    frames.sort(key=lambda f: f[0])
    return frames


def render(frames: Iterable[Tuple[float, Any]], events: Sequence[Dict[str, Any]], out: os.PathLike,
           scale: float = 1.0, origin: Point = (0.0, 0.0), frame_ms: int = 600) -> List[Path]:
    """Annotate each (ts, image or path) frame. ``out`` ending in .gif makes a GIF,
    otherwise ``out`` is a folder of numbered PNGs. Returns the files written."""
    images = []
    for ts, src in frames:
        img = src if isinstance(src, Image.Image) else Image.open(src)
        images.append(annotate(img, state_at(events, ts), scale=scale, origin=origin))
    out = Path(out)
    if not images:
        return []
    if out.suffix.lower() == ".gif":
        out.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(out, save_all=True, append_images=images[1:], duration=frame_ms, loop=0)
        return [out]
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, im in enumerate(images):
        p = out / f"frame_{i:04d}.png"
        im.save(p)
        written.append(p)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Draw the Dobby overlay onto recorded screenshots.")
    ap.add_argument("--track", required=True, help="overlay track .jsonl")
    ap.add_argument("--frames", required=True, help="folder of timestamped screenshots")
    ap.add_argument("--out", required=True, help="output .gif, or a folder for PNGs")
    ap.add_argument("--scale", type=float, default=1.0, help="image pixels per point")
    ap.add_argument("--frame-ms", type=int, default=600)
    args = ap.parse_args(argv)
    events = load_track(args.track)
    frames = find_frames(args.frames)
    if not frames:
        print(f"no frames in {args.frames}", file=sys.stderr)
        return 1
    written = render(frames, events, args.out, scale=args.scale, frame_ms=args.frame_ms)
    print("\n".join(str(p) for p in written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
