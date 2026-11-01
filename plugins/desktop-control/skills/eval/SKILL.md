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
3. **Replay the behavior you changed** against a cassette (below), so the result does not depend on what is on screen today. `pytest -m replay` runs only the cassettes in `tests/cassettes/`.
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

To record one from a live session, enable the `skills` toolset, call `start_cassette_recording(name)`, do the task with the normal tools, then `stop_cassette_recording()`. Each input action is followed by a settle wait and a frame of AX nodes, OCR lines, windows and cursor (add `capture_images=true` for JPEG frames). The cassette lands in `~/.desktop-control/cassettes/<name>/`. Typed text is stored verbatim, so never record while typing a secret.

To keep it as a regression test, copy the folder into `tests/cassettes/`, add an `expect.json` for the final frame, and run `.venv/bin/python -m pytest -q -m replay` (or `scripts/replay_cassette.py <folder>` for one).

## References

- `references/cassettes.md`: cassette JSON format, recording, `expect.json`, the replay runner, and a minimal example.
