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
        max_depth: int = 6,
        filter_interactable: bool = True,
    ) -> List[UIElement]:
        """
        Traverses the AT-SPI desktop hierarchy and returns flattened list of UI elements.

        Args:
            app_name_filter: Optional substring to filter matching application names.
            max_depth: Maximum recursion depth.
            filter_interactable: If True, only returns clickable or typable elements.

        Returns:
            List of UIElement models with true screen bounding boxes.
        """
        if not self._available or not self._atspi:
            return []

        elements: List[UIElement] = []
        element_id = 1

        try:
            desktop = self._atspi.get_desktop(0)
            app_count = desktop.get_child_count()

            for i in range(app_count):
                app = desktop.get_child_at_index(i)
                if not app:
                    continue

                app_name = app.get_name() or ""
                if app_name_filter and app_name_filter.lower() not in app_name.lower():
                    continue

                self._traverse_node(
                    node=app,
                    depth=1,
                    max_depth=max_depth,
                    filter_interactable=filter_interactable,
                    elements=elements,
                    start_id=element_id,
                )
                element_id = len(elements) + 1

                if len(elements) >= CONFIG.som_max_elements:
                    break

        except Exception:
            pass

        return elements[:CONFIG.som_max_elements]

    def _traverse_node(
        self,
        node,
        depth: int,
        max_depth: int,
        filter_interactable: bool,
        elements: List[UIElement],
        start_id: int,
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

                # Check validity of geometry
                area = w * h
                if w > 4 and h > 4 and area >= CONFIG.som_min_element_area:
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
                        start_id=start_id,
                    )
        except Exception:
            return
