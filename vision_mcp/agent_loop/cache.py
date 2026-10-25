"""Self-Healing Action & Locator Cache for Zero-Token Replay.

Inspired by Stagehand's locator caching and enterprise RPA multi-anchoring.
Caches element bounding boxes, roles, and centroids so repeat interactions
execute in <80ms with 0 multimodal LLM tokens. Self-heals when UI drifts.
"""

import os
import json
import time
from typing import Optional, Dict, Tuple, Any
from pydantic import BaseModel, Field

from vision_mcp.types import BoundingBox


class CachedLocator(BaseModel):
    """Cached element signature and coordinates."""
    app_key: str = Field(description="Application or window identifier (e.g. 'chrome', 'gedit')")
    query: str = Field(description="Target search query or label")
    bbox: BoundingBox = Field(description="Physical desktop bounding box")
    center_coords: Tuple[int, int] = Field(description="Physical (x, y) coordinates for clicking")
    role: str = Field(default="unknown", description="Semantic role (button, text_entry, etc.)")
    hit_count: int = Field(default=1, description="Number of successful replayed clicks")
    created_at: float = Field(default_factory=time.time)
    last_verified_at: float = Field(default_factory=time.time)


class ActionCache:
    """
    Manages persistent storage and self-healing lifecycle for element locators.
    """

    def __init__(self, cache_file_path: Optional[str] = None) -> None:
        if cache_file_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cache_dir = os.path.join(base_dir, ".cache")
            os.makedirs(cache_dir, exist_ok=True)
            self.cache_file = os.path.join(cache_dir, "locator_cache.json")
        else:
            self.cache_file = cache_file_path
            os.makedirs(os.path.dirname(os.path.abspath(self.cache_file)), exist_ok=True)

        self._cache: Dict[str, CachedLocator] = {}
        self._load()

    def _make_key(self, app_key: str, query: str) -> str:
        """Generates normalized lookup key."""
        return f"{app_key.lower().strip()}::{query.lower().strip()}"

    def _load(self) -> None:
        """Loads cached entries from disk if present."""
        if not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            for k, v in raw_data.items():
                self._cache[k] = CachedLocator(**v)
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        """Persists cache to disk."""
        try:
            raw_data = {k: v.model_dump() for k, v in self._cache.items()}
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2)
        except Exception:
            pass

    def get(self, app_key: str, query: str) -> Optional[CachedLocator]:
        """Retrieves cached locator if exists."""
        key = self._make_key(app_key, query)
        return self._cache.get(key)

    def record(
        self,
        app_key: str,
        query: str,
        bbox: BoundingBox,
        center_coords: Tuple[int, int],
        role: str = "unknown",
    ) -> CachedLocator:
        """Records or updates a verified locator in the cache."""
        key = self._make_key(app_key, query)
        if key in self._cache:
            entry = self._cache[key]
            entry.bbox = bbox
            entry.center_coords = center_coords
            entry.role = role
            entry.hit_count += 1
            entry.last_verified_at = time.time()
        else:
            entry = CachedLocator(
                app_key=app_key.lower().strip(),
                query=query.lower().strip(),
                bbox=bbox,
                center_coords=center_coords,
                role=role,
                hit_count=1,
            )
            self._cache[key] = entry

        self._save()
        return entry

    def record_hit(self, app_key: str, query: str) -> None:
        """Increments hit count on successful cache replay."""
        key = self._make_key(app_key, query)
        if key in self._cache:
            self._cache[key].hit_count += 1
            self._cache[key].last_verified_at = time.time()
            self._save()

    def invalidate(self, app_key: str, query: str) -> bool:
        """Invalidates a broken cache entry when layout shift is detected."""
        key = self._make_key(app_key, query)
        if key in self._cache:
            del self._cache[key]
            self._save()
            return True
        return False

    def clear(self) -> None:
        """Clears all cached locators."""
        self._cache.clear()
        if os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
            except Exception:
                pass

    def get_stats(self) -> Dict[str, Any]:
        """Returns cache telemetry."""
        total_hits = sum(e.hit_count for e in self._cache.values())
        return {
            "entries_count": len(self._cache),
            "total_hits": total_hits,
            "cache_file": self.cache_file,
            "cached_keys": list(self._cache.keys()),
        }
