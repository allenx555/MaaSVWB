from __future__ import annotations

import logging
import time

from .backend import MaaBackend


LOGGER = logging.getLogger("maasvwb.solution")
LIST_SWIPE_DURATION_MS = 900
LIST_SWIPE_SETTLE_MS = 1400
LIST_OCR_STABLE_MS = 700
LIST_CLICK_SETTLE_MS = 1200


class PuzzleNavigator:
    """负责盘面解密列表的滚动、分类选择和题目确认。"""

    def __init__(self, backend: MaaBackend) -> None:
        self.backend = backend

    def find_in_scroll_list(
        self,
        pipeline_node: str,
        expected: str,
        list_top: tuple[int, int],
        list_bottom: tuple[int, int],
        max_swipes: int,
    ):
        """先让列表向下移动，再反向搜索，并等待 OCR 坐标稳定。"""
        override = {pipeline_node: {"expected": expected}}

        def find_visible():
            detail = self.backend.recognize(pipeline_node, override)
            if detail and detail.hit and detail.box is not None:
                return detail
            return None

        def wait_until_stable(detail):
            previous = detail
            for _ in range(4):
                time.sleep(LIST_OCR_STABLE_MS / 1000)
                current = find_visible()
                if current is None:
                    previous = None
                    continue
                if previous is not None:
                    old = previous.box
                    new = current.box
                    old_center = (old.x + old.w // 2, old.y + old.h // 2)
                    new_center = (new.x + new.w // 2, new.y + new.h // 2)
                    if (
                        abs(old_center[0] - new_center[0]) <= 8
                        and abs(old_center[1] - new_center[1]) <= 8
                    ):
                        return current
                previous = current
            return None

        detail = find_visible()
        for start, end in ((list_bottom, list_top), (list_top, list_bottom)):
            if detail is not None:
                break
            for _ in range(max_swipes):
                if not self.backend.swipe(*start, *end, LIST_SWIPE_DURATION_MS):
                    return None
                time.sleep(LIST_SWIPE_SETTLE_MS / 1000)
                detail = find_visible()
                if detail is not None:
                    break
        return wait_until_stable(detail) if detail is not None else None

    def select_puzzle(
        self,
        name_pattern: str,
        confirm_x: int,
        confirm_y: int,
        list_top: tuple[int, int],
        list_bottom: tuple[int, int],
        max_swipes: int,
        skip_completed: bool = False,
    ) -> str | None:
        detail = self.find_in_scroll_list(
            "识别_盘面解密名称", name_pattern, list_top, list_bottom, max_swipes
        )
        if detail is None:
            return None
        if skip_completed and self.is_puzzle_completed(detail):
            return "completed"

        box = detail.box
        if not self.backend.tap(box.x + box.w // 2, box.y + box.h // 2):
            return None
        time.sleep(LIST_CLICK_SETTLE_MS / 1000)
        if not self.backend.verify("识别_盘面解密决定可用"):
            LOGGER.error("点击题名后，决定按钮没有进入亮蓝可用状态")
            return None
        return "selected" if self.backend.tap(confirm_x, confirm_y) else None

    def is_puzzle_completed(self, name_detail) -> bool:
        """确认题名同一行同时出现“完成”和“已领取”。"""
        if name_detail is None or name_detail.box is None:
            return False
        box = name_detail.box
        row_top = max(190, box.y - 45)
        row_height = max(75, min(100, box.h + 65))
        complete = self.backend.recognize(
            "识别_盘面解密完成标记",
            {"识别_盘面解密完成标记": {"roi": [55, row_top, 105, row_height]}},
        )
        claimed = self.backend.recognize(
            "识别_盘面解密已领取",
            {"识别_盘面解密已领取": {"roi": [390, row_top, 130, row_height]}},
        )
        completed = bool(complete and complete.hit and claimed and claimed.hit)
        LOGGER.info(
            "检查解密完成状态: 完成=%s, 已领取=%s, row_y=%d",
            bool(complete and complete.hit),
            bool(claimed and claimed.hit),
            row_top,
        )
        return completed

    def activate_category(
        self,
        category: dict,
        list_top: tuple[int, int],
        list_bottom: tuple[int, int],
        max_swipes: int,
        puzzle_pattern: str | None = None,
        max_clicks: int = 4,
    ) -> bool:
        for attempt in range(1, max_clicks + 1):
            detail = self.find_in_scroll_list(
                "识别_盘面解密类别",
                category["pattern"],
                list_top,
                list_bottom,
                max_swipes,
            )
            if detail is None or detail.box is None:
                LOGGER.error("未识别到盘面解密类别: %s", category["display_name"])
                return False
            box = detail.box
            expanded = self.backend.category_expanded(box)
            if expanded is True:
                LOGGER.info("类别已经展开，无需点击: %s", category["display_name"])
                return True
            if expanded is None and puzzle_pattern:
                puzzle = self.find_in_scroll_list(
                    "识别_盘面解密名称",
                    puzzle_pattern,
                    list_top,
                    list_bottom,
                    max_swipes,
                )
                if puzzle is not None:
                    LOGGER.info(
                        "类别箭头无法判断，但目标题目已显示: %s",
                        category["display_name"],
                    )
                    return True
            if not self.backend.tap(box.x + box.w // 2, box.y + box.h // 2):
                return False
            LOGGER.info("点击盘面解密类别: %s（第 %d 次）", category["display_name"], attempt)
            time.sleep(LIST_CLICK_SETTLE_MS / 1000)
            if puzzle_pattern:
                puzzle = self.find_in_scroll_list(
                    "识别_盘面解密名称",
                    puzzle_pattern,
                    list_top,
                    list_bottom,
                    max_swipes,
                )
                if puzzle is not None:
                    return True
            elif self.backend.wait_recognition("识别_盘面解密决定", 1500, 250):
                return True
        LOGGER.error("点击后仍未找到目标题目: %s", category["display_name"])
        return False

    def confirm_categories(
        self,
        categories: list[dict],
        list_top: tuple[int, int],
        list_bottom: tuple[int, int],
        max_swipes: int,
    ) -> bool:
        for category in categories:
            node = "识别_盘面解密标签" if category["scope"] == "tab" else "识别_盘面解密类别"
            if category["scope"] == "list":
                detail = self.find_in_scroll_list(
                    node, category["pattern"], list_top, list_bottom, max_swipes
                )
            else:
                detail = self.backend.recognize(
                    node, {node: {"expected": category["pattern"]}}
                )
            if not detail or not detail.hit or detail.box is None:
                LOGGER.error("未识别到盘面解密类别: %s", category["display_name"])
                return False
            box = detail.box
            if not self.backend.tap(box.x + box.w // 2, box.y + box.h // 2):
                return False
            time.sleep(900 / 1000)
        return True
