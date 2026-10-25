"""Configuration settings for Vision Control MCP Server."""

from pydantic import BaseModel, Field
from typing import Optional


class VisionConfig(BaseModel):
    """Runtime configuration for screen capture, input simulation, and grounding."""

    # Screen Capture & Image Optimization
    max_image_dimension: int = Field(
        default=1600,
        description="Max width or height for screenshots sent to AI (prevents token bloat).",
    )
    image_quality: int = Field(
        default=85,
        description="JPEG/WebP compression quality (1-100).",
    )
    draw_cursor: bool = Field(
        default=True,
        description="Whether to draw a virtual cursor overlay on captured screenshots.",
    )
    token_optimization_mode: str = Field(
        default="standard",
        description="Token optimization mode: 'standard', 'delta_patch', 'thumbnail_roi'.",
    )
    clip_to_active_window: bool = Field(
        default=False,
        description="Whether to automatically crop screenshots to the currently active window bounds.",
    )

    # Event-Driven Quiescence & Verification
    enable_quiescence_monitor: bool = Field(
        default=True,
        description="Whether to use XDamage & XFixes sub-millisecond quiescence monitoring instead of static sleep.",
    )
    quiescence_window_ms: int = Field(
        default=180,
        description="Continuous quiet period (ms) required before declaring UI settled.",
    )
    initial_reaction_timeout_ms: int = Field(
        default=1500,
        description="Maximum milliseconds to wait for initial screen damage or cursor busy signal post-action.",
    )
    max_quiescence_timeout_ms: int = Field(
        default=15000,
        description="Maximum total milliseconds to wait for UI settling before timeout or async job promotion.",
    )
    min_damage_area: int = Field(
        default=64,
        description="Pixel area threshold to filter out tiny caret blinks during damage accumulation.",
    )

    # GUI-to-Script Skill Crystallization
    enable_skill_crystallization: bool = Field(
        default=True,
        description="Whether to capture and correlate underlying application journal streams into reusable Tcl/CLI scripts.",
    )
    crystallized_skills_path: str = Field(
        default="~/.gemini/antigravity-cli/skills/crystallized_skills.json",
        description="Persistent file path for storing crystallized parameterized skills.",
    )

    # Self-Healing Action Cache
    enable_action_cache: bool = Field(
        default=True,
        description="Whether to use the self-healing locator cache for zero-token repeat actions.",
    )

    # Autonomous Obstruction Interception
    auto_dismiss_obstructions: bool = Field(
        default=True,
        description="Whether to automatically detect and dismiss blocking modal dialogs/permission prompts.",
    )

    # Set-of-Marks (SoM) & Grounding Strategy
    grounding_strategy: str = Field(
        default="ensemble",
        description="Active grounding strategy: 'ensemble', 'semantic', 'cv', or 'template'.",
    )
    enable_nms_fusion: bool = Field(
        default=True,
        description="Whether to use Non-Maximum Suppression to deduplicate fused detections.",
    )
    nms_iou_threshold: float = Field(
        default=0.40,
        description="Intersection-over-Union threshold for fusing overlapping marks.",
    )
    som_badge_font_size: int = Field(
        default=14,
        description="Font size for SoM numeric badge overlays.",
    )
    som_max_elements: int = Field(
        default=150,
        description="Max number of interactable elements to tag with SoM badges.",
    )
    som_min_element_area: int = Field(
        default=100,
        description="Minimum pixel area for an element to be tagged with a mark.",
    )

    # Input Simulation & Safety
    typing_delay_ms: float = Field(
        default=12.0,
        description="Natural typing delay between keystrokes in milliseconds.",
    )
    action_cooldown_ms: float = Field(
        default=50.0,
        description="Minimum delay after mouse or keyboard actions to allow UI update.",
    )
    failsafe_corner: bool = Field(
        default=True,
        description="Emergency abort if mouse cursor is forced to top-left (0, 0).",
    )

    # Terminal Integration
    allow_terminal_commands: bool = Field(
        default=True,
        description="Allow AI to execute headless bash commands for hybrid vision + CLI speed.",
    )
    command_timeout_seconds: int = Field(
        default=30,
        description="Max runtime in seconds for terminal commands.",
    )


# Singleton default config instance
CONFIG = VisionConfig()
