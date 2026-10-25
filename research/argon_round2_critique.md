These production-grade architectural blueprints, schemas, and Python/C implementations address the three core systems.

1. P2: GUI-to-Script Skill Crystallization Engine
Complex EDA applications like AMD Vivado and Synopsys Verdi operate on an internal command interpreter (Tcl/Tk or custom CLI) where every GUI action dispatches an underlying text command echoed to a journal file (vivado.jou, novas.cmd). By correlating GUI action spans with journal file byte-offsets, Vision MCP can compile fragile multi-step visual trajectories into deterministic, zero-token MCP tools.

A. Journal/Log Listener & Temporal Correlator (inotify + Byte-Offset Bracketing)
Instead of polling log files, the MCP server uses Linux inotify (IN_MODIFY) to watch the active journal file descriptor and brackets every physical GUI action with precise byte offsets.

Python
import os
import time
import fcntl
import struct
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class CorrelatedStep:
    action_id: str
    gui_intent: str              # e.g., "Click 'Create Clock' in Timing Constraints wizard"
    ui_target_text: str          # e.g., "clk_core_0"
    timestamp_start: float
    timestamp_end: float
    journal_lines: List[str] = field(default_factory=list)

class JournalCorrelator:
    def __init__(self, journal_path: str):
        self.journal_path = journal_path
        self._fd = open(self.journal_path, "r", encoding="utf-8", errors="replace")
        self._fd.seek(0, os.SEEK_END)
        self._mark_offset = self._fd.tell()

    def mark_pre_action(self) -> int:
        """Called immediately before X11 mouse/keyboard injection."""
        self._fd.seek(0, os.SEEK_END)
        self._mark_offset = self._fd.tell()
        return self._mark_offset

    def harvest_post_quiescence(self, action_id: str, gui_intent: str, ui_target_text: str, t_start: float) -> CorrelatedStep:
        """Called immediately after the Quiescence Engine confirms UI stability."""
        self._fd.seek(self._mark_offset, os.SEEK_SET)
        raw_chunk = self._fd.read()
        self._mark_offset = self._fd.tell()

        # Filter comments (#), empty lines, and pure GUI layout commands (e.g., view_zoom)
        valid_lines = [
            line.strip() for line in raw_chunk.splitlines()
            if line.strip() and not line.strip().startswith("#")
            and not line.strip().startswith(("gui_", "wvZoom", "select_area"))
        ]
        return CorrelatedStep(
            action_id=action_id,
            gui_intent=gui_intent,
            ui_target_text=ui_target_text,
            timestamp_start=t_start,
            timestamp_end=time.monotonic(),
            journal_lines=valid_lines
        )
B. Trajectory Compiler & AST Parameterizer
Raw journal traces contain session-specific artifacts: hardcoded net names, ephemeral GUI coordinates, and polling loops. The compiler sanitizes these traces and lifts literals that match user/agent inputs into typed parameters.

Python
import re
from typing import Dict, Any, Tuple
from pydantic import BaseModel

class CrystallizedSkillSpec(BaseModel):
    skill_name: str
    description: str
    app_target: str                    # "vivado_2025.1" | "verdi_2024.09"
    tcl_template: str                  # Parameterized script with {{param}} placeholders
    parameters: Dict[str, Dict[str, Any]]  # JSON Schema property definitions
    verification_cmd: str              # Tcl command returning 0/1 or status string

class TclTrajectoryCompiler:
    # Commands that only affect GUI viewport state and should be stripped
    NOISE_PATTERNS = [
        r"^highlight_objects\b.*",
        r"^unhighlight_objects\b.*",
        r"^show_objects\b.*-name\s+find_\d+",
        r"^wvSetCursor\b.*",
    ]

    def compile_trajectory(
        self,
        steps: List[CorrelatedStep],
        task_prompt: str,
        extracted_entities: Dict[str, str] # e.g., {"clk_pin": "u_pll/clk_out1", "period_ns": "5.0"}
    ) -> CrystallizedSkillSpec:
        raw_commands: List[str] = []
        for step in steps:
            for line in step.journal_lines:
                if not any(re.match(pat, line) for pat in self.NOISE_PATTERNS):
                    raw_commands.append(line)

        # Collapse redundant sequential selections (keep only the last selection before an action)
        deduped_commands = self._collapse_redundant_selections(raw_commands)
        script_body = "\n".join(deduped_commands)

        # Replace entity literals with Jinja-style {{param_name}} placeholders
        param_schema: Dict[str, Dict[str, Any]] = {}
        # Sort by length descending so substrings don't clobber longer identifiers
        for param_key, literal_val in sorted(extracted_entities.items(), key=lambda x: -len(str(x[1]))):
            escaped_val = re.escape(str(literal_val))
            if re.search(escaped_val, script_body):
                script_body = re.sub(escaped_val, f"{{{{{param_key}}}}}", script_body)
                param_schema[param_key] = {
                    "type": "number" if self._is_numeric(literal_val) else "string",
                    "description": f"Parameterized from literal '{literal_val}' in task: {task_prompt}",
                    "default": float(literal_val) if self._is_numeric(literal_val) else literal_val
                }

        # Wrap asynchronous commands (e.g., launch_runs) with deterministic blocking waits
        script_body = self._inject_sync_barriers(script_body)

        return CrystallizedSkillSpec(
            skill_name="vivado_create_custom_clock",
            description=f"Deterministic Tcl skill crystallized from GUI trajectory: {task_prompt}",
            app_target="vivado_2025.1",
            tcl_template=script_body,
            parameters=param_schema,
            verification_cmd="llength [get_clocks -quiet]"
        )

    def _collapse_redundant_selections(self, cmds: List[str]) -> List[str]:
        result = []
        for i, cmd in enumerate(cmds):
            if cmd.startswith("select_objects") and i + 1 < len(cmds) and cmds[i + 1].startswith("select_objects"):
                continue
            result.append(cmd)
        return result

    def _inject_sync_barriers(self, script: str) -> str:
        # If trajectory contains async run launches, append Vivado's blocking wait_on_run
        pattern = r"(launch_runs\s+([^\s]+).*)"
        return re.sub(pattern, r"\1\nwait_on_run \2", script)

    @staticmethod
    def _is_numeric(val: str) -> bool:
        try:
            float(val)
            return True
        except ValueError:
            return False
C. Dynamic MCP Tool Registry
Once compiled, the skill is dynamically registered into the live MCP server and persisted to a local SQLite/JSON skill store. The MCP server issues a notifications/tools/list_changed event so the LLM orchestrator immediately sees the new zero-token tool.

Python
from mcp.server import Server
from mcp.types import Tool, TextContent
import jinja2

class DynamicSkillRegistry:
    def __init__(self, mcp_server: Server, tcl_rpc_client: Any):
        self.mcp = mcp_server
        self.tcl_rpc = tcl_rpc_client
        self.skills: Dict[str, CrystallizedSkillSpec] = {}
        self._jinja = jinja2.Environment(autoescape=False)

    async def register_skill(self, spec: CrystallizedSkillSpec, session: Any) -> None:
        self.skills[spec.skill_name] = spec
        # Notify connected MCP client (e.g., Claude Desktop / Orchestrator) that tool list updated
        await session.send_tool_list_changed()

    def get_mcp_tools(self) -> List[Tool]:
        tools = []
        for name, spec in self.skills.items():
            tools.append(
                Tool(
                    name=name,
                    description=f"[CRYSTALLIZED 0-TOKEN SKILL] {spec.description}",
                    inputSchema={
                        "type": "object",
                        "properties": spec.parameters,
                        "required": list(spec.parameters.keys()),
                    },
                )
            )
        return tools

    async def execute_skill(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        spec = self.skills[name]
        template = self._jinja.from_string(spec.tcl_template)
        rendered_tcl = template.render(**arguments)

        # Execute directly over Vivado/Verdi Tcl socket (0 screenshots, 0 GUI clicks)
        exec_result = await self.tcl_rpc.eval(rendered_tcl)
        verify_result = await self.tcl_rpc.eval(spec.verification_cmd)

        return [TextContent(
            type="text",
            text=f"Skill '{name}' executed.\nOutput: {exec_result}\nVerification: {verify_result}"
        )]
2. P0: Event-Driven Quiescence & Semantic Verification Engine
A. X11 / Linux Compositor Integration (XDamage + XFixes via ctypes)
Using ctypes against libX11.so.6, libXdamage.so.1, and libXfixes.so.3 gives sub-millisecond visibility into screen buffer dirtiness and cursor busy states without capturing full screenshots.

Python
import ctypes
import ctypes.util
from ctypes import c_int, c_ulong, c_uint, c_short, c_ushort, c_char_p, POINTER, Structure

class XRectangle(Structure):
    _fields_ = [("x", c_short), ("y", c_short), ("width", c_ushort), ("height", c_ushort)]

class XFixesCursorImage(Structure):
    _fields_ = [
        ("x", c_short), ("y", c_short),
        ("width", c_ushort), ("height", c_ushort),
        ("xhot", c_ushort), ("yhot", c_ushort),
        ("cursor_serial", c_ulong),
        ("pixels", POINTER(c_ulong)),
        ("atom", c_ulong),
        ("name", c_char_p),
    ]

class X11QuiescenceMonitor:
    BUSY_CURSOR_NAMES = {"watch", "wait", "progress", "left_ptr_watch", "clock", "spinning"}

    def __init__(self, display_name: Optional[bytes] = None, window_id: Optional[int] = None):
        self.x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
        self.xdamage = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xdamage"))
        self.xfixes = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xfixes"))

        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XDefaultRootWindow.restype = c_ulong
        self.xfixes.XFixesGetCursorImage.restype = POINTER(XFixesCursorImage)
        self.xdamage.XDamageCreate.restype = c_ulong
        self.xfixes.XFixesCreateRegion.restype = c_ulong
        self.xfixes.XFixesFetchRegion.restype = POINTER(XRectangle)

        self.dpy = self.x11.XOpenDisplay(display_name)
        if not self.dpy:
            raise RuntimeError("Cannot connect to X11 display")

        self.target_win = window_id or self.x11.XDefaultRootWindow(self.dpy)
        # XDamageReportRawRectangles = 0
        self.damage_handle = self.xdamage.XDamageCreate(self.dpy, c_ulong(self.target_win), c_int(0))
        self.region_handle = self.xfixes.XFixesCreateRegion(self.dpy, None, c_int(0))

    def get_cursor_state(self) -> Tuple[str, int]:
        """Returns (cursor_semantic_name, cursor_serial_hash)."""
        cursor_ptr = self.xfixes.XFixesGetCursorImage(self.dpy)
        if not cursor_ptr:
            return ("unknown", 0)
        try:
            img = cursor_ptr.contents
            name = img.name.decode("utf-8", errors="ignore").lower() if img.name else ""
            serial = int(img.cursor_serial)
            return (name, serial)
        finally:
            self.x11.XFree(cursor_ptr)

    def is_cursor_busy(self) -> bool:
        name, _ = self.get_cursor_state()
        return any(busy in name for busy in self.BUSY_CURSOR_NAMES)

    def consume_damage_area(self) -> int:
        """Atomically copies and clears accumulated XDamage regions, returning total dirty pixels."""
        self.x11.XSync(self.dpy, c_int(0))
        # XDamageSubtract copies damaged region into region_handle and clears server-side damage
        self.xdamage.XDamageSubtract(self.dpy, c_ulong(self.damage_handle), c_ulong(0), c_ulong(self.region_handle))
        
        nrects = c_int(0)
        rects_ptr = self.xfixes.XFixesFetchRegion(self.dpy, c_ulong(self.region_handle), ctypes.byref(nrects))
        if not rects_ptr or nrects.value == 0:
            return 0

        total_area = 0
        try:
            for i in range(nrects.value):
                r = rects_ptr[i]
                # Filter out tiny blinking cursor rectangles (typically <= 2x20 px)
                if r.width * r.height > 64:
                    total_area += (r.width * r.height)
            return total_area
        finally:
            self.x11.XFree(rects_ptr)
B. Post-Condition Contract Schema
Every mutating GUI tool accepts an optional PostConditionContract so the controller can deterministically verify whether the intended semantic effect occurred.

Python
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

class StateAssertionType(str, Enum):
    AT_SPI_STATE_PRESENT = "at_spi_state_present"   # e.g., CHECKED, EXPANDED, FOCUSED
    AT_SPI_STATE_ABSENT = "at_spi_state_absent"
    WINDOW_SPAWNED = "window_spawned"               # New transient modal or top-level window
    WINDOW_CLOSED = "window_closed"
    TEXT_APPEARED = "text_appeared"                 # OCR or AT-SPI text in target ROI
    SUBPANE_SSIM_DROP = "subpane_ssim_drop"         # Structural change in specific canvas ROI

class PostConditionAssertion(BaseModel):
    assertion_type: StateAssertionType
    target_role: Optional[str] = None               # e.g., "push_button", "dialog", "menu_item"
    target_name_regex: Optional[str] = None         # e.g., ".*Synthesis Complete.*"
    target_subpane_id: Optional[str] = None         # e.g., "waveform_canvas", "tcl_console"
    expected_state: Optional[str] = None            # e.g., "EXPANDED", "CHECKED"
    min_ssim_delta: float = Field(default=0.08, ge=0.0, le=1.0)

class PostConditionContract(BaseModel):
    assertions: List[PostConditionAssertion]
    require_all: bool = True                        # AND vs OR evaluation across assertions
    initial_reaction_timeout_ms: int = 1500         # Max wait for first damage/AT-SPI event
    quiescence_window_ms: int = 180                 # Continuous quiet period required
    max_total_timeout_ms: int = 15000               # Hard ceiling before escalation/async handoff
    allow_async_promotion: bool = True              # Promote to background job if busy cursor persists
C. Adaptive Timeout & Quiescence State Machine
                      +-------------------+
                      |    DISPATCHED     | (Action injected into X11/UIA)
                      +---------+---------+
                                |
          +---------------------+---------------------+
          | First Damage > 64px | No Damage within    |
          | or AT-SPI Event     | initial_timeout_ms  |
          v                     v                     |
+-----------------------+   +-----------------------+ |
|  DAMAGE_ACCUMULATION  |   | NO_REACTION_DETECTED  | |
+-----------+-----------+   +-----------+-----------+ |
            |                           |             |
            | Damage == 0 &             |             |
            | Cursor != BUSY            |             |
            v                           |             |
+-----------------------+               |             |
|       SETTLING        |---------------+-------------+
+-----------+-----------+  (If Damage spikes, loop back to DAMAGE_ACCUMULATION)
            |
            | Quiet for quiescence_window_ms (180ms)
            v
+-----------------------+
|       QUIESCENT       |
+-----------+-----------+
            |
            | Run PostConditionContract Evaluators + Obstruction Check
            +--------------------+--------------------+
            |                    |                    |
            v                    v                    v
+-------------------+  +-------------------+  +-----------------------+
| CONTRACT_VERIFIED |  | OBSTRUCTED_BY_MOD |  |    CONTRACT_FAILED    |
+-------------------+  +-------------------+  +-----------------------+
Python
import asyncio
from enum import auto

class ExecutionPhase(Enum):
    DISPATCHED = auto()
    DAMAGE_ACCUMULATION = auto()
    SETTLING = auto()
    QUIESCENT = auto()
    ASYNC_PROMOTED = auto()
    CONTRACT_VERIFIED = auto()
    OBSTRUCTED_BY_MODAL = auto()
    CONTRACT_FAILED = auto()

async def run_quiescence_loop(
    monitor: X11QuiescenceMonitor,
    contract: PostConditionContract,
    verifier_fn,
    modal_detector_fn
) -> Tuple[ExecutionPhase, Dict[str, Any]]:
    t_start = time.monotonic()
    phase = ExecutionPhase.DISPATCHED
    quiet_since: Optional[float] = None
    poll_interval = 0.025  # 25ms compositor check

    # Clear stale pre-action damage
    monitor.consume_damage_area()

    while True:
        now = time.monotonic()
        elapsed_ms = (now - t_start) * 1000.0

        damaged_px = monitor.consume_damage_area()
        cursor_busy = monitor.is_cursor_busy()

        if phase == ExecutionPhase.DISPATCHED:
            if damaged_px > 0 or cursor_busy:
                phase = ExecutionPhase.DAMAGE_ACCUMULATION
            elif elapsed_ms >= contract.initial_reaction_timeout_ms:
                # Even with 0 pixel damage, check if AT-SPI state already satisfied contract
                if await verifier_fn(contract):
                    return ExecutionPhase.CONTRACT_VERIFIED, {"elapsed_ms": elapsed_ms}
                return ExecutionPhase.CONTRACT_FAILED, {"reason": "Zero UI reaction within initial window"}

        elif phase == ExecutionPhase.DAMAGE_ACCUMULATION:
            if damaged_px == 0 and not cursor_busy:
                phase = ExecutionPhase.SETTLING
                quiet_since = now
            elif elapsed_ms >= contract.max_total_timeout_ms:
                if cursor_busy and contract.allow_async_promotion:
                    return ExecutionPhase.ASYNC_PROMOTED, {"reason": "Persistent busy cursor; promoted to async job monitor"}
                return ExecutionPhase.CONTRACT_FAILED, {"reason": "UI failed to settle before max timeout"}

        elif phase == ExecutionPhase.SETTLING:
            if damaged_px > 0 or cursor_busy:
                phase = ExecutionPhase.DAMAGE_ACCUMULATION
                quiet_since = None
            elif (now - quiet_since) * 1000.0 >= contract.quiescence_window_ms:
                phase = ExecutionPhase.QUIESCENT
                break

        await asyncio.sleep(poll_interval)

    # Phase == QUIESCENT: First check for unexpected modal obstructions
    modal_info = await modal_detector_fn()
    if modal_info is not None:
        return ExecutionPhase.OBSTRUCTED_BY_MODAL, {"modal": modal_info, "elapsed_ms": (time.monotonic() - t_start) * 1000.0}

    # Evaluate semantic post-condition assertions
    if await verifier_fn(contract):
        return ExecutionPhase.CONTRACT_VERIFIED, {"elapsed_ms": (time.monotonic() - t_start) * 1000.0}

    return ExecutionPhase.CONTRACT_FAILED, {"reason": "UI quiescent, but post-condition assertions failed"}
3. P3: Semantic Modal Triage & Policy Router (classify_obstruction)
A. Modal Risk Classification Taxonomy
Risk Tier	Classification	Examples in EDA / IDE / Browser	Automated Policy Action
Tier 0	BENIGN_DISMISSIBLE	"Tip of the Day", cookie consent banners, telemetry opt-ins, "What's New in Vivado 2025.1".	Auto-Dismiss: Click explicit close (X), Close, or Don't show again + OK. Log silently.
Tier 1	INFORMATIVE_ACK	"Synthesis Completed Successfully", "DRC completed with 0 errors", single-button OK info dialogs.	Auto-Acknowledge & Extract: Scrape dialog text + metrics, click OK, attach extracted summary to tool output.
Tier 2	WORKFLOW_BRANCHING	"Synthesis is out-of-date. Run Synthesis before Implementation?", "Save changes to constraints before running?".	Halt & Escalate: Never auto-click. Return structured ModalEscalationPayload to the LLM planner with semantic button descriptors.
Tier 3	DESTRUCTIVE_OR_SYSTEM	"Overwrite existing XDC file?", "FlexLM License Server checkout failed — Retry or Terminate?", "Delete synthesized netlist?".	Hard Freeze & Checkpoint: Block execution, capture sub-pane screenshot of modal, return high-priority alert to orchestrator.
B. Escalation Payload Schema & Decision Router
When OBSTRUCTED_BY_MODAL triggers, the MCP inspects the transient window (WM_TRANSIENT_FOR) via AT-SPI2 (falling back to local OCR) and runs deterministic heuristic rules before deciding whether to auto-resolve or return an escalation payload.

Python
from typing import Literal

class ModalRiskTier(str, Enum):
    BENIGN_DISMISSIBLE = "BENIGN_DISMISSIBLE"
    INFORMATIVE_ACK = "INFORMATIVE_ACK"
    WORKFLOW_BRANCHING = "WORKFLOW_BRANCHING"
    DESTRUCTIVE_OR_SYSTEM = "DESTRUCTIVE_OR_SYSTEM"

class ModalButtonOption(BaseModel):
    button_id: str                     # e.g., "btn_0"
    label: str                         # e.g., "Overwrite", "Cancel", "Save As..."
    bbox: Tuple[int, int, int, int]    # (x, y, w, h) screen coordinates
    is_default_focused: bool
    inferred_consequence: str          # Heuristic hint: "Destructive state mutation" | "Safe abort"

class ModalEscalationPayload(BaseModel):
    status: Literal["ACTION_BLOCKED_BY_MODAL"] = "ACTION_BLOCKED_BY_MODAL"
    window_title: str
    dialog_body_text: str
    risk_tier: ModalRiskTier
    detected_buttons: List[ModalButtonOption]
    recommended_action_tool: str = "resolve_modal_dialog"
    subpane_crop_base64: Optional[str] = None   # Included ONLY if OCR confidence < 0.85

class SemanticModalRouter:
    DESTRUCTIVE_KEYWORDS = re.compile(
        r"\b(overwrite|delete|remove|discard|lose changes|force|corrupt|license|flexlm|expired|terminate|kill)\b",
        re.IGNORECASE
    )
    BRANCHING_KEYWORDS = re.compile(
        r"\b(out-of-date|unsaved|modified|save changes|re-run|launch|conflict|merge)\b",
        re.IGNORECASE
    )
    BENIGN_TITLES = re.compile(
        r"\b(tip of the day|welcome|what's new|cookie|privacy|telemetry|feedback)\b",
        re.IGNORECASE
    )

    def classify_and_route(
        self,
        window_title: str,
        body_text: str,
        buttons: List[ModalButtonOption]
    ) -> Tuple[ModalRiskTier, Optional[ModalButtonOption], Optional[ModalEscalationPayload]]:
        """
        Returns (tier, auto_click_button_if_safe, escalation_payload_if_unsafe).
        """
        combined_text = f"{window_title} {body_text}"
        btn_labels = [b.label.lower().strip() for b in buttons]

        # 1. Check Tier 3: Destructive or System/License failures (Highest Priority)
        if self.DESTRUCTIVE_KEYWORDS.search(combined_text):
            return (
                ModalRiskTier.DESTRUCTIVE_OR_SYSTEM,
                None,
                ModalEscalationPayload(
                    window_title=window_title,
                    dialog_body_text=body_text,
                    risk_tier=ModalRiskTier.DESTRUCTIVE_OR_SYSTEM,
                    detected_buttons=buttons
                )
            )

        # 2. Check Tier 0: Benign Dismissible
        if self.BENIGN_TITLES.search(window_title):
            safe_btn = next((b for b in buttons if b.label.lower() in {"close", "ok", "got it", "dismiss"}), None)
            if safe_btn:
                return (ModalRiskTier.BENIGN_DISMISSIBLE, safe_btn, None)

        # 3. Check Tier 1: Single-button Informative Acknowledgment
        if len(buttons) == 1 and btn_labels[0] in {"ok", "close", "acknowledge"}:
            if not self.BRANCHING_KEYWORDS.search(combined_text):
                return (ModalRiskTier.INFORMATIVE_ACK, buttons[0], None)

        # 4. Default to Tier 2: Workflow Branching (Multi-button decision)
        return (
            ModalRiskTier.WORKFLOW_BRANCHING,
            None,
            ModalEscalationPayload(
                window_title=window_title,
                dialog_body_text=body_text,
                risk_tier=ModalRiskTier.WORKFLOW_BRANCHING,
                detected_buttons=buttons
            )
        )
When the router returns an escalation payload, the MCP server exposes a dedicated resolve_modal_dialog(button_id: str) tool. This forces the LLM orchestrator to explicitly reason about the dialog text and select a specific button_id in its next turn—achieving 0 visual tokens for standard text dialogs while guaranteeing complete safety against accidental destructive clicks.

Want me to design the P1 Local Neural Grounding Sidecar and Virtual DOM schema next?

Yes




Gemini is AI and can make mistakes.