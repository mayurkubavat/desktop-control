"""Feedback loop controller for perception-action-verification cycles."""

import time
from typing import Optional, Dict, Tuple, List, Callable
from PIL import Image

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.perception.capture import CapturePipeline
from vision_mcp.perception.som import SetOfMarksGenerator
from vision_mcp.perception.grounding.engine import GroundingEngine
from vision_mcp.perception.token_optimizer import TokenOptimizer
from vision_mcp.perception.window_clipper import WindowClipper
from vision_mcp.agent_loop.cache import ActionCache
from vision_mcp.agent_loop.obstruction import ObstructionInterceptor
from vision_mcp.types import (
    ScreenshotResult,
    UIElement,
    ActionVerificationResult,
    FindElementResult,
    BoundingBox,
)
from vision_mcp.config import CONFIG


class FeedbackLoopController:
    """
    Coordinates perception, action execution, and post-action verification.
    Integrates the pluggable GroundingEngine, TokenOptimizer, WindowClipper,
    Self-Healing ActionCache, ObstructionInterceptor, and Set-of-Marks mapping.
    """

    def __init__(self, hal: IDesktopHAL) -> None:
        self.hal = hal
        self.pipeline = CapturePipeline(hal)
        self.som_generator = SetOfMarksGenerator()
        self.grounding_engine = GroundingEngine()
        self.token_optimizer = TokenOptimizer()
        self.window_clipper = WindowClipper(hal)
        self.action_cache = ActionCache()

        # Backward compatibility aliases
        self.atspi_inspector = self.grounding_engine._semantic.inspector
        self.cv_detector = self.grounding_engine._cv.detector

        self.obstruction_interceptor = ObstructionInterceptor(hal, self.atspi_inspector)
        self.active_marks: Dict[int, UIElement] = {}
        self.last_screenshot_meta: Optional[Tuple[int, int, float]] = None
        self.last_clean_frame: Optional[Image.Image] = None

    def _get_active_app_key(self) -> str:
        """Derives a normalized application key from the currently focused window."""
        try:
            act_win = self.hal.get_active_window()
            if act_win and act_win.title:
                parts = act_win.title.split(" - ")
                return parts[-1].strip().lower()
        except Exception:
            pass
        return "desktop"

    def capture_state(
        self,
        mode: str = "annotated_som",
        app_filter: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        window_id: Optional[str] = None,
        clip_to_active_window: bool = False,
        strategy_override: Optional[str] = None,
        compress_quality: int = CONFIG.image_quality,
    ) -> ScreenshotResult:
        """
        Captures current desktop state with Set-of-Marks, pluggable grounding,
        and optional per-window clipping.

        Args:
            mode: 'annotated_som' (uses active grounding strategy or ensemble),
                  'annotated_cv' (forces pure computer vision),
                  'raw' (clean screenshot without annotations),
                  'cursor_only' (clean screenshot with virtual pointer).
            app_filter: Optional filter for AT-SPI inspection.
            region: Optional (x, y, w, h) sub-region.
            window_id: Optional window identifier to clip perception strictly to window bounds.
            clip_to_active_window: If True, crops capture frame to the focused window bounds.
            strategy_override: Optional override for grounding provider ('semantic', 'cv', 'template', 'ensemble').
            compress_quality: JPEG compression factor.

        Returns:
            ScreenshotResult model containing base64 payload and marked element registry.
        """
        target_win = None
        if window_id or clip_to_active_window or CONFIG.clip_to_active_window:
            target_win = self.window_clipper.resolve_target_window(window_id=window_id)
            if target_win and not region:
                screen_size = self.hal.get_screen_size()
                region = self.window_clipper.clip_region_to_screen(target_win.bbox, screen_size)

        draw_cursor = mode in ("annotated_som", "annotated_cv", "cursor_only")
        img, scale_factor, (orig_w, orig_h), cursor_pos = self.pipeline.capture(
            region=region,
            draw_cursor=draw_cursor,
            scale_down=True,
        )

        marks_list: List[UIElement] = []

        if mode in ("annotated_som", "annotated_cv"):
            strat = "cv" if mode == "annotated_cv" else strategy_override
            raw_elements = self.grounding_engine.detect_elements(
                image=img,
                scale_factor=scale_factor,
                strategy_override=strat,
                app_filter=app_filter,
                region=region,
            )

            # Filter marks if clipped to window
            if target_win:
                raw_elements = self.window_clipper.filter_and_offset_elements(raw_elements, target_win.bbox)

            if raw_elements:
                img, self.active_marks = self.som_generator.annotate(
                    image=img,
                    elements=raw_elements,
                    scale_factor=scale_factor,
                )
                marks_list = list(self.active_marks.values())
            else:
                self.active_marks = {}
        else:
            self.active_marks = {}

        self.last_clean_frame = img
        self.last_screenshot_meta = (orig_w, orig_h, scale_factor)
        b64 = self.pipeline.encode_image(img, format="JPEG", quality=compress_quality)

        return ScreenshotResult(
            image_base64=b64,
            mime_type="image/jpeg",
            width=img.size[0],
            height=img.size[1],
            original_width=orig_w,
            original_height=orig_h,
            scale_factor=scale_factor,
            marks=marks_list,
            cursor_position=cursor_pos,
        )

    def find_element(
        self,
        query: str,
        role: Optional[str] = None,
        fuzzy: bool = True,
        strategy_override: Optional[str] = None,
    ) -> FindElementResult:
        """
        Autonomous element search by text label, accessible name, or role.
        Enables one-shot coordinate resolution with zero screenshot token overhead.
        """
        clean_img, scale_factor, _, _ = self.pipeline.capture(draw_cursor=False, scale_down=True)
        candidates = self.grounding_engine.find_element(
            query=query,
            image=clean_img,
            scale_factor=scale_factor,
            fuzzy=fuzzy,
            strategy_override=strategy_override,
        )

        if role:
            r_low = role.lower().strip()
            candidates = [c for c in candidates if r_low in (c.role or "").lower()]

        if not candidates:
            return FindElementResult(
                found=False,
                query=query,
                element=None,
                center_coords=None,
                confidence=0.0,
                candidates_count=0,
            )

        best = candidates[0]
        return FindElementResult(
            found=True,
            query=query,
            element=best,
            center_coords=best.bbox.center,
            confidence=1.0,
            candidates_count=len(candidates),
        )

    def execute_with_verification(
        self,
        action_name: str,
        action_func: Callable[[], None],
        settle_time_sec: float = 0.25,
        verify_delta: bool = True,
    ) -> ActionVerificationResult:
        """
        Executes action with automated before-and-after visual delta verification.
        """
        before_img: Optional[Image.Image] = None
        if verify_delta:
            try:
                before_img, _, _, _ = self.pipeline.capture(draw_cursor=False, scale_down=True)
            except Exception:
                before_img = None

        try:
            action_func()
        except Exception as e:
            return ActionVerificationResult(
                success=False,
                action_type=action_name,
                delta_detected=False,
                change_ratio=0.0,
                message=f"Action failed with error: {str(e)}",
            )

        if not verify_delta or before_img is None:
            return ActionVerificationResult(
                success=True,
                action_type=action_name,
                delta_detected=False,
                change_ratio=0.0,
                message="Action executed (verification skipped)",
            )

        time.sleep(settle_time_sec)

        try:
            after_img, _, _, _ = self.pipeline.capture(draw_cursor=False, scale_down=True)
            delta = self.pipeline.compute_image_delta(before_img, after_img)
            has_changed = delta > 0.001

            return ActionVerificationResult(
                success=True,
                action_type=action_name,
                delta_detected=has_changed,
                change_ratio=round(delta, 4),
                message=f"Action verified. Visual change delta: {delta:.2%}",
            )
        except Exception as e:
            return ActionVerificationResult(
                success=True,
                action_type=action_name,
                delta_detected=False,
                change_ratio=0.0,
                message=f"Action executed but post-verification failed: {str(e)}",
            )

    def resolve_target_coordinates(
        self,
        query: Optional[str] = None,
        mark_id: Optional[int] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        use_cache: bool = True,
    ) -> Tuple[int, int]:
        """
        Resolves target coordinates from cache, query text, mark ID, or explicit (x, y).
        """
        if query:
            app_key = self._get_active_app_key()
            if use_cache and CONFIG.enable_action_cache:
                cached = self.action_cache.get(app_key, query)
                if cached:
                    return cached.center_coords

            res = self.find_element(query=query)
            if res.found and res.center_coords and res.element:
                if CONFIG.enable_action_cache:
                    self.action_cache.record(
                        app_key=app_key,
                        query=query,
                        bbox=res.element.bbox,
                        center_coords=res.center_coords,
                        role=res.element.role,
                    )
                return res.center_coords
            raise ValueError(f"Could not find element matching query '{query}'.")

        if mark_id is not None:
            if mark_id not in self.active_marks:
                raise ValueError(
                    f"Mark ID #{mark_id} not found in active screen marks. "
                    f"Available marks: {list(self.active_marks.keys())}. "
                    "Take a new screenshot to refresh marks."
                )
            elem = self.active_marks[mark_id]
            return elem.bbox.center

        if x is not None and y is not None:
            return int(x), int(y)

        raise ValueError("Must provide either 'query', 'mark_id', or both 'x' and 'y' coordinates.")

    def find_and_click(
        self,
        query: str,
        button: str = "left",
        click_count: int = 1,
        verify_delta: bool = True,
    ) -> ActionVerificationResult:
        """
        Autonomous one-shot action with Self-Healing Action Cache & Obstruction Defense.
        """
        app_key = self._get_active_app_key()
        cached = self.action_cache.get(app_key, query) if CONFIG.enable_action_cache else None

        # 1. Attempt cached locator playback
        if cached:
            target_x, target_y = cached.center_coords

            def _do_cached():
                self.hal.mouse_click(target_x, target_y, button=button, click_count=click_count)

            res = self.execute_with_verification(
                action_name=f"find_and_click[cached]('{query}', {button}) at ({target_x}, {target_y})",
                action_func=_do_cached,
                verify_delta=verify_delta,
            )

            if res.success and (not verify_delta or res.delta_detected):
                self.action_cache.record_hit(app_key, query)
                return res

            # Cache miss / UI layout changed -> invalidate and self-heal
            self.action_cache.invalidate(app_key, query)

        # 2. Defensive obstruction check if enabled
        if CONFIG.auto_dismiss_obstructions:
            self.obstruction_interceptor.dismiss_if_present()

        # 3. Grounding resolution (self-healing path)
        elem_res = self.find_element(query=query)
        if not elem_res.found or not elem_res.center_coords or not elem_res.element:
            return ActionVerificationResult(
                success=False,
                action_type=f"find_and_click('{query}')",
                delta_detected=False,
                change_ratio=0.0,
                message=f"Element matching '{query}' could not be located on screen.",
            )

        target_x, target_y = elem_res.center_coords

        def _do_fresh_click():
            self.hal.mouse_click(target_x, target_y, button=button, click_count=click_count)

        res = self.execute_with_verification(
            action_name=f"find_and_click[self-healed]('{query}', {button}) at ({target_x}, {target_y})",
            action_func=_do_fresh_click,
            verify_delta=verify_delta,
        )

        # 4. Save newly verified coordinates into cache
        if res.success and (not verify_delta or res.delta_detected) and CONFIG.enable_action_cache:
            self.action_cache.record(
                app_key=app_key,
                query=query,
                bbox=elem_res.element.bbox,
                center_coords=(target_x, target_y),
                role=elem_res.element.role,
            )

        return res

    def click_and_type(
        self,
        text: str,
        query: Optional[str] = None,
        mark_id: Optional[int] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        clear_first: bool = False,
        press_enter: bool = False,
        delay_ms: float = CONFIG.typing_delay_ms,
        verify_delta: bool = True,
    ) -> ActionVerificationResult:
        """
        Compound action with Self-Healing Action Cache: Focuses target, optionally clears,
        types text, and optionally presses Enter.
        """
        app_key = self._get_active_app_key()

        # Check defensive obstruction if query is given
        if query and CONFIG.auto_dismiss_obstructions:
            self.obstruction_interceptor.dismiss_if_present()

        target_x, target_y = self.resolve_target_coordinates(query=query, mark_id=mark_id, x=x, y=y)

        def _do_compound():
            self.hal.mouse_click(target_x, target_y, button="left", click_count=1)
            time.sleep(0.08)

            if clear_first:
                self.hal.keyboard_hotkey(["ctrl", "a"])
                time.sleep(0.03)
                self.hal.keyboard_press_key("backspace")
                time.sleep(0.03)

            self.hal.keyboard_type(text, delay_ms=delay_ms)

            if press_enter:
                time.sleep(0.05)
                self.hal.keyboard_press_key("enter")

        res = self.execute_with_verification(
            action_name=f"click_and_type(len={len(text)}, enter={press_enter}) at ({target_x}, {target_y})",
            action_func=_do_compound,
            verify_delta=verify_delta,
        )

        # Self-healing retry if query was used and delta was zero
        if query and verify_delta and not res.delta_detected and CONFIG.enable_action_cache:
            self.action_cache.invalidate(app_key, query)
            # Re-resolve without cache
            elem_res = self.find_element(query=query)
            if elem_res.found and elem_res.center_coords and elem_res.element:
                target_x, target_y = elem_res.center_coords
                res = self.execute_with_verification(
                    action_name=f"click_and_type[self-healed](len={len(text)}) at ({target_x}, {target_y})",
                    action_func=_do_compound,
                    verify_delta=verify_delta,
                )
                if res.delta_detected:
                    self.action_cache.record(
                        app_key=app_key,
                        query=query,
                        bbox=elem_res.element.bbox,
                        center_coords=(target_x, target_y),
                        role=elem_res.element.role,
                    )

        return res

    def scroll_until_visible(
        self,
        query: str,
        direction: str = "down",
        max_scrolls: int = 6,
        scroll_amount: int = 6,
        verify_delta: bool = True,
    ) -> FindElementResult:
        """
        Iteratively scrolls the viewport until the query element is discovered.
        """
        for scroll_idx in range(max_scrolls):
            res = self.find_element(query=query)
            if res.found:
                return res

            dy = -scroll_amount if direction == "down" else scroll_amount
            self.hal.mouse_scroll(dx=0, dy=dy)
            time.sleep(0.35)

        return self.find_element(query=query)
