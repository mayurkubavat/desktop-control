"""
GUI-to-Script Skill Crystallization Engine.

Translates slow, high-token physical GUI demonstrations into deterministic,
sub-millisecond parameterized Tcl/CLI scripts that execute with 0 visual tokens.
"""

from dobby.crystallization.correlator import JournalCorrelator
from dobby.crystallization.compiler import TclTrajectoryCompiler
from dobby.crystallization.trace_compiler import TraceCompiler, replay_macro
from dobby.crystallization.registry import DynamicSkillRegistry
from dobby.types import (
    CorrelatedStep,
    CrystallizedMacro,
    CrystallizedSkillSpec,
    SkillExecutionResult,
)

__all__ = [
    "JournalCorrelator",
    "TclTrajectoryCompiler",
    "TraceCompiler",
    "replay_macro",
    "DynamicSkillRegistry",
    "CorrelatedStep",
    "CrystallizedSkillSpec",
    "CrystallizedMacro",
    "SkillExecutionResult",
]
