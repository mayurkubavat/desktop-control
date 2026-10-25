"""
Tests for Local Gemma 3 Multimodal Sidecar and Perceptual dHash Cache.
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image, ImageDraw

from vision_mcp.types import (
    BoundingBox,
    GroundingSource,
    UIRole,
    VDOMNode,
    VirtualDOMSnapshot,
)
from vision_mcp.vdom.gemma3_sidecar import (
    Gemma3Grounder,
    SemanticROICache,
    compute_dhash,
    hamming_distance,
)
from vision_mcp.vdom.sidecar import LocalNeuralGrounder


def _create_sample_image(color="white", draw_button=True) -> Image.Image:
    img = Image.new("RGB", (200, 100), color=color)
    if draw_button:
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 80, 60], fill="blue", outline="black")
        draw.rectangle([100, 20, 180, 60], fill="gray", outline="black")
    return img


def test_dhash_and_hamming_distance():
    img1 = _create_sample_image("white", draw_button=True)
    img2 = _create_sample_image("white", draw_button=True)
    img3 = _create_sample_image("black", draw_button=False)

    h1 = compute_dhash(img1)
    h2 = compute_dhash(img2)
    h3 = compute_dhash(img3)

    assert h1 == h2
    assert hamming_distance(h1, h2) == 0
    assert hamming_distance(h1, h3) > 10


def test_semantic_roi_cache():
    cache = SemanticROICache(capacity=2, threshold=4)
    proposals = [
        {"rel_box": {"x": 10, "y": 10, "width": 50, "height": 30}, "class_name": "push_button", "confidence": 0.95}
    ]

    h1 = 0x123456789ABCDEF0
    cache.put("anchor_a:intent_1", h1, proposals)

    # Exact hit
    assert cache.get("anchor_a:intent_1", h1) == proposals

    # Perceptual hit (Hamming distance = 1 bit flipped)
    h1_drift = h1 ^ 0x01
    assert hamming_distance(h1, h1_drift) == 1
    assert cache.get("anchor_a:intent_1", h1_drift) == proposals

    # Miss due to large distance
    h_distant = h1 ^ 0xFFFFFFFFFF
    assert cache.get("anchor_a:intent_1", h_distant) is None

    # Test LRU eviction
    cache.put("anchor_b:intent_1", 0x1111, proposals)
    cache.put("anchor_c:intent_1", 0x2222, proposals)
    assert len(cache) == 2
    assert cache.get("anchor_a:intent_1", h1) is None


def test_gemma3_grounder_mocked_http():
    grounder = Gemma3Grounder(endpoint="http://127.0.0.1:11434/api/generate", timeout=5.0)

    mock_ollama_response = {
        "response": json.dumps({
            "elements": [
                {
                    "box_2d": [100, 200, 500, 600],
                    "role": "icon_button",
                    "label": "Zoom Fit",
                    "confidence": 0.96,
                },
                {
                    "box_2d": [600, 100, 900, 800],
                    "role": "waveform_signal",
                    "label": "clk_250m",
                    "confidence": 0.91,
                },
            ]
        })
    }

    img = _create_sample_image()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_ollama_response).encode("utf-8")
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        proposals = grounder.ground_roi(
            image=img,
            offset=(50, 100),
            anchor_id="waveform_canvas",
            task_intent="find_zoom_fit",
        )

        assert len(proposals) == 2
        # First element: box_2d [100, 200, 500, 600] on 200x100 img:
        # rel_x = 200 * 200 / 1000 = 40; rel_y = 100 * 100 / 1000 = 10;
        # rel_w = (600 - 200) * 200 / 1000 = 80; rel_h = (500 - 100) * 100 / 1000 = 40
        # abs_x = 50 + 40 = 90; abs_y = 100 + 10 = 110
        p1 = proposals[0]
        assert p1["bbox"]["x"] == 90
        assert p1["bbox"]["y"] == 110
        assert p1["bbox"]["width"] == 80
        assert p1["bbox"]["height"] == 40
        assert p1["class_name"] == "icon_button"
        assert p1["text"] == "Zoom Fit"

        # Subsequent call with same image and anchor must hit cache with zero HTTP calls
        mock_urlopen.reset_mock()
        cached_proposals = grounder.ground_roi(
            image=img,
            offset=(50, 100),
            anchor_id="waveform_canvas",
            task_intent="find_zoom_fit",
        )
        assert len(cached_proposals) == 2
        mock_urlopen.assert_not_called()


def test_gemma3_modal_classification():
    grounder = Gemma3Grounder()
    mock_modal_response = {
        "response": json.dumps({
            "risk_level": "DESTRUCTIVE",
            "default_action": "Cancel",
            "confidence": 0.98,
            "reason": "Dialog prompts to reset simulation dropping all recorded waveforms.",
        })
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_modal_response).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = grounder.classify_modal("Reset simulation and discard unsaved waveforms?")
        assert result["risk_level"] == "DESTRUCTIVE"
        assert result["default_action"] == "Cancel"
        assert result["confidence"] == 0.98


def test_gemma3_vdom_fusion():
    grounder = Gemma3Grounder()
    root = VDOMNode(
        node_id="root_1",
        role=UIRole.WINDOW,
        name="Main Window",
        bbox=BoundingBox(x=0, y=0, width=1920, height=1080),
        source=GroundingSource.AT_SPI2,
    )
    vdom = VirtualDOMSnapshot(
        snapshot_id="snap_test_1",
        timestamp=1.0,
        window_title="Vivado 2025.1",
        window_bbox=BoundingBox(x=0, y=0, width=1920, height=1080),
        root_id="root_1",
        nodes={"root_1": root},
    )

    proposals = [
        {
            "bbox": {"x": 200, "y": 300, "width": 80, "height": 30},
            "class_name": "push_button",
            "text": "Run Simulation",
            "confidence": 0.94,
        }
    ]

    fused_vdom = grounder.fuse_with_vdom(vdom, proposals, anchor_id="tcl_console")
    assert len(fused_vdom.nodes) == 2
    assert "gemma3_2" in fused_vdom.nodes
    gemma_node = fused_vdom.nodes["gemma3_2"]
    assert gemma_node.node_id == "gemma3_2"
    assert gemma_node.role == UIRole.PUSH_BUTTON
    assert gemma_node.name == "Run Simulation"
    assert gemma_node.source == GroundingSource.VISION_ONLY
    assert gemma_node.attributes.get("anchor_id") == "tcl_console"
    assert gemma_node.click_point == (240, 315)
    assert "gemma3_2" in fused_vdom.nodes["root_1"].children_ids


def test_local_neural_grounder_delegation():
    grounder = LocalNeuralGrounder(enable_gemma3=True)
    img = _create_sample_image()

    with patch.object(grounder.gemma3_grounder, "ground_roi") as mock_ground_roi:
        mock_ground_roi.return_value = [
            {
                "bbox": {"x": 30, "y": 40, "width": 50, "height": 20},
                "confidence": 0.92,
                "class_name": "icon_button",
                "text": "Step",
                "source": "VISION_ONLY",
            }
        ]

        proposals = grounder.ground_subpane(img, offset=(10, 20), anchor_id="sim_toolbar")
        assert len(proposals) == 1
        assert proposals[0]["class_name"] == "icon_button"
        mock_ground_roi.assert_called_once()
