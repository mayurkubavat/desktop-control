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

---

## 🔗 Related Knowledge Repositories
* [[../learnings/INDEX|Practical Learnings & Execution Recipes]] — Real-world heuristics, window management discoveries, and operational debugging tips.
* [[../references/README|Reference MCP Codebases & Analysis]] — Upstream architectural breakdowns and source code for Microsoft Playwright MCP and Chrome DevTools MCP.
