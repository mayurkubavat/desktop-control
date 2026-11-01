"""ADK agent pipeline for desktop-control (optional; ``pip install -e '.[adk]'``).

Deterministic code runs the desktop tools; local Gemma only judges, through ADK
``LlmAgent``s with an ``output_schema`` (which turns tools off for them). The
planner is not here: a plan is a JSON list of tool steps with expectations,
written by Claude (or taken from a crystallized skill). When a step cannot be
verified, the run stops and returns a report for the planner.

    python -m vision_mcp.adk plan.json                 # drives the live desktop over MCP
    python -m vision_mcp.adk plan.json --in-process    # same, inside this process (cassettes: DESKTOP_HAL=replay)

Nothing in the MCP server imports this package.
"""

from vision_mcp.adk.plan import Expect, Plan, Step  # noqa: F401
