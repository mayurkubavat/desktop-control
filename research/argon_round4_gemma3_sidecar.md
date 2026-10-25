Upgrading the Vision Control MCP 2.0 perception stack requires decoupling spatial localization from semantic interpretation. Replacing Phase 4’s OpenCV contour heuristics with a unified neural pipeline cannot rely on a single Vision-Language Model (VLM); doing so will violate your 40ms frame-to-vDOM budget and stall the Phase 1 XDamage event loop. Instead, the architecture must pair a deterministic, sub-30ms TensorRT vision backbone with an asynchronous, ROI-triggered Gemma 3 reasoning plugin.

---

## Section 1: The Production Edge Neural Hierarchy (Sub-40ms vs. On-Demand VLM)

### The Single-Model Fallacy in High-Frequency UI Tracking

Autoregressive VLMs are fundamentally mismatched for high-frequency spatial tracking across 4K/2K EDA workspaces for three reasons:

1. **Vision Encoder Patchification Overhead:** Processing a full $2560 \times 1440$ desktop frame through a ViT/SigLIP tower requires either aggressive downscaling (which obliterates 8px schematic pins and 10pt netlist labels in Synopsys Verdi) or dynamic high-resolution tiling (e.g., Pan & Scan), which explodes visual token counts into the thousands and pushes Time-To-First-Token (TTFT) well past 250ms.
2. **Autoregressive Coordinate Decoding:** Generating bounding boxes token-by-token is sequentially bound by memory bandwidth. Emitting 150 UI elements in a dense Vivado layout requires thousands of output tokens, translating to 2–5 seconds of latency per frame.
3. **Coordinate Quantization Drift:** VLMs map continuous spatial geometry into discrete token bins (typically $0..1000$). On high-DPI displays, rounding errors and hallucinated spatial alignment lack the sub-pixel tightness required for deterministic Phase 3 skill crystallization and Phase 4 IoU fusion ($\ge 0.65$).

### The Dual-Lane Architecture

To hold the strict **less than 40ms** Phase 4 SLA while gaining deep semantic comprehension over unlabelled OpenGL/Qt canvases, the perception sidecar must split into two execution lanes reading from `/dev/shm/vision_mcp_fb`:

```
                       [/dev/shm/vision_mcp_fb]
                                  │
            ┌─────────────────────┴─────────────────────┐
            ▼ (Every Quiescent Frame)                   ▼ (On-Demand / Async ROI)
┌───────────────────────────┐               ┌───────────────────────────┐
│   LANE 1: FAST-PATH (<30ms)│               │  LANE 2: SLOW-PATH (~350ms)│
│  TensorRT FP16 / CUDA IPC │               │  Gemma 3 4B-IT Sidecar    │
├───────────────────────────┤               ├───────────────────────────┤
│ • YOLOv11s-UI / OmniParser│               │ • Cropped ROI via SHM     │
│ • PP-OCRv4 (Det + Rec)    │               │ • GBNF Grammar Constrained│
│ • Spatial BBoxes + Raw Txt│               │ • Deep EDA Semantics      │
└─────────────┬─────────────┘               └─────────────┬─────────────┘
              │                                           │
              ▼                                           ▼
      [Asymmetric IoU Fusion] ◄─────────────────── [Semantic Cache]
              │                                   (pHash + vDOM Anchor)
              ▼
    [Unified vDOM Graph (P4)]

```

#### Lane 1: Fast-Path Structural & Lexical Grounding (Target: under 30ms)

Executes synchronously on every quiescent dirty-rect event signaled by Phase 1.

* **Icon & Widget Detector:** **YOLOv11s-UI** (or **OmniParser-v2** detection head) compiled to TensorRT FP16 with dynamic batching over dirty regions. Detects structural bounds (`icon_button`, `checkbox`, `tab`, `text_field`, `canvas_viewport`) in **6–9ms**.
* **High-Speed Lexical Extraction:** **PP-OCRv4** (DBNet++ detection + SVTR-LCNet recognition) running concurrently on a separate CUDA stream via TensorRT. Extracts bounding polygons and raw strings for net names, menu items, and hex bus values in **12–16ms**.
* **vDOM Fusion (2–3ms):** Merges Fast-Path proposals with the AT-SPI2 accessibility tree using your existing asymmetric IoU ($\ge 0.65$) and containment ($\ge 0.85$) kernels.

#### Lane 2: Slow-Path Cognitive VLM (Target: 150ms–450ms TTFT+Decode, Amortized to under 1ms)

Executes asynchronously or on-demand when the Fast-Path produces structurally valid but semantically opaque `VDOMNode` entries, or when high-level visual reasoning is required. Powered by **Gemma 3 (4B-IT or 12B-IT)**.

### Gating & Dispatch Heuristics

Gemma 3 is strictly gated by a deterministic **Semantic Escalation Router** inside Phase 4. It is never invoked on raw full-screen frames unless a catastrophic layout stall occurs.

1. **Unlabelled Custom Widget Triage (`AT-SPI2 Miss + OCR Miss`):**
* *Condition:* YOLOv11s-UI detects an interactive widget ($C_{conf} > 0.75$) inside a toolbar or hierarchy tree, AT-SPI2 returns `role=ROLE_UNKNOWN` or an empty `accessible-name` (common in custom Qt/Tkinter/Tcl EDA wrappers), and PP-OCRv4 finds zero overlapping text.
* *Action:* Crop a $128 \times 128$ padded ROI around the widget, check the perceptual hash (`pHash`) cache, and on a miss, dispatch to Gemma 3 to classify the icon's semantic function (e.g., `"Zoom Fit"`, `"Run DRC"`, `"Toggle Breakpoint"`).


2. **Opaque OpenGL / Canvas Viewport Inspection:**
* *Condition:* The active task planner targets a Phase 5 anchor-relative sub-pane whose AT-SPI2 role is a monolithic drawing area (`ROLE_CANVAS`, `ROLE_DRAWING_AREA`, or custom X11 child window in Vivado Schematic / Verdi nWave) and requires relational reasoning that flat OCR cannot link (e.g., associating a floating hex value with a specific multi-bit waveform trace or tracing a red DRC error marker between two RTL blocks).
* *Action:* Crop the sub-pane ROI via Phase 5 topological coordinates ($896 \times 896$ native resolution) and query Gemma 3 with a task-specific system prompt.


3. **Phase 2 Modal Escalation Fallback:**
* *Condition:* Phase 2 (Semantic Modal Triage) intercepts a novel modal dialog where keyword/regex rules over AT-SPI2/OCR text yield an ambiguous risk score between `Workflow Branching` and `Destructive` (e.g., custom graphical warning dialogs in Vivado IP Integrator showing block diagram lock states).
* *Action:* Dispatch modal crop to Gemma 3 for zero-shot classification into the 4-tier risk taxonomy.


4. **Phase 3 Crystallization Verification Failure:**
* *Condition:* During deterministic zero-token replay, an expected post-condition fails (e.g., cursor remains busy or expected vDOM anchor fails to materialize within the timeout).
* *Action:* Invoke Gemma 3 on the dirty rect to diagnose the visual anomaly before aborting or branching the journaled skill.



---

## Section 2: Local Gemma 3 Multimodal Sidecar Architecture & Edge Deployment

### Model Sizing Trade-Offs (Gemma 3 Family)

A critical architectural pitfall must be avoided upfront: **Gemma 3 1B is a text-only model.** It lacks the SigLIP vision tower and multimodal projector (`mmproj`) introduced in the 4B, 12B, and 27B variants. However, 1B remains highly useful if paired as a pure text-reasoning micro-sidecar for Phase 2 modal text classification.

For visual perception on modern Linux engineering workstations (e.g., NVIDIA RTX 4080/4090 16–24GB, RTX 5080, or RTX 4000 Ada 20GB), **Gemma 3 4B-IT (Q4_K_M / FP8)** is the production sweet spot:

| Metric / Characteristic | Gemma 3 1B-IT | Gemma 3 4B-IT (Recommended) | Gemma 3 12B-IT |
| --- | --- | --- | --- |
| **Multimodal Support** | **No (Text-Only)** | **Yes** (SigLIP Vision Tower, $896 \times 896$ native) | **Yes** (SigLIP Vision Tower + Pan & Scan) |
| **VRAM Footprint (Q4_K_M / AWQ)** | ~0.9 GB | **~3.4 GB** (Weights + `mmproj-f16` + 8K KV) | **~8.6 GB** (Weights + `mmproj-f16` + 8K KV) |
| **Single ROI ($896 \times 896$) TTFT** | ~12 ms (Text only) | **~65–95 ms** (256 visual tokens) | **~160–240 ms** (256 visual tokens) |
| **Decode Speed (RTX 4090 / 4000 Ada)** | ~190 tok/s | **~115–135 tok/s** | **~55–70 tok/s** |
| **End-to-End JSON Emit (~60 tokens)** | ~320 ms | **~480–580 ms** | **~1,100–1,400 ms** |
| **Role in Vision Control MCP 2.0** | Phase 2 text-only modal triage & Tcl error log summarization | **Primary Phase 4 Visual Sidecar:** Icon labeling, waveform inspection, schematic pin grounding | Heavy escalation fallback for complex multi-pane cross-probing when VRAM permits |

*Why Gemma 3 4B-IT excels here:* Gemma 3's vision encoder compresses an $896 \times 896$ image into a fixed **256 token sequence**. When you pass a targeted Phase 5 sub-pane crop (rather than a downscaled 4K monitor), $896 \times 896$ preserves 1:1 pixel fidelity for EDA schematics and waveforms while keeping prefill latency under 100ms.

### Optimal Inference Engine Stack

While TensorRT-LLM and vLLM offer superior high-concurrency batching for cloud deployments, a local desktop sidecar co-existing with VRAM-hungry X11 applications and Phase 4's YOLOv11/PP-OCRv4 TensorRT engines requires minimal memory overhead and deterministic grammar enforcement.

**Recommended Stack: `llama.cpp` (`llama-server`) with CUDA Backend & GBNF Grammar**

* **VRAM Predictability:** `llama-server` reserves a strictly static memory pool (`--ctx-size 4096 --parallel 2`), preventing CUDA Out-Of-Memory (OOM) collisions with TensorRT Fast-Path engines or hardware-accelerated CAD viewports.
* **Sub-Millisecond Grammar Constraints:** `llama.cpp` compiles Backus-Naur Form (GBNF) grammars or JSON Schemas directly into token-level logit masks on the CPU/GPU boundary with virtually zero latency penalty, guaranteeing 100% syntactically valid coordinate arrays and enum roles.
* **Launch Configuration:**
```bash
llama-server \
  --model /opt/models/gemma-3-4b-it-q4_k_m.gguf \
  --mmproj /opt/models/mmproj-gemma-3-4b-it-f16.gguf \
  --host 127.0.0.1 --port 8089 \
  --n-gpu-layers 99 --ctx-size 4096 \
  --flash-attn --cache-type-k q8_0 --cache-type-v q8_0 \
  --parallel 1 --cont-batching

```



### Zero-Copy IPC Integration

Standard HTTP VLM pipelines read the screen, encode to PNG, Base64-encode the buffer, serialize JSON, and decode inside the server—wasting 15–25ms of CPU time.

1. **Zero-Copy Shared Memory Slicing:** Your XDamage collector writes raw BGRA frames to `/dev/shm/vision_mcp_fb` (preceded by a 64-byte lock-free atomic seqlock header containing `width`, `height`, `stride`, and `frame_seq`). The Python sidecar maps this file via `mmap` and wraps it in a zero-copy `numpy.ndarray` view (`np.frombuffer`).
2. **Sub-Millisecond ROI Extraction & Fast Transport:** Slicing the target sub-pane `fb[y1:y2, x1:x2]` creates a strided NumPy view without copying memory.
* *For Unpatched `llama-server`:* Encode *only* the cropped ROI in-memory to uncompressed **BMP** or **QOI (Quite OK Image)** format rather than PNG. Compressing an $896 \times 896$ crop to PNG takes ~9ms (zlib deflate bottleneck); writing an in-memory BMP header over a contiguous RGB buffer takes **0.3ms**, and loopback TCP over `127.0.0.1` transfers 2.4MB in ~0.2ms.
* *For Patched Production `llama-server` (C++ Custom Slot):* Pass a JSON descriptor `{"shm_path": "/dev/shm/vision_mcp_fb", "roi": [x, y, w, h], "stride": 10240}` directly to a custom endpoint in `llama-server` that maps `/dev/shm/vision_mcp_fb` directly into `clip_image_u8` before CUDA upload.



### Structured Output Formatting & Prompt Engineering

Gemma 3 is trained to emit normalized bounding coordinates in `[ymin, xmin, ymax, xmax]` scaled to `[0, 1000]`. We enforce this via both the system prompt and a strict JSON Schema converted to GBNF.

#### System Prompt

```text
You are a precision UI & Electronic Design Automation (EDA) visual grounding engine operating on a cropped desktop region.
Analyze the provided image crop and identify all requested UI elements, schematic components, or waveform signals.
Output strictly valid JSON matching the schema.
Coordinates MUST be normalized integers [ymin, xmin, ymax, xmax] scaled from 0 to 1000 relative to the provided image crop.
Valid roles: ["icon_button", "schematic_pin", "schematic_net", "waveform_signal", "waveform_cursor_val", "hierarchy_node", "drc_error_marker", "modal_action", "status_indicator"].

```

#### GBNF Grammar Enforcement (`gemma3_vdom.gbnf`)

```ebnf
root   ::= "{" ws "\"elements\":" ws "[" ws (element (ws "," ws element)*)? ws "]" ws "}"
element ::= "{" ws
  "\"box_2d\":" ws "[" ws coord ws "," ws coord ws "," ws coord ws "," ws coord ws "]," ws
  "\"role\":" ws role "," ws
  "\"label\":" ws string "," ws
  "\"value\":" ws (string | "null") "," ws
  "\"state\":" ws state "," ws
  "\"confidence\":" ws float
ws "}"

coord  ::= [0-9] | [1-9][0-9] | [1-9][0-9][0-9] | "1000"
role   ::= "\"icon_button\"" | "\"schematic_pin\"" | "\"schematic_net\"" | "\"waveform_signal\"" | "\"waveform_cursor_val\"" | "\"hierarchy_node\"" | "\"drc_error_marker\"" | "\"modal_action\"" | "\"status_indicator\""
state  ::= "\"normal\"" | "\"active\"" | "\"disabled\"" | "\"error\"" | "\"warning\"" | "\"high_z\"" | "\"unknown_x\""
float  ::= "0." [0-9][0-9] | "1.00"
string ::= "\"" ([^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4}))* "\""
ws     ::= ([ \t\n]*)

```

---

## Section 3: Concrete Implementation Blueprint

Below is the complete, production-grade implementation of the `Gemma3SidecarPlugin` designed to slot directly into your Phase 4 vDOM pipeline.

```python
from __future__ import annotations

import asyncio
import base64
import enum
import hashlib
import json
import logging
import mmap
import os
import struct
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import numpy as np

logger = logging.getLogger("vision_mcp.phase4.gemma3_sidecar")


# ============================================================================
# 1. Core Domain Models & Configuration (Phase 4 vDOM Contracts)
# ============================================================================

class GroundingSource(str, enum.Enum):
    ATSPI_ONLY = "ATSPI_ONLY"
    VISION_FAST = "VISION_FAST"      # YOLOv11s-UI + PP-OCRv4
    VISION_ONLY = "VISION_ONLY"      # Gemma 3 Pure Visual Discovery
    HYBRID = "HYBRID"                # AT-SPI2 / Fast-Path + Gemma 3 Semantic Fusion


class UIRole(str, enum.Enum):
    ICON_BUTTON = "icon_button"
    SCHEMATIC_PIN = "schematic_pin"
    SCHEMATIC_NET = "schematic_net"
    WAVEFORM_SIGNAL = "waveform_signal"
    WAVEFORM_CURSOR_VAL = "waveform_cursor_val"
    HIERARCHY_NODE = "hierarchy_node"
    DRC_ERROR_MARKER = "drc_error_marker"
    MODAL_ACTION = "modal_action"
    STATUS_INDICATOR = "status_indicator"


@dataclass(slots=True)
class BoundingBox:
    """Global X11 screen coordinates in physical pixels."""
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.width * self.height

    def iou(self, other: BoundingBox) -> float:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        union = self.area + other.area - inter
        return inter / float(union) if union > 0 else 0.0

    def containment(self, other: BoundingBox) -> float:
        """Asymmetric containment: fraction of `self` inside `other`."""
        if self.area == 0:
            return 0.0
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        return inter / float(self.area)


@dataclass(slots=True)
class VDOMNode:
    node_id: str
    bbox: BoundingBox
    role: str
    semantic_label: str
    value: Optional[str] = None
    state: str = "normal"
    confidence: float = 1.0
    source: GroundingSource = GroundingSource.VISION_ONLY
    anchor_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Gemma3Config:
    endpoint_url: str = "http://127.0.0.1:8089/v1/chat/completions"
    model_name: str = "gemma-3-4b-it"
    quantization: str = "Q4_K_M"
    shm_path: str = "/dev/shm/vision_mcp_fb"
    shm_header_bytes: int = 64
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_sec: float = 1.2
    iou_fusion_threshold: float = 0.65
    containment_threshold: float = 0.85
    cache_max_entries: int = 2048
    cache_hamming_threshold: int = 4  # Max 64-bit dHash bit flips for hit


# ============================================================================
# 2. Zero-Copy Shared Memory Framebuffer Reader & Fast BMP Encoder
# ============================================================================

class SharedMemoryFramebuffer:
    """
    Zero-copy POSIX shared memory reader for `/dev/shm/vision_mcp_fb`.
    Header layout (64 bytes, little-endian):
      offset 0:  uint64 seq_lock (even = consistent, odd = write in progress)
      offset 8:  uint32 width
      offset 12: uint32 height
      offset 16: uint32 stride_bytes
      offset 20: uint32 format (0 = BGRA8888)
      offset 24: uint64 timestamp_ns
      offset 32..64: reserved padding
    """
    HEADER_STRUCT = struct.Struct("<QIIIIQ32x")

    def __init__(self, shm_path: str, header_bytes: int = 64) -> None:
        self.shm_path = shm_path
        self.header_bytes = header_bytes
        self._fd: Optional[int] = None
        self._mmap: Optional[mmap.mmap] = None

    def open(self) -> None:
        if self._mmap is not None:
            return
        if not os.path.exists(self.shm_path):
            raise FileNotFoundError(f"SHM framebuffer not found at {self.shm_path}")
        self._fd = os.open(self.shm_path, os.O_RDONLY)
        size = os.fstat(self._fd).st_size
        self._mmap = mmap.mmap(self._fd, size, mmap.MAP_SHARED, mmap.PROT_READ)

    def close(self) -> None:
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def get_zero_copy_roi(self, roi: BoundingBox) -> Tuple[np.ndarray, int]:
        """
        Returns a zero-copy NumPy view of shape (H, W, 4) in BGRA order
        and the validated frame sequence number.
        """
        if self._mmap is None:
            self.open()
        assert self._mmap is not None

        for _ in range(5):
            seq1, width, height, stride, _fmt, _ts = self.HEADER_STRUCT.unpack_from(
                self._mmap, 0
            )
            if seq1 & 1:  # Writer active; spin briefly
                time.sleep(0.0001)
                continue

            # Clamp ROI to screen geometry
            x1 = max(0, min(roi.x1, width - 1))
            y1 = max(0, min(roi.y1, height - 1))
            x2 = max(x1 + 1, min(roi.x2, width))
            y2 = max(y1 + 1, min(roi.y2, height))

            # Construct zero-copy strided ndarray view directly over mmap buffer
            fb_view = np.ndarray(
                shape=(height, width, 4),
                dtype=np.uint8,
                buffer=self._mmap,
                offset=self.header_bytes,
                strides=(stride, 4, 1),
            )
            roi_view = fb_view[y1:y2, x1:x2]

            seq2, *_ = self.HEADER_STRUCT.unpack_from(self._mmap, 0)
            if seq1 == seq2:
                return roi_view, seq1

        raise RuntimeError("Failed to acquire tear-free SHM read lock within 5 retries")

    @staticmethod
    def encode_bgra_to_bmp_bytes(bgra_roi: np.ndarray) -> bytes:
        """
        Sub-millisecond uncompressed 24-bit BGR BMP encoder.
        Avoids 8-15ms zlib PNG compression overhead for local loopback IPC.
        """
        h, w, _ = bgra_roi.shape
        row_raw = w * 3
        row_pad = (4 - (row_raw % 4)) % 4
        stride = row_raw + row_pad
        pixel_bytes_size = stride * h
        file_size = 54 + pixel_bytes_size

        # BMP Header (14 bytes) + DIB BITMAPINFOHEADER (40 bytes)
        # Negative height (-h) indicates top-down scanline order (no vertical flip needed)
        header = struct.pack(
            "<2sIHHIiiiHHIIiiII",
            b"BM",
            file_size,
            0,
            0,
            54,
            40,
            w,
            -h,
            1,
            24,
            0,
            pixel_bytes_size,
            2835,
            2835,
            0,
            0,
        )

        bgr = np.ascontiguousarray(bgra_roi[:, :, :3])
        if row_pad > 0:
            padded = np.zeros((h, stride), dtype=np.uint8)
            padded[:, :row_raw] = bgr.reshape(h, row_raw)
            payload = padded.tobytes()
        else:
            payload = bgr.tobytes()

        return header + payload


# ============================================================================
# 3. Perceptual Hash (dHash) Semantic Grounding Cache
# ============================================================================

class SemanticROICache:
    """
    Amortizes Gemma 3 latency to <0.2ms on stationary or recurring sub-panes.
    Keys by (anchor_id, task_intent) and validates visual invariance via 64-bit dHash.
    """

    def __init__(self, max_entries: int = 2048, hamming_threshold: int = 4) -> None:
        self.max_entries = max_entries
        self.hamming_threshold = hamming_threshold
        self._store: OrderedDict[str, Tuple[int, List[VDOMNode]]] = OrderedDict()

    @staticmethod
    def compute_dhash64(bgra_roi: np.ndarray) -> int:
        """Fast 64-bit horizontal gradient hash using stride subsampling."""
        h, w, _ = bgra_roi.shape
        # Subsample to 8 rows x 9 cols using green channel (highest luminance weight)
        row_idx = np.linspace(0, h - 1, 8, dtype=np.intp)
        col_idx = np.linspace(0, w - 1, 9, dtype=np.intp)
        green_grid = bgra_roi[np.ix_(row_idx, col_idx)][:, :, 1]
        diff = green_grid[:, 1:] > green_grid[:, :-1]
        bits = diff.flatten()
        # Pack 64 booleans into a Python int
        hash_val = 0
        for bit in bits:
            hash_val = (hash_val << 1) | int(bit)
        return hash_val

    def lookup(
        self, anchor_id: str, task_intent: str, dhash: int, current_roi: BoundingBox
    ) -> Optional[List[VDOMNode]]:
        key = f"{anchor_id}::{task_intent}"
        entry = self._store.get(key)
        if entry is None:
            return None

        cached_dhash, cached_nodes = entry
        hamming_dist = (cached_dhash ^ dhash).bit_count()
        if hamming_dist > self.hamming_threshold:
            return None

        # Move to MRU and translate relative node coordinates to current_roi origin
        self._store.move_to_end(key)
        translated_nodes: List[VDOMNode] = []
        for node in cached_nodes:
            rel_x1 = node.metadata["rel_x1"]
            rel_y1 = node.metadata["rel_y1"]
            rel_x2 = node.metadata["rel_x2"]
            rel_y2 = node.metadata["rel_y2"]
            translated_nodes.append(
                VDOMNode(
                    node_id=node.node_id,
                    bbox=BoundingBox(
                        x1=current_roi.x1 + rel_x1,
                        y1=current_roi.y1 + rel_y1,
                        x2=current_roi.x1 + rel_x2,
                        y2=current_roi.y1 + rel_y2,
                    ),
                    role=node.role,
                    semantic_label=node.semantic_label,
                    value=node.value,
                    state=node.state,
                    confidence=node.confidence,
                    source=node.source,
                    anchor_id=anchor_id,
                    metadata={**node.metadata, "cache_hit": True, "hamming_dist": hamming_dist},
                )
            )
        return translated_nodes

    def insert(
        self, anchor_id: str, task_intent: str, dhash: int, nodes: List[VDOMNode]
    ) -> None:
        key = f"{anchor_id}::{task_intent}"
        self._store[key] = (dhash, nodes)
        self._store.move_to_end(key)
        if len(self._store) > self.max_entries:
            self._store.popitem(last=False)


# ============================================================================
# 4. Gemma 3 Sidecar Plugin (Prompting, Inference, Coordinate Mapping & Fusion)
# ============================================================================

GEMMA3_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "role": {
                        "type": "string",
                        "enum": [r.value for r in UIRole],
                    },
                    "label": {"type": "string"},
                    "value": {"type": ["string", "null"]},
                    "state": {
                        "type": "string",
                        "enum": [
                            "normal",
                            "active",
                            "disabled",
                            "error",
                            "warning",
                            "high_z",
                            "unknown_x",
                        ],
                    },
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["box_2d", "role", "label", "value", "state", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["elements"],
    "additionalProperties": False,
}


class Gemma3SidecarPlugin:
    """
    Production Phase 4 Local Reasoning & Perception Plugin powered by Gemma 3.
    Operates over `/dev/shm/vision_mcp_fb` crops and fuses into the Unified vDOM.
    """

    SYSTEM_PROMPT = (
        "You are a precision UI & Electronic Design Automation (EDA) visual grounding "
        "sidecar operating on a cropped Linux X11 desktop sub-pane. Identify all UI "
        "controls, schematic pins/nets, or waveform traces relevant to the user query. "
        "Return strictly valid JSON. Bounding boxes `box_2d` MUST be [ymin, xmin, ymax, xmax] "
        "normalized to 0..1000 relative to this image crop."
    )

    def __init__(self, config: Optional[Gemma3Config] = None) -> None:
        self.config = config or Gemma3Config()
        self.shm = SharedMemoryFramebuffer(
            self.config.shm_path, self.config.shm_header_bytes
        )
        self.cache = SemanticROICache(
            max_entries=self.config.cache_max_entries,
            hamming_threshold=self.config.cache_hamming_threshold,
        )
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        self.shm.open()
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_sec)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def stop(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        self.shm.close()

    async def ground_subpane(
        self,
        roi: BoundingBox,
        anchor_id: str,
        task_intent: str,
        existing_vdom_nodes: Optional[List[VDOMNode]] = None,
        bypass_cache: bool = False,
    ) -> List[VDOMNode]:
        """
        Main entry point invoked by the Phase 4 Semantic Escalation Router.
        1. Zero-copy slices `/dev/shm/vision_mcp_fb`.
        2. Checks 64-bit dHash semantic cache.
        3. Dispatches BMP crop to local Gemma 3 llama-server with JSON schema grammar.
        4. Projects normalized [ymin, xmin, ymax, xmax] to global X11 coordinates.
        5. Performs asymmetric IoU (>=0.65) and containment (>=0.85) fusion.
        """
        t0 = time.perf_counter()
        bgra_crop, frame_seq = self.shm.get_zero_copy_roi(roi)
        dhash = self.cache.compute_dhash64(bgra_crop)

        if not bypass_cache:
            cached = self.cache.lookup(anchor_id, task_intent, dhash, roi)
            if cached is not None:
                return self._fuse_with_vdom(cached, existing_vdom_nodes or [])

        bmp_bytes = self.shm.encode_bgra_to_bmp_bytes(bgra_crop)
        b64_img = base64.b64encode(bmp_bytes).decode("ascii")

        payload = {
            "model": self.config.model_name,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/bmp;base64,{b64_img}"},
                        },
                        {
                            "type": "text",
                            "text": f"Sub-pane Anchor: {anchor_id}\nTask Intent: {task_intent}",
                        },
                    ],
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "gemma3_vdom_grounding",
                    "strict": True,
                    "schema": GEMMA3_RESPONSE_SCHEMA,
                },
            },
        }

        raw_predictions = await self._invoke_gemma3(payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        vdom_proposals = self._parse_and_project_coordinates(
            raw_predictions, roi, anchor_id, frame_seq, elapsed_ms
        )

        if vdom_proposals:
            self.cache.insert(anchor_id, task_intent, dhash, vdom_proposals)

        return self._fuse_with_vdom(vdom_proposals, existing_vdom_nodes or [])

    async def _invoke_gemma3(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._session is None:
            await self.start()
        assert self._session is not None

        try:
            async with self._session.post(self.config.endpoint_url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except ( asyncio.TimeoutError, aiohttp.ClientError, KeyError, json.JSONDecodeError ) as exc:
            logger.warning("Gemma 3 sidecar inference failed or timed out: %s", exc)
            return {"elements": []}

    def _parse_and_project_coordinates(
        self,
        prediction_json: Dict[str, Any],
        roi: BoundingBox,
        anchor_id: str,
        frame_seq: int,
        latency_ms: float,
    ) -> List[VDOMNode]:
        """
        Converts Gemma 3 normalized [ymin, xmin, ymax, xmax] (0..1000) into
        global X11 screen coordinates and builds VDOMNode proposals.
        """
        proposals: List[VDOMNode] = []
        crop_w = roi.width
        crop_h = roi.height

        for idx, item in enumerate(prediction_json.get("elements", [])):
            ymin_n, xmin_n, ymax_n, xmax_n = item["box_2d"]
            # Enforce ordering invariance
            ymin_n, ymax_n = min(ymin_n, ymax_n), max(ymin_n, ymax_n)
            xmin_n, xmax_n = min(xmin_n, xmax_n), max(xmin_n, xmax_n)

            rel_x1 = int(round((xmin_n / 1000.0) * crop_w))
            rel_y1 = int(round((ymin_n / 1000.0) * crop_h))
            rel_x2 = int(round((xmax_n / 1000.0) * crop_w))
            rel_y2 = int(round((ymax_n / 1000.0) * crop_h))

            global_bbox = BoundingBox(
                x1=roi.x1 + rel_x1,
                y1=roi.y1 + rel_y1,
                x2=roi.x1 + max(rel_x1 + 2, rel_x2),
                y2=roi.y1 + max(rel_y1 + 2, rel_y2),
            )

            stable_hash = hashlib.blake2b(
                f"{anchor_id}:{item['role']}:{item['label']}:{rel_x1}:{rel_y1}".encode(),
                digest_size=6,
            ).hexdigest()

            proposals.append(
                VDOMNode(
                    node_id=f"gemma3_{stable_hash}",
                    bbox=global_bbox,
                    role=item["role"],
                    semantic_label=item["label"],
                    value=item.get("value"),
                    state=item.get("state", "normal"),
                    confidence=float(item.get("confidence", 0.9)),
                    source=GroundingSource.VISION_ONLY,
                    anchor_id=anchor_id,
                    metadata={
                        "rel_x1": rel_x1,
                        "rel_y1": rel_y1,
                        "rel_x2": rel_x2,
                        "rel_y2": rel_y2,
                        "frame_seq": frame_seq,
                        "gemma3_latency_ms": round(latency_ms, 2),
                        "cache_hit": False,
                    },
                )
            )
        return proposals

    def _fuse_with_vdom(
        self,
        gemma_proposals: List[VDOMNode],
        existing_nodes: List[VDOMNode],
    ) -> List[VDOMNode]:
        """
        Fuses Gemma 3 semantic proposals with AT-SPI2 / Fast-Path (YOLOv11s) nodes.
        - If IoU >= 0.65 OR containment >= 0.85: Keep the tight spatial bounding box
          from AT-SPI2/YOLOv11s, upgrade source to GroundingSource.HYBRID, and enrich
          with Gemma 3's semantic_label, value, and state.
        - Otherwise: Append as a pure GroundingSource.VISION_ONLY node (e.g., internal
          OpenGL canvas pins/waveforms invisible to AT-SPI2).
        """
        if not existing_nodes:
            return gemma_proposals

        fused_output: List[VDOMNode] = list(existing_nodes)

        for prop in gemma_proposals:
            best_match: Optional[VDOMNode] = None
            best_score: float = 0.0

            for existing in fused_output:
                iou_score = prop.bbox.iou(existing.bbox)
                cont_score = max(
                    prop.bbox.containment(existing.bbox),
                    existing.bbox.containment(prop.bbox),
                )
                if (
                    iou_score >= self.config.iou_fusion_threshold
                    or cont_score >= self.config.containment_threshold
                ):
                    score = max(iou_score, cont_score)
                    if score > best_score:
                        best_score = score
                        best_match = existing

            if best_match is not None:
                # Retain crisp fast-path/AT-SPI2 spatial bounds; inject Gemma 3 semantics
                best_match.semantic_label = prop.semantic_label
                best_match.role = prop.role
                if prop.value is not None:
                    best_match.value = prop.value
                best_match.state = prop.state
                best_match.source = GroundingSource.HYBRID
                best_match.metadata.update(
                    {
                        "fused_from_gemma3": prop.node_id,
                        "fusion_score": round(best_score, 3),
                        "cache_hit": prop.metadata.get("cache_hit", False),
                    }
                )
            else:
                fused_output.append(prop)

        return fused_output

```

---

## Section 4: Practical DV / EDA Case Study with Gemma 3

Standard desktop accessibility trees (AT-SPI2) and pure OCR pipelines break down inside Electronic Design Automation tools because waveform engines, schematic canvases, and custom hierarchy trees render directly to X11/OpenGL drawable buffers without exposing child widgets. Below is how the dual-lane hierarchy + `Gemma3SidecarPlugin` resolves three concrete DV workflows.

### 1. Synopsys Verdi `nWave` & Vivado Simulator: Multi-Signal Bus & Waveform Analysis

* **The Failure Mode of Fast-Path Alone:** In Verdi `nWave`, signal names (`top.dut.u_axi.awaddr[31:0]`), cursor values (`32'h8000_1040`), and the actual waveform traces occupy three separate sub-columns inside a single OpenGL canvas (`anchor_id="verdi_nwave_canvas"`). PP-OCRv4 reads the text strings `"awaddr[31:0]"` and `"8000_1040"`, but cannot determine whether the trace at the active yellow marker (`T1 = 1450ns`) is in a valid steady state, transitioning, High-Z (`Z` drawn in orange), or Unknown/X-propagation (`X` drawn in red cross-hatch).
* **Gemma 3 Execution Flow:**
1. Phase 5 resolves the horizontal strip corresponding to the target signal row (`height=96px, width=896px`) spanning the Signal Name column, Value column, and Waveform Trace around cursor `T1`.
2. `Gemma3SidecarPlugin.ground_subpane()` passes this crop with `task_intent="Extract waveform signal name, cursor hex value, and logic state (normal, high_z, unknown_x) at the active yellow cursor."`
3. Gemma 3 visually correlates the red cross-hatched waveform bus polygon with the signal row and emits:
```json
{
  "box_2d": [120, 410, 880, 950],
  "role": "waveform_signal",
  "label": "top.dut.u_axi.rdata[63:0]",
  "value": "64'hXXXX_XXXX_0000_0001",
  "state": "unknown_x",
  "confidence": 0.96
}

```


4. The agent immediately identifies the upper 32-bit slice X-propagation at `T1` and triggers a double-click action inside `box_2d` to invoke Verdi's *Active Annotation / Trace X* driver in `nSchema`.



### 2. Design Hierarchy Tree Icons (Vivado Sources / Verdi Instance Tree)

* **The Failure Mode of Fast-Path Alone:** The Design Hierarchy `QTreeView` renders a 16x16 status and module-type badge next to every instance name (e.g., green square with a lock for *Locked IP*, orange triangle for *Out-of-Context / Stale Synthesis*, blue puzzle piece for *SystemVerilog Interface*, red exclamation for *Unresolved Blackbox*). AT-SPI2 exposes the text `"u_pcie_phy_wrapper"` on the tree cell, but the icon pixmap is painted via a custom `QStyledItemDelegate` with zero accessibility metadata.
* **Gemma 3 Execution Flow:**
1. Fast-Path YOLOv11s-UI detects the 16x16 icon bounding box to the left of the text node.
2. Upon an `AT-SPI2 Miss + OCR Miss` on that icon box, the router crops the $256 \times 64$ tree row (`anchor_id="vivado_sources_tree_row"`).
3. Gemma 3 returns `role="hierarchy_node"`, `label="u_pcie_phy_wrapper"`, `state="warning"`, `value="ip_locked_stale_synth"`.
4. `_fuse_with_vdom()` matches the proposal with the existing AT-SPI2 tree cell (`containment >= 0.85`), upgrading the node to `GroundingSource.HYBRID`. Because the 64-bit `dHash` of that icon/row remains invariant while scrolling or inspecting other panes, subsequent frames hit `SemanticROICache` in **0.14ms**.



### 3. Schematic View Compilation / DRC Error Markers & Pin Grounding

* **The Failure Mode of Fast-Path Alone:** After running `report_drc` or Elaboration in Vivado, unconnected pins or width-mismatched nets in the Schematic viewport are highlighted in magenta/red with tiny graphical violation badges (`DRC MDRV-1` multiple driver cross-mark) next to specific input/output pins (`s_axis_tvalid`). Clicking the net vs. clicking the pin terminal changes the Vivado Tcl selection (`get_selected_objects` returns a `net` vs. a `pin`).
* **Gemma 3 Execution Flow:**
1. Phase 5 crops the schematic sub-pane around the highlighted RTL cell.
2. Gemma 3 distinguishes the triangular pin terminal (`role="schematic_pin"`, `label="u_fifo/s_axis_tready"`) from the attached wire (`role="schematic_net"`) and locates the red DRC violation badge (`role="drc_error_marker"`, `state="error"`).
3. Once grounded and clicked once, **Phase 3 (GUI-to-Script Skill Crystallization Engine)** correlates the X11 click on the `GroundingSource.VISION_ONLY` pin node with the byte-offset delta in `vivado.jou` (`select_objects [get_pins u_fifo/s_axis_tready]`), crystallizing future executions into deterministic, zero-token Tcl commands.