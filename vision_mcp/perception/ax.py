"""
macOS Accessibility (AXUIElement) inspector with the same interface as
``ATSPIInspector`` (``is_available``, ``inspect_desktop``, ``inspect``).

Roles are mapped to the AT-SPI role names the rest of the code already
understands ("push button", "entry", "dialog", "label", ...), so modal triage,
vDOM fusion and Set-of-Marks work unchanged.

Pruning follows the token-efficiency research: skip nodes under 4 points,
skip nodes entirely off-screen, and cap each walk by node count and time.
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional, Tuple

from vision_mcp.config import CONFIG
from vision_mcp.perception.atspi import INTERACTABLE_ROLES
from vision_mcp.types import BoundingBox, UIElement

logger = logging.getLogger(__name__)

AX_ROLE_MAP = {
    "AXButton": "push button",
    "AXMenuButton": "push button",
    "AXCheckBox": "check box",
    "AXRadioButton": "radio button",
    "AXDisclosureTriangle": "toggle button",
    "AXMenuItem": "menu item",
    "AXMenuBarItem": "menu item",
    "AXTextField": "entry",
    "AXSearchField": "entry",
    "AXSecureTextField": "password text",
    "AXTextArea": "text",
    "AXComboBox": "combo box",
    "AXPopUpButton": "combo box",
    "AXLink": "link",
    "AXSlider": "slider",
    "AXIncrementor": "spin button",
    "AXRow": "list item",
    "AXCell": "table cell",
    "AXOutline": "tree",
    "AXTable": "tree table",
    "AXStaticText": "label",
    "AXImage": "image",
    "AXWindow": "frame",
    "AXSheet": "dialog",
    "AXGroup": "panel",
    "AXSplitGroup": "panel",
    "AXScrollArea": "scroll pane",
    "AXToolbar": "tool bar",
    "AXTabGroup": "page tab list",
    "AXList": "list",
}

DIALOG_SUBROLES = {"AXDialog", "AXSystemDialog", "AXFloatingWindow"}


class AXInspector:
    """Walks the AX tree of the frontmost app (or apps matching a filter)."""

    def __init__(
        self,
        ax: Any = None,
        appkit: Any = None,
        max_nodes: int = 4000,
        max_seconds: float = 0.6,
        screen_bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        self.screen_bounds = screen_bounds
        self.max_nodes = max_nodes
        self.max_seconds = max_seconds
        self._ax = ax
        self._appkit = appkit
        self.error: Optional[str] = None
        if self._ax is None:
            try:
                import ApplicationServices  # type: ignore

                self._ax = ApplicationServices
            except Exception as e:
                self.error = f"{type(e).__name__}: {e} (pip install pyobjc-framework-ApplicationServices)"
        if self._appkit is None and self._ax is not None:
            try:
                import AppKit  # type: ignore

                self._appkit = AppKit
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"

    @property
    def is_available(self) -> bool:
        if self._ax is None or self._appkit is None:
            return False
        try:
            trusted = bool(self._ax.AXIsProcessTrusted())
        except Exception:
            trusted = False
        if not trusted:
            self.error = "Accessibility permission not granted to this process (System Settings > Privacy & Security > Accessibility)"
        return trusted

    # -------------------------------------------------------------- AX access

    def _attr(self, el, name: str):
        try:
            err, value = self._ax.AXUIElementCopyAttributeValue(el, name, None)
        except Exception:
            return None
        return value if err == 0 else None

    def _frame(self, el) -> Optional[Tuple[int, int, int, int]]:
        pos, size = self._attr(el, "AXPosition"), self._attr(el, "AXSize")
        if pos is None or size is None:
            return None
        try:
            ok1, p = self._ax.AXValueGetValue(pos, self._ax.kAXValueCGPointType, None)
            ok2, s = self._ax.AXValueGetValue(size, self._ax.kAXValueCGSizeType, None)
        except Exception:
            return None
        if not (ok1 and ok2):
            return None
        return int(p.x), int(p.y), int(s.width), int(s.height)

    def _apps(self, app_name_filter: Optional[str]):
        ws = self._appkit.NSWorkspace.sharedWorkspace()
        if not app_name_filter:
            front = ws.frontmostApplication()
            return [front] if front is not None else []
        needle = app_name_filter.lower()
        return [
            a for a in ws.runningApplications()
            if a.activationPolicy() == 0 and needle in str(a.localizedName() or "").lower()
        ]

    # ------------------------------------------------------------------ public

    def inspect_desktop(
        self,
        app_name_filter: Optional[str] = None,
        max_depth: int = 16,
        filter_interactable: bool = True,
    ) -> List[UIElement]:
        if not self.is_available:
            return []
        screen = self.screen_bounds
        if screen is None:
            screen = self._main_screen()

        elements: List[UIElement] = []
        deadline = time.monotonic() + self.max_seconds
        budget = [self.max_nodes]
        for app in self._apps(app_name_filter):
            root = self._ax.AXUIElementCreateApplication(int(app.processIdentifier()))
            for win in self._attr(root, "AXWindows") or []:
                self._walk(win, 1, max_depth, filter_interactable, elements, deadline, budget, screen, parent_role="")
                if len(elements) >= CONFIG.som_max_elements or time.monotonic() > deadline:
                    break
        return elements[: CONFIG.som_max_elements]

    @staticmethod
    def _main_screen() -> Optional[Tuple[int, int, int, int]]:
        try:
            import Quartz  # type: ignore

            b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            return (int(b.origin.x), int(b.origin.y), int(b.size.width), int(b.size.height))
        except Exception:
            return None

    def inspect(self) -> List[UIElement]:
        """All elements (not just interactable) of the frontmost app."""
        return self.inspect_desktop(filter_interactable=False)

    def _walk(self, el, depth, max_depth, filter_interactable, out, deadline, budget, screen, parent_role) -> None:
        if depth > max_depth or budget[0] <= 0 or time.monotonic() > deadline or len(out) >= CONFIG.som_max_elements:
            return
        budget[0] -= 1
        ax_role = str(self._attr(el, "AXRole") or "")
        subrole = str(self._attr(el, "AXSubrole") or "")
        role = AX_ROLE_MAP.get(ax_role, ax_role.replace("AX", "").lower() or "unknown")
        if ax_role == "AXWindow" and subrole in DIALOG_SUBROLES:
            role = "dialog"
        if ax_role == "AXRadioButton" and parent_role == "AXTabGroup":
            role = "page tab"

        frame = self._frame(el)
        visible = True
        if frame is not None:
            x, y, w, h = frame
            if screen is not None:
                sx, sy, sw, sh = screen
                visible = x + w > sx and y + h > sy and x < sx + sw and y < sy + sh
            if w >= 4 and h >= 4 and visible:
                interactable = role in INTERACTABLE_ROLES
                if not filter_interactable or interactable or role == "dialog":
                    name = ""
                    for attr in ("AXTitle", "AXDescription", "AXValue", "AXPlaceholderValue", "AXHelp"):
                        v = self._attr(el, attr)
                        if isinstance(v, str) and v.strip():
                            name = v.strip()[:200]
                            break
                    states = []
                    if self._attr(el, "AXFocused"):
                        states.append("focused")
                    enabled = self._attr(el, "AXEnabled")
                    states.append("disabled" if enabled is False else "enabled")
                    if self._attr(el, "AXSelected"):
                        states.append("selected")
                    out.append(
                        UIElement(
                            id=len(out) + 1,
                            role=role,
                            name=name,
                            bbox=BoundingBox(x=x, y=y, width=w, height=h),
                            interactable=interactable,
                            states=states,
                        )
                    )
        if not visible:
            return  # off-screen subtree
        for child in self._attr(el, "AXChildren") or []:
            self._walk(child, depth + 1, max_depth, filter_interactable, out, deadline, budget, screen, ax_role)


def get_accessibility_inspector():
    """AXInspector on macOS, ATSPIInspector elsewhere."""
    import sys

    if sys.platform == "darwin":
        return AXInspector()
    from vision_mcp.perception.atspi import ATSPIInspector

    return ATSPIInspector()
