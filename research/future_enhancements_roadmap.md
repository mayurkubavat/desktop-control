---
title: Vision Control MCP Next-Generation Enhancement Roadmap
tags:
  - roadmap/future
  - architecture/agentic
  - technique/caching
  - technique/macros
  - technique/obstruction-handling
aliases:
  - Enhancement Roadmap
  - Next Steps for Vision MCP
created: 2026-10-25
updated: 2026-10-25
related:
  - "[[INDEX]]"
  - "[[ai_orchestrators_and_vision_control]]"
  - "[[tool_ecosystem_comparison]]"
  - "[[token_optimization_and_cost_dynamics]]"
---

# Vision Control MCP Next-Generation Enhancement Roadmap

Based on empirical research with Gemini (Flash & Argon), live desktop automation sessions with AMD Xilinx Vivado 2025.1, and the successful completion of the core 5-Phase Vision MCP 2.0 platform, this roadmap tracks completed milestones and outlines the remaining high-impact engineering frontiers for future implementation.

---

## 🗺️ Architectural Roadmap & Milestone Status

```mermaid
flowchart TD
    subgraph Completed Milestones: Vision MCP 2.0 Core
        M1["✅ 1. Self-Healing Action Cache<br/>(Commit aed5eda: dHash + localized drift recovery)"]
        M2["✅ 2. Autonomous Obstruction Interceptor<br/>(dismiss_obstructions & modal triage)"]
        M3["✅ 3. Local Macro Trajectory Dispatcher<br/>(Commit a33d6db: execute_trajectory, 14.4k tokens saved)"]
        M4["✅ 4. Per-Window & Anchor Sub-Pane Perception<br/>(capture_window & capture_pane: 85% token reduction)"]
        M5["✅ 5. Neural Fast-Path Backbone<br/>(Commit 81a07bf: FastONNXUIDetector, 8.34ms)"]
        M6["✅ 6. Local Multimodal Sidecar<br/>(Commit b9ac0cc: Gemma 3 on Vulkan iGPU 17.2GB VRAM)"]
    end

    subgraph Frontier 1: Domain EDA Expansion (Next Up)
        F1["7. Synopsys Verdi Automation Plugin<br/>(nWave, nTrace, nSchema & novas.cmd correlation)"]
    end

    subgraph Frontier 2: Developer Ergonomics & Diagnostics
        F2["8. Interactive SoM Visual Debugger<br/>(Overlay vDOM bounding boxes & node IDs in real-time)"]
    end

    subgraph Frontier 3: Resilience & High-Throughput IPC
        F3["9. State Checkpointing & Rollback Engine<br/>(Transactional undo on assertion failure)"]
        F4["10. C-Native /dev/shm Zero-Copy Stream Daemon<br/>(Lock-free atomic seqlock frame pump at 60 FPS)"]
    end

    subgraph Frontier 4: Production Deployment
        F5["11. Global Antigravity MCP Packaging<br/>(Production config, auto-sidecar launch, /vision command)"]
    end

    M1 & M3 --> F1
    M4 & M5 --> F2
    M3 --> F3
    M5 & M6 --> F4
    M3 & F1 --> F5
```

---

## 🏁 Completed Milestones

* [x] **1. Self-Healing Action & Locator Cache (`ActionCache`)** — *Implemented in commit `aed5eda`*
  * Window movement re-projection (`window_offset`, `window_relative_bbox`).
  * Sub-millisecond pre-flight visual dHash verification ($<0.5\text{ ms}$, $d \le 6$).
  * Localized neighborhood drift recovery via `cv2.matchTemplate` ($\pm 60\text{ px}$ radius, $\ge 0.78$ score).
* [x] **2. Autonomous Obstruction Interceptor (`ObstructionHandler`)** — *Implemented in `server.py` & `modal_triage.py`*
  * Non-destructive dismissal strategies (`dismiss_obstructions`, `resolve_modal_dialog`).
  * Automated screensaver/lock-screen bypass and popup suppression.
* [x] **3. Local Macro & Trajectory Dispatcher (`execute_trajectory`)** — *Implemented in commit `a33d6db`*
  * Declarative 17-primitive dispatcher executing at native OS speeds ($5.76\text{ s}$ for 9 steps, 0 intermediate tokens).
  * Jinja2 parameter interpolation, per-step delta verification, and post-condition assertions.
  * Validated live on Vivado 2025.1 CDC FIFO simulation GUI, saving 14,400 multimodal cloud tokens.
* [x] **4. Per-Window & Anchor-Relative Sub-Pane Perception (`capture_pane`)** — *Implemented in `vision_mcp/vdom/layout.py`*
  * Dynamic boundary solvers with anchor-relative constraints (`tab_item[name*="Tcl Console"]`, `:sash_divider`).
  * Sub-pane isolation (`waveform_canvas`, `tcl_console`, `flow_navigator`), slashing visual tokens by up to 90%.
* [x] **5. Neural Fast-Path Backbone (`FastONNXUIDetector`)** — *Implemented in commit `81a07bf`*
  * ONNX Runtime with CPU AVX-512 acceleration, letterbox scaling, anchor decoding, and vectorized NMS.
  * End-to-end inference latency: **8.34 ms** (~120 FPS).
* [x] **6. Local Multimodal Sidecar (`Gemma3MultimodalSidecar`)** — *Implemented in commit `b9ac0cc`*
  * Local `gemma3:4b` VLM and `gemma3:1b` LLM via Ollama on Vulkan iGPU with 17.2 GiB VRAM allocation.

---

## 🚀 Backlog: Next Implementation Frontiers (To Do Later)

### 7. Synopsys Verdi Automation Plugin (`vision_mcp/plugins/verdi.py`)
* **Objective**: Extend Vision MCP's EDA domain coverage beyond Vivado into Synopsys Verdi, the semiconductor industry standard for debug and waveform analysis.
* **Architecture**:
  * Inherits from [`BaseAppPlugin`](file:///home/mk/DV/git/Vision/vision_mcp/plugins/base.py#L31).
  * App identifier: `verdi` (window title match: `Verdi.*\[.*\]`, `nWave.*`, `nTrace.*`).
  * Sub-Pane Layout Specifications:
    * `nTrace`: Source code hierarchy, signal driver/load browser, and active line tracking.
    * `nWave`: Waveform display area, signal value columns, cursor delta measurements (`C1`, `C2`).
    * `nSchema`: Gate-level and RTL schematic navigation viewer.
    * `temporal_flow_view`: Clock-domain crossing and causality transaction flow.
  * Declarative Feature Descriptors:
    * `verdi.trace_driver` (`Ctrl+D`): Traces the active signal driver to source RTL.
    * `verdi.trace_load` (`Ctrl+L`): Traces signal destinations and fanouts.
    * `verdi.zoom_fit` (`F` key): Zooms nWave to full simulation time range.
    * `verdi.add_signal`: Dispatches signal addition via Tcl CLI or drag-and-drop.
    * `verdi.command_exec`: Dispatches deterministic commands to Verdi Tcl console.
  * Journal Synchronization:
    * Integrate [`JournalCorrelator`](file:///home/mk/DV/git/Vision/vision_mcp/crystallization/correlator.py#L25) with `novas.cmd` / `verdi.cmd` journal files for zero-token GUI-to-Tcl skill crystallization.

---

### 8. Interactive SoM Visual Debugger & vDOM Overlay (`debug_vdom_overlay`)
* **Objective**: Provide an interactive visual diagnostic tool for human engineers and agent developers to visually audit grounded elements, vDOM hierarchy trees, and bounding box alignments in real time.
* **Architecture**:
  * Tool endpoint: `mcp_vision_control_debug_vdom_overlay(window_id, format='annotated_image'|'html_inspector')`.
  * Visual Rendering:
    * Renders numbered bounding box badges with role color-coding:
      * Green: Hybrid (AT-SPI2 + Visual Proposal match).
      * Blue: Pure Accessible (AT-SPI2).
      * Purple: Neural Fast-Path proposal (ONNX).
      * Amber: Localized template match.
    * Generates a lightweight standalone interactive HTML/SVG overlay viewer with pan/zoom, node tree inspection, and coordinate copy-to-clipboard.

---

### 9. State Checkpointing & Transactional Rollback Engine (`StateManager`)
* **Objective**: Guard against destructive actions or dead-end navigation by providing transactional checkpointing and automated rollback primitives.
* **Architecture**:
  * Core class: `TransactionManager` inside `vision_mcp/agent_loop/transactions.py`.
  * Pre-Action Snapshot: Captures lightweight window state, active document tabs, and undo-stack depth before entering high-risk steps.
  * Rollback Primitives:
    * Standard undo hotkeys (`Ctrl+Z`, `u` in vim, `undo` in EDA consoles).
    * Navigational back-stepping (`Alt+Left`, browser back, window reopen).
    * Scratch directory file rollbacks via Git stash or copy-on-write temp trees.
  * Integration with `execute_trajectory`: If a step with `rollback_on_failure=True` fails post-condition assertions, the engine automatically unwinds previous steps back to the checkpoint.

---

### 10. C-Native `/dev/shm` Zero-Copy Frame Streaming Daemon (`shm_streamer`)
* **Objective**: Replace Python-level framebuffer screenshot captures with a blazing-fast, compiled C/Rust zero-copy memory daemon for continuous 60+ FPS visual perception.
* **Architecture**:
  * Daemon binary: `vision_mcp/bin/shm_streamer` using X11 MIT-SHM extension.
  * Direct X11 Shared Memory: Directly maps X11 root window pixmaps into `/dev/shm/vision_mcp_fb` using a lock-free atomic seqlock ring buffer.
  * Performance Target: Sub-1ms frame capture latency (down from 15-20ms with PIL/mss), enabling continuous visual servoing, motion tracking, and instant delta detection with zero CPU overhead.

---

### 11. Global Antigravity MCP Packaging & Production Installation
* **Objective**: Package the Vision Control MCP server into an autonomous plug-and-play extension for the user's global Antigravity installation.
* **Architecture**:
  * MCP Server Manifest: Register `vision-control` in `~/.gemini/antigravity-cli/mcp_config.json` pointing to `/home/mk/DV/git/Vision/.venv/bin/python -m vision_mcp.server`.
  * Background Sidecar Daemon Auto-Start: Launch Ollama (`OLLAMA_IGPU_ENABLE=1`) and Gemma 3 sidecars automatically when the MCP server initializes.
  * Antigravity Customization:
    * Provide a customized slash command `/vision` in `~/.gemini/antigravity-cli/builtin/commands/vision.md` to trigger vision-guided desktop workflows.
    * Package skill instructions in `~/.gemini/config/skills/vision-control/` with automated tool discovery.
