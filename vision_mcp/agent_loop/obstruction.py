"""Autonomous Obstruction and Modal Dialog Interceptor.

Detects and automatically dismisses blocking popups, permission dialogs
(e.g. Chrome 'Show notifications'), cookie banners, and modal overlays
to prevent multi-step agent trajectories from hanging.
"""

import time
from typing import Optional, Dict, Any, List
from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.perception.atspi import ATSPIInspector
from vision_mcp.types import UIElement


DISMISS_BUTTON_KEYWORDS = [
    "block",
    "dismiss",
    "not now",
    "close",
    "got it",
    "cancel",
    "reject",
    "decline",
    "maybe later",
    "no thanks",
    "x",
]

OBSTRUCTION_ROLES = {
    "dialog",
    "alert",
    "notification",
    "popup menu",
}


class ObstructionInterceptor:
    """
    Monitors for and automatically dismisses blocking modal dialogs and overlays.
    """

    def __init__(self, hal: IDesktopHAL, atspi_inspector: Optional[ATSPIInspector] = None) -> None:
        self.hal = hal
        self.atspi = atspi_inspector or ATSPIInspector()

    def find_obstructions(self) -> List[UIElement]:
        """
        Scans for active dialogs, permission requests, or popup overlays.
        """
        if not self.atspi.is_available:
            return []

        elements = self.atspi.inspect_desktop(filter_interactable=True)
        dismiss_candidates: List[UIElement] = []

        for elem in elements:
            name_lower = (elem.name or "").lower().strip()
            role_lower = (elem.role or "").lower().strip()

            # Check if this element is an explicit dismissal button
            if elem.interactable and any(kw == name_lower or f" {kw} " in f" {name_lower} " for kw in DISMISS_BUTTON_KEYWORDS):
                dismiss_candidates.append(elem)

        return dismiss_candidates

    def dismiss_if_present(self, max_attempts: int = 2) -> Dict[str, Any]:
        """
        Checks for blocking dialogs and dismisses them automatically.

        Returns:
            Dict detailing whether an obstruction was cleared, the action taken, and delta.
        """
        cleared_items: List[str] = []

        for attempt in range(max_attempts):
            candidates = self.find_obstructions()
            if not candidates:
                break

            # Target the best dismissal button
            target = candidates[0]
            action_desc = f"Clicked dismissal button '{target.name}' at {target.bbox.center}"
            cx, cy = target.bbox.center
            self.hal.mouse_click(cx, cy, button="left", click_count=1)
            time.sleep(0.3)
            cleared_items.append(action_desc)

        # If obstructions were still found or AT-SPI wasn't available, check if escape helps
        return {
            "obstruction_cleared": len(cleared_items) > 0,
            "actions_taken": cleared_items,
            "attempts": len(cleared_items),
        }

    def dismiss_with_escape(self) -> bool:
        """Fallback non-destructive escape key dismissal."""
        self.hal.keyboard_press_key("escape")
        time.sleep(0.2)
        return True
