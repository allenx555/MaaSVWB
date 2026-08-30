from __future__ import annotations

import logging
import time

import numpy as np
from maa.context import Context
from maa.pipeline import JWaitFreezes


LOGGER = logging.getLogger("maasvwb.solution")


class MaaBackend:
    """把通用解法动作适配到 MaaFramework Controller。"""

    def __init__(self, context: Context) -> None:
        self.context = context
        self.controller = context.tasker.controller

    @staticmethod
    def _wait_success(job) -> bool:
        job.wait()
        return bool(job.succeeded)

    def tap(self, x: int, y: int) -> bool:
        return self._wait_success(self.controller.post_click(x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> bool:
        return self._wait_success(
            self.controller.post_swipe(x1, y1, x2, y2, duration_ms)
        )

    def key(self, keycode: int) -> bool:
        return self._wait_success(self.controller.post_click_key(keycode))

    def verify(self, pipeline_node: str) -> bool:
        detail = self.recognize(pipeline_node)
        return bool(detail and detail.hit)

    def capture_frame(self):
        capture = self.controller.post_screencap()
        capture.wait()
        if not capture.succeeded:
            return None
        return np.array(self.controller.cached_image, copy=True)

    def category_expanded(self, category_box) -> bool | None:
        """根据类别行右侧的上/下箭头判断手风琴是否展开。"""
        frame = self.capture_frame()
        if frame is None or frame.ndim < 3:
            return None

        arrow_center_x = 500
        arrow_center_y = category_box.y + category_box.h // 2 + 14
        left = arrow_center_x - 20
        top = arrow_center_y - 21
        right = arrow_center_x + 20
        bottom = arrow_center_y + 21
        if left < 0 or top < 0 or right > frame.shape[1] or bottom > frame.shape[0]:
            return None

        crop = frame[top:bottom, left:right].astype(np.float32)
        bright = np.mean(crop, axis=2) > 170
        ys, xs = np.nonzero(bright)
        if len(xs) < 20:
            LOGGER.warning("类别箭头亮色像素不足: %d", len(xs))
            return None

        horizontal_spread = np.abs(xs - (bright.shape[1] - 1) / 2)
        direction_score = float(
            np.mean((ys - np.mean(ys)) * (horizontal_spread - np.mean(horizontal_spread)))
        )
        expanded = direction_score > 0
        LOGGER.info(
            "类别箭头方向: %s，score=%.3f，box=(%d,%d,%d,%d)",
            "展开" if expanded else "折叠",
            direction_score,
            category_box.x,
            category_box.y,
            category_box.w,
            category_box.h,
        )
        return expanded

    def recognize(self, pipeline_node: str, override: dict | None = None):
        capture = self.controller.post_screencap()
        capture.wait()
        if not capture.succeeded:
            return None
        return self.context.run_recognition(
            pipeline_node,
            self.controller.cached_image,
            override or {},
        )

    def wait_recognition(
        self,
        pipeline_node: str,
        timeout_ms: int,
        interval_ms: int = 500,
    ) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._stopping():
                return False
            detail = self.recognize(pipeline_node)
            if detail and detail.hit:
                return True
            time.sleep(interval_ms / 1000)
        return False

    def wait_recognition_gone(
        self,
        pipeline_node: str,
        timeout_ms: int,
        interval_ms: int = 500,
    ) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._stopping():
                return False
            detail = self.recognize(pipeline_node)
            if not detail or not detail.hit:
                return True
            time.sleep(interval_ms / 1000)
        return False

    def wait_changed(
        self,
        reference,
        roi: tuple[int, int, int, int],
        timeout_ms: int,
        threshold: float,
        settle_ms: int,
    ) -> bool:
        x, y, width, height = roi
        if reference is None or reference.ndim < 2:
            return False
        if x < 0 or y < 0 or x + width > reference.shape[1] or y + height > reference.shape[0]:
            LOGGER.error("状态校验区域越界: %s, image=%sx%s", roi, reference.shape[1], reference.shape[0])
            return False

        freeze_timeout = max(settle_ms + 500, min(timeout_ms, 3_000))
        self.context.wait_freezes(
            wait_freezes_param=JWaitFreezes(
                time=max(settle_ms, 1),
                target=roi,
                rate_limit=100,
                timeout=freeze_timeout,
            )
        )

        deadline = time.monotonic() + timeout_ms / 1000
        reference_crop = reference[y : y + height, x : x + width].astype(np.float32)
        while time.monotonic() < deadline:
            if self._stopping():
                return False
            current = self.capture_frame()
            if current is None:
                time.sleep(0.1)
                continue
            if current.shape[:2] != reference.shape[:2]:
                LOGGER.error("动作前后截图尺寸不一致: %s -> %s", reference.shape, current.shape)
                return False
            current_crop = current[y : y + height, x : x + width].astype(np.float32)
            score = float(np.mean(np.abs(current_crop - reference_crop)))
            LOGGER.debug("盘面变化分数 %.3f，阈值 %.3f，区域 %s", score, threshold, roi)
            if score >= threshold:
                return True
            time.sleep(0.15)
        return False

    def _stopping(self) -> bool:
        try:
            return bool(self.context.tasker.stopping)
        except (AttributeError, RuntimeError):
            return False

    def skip_dialogue(
        self,
        pipeline_node: str,
        click_x: int,
        click_y: int,
        max_clicks: int,
        interval_ms: int,
        stable_hits: int,
        ready_grace_ms: int = 0,
    ) -> bool:
        """在安全点推进遮罩，直到连续识别到可操作状态。"""
        hits = 0
        clicks = 0
        ready_since: float | None = None
        while True:
            if self._stopping():
                return False
            detail = self.recognize(pipeline_node)
            if detail and detail.hit:
                if ready_since is None:
                    ready_since = time.monotonic()
                ready_elapsed_ms = (time.monotonic() - ready_since) * 1000
                if ready_elapsed_ms < ready_grace_ms:
                    hits = 0
                    time.sleep(min(interval_ms, 200) / 1000)
                    continue
                hits += 1
                LOGGER.info("检测到可操作状态：%d/%d", hits, stable_hits)
                if hits >= stable_hits:
                    LOGGER.info("教程提示已结束，共点击 %d 次", clicks)
                    return True
                time.sleep(min(interval_ms, 200) / 1000)
                continue

            hits = 0
            ready_since = None
            if clicks >= max_clicks:
                LOGGER.error("达到最大点击次数仍未检测到主战者框: %d", max_clicks)
                return False
            if not self.tap(click_x, click_y):
                return False
            clicks += 1
            LOGGER.info("推进教程提示：第 %d 次点击", clicks)
            time.sleep(interval_ms / 1000)
