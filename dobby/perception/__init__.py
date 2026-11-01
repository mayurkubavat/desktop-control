"""Perception and visual/semantic grounding components."""

from dobby.perception.capture import CapturePipeline
from dobby.perception.som import SetOfMarksGenerator
from dobby.perception.atspi import ATSPIInspector
from dobby.perception.cv_detector import CVDetector

__all__ = ["CapturePipeline", "SetOfMarksGenerator", "ATSPIInspector", "CVDetector"]
