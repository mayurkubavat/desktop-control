# Dobby

A Model Context Protocol (MCP) server for desktop automation, screen perception, and window management on Linux, Windows and macOS.

`dobby` lets AI coding assistants and autonomous agents (such as Antigravity, Claude, and Gemini) interact with graphical desktop applications. It provides tools for screen capture, mouse and keyboard control, UI element detection, window management, and executing multi-step action scripts.

---

## Features

- **Screen Perception**: Capture full screens, specific application windows, or named sub-panes (e.g. waveform viewers, address bars). Optional Set-of-Marks (SoM) visual badge overlays.
- **Input Automation**: Mouse clicking, dragging, scrolling, text typing with cadence, single key presses, and multi-key shortcuts.
- **UI Element Detection**: Finds interactive elements using OS accessibility trees (AT-SPI2 / D-Bus), a lightweight local ONNX detector (sub-10ms), or visual template matching.
- **Self-Healing Locator Cache**: Remembers element locations across runs, verifies them with visual hashing (<0.5ms), and automatically adjusts for window movement or slight layout drift.
- **Local Trajectory Execution**: Batches multi-step sequences (`execute_trajectory`) locally at native OS speeds without needing model round-trips for every action.
- **Application Plugins**: Pre-configured support for dense applications such as AMD Vivado 2025.1 and Google Chrome, with extensible interfaces for custom tools.
- **GUI-to-Script Crystallization**: Correlates physical UI interactions with application journals (e.g. Vivado `.jou`) to compile repetitive workflows into parameterized scripts.
- **Event-Driven Quiescence**: Uses X11 damage events (`XDamage`) to wait for screen rendering to settle before taking action, avoiding fixed sleep timers.

---

## Installation

### Prerequisites

- **Python**: 3.10 or higher
- **Linux**: an X11 or XWayland session (native Wayland is not supported yet); see [docs/linux.md](docs/linux.md)
- **Windows**: Windows 10/11 (supported via Win32 / UIA HAL)

### Setup

```bash
# Clone the repository
git clone https://github.com/<your-org>/Dobby.git
cd Dobby

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode
pip install -e .

# Optional local OCR lane (RapidOCR on Linux/Windows, Apple Vision on macOS)
pip install -e ".[ocr]"

# macOS backend (Quartz capture/input, Accessibility tree)
pip install -e ".[macos,ocr]"

# Linux X11 backend (system packages first: see docs/linux.md)
pip install -e ".[linux,ocr]"
```

On macOS, grant the app that launches the server (Terminal, Claude, Antigravity)
**Accessibility** and **Screen Recording** in System Settings > Privacy & Security.
Coordinates are logical points; Retina captures are resized to points. Shortcuts use
`cmd` for Command (`hotkey("cmd+s")`); `ctrl` is the Control key.

Read-only smoke test of the local stack (HAL, accessibility, OCR, Gemma):

```bash
python scripts/smoke_local.py
```

To run the test suite:

```bash
pip install -e ".[dev]"
pytest tests/
```

---

## MCP Client Configuration

Add `dobby` to your MCP client configuration file:

### Claude Desktop (`~/.config/Claude/claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "Dobby": {
      "command": "/path/to/Dobby/.venv/bin/dobby",
      "env": {
        "DISPLAY": ":0"
      }
    }
  }
}
```

### Antigravity / Gemini CLI (`~/.gemini/antigravity-cli/mcp_config.json`)

```json
{
  "mcpServers": {
    "Dobby": {
      "command": "/path/to/Dobby/.venv/bin/dobby",
      "env": {
        "DISPLAY": ":20"
      }
    }
  }
}
```

---

## Available Tools (40 Tools)

### Screen Perception & Window Management
| Tool | Description |
| :--- | :--- |
| `take_screenshot` | Captures the screen with optional Set-of-Marks labels and window clipping. |
| `capture_window` | Captures only the target or active window, reducing image size. |
| `capture_pane` | Captures a named functional zone (e.g., `waveform_canvas`, `tcl_console`). |
| `list_windows` | Lists open desktop windows with IDs, titles, and bounding boxes. |
| `get_active_window` | Returns information about the currently focused window. |
| `focus_window` | Brings a window to the foreground by ID or title. |
| `wait_for_ui_change` | Waits until a visual change occurs on screen. |
| `ask_screen` | Answers a yes/no question about the screen with local Gemma; returns text only, no image tokens. |

### Mouse & Keyboard Input
| Tool | Description |
| :--- | :--- |
| `click` | Clicks at coordinates, on a mark ID, or by element label. |
| `click_and_type` | Focuses an element, clears existing text, types new text, and submits. |
| `type_text` | Types text into the focused element with adjustable typing speed. |
| `press_key` | Presses and releases a single key (e.g., `enter`, `escape`, `tab`, `f5`). |
| `hotkey` | Sends a key combination (e.g., `ctrl+c`, `alt+tab`, `ctrl+f5`). |
| `move_cursor` | Moves the mouse pointer to coordinates. |
| `drag_and_drop` | Drags the mouse from start coordinates to end coordinates. |
| `scroll` | Scrolls the mouse wheel horizontally or vertically. |
| `scroll_until_visible` | Scrolls until a target element or text becomes visible. |

### UI Element Grounding & vDOM
| Tool | Description |
| :--- | :--- |
| `find_element` | Finds an element's screen coordinates by text label or accessible role. |
| `find_and_click` | Finds an element by label and clicks it in a single step. |
| `get_accessibility_tree` | Retrieves the accessibility tree (AT-SPI2) for open applications. |
| `capture_vdom` | Fuses accessibility and visual elements into an indexed virtual DOM; `label_with_gemma` names unlabeled visual nodes with local Gemma. |
| `read_screen_text` | Reads on-screen text with local OCR (Apple Vision on macOS, RapidOCR on Linux/Windows); returns lines and click points, no image. |
| `find_visual_element` | Finds an unlabeled element by description: detector boxes, local Gemma picks one by number, click point from the detector. |
| `query_vdom` | Queries the virtual DOM using CSS-style selectors (e.g., `push_button`, `tab_item`). |

### Trajectories, Macros & Script Crystallization
| Tool | Description |
| :--- | :--- |
| `execute_trajectory` | Executes a declarative multi-step action sequence locally at native speed. |
| `start_skill_recording` | Starts recording physical actions alongside application journal streams. |
| `stop_skill_recording` | Stops recording and correlates actions with journal commands. |
| `crystallize_skill` | Compiles recorded interactions into a parameterized script template. |
| `execute_crystallized_skill` | Executes a saved parameterized script directly through the application CLI. |
| `list_crystallized_skills` | Lists all saved crystallized skills. |
| `delete_crystallized_skill` | Deletes a saved skill. |
| `start_cassette_recording` | Records each input action plus AX, OCR and window state as a replayable cassette. |
| `stop_cassette_recording` | Writes the cassette to `~/.dobby/cassettes/<name>/index.json`. |

### Plugins & Utilities
| Tool | Description |
| :--- | :--- |
| `list_plugins` | Lists available application plugins (e.g., Vivado, Chrome). |
| `list_plugin_features` | Lists capabilities and sub-panes for a specific plugin. |
| `invoke_plugin_feature` | Runs a named plugin action (e.g., `vivado.zoom_fit`, `vivado.run_for`). |
| `dismiss_obstructions` | Dismisses modal popups, update prompts, and screensavers. |
| `resolve_modal_dialog` | Classifies and resolves confirmation or alert dialogs. |
| `manage_cache` | Inspects, verifies, or clears the self-healing locator cache. |
| `configure_vision` | Changes runtime settings (grounding strategy, cache toggles). |
| `get_vision_diagnostics` | Returns system diagnostics, screen resolution, and active window. |
| `run_terminal_command` | Executes a shell command and returns output and exit code. |

---

## Directory Structure

```
dobby/
├── dobby/             # Main Python package
│   ├── hal/                # Hardware Abstraction Layer (Linux X11/Wayland, Windows)
│   ├── perception/         # Screen capture, AT-SPI2, Set-of-Marks, token optimizer
│   ├── vdom/               # Fast ONNX detector, virtual DOM fusion, layout solver
│   ├── agent_loop/         # Controller, action cache, obstruction handler, trajectory engine
│   ├── crystallization/    # GUI-to-script compiler and skill registry
│   ├── plugins/            # Application plugins (Vivado, Chrome, base plugin)
│   ├── models/             # Bundled Fast-Path ONNX UI detector (159 KB)
│   ├── server.py           # FastMCP server and tool registrations
│   ├── config.py           # Settings and environment variable handling
│   └── types.py            # Pydantic data models and schemas
│
├── docs/                   # Documentation and runbooks
│   ├── setup.md            # Installation and client configuration guide
│   ├── tools.md            # Detailed tool reference with parameters and examples
│   ├── architecture.md     # System architecture and design principles
│   └── plugins/            # Plugin documentation (Vivado, custom plugins)
│
├── examples/               # Demonstrations and example scripts
│   ├── live_trajectory_vivado.py  # End-to-end Vivado simulation trajectory
│   └── dashboard.html             # Test fixture for browser interactions
│
├── tests/                  # Test suite (89 unit and integration tests)
├── pyproject.toml          # Build configuration and dependencies
├── requirements.txt        # Pinned dependencies
├── LICENSE                 # License file
└── README.md
```

---

## Testing

Run the full test suite with `pytest`:

```bash
.venv/bin/pytest tests/
```

The tests cover HAL window management, quiescence monitoring, grounding strategies, modal triage, crystallization, self-healing cache, vDOM layout solvers, and trajectory execution.

Recorded cassettes in `tests/cassettes/` replay offline and check their `expect.json`:

```bash
.venv/bin/pytest -m replay
.venv/bin/python scripts/replay_cassette.py tests/cassettes/example_click
```

Record new ones from a live session with `start_cassette_recording` / `stop_cassette_recording` (toolset `skills`); see `tests/cassettes/README.md`.

---

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.

## Local models (plug and play)

Dobby works with any model served by Ollama. Each job has a role with its own model:
`text` (choices over the text screen state), `vision` (yes/no on crops), `visual_pick`
(lettered boxes on a screenshot) and `triage` (dialog text). All default to `gemma3:4b`.

Swap a role without code changes, first match wins:

1. `DOBBY_MODEL_<ROLE>=qwen2.5vl:7b` in the MCP client's env
2. `set_model_role("visual_pick", "qwen2.5vl:7b")` at runtime (advanced_vision toolset)
3. `~/.dobby/models.json`, e.g. `{"vision": "qwen2.5vl:7b", "visual_pick": "qwen3-vl:8b"}` (re-read on change)
4. `CONFIG.model_<role>`, else the `gemma3_*` defaults

Compare candidates first: `python scripts/bench_models.py --models gemma3:4b,qwen2.5vl:7b`.
It scores accuracy, confident mistakes and whether a model says "none" when the target is
absent. `get_model_roles` lists roles, sources and known candidates (`dobby/local_models.py`).
Nothing downloads models; pull them yourself after checking `~/LocalAI/MODELS.md`.

## ADK pipeline (optional)

`pip install -e '.[adk]'`, then `python -m dobby.adk plan.json` runs a JSON plan step by step: code calls the tools, local Gemma judges each step through ADK structured-output agents (OCR first, then a text verifier, then `ask_screen`), and the run stops with a report when a step cannot be verified. Format and tiers: `plugins/dobby/skills/orchestrator/references/adk-pipeline.md`; example: `examples/adk/example_click_plan.json`.

## Agent skills plugin

`plugins/dobby/` is a Claude Code plugin of skills that teach an agent
to use this server well: a perception ladder that avoids screenshots, verified
actions, app playbooks (Claude, Chrome, Vivado, Verdi), skill crafting,
evaluation and troubleshooting. Install it with
`/plugin marketplace add <path to this repo>` and
`/plugin install dobby@dobby`. See
[plugins/dobby/README.md](plugins/dobby/README.md).
