"""HAL decorator that shows the overlay around real actions.

``OverlayHAL(inner, overlay)`` wraps any Dobby HAL. It forwards every call to
``inner`` and adds overlay side effects:

* mouse actions: the agent pointer glides to the target first (waiting for
  the helper's ack, capped by a timeout), then the real action fires, then a
  click ripple is shown;
* ``keyboard_type``: the pointer shows a typing badge while typing;
* ``focus_window``: the target window gets the glowing border;
* ``capture_screen``: the overlay is hidden for the capture so screenshots,
  OCR and Gemma never see it;
* ``list_windows``: overlay panels are filtered out.

Anything not listed here is forwarded untouched through ``__getattr__``, so
the wrapper keeps working when the HAL grows new methods.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from .client import NullOverlay
from .protocol import OVERLAY_WINDOW_TITLE

ToPoints = Callable[[float, float], Tuple[float, float]]


class OverlayHAL:
    def __init__(self, inner: Any, overlay: Optional[NullOverlay] = None,
                 to_points: Optional[ToPoints] = None) -> None:
        self._inner = inner
        self.overlay = overlay or NullOverlay()
        # HAL coordinates -> global points. Identity when the HAL already
        # works in points (Quartz events do); pass a converter otherwise.
        self._to_points: ToPoints = to_points or (lambda x, y: (x, y))
        self._tracked: Optional[str] = None

    @property
    def inner(self) -> Any:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    # ------------------------------------------------------------- helpers
    def _follow_active_window(self) -> None:
        """Move the glow to whatever window is active after an action."""
        getter = getattr(self._inner, "get_active_window", None)
        if getter is None:
            return
        try:
            win = getter()
        except Exception:  # noqa: BLE001 - glow is cosmetic
            return
        wid = getattr(win, "window_id", None) if win is not None else None
        if wid is not None and str(wid) != self._tracked:
            self._tracked = str(wid)
            self.overlay.track(window_id=wid)

    def _point_to(self, x: float, y: float, ms: Optional[int] = None, wait: bool = True) -> None:
        px, py = self._to_points(x, y)
        self.overlay.move(px, py, ms=ms, wait=wait)

    # --------------------------------------------------------------- mouse
    def mouse_move(self, x: int, y: int, *args: Any, **kwargs: Any) -> Any:
        self._point_to(x, y)
        return self._inner.mouse_move(x, y, *args, **kwargs)

    def mouse_click(self, x: int, y: int, button: str = "left", click_count: int = 1,
                    *args: Any, **kwargs: Any) -> Any:
        self._point_to(x, y)
        result = self._inner.mouse_click(x, y, button, click_count, *args, **kwargs)
        self.overlay.click(button=button, count=click_count)
        self._follow_active_window()
        return result

    def mouse_drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
                   duration_sec: float = 0.3, *args: Any, **kwargs: Any) -> Any:
        self._point_to(start_x, start_y)
        # Follow the drag in parallel with the real one.
        self._point_to(end_x, end_y, ms=int(duration_sec * 1000), wait=False)
        return self._inner.mouse_drag(start_x, start_y, end_x, end_y, duration_sec, *args, **kwargs)

    # ------------------------------------------------------------ keyboard
    def keyboard_type(self, text: str, *args: Any, **kwargs: Any) -> Any:
        self.overlay.state("typing")
        try:
            return self._inner.keyboard_type(text, *args, **kwargs)
        finally:
            self.overlay.state("idle")

    # ------------------------------------------------------------- windows
    def focus_window(self, window_id: str, *args: Any, **kwargs: Any) -> Any:
        ok = self._inner.focus_window(window_id, *args, **kwargs)
        if ok:
            self._tracked = str(window_id)
            self.overlay.track(window_id=window_id)
        return ok

    def list_windows(self, *args: Any, **kwargs: Any) -> List[Any]:
        windows = self._inner.list_windows(*args, **kwargs)
        # MacHAL already keeps only layer-0 windows (the overlay sits far above),
        # so this is a second line of defence for other HALs.
        return [w for w in windows if not str(getattr(w, "title", "") or "").startswith(OVERLAY_WINDOW_TITLE)]

    # ------------------------------------------------------------- capture
    def capture_screen(self, *args: Any, **kwargs: Any) -> Any:
        if not self.overlay.active:
            return self._inner.capture_screen(*args, **kwargs)
        self.overlay.hide()
        try:
            return self._inner.capture_screen(*args, **kwargs)
        finally:
            self.overlay.show()


def unwrap(hal: Any) -> Any:
    """Return the innermost HAL (for isinstance checks against concrete HALs)."""
    while isinstance(hal, OverlayHAL):
        hal = hal.inner
    return hal
