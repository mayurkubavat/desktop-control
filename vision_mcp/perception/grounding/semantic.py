"""Semantic Grounding Provider using OS Accessibility APIs (AT-SPI2 / UIA)."""

from typing import List, Optional, Tuple
from PIL import Image

from vision_mcp.perception.grounding.base import BaseGroundingProvider
from vision_mcp.perception.atspi import ATSPIInspector
from vision_mcp.types import UIElement


class SemanticGroundingProvider(BaseGroundingProvider):
    """Grounding provider leveraging OS accessibility trees (AT-SPI2 on Linux)."""

    def __init__(self, inspector: Optional[ATSPIInspector] = None) -> None:
        self.inspector = inspector or ATSPIInspector()

    @property
    def name(self) -> str:
        return "semantic"

    @property
    def is_available(self) -> bool:
        return self.inspector.is_available

    def detect(
        self,
        image: Image.Image,
        scale_factor: float = 1.0,
        app_filter: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[UIElement]:
        """Queries the OS accessibility hierarchy directly."""
        elements = self.inspector.inspect_desktop(app_name_filter=app_filter)
        if region:
            rx, ry, rw, rh = region
            filtered = []
            for e in elements:
                bx, by, bw, bh = e.bbox.x, e.bbox.y, e.bbox.width, e.bbox.height
                if (bx >= rx and by >= ry and (bx + bw) <= (rx + rw) and (by + bh) <= (ry + rh)):
                    filtered.append(e)
            return filtered
        return elements

    def find_by_text(
        self,
        query: str,
        image: Optional[Image.Image] = None,
        scale_factor: float = 1.0,
        fuzzy: bool = True,
    ) -> List[UIElement]:
        """
        Fast semantic search across the OS accessibility tree without requiring screen image tokens.
        """
        all_elements = self.inspector.inspect_desktop()
        q = query.lower().strip()
        matches = []
        for elem in all_elements:
            name = (elem.name or "").lower()
            role = (elem.role or "").lower()
            if fuzzy and (q in name or q in role):
                matches.append(elem)
            elif not fuzzy and (q == name or q == role):
                matches.append(elem)
        return matches
