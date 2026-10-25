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

    # Set-of-Marks (SoM) Visual Overlay
    som_badge_font_size: int = Field(
        default=14,
        description="Font size for SoM numeric badge overlays.",
    )
    som_max_elements: int = Field(
        default=60,
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
