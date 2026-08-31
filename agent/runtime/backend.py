from __future__ import annotations

import logging
import re
import time

import numpy as np
from maa.context import Context
from maa.pipeline import JWaitFreezes

from pipeline_nodes import CURRENT_ENERGY, CURRENT_HAND_COUNT
from solution_engine.layout import BoardLayout


LOGGER = logging.getLogger("maasvwb.solution")


class MaaBackend:
    """把通用解法动作适配到 MaaFramework Controller。"""

    def __init__(self, context: Context, layout: BoardLayout) -> None:
        self.context = context
        self.controller = context.tasker.controller
        self.layout = layout

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

    def verify(self, pipeline_node: str, frame=None) -> bool:
        detail = self.recognize(pipeline_node, frame=frame)
        return bool(detail and detail.hit)

    def capture_frame(self):
        capture = self.controller.post_screencap()
        capture.wait()
        if not capture.succeeded:
            return None
        return np.array(self.controller.cached_image, copy=True)

    def read_hand_count(self) -> int | None:
        """从盘面左下角牌堆状态栏读取当前手牌数。"""
        detail = self.recognize(CURRENT_HAND_COUNT)
        result = detail.best_result if detail and detail.hit else None
        text = getattr(result, "text", "")
        match = re.search(r"\d+", text)
        if match is None:
            LOGGER.warning("未能读取当前手牌数量: %r", text)
            return None
        count = int(match.group())
        if not 0 <= count <= 9:
            LOGGER.warning("当前手牌数量超出支持范围: %d", count)
            return None
        LOGGER.info("实时手牌数量: %d", count)
        return count

    def read_energy_points(self) -> tuple[int, int] | None:
        """读取玩家侧能量点，返回（当前值，上限）。"""
        detail = self.recognize(CURRENT_ENERGY)
        result = detail.best_result if detail and detail.hit else None
        if result is None and detail:
            results = getattr(detail, "all_results", ())
            result = results[0] if results else None
        text = getattr(result, "text", "")
        parsed = self._parse_energy_text(text)
        if parsed is None:
            LOGGER.warning("未能读取当前能量点: %r", text)
            return None
        current, maximum = parsed
        LOGGER.info("实时能量点: %d/%d（OCR=%r）", current, maximum, text)
        return current, maximum

    @staticmethod
    def _parse_energy_text(text: str) -> tuple[int, int] | None:
        normalized = text.translate(str.maketrans({"I": "1", "l": "1", "|": "/"}))
        match = re.search(r"(\d+)\s*/\s*(\d+)", normalized)
        candidates: list[tuple[int, int]] = []
        if match is not None:
            current_text, maximum_text = match.groups()
            candidates.append((int(current_text), int(maximum_text)))
        digits = re.sub(r"\D", "", normalized)
        for separator in (index for index, value in enumerate(digits) if value == "1"):
            if separator == 0 or separator == len(digits) - 1:
                continue
            candidates.append((int(digits[:separator]), int(digits[separator + 1 :])))
        if len(digits) in {2, 4}:
            middle = len(digits) // 2
            candidates.append((int(digits[:middle]), int(digits[middle:])))
        valid = [pair for pair in candidates if 0 <= pair[0] <= pair[1] <= 10]
        return valid[0] if valid else None

    def read_follower_count(self, side: str) -> int | None:
        """根据随从左下角蓝色攻击力数字，读取当前一侧的随从数量。"""
        regions = {
            "enemy": "enemy_follower_stats",
            "ally": "ally_follower_stats",
        }
        if side not in regions:
            raise ValueError(f"未知场上阵营: {side}")
        frame = self.capture_frame()
        if frame is None or frame.ndim < 3:
            return None

        region_x, y, width, height = self.layout.region(regions[side])
        if region_x + width > frame.shape[1] or y + height > frame.shape[0]:
            LOGGER.error("随从计数区域越界: %s", (region_x, y, width, height))
            return None
        crop = frame[y : y + height, region_x : region_x + width].astype(np.float32)
        blue = crop[:, :, 0]
        green = crop[:, :, 1]
        red = crop[:, :, 2]
        stat_pixels = (
            (blue > 90)
            & (blue > red * 1.15)
            & (blue > green * 1.05)
        )
        histogram = np.count_nonzero(stat_pixels, axis=0).astype(np.float32)
        score = np.convolve(histogram, np.ones(17, dtype=np.float32), mode="same")

        peaks: list[int] = []
        while len(peaks) < 5:
            x = int(np.argmax(score))
            if score[x] < 420:
                break
            peaks.append(x + region_x)
            score[max(0, x - 75) : min(len(score), x + 76)] = 0
        peaks.sort()
        if not peaks:
            LOGGER.warning(
                "未识别到%s场上随从攻击力数字",
                "敌方" if side == "enemy" else "我方",
            )
            return None
        LOGGER.info(
            "实时%s随从数量: %d（攻击力数字 x=%s）",
            "敌方" if side == "enemy" else "我方",
            len(peaks),
            peaks,
        )
        return len(peaks)

    def read_ward_indexes(self, enemy_count: int) -> tuple[int, ...]:
        """按敌方随从序号检测明亮的黄绿色守护盾牌。"""
        if enemy_count <= 0:
            return ()
        frame = self.capture_frame()
        if frame is None or frame.ndim < 3:
            return ()

        wards: list[int] = []
        for index in range(1, enemy_count + 1):
            center_x, center_y = self.layout.indexed_point(
                "enemy_followers", enemy_count, index
            )
            left = max(0, center_x - 78)
            right = min(frame.shape[1], center_x + 79)
            top = max(0, center_y - 105)
            bottom = min(frame.shape[0], center_y + 45)
            crop = frame[top:bottom, left:right].astype(np.float32)
            blue = crop[:, :, 0]
            green = crop[:, :, 1]
            red = crop[:, :, 2]
            shield_pixels = (
                (green > 145)
                & (red > 95)
                & (green > blue * 1.25)
                & (green > red * 1.03)
            )
            count = int(np.count_nonzero(shield_pixels))
            LOGGER.debug("敌方随从 %d 守护特征像素=%d", index, count)
            if count >= 900:
                wards.append(index)
        if wards:
            LOGGER.info("检测到敌方守护随从序号: %s", wards)
        return tuple(wards)

    def hand_is_expanded(
        self, point: tuple[int, int]
    ) -> bool | None:
        """根据可出牌卡牌的青绿色外框判断手牌是否已在中央展开。"""
        frame = self.capture_frame()
        if frame is None or frame.ndim < 3:
            return None
        center_x, center_y = point
        x = center_x - 55
        y = center_y - 105
        width = 110
        height = 125
        if x < 0 or y < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
            return None
        crop = frame[y : y + height, x : x + width]
        blue = crop[:, :, 0].astype(np.float32)
        green = crop[:, :, 1].astype(np.float32)
        red = crop[:, :, 2].astype(np.float32)
        highlighted = (
            (green > 140)
            & (blue > 100)
            & (green > red * 1.15)
            & (blue > red * 0.9)
        )
        pixels = int(np.count_nonzero(highlighted))
        expanded = pixels >= 100
        LOGGER.info(
            "实时手牌展开状态: %s（高亮像素=%d）",
            "已展开" if expanded else "已收拢",
            pixels,
        )
        return expanded

    def tap_recognition(
        self,
        pipeline_node: str,
        timeout_ms: int,
        interval_ms: int = 250,
    ) -> bool:
        """等待识别框出现并点击其中心。"""
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self.is_stopping():
                return False
            frame = self.capture_frame()
            detail = self.recognize(pipeline_node, frame=frame)
            if detail and detail.hit and detail.box is not None:
                box = detail.box
                return self.tap(box.x + box.w // 2, box.y + box.h // 2)
            time.sleep(interval_ms / 1000)
        return False

    def category_expanded(self, category_box) -> bool | None:
        """根据类别行右侧的上/下箭头判断手风琴是否展开。"""
        frame = self.capture_frame()
        if frame is None or frame.ndim < 3:
            return None

        arrow_center_x, arrow_y_offset = self.layout.fixed_point(
            "puzzle_category_arrow_probe"
        )
        arrow_center_y = category_box.y + category_box.h // 2 + arrow_y_offset
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

    def recognize(
        self,
        pipeline_node: str,
        override: dict | None = None,
        *,
        frame=None,
    ):
        image = self.capture_frame() if frame is None else frame
        if image is None:
            return None
        return self.context.run_recognition(
            pipeline_node,
            image,
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
            if self.is_stopping():
                return False
            frame = self.capture_frame()
            detail = self.recognize(pipeline_node, frame=frame)
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
            if self.is_stopping():
                return False
            frame = self.capture_frame()
            detail = self.recognize(pipeline_node, frame=frame)
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
            if self.is_stopping():
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

    def is_stopping(self) -> bool:
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
            if self.is_stopping():
                return False
            frame = self.capture_frame()
            detail = self.recognize(pipeline_node, frame=frame)
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
