"""Agent cursor and window glow overlay for Dobby (macOS).

Usage from the server or HAL factory::

    from dobby.overlay import wrap_hal
    hal = wrap_hal(hal)          # no-op unless the overlay is enabled

Enable/disable with ``DOBBY_OVERLAY=1|0``. Default: on for macOS, off under
pytest, in cassette replay (``DOBBY_REPLAY=1``) and on other platforms.
Look settings come from ``DOBBY_OVERLAY_COLOR`` (hex), ``DOBBY_OVERLAY_SPEED``
(1.0 normal, 0 = no animation) and ``DOBBY_OVERLAY_LABEL``.
``DOBBY_OVERLAY_CAPTURE_VISIBLE=0`` hides the overlay from screen recordings
too (default: recordings and screen shares show it).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .client import NullOverlay, OverlayClient
from .hal import OverlayHAL, unwrap
from .protocol import OVERLAY_WINDOW_TITLE, PROTOCOL_VERSION

__all__ = [
    "NullOverlay", "OverlayClient", "OverlayHAL", "unwrap", "make_overlay",
    "wrap_hal", "overlay_enabled", "OVERLAY_WINDOW_TITLE", "PROTOCOL_VERSION",
]

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def overlay_enabled(env: Optional[Dict[str, str]] = None, platform: str = sys.platform) -> bool:
    env = os.environ if env is None else env
    flag = env.get("DOBBY_OVERLAY", "").strip().lower()
    if flag in _FALSE:
        return False
    if platform != "darwin":
        return False
    if flag in _TRUE:
        return True
    if "PYTEST_CURRENT_TEST" in env or env.get("DOBBY_REPLAY", "").lower() in _TRUE:
        return False
    return True


def overlay_config(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ if env is None else env
    cfg: Dict[str, Any] = {}
    if env.get("DOBBY_OVERLAY_COLOR"):
        cfg["color"] = env["DOBBY_OVERLAY_COLOR"]
    if env.get("DOBBY_OVERLAY_LABEL"):
        cfg["label"] = env["DOBBY_OVERLAY_LABEL"]
    if env.get("DOBBY_OVERLAY_CAPTURE_VISIBLE", "").strip().lower() in _FALSE:
        cfg["capture_visible"] = False
    if env.get("DOBBY_OVERLAY_SPEED"):
        try:
            cfg["speed"] = float(env["DOBBY_OVERLAY_SPEED"])
        except ValueError:
            pass
    return cfg


def make_overlay(enabled: Optional[bool] = None) -> NullOverlay:
    if enabled is None:
        enabled = overlay_enabled()
    if not enabled:
        return NullOverlay()
    log_path = Path(os.path.expanduser("~/.dobby/logs/overlay.log"))
    return OverlayClient(config=overlay_config(), log_path=log_path)


def wrap_hal(hal: Any, overlay: Optional[NullOverlay] = None, **kwargs: Any) -> Any:
    """Wrap ``hal`` in :class:`OverlayHAL` when the overlay is enabled."""
    if isinstance(hal, OverlayHAL):
        return hal
    overlay = overlay if overlay is not None else make_overlay()
    if isinstance(overlay, OverlayClient) or overlay.__class__ is not NullOverlay:
        return OverlayHAL(hal, overlay, **kwargs)
    return hal
