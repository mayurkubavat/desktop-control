"""
GUI-to-Script Skill Crystallization Engine.

Translates slow, high-token physical GUI demonstrations into deterministic,
sub-millisecond parameterized Tcl/CLI scripts that execute with 0 visual tokens.
"""

from vision_mcp.crystallization.correlator import JournalCorrelator
from vision_mcp.crystallization.compiler import TclTrajectoryCompiler
from vision_mcp.crystallization.registry import DynamicSkillRegistry
from vision_mcp.types import (
    CorrelatedStep,
    CrystallizedSkillSpec,
    SkillExecutionResult,
)

__all__ = [
    "JournalCorrelator",
    "TclTrajectoryCompiler",
    "DynamicSkillRegistry",
    "CorrelatedStep",
    "CrystallizedSkillSpec",
    "SkillExecutionResult",
]
