from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from maa.context import Context

from solution_engine.executor import SolutionExecutor
from solution_engine.layout import BoardLayout
from solution_engine.models import SolutionError
from solution_engine.repository import SolutionRepository

from .backend import MaaBackend
from .events import emit_event
from .puzzle_navigator import PuzzleNavigator


LOGGER = logging.getLogger("maasvwb.solution")


def resolve_project_root() -> Path:
    configured = os.environ.get("MAASVWB_ROOT")
    if configured:
        return Path(configured).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = resolve_project_root()


def find_resource_root() -> Path:
    candidates = (PROJECT_ROOT / "assets" / "resource", PROJECT_ROOT / "resource")
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
        if backend.verify("识别_盘面解密列表"):
            return True
        if backend.verify("识别_盘面解密奖励领取"):
            print("[完成] 检测到首次通关奖励，点击继续", flush=True)
            if not backend.tap(*reward_continue):
                return False
            time.sleep(1)
            continue
        time.sleep(interval_ms / 1000)
    return False


def reset_puzzle_for_debug(backend: MaaBackend, layout: BoardLayout) -> None:
    """从关卡内点击左侧重置按钮；只供显式调试流程调用。"""
    print("[调试] 点击左侧重置按钮", flush=True)
    if not backend.tap(*layout.fixed_point("puzzle_reset")):
        raise SolutionError("调试重置盘面失败")
    time.sleep(1_200 / 1000)


def run_solution(
    context: Context,
    solution_id: str,
    *,
    skip_completed: bool = False,
    reset_before_execute: bool = False,
) -> bool:
    solution = SolutionRepository.for_project(PROJECT_ROOT).load(solution_id)
    layout = BoardLayout.load(find_resource_root() / "layouts" / "default.json")
    backend = MaaBackend(context)
    navigator = PuzzleNavigator(backend)

    if reset_before_execute and not backend.verify("识别_盘面解密列表"):
        reset_puzzle_for_debug(backend, layout)

    entered_from_list = False
    if solution.navigation is not None:
        display_name = solution.navigation["display_name"]
        if backend.verify("识别_盘面解密列表"):
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
                raise SolutionError("未能确认盘面解密固定类别")
            print("[导航 1/3] 已确认盘面解密固定标签", flush=True)

            for category in list_categories:
                print(f"[导航 2/3] 确认类别展开状态：{category['display_name']}", flush=True)
                if not navigator.activate_category(
                    category,
                    list_top,
                    list_bottom,
                    search_swipes,
                    solution.navigation["name_pattern"],
                ):
                    raise SolutionError(
                        f"未能展开盘面解密类别: {category['display_name']}"
                    )

            print(f"[导航 3/3] 查找题目：{display_name}", flush=True)
            selection = navigator.select_puzzle(
                solution.navigation["name_pattern"],
                *layout.fixed_point("puzzle_confirm"),
                list_top,
                list_bottom,
                min(search_swipes, 6),
                skip_completed=skip_completed,
            )
            if selection == "completed":
                print(f"[跳过] 已完成并领取奖励：{display_name}", flush=True)
                return False
            selected = selection == "selected"

            if not selected:
                for category in list_categories:
                    print(f"[导航重试] 重新确认类别展开状态：{category['display_name']}", flush=True)
                    if not navigator.activate_category(
                        category,
                        list_top,
                        list_bottom,
                        search_swipes,
                        solution.navigation["name_pattern"],
                    ):
                        break
                else:
                    selection = navigator.select_puzzle(
                        solution.navigation["name_pattern"],
                        *layout.fixed_point("puzzle_confirm"),
                        list_top,
                        list_bottom,
                        min(search_swipes, 6),
                        skip_completed=skip_completed,
                    )
                    if selection == "completed":
                        print(f"[跳过] 已完成并领取奖励：{display_name}", flush=True)
                        return False
                    selected = selection == "selected"
            if not selected:
                raise SolutionError(f"未能在列表中识别盘面解密: {display_name}")
            time.sleep(solution.navigation.get("entry_wait_ms", 3500) / 1000)
        else:
            LOGGER.info("当前不在盘面解密列表，按已进入关卡继续")

        print("[开场] 正在跳过教程提示并等待可操作盘面", flush=True)
        if not backend.skip_dialogue(
            "识别_教程主战者框可操作",
            *layout.fixed_point("dialog_advance"),
            60,
            350,
            2,
            ready_grace_ms=3000 if entered_from_list else 0,
        ):
            raise SolutionError("进入关卡后未能识别到可操作盘面")
        print("[开场] 已进入可操作状态", flush=True)

    LOGGER.info("开始执行解法: %s (%s)", solution.id, solution.name)
    emit_event("solution", f"开始执行：{solution.name}", state="starting", name=solution.id)
    print(f"[解法] 开始执行：{solution.name}", flush=True)
    SolutionExecutor(backend, LOGGER, layout).execute(solution)
    LOGGER.info("解法执行完成: %s", solution.id)
    emit_event("solution", f"解法动作完成：{solution.name}", state="succeeded", name=solution.id)

    if solution.navigation is not None:
        print("[完成] 解法动作已执行，等待返回盘面解密列表", flush=True)
        if not wait_for_puzzle_list(
            backend, layout.fixed_point("puzzle_reward_continue")
        ):
            raise SolutionError("解密完成后 60 秒内未返回盘面解密列表")
    return True
