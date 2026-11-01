"""
Local Gemma 3 Multimodal Sidecar Plugin for Phase 4 Grounding and Modal Triage.

Integrates local Google Gemma 3 models served by Ollama (gemma3:4b by default for both
vision sub-panes and text modal triage) with perceptual dHash caching and zero cloud
token overhead. Replies are constrained to JSON schemas via vision_mcp.gemma.client.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
import numpy as np

from vision_mcp.config import CONFIG
from vision_mcp.gemma.client import GemmaClient, GemmaError, encode_image
from vision_mcp.types import (
    BoundingBox,
    GroundingSource,
    ModalRiskTier,
    UIRole,
    VDOMNode,
    VirtualDOMSnapshot,
)

logger = logging.getLogger(__name__)


def compute_dhash(image: Image.Image) -> int:
    """
    Computes a 64-bit difference hash (dHash) for an image crop in < 0.6ms.
    Captures structural gradient morphology invariant to slight brightness/contrast shifts.
    """
    try:
        # Resize to 9x8 grayscale
        resized = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
        arr = np.array(resized)
        # Compare adjacent columns
        diff = arr[:, 1:] > arr[:, :-1]
        return int.from_bytes(np.packbits(diff.flatten()), "big")
    except Exception as e:
        logger.debug(f"Error computing dHash: {e}")
        return 0


def hamming_distance(h1: int, h2: int) -> int:
    """Computes the Hamming distance (number of differing bits) between two 64-bit hashes."""
    return (h1 ^ h2).bit_count()


class SemanticROICache:
    """
    Perceptual LRU cache for visual grounding proposals.
    Provides sub-millisecond retrieval on static or repeating EDA sub-panes.
    """

    def __init__(self, capacity: int = 256, threshold: int = 4) -> None:
        self.capacity = capacity
        self.threshold = threshold
        # Key: cache_key -> (dhash, timestamp, List[Dict[str, Any]])
        self._entries: OrderedDict[str, Tuple[int, float, List[Dict[str, Any]]]] = OrderedDict()

    def get(self, cache_key: str, dhash: int) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieves cached proposals if key matches and Hamming distance <= threshold.
        """
        if cache_key in self._entries:
            entry_dhash, _, proposals = self._entries[cache_key]
            if hamming_distance(dhash, entry_dhash) <= self.threshold:
                self._entries.move_to_end(cache_key)
                logger.debug(f"SemanticROICache hit for key '{cache_key}' (Hamming dist={hamming_distance(dhash, entry_dhash)})")
                return proposals

        # Secondary search across all entries for identical perceptual match
        for k, (entry_dhash, _, proposals) in list(self._entries.items()):
            if hamming_distance(dhash, entry_dhash) <= self.threshold:
                self._entries.move_to_end(k)
                logger.debug(f"SemanticROICache perceptual match for key '{k}' (Hamming dist={hamming_distance(dhash, entry_dhash)})")
                return proposals

        return None

    def put(self, cache_key: str, dhash: int, proposals: List[Dict[str, Any]]) -> None:
        """Stores proposals in the LRU cache."""
        if cache_key in self._entries:
            self._entries.move_to_end(cache_key)
        self._entries[cache_key] = (dhash, time.time(), proposals)
        if len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


_GROUND_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "role": {
                        "type": "string",
                        "enum": [
                            "icon_button",
                            "push_button",
                            "text_input",
                            "dropdown",
                            "waveform_signal",
                            "schematic_pin",
                        ],
                    },
                    "label": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["box_2d", "role", "label", "confidence"],
            },
        }
    },
    "required": ["elements"],
}

_MODAL_TIERS = [t.value for t in ModalRiskTier]

_MODAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "risk_tier": {"type": "string", "enum": _MODAL_TIERS},
        "suggested_button": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["risk_tier", "suggested_button", "confidence", "reason"],
}


_YES_NO_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "string"},
    },
    "required": ["answer", "confidence", "evidence"],
}


def _fit_image(image: Image.Image, max_side: int) -> Image.Image:
    w, h = image.size
    scale = max_side / float(max(w, h))
    if scale >= 1.0:
        return image
    return image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _escalate(reason: str) -> Dict[str, Any]:
    """Fail-closed modal verdict: never auto-click, hand the choice to the planner."""
    return {
        "risk_tier": ModalRiskTier.WORKFLOW_BRANCHING.value,
        "suggested_button": None,
        "confidence": 0.0,
        "reason": reason,
        "source": "fallback",
    }


class Gemma3Grounder:
    """
    On-demand local Gemma 3 sidecar (via Ollama) for sub-pane grounding and
    modal triage. All calls go through :class:`GemmaClient`, which constrains
    replies to a JSON schema and records call counts and latency.
    """

    def __init__(
        self,
        endpoint: str = CONFIG.gemma3_endpoint,
        vision_model: str = CONFIG.gemma3_vision_model,
        text_model: str = CONFIG.gemma3_text_model,
        dhash_threshold: int = CONFIG.gemma3_dhash_threshold,
        cache_capacity: int = CONFIG.gemma3_cache_capacity,
        timeout: float = CONFIG.gemma3_timeout_seconds,
        client: Optional[GemmaClient] = None,
    ) -> None:
        self.client = client or GemmaClient(
            base_url=endpoint,
            timeout=timeout,
            keep_alive=CONFIG.gemma3_keep_alive,
        )
        self.endpoint = self.client.base_url
        self.vision_model = vision_model
        self.text_model = text_model
        self.timeout = timeout
        self.cache = SemanticROICache(capacity=cache_capacity, threshold=dhash_threshold)
        self.cache_hits = 0

    def is_available(self) -> bool:
        """True when Ollama is reachable and both configured models are installed (exact names)."""
        return self.client.has_models({self.vision_model, self.text_model})

    def diagnostics(self) -> Dict[str, Any]:
        installed = self.client.installed_models()
        return {
            "vision_model": self.vision_model,
            "text_model": self.text_model,
            "available": self.is_available(),
            "installed_models": sorted(installed),
            "roi_cache_entries": len(self.cache),
            "roi_cache_hits": self.cache_hits,
            **self.client.stats(),
        }

    def ground_roi(
        self,
        image: Image.Image,
        offset: Tuple[int, int] = (0, 0),
        anchor_id: str = "default",
        task_intent: str = "ground_ui",
    ) -> List[Dict[str, Any]]:
        """
        Grounds UI elements inside an ROI crop and returns proposals in absolute
        screen coordinates. Returns [] on any Gemma failure so callers fall back
        to the CV/ONNX proposals.
        """
        ox, oy = offset
        w, h = image.size
        if w < 10 or h < 10:
            return []

        img_dhash = compute_dhash(image)
        cache_key = f"{anchor_id}:{task_intent}"
        cached = self.cache.get(cache_key, img_dhash)
        if cached is not None:
            self.cache_hits += 1
            return [
                {
                    "bbox": {
                        "x": ox + item["rel_box"]["x"],
                        "y": oy + item["rel_box"]["y"],
                        "width": item["rel_box"]["width"],
                        "height": item["rel_box"]["height"],
                    },
                    "confidence": item["confidence"],
                    "class_name": item["class_name"],
                    "text": item.get("text", ""),
                    "source": GroundingSource.VISION_ONLY.value,
                }
                for item in cached
            ]

        system_prompt = (
            "You are a UI grounding engine operating on a cropped desktop region.\n"
            "Identify interactive UI elements (buttons, inputs, dropdowns, icons, waveform signals, schematic pins).\n"
            "box_2d is [ymin, xmin, ymax, xmax] as integers from 0 to 1000 relative to the image."
        )
        user_prompt = f"Ground the interactive targets in this '{anchor_id}' crop for '{task_intent}'."

        try:
            data = self.client.chat_json(
                model=self.vision_model,
                system=system_prompt,
                user=user_prompt,
                schema=_GROUND_SCHEMA,
                images=[encode_image(image, quality=92)],
                timeout=self.timeout,
            )
        except GemmaError as e:
            logger.warning(f"Gemma 3 grounding failed: {e}")
            return []

        proposals: List[Dict[str, Any]] = []
        raw_items_for_cache: List[Dict[str, Any]] = []
        for el in data.get("elements", []) or []:
            box_2d = el.get("box_2d") if isinstance(el, dict) else None
            if not box_2d or len(box_2d) != 4:
                continue
            try:
                ymin, xmin, ymax, xmax = [float(v) for v in box_2d]
                conf = float(el.get("confidence", 0.5))
            except (TypeError, ValueError):
                continue

            ymin = max(0.0, min(1000.0, ymin))
            xmin = max(0.0, min(1000.0, xmin))
            ymax = max(ymin + 5.0, min(1000.0, ymax))
            xmax = max(xmin + 5.0, min(1000.0, xmax))

            rel_x = int(round(xmin * w / 1000.0))
            rel_y = int(round(ymin * h / 1000.0))
            rel_w = max(4, int(round((xmax - xmin) * w / 1000.0)))
            rel_h = max(4, int(round((ymax - ymin) * h / 1000.0)))

            role = el.get("role", "icon_button")
            label = el.get("label", "")
            conf = max(0.0, min(1.0, conf))

            raw_items_for_cache.append({
                "rel_box": {"x": rel_x, "y": rel_y, "width": rel_w, "height": rel_h},
                "class_name": role,
                "text": label,
                "confidence": conf,
            })
            proposals.append({
                "bbox": {"x": ox + rel_x, "y": oy + rel_y, "width": rel_w, "height": rel_h},
                "confidence": conf,
                "class_name": role,
                "text": label,
                "source": GroundingSource.VISION_ONLY.value,
            })

        if raw_items_for_cache:
            self.cache.put(cache_key, img_dhash, raw_items_for_cache)
            logger.info(f"Gemma 3 grounded {len(proposals)} elements in '{anchor_id}' (dHash {hex(img_dhash)})")
        return proposals

    def classify_modal(
        self,
        modal_text: str,
        modal_image: Optional[Image.Image] = None,
        button_labels: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Classifies a modal dialog into the same tiers as ``ModalRiskTier``.

        Returns ``{risk_tier, suggested_button, confidence, reason, source}``.
        Fails closed: on any error, unknown tier, or a suggested button that is
        not one of ``button_labels``, the verdict is WORKFLOW_BRANCHING with no
        button, so the dialog is escalated instead of clicked.
        """
        system_prompt = (
            "You are a safety triage classifier for desktop and EDA software dialogs.\n"
            "Classify the dialog into exactly one risk tier:\n"
            "- BENIGN_DISMISSIBLE: tips, telemetry, cookie or update nags; safe to close.\n"
            "- INFORMATIVE_ACK: a finished-task or status notice with a single acknowledge button.\n"
            "- WORKFLOW_BRANCHING: a choice that changes what the workflow does next.\n"
            "- DESTRUCTIVE_OR_SYSTEM: overwrites or deletes files, discards work, kills runs, license or system errors.\n"
            "suggested_button must be copied exactly from the button list, or null. "
            "Only suggest a button for BENIGN_DISMISSIBLE or INFORMATIVE_ACK. When unsure, use WORKFLOW_BRANCHING."
        )
        buttons_line = ", ".join(f'"{b}"' for b in button_labels) if button_labels else "(unknown)"
        user_prompt = f"Dialog text:\n{modal_text}\n\nButtons: {buttons_line}"

        model = self.text_model
        images = None
        if modal_image is not None:
            model = self.vision_model
            images = [encode_image(modal_image, quality=90)]

        try:
            data = self.client.chat_json(
                model=model,
                system=system_prompt,
                user=user_prompt,
                schema=_MODAL_SCHEMA,
                images=images,
                timeout=timeout or self.timeout,
            )
        except GemmaError as e:
            logger.warning(f"Modal classification with Gemma 3 failed: {e}")
            return _escalate(f"Gemma unavailable: {e}")

        tier = data.get("risk_tier")
        if tier not in _MODAL_TIERS:
            return _escalate(f"Gemma returned unknown tier {tier!r}")

        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0

        suggested = data.get("suggested_button")
        safe_tiers = {ModalRiskTier.BENIGN_DISMISSIBLE.value, ModalRiskTier.INFORMATIVE_ACK.value}
        if tier not in safe_tiers:
            suggested = None
        elif suggested is not None and button_labels is not None:
            match = next((b for b in button_labels if b.strip().lower() == str(suggested).strip().lower()), None)
            suggested = match
        if tier in safe_tiers and suggested is None:
            # A "safe" verdict with no usable button cannot be acted on: escalate.
            return _escalate(f"Gemma said {tier} but named no valid button")

        return {
            "risk_tier": tier,
            "suggested_button": suggested,
            "confidence": confidence,
            "reason": str(data.get("reason", "")),
            "source": "gemma",
        }

    def ask_yes_no(
        self,
        image: Image.Image,
        question: str,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Answers a yes/no question about a screen crop.

        Returns ``{answer, confidence, evidence, source}``. ``answer`` is None
        when Gemma could not answer (unavailable, timeout, bad reply), so the
        caller can fall back to sending a screenshot to the planner.
        """
        if image.size[0] < 4 or image.size[1] < 4:
            return {"answer": None, "confidence": 0.0, "evidence": "crop too small", "source": "fallback"}
        crop = _fit_image(image, CONFIG.gemma3_visual_max_side)
        system_prompt = (
            "You check the state of a desktop application from a screenshot crop.\n"
            "Answer the question with true or false. Base the answer only on what is visible. "
            "If the crop does not show enough to tell, answer false with low confidence. "
            "evidence is one short sentence quoting the visible text or describing the element you relied on."
        )
        try:
            data = self.client.chat_json(
                model=self.vision_model,
                system=system_prompt,
                user=question,
                schema=_YES_NO_SCHEMA,
                images=[encode_image(crop, quality=90)],
                timeout=timeout or self.timeout,
            )
        except GemmaError as e:
            return {"answer": None, "confidence": 0.0, "evidence": f"Gemma unavailable: {e}", "source": "fallback"}
        answer = data.get("answer")
        if not isinstance(answer, bool):
            return {"answer": None, "confidence": 0.0, "evidence": f"bad answer {answer!r}", "source": "fallback"}
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "answer": answer,
            "confidence": confidence,
            "evidence": str(data.get("evidence", ""))[:300],
            "source": "gemma",
        }

    def fuse_with_vdom(
        self,
        vdom_snapshot: VirtualDOMSnapshot,
        proposals: List[Dict[str, Any]],
        anchor_id: Optional[str] = None,
    ) -> VirtualDOMSnapshot:
        """
        Integrates Gemma 3 visual proposals into a VirtualDOMSnapshot.
        Injects nodes with source=GroundingSource.VISION_ONLY into the snapshot nodes dictionary.
        """
        next_idx = len(vdom_snapshot.nodes) + 1

        for p in proposals:
            bbox_dict = p.get("bbox", {})
            bx = bbox_dict.get("x", 0)
            by = bbox_dict.get("y", 0)
            bw = bbox_dict.get("width", 10)
            bh = bbox_dict.get("height", 10)
            bbox = BoundingBox(
                x=bx,
                y=by,
                width=bw,
                height=bh,
            )
            role_name = p.get("class_name", "icon_button")
            try:
                role = UIRole(role_name)
            except ValueError:
                role = UIRole.PUSH_BUTTON

            node_id = f"gemma3_{next_idx}"
            attrs: Dict[str, str] = {}
            if anchor_id:
                attrs["anchor_id"] = anchor_id

            node = VDOMNode(
                node_id=node_id,
                role=role,
                name=p.get("text", "") or role_name,
                bbox=bbox,
                click_point=(bx + bw // 2, by + bh // 2),
                source=GroundingSource.VISION_ONLY,
                confidence=float(p.get("confidence", 0.9)),
                attributes=attrs,
                parent_id=vdom_snapshot.root_id if vdom_snapshot.root_id else None,
            )
            vdom_snapshot.nodes[node_id] = node

            # If root exists, add child reference
            if vdom_snapshot.root_id and vdom_snapshot.root_id in vdom_snapshot.nodes:
                vdom_snapshot.nodes[vdom_snapshot.root_id].children_ids.append(node_id)

            next_idx += 1

        return vdom_snapshot
