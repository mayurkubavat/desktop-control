"""Grounding Engine Coordinator providing hotswappable perception strategies."""

from typing import Dict, List, Optional, Tuple
from PIL import Image

from vision_mcp.perception.grounding.base import BaseGroundingProvider
from vision_mcp.perception.grounding.semantic import SemanticGroundingProvider
from vision_mcp.perception.grounding.cv import CVGroundingProvider
from vision_mcp.perception.grounding.template import TemplateGroundingProvider
from vision_mcp.perception.grounding.ensemble import EnsembleGroundingProvider
from vision_mcp.perception.grounding.magnitude import ground_magnitude_icon
from vision_mcp.types import UIElement, RelationalAnchor
from vision_mcp.config import CONFIG


class GroundingEngine:
    """
    Coordinates and hotswaps perception grounding providers at runtime.
    Supports 'ensemble', 'semantic', 'cv', and 'template' modes.
    """

    def __init__(self, default_strategy: str = CONFIG.grounding_strategy) -> None:
        self._semantic = SemanticGroundingProvider()
        self._cv = CVGroundingProvider()
        self._template = TemplateGroundingProvider()
        self._ensemble = EnsembleGroundingProvider(
            semantic_provider=self._semantic,
            cv_provider=self._cv,
            template_provider=self._template,
        )

        self._providers: Dict[str, BaseGroundingProvider] = {
            "semantic": self._semantic,
            "cv": self._cv,
            "template": self._template,
            "ensemble": self._ensemble,
        }

        self.active_strategy = default_strategy if default_strategy in self._providers else "ensemble"

    @property
    def current_provider(self) -> BaseGroundingProvider:
        """Returns the currently active grounding provider."""
        return self._providers.get(self.active_strategy, self._ensemble)

    def set_strategy(self, strategy: str) -> bool:
        """
        Hotswaps the active grounding strategy.

        Args:
            strategy: 'ensemble', 'semantic', 'cv', or 'template'.

        Returns:
            True if strategy was successfully switched, False otherwise.
        """
        low = strategy.lower().strip()
        if low in self._providers:
            self.active_strategy = low
            CONFIG.grounding_strategy = low
            return True
        return False

    def list_strategies(self) -> List[str]:
        """Returns list of registered grounding strategy names."""
        return list(self._providers.keys())

    def get_provider(self, name: str) -> Optional[BaseGroundingProvider]:
        """Gets a specific provider by name."""
        return self._providers.get(name.lower().strip())

    def detect_elements(
        self,
        image: Image.Image,
        scale_factor: float = 1.0,
        strategy_override: Optional[str] = None,
        app_filter: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[UIElement]:
        """Runs detection using the active or overridden grounding provider."""
        provider = self.get_provider(strategy_override) if strategy_override else self.current_provider
        if not provider:
            provider = self._ensemble
        return provider.detect(
            image=image,
            scale_factor=scale_factor,
            app_filter=app_filter,
            region=region,
        )

    def find_element(
        self,
        query: str,
        image: Optional[Image.Image] = None,
        scale_factor: float = 1.0,
        fuzzy: bool = True,
        strategy_override: Optional[str] = None,
    ) -> List[UIElement]:
        """Searches for elements matching query text across the chosen grounding backend."""
        provider = self.get_provider(strategy_override) if strategy_override else self.current_provider
        if not provider:
            provider = self._ensemble
        return provider.find_by_text(
            query=query,
            image=image,
            scale_factor=scale_factor,
            fuzzy=fuzzy,
        )

    def ground_icon(
        self,
        image: Image.Image,
        template: Image.Image,
        anchor: Optional[RelationalAnchor] = None,
        ocr_lines: Optional[list] = None,
        scale_factor: float = 1.0,
        cache: Optional[object] = None,
        app_key: str = "desktop",
    ) -> Optional[UIElement]:
        """Magnitude match, optionally inside an OCR offset window, with cache write-back."""
        element = ground_magnitude_icon(
            image=image,
            template=template,
            anchor=anchor,
            ocr_lines=ocr_lines,
            scale_factor=scale_factor,
        )
        if element is not None and anchor is not None and cache is not None and hasattr(cache, "remember_anchor"):
            cache.remember_anchor(app_key, anchor.label, anchor)
        return element
