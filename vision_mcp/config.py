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

    # Local Neural Grounding Sidecar & Unified vDOM
    enable_vdom: bool = Field(
        default=True,
        description="Whether to generate and maintain a unified hierarchical Virtual DOM (vDOM).",
    )
    vdom_sidecar_shm_path: str = Field(
        default="/dev/shm/vision_mcp_fb",
        description="Shared memory path for zero-copy IPC between MCP server and local neural daemon.",
    )
    vdom_fusion_iou_threshold: float = Field(
        default=0.65,
        description="Asymmetric IoU threshold for merging neural proposals with AT-SPI2 leaf nodes into HYBRID nodes.",
    )
    vdom_containment_ratio_threshold: float = Field(
        default=0.85,
        description="Containment threshold for nesting unmatched visual elements under parent containers.",
    )

    # Fast-Path Neural ONNX UI Detector
    enable_fast_onnx_detector: bool = Field(
        default=True,
        description="Whether to use sub-20ms ONNX UI detector for fast zero-token vDOM proposals.",
    )
    fast_onnx_model_path: str = Field(
        default="vision_mcp/models/ui_detector_fast.onnx",
        description="File path to the ONNX UI detection model.",
    )
    fast_onnx_conf_threshold: float = Field(
        default=0.25,
        description="Confidence threshold for neural UI proposals.",
    )
    fast_onnx_iou_threshold: float = Field(
        default=0.45,
        description="Non-Maximum Suppression IoU threshold for neural proposals.",
    )
    fast_onnx_num_threads: int = Field(
        default=4,
        description="Number of intra-op threads for ONNX Runtime CPU inference.",
    )

    # Local Gemma 3 Multimodal Sidecar Plugin
    enable_gemma3_sidecar: bool = Field(
        default=True,
        description="Whether to enable on-demand Gemma 3 multimodal grounding for opaque sub-panes and modal triage.",
    )
    gemma3_endpoint: str = Field(
        default="http://127.0.0.1:11434/api/generate",
        description="Ollama API endpoint for local Gemma 3 inference.",
    )
    gemma3_vision_model: str = Field(
        default="gemma3:4b",
        description="Model identifier for multimodal visual grounding (Gemma 3 4B-IT).",
    )
    gemma3_text_model: str = Field(
        default="gemma3:1b",
        description="Model identifier for lightweight text modal risk triage (Gemma 3 1B-IT).",
    )
    gemma3_dhash_threshold: int = Field(
        default=4,
        description="Perceptual hash Hamming distance threshold for semantic ROI cache hits.",
    )
    gemma3_cache_capacity: int = Field(
        default=256,
        description="Maximum entries in the local Gemma 3 semantic ROI cache.",
    )
    gemma3_timeout_seconds: float = Field(
        default=25.0,
        description="Maximum timeout in seconds for local Gemma 3 inference requests.",
    )

    # Dynamic Anchor-Relative Sub-Pane Resolution
    enable_dynamic_subpanes: bool = Field(
        default=True,
        description="Whether to resolve sub-pane boundaries dynamically relative to persistent UI anchors.",
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
