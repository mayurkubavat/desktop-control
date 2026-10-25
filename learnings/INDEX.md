---
title: Vision Control Operational Learnings & Recipes Index
tags:
  - type/index
  - domain/learnings
  - domain/troubleshooting
  - scope/mcp
aliases:
  - Learnings MOC
  - Operational Runbook
created: 2026-10-25
updated: 2026-10-25
---

# 🛠️ Vision Control Operational Learnings & Recipes Index

This repository contains practical discoveries, troubleshooting runbooks, and hardened execution patterns learned while developing and testing the **Vision Control MCP** on real desktop and browser environments.

---

## 🗺️ Map of Learnings & Recipes

### 1. Window & Display Management
* [[linux_desktop_window_management|Linux Desktop & X11 Window Management]]
  * EWMH `_NET_ACTIVE_WINDOW` ClientMessage protocol fix.
  * Direct X11 window stack-raising (`stack_mode=X.Above`) and input focus fallback.
  * Recovering from minimized windows via panel taskbar element clicks.

### 2. Browser Navigation & Web App Interaction
* [[browser_interaction_recipes|Browser Automation & Gemini Web Recipes]]
  * Handling browser permission popups ("Show notifications").
  * Interacting with dynamic dropdowns (e.g. model selector "Flash-Lite" $\rightarrow$ "4 Argon").
  * Cadence-aware text entry and Enter key submission.
* [[verdi_and_complex_eda_ui_automation|Browser Obstructions, Taskbar Focus & EDA UI Automation]]
  * Dismissing Chrome permission popups at calibrated coordinates with delta confirmation.
  * Restoring focus via bottom panel taskbar clicks when terminal commands steal X11 focus.
  * Streaming generation heuristics and multi-page content scrolling.
  * Visual ergonomics, hotkey dispatching, and value column reading for EDA tools (Verdi).
* [[vivado_gui_waveform_automation|AMD/Xilinx Vivado GUI Waveform Automation & Sub-Pane Perception]]
  * Operational runbook for automating Vivado 2025.1 GUI on Linux.
  * SystemVerilog FIFO simulation, tab switching, and waveform toolbar zoom-fit mechanics.
  * High-efficiency sub-pane ROI perception slashing token consumption by 82.4%.
* [[vivado_ui_layout_customization_for_dv|Vivado UI Layout Customization for DV Engineers: dv-view Setup & Persistence]]
  * Visual exploration and spatial reorganization of Vivado GUI for verification engineers.
  * Collapsing Flow Navigator, docking Call Stacks, Stack Frames, Locals, Objects, and Scope.
  * Saving and persisting `dv-view` to `~/.Xilinx/Vivado/2025.1/data/layouts/dv-view.layout`.

### 3. Agentic Performance & Token Optimization
* [[zero_token_element_discovery|Zero-Token Element Discovery & Compound Actions]]
  * When to use `find_element` and `find_and_click` before taking full screenshots.
  * Using `click_and_type` to combine 4 actions into a single atomic step.
* [[gemini_web_clipboard_extraction_recipe|Zero-Token Research Extraction: Gemini Web Copy Button Recipe]]
  * Harvesting multi-page markdown responses with zero visual tokens by clicking the response footer copy icon.
  * Desktop HAL and X11 clipboard integration pattern for on-the-go tool research.
  * Multi-turn autonomous Q&A orchestration with Gemini 4 Argon via background xclip, xtest, and settled-state diffing.
* [[visual_delta_verification|Visual Delta Verification Tuning]]
  * Settle time calibration (`settle_time_sec=0.25`).
  * Interpreting $\Delta_{ratio}$ to prevent action cascading.

---

## 🔗 Related Knowledge Repositories
* [[../research/INDEX|Theoretical & Architectural Research Library]] — End-to-end system architectures, grounding models, and comparative benchmark evaluations.
* [[../references/README|Reference MCP Codebases & Analysis]] — Upstream architectural breakdowns and source code for Microsoft Playwright MCP and Chrome DevTools MCP.
