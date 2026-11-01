"""
Tests for the Gemma dialog tie-breaker and the VISUAL_QUERY post-condition.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from PIL import Image

from vision_mcp.agent_loop.controller import FeedbackLoopController
from vision_mcp.agent_loop.obstruction import SemanticModalRouter
from vision_mcp.gemma.client import GemmaClient
from vision_mcp.types import (
    BoundingBox,
    ModalButtonOption,
    ModalRiskTier,
    PostConditionAssertion,
    PostConditionContract,
    StateAssertionType,
    WindowInfo,
)
from vision_mcp.vdom.gemma3_sidecar import Gemma3Grounder

from test_gemma3_sidecar import FakeOllama


def _buttons(*labels: str) -> List[ModalButtonOption]:
    return [
        ModalButtonOption(button_id=f"btn_{i}", label=lbl, bbox=BoundingBox(x=10 * i, y=0, width=8, height=8))
        for i, lbl in enumerate(labels)
    ]


def _verdict(tier: str, button=None, confidence=0.95) -> Dict[str, Any]:
    return {"risk_tier": tier, "suggested_button": button, "confidence": confidence, "reason": "r", "source": "gemma"}


class RecordingClassifier:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    def __call__(self, text, labels):
        self.calls.append((text, labels))
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


# ----------------------------------------------------------------- tie-breaker


def test_unmatched_dialog_dismissed_on_confident_safe_verdict():
    clf = RecordingClassifier(_verdict("BENIGN_DISMISSIBLE", "Not now"))
    router = SemanticModalRouter(classifier=clf)
    tier, btn, payload = router.classify_and_route("Rate this app", "Enjoying the tool?", _buttons("Rate", "Not now"))
    assert tier == ModalRiskTier.BENIGN_DISMISSIBLE
    assert btn is not None and btn.label == "Not now"
    assert payload is None
    assert router.last_source == "gemma"
    assert clf.calls[0][1] == ["Rate", "Not now"]


def test_gemma_can_make_verdict_stricter():
    clf = RecordingClassifier(_verdict("DESTRUCTIVE_OR_SYSTEM"))
    router = SemanticModalRouter(classifier=clf)
    tier, btn, payload = router.classify_and_route("Vivado", "Clear all results from this run?", _buttons("Yes", "Cancel"))
    assert tier == ModalRiskTier.DESTRUCTIVE_OR_SYSTEM
    assert btn is None
    assert payload.risk_tier == ModalRiskTier.DESTRUCTIVE_OR_SYSTEM


@pytest.mark.parametrize(
    "verdict",
    [
        _verdict("BENIGN_DISMISSIBLE", "Not now", confidence=0.5),  # not confident enough
        _verdict("BENIGN_DISMISSIBLE", "Rate"),  # not a known-safe dismiss label
        _verdict("WORKFLOW_BRANCHING"),
        {"risk_tier": "BENIGN_DISMISSIBLE", "suggested_button": "Not now", "confidence": 0.99, "source": "fallback"},
        RuntimeError("ollama down"),
    ],
)
def test_unsafe_or_uncertain_verdicts_escalate(verdict):
    router = SemanticModalRouter(classifier=RecordingClassifier(verdict))
    tier, btn, payload = router.classify_and_route("Rate this app", "Enjoying the tool?", _buttons("Rate", "Not now"))
    assert tier == ModalRiskTier.WORKFLOW_BRANCHING
    assert btn is None
    assert payload is not None


def test_rules_win_and_gemma_not_called_when_rules_match():
    clf = RecordingClassifier(_verdict("BENIGN_DISMISSIBLE", "OK"))
    router = SemanticModalRouter(classifier=clf)
    # Destructive keyword: rules decide, Gemma is never asked
    tier, btn, _ = router.classify_and_route("Confirm", "Delete the project directory?", _buttons("OK", "Cancel"))
    assert tier == ModalRiskTier.DESTRUCTIVE_OR_SYSTEM and btn is None
    # Branching keyword: rules escalate, Gemma is never asked
    tier, btn, _ = router.classify_and_route("Vivado", "Design is out-of-date. Re-run?", _buttons("OK", "Cancel"))
    assert tier == ModalRiskTier.WORKFLOW_BRANCHING and btn is None
    assert clf.calls == []
    assert router.last_source == "rules"


def test_no_classifier_keeps_old_behaviour():
    router = SemanticModalRouter()
    tier, btn, payload = router.classify_and_route("Rate this app", "Enjoying the tool?", _buttons("Rate", "Not now"))
    assert tier == ModalRiskTier.WORKFLOW_BRANCHING and btn is None and payload is not None


# ----------------------------------------------------------- visual query


def _controller_with_fake(fake: FakeOllama) -> FeedbackLoopController:
    hal = MagicMock()
    hal.capture_screen.return_value = Image.new("RGB", (1600, 1000), "white")
    hal.get_active_window.return_value = WindowInfo(
        window_id="1", title="Vivado", bbox=BoundingBox(x=100, y=50, width=1600, height=1000)
    )
    hal._is_wayland = False
    ctrl = FeedbackLoopController.__new__(FeedbackLoopController)
    ctrl.hal = hal
    ctrl.neural_grounder = MagicMock()
    ctrl.neural_grounder.gemma3_grounder = Gemma3Grounder(client=GemmaClient(transport=fake))
    ctrl.atspi_inspector = MagicMock()
    ctrl.quiescence_monitor = None
    return ctrl


def _contract(question="Is the Save dialog closed?", region=None):
    return PostConditionContract(assertions=[
        PostConditionAssertion(
            assertion_type=StateAssertionType.VISUAL_QUERY,
            visual_question=question,
            visual_region=region,
        )
    ])


def test_visual_query_passes_and_crops_active_window():
    fake = FakeOllama(replies=[{"answer": True, "confidence": 0.9, "evidence": "No dialog visible"}])
    ctrl = _controller_with_fake(fake)
    ok, details = ctrl.verify_post_conditions(_contract())
    assert ok, details
    ctrl.hal.capture_screen.assert_called_once_with(region=(100, 50, 1600, 1000))
    body = fake.chat_calls[0]
    assert body["messages"][1]["content"] == "Is the Save dialog closed?"
    assert body["format"]["required"] == ["answer", "confidence", "evidence"]


def test_visual_query_downscales_crop_to_gemma_tile():
    import base64, io

    fake = FakeOllama(replies=[{"answer": True, "confidence": 0.9, "evidence": "ok"}])
    ctrl = _controller_with_fake(fake)
    ctrl.verify_post_conditions(_contract(region=[0, 0, 1600, 1000]))
    img = Image.open(io.BytesIO(base64.b64decode(fake.chat_calls[0]["messages"][1]["images"][0])))
    assert max(img.size) == 896


@pytest.mark.parametrize(
    "fake",
    [
        FakeOllama(replies=[{"answer": False, "confidence": 0.9, "evidence": "Save dialog still open"}]),
        FakeOllama(replies=[{"answer": True, "confidence": 0.3, "evidence": "unclear"}]),
        FakeOllama(fail=TimeoutError("timed out")),
    ],
)
def test_visual_query_fails_when_no_or_unsure_or_unavailable(fake):
    ok, details = _controller_with_fake(fake).verify_post_conditions(_contract())
    assert not ok
    assert "VISUAL_QUERY" in details[0]


def test_ask_screen_without_gemma():
    ctrl = _controller_with_fake(FakeOllama())
    ctrl.neural_grounder.gemma3_grounder = None
    res = ctrl.ask_screen("Is it running?")
    assert res["answer"] is None and res["source"] == "fallback"
