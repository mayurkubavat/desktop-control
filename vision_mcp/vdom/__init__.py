"""
Virtual DOM (vDOM), Grounding Sidecar, and Dynamic Layout Engine.

Provides unified perception fusing AT-SPI2 semantics with neural vision proposals,
zero-token CSS spatial querying, and dynamic anchor-relative layout resolution.
"""

from vision_mcp.vdom.fusion import VDOMFusionEngine
from vision_mcp.vdom.query import VDOMQueryEngine
from vision_mcp.vdom.sidecar import LocalNeuralGrounder
from vision_mcp.vdom.layout import SubPaneLayoutSolver

__all__ = [
    "VDOMFusionEngine",
    "VDOMQueryEngine",
    "LocalNeuralGrounder",
    "SubPaneLayoutSolver",
]
