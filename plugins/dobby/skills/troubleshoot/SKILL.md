---
name: troubleshoot
description: Fix Dobby when it misbehaves - a missing tool, an empty accessibility tree, OCR or Gemma unavailable, black captures, the server failing to start in Claude Code, Claude Desktop or Antigravity, or Linux window focus problems. Use when a Dobby call errors or returns nothing useful.
---

# Troubleshooting Dobby

Start with `get_vision_diagnostics` (in the `advanced_vision` toolset; enable it if needed). It reports the platform, display server, active window, the OCR engine, and Gemma's availability, installed models and last error. Then match the symptom:

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| "Tool ... is outside the active tool profile" | Its toolset is off; only `core` is on by default | `manage_toolsets(action="enable", domains=["<domain>"])`. Some clients only see new tools after a restart |
| AX tree empty on macOS | Accessibility not granted, or granted after the server started | Grant it to the app that launches the server (Claude, Antigravity, the terminal), then fully quit and reopen that app |
| AX tree has only window buttons in Claude, VS Code or Slack | First read of an Electron app | Call again; the first read turns on Chromium's accessibility |
| Captures are black or only the wallpaper | Screen Recording not granted | System Settings > Privacy & Security > Screen Recording, then restart the app |
| `display_server` is null in diagnostics | Server older than the review fixes (ce1a2f3) | Update the branch and restart the client |
| OCR `available: false` | Missing extra | `uv pip install -e ".[ocr]"` (Apple Vision on macOS, RapidOCR elsewhere) |
| Gemma unavailable or answers time out | Ollama not running, model not pulled, or cold load | `brew services list` should show Ollama; `ollama list`; the first call takes ~8 s. Never pull without `~/LocalAI/bin/ai-check` |
| Server marked "Failed" in Claude Desktop | Stale command path in its config | Check the command exists and is executable; fix the entry while Claude Desktop is quit |
| Edits to a client config vanish | Claude Desktop rewrites its config when it quits | Quit the app first, then edit, then reopen |
| Linux: clicks land in the wrong window | X11 focus was stolen by a terminal | See `references/linux-window-management.md` |

## References

- `references/macos.md`: permissions, client config files and the exact registration entries.
- `references/setup.md`: install and setup (copied from `docs/setup.md`).
- `references/linux-window-management.md`: X11 focus and stacking fixes.
