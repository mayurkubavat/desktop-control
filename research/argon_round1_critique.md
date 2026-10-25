The Vision Control MCP architecture demonstrates strong systems engineering—particularly the hybrid AT-SPI2/CV grounding, token-slashing sub-pane perception, and the hybrid GUI/Tcl scripting approach for EDA tools. However, transitioning from reliable short-horizon execution to 100% completion accuracy across 100+ step workflows in heavyweight applications like Synopsys Verdi and AMD Vivado exposes fundamental limits in reactive, pixel-diff-driven architectures.

1. Architectural Critique & Blindspots
The 250ms Settle-Time & Delta_ratio Fallacy
False Positives (Ambient Noise): Professional apps feature blinking cursors, oscillating waveform clocks, live resource monitors, and animated progress spinners. A raw pixel Delta_ratio will register greater than zero even when an action fails or hits a dead zone.

False Negatives (Latent & Sub-Threshold Reactions): In Vivado or Verdi, clicking "Run Synthesis" or loading a 50GB FSDB waveform might take 2–10 seconds just to spawn a modal or update a status bar, completely missing the 250ms window. Conversely, toggling a small toolbar icon ("Snap to Grid") or changing a state in a background tab produces a tiny pixel delta that falls below noise thresholds.

Semantic Blindness: Delta_ratio confirms change, not intent. If the agent intends to click "Run" but hits "Cancel" due to a layout shift, the screen changes significantly (Delta_ratio passes), and the controller proceeds down a corrupted state path.

Classical CV & AT-SPI2 Fragility in EDA/CAD
The Dense Canvas Problem: Canny edge detection + MSER text proposals fail on high-density custom canvases. In a Verdi schematic view or Vivado floorplanner, overlapping routing wires, bus labels, and logic gates create thousands of intersecting contours, shattering bounding box proposals and overwhelming IoU deduplication.

AT-SPI2 Thread Locking & Staleness: Qt and Java Swing apps (which underpin most EDA tools) notoriously implement broken or lazy accessibility trees. Querying deep AT-SPI2 trees over D-Bus on a complex schematic can freeze the target application's UI thread for seconds or return off-screen/stale coordinates for virtualized scroll lists.

Scale & Theme Variance: Normalized Cross-Correlation (template matching) breaks across DPI scaling (X11 vs. Wayland fractional scaling), custom dark/light EDA themes, and anti-aliasing variations.

Autonomous Defense (dismiss_obstructions) as a Footgun
Destructive Auto-Dismissal: In consumer browsers, dismissing popups is safe. In professional tools, modal dialogs carry critical state branches: "Synthesis out of date. Force bitgen anyway?", "License server lost—retry or exit?", or "Overwrite constraints file?". Blindly dismissing or clicking the default button on these modals will silently corrupt a 2-hour engineering workflow.

Sub-Pane Coordinate Drift
Docking panels in IDEs and EDA suites are dynamic. Resizing a main window, dragging a sash separator, or undocking a waveform_canvas invalidates static ROI definitions and cached coordinates instantly.

2. Next-Generation Perception Paradigms
To achieve near-zero token overhead with high reliability, move from static frame capture to event-driven, multi-tiered semantic perception:

Perception Tier	Mechanism	Latency / Cost	Target Use Case
Tier 0: OS/Compositor Hooks	Damage tracking (XDamage / Wayland frame callbacks), mouse cursor shape (XFixes), OS thread CPU/IO monitoring	< 5ms / 0 Tokens	Replacing fixed 250ms sleep with dynamic UI quiescence detection.
Tier 1: Semantic Graph Diffing	Incremental AT-SPI2 / UIA event listeners (object:state-changed, window:activate)	~10ms / 0 Tokens	Tracking focus shifts, menu expansions, and modal spawns without polling.
Tier 2: Local Vision Sidecar	Quantized local models (OmniParser-v2, Florence-2, YOLO-World, PaddleOCR) running on local GPU/NPU	30–80ms / 0 API Tokens	Replacing Canny/MSER for dense canvas icon detection, Set-of-Marks (SoM) generation, and semantic OCR.
Tier 3: Frontier VLM	High-res sub-pane crop + SoM overlay sent to Claude/GPT/Gemini	1–3s / High Token Cost	Exception handling, interpreting complex waveform/schematic graphs, and resolving novel modal dialogs.
Key Paradigm Shifts:
Compositor-Level Quiescence instead of 250ms Sleep: Subscribe to X11 XDamage or PipeWire/Wayland damage regions, combined with process CPU load and cursor icon state (XFixesGetCursorImage). Wait for the cursor to return from watch/wait to arrow and for screen damage events to settle before capturing verification frames.

Lightweight Local Vision Sidecars: Replace brittle Canny/MSER pipelines with a persistent local ONNX/TensorRT sidecar running Florence-2 or fine-tuned YOLOv11-UI. The sidecar continuously converts raw frames into a structured JSON scene graph (bounding boxes, semantic icon labels, OCR text) locally, exposing a zero-token queryable DOM even for pure OpenGL/Vulkan canvases.

Structural & Perceptual Hashing: Replace raw pixel Delta_ratio with region-specific SSIM (Structural Similarity Index) and dHash/pHash inside the target element's bounding box and expected reaction zones (e.g., checking if a button's bevel inverted or a menu tree expanded).

3. State Tracking & Hierarchical Planning
Long-horizon tasks (100+ steps) fail primarily due to context window pollution and irreversible state divergence.

Explicit Application Belief State (World State Graph)
Maintain a structured JSON state machine inside the MCP server rather than relying on the LLM's conversation history to remember UI state:

Window Stack & Modality Graph: Track the exact Z-order of windows, active transient child dialogs (WM_TRANSIENT_FOR), and current focus owner.

Application Mode: Track explicit operational states (e.g., Vivado.State = SYNTHESIS_RUNNING | PROJECT_OPEN | DRC_ERROR_MODAL).

Pre/Post-Condition Contracts: Every MCP tool call should declare expected post-conditions (e.g., click("Open Schematic") 
→ expect_window_title_contains("Schematic") OR expect_pane_visible("schematic_canvas")).

Hierarchical Planning with Transactional Checkpointing
Macro-Planner (Frontier LLM): Decomposes the user prompt into a DAG of 5–15 high-level milestones (e.g., 1. Load Design 
→ 2. Configure Clock Constraints 
→ 3. Run Synthesis 
→ 4. Inspect Timing Report).

Micro-Executor (Local Agent / Small Fast Model): Executes the GUI clicks/Tcl commands to achieve a single milestone, returning only a compressed semantic summary ({"status": "success", "wns": -0.45, "tns": -12.3}) to the Macro-Planner.

State Rollback & Checkpointing: Before executing destructive or multi-step GUI sequences, the MCP plugin triggers native application checkpoints (e.g., write_checkpoint in Vivado, git stash in IDEs, session save in Verdi). If the micro-executor enters an unrecoverable UI state, it rolls back via CLI/Tcl rather than trying to click "Undo" 15 times.

Asynchronous Job Multiplexing
When an action triggers a 20-minute compilation or waveform index:

Transition the MCP task state to ASYNC_WAITING.

Hook into the application's log stream (runme.log in Vivado) or OS child process table (pidstat) rather than taking periodic screenshots of a progress bar.

Emit an MCP notification or webhook back to the orchestrator only when the background process terminates or throws a critical error in the log.

4. Top 5 Concrete Roadmap Recommendations
Priority	Feature / Refactor	Architectural Impact	Implementation Path
P0	Event-Driven Quiescence & Semantic Verification Engine	Eliminates timing flakes, 250ms race conditions, and silent misclicks.	Replace sleep(250ms) + Delta_ratio with XDamage/UIA event listeners + XFixes cursor shape checks. Add post-condition verification assertions (expect_role_change, expect_text_appear) to every action tool.
P1	Local Neural Grounding Sidecar (Replace Canny/MSER)	Unlocks accurate zero-token perception on dense EDA/CAD canvases and custom Qt widgets.	Deploy a quantized OmniParser-v2 / Florence-2 + PaddleOCR local daemon via ONNX Runtime. Fuse its output with AT-SPI2 into a unified, queryable Virtual DOM (vDOM) served via MCP resources.
P2	GUI-to-Script Compiler (Skill Crystallization)	Converts fragile 20-step GUI interactions into 1-step, 100% reliable, 0-token API calls.	Log Tcl/CLI echoes emitted by apps during GUI exploration (Vivado and Verdi echo every GUI click to a journal .jou / .cmd file). Automatically synthesize successful GUI trajectories into reusable parameterized MCP tools.
P3	Semantic Modal Triage (classify_obstruction)	Prevents catastrophic data loss from blind popup dismissal in engineering tools.	Upgrade dismiss_obstructions from an auto-clicker to a policy router: auto-dismiss known benign patterns (cookie banners, tips), but extract text via OCR/AT-SPI2 and escalate unknown system/save/license modals to the planner with structured options.
P4	Dynamic Anchor-Relative Sub-Pane Resolution	Prevents capture_pane and cached coordinates from breaking when windows resize or undock.	Define sub-panes relative to semantic anchors (e.g., "bounded by the 'Tcl Console' tab header on top-left and the main status bar on bottom") or Qt widget object names, recalculating pixel bounds dynamically before every crop.
Want me to design the schema and state machine for the GUI-to-Script Skill Crystallization engine?

Yes
2 / 2




Gemini is AI and can make mistakes.