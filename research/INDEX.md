---
title: Vision Control & AI Orchestration Research Library
tags:
  - type/index
  - domain/vision-control
  - domain/ai-orchestrator
  - scope/mcp
aliases:
  - Vision Research MOC
  - Research Index
created: 2026-10-25
updated: 2026-10-25
---

# 📚 Vision Control & AI Orchestrator Research Library

Welcome to the knowledge base for **Vision Control MCP** and **Multimodal AI Orchestration**. This library documents architectural paradigms, perception grounding benchmarks, tool evaluations, and token efficiency techniques.

All documents follow Obsidian-style knowledge graph formatting with YAML metadata tags, wikilinks (`[[Note Name]]`), and cross-references.

---

## 🗺️ Map of Content (MOC)

### Core Architectural Research
* [[ai_orchestrators_and_vision_control|AI Orchestrators & Vision Control Architectures]]
  * Closed-loop *Reason $\rightarrow$ Act $\rightarrow$ Observe* pipeline.
  * Interaction between Multimodal Orchestrators (VLMs/LAMs) and low-level programmatic runtimes.
* [[perception_grounding_landscape|Perception & Grounding Landscape]]
  * Triple Grounding: Set-of-Marks (SoM), OS Accessibility Trees (AT-SPI2 / UIA / AXUI), and pure Computer Vision.
  * Deep-dive into OmniParser v2, Florence-2, and UI-TARS.
* [[tool_ecosystem_comparison|Tool Ecosystem & Benchmark Comparison]]
  * Comparative matrix: Browser-Use, Stagehand, OSWorld, OmniParser v2, UI-TARS, Playwright MCP, and UiPath.
  * Latency, token consumption, and failure modes across web and desktop workflows.
* [[token_optimization_and_cost_dynamics|Token Optimization & Cost Dynamics]]
  * Overcoming the context-window explosion in long-horizon desktop tasks.
  * Sliding visual windows, delta-patching, semantic pruning, and locator caching.
* [[future_enhancements_roadmap|Next-Generation Enhancement Roadmap]]
  * Six architectural frontiers: Action Caching, Obstruction Interception, Macro Trajectories, Per-Window Perception, State Rollback, and Embedded OCR.
* [[ui_tool_plugin_architecture|UI Tool Plugin Architecture & Consolidated Strategy]]
  * Handling complex applications with 100s of features (EDA tools, IDEs, CAD suites).
  * Declarative Feature Maps, Sub-Pane ROI routing, automated menu traversal, and phased roadmap.
* [[phase2_chrome_browser_tool|Phase 2: Chrome Browser Tool & Plugin Architecture]]
  * Dedicated browser automation plugin combining Playwright/CDP insights with native desktop control.
  * Tab lifecycle, accessibility tree UID addressing, and web application macro recipes.
* [[verdi_tool_features_and_ai_automation|Synopsys Verdi Features & AI Automation Blueprint]]
  * Deep-dive into KDB, FSDB, nTrace, nWave, nSchema, Temporal Flow View, and Transaction debug.
  * Tactical recommendations for AI vision agents automating 100+ feature dense EDA interfaces.
* [[vivado_tool_features_and_ai_automation|Vivado Tool Features & AI Automation Architecture]]
  * AMD/Xilinx Vivado (v2025.1) architecture, `xsim` flow, sub-panes, waveform hotkeys, and Tcl script automation.
  * Synchronous FIFO design specifications, waveform verification checklist, and hybrid Tcl/Vision operation.
* [[next_gen_vision_mcp_gemini_research|Next-Gen Vision Control MCP Architecture: Deep-Dive Research with Gemini 4 Argon]]
  * Multi-turn research dialogue with Gemini 4 Argon on Gemini Web exploring fundamental limits of reactive agents.
  * Comprehensive blueprints for Event-Driven Quiescence (XDamage/XFixes), Skill Crystallization (Journal AST), Semantic Modal Triage, Local Neural vDOM Sidecar, and 5-Phase Roadmap.
* [[argon_round4_gemma3_sidecar|Round 4 Architecture: Local Neural Sidecar & Gemma 3 Multimodal Edge Plugin]]
  * Dual-lane edge architecture: Fast-Path (<30ms YOLOv11s-UI + PP-OCRv4 via TensorRT) vs Slow-Path Cognitive VLM (Gemma 3 4B-IT via llama-server).
  * Why Gemma 3 1B is text-only while 4B-IT provides 256-token SigLIP multimodal vision at ~3.4 GB VRAM footprint.
  * Sub-millisecond BMP shared memory slicing (`/dev/shm`), 64-bit dHash perceptual caching (<0.2ms hits), and GBNF grammar-constrained JSON output.
  * Practical DV case studies: Synopsys Verdi/Vivado waveform X-propagation detection, locked IP hierarchy icons, and schematic DRC pin grounding.
* [[macos_automation_control_and_token_efficiency|Architecting High-Efficiency Computer-Use Agents: Control Paradigms, Token Economics, and macOS Implementation]]
  * Deep-research extraction on macOS AI Orchestration, token cost mathematics across providers, and native 4-tier escalation architecture.
  * Tile-aligned pre-downscaling (720p HD / 516 Gemini tiles), coarse-to-fine zoom, diff-only AXTree streaming, and local Apple Neural Engine perception.
* [[argon_round5_maintenance_and_local_models|Round 5 Architecture: Production Maintainability, Modular Codebase, and Local Model Token Reduction]]
  * Modular Platform HAL (`protocols.py`, lazy OS factory, deterministic `MockReplayHAL` cassettes for headless CI).
  * MCP Tool Catalog Modularization & Capability Gating (reducing 5,400-token tool schema bloat to <900 tokens).
  * Out-of-band file offloading (`--output-mode file` / `mcp://desktop-control/state/<file>`) for dense AX trees and VDOM.
  * Asymmetric Local Perception Shield & Hardware Partitioning (Apple Neural Engine OCR/CoreML + quantized Gemma 3 4B-IT).
  * 8-part invariant `COMPACT_PROMPT` history compaction and Bicameral System 1/System 2 execution routing.
* [[cursor_architecture_and_token_efficiency|Cursor Architecture Specification: Platform HAL, Tool Modularization, Token Economics, and Next-Gen Agents]]
  * In-depth codebase exploration and architectural blueprint formulated natively inside Cursor IDE.
  * Multi-monitor logical coordinate topology, pure protocol seams, and headless cassette transition format.
  * Complete 7-predicate escalation suite (P1–P7) and end-to-end token budget cutting cloud consumption by 89.5%–92.5%.
  * Polarity-invariant gradient magnitude icon matching across dark/light themes and dual-path skill crystallization.
  * Systematic implementation roadmap bridging the gap between library contracts and live execution loops.
* [[../learnings/vision_mcp_2_0_implementation_runbook|Vision Control MCP 2.0 Implementation Runbook & Architectural Reference]]
  * Full 5-phase production deployment: Quiescence (`XDamage`/`XFixes`), Modal Triage, Skill Crystallization (`.jou` $\rightarrow$ Jinja2), Neural vDOM Sidecar (`/dev/shm`), and Dynamic Anchor Resolution.
  * Comprehensive tool catalog, architecture flowcharts, and 100% verified test suite (62/62 tests).

---

## 🔗 Related Knowledge Repositories
* [[../learnings/INDEX|Practical Learnings & Execution Recipes]] — Real-world heuristics, window management discoveries, and operational debugging tips.
* [[../references/README|Reference MCP Codebases & Analysis]] — Upstream architectural breakdowns and source code for Microsoft Playwright MCP and Chrome DevTools MCP.
