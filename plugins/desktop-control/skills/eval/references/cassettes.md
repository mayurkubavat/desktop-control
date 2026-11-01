# Cassettes

Source of truth: `vision_mcp/hal/mock_replay.py` (`MockReplayHAL`, `load_cassette`, `CassetteRecorder`).

## Loading

- From Python: `load_cassette(path)` accepts an `index.json` file, a directory holding `index.json`, a zip (`.halpack`) holding `index.json`, or a JSON string.
- As the server's backend: `get_desktop_hal(kind="replay", cassette=path)`, or start the server with `DESKTOP_HAL=replay` and `DESKTOP_CASSETTE=<path>`.
- In `crystallize_skill(..., cassette_path=path)`: the new macro is replayed on it before registration.

## index.json

```json
{
  "frames": [
    {
      "frame_id": "pre",
      "ocr_boxes": [{"text": "Run"}],
      "ax_tree": {},
      "ax_diff": {},
      "screen_size": [1512, 982],
      "cursor_pos": [0, 0],
      "windows": [],
      "active_window": null,
      "pixel_delta_from_prev": 0.0,
      "image_path": "frames/pre.png",
      "phase": "QUIESCENT"
    },
    {"frame_id": "post", "ocr_boxes": [{"text": "Done"}]}
  ],
  "transitions": [
    {
      "pre_frame_id": "pre",
      "action": "mouse_click",
      "args": {"x": 3, "y": 4, "button": "left", "click_count": 1},
      "post_frame_id": "post"
    }
  ],
  "topology": null
}
```

Only `frame_id` is required per frame; the rest default as shown. `image_path` is relative to the cassette's folder. `phase` is reported by the replay quiescence monitor (`QUIESCENT`, `SETTLING`, ...).

## Behavior

- The replay starts at the first frame. Each HAL action must match the next transition from the current frame (action name and args), or `CassetteMismatch` is raised.
- `read_screen_text(contains=...)` on the replay HAL searches the current frame's `ocr_boxes`.
- `wait_for_quiescence` returns the frame's recorded phase and `pixel_delta_from_prev` without sleeping.

## Tips for a useful cassette

- One cassette per task, named for it: `tests/cassettes/<app>_<task>/index.json`.
- Record the frames that matter for verification (before and after the key action), not every frame.
- Keep OCR text exact; it is what Tier 0 checks match against.
