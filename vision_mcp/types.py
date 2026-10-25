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


class FindElementResult(BaseModel):
    """Result of an autonomous element search by text, role, or label."""
    found: bool = Field(description="Whether a matching element was discovered")
    query: str = Field(description="Search query string or pattern")
    element: Optional[UIElement] = Field(default=None, description="Best matching UI element if found")
    center_coords: Optional[tuple[int, int]] = Field(default=None, description="Exact physical (x, y) coordinates for clicking")
    confidence: float = Field(default=1.0, description="Match confidence score (0.0 to 1.0)")
    candidates_count: int = Field(default=0, description="Total matching candidates discovered")


class DiagnosticsResult(BaseModel):
    """Diagnostic health check of the Vision MCP server and perception backends."""
    platform: str = Field(description="Host OS platform (linux, win32, darwin)")
    display_server: str = Field(description="Display environment (X11, Wayland, Windows GDI/DXGI)")
    primary_screen_size: tuple[int, int] = Field(description="Primary display resolution (w, h)")
    active_grounding_strategy: str = Field(description="Current grounding engine mode")
    atspi_available: bool = Field(description="Whether Linux AT-SPI2 accessibility bus is active")
    opencv_available: bool = Field(description="Whether OpenCV contour detection is active")
    supported_grounding_providers: List[str] = Field(description="List of registered grounding providers")
    active_window: Optional[str] = Field(default=None, description="Currently focused window title")
    config_summary: Dict[str, Any] = Field(description="Active configuration parameters")


class SubPaneROI(BaseModel):
    """Defines a functional sub-pane within an application window."""
    name: str = Field(description="Identifier for the pane (e.g. address_bar, tab_strip, waveform_canvas)")
    description: str = Field(default="", description="Semantic role or description of the sub-pane")
    relative_x: float = Field(default=0.0, description="Horizontal start offset as fraction of window width [0.0..1.0]")
    relative_y: float = Field(default=0.0, description="Vertical start offset as fraction of window height [0.0..1.0]")
    relative_width: float = Field(default=1.0, description="Pane width as fraction of window width [0.0..1.0]")
    relative_height: float = Field(default=1.0, description="Pane height as fraction of window height [0.0..1.0]")
    offset_x: int = Field(default=0, description="Fixed pixel offset added to X")
    offset_y: int = Field(default=0, description="Fixed pixel offset added to Y")
    fixed_width: Optional[int] = Field(default=None, description="Optional fixed pixel width overriding relative_width")
    fixed_height: Optional[int] = Field(default=None, description="Optional fixed pixel height overriding relative_height")

    def compute_bounds(self, window_bbox: BoundingBox) -> BoundingBox:
        """Computes absolute physical screen bounding box relative to host window."""
        x = window_bbox.x + int(window_bbox.width * self.relative_x) + self.offset_x
        y = window_bbox.y + int(window_bbox.height * self.relative_y) + self.offset_y

        if self.fixed_width is not None:
            w = min(self.fixed_width, max(1, window_bbox.width - (x - window_bbox.x)))
        else:
            w = int(window_bbox.width * self.relative_width) - self.offset_x

        if self.fixed_height is not None:
            h = min(self.fixed_height, max(1, window_bbox.height - (y - window_bbox.y)))
        else:
            h = int(window_bbox.height * self.relative_height) - self.offset_y

        return BoundingBox(x=x, y=y, width=max(1, w), height=max(1, h))


class FeatureDescriptor(BaseModel):
    """Declarative capability supported by an application plugin."""
    feature_id: str = Field(description="Unique feature identifier (e.g. 'browser.navigate', 'verdi.trace_driver')")
    name: str = Field(description="Human-readable feature name")
    description: str = Field(description="Description of what this feature accomplishes")
    category: str = Field(default="general", description="Category: navigation, editing, view, devtools, macro")
    hotkey: Optional[str] = Field(default=None, description="Direct keyboard shortcut if applicable (e.g. 'ctrl+l')")
    menu_path: Optional[List[str]] = Field(default=None, description="Menu navigation path if applicable")
    target_pane: Optional[str] = Field(default=None, description="Name of sub-pane where feature executes")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Expected parameter schemas")


class PluginSummary(BaseModel):
    """Metadata summary of a registered UI application plugin."""
    app_id: str = Field(description="Unique application identifier")
    name: str = Field(description="Display name")
    description: str = Field(description="Plugin description")
    is_active: bool = Field(default=False, description="Whether this plugin matches the current active foreground window")
    supported_panes: List[str] = Field(default_factory=list, description="Names of available sub-panes")
    features_count: int = Field(default=0, description="Total number of registered features")

