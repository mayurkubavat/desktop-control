"""AT-SPI2 Linux Accessibility Tree Inspector."""

from typing import List, Optional, Set
from vision_mcp.types import UIElement, BoundingBox
from vision_mcp.config import CONFIG

INTERACTABLE_ROLES: Set[str] = {
    "push button",
    "button",
    "toggle button",
    "check box",
    "radio button",
    "menu item",
    "check menu item",
    "radio menu item",
    "entry",
    "text",
    "password text",
    "combo box",
    "list item",
    "tab",
    "page tab",
    "slider",
    "spin button",
    "link",
    "tree table",
    "tree",
    "icon",
    "table cell",
    "terminal",
}


class ATSPIInspector:
    """Queries Linux D-Bus AT-SPI2 registry to extract semantic UI components and bounding boxes."""

    def __init__(self) -> None:
        self._available = False
        self._atspi = None
        self._coord_type = None

        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
            self._atspi = Atspi
            self._coord_type = Atspi.CoordType.SCREEN
            self._available = True
        except Exception:
            self._available = False

    @property
    def is_available(self) -> bool:
        """Returns True if PyGObject Atspi is present and functional."""
        return self._available

    def inspect_desktop(
        self,
        app_name_filter: Optional[str] = None,
        max_depth: int = 16,
        filter_interactable: bool = True,
    ) -> List[UIElement]:
        """
        Traverses the AT-SPI desktop hierarchy and returns flattened list of UI elements.

        Args:
            app_name_filter: Optional substring to filter matching application names or window titles.
            max_depth: Maximum recursion depth.
            filter_interactable: If True, only returns clickable or typable elements.

        Returns:
            List of UIElement models with true screen bounding boxes.
        """
        if not self._available or not self._atspi:
            return []

        elements: List[UIElement] = []

        try:
            desktop = self._atspi.get_desktop(0)
            app_count = desktop.get_child_count()

            for i in range(app_count):
                app = desktop.get_child_at_index(i)
                if not app:
                    continue

                app_name = app.get_name() or ""
                
                # Check if app matches filter or has matching window
                matched = True
                if app_name_filter:
                    matched = app_name_filter.lower() in app_name.lower()
                    if not matched:
                        # Check window titles
                        for w_idx in range(app.get_child_count()):
                            w_child = app.get_child_at_index(w_idx)
                            if w_child and app_name_filter.lower() in (w_child.get_name() or "").lower():
                                matched = True
                                break

                if not matched:
                    continue

                # Traverse top-level frames/windows
                for w_idx in range(app.get_child_count()):
                    win_node = app.get_child_at_index(w_idx)
                    if not win_node:
                        continue

                    # Obtain window screen extents for offset fallback
                    win_x, win_y = 0, 0
                    win_comp = win_node.get_component_iface()
                    if win_comp:
                        w_ext = win_comp.get_extents(self._coord_type)
                        win_x, win_y = w_ext.x, w_ext.y

                    # If AT-SPI reports window top-level at 0,0, cross-reference X11 window position
                    if win_x == 0 and win_y == 0:
                        try:
                            from vision_mcp.hal.factory import get_desktop_hal
                            hal_wins = get_desktop_hal().list_windows()
                            w_title = (win_node.get_name() or "").lower()
                            for hw in hal_wins:
                                if w_title and (w_title in hw.title.lower() or hw.title.lower() in w_title):
                                    win_x, win_y = hw.bbox.x, hw.bbox.y
                                    break
                        except Exception:
                            pass

                    self._traverse_node(
                        node=win_node,
                        depth=1,
                        max_depth=max_depth,
                        filter_interactable=filter_interactable,
                        elements=elements,
                        win_offset=(win_x, win_y),
                    )

                if len(elements) >= CONFIG.som_max_elements:
                    break

        except Exception:
            pass

        return elements[:CONFIG.som_max_elements]

    def inspect(self) -> List[UIElement]:
        """All elements, interactable or not (used by post-condition checks)."""
        return self.inspect_desktop(filter_interactable=False)

    def _traverse_node(
        self,
        node,
        depth: int,
        max_depth: int,
        filter_interactable: bool,
        elements: List[UIElement],
        win_offset: tuple[int, int] = (0, 0),
    ) -> None:
        if depth > max_depth or len(elements) >= CONFIG.som_max_elements:
            return

        try:
            role = node.get_role_name() or "unknown"
            name = node.get_name() or ""
            is_interactable = role.lower() in INTERACTABLE_ROLES

            # Extract screen extents
            comp = node.get_component_iface()
            if comp:
                rect = comp.get_extents(self._coord_type)
                w, h = rect.width, rect.height
                x, y = rect.x, rect.y

                # If screen coordinates are 0,0 and we have a window offset, try WINDOW coordinates
                if x == 0 and y == 0 and (win_offset[0] != 0 or win_offset[1] != 0):
                    w_rect = comp.get_extents(self._atspi.CoordType.WINDOW)
                    x = win_offset[0] + w_rect.x
                    y = win_offset[1] + w_rect.y

                # Check validity of geometry (skip collapsed dropdown items)
                area = w * h
                is_collapsed_menu = (role.lower() == "menu item" and h <= 14)
                if w > 8 and h > 8 and area >= CONFIG.som_min_element_area and not is_collapsed_menu:
                    # Filter condition
                    if not filter_interactable or is_interactable:
                        element = UIElement(
                            id=len(elements) + 1,
                            role=role,
                            name=name.strip(),
                            bbox=BoundingBox(x=x, y=y, width=w, height=h),
                            interactable=is_interactable,
                        )
                        elements.append(element)

            # Recurse children
            child_count = node.get_child_count()
            for c in range(child_count):
                child = node.get_child_at_index(c)
                if child:
                    self._traverse_node(
                        node=child,
                        depth=depth + 1,
                        max_depth=max_depth,
                        filter_interactable=filter_interactable,
                        elements=elements,
                        win_offset=win_offset,
                    )
        except Exception:
            return
