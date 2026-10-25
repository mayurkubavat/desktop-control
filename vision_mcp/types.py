"""Data types and schemas for Vision Control MCP."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """2D Bounding Box in physical desktop pixel coordinates."""
    x: int = Field(description="X coordinate of top-left corner")
    y: int = Field(description="Y coordinate of top-left corner")
    width: int = Field(description="Width in pixels")
    height: int = Field(description="Height in pixels")

    @property
    def center(self) -> tuple[int, int]:
        """Returns the center (x, y) coordinates."""
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        """Returns pixel area."""
        return self.width * self.height


class UIElement(BaseModel):
    """Semantic or visual UI element."""
    id: int = Field(description="Numeric Set-of-Marks identifier or index")
    role: str = Field(default="unknown", description="Semantic role (button, text_entry, menu_item, etc.)")
    name: str = Field(default="", description="Text label, accessible name, or description")
    bbox: BoundingBox = Field(description="Physical screen location and dimensions")
    interactable: bool = Field(default=True, description="Whether element responds to clicks or keyboard input")
    states: List[str] = Field(default_factory=list, description="Active states (e.g., focused, selected, enabled)")


class WindowInfo(BaseModel):
    """Desktop window metadata."""
    window_id: str = Field(description="Hexadecimal or integer window identifier")
    title: str = Field(description="Window title bar text")
    bbox: BoundingBox = Field(description="Window position and dimensions")
    is_active: bool = Field(default=False, description="Whether this window currently has keyboard/mouse focus")
    app_name: Optional[str] = Field(default=None, description="Application binary name or WM_CLASS")


class ScreenshotResult(BaseModel):
    """Output of a screen capture with optional Set-of-Marks tags."""
    image_base64: str = Field(description="Base64 encoded JPEG or WebP image string")
    mime_type: str = Field(default="image/jpeg", description="MIME format of the image")
    width: int = Field(description="Captured image width (post-scaling)")
    height: int = Field(description="Captured image height (post-scaling)")
    original_width: int = Field(description="Physical desktop screen width")
    original_height: int = Field(description="Physical desktop screen height")
    scale_factor: float = Field(default=1.0, description="Scale ratio applied (e.g. 0.5 means scaled to 50%)")
    marks: List[UIElement] = Field(default_factory=list, description="List of interactable elements tagged with marks")
    cursor_position: Optional[tuple[int, int]] = Field(default=None, description="Pointer (x, y) at time of capture")


class ActionVerificationResult(BaseModel):
    """Outcome of an action execution with observation verification."""
    success: bool = Field(description="Whether the action was physically injected successfully")
    action_type: str = Field(description="Name of the action executed")
    delta_detected: bool = Field(default=False, description="Whether a visual screen change was observed post-action")
    change_ratio: float = Field(default=0.0, description="Fraction of pixels altered in region of interest")
    message: str = Field(default="", description="Status or error message")
