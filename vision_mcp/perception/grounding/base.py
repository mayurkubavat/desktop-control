"""Base abstract interface for pluggable grounding and perception providers."""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from PIL import Image

from vision_mcp.types import UIElement, BoundingBox


class BaseGroundingProvider(ABC):
    """Abstract base class for all hotswappable perception and UI grounding backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g. 'semantic', 'cv', 'template', 'ensemble')."""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Checks if dependencies and system hooks for this provider are functional."""
        pass

    @abstractmethod
    def detect(
        self,
        image: Image.Image,
        scale_factor: float = 1.0,
        app_filter: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[UIElement]:
        """
        Discovers interactable UI elements on the screen.

        Args:
            image: Screen frame (PIL Image, potentially scaled).
            scale_factor: Ratio of current image relative to physical screen.
            app_filter: Optional target application or process name filter.
            region: Optional (x, y, w, h) sub-region of interest.

        Returns:
            List of UIElement objects with physical screen coordinates.
        """
        pass

    def find_by_text(
        self,
        query: str,
        image: Optional[Image.Image] = None,
        scale_factor: float = 1.0,
        fuzzy: bool = True,
    ) -> List[UIElement]:
        """
        Searches for UI elements matching text or label query.
        Default implementation filters results from detect().
        """
        if image is None:
            return []
        all_elements = self.detect(image, scale_factor=scale_factor)
        q = query.lower().strip()
        matches = []
        for elem in all_elements:
            name = (elem.name or "").lower()
            if fuzzy and (q in name or name in q):
                matches.append(elem)
            elif not fuzzy and q == name:
                matches.append(elem)
        return matches
