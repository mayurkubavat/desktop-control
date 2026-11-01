# Local Gemma in desktop-control

Measured on Mayur's MacBook Pro (16 GB), 2026-11-01, Claude window 1512x949.

| Step | Time | Notes |
| --- | --- | --- |
| Capture window | ~265 ms | Quartz, Retina downscaled to logical points |
| Apple Vision OCR | ~220 ms, ~0.6 ms cached | dHash cache keyed on the frame |
| Gemma yes/no, cold | ~8.4 s | First call loads gemma3:4b; warmup at server start hides it |
| Gemma yes/no, warm | ~1.2 s | ~30 output tokens |
| Screenshot sent to a cloud model | ~1,533 image tokens | For comparison |

## Where Gemma is used

| Tool or path | What Gemma does | Fallback |
| --- | --- | --- |
| `ask_screen` | Answers a yes/no with short evidence, after OCR could not settle it | `answer: null`, `source: fallback`; caller escalates |
| `find_visual_element` | Picks one numbered box (Set-of-Marks) matching a description | OCR match first; none found returns no element |
| `capture_vdom(label_with_gemma=true)` | Names unnamed detector boxes; cached per app by patch dHash | Boxes stay unnamed |
| Modal triage (obstruction interceptor) | Tie-breaker on dialog risk when rules disagree; fail-closed | Escalates, never auto-dismisses |
| Bicameral Tier 1 | Judges a step's expected outcome after Tier 0 (AX diff, OCR) is unsure | Tier 2 (cloud screenshot) |

## Settings (`vision_mcp/config.py`, or `configure_vision(setting, value)` at runtime)

- `gemma3_endpoint` (`http://127.0.0.1:11434`), `gemma3_vision_model` and `gemma3_text_model` (`gemma3:4b`).
- `gemma3_keep_alive` (`10m`) keeps the model loaded between calls; `gemma3_warmup_on_start` loads it at server start.
- `gemma3_visual_max_side` (896) caps the image side sent to Gemma; `gemma3_max_marks` (30) caps boxes per call.
- `gemma3_modal_min_confidence` (0.8) and `gemma3_visual_min_confidence` (0.6) gate acting on an answer.
- `gemma3_timeout_seconds` (25) per call.

## Models

Only models listed in `~/LocalAI/MODELS.md` are used. Run `~/LocalAI/bin/ai-check` before pulling anything; one Ollama serves every project on the Mac, and duplicate downloads are not allowed. gemma3:12b is installed too, for slower, off-the-hot-path work such as history compaction.

## Measuring

`python scripts/bench_local.py --repeats 3` prints these numbers for the active window (read-only, never clicks). `python scripts/smoke_local.py` checks each layer once.
