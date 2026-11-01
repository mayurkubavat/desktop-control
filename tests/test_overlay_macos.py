"""Tests for the macOS overlay helper that need AppKit and a window server."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="needs AppKit")


def test_panel_sits_above_menus():
    AppKit = pytest.importorskip("AppKit")
    from dobby.overlay import mac_helper

    screen = AppKit.NSScreen.mainScreen()
    if screen is None:
        pytest.skip("no window server connection")
    panel = mac_helper._Panel(screen, mac_helper.DEFAULT_CONFIG, (0.5, 0.4, 1.0))
    try:
        assert panel.window.level() == AppKit.NSScreenSaverWindowLevel
    finally:
        panel.close()
