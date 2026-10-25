"""Perception and visual/semantic grounding components."""

from vision_mcp.perception.capture import CapturePipeline
from vision_mcp.perception.som import SetOfMarksGenerator
from vision_mcp.perception.atspi import ATSPIInspector
from vision_mcp.perception.cv_detector import CVDetector

__all__ = ["CapturePipeline", "SetOfMarksGenerator", "ATSPIInspector", "CVDetector"]
