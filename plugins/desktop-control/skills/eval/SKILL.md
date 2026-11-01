---
name: eval
description: Check that a change to desktop-control (prompts, local models, perception or server code) helps rather than hurts - unit and replay tests, cassettes, and the local benchmark. Use before committing such a change, or when comparing two models or prompts.
---

# Evaluating desktop-control changes

A change lands only with evidence that it helped. Run these in order; stop at the first failure.

1. **Unit and replay tests** (fast, no desktop needed):
   `.venv/bin/python -m pytest -q`
   On macOS, 5 skips are expected (X11-only tests, a missing font, RapidOCR is the Linux engine). Any failure blocks the change.
2. **Generated references are current:**
   `.venv/bin/python scripts/build_skill_refs.py --check`
3. **Replay the behavior you changed** against a cassette (below), so the result does not depend on what is on screen today.
4. **Benchmark on the real desktop** (read-only, never clicks):
   `.venv/bin/python scripts/bench_local.py --repeats 3`
   Compare capture, OCR and Gemma latency and the token-savings block with the previous run.

## What to compare

| Change | Must not get worse | Should improve |
| --- | --- | --- |
| Gemma prompt or model | Replay accuracy on yes/no and dialog triage | Latency (warm p50), output tokens |
| OCR settings | Lines found on the bench window | OCR ms, text tokens |
| Perception or ladder logic | Tests, replay verdicts | Screenshots per task |
| Server tools or toolsets | Tests, tool reference drift check | Tool count in `core` only if each earns its place |

Write the before and after numbers into the commit message.

## Cassettes

A cassette is a recorded desktop: frames (AX tree, OCR boxes, windows, screen size, an optional image) and the transitions an action causes. Replaying one runs the real controller against a fake desktop and raises `CassetteMismatch` when an action does not match the recording. Format and how to make one: `references/cassettes.md`.

Current limits, so plans stay honest: there is no MCP tool yet to record a cassette from a live session. `CassetteRecorder` in `vision_mcp/hal/mock_replay.py` records AX and screen size from Python only, and keeps them in memory. Hand-written cassettes (as in `tests/test_architecture_plan.py`) are the practical route today.

## References

- `references/cassettes.md`: cassette JSON format, loading, and a minimal example.
