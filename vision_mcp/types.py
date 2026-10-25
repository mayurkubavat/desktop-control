"""Data types and schemas for Vision Control MCP."""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ExecutionPhase(str, Enum):
    """Lifecycle phases of the adaptive event-driven quiescence loop."""
    DISPATCHED = "DISPATCHED"
    DAMAGE_ACCUMULATION = "DAMAGE_ACCUMULATION"
    SETTLING = "SETTLING"
    QUIESCENT = "QUIESCENT"
    ASYNC_PROMOTED = "ASYNC_PROMOTED"
    CONTRACT_VERIFIED = "CONTRACT_VERIFIED"
    OBSTRUCTED_BY_MODAL = "OBSTRUCTED_BY_MODAL"
    CONTRACT_FAILED = "CONTRACT_FAILED"


class StateAssertionType(str, Enum):
    """Semantic post-condition assertion types."""
    AT_SPI_STATE_PRESENT = "at_spi_state_present"
    AT_SPI_STATE_ABSENT = "at_spi_state_absent"
    WINDOW_SPAWNED = "window_spawned"
    WINDOW_CLOSED = "window_closed"
    TEXT_APPEARED = "text_appeared"
    SUBPANE_SSIM_DROP = "subpane_ssim_drop"
    CURSOR_CHANGED = "cursor_changed"


class PostConditionAssertion(BaseModel):
    """Single semantic post-condition assertion evaluated upon UI quiescence."""
    assertion_type: StateAssertionType = Field(description="Target assertion mechanism")
    target_role: Optional[str] = Field(default=None, description="UI role to inspect (push_button, dialog, etc.)")
    target_name_regex: Optional[str] = Field(default=None, description="Regex pattern matching element name or window title")
    target_subpane_id: Optional[str] = Field(default=None, description="Optional sub-pane identifier for localized verification")
    expected_state: Optional[str] = Field(default=None, description="Expected accessible state (e.g., FOCUSED, CHECKED)")
    min_ssim_delta: float = Field(default=0.08, ge=0.0, le=1.0, description="Minimum structural change required")
    cursor_expected: Optional[str] = Field(default=None, description="Expected cursor shape name (e.g., arrow, text)")


class PostConditionContract(BaseModel):
    """Contract declaring expected post-conditions following a GUI action."""
    assertions: List[PostConditionAssertion] = Field(default_factory=list, description="List of expected post-conditions")
    require_all: bool = Field(default=True, description="True for AND evaluation across assertions; False for OR")
    initial_reaction_timeout_ms: int = Field(default=1500, description="Max milliseconds to wait for initial reaction/damage")
    quiescence_window_ms: int = Field(default=180, description="Required milliseconds of continuous quiet state")
    max_total_timeout_ms: int = Field(default=15000, description="Maximum ceiling before escalating or timing out")
    allow_async_promotion: bool = Field(default=True, description="Whether to promote long-running actions to async jobs")


class ModalRiskTier(str, Enum):
    """Risk tiers for modal dialog classification and triage."""
    BENIGN_DISMISSIBLE = "BENIGN_DISMISSIBLE"
    INFORMATIVE_ACK = "INFORMATIVE_ACK"
    WORKFLOW_BRANCHING = "WORKFLOW_BRANCHING"
    DESTRUCTIVE_OR_SYSTEM = "DESTRUCTIVE_OR_SYSTEM"


class ModalButtonOption(BaseModel):
    """Button option discovered inside a modal dialog."""
    button_id: str = Field(description="Unique button identifier (e.g. 'btn_0', 'btn_ok')")
    label: str = Field(description="Button display label text")
    bbox: BoundingBox = Field(description="Physical pixel bounding box")
    is_default_focused: bool = Field(default=False, description="Whether button is the default focused option")
    inferred_consequence: str = Field(
        default="State mutation",
        description="Heuristic inference: 'Safe dismissal', 'Workflow branching decision', 'Destructive mutation'",
    )


class ModalEscalationPayload(BaseModel):
    """Structured payload returned to the orchestrator when an ambiguous or dangerous modal is encountered."""
    status: str = Field(default="ACTION_BLOCKED_BY_MODAL", description="Escalation status indicator")
    window_title: str = Field(description="Title bar of the blocking modal window")
    dialog_body_text: str = Field(description="Text extracted from the dialog body")
    risk_tier: ModalRiskTier = Field(description="Assessed risk classification tier")
    detected_buttons: List[ModalButtonOption] = Field(default_factory=list, description="Available action buttons")
    recommended_action_tool: str = Field(
        default="resolve_modal_dialog",
        description="Tool name to invoke with chosen button_id",
    )


class ModalTriageResult(BaseModel):
    """Outcome of an autonomous modal inspection and triage cycle."""
    detected: bool = Field(default=False, description="Whether a modal or popup was detected")
    window_title: str = Field(default="", description="Title of the detected window")
    body_text: str = Field(default="", description="Body text content of the dialog")
    risk_tier: Optional[ModalRiskTier] = Field(default=None, description="Assessed risk tier")
    auto_dismissed: bool = Field(default=False, description="Whether the modal was safely auto-dismissed")
    action_taken: str = Field(default="", description="Description of the action taken (or escalation reason)")
    extracted_summary: Optional[str] = Field(default=None, description="Information extracted from informative dialogs")
    escalation: Optional[ModalEscalationPayload] = Field(default=None, description="Escalation details if blocked")


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
    execution_phase: ExecutionPhase = Field(
        default=ExecutionPhase.CONTRACT_VERIFIED,
        description="Quiescence lifecycle phase reached (QUIESCENT, CONTRACT_VERIFIED, CONTRACT_FAILED, etc.)",
    )
    quiescence_elapsed_ms: float = Field(
        default=0.0,
        description="Time in milliseconds elapsed from action injection to UI quiescence",
    )
    post_conditions_passed: Optional[bool] = Field(
        default=None,
        description="Whether explicit post-condition contract assertions succeeded (None if no contract provided)",
    )
    cursor_state: Optional[str] = Field(
        default=None,
        description="Observed mouse cursor shape name post-action (e.g. 'arrow', 'text', 'watch')",
    )
    dirty_pixel_area: int = Field(
        default=0,
        description="Total cumulative dirty pixel area observed during damage accumulation",
    )


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

