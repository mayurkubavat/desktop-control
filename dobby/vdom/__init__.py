"""
Virtual DOM (vDOM), Grounding Sidecar, and Dynamic Layout Engine.

Provides unified perception fusing AT-SPI2 semantics with neural vision proposals,
zero-token CSS spatial querying, and dynamic anchor-relative layout resolution.
"""

from dobby.vdom.fusion import VDOMFusionEngine
from dobby.vdom.query import VDOMQueryEngine
from dobby.vdom.sidecar import LocalNeuralGrounder
from dobby.vdom.layout import SubPaneLayoutSolver
from dobby.vdom.gemma3_sidecar import Gemma3Grounder, SemanticROICache, compute_dhash
from dobby.vdom.fast_detector import (
    FastONNXUIDetector,
    UIClass,
    build_default_ui_detector_model,
    letterbox,
    unletterbox_boxes,
    nms_vectorized,
    postprocess_yolo_detections,
)

__all__ = [
    "VDOMFusionEngine",
    "VDOMQueryEngine",
    "LocalNeuralGrounder",
    "SubPaneLayoutSolver",
    "Gemma3Grounder",
    "SemanticROICache",
    "compute_dhash",
    "FastONNXUIDetector",
    "UIClass",
    "build_default_ui_detector_model",
    "letterbox",
    "unletterbox_boxes",
    "nms_vectorized",
    "postprocess_yolo_detections",
]
