"""Vision Control Model Context Protocol (MCP) Server.

Exposes tools for autonomous Linux and cross-platform desktop UI navigation,
perception with Set-of-Marks and AT-SPI accessibility trees, input injection,
and closed-loop verification.
"""

import sys
import subprocess
import time
from typing import Optional, List, Dict, Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from vision_mcp.hal.factory import get_desktop_hal
from vision_mcp.agent_loop.controller import FeedbackLoopController
from vision_mcp.config import CONFIG

# Initialize Server and Feedback Loop Controller
mcp_server = MCPServer("vision-control-mcp")
hal = get_desktop_hal()
controller = FeedbackLoopController(hal)


@mcp_server.tool()
def take_screenshot(
    mode: str = "annotated_som",
    app_filter: Optional[str] = None,
    region: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Captures the desktop screen with visual perception and grounding.

    Args:
        mode: Grounding mode:
              - 'annotated_som': Overlays Set-of-Marks numbered badges on interactable elements.
              - 'cursor_only': Screenshot showing current mouse pointer position.
              - 'raw': Clean desktop screenshot without annotations.
        app_filter: Optional application title or process filter for AT-SPI introspection.
        region: Optional [x, y, width, height] bounding box. If None, captures primary screen.

    Returns:
        Dictionary containing:
        - image_base64: Base64 JPEG string of the captured screen.
        - mime_type: "image/jpeg"
        - width, height: Dimensions of the returned image.
        - original_width, original_height: Physical desktop display resolution.
        - scale_factor: Ratio applied to optimize token usage (e.g. 0.53).
        - marks: List of tagged UI elements with their mark IDs, roles, names, and coordinates.
        - cursor_position: Current pointer coordinates [x, y].
    """
    reg_tuple = tuple(region) if region and len(region) == 4 else None
    result = controller.capture_state(
        mode=mode,
        app_filter=app_filter,
        region=reg_tuple,
    )
    return result.model_dump()


@mcp_server.tool()
def get_accessibility_tree(
    app_name_filter: Optional[str] = None,
    max_depth: int = 16,
    filter_interactable: bool = True,
) -> List[Dict[str, Any]]:
    """
    Directly queries Linux AT-SPI2 (or OS accessibility bus) for the live semantic UI tree.
    Provides ground-truth element names, roles, and physical bounding boxes without visual hallucination.

    Args:
        app_name_filter: Filter to target a specific app (e.g. 'terminal', 'gedit', 'calc').
        max_depth: Maximum hierarchy recursion depth.
        filter_interactable: If True, only returns clickable or typable elements.

    Returns:
        List of UIElement objects with: id, role, name, bbox [x, y, w, h], and interactable state.
    """
    elements = controller.atspi_inspector.inspect_desktop(
        app_name_filter=app_name_filter,
        max_depth=max_depth,
        filter_interactable=filter_interactable,
    )
    return [elem.model_dump() for elem in elements]


@mcp_server.tool()
def click(
    mark_id: Optional[int] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    click_count: int = 1,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Clicks on a UI element either by its Set-of-Marks ID or physical (x, y) coordinates.

    Args:
        mark_id: Numeric badge ID from the last 'annotated_som' screenshot (e.g., 5).
        x: Physical X pixel coordinate (used if mark_id is not specified).
        y: Physical Y pixel coordinate (used if mark_id is not specified).
        button: 'left', 'right', or 'middle'.
        click_count: 1 for single click, 2 for double click, 3 for triple click.
        verify_delta: Whether to automatically check if the screen visually changed post-click.

    Returns:
        Verification result detailing success, delta detected, and visual change ratio.
    """
    target_x, target_y = controller.resolve_target_coordinates(mark_id=mark_id, x=x, y=y)

    def _do_click():
        hal.mouse_click(target_x, target_y, button=button, click_count=click_count)

    res = controller.execute_with_verification(
        action_name=f"click({button}, count={click_count}) at ({target_x}, {target_y})",
        action_func=_do_click,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def move_cursor(x: int, y: int) -> Dict[str, Any]:
    """
    Moves the mouse pointer to absolute coordinates (x, y) without clicking.

    Args:
        x: Target X coordinate.
        y: Target Y coordinate.
    """
    hal.mouse_move(x, y)
    return {"success": True, "cursor_position": [x, y]}


@mcp_server.tool()
def drag_and_drop(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration_sec: float = 0.3,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Smoothly drags mouse pointer from start coordinates to end coordinates.

    Args:
        start_x, start_y: Drag origin.
        end_x, end_y: Drag destination.
        duration_sec: Duration of mouse travel.
        verify_delta: Whether to verify visual change after dropping.
    """
    def _do_drag():
        hal.mouse_drag(start_x, start_y, end_x, end_y, duration_sec=duration_sec)

    res = controller.execute_with_verification(
        action_name=f"drag from ({start_x}, {start_y}) to ({end_x}, {end_y})",
        action_func=_do_drag,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def scroll(
    direction: str = "down",
    amount: int = 3,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Emulates mouse wheel scroll at current cursor location.

    Args:
        direction: 'up', 'down', 'left', or 'right'.
        amount: Number of scroll increments / notches.
        verify_delta: Whether to verify visual delta post-scroll.
    """
    dx, dy = 0, 0
    if direction == "up":
        dy = amount
    elif direction == "down":
        dy = -amount
    elif direction == "left":
        dx = -amount
    elif direction == "right":
        dx = amount

    def _do_scroll():
        hal.mouse_scroll(dx=dx, dy=dy)

    res = controller.execute_with_verification(
        action_name=f"scroll({direction}, amount={amount})",
        action_func=_do_scroll,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def type_text(
    text: str,
    press_enter: bool = False,
    delay_ms: float = 12.0,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Types text into the currently focused desktop element.

    Args:
        text: Text to type.
        press_enter: Whether to press Enter key after typing string.
        delay_ms: Keystroke cadence in milliseconds.
        verify_delta: Whether to verify screen delta after typing.
    """
    def _do_type():
        hal.keyboard_type(text, delay_ms=delay_ms)
        if press_enter:
            hal.keyboard_press_key("enter")

    res = controller.execute_with_verification(
        action_name=f"type_text(len={len(text)}, enter={press_enter})",
        action_func=_do_type,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def press_key(key: str, verify_delta: bool = True) -> Dict[str, Any]:
    """
    Presses and releases a single key.

    Args:
        key: Key identifier (e.g., 'enter', 'tab', 'escape', 'backspace', 'space', 'down', 'f5').
        verify_delta: Whether to verify screen delta.
    """
    def _do_press():
        hal.keyboard_press_key(key)

    res = controller.execute_with_verification(
        action_name=f"press_key({key})",
        action_func=_do_press,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def hotkey(combo: str, verify_delta: bool = True) -> Dict[str, Any]:
    """
    Sends a keyboard chord shortcut.

    Args:
        combo: Plus-delimited shortcut (e.g. 'ctrl+c', 'ctrl+alt+t', 'alt+tab', 'ctrl+shift+p').
        verify_delta: Whether to verify screen delta after shortcut.
    """
    keys = [k.strip() for k in combo.split("+")]

    def _do_hotkey():
        hal.keyboard_hotkey(keys)

    res = controller.execute_with_verification(
        action_name=f"hotkey({combo})",
        action_func=_do_hotkey,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def list_windows() -> List[Dict[str, Any]]:
    """
    Lists open desktop windows, titles, geometry bounds, and active focus status.
    """
    windows = hal.list_windows()
    return [win.model_dump() for win in windows]


@mcp_server.tool()
def focus_window(window_id: str) -> Dict[str, Any]:
    """
    Brings target window to the foreground and grants it focus.

    Args:
        window_id: Hex or integer window identifier from list_windows().
    """
    ok = hal.focus_window(window_id)
    return {"success": ok, "window_id": window_id}


@mcp_server.tool()
def run_terminal_command(
    command: str,
    timeout_seconds: int = CONFIG.command_timeout_seconds,
) -> Dict[str, Any]:
    """
    Executes a shell command in the background.
    Provides fast hybrid CLI navigation when visual GUI interaction is redundant.

    Args:
        command: Bash command line to execute.
        timeout_seconds: Max seconds to wait before terminating.

    Returns:
        Dict with exit_code, stdout, stderr, and execution_time_sec.
    """
    if not CONFIG.allow_terminal_commands:
        return {"success": False, "error": "Terminal commands are disabled in configuration."}

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        elapsed = time.perf_counter() - start
        return {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "execution_time_sec": round(elapsed, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": -1,
            "error": f"Command timed out after {timeout_seconds} seconds",
            "execution_time_sec": timeout_seconds,
        }
    except Exception as e:
        return {
            "success": False,
            "exit_code": -1,
            "error": str(e),
        }


@mcp_server.tool()
def wait_for_ui_change(
    timeout_seconds: float = 5.0,
    poll_interval_sec: float = 0.2,
    min_delta_ratio: float = 0.005,
) -> Dict[str, Any]:
    """
    Blocks until a visual change occurs on the desktop (e.g. waiting for page load or modal popup).

    Args:
        timeout_seconds: Max time to wait.
        poll_interval_sec: Polling interval between frames.
        min_delta_ratio: Threshold fraction of pixels that must change.
    """
    initial_img, _, _, _ = controller.pipeline.capture(draw_cursor=False, scale_down=True)
    start_time = time.perf_counter()

    while time.perf_counter() - start_time < timeout_seconds:
        time.sleep(poll_interval_sec)
        current_img, _, _, _ = controller.pipeline.capture(draw_cursor=False, scale_down=True)
        delta = controller.pipeline.compute_image_delta(initial_img, current_img)
        if delta >= min_delta_ratio:
            return {
                "change_detected": True,
                "delta_ratio": round(delta, 4),
                "elapsed_sec": round(time.perf_counter() - start_time, 3),
            }

    return {
        "change_detected": False,
        "delta_ratio": 0.0,
        "elapsed_sec": timeout_seconds,
        "message": "Timed out waiting for visual change.",
    }


def main():
    """Starts the FastMCP server in standard I/O mode."""
    mcp_server.run()


if __name__ == "__main__":
    main()
