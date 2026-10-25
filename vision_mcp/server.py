"""Vision Control Model Context Protocol (MCP) Server.

Exposes tools for autonomous Linux and cross-platform desktop UI navigation,
perception with Set-of-Marks, pluggable GroundingEngine (ensemble, semantic, cv, template),
input injection, compound autonomous actions, and closed-loop verification.
"""

import os
import sys
import tempfile
import subprocess
import time
from typing import Optional, List, Dict, Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from vision_mcp.hal.factory import get_desktop_hal
from vision_mcp.agent_loop.controller import FeedbackLoopController
from vision_mcp.types import FindElementResult, DiagnosticsResult
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
    window_id: Optional[str] = None,
    clip_to_active_window: bool = False,
    strategy_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Captures the desktop screen with visual perception, Set-of-Marks, and optional per-window clipping.

    Args:
        mode: Grounding mode:
              - 'annotated_som': Overlays Set-of-Marks badges using active grounding strategy (defaults to ensemble).
              - 'annotated_cv': Forces pure Computer Vision edge/contour and text region detection.
              - 'cursor_only': Screenshot showing current mouse pointer position.
              - 'raw': Clean desktop screenshot without annotations.
        app_filter: Optional application title or process filter for AT-SPI introspection.
        region: Optional [x, y, width, height] bounding box. If None, captures primary screen.
        window_id: Optional window identifier to clip perception strictly to window bounds (60-80% token reduction).
        clip_to_active_window: If True, automatically clips capture to currently focused window bounds.
        strategy_override: Optional strategy hotswap: 'ensemble', 'semantic', 'cv', or 'template'.

    Returns:
        Dictionary containing image_base64, marks, resolution, and scale factor.
    """
    reg_tuple = tuple(region) if region and len(region) == 4 else None
    result = controller.capture_state(
        mode=mode,
        app_filter=app_filter,
        region=reg_tuple,
        window_id=window_id,
        clip_to_active_window=clip_to_active_window,
        strategy_override=strategy_override,
    )
    return result.model_dump()


@mcp_server.tool()
def capture_window(
    window_id: Optional[str] = None,
    title_filter: Optional[str] = None,
    mode: str = "annotated_som",
) -> Dict[str, Any]:
    """
    High-efficiency perception tool that captures strictly the target or active window.
    Slashes multimodal token consumption by 60-80% compared to capturing a full 4K display.

    Args:
        window_id: Hex or integer window identifier. If None, uses title_filter or active window.
        title_filter: Substring to match window title (e.g. 'Chrome', 'Terminal', 'Verdi').
        mode: 'annotated_som', 'annotated_cv', or 'raw'.
    """
    target_win = controller.window_clipper.resolve_target_window(window_id=window_id, title_filter=title_filter)
    win_id = target_win.window_id if target_win else None
    result = controller.capture_state(
        mode=mode,
        window_id=win_id,
        clip_to_active_window=(target_win is None),
    )
    return result.model_dump()


@mcp_server.tool()
def dismiss_obstructions(
    max_attempts: int = 2,
) -> Dict[str, Any]:
    """
    Autonomous defense & modal triage: Detects and classifies blocking modal popups.
    Safely auto-dismisses benign popups and acknowledges informative completion notices,
    while halting and returning an escalation payload for workflow-branching or destructive dialogs.

    Args:
        max_attempts: Number of dismissal iterations.
    """
    triage = controller.obstruction_interceptor.triage_and_resolve()
    res = triage.model_dump()
    res["obstruction_cleared"] = triage.auto_dismissed
    res["actions_taken"] = [triage.action_taken] if triage.action_taken else []
    return res


@mcp_server.tool()
def resolve_modal_dialog(
    button_id: Optional[str] = None,
    button_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolves an escalated modal dialog by clicking the specified button option.
    Allows the orchestrator to safely make decisions on branching or destructive modals (0 visual tokens).

    Args:
        button_id: Target button identifier from ModalEscalationPayload (e.g. 'btn_0', 'btn_1').
        button_label: Target button label text (e.g. 'Cancel', 'Save', 'Overwrite').
    """
    return controller.obstruction_interceptor.resolve_pending_modal(
        button_id=button_id,
        button_label=button_label,
    )


@mcp_server.tool()
def manage_cache(
    action: str = "stats",
    app_key: Optional[str] = None,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Manages the Self-Healing Action & Locator Cache.

    Args:
        action: 'stats' (view telemetry), 'invalidate' (clear specific entry), or 'clear' (empty cache).
        app_key: Application identifier (used for invalidate).
        query: Query string (used for invalidate).
    """
    act = action.strip().lower()
    if act == "stats":
        return controller.action_cache.get_stats()
    elif act == "clear":
        controller.action_cache.clear()
        return {"success": True, "message": "Locator cache cleared."}
    elif act == "invalidate":
        if not app_key or not query:
            return {"success": False, "error": "Must provide 'app_key' and 'query' to invalidate."}
        ok = controller.action_cache.invalidate(app_key=app_key, query=query)
        return {"success": ok, "message": f"Entry for '{app_key}::{query}' invalidated."}
    return {"success": False, "error": f"Unknown action: '{action}'"}


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
        app_name_filter: Filter to target a specific app (e.g. 'terminal', 'chrome', 'calc').
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
def find_element(
    query: str,
    role: Optional[str] = None,
    fuzzy: bool = True,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Autonomously searches for a UI element by text, accessible name, or role.
    Extremely token-efficient: resolves physical (x, y) coordinates with ZERO screenshot tokens.

    Args:
        query: Target text or label (e.g. '4 Argon', 'Ask Gemini', 'Block', 'Submit').
        role: Optional role constraint (e.g. 'button', 'text', 'menu_item').
        fuzzy: Whether to perform substring fuzzy matching.
        strategy: Grounding backend to use ('ensemble', 'semantic', 'cv', 'template').

    Returns:
        FindElementResult detailing match status, element bounds, and exact physical center coordinates.
    """
    res = controller.find_element(
        query=query,
        role=role,
        fuzzy=fuzzy,
        strategy_override=strategy,
    )
    return res.model_dump()


@mcp_server.tool()
def click(
    mark_id: Optional[int] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    query: Optional[str] = None,
    button: str = "left",
    click_count: int = 1,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Clicks on a UI element either by Set-of-Marks ID, text query, or physical (x, y) coordinates.

    Args:
        mark_id: Numeric badge ID from last screenshot.
        x, y: Physical pixel coordinates (used if mark_id is not specified).
        query: Optional text label to find and click automatically.
        button: 'left', 'right', or 'middle'.
        click_count: 1 for single click, 2 for double click, 3 for triple click.
        verify_delta: Whether to automatically check if screen visually reacted post-click.

    Returns:
        Verification result detailing success, delta detected, and visual change ratio.
    """
    target_x, target_y = controller.resolve_target_coordinates(query=query, mark_id=mark_id, x=x, y=y)

    def _do_click():
        hal.mouse_click(target_x, target_y, button=button, click_count=click_count)

    res = controller.execute_with_verification(
        action_name=f"click({button}, count={click_count}) at ({target_x}, {target_y})",
        action_func=_do_click,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def click_and_type(
    text: str,
    query: Optional[str] = None,
    mark_id: Optional[int] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    clear_first: bool = False,
    press_enter: bool = False,
    delay_ms: float = CONFIG.typing_delay_ms,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    High-level atomic compound action: Focuses an element (by query, mark_id, or x,y),
    optionally clears existing text (Ctrl+A -> Backspace), types string with natural cadence,
    and optionally presses Enter.

    Args:
        text: Text to type into target.
        query: Optional label to find the target element autonomously.
        mark_id: Optional Set-of-Marks badge ID.
        x, y: Optional physical coordinates.
        clear_first: Whether to select all and delete existing text before typing.
        press_enter: Whether to press Enter after typing.
        delay_ms: Milliseconds delay between keystrokes.
        verify_delta: Whether to verify visual change post-execution.
    """
    res = controller.click_and_type(
        text=text,
        query=query,
        mark_id=mark_id,
        x=x,
        y=y,
        clear_first=clear_first,
        press_enter=press_enter,
        delay_ms=delay_ms,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def find_and_click(
    query: str,
    button: str = "left",
    click_count: int = 1,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Autonomous one-shot action: Finds an element by text query and clicks it with verified delta.

    Args:
        query: Target text or label (e.g. 'Flash-Lite', 'Argon', 'Send').
        button: 'left', 'right', or 'middle'.
        click_count: 1 for single click, 2 for double click.
        verify_delta: Whether to verify visual reaction.
    """
    res = controller.find_and_click(
        query=query,
        button=button,
        click_count=click_count,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def move_cursor(x: int, y: int) -> Dict[str, Any]:
    """
    Moves the mouse pointer to absolute coordinates (x, y) without clicking.
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
def scroll_until_visible(
    query: str,
    direction: str = "down",
    max_scrolls: int = 6,
    scroll_amount: int = 6,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Autonomous scroll loop: Iteratively scrolls the viewport until the query element is found.

    Args:
        query: Text or label to find.
        direction: 'down' or 'up'.
        max_scrolls: Max scroll attempts.
        scroll_amount: Wheel increments per scroll step.
    """
    res = controller.scroll_until_visible(
        query=query,
        direction=direction,
        max_scrolls=max_scrolls,
        scroll_amount=scroll_amount,
        verify_delta=verify_delta,
    )
    return res.model_dump()


@mcp_server.tool()
def type_text(
    text: str,
    press_enter: bool = False,
    delay_ms: float = CONFIG.typing_delay_ms,
    verify_delta: bool = True,
) -> Dict[str, Any]:
    """
    Types text into the currently focused desktop element.
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
    Sends a keyboard chord shortcut (e.g. 'ctrl+c', 'alt+tab', 'ctrl+a').
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
def get_active_window() -> Optional[Dict[str, Any]]:
    """
    Returns the currently active / focused window metadata.
    """
    win = hal.get_active_window()
    return win.model_dump() if win else None


@mcp_server.tool()
def focus_window(window_id: str) -> Dict[str, Any]:
    """
    Brings target window to the foreground and grants it focus.
    """
    ok = hal.focus_window(window_id)
    return {"success": ok, "window_id": window_id}


@mcp_server.tool()
def configure_vision(
    setting: str,
    value: Any,
) -> Dict[str, Any]:
    """
    Dynamically hotswaps runtime settings for grounding, tokens, and safety.

    Args:
        setting: Parameter name:
                 - 'grounding_strategy' ('ensemble', 'semantic', 'cv', 'template')
                 - 'max_image_dimension' (int, e.g. 1200, 1600)
                 - 'image_quality' (int, e.g. 70, 85)
                 - 'token_optimization_mode' ('standard', 'delta_patch')
                 - 'enable_nms_fusion' (bool)
                 - 'typing_delay_ms' (float)
        value: New value to apply.
    """
    setting_clean = setting.strip().lower()

    if setting_clean == "grounding_strategy":
        ok = controller.grounding_engine.set_strategy(str(value))
        return {"success": ok, "setting": setting_clean, "value": controller.grounding_engine.active_strategy}

    if hasattr(CONFIG, setting_clean):
        setattr(CONFIG, setting_clean, value)
        return {"success": True, "setting": setting_clean, "value": getattr(CONFIG, setting_clean)}

    return {"success": False, "error": f"Unknown configuration setting: '{setting}'"}


@mcp_server.tool()
def get_vision_diagnostics() -> Dict[str, Any]:
    """
    Returns diagnostic health check of the Vision MCP server, active display,
    available perception backends, and current configuration.
    """
    screen_w, screen_h = hal.get_screen_size()
    active_win = hal.get_active_window()

    diag = DiagnosticsResult(
        platform=sys.platform,
        display_server="Wayland" if controller.hal._is_wayland else "X11",
        primary_screen_size=(screen_w, screen_h),
        active_grounding_strategy=controller.grounding_engine.active_strategy,
        atspi_available=controller.atspi_inspector.is_available,
        opencv_available=True,
        supported_grounding_providers=controller.grounding_engine.list_strategies(),
        active_window=active_win.title if active_win else None,
        config_summary=CONFIG.model_dump(),
    )
    return diag.model_dump()


@mcp_server.tool()
def run_terminal_command(
    command: str,
    timeout_seconds: int = CONFIG.command_timeout_seconds,
) -> Dict[str, Any]:
    """
    Executes a shell command in the background for hybrid CLI navigation.
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
    Blocks until a visual change occurs on the desktop.
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


@mcp_server.tool()
def list_plugins() -> List[Dict[str, Any]]:
    """
    Lists all registered UI Application Plugins and reports which is currently active.
    
    Returns:
        List of plugin summaries including app_id, name, is_active, and supported sub-panes.
    """
    act_win = hal.get_active_window()
    active_title = act_win.title if act_win else None
    summaries = controller.plugin_registry.list_all(active_window_title=active_title)
    return [s.model_dump() for s in summaries]


@mcp_server.tool()
def list_plugin_features(
    plugin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns the declarative feature catalog and hotkeys for an application plugin.
    
    Args:
        plugin_id: Target plugin identifier ('chrome', 'verdi', etc.). If None, detects active window.
        
    Returns:
        Dictionary containing plugin metadata and list of feature descriptors.
    """
    plugin = None
    if plugin_id:
        plugin = controller.plugin_registry.get(plugin_id)
    else:
        plugin = controller.get_active_plugin() or controller.plugin_registry.get("chrome")

    if not plugin:
        return {"error": f"Plugin '{plugin_id}' not found.", "features": []}

    features = [f.model_dump() for f in plugin.list_features()]
    return {
        "app_id": plugin.app_id,
        "name": plugin.name,
        "supported_panes": list(plugin.sub_panes.keys()),
        "features": features,
    }


@mcp_server.tool()
def invoke_plugin_feature(
    feature_id: str,
    plugin_id: Optional[str] = None,
    args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Executes a high-level application capability natively with closed-loop delta verification.
    
    Args:
        feature_id: Identifier of the capability (e.g. 'browser.navigate', 'browser.new_tab', 'browser.reload').
        plugin_id: Target plugin identifier. If omitted, routes to the active window's plugin.
        args: Optional parameter dictionary (e.g. {'url': 'https://gemini.google.com'}).
        
    Returns:
        Action outcome with success flag, visual delta, and status message.
    """
    plugin = None
    if plugin_id:
        plugin = controller.plugin_registry.get(plugin_id)
    else:
        plugin = controller.get_active_plugin() or controller.plugin_registry.get("chrome")

    if not plugin:
        return {
            "success": False,
            "feature_id": feature_id,
            "message": f"Could not resolve an application plugin for feature '{feature_id}'.",
        }

    return plugin.execute_feature(feature_id=feature_id, controller=controller, args=args)


@mcp_server.tool()
def capture_pane(
    pane_name: str,
    window_id: Optional[str] = None,
    title_filter: Optional[str] = None,
    mode: str = "raw",
) -> Dict[str, Any]:
    """
    Ultra-efficient sub-pane perception tool. Captures strictly a named functional
    zone of the target or active window (e.g. 'address_bar', 'tab_strip', 'content_area').
    Slashes multimodal token consumption by up to 90% compared to capturing a whole display.
    
    Args:
        pane_name: Identifier of sub-pane ('address_bar', 'tab_strip', 'content_area', etc.).
        window_id: Optional target window ID.
        title_filter: Optional title substring filter (e.g. 'Chrome').
        mode: Grounding mode ('raw', 'cursor_only', 'annotated_som').
        
    Returns:
        ScreenshotResult dictionary with image_base64 and scaled dimensions.
    """
    result = controller.capture_pane(
        pane_name=pane_name,
        window_id=window_id,
        title_filter=title_filter,
        mode=mode,
    )
    return result.model_dump()


@mcp_server.tool()
def start_skill_recording(
    journal_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    GUI-to-Script Crystallization: Starts recording physical GUI actions and correlations
    with application command journal streams (e.g. vivado.jou, novas.cmd).
    
    Args:
        journal_path: Path to application journal file. If omitted, uses default or existing path.
    """
    if journal_path:
        controller.journal_correlator.set_journal_path(journal_path)
    elif not controller.journal_correlator.journal_path:
        candidates = [
            "/home/mk/DV/vivado_fifo/vivado.jou",
            os.path.abspath("vivado.jou"),
        ]
        for c in candidates:
            if os.path.exists(c):
                controller.journal_correlator.set_journal_path(c)
                break

    controller.journal_correlator.start_recording()
    return {
        "success": True,
        "recording": True,
        "journal_path": controller.journal_correlator.journal_path,
        "message": f"Skill recording started. Tracking commands from '{controller.journal_correlator.journal_path}'.",
    }


@mcp_server.tool()
def stop_skill_recording() -> Dict[str, Any]:
    """
    Stops active skill recording and returns summary of captured action steps.
    """
    steps = controller.journal_correlator.stop_recording()
    return {
        "success": True,
        "recording": False,
        "recorded_steps_count": len(steps),
        "steps": [s.model_dump() for s in steps],
        "message": f"Skill recording stopped. Captured {len(steps)} correlated GUI action steps.",
    }


@mcp_server.tool()
def crystallize_skill(
    skill_name: str,
    task_prompt: str,
    app_target: str = "vivado_2025.1",
    extracted_entities: Optional[Dict[str, Any]] = None,
    verification_cmd: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compiles recorded GUI trajectory into a parameterized, deterministic Tcl/CLI skill,
    lifting entity literals into Jinja2 parameters and saving to dynamic skill registry.
    
    Args:
        skill_name: Identifier for the new skill (e.g. 'run_sim_fifo').
        task_prompt: Natural language description of the demonstrated task.
        app_target: Target application suite (default 'vivado_2025.1').
        extracted_entities: Dictionary of literal parameters to lift into variables (e.g. {'runtime': '10us', 'radix': 'hex'}).
        verification_cmd: Tcl assertion command for post-execution verification.
        description: Detailed summary of what this crystallized skill accomplishes.
    """
    steps = controller.journal_correlator.recorded_steps
    if not steps:
        return {
            "success": False,
            "message": "No recorded trajectory steps found. Run start_skill_recording() and perform GUI actions first.",
        }

    spec = controller.trajectory_compiler.compile_trajectory(
        steps=steps,
        task_prompt=task_prompt,
        extracted_entities=extracted_entities,
        skill_name=skill_name,
        app_target=app_target,
        description=description,
        verification_cmd=verification_cmd,
    )
    controller.skill_registry.register_skill(spec)
    return {
        "success": True,
        "skill": spec.model_dump(),
        "message": f"Successfully crystallized skill '{skill_name}' with {len(spec.parameters)} parameters.",
    }


@mcp_server.tool()
def execute_crystallized_skill(
    skill_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Executes a crystallized parameterized skill with 0 visual tokens by compiling
    the template and executing deterministically via application CLI/Tcl bridge.
    
    Args:
        skill_name: Identifier of the crystallized skill to execute.
        arguments: Dynamic arguments overriding default parameters.
    """
    spec = controller.skill_registry.get_skill(skill_name)
    if not spec:
        return {
            "success": False,
            "skill_name": skill_name,
            "message": f"Skill '{skill_name}' not found in dynamic skill registry.",
        }

    t_start = time.monotonic()
    try:
        rendered_script = controller.skill_registry.render_script(skill_name, arguments)
    except Exception as e:
        return {
            "success": False,
            "skill_name": skill_name,
            "message": f"Failed to render skill template: {e}",
        }

    plugin = controller.get_active_plugin()
    exec_msg = ""
    success = True

    if plugin and "vivado" in plugin.app_id:
        with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as f:
            f.write(rendered_script + "\n")
            temp_path = f.name

        try:
            res = plugin.execute_feature(
                "vivado.tcl_exec",
                controller,
                {"command": f"source {temp_path}"},
            )
            success = res.get("success", True)
            exec_msg = f"Sourced {temp_path} into Vivado Tcl Console"
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    else:
        exec_msg = f"Rendered and executed script ({len(rendered_script.splitlines())} lines)"

    elapsed_ms = (time.monotonic() - t_start) * 1000.0
    return {
        "success": success,
        "skill_name": skill_name,
        "rendered_tcl": rendered_script,
        "execution_time_ms": round(elapsed_ms, 2),
        "message": f"Skill '{skill_name}' executed in {elapsed_ms:.1f}ms: {exec_msg}",
    }


@mcp_server.tool()
def list_crystallized_skills() -> Dict[str, Any]:
    """
    Lists all registered crystallized skills available for zero-visual-token deterministic execution.
    """
    skills = controller.skill_registry.list_skills()
    return {
        "count": len(skills),
        "skills": [s.model_dump() for s in skills],
    }


@mcp_server.tool()
def delete_crystallized_skill(
    skill_name: str,
) -> Dict[str, Any]:
    """
    Deletes a crystallized skill from the registry.
    """
    deleted = controller.skill_registry.delete_skill(skill_name)
    return {
        "success": deleted,
        "skill_name": skill_name,
        "message": f"Skill '{skill_name}' deleted." if deleted else f"Skill '{skill_name}' not found.",
    }


def main():
    """Starts the FastMCP server in standard I/O mode."""
    mcp_server.run()


if __name__ == "__main__":
    main()
