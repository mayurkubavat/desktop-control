"""Deterministic Mock & Replay HAL for Headless CI and Cassette Testing.

Allows running full multi-turn agent loops, accessibility tree diffing,
and local OCR assertion verifications in CI environments without requiring
a physical display server, WindowServer, or Xvfb.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image

from vision_mcp.types import WindowInfo, BoundingBox


@dataclass
class ScreenFrameState:
    """Represents a discrete recorded snapshot in a deterministic state cassette."""

    frame_id: str
    ocr_boxes: List[Dict[str, Any]] = field(default_factory=list)
    ax_tree: Dict[str, Any] = field(default_factory=dict)
    ax_diff: Dict[str, Any] = field(default_factory=dict)
    screen_size: Tuple[int, int] = (1920, 1080)
    cursor_pos: Tuple[int, int] = (100, 100)
    windows: List[WindowInfo] = field(default_factory=list)
    active_window: Optional[WindowInfo] = None
    pixel_delta_from_prev: float = 0.0


class MockReplayHAL:
    """
    Cassette-driven Desktop HAL that replays deterministic frames.
    Implements IDesktopHALProtocol and IAXTreeDriver.
    """

    def __init__(self, states: Optional[List[ScreenFrameState]] = None) -> None:
        if not states:
            # Default single initial state
            states = [
                ScreenFrameState(
                    frame_id="init",
                    screen_size=(1920, 1080),
                    cursor_pos=(0, 0),
                    windows=[
                        WindowInfo(
                            window_id="0x1000",
                            title="Mock Terminal",
                            bbox=BoundingBox(x=50, y=50, width=800, height=600),
                            is_active=True,
                        )
                    ],
                    active_window=WindowInfo(
                        window_id="0x1000",
                        title="Mock Terminal",
                        bbox=BoundingBox(x=50, y=50, width=800, height=600),
                        is_active=True,
                    ),
                )
            ]
        self.states: List[ScreenFrameState] = states
        self.cursor: int = 0
        self.actions_dispatched: List[Tuple[str, Dict[str, Any]]] = []
        self._auto_advance: bool = True

    @property
    def current_state(self) -> ScreenFrameState:
        return self.states[self.cursor]

    def set_auto_advance(self, auto_advance: bool) -> None:
        """Enable or disable advancing frame automatically upon action dispatch."""
        self._auto_advance = auto_advance

    def advance_frame(self) -> None:
        """Manually advance to next recorded state frame if available."""
        if self.cursor < len(self.states) - 1:
            self.cursor += 1

    # IScreenCapture Protocol
    def get_screen_size(self) -> Tuple[int, int]:
        return self.current_state.screen_size

    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        w, h = self.current_state.screen_size
        if region:
            _, _, rw, rh = region
            return Image.new("RGB", (rw, rh), color=(30, 30, 30))
        return Image.new("RGB", (w, h), color=(30, 30, 30))

    # IInputDriver Protocol
    def get_cursor_position(self) -> Tuple[int, int]:
        return self.current_state.cursor_pos

    def mouse_move(self, x: int, y: int) -> None:
        self.actions_dispatched.append(("mouse_move", {"x": x, "y": y}))
        self.current_state.cursor_pos = (x, y)
        if self._auto_advance:
            self.advance_frame()

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1) -> None:
        self.actions_dispatched.append(
            ("mouse_click", {"x": x, "y": y, "button": button, "click_count": click_count})
        )
        self.current_state.cursor_pos = (x, y)
        if self._auto_advance:
            self.advance_frame()

    def mouse_drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_sec: float = 0.3
    ) -> None:
        self.actions_dispatched.append(
            (
                "mouse_drag",
                {
                    "start_x": start_x,
                    "start_y": start_y,
                    "end_x": end_x,
                    "end_y": end_y,
                    "duration_sec": duration_sec,
                },
            )
        )
        self.current_state.cursor_pos = (end_x, end_y)
        if self._auto_advance:
            self.advance_frame()

    def mouse_scroll(self, dx: int, dy: int) -> None:
        self.actions_dispatched.append(("mouse_scroll", {"dx": dx, "dy": dy}))
        if self._auto_advance:
            self.advance_frame()

    def keyboard_type(self, text: str, delay_ms: float = 12.0) -> None:
        self.actions_dispatched.append(("keyboard_type", {"text": text, "delay_ms": delay_ms}))
        if self._auto_advance:
            self.advance_frame()

    def keyboard_press_key(self, key_name: str) -> None:
        self.actions_dispatched.append(("keyboard_press_key", {"key_name": key_name}))
        if self._auto_advance:
            self.advance_frame()

    def keyboard_hotkey(self, keys: List[str]) -> None:
        self.actions_dispatched.append(("keyboard_hotkey", {"keys": keys}))
        if self._auto_advance:
            self.advance_frame()

    # IWindowManager Protocol
    def list_windows(self) -> List[WindowInfo]:
        return self.current_state.windows

    def get_active_window(self) -> Optional[WindowInfo]:
        return self.current_state.active_window

    def focus_window(self, window_id: str) -> bool:
        self.actions_dispatched.append(("focus_window", {"window_id": window_id}))
        for win in self.current_state.windows:
            if win.window_id == window_id:
                win.is_active = True
                self.current_state.active_window = win
                return True
        return False

    # IAXTreeDriver Protocol
    def get_accessibility_tree(
        self,
        app_filter: Optional[str] = None,
        max_depth: Optional[int] = None,
        diff_only: bool = False,
    ) -> Dict[str, Any]:
        if diff_only:
            return self.current_state.ax_diff or {"changed": False, "nodes": []}
        return self.current_state.ax_tree or {"role": "AXApplication", "children": []}

    # OCR Query
    def read_screen_text(self, contains: Optional[str] = None) -> Dict[str, Any]:
        """Queries recorded OCR boxes in the active frame."""
        boxes = self.current_state.ocr_boxes
        if contains:
            matched = [
                b for b in boxes if contains.lower() in str(b.get("text", "")).lower()
            ]
            return {"count": len(matched), "lines": matched}
        return {"count": len(boxes), "lines": boxes}

    # Serialization / Cassette loader
    @classmethod
    def load_cassette(cls, path_or_json: str | Path) -> MockReplayHAL:
        """Loads a state cassette from file or JSON string."""
        if isinstance(path_or_json, Path) or (
            isinstance(path_or_json, str) and path_or_json.endswith((".json", ".halpack"))
        ):
            content = Path(path_or_json).read_text(encoding="utf-8")
        else:
            content = path_or_json
        data = json.loads(content)
        frames = []
        for f in data.get("frames", []):
            wins = [WindowInfo(**w) for w in f.get("windows", [])]
            act = WindowInfo(**f["active_window"]) if f.get("active_window") else None
            frames.append(
                ScreenFrameState(
                    frame_id=f.get("frame_id", "f"),
                    ocr_boxes=f.get("ocr_boxes", []),
                    ax_tree=f.get("ax_tree", {}),
                    ax_diff=f.get("ax_diff", {}),
                    screen_size=tuple(f.get("screen_size", (1920, 1080))),
                    cursor_pos=tuple(f.get("cursor_pos", (0, 0))),
                    windows=wins,
                    active_window=act,
                    pixel_delta_from_prev=f.get("pixel_delta_from_prev", 0.0),
                )
            )
        return cls(states=frames)
