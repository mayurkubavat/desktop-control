# desktop-control skills plugin

Skills that teach an agent to drive the desktop through the desktop-control MCP
server. Each skill is a short `SKILL.md` (when to use it, the steps) plus a
`references/` folder read only when needed.

| Skill | Use it for |
| --- | --- |
| `desktop-control:orchestrator` | Entry point for any desktop task: perception ladder, contracts, recovery, safety |
| `desktop-control:perception` | Choosing between AX, OCR, local Gemma and screenshots; the full tool reference |
| `desktop-control:skill-crafting` | Recording a task and crystallizing it into a replayable skill |
| `desktop-control:eval` | Cassettes, replay tests and the local benchmark |
| `desktop-control:troubleshoot` | Permissions, Ollama and models, toolsets, client config |
| `desktop-control:app-claude` | The Claude desktop app (Electron) |
| `desktop-control:app-chrome` | Chrome and web apps, including Gemini on the web |
| `desktop-control:app-vivado` | AMD/Xilinx Vivado GUI and simulation waveforms |
| `desktop-control:app-verdi` | Synopsys Verdi and other dense EDA UIs |

## Install

Claude Code, from any directory:

```
/plugin marketplace add ~/Silicon/DV/git/desktop-control
/plugin install desktop-control@desktop-control
```

Other agents (Antigravity, Cursor) can use the same files: point them at
`plugins/desktop-control/skills/` with a symlink into whatever folder that tool
reads skills or rules from. Check the tool's current docs for that folder; this
repo does not assume one.

## Editing references

Files whose first line says `GENERATED` come from code or from `learnings/` and
`docs/`. Edit the source and run `python scripts/build_skill_refs.py`;
`tests/test_skill_plugin.py` fails while any of them is stale. Everything else is
written by hand and edited in place.
