"""Gemma prompt pack: registry, overrides, three-valued answers, OCR-checked evidence."""

from PIL import Image

from vision_mcp.gemma.client import GemmaClient
from vision_mcp.gemma.prompts import (
    PROMPTS,
    evidence_in_ocr,
    get_prompt,
    list_prompts,
    parse_answer,
    yes_no_user,
)
from vision_mcp.vdom.gemma3_sidecar import Gemma3Grounder

from test_gemma3_sidecar import FakeOllama

IMG = Image.new("RGB", (200, 100), (240, 240, 240))


def _ask(reply, ocr=None):
    fake = FakeOllama(replies=[reply])
    g = Gemma3Grounder(client=GemmaClient(transport=fake))
    return g.ask_yes_no(IMG, "Did synthesis finish?", ocr_lines=ocr), fake


def test_registry_has_every_gemma_call():
    assert set(PROMPTS) == {"yes_no", "modal_triage", "mark_label", "mark_find", "ground_roi", "compress_history"}
    assert get_prompt("yes_no", prompt_dir="").tag == "yes_no@2"
    assert all(p["system"] for p in list_prompts())


def test_local_override(tmp_path):
    (tmp_path / "yes_no.txt").write_text("Custom checker prompt.")
    spec = get_prompt("yes_no", prompt_dir=str(tmp_path))
    assert spec.system == "Custom checker prompt." and spec.tag == "yes_no@2+local"
    assert spec.schema == PROMPTS["yes_no"].schema


def test_parse_answer():
    assert parse_answer("yes") is True and parse_answer("No") is False
    assert parse_answer("unsure") is None and parse_answer(None) is None
    assert parse_answer(True) is True  # v1 replies


def test_evidence_in_ocr():
    lines = ["Synthesis Completed", "Run Implementation"]
    assert evidence_in_ocr("'synthesis completed'", lines)
    assert evidence_in_ocr("Completed synthesis", lines)  # word overlap
    assert not evidence_in_ocr("Implementation failed with errors", lines)
    assert not evidence_in_ocr("", lines)


def test_user_message_includes_ocr_and_truncates():
    msg = yes_no_user("Is it done?", ["Done", "x" * 2000])
    assert msg.startswith("Question: Is it done?") and "- Done" in msg and msg.endswith("...")
    assert yes_no_user("Q?", []) == "Question: Q?"


def test_unsure_is_none_not_a_guess():
    res, _ = _ask({"answer": "unsure", "confidence": 0.7, "evidence_type": "none", "evidence": ""})
    assert res["answer"] is None and res["confidence"] == 0.0 and res["source"] == "gemma"
    assert res["prompt"] == "yes_no@2"


def test_text_evidence_confirmed_by_ocr_keeps_confidence():
    res, fake = _ask(
        {"answer": "yes", "confidence": 0.93, "evidence_type": "text", "evidence": "Synthesis Completed"},
        ocr=["Synthesis Completed", "OK"],
    )
    assert res["answer"] is True and res["evidence_verified"] is True and res["confidence"] == 0.93
    assert "OCR text in this crop" in fake.chat_calls[0]["messages"][1]["content"]


def test_hallucinated_text_evidence_is_capped():
    res, _ = _ask(
        {"answer": "yes", "confidence": 0.95, "evidence_type": "text", "evidence": "Synthesis Completed"},
        ocr=["Running synth_design", "Cancel"],
    )
    assert res["answer"] is True and res["evidence_verified"] is False
    assert res["confidence"] <= 0.5  # below the 0.6 VISUAL_QUERY and 0.82 tier-1 bars


def test_visual_evidence_is_not_checked():
    res, _ = _ask(
        {"answer": "no", "confidence": 0.8, "evidence_type": "visual", "evidence": "red status icon"},
        ocr=["Status"],
    )
    assert res["answer"] is False and res["evidence_verified"] is None and res["confidence"] == 0.8


def test_bad_answer_falls_back():
    res, _ = _ask({"answer": "maybe", "confidence": 0.9, "evidence_type": "none", "evidence": ""})
    assert res["answer"] is None and res["source"] == "fallback"


def test_ask_screen_passes_ocr_context():
    from unittest.mock import MagicMock

    from vision_mcp.agent_loop.controller import FeedbackLoopController
    from vision_mcp.perception.ocr import CachedOCR, OCREngine, OCRLine

    class _Ocr(OCREngine):
        name = "fake"

        @property
        def is_available(self):
            return True

        def _recognize(self, image):
            return [OCRLine("Simulation finished", 10, 10, 150, 20, 0.97)]

    fake = FakeOllama(replies=[{"answer": "yes", "confidence": 0.9, "evidence_type": "text", "evidence": "Simulation finished"}])
    hal = MagicMock()
    hal.get_active_window.return_value = None
    hal.capture_screen.return_value = IMG
    ctrl = FeedbackLoopController(hal)
    ctrl.neural_grounder.gemma3_grounder = Gemma3Grounder(client=GemmaClient(transport=fake))
    ctrl.ocr = CachedOCR(_Ocr())
    res = ctrl.ask_screen("Is the simulation done?")
    assert res["answer"] is True and res["evidence_verified"] is True
    assert "- Simulation finished" in fake.chat_calls[0]["messages"][1]["content"]
