from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pipeline_nodes import (
    PUZZLE_CATEGORY,
    PUZZLE_COMPLETED,
    PUZZLE_CONFIRM,
    PUZZLE_CONFIRM_ENABLED,
    PUZZLE_NAME,
    PUZZLE_REWARD_CLAIMED,
    PUZZLE_TAB,
)

from .backend import MaaBackend


LOGGER = logging.getLogger("maasvwb.solution")
LIST_SWIPE_DURATION_MS = 900
LIST_SWIPE_SETTLE_MS = 1400
LIST_OCR_STABLE_MS = 700
LIST_CLICK_SETTLE_MS = 1200
CATEGORY_SUFFIX_LEFT_OVERLAP = 5
CATEGORY_SUFFIX_TOP_PADDING = 8
CATEGORY_SUFFIX_WIDTH = 35
CATEGORY_SUFFIX_VERTICAL_PADDING = 16


@dataclass(frozen=True)
class ListNavigationNodes:
    name: str = PUZZLE_NAME
    tab: str = PUZZLE_TAB
    category: str = PUZZLE_CATEGORY
    confirm: str = PUZZLE_CONFIRM
    confirm_enabled: str = PUZZLE_CONFIRM_ENABLED
    completed: str = PUZZLE_COMPLETED
    reward_claimed: str = PUZZLE_REWARD_CLAIMED


class PuzzleNavigator:
    """负责教程类列表的滚动、分类选择和条目确认。"""

    def __init__(
        self,
        backend: MaaBackend,
        nodes: ListNavigationNodes | None = None,
    ) -> None:
        self.backend = backend
        self.nodes = nodes or ListNavigationNodes()

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
                    if old is None or new is None:
                        previous = current
                        continue
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
            self.nodes.name, name_pattern, list_top, list_bottom, max_swipes
        )
        if detail is None:
            return None
        if skip_completed and self.is_puzzle_completed(detail):
            return "completed"

        box = detail.box
        if box is None:
            return None
        if not self.backend.tap(box.x + box.w // 2, box.y + box.h // 2):
            return None
        time.sleep(LIST_CLICK_SETTLE_MS / 1000)
        if not self.backend.verify(self.nodes.confirm_enabled):
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
            self.nodes.completed,
            {self.nodes.completed: {"roi": [55, row_top, 105, row_height]}},
        )
        claimed = self.backend.recognize(
            self.nodes.reward_claimed,
            {self.nodes.reward_claimed: {"roi": [390, row_top, 130, row_height]}},
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
                self.nodes.category,
                category["pattern"],
                list_top,
                list_bottom,
                max_swipes,
            )
            if detail is None or detail.box is None:
                LOGGER.error("未识别到盘面解密类别: %s", category["display_name"])
                return False
            box = detail.box
            suffix_pattern = category.get("suffix_pattern")
            if suffix_pattern and not self._category_suffix_matches(
                box, suffix_pattern
            ):
                LOGGER.warning(
                    "类别主体已识别，但右侧编号不匹配: %s（第 %d 次）",
                    category["display_name"],
                    attempt,
                )
                continue
            expanded = self.backend.category_expanded(box)
            if expanded is True:
                LOGGER.info("类别已经展开，无需点击: %s", category["display_name"])
                return True
            if expanded is None and puzzle_pattern:
                puzzle = self.find_in_scroll_list(
                    self.nodes.name,
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
                    self.nodes.name,
                    puzzle_pattern,
                    list_top,
                    list_bottom,
                    max_swipes,
                )
                if puzzle is not None:
                    return True
            elif self.backend.wait_recognition(self.nodes.confirm, 1500, 250):
                return True
        LOGGER.error("点击后仍未找到目标题目: %s", category["display_name"])
        return False

    def _category_suffix_matches(self, box, expected: str) -> bool:
        """用精确小 ROI 绕过 OCR 检测模型对圈号漏框的问题。"""
        roi = [
            box.x + box.w - CATEGORY_SUFFIX_LEFT_OVERLAP,
            box.y - CATEGORY_SUFFIX_TOP_PADDING,
            CATEGORY_SUFFIX_WIDTH,
            box.h + CATEGORY_SUFFIX_VERTICAL_PADDING,
        ]
        detail = self.backend.recognize(
            self.nodes.category,
            {
                self.nodes.category: {
                    "roi": roi,
                    "only_rec": True,
                    "expected": expected,
                    "threshold": 0.1,
                }
            },
        )
        return bool(detail and detail.hit)

    def confirm_categories(
        self,
        categories: list[dict],
        list_top: tuple[int, int],
        list_bottom: tuple[int, int],
        max_swipes: int,
    ) -> bool:
        for category in categories:
            node = self.nodes.tab if category["scope"] == "tab" else self.nodes.category
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
