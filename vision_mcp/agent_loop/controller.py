"""Feedback loop controller for perception-action-verification cycles."""

import time
from typing import Optional, Dict, Tuple, List, Callable
from PIL import Image

from vision_mcp.hal.base import IDesktopHAL
from vision_mcp.perception.capture import CapturePipeline
from vision_mcp.perception.som import SetOfMarksGenerator
from vision_mcp.perception.atspi import ATSPIInspector
from vision_mcp.perception.cv_detector import CVDetector
from vision_mcp.types import (
    ScreenshotResult,
    UIElement,
    ActionVerificationResult,
    BoundingBox,
)
from vision_mcp.config import CONFIG


class FeedbackLoopController:
    """
    Coordinates perception, action execution, and post-action verification.
    Maintains active Set-of-Marks mapping so agents can interact via numeric mark IDs.
    """

    def __init__(self, hal: IDesktopHAL) -> None:
        self.hal = hal
        self.pipeline = CapturePipeline(hal)
        self.som_generator = SetOfMarksGenerator()
        self.atspi_inspector = ATSPIInspector()
        self.cv_detector = CVDetector()
        self.active_marks: Dict[int, UIElement] = {}
        self.last_screenshot_meta: Optional[Tuple[int, int, float]] = None

    def capture_state(
        self,
        mode: str = "annotated_som",
        app_filter: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        compress_quality: int = CONFIG.image_quality,
    ) -> ScreenshotResult:
        """
        Captures current desktop state with optional Set-of-Marks annotations.

        Args:
            mode: 'annotated_som' (hybrid AT-SPI with CV fallback),
                  'annotated_cv' (force pure computer vision detection),
                  'raw' (unmodified screenshot),
                  or 'cursor_only' (screenshot with virtual pointer).
            app_filter: Filter for AT-SPI application inspection.
            region: Optional (x, y, w, h) sub-region.
            compress_quality: JPEG compression factor.

        Returns:
            ScreenshotResult model containing base64 payload and marked element registry.
        """
        draw_cursor = mode in ("annotated_som", "annotated_cv", "cursor_only")
        img, scale_factor, (orig_w, orig_h), cursor_pos = self.pipeline.capture(
            region=region,
            draw_cursor=draw_cursor,
            scale_down=True,
        )

        marks_list: List[UIElement] = []

        if mode in ("annotated_som", "annotated_cv"):
            raw_elements: List[UIElement] = []

            # Try AT-SPI first if not forcing pure CV
            if mode != "annotated_cv":
                raw_elements = self.atspi_inspector.inspect_desktop(app_name_filter=app_filter)

            # Fallback to Computer Vision edge & contour detection if AT-SPI returns no elements
            if not raw_elements:
                raw_elements = self.cv_detector.detect(img, scale_factor=scale_factor)

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

    def execute_with_verification(
        self,
        action_name: str,
        action_func: Callable[[], None],
        settle_time_sec: float = 0.25,
        verify_delta: bool = True,
    ) -> ActionVerificationResult:
        """
        Executes action with automated before-and-after visual delta verification.

        Args:
            action_name: Descriptive name (e.g., 'click', 'type').
            action_func: Callable that executes the physical HAL interaction.
            settle_time_sec: Time to wait for UI animation or transition after action.
            verify_delta: If True, compares screenshots before and after to verify visual reaction.

        Returns:
            ActionVerificationResult documenting execution success and visual change.
        """
        before_img: Optional[Image.Image] = None
        if verify_delta:
            try:
                before_img, _, _, _ = self.pipeline.capture(draw_cursor=False, scale_down=True)
            except Exception:
                before_img = None

        # Execute physical interaction
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

        # Allow UI animation / repaint to settle
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
        mark_id: Optional[int] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
    ) -> Tuple[int, int]:
        """
        Resolves target coordinates from either a Set-of-Marks ID or physical coordinates.
        """
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

        raise ValueError("Must provide either 'mark_id' or both 'x' and 'y' coordinates.")
