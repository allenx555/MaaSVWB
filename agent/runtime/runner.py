from __future__ import annotations

import logging
import os
import sys
import time
from functools import lru_cache
from pathlib import Path

from maa.context import Context

from pipeline_nodes import (
    PUZZLE_LIST,
    PUZZLE_REWARD,
    TUTORIAL_CONFIRM,
    TUTORIAL_CONFIRM_ENABLED,
    TUTORIAL_LEADER_OPERABLE,
    TUTORIAL_LIST,
    TUTORIAL_NAME,
    TUTORIAL_TAB,
)
from solution_engine.executor import SolutionExecutor
from solution_engine.layout import BoardLayout
from solution_engine.models import SolutionError
from solution_engine.repository import SolutionRepository

from .backend import MaaBackend
from .events import emit_event
from .puzzle_navigator import ListNavigationNodes, PuzzleNavigator


LOGGER = logging.getLogger("maasvwb.solution")


def resolve_project_root() -> Path:
    configured = os.environ.get("MAASVWB_ROOT")
    if configured:
        return Path(configured).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2]


def find_resource_root(project_root: Path | None = None) -> Path:
    root = project_root or resolve_project_root()
    candidates = (root / "assets" / "resource", root / "resource")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise RuntimeError("找不到 MaaSVWB resource 目录")


def wait_for_puzzle_list(
    backend: MaaBackend,
    reward_continue: tuple[int, int],
    timeout_ms: int = 60_000,
    interval_ms: int = 500,
) -> bool:
    """等待返回盘面解密列表，并处理首次通关的奖励领取页。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if backend.is_stopping():
            return False
        frame = backend.capture_frame()
        if frame is None:
            time.sleep(interval_ms / 1000)
            continue
        if backend.verify(PUZZLE_LIST, frame):
            return True
        if backend.verify(PUZZLE_REWARD, frame):
            LOGGER.info("[完成] 检测到首次通关奖励，点击继续")
            if not backend.tap(*reward_continue):
                return False
            time.sleep(interval_ms / 1000)
            continue
        time.sleep(interval_ms / 1000)
    return False


def wait_for_tutorial_list(
    backend: MaaBackend,
    advance_point: tuple[int, int],
    timeout_ms: int = 60_000,
    interval_ms: int = 700,
) -> bool:
    """推进教程结束对白，直到返回对战教程列表。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if backend.is_stopping():
            return False
        frame = backend.capture_frame()
        if frame is None:
            time.sleep(interval_ms / 1000)
            continue
        if backend.verify(TUTORIAL_LIST, frame):
            return True
        if not backend.tap(*advance_point):
            return False
        time.sleep(interval_ms / 1000)
    return False


def reset_puzzle_for_debug(backend: MaaBackend, layout: BoardLayout) -> None:
    """从关卡内点击左侧重置按钮；只供显式调试流程调用。"""
    LOGGER.info("[调试] 点击左侧重置按钮")
    if not backend.tap(*layout.fixed_point("puzzle_reset")):
        raise SolutionError("调试重置盘面失败")
    time.sleep(1_200 / 1000)


@lru_cache(maxsize=4)
def _load_layout(project_root: Path) -> BoardLayout:
    return BoardLayout.load(find_resource_root(project_root) / "layouts" / "default.json")


@lru_cache(maxsize=128)
def _load_solution(project_root: Path, solution_id: str):
    return SolutionRepository.for_project(project_root).load(solution_id)


def _select_puzzle(
    navigator: PuzzleNavigator,
    navigation: dict,
    list_categories: list[dict],
    layout: BoardLayout,
    search_swipes: int,
    skip_completed: bool,
) -> str | None:
    list_top = layout.fixed_point("puzzle_list_top")
    list_bottom = layout.fixed_point("puzzle_list_bottom")
    for category in list_categories:
        LOGGER.info("确认类别展开状态：%s", category["display_name"])
        if not navigator.activate_category(
            category,
            list_top,
            list_bottom,
            search_swipes,
            navigation["name_pattern"],
        ):
            return None
    return navigator.select_puzzle(
        navigation["name_pattern"],
        *layout.fixed_point("puzzle_confirm"),
        list_top,
        list_bottom,
        min(search_swipes, 6),
        skip_completed=skip_completed,
    )


def run_solution(
    context: Context,
    solution_id: str,
    *,
    skip_completed: bool = False,
    reset_before_execute: bool = False,
    start_step: int = 1,
) -> bool:
    project_root = resolve_project_root()
    solution = _load_solution(project_root, solution_id)
    layout = _load_layout(project_root)
    backend = MaaBackend(context, layout)
    list_node = PUZZLE_LIST
    list_label = "盘面解密"
    navigator = PuzzleNavigator(backend)
    if solution.category == "tutorial":
        list_node = TUTORIAL_LIST
        list_label = "对战教程"
        navigator = PuzzleNavigator(
            backend,
            ListNavigationNodes(
                name=TUTORIAL_NAME,
                tab=TUTORIAL_TAB,
                category=TUTORIAL_NAME,
                confirm=TUTORIAL_CONFIRM,
                confirm_enabled=TUTORIAL_CONFIRM_ENABLED,
            ),
        )

    if (
        reset_before_execute
        and solution.category == "puzzle"
        and not backend.verify(PUZZLE_LIST)
    ):
        reset_puzzle_for_debug(backend, layout)

    entered_from_list = False
    if solution.navigation is not None:
        display_name = solution.navigation["display_name"]
        if backend.verify(list_node):
            entered_from_list = True
            categories = solution.navigation.get("categories", [])
            tab_categories = [item for item in categories if item["scope"] == "tab"]
            list_categories = [item for item in categories if item["scope"] == "list"]
            list_top = layout.fixed_point("puzzle_list_top")
            list_bottom = layout.fixed_point("puzzle_list_bottom")
            search_swipes = solution.navigation.get("search_swipes", 20)

            if not navigator.confirm_categories(
                tab_categories, list_top, list_bottom, search_swipes
            ):
                raise SolutionError(f"未能确认{list_label}固定类别")
            LOGGER.info("[导航 1/3] 已确认%s固定标签", list_label)

            LOGGER.info("[导航 2/3] 确认列表类别")
            LOGGER.info("[导航 3/3] 查找题目：%s", display_name)
            selection = _select_puzzle(
                navigator,
                solution.navigation,
                list_categories,
                layout,
                search_swipes,
                skip_completed and solution.category == "puzzle",
            )
            if selection == "completed":
                LOGGER.info("[跳过] 已完成并领取奖励：%s", display_name)
                return False
            selected = selection == "selected"

            if not selected:
                LOGGER.info("[导航重试] 重新确认类别并查找题目")
                selection = _select_puzzle(
                    navigator,
                    solution.navigation,
                    list_categories,
                    layout,
                    search_swipes,
                    skip_completed and solution.category == "puzzle",
                )
                if selection == "completed":
                    LOGGER.info("[跳过] 已完成并领取奖励：%s", display_name)
                    return False
                selected = selection == "selected"
            if not selected:
                raise SolutionError(f"未能在列表中识别{list_label}: {display_name}")
            time.sleep(solution.navigation.get("entry_wait_ms", 3500) / 1000)
        else:
            LOGGER.info("当前不在%s列表，按已进入关卡继续", list_label)

        should_sync_opening = (
            solution.category != "tutorial"
            and (entered_from_list or start_step == 1)
        )
        if should_sync_opening:
            LOGGER.info("[开场] 正在跳过教程提示并等待可操作盘面")
        if should_sync_opening and not backend.skip_dialogue(
            TUTORIAL_LEADER_OPERABLE,
            *layout.fixed_point("dialog_advance"),
            60,
            350,
            2,
            ready_grace_ms=3000 if entered_from_list else 0,
        ):
            raise SolutionError("进入关卡后未能识别到可操作盘面")
        if should_sync_opening:
            LOGGER.info("[开场] 已进入可操作状态")
        elif solution.category != "tutorial":
            LOGGER.info("[调试] 从第 %d 步继续，跳过开场状态同步", start_step)
        else:
            LOGGER.info("[教程] 由解法按固定次数推进教学提示")

    LOGGER.info("开始执行解法: %s (%s)", solution.id, solution.name)
    emit_event("solution", f"开始执行：{solution.name}", state="starting", name=solution.id)
    LOGGER.info("[解法] 开始执行：%s", solution.name)
    SolutionExecutor(backend, LOGGER, layout).execute(solution, start_step=start_step)
    LOGGER.info("解法执行完成: %s", solution.id)
    emit_event("solution", f"解法动作完成：{solution.name}", state="succeeded", name=solution.id)

    if solution.navigation is not None and solution.category == "puzzle":
        LOGGER.info("[完成] 解法动作已执行，等待返回盘面解密列表")
        if not wait_for_puzzle_list(
            backend, layout.fixed_point("puzzle_reward_continue")
        ):
            raise SolutionError("解密完成后 60 秒内未返回盘面解密列表")
    elif solution.navigation is not None and solution.category == "tutorial":
        LOGGER.info("[完成] 教程动作已执行，推进结束对白并等待返回教程列表")
        if not wait_for_tutorial_list(
            backend, layout.fixed_point("dialog_advance")
        ):
            raise SolutionError("教程完成后 60 秒内未返回对战教程列表")
    return True
