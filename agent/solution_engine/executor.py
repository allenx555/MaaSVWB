from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from .layout import BoardLayout
from .models import Solution, SolutionError


class ActionBackend(Protocol):
    def tap(self, x: int, y: int) -> bool: ...

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> bool: ...

    def key(self, keycode: int) -> bool: ...

    def verify(self, pipeline_node: str) -> bool: ...

    def wait_recognition(
        self, pipeline_node: str, timeout_ms: int, interval_ms: int = 500
    ) -> bool: ...

    def wait_recognition_gone(
        self, pipeline_node: str, timeout_ms: int, interval_ms: int = 500
    ) -> bool: ...

    def capture_frame(self) -> Any | None: ...

    def read_hand_count(self) -> int | None: ...

    def hand_is_expanded(
        self, point: tuple[int, int]
    ) -> bool | None: ...

    def tap_recognition(
        self, pipeline_node: str, timeout_ms: int, interval_ms: int = 250
    ) -> bool: ...

    def wait_changed(
        self,
        reference: Any,
        roi: tuple[int, int, int, int],
        timeout_ms: int,
        threshold: float,
        settle_ms: int,
    ) -> bool: ...

    def skip_dialogue(
        self,
        pipeline_node: str,
        click_x: int,
        click_y: int,
        max_clicks: int,
        interval_ms: int,
        stable_hits: int,
    ) -> bool: ...


class SolutionExecutor:
    SUPPORTED_ACTIONS = {
        "tap",
        "swipe",
        "wait",
        "key",
        "verify",
        "play_card",
        "attack",
        "select_target",
        "select_choice",
        "evolve",
        "end_turn",
        "skip_dialogue",
    }

    def __init__(
        self,
        backend: ActionBackend,
        logger: logging.Logger | None = None,
        layout: BoardLayout | None = None,
    ) -> None:
        self.backend = backend
        self.logger = logger or logging.getLogger(__name__)
        self.layout = layout
        self._hand_expanded = False

    def execute(self, solution: Solution) -> None:
        self._hand_expanded = False
        for index, step in enumerate(solution.steps, start=1):
            action = step.get("action")
            if action not in self.SUPPORTED_ACTIONS:
                raise SolutionError(f"第 {index} 步包含未知动作: {action!r}")

            label = step.get("label", action)
            self.logger.info("执行第 %d/%d 步: %s", index, len(solution.steps), label)
            change_check = self._prepare_change_check(step, index)
            self._execute_step(solution, step, index)
            self._verify_postconditions(step, index, change_check)

            after_ms = self._milliseconds(step.get("after_ms", 0), "after_ms", index)
            if after_ms:
                time.sleep(after_ms / 1000)

    def _prepare_change_check(
        self, step: dict, index: int
    ) -> tuple[Any, tuple[int, int, int, int]] | None:
        region_name = step.get("change_roi")
        if region_name is None:
            return None
        if not isinstance(region_name, str) or not region_name:
            raise SolutionError(f"第 {index} 步 change_roi 必须是非空字符串")
        layout = self._require_layout(index)
        reference = self.backend.capture_frame()
        if reference is None:
            raise SolutionError(f"第 {index} 步无法取得动作前截图")
        return reference, layout.region(region_name)

    def _verify_postconditions(
        self,
        step: dict,
        index: int,
        change_check: tuple[Any, tuple[int, int, int, int]] | None,
    ) -> None:
        timeout_ms = self._milliseconds(
            step.get("post_timeout_ms", 5_000), "post_timeout_ms", index
        )
        interval_ms = self._milliseconds(
            step.get("post_interval_ms", 250), "post_interval_ms", index
        )

        if change_check is not None:
            reference, roi = change_check
            threshold = step.get("change_threshold", 2.5)
            if not isinstance(threshold, (int, float)) or not 0 < threshold <= 255:
                raise SolutionError(f"第 {index} 步 change_threshold 必须在 0 到 255 之间")
            settle_ms = self._milliseconds(
                step.get("change_settle_ms", 350), "change_settle_ms", index
            )
            if not self.backend.wait_changed(
                reference, roi, timeout_ms, float(threshold), settle_ms
            ):
                raise SolutionError(f"第 {index} 步执行后盘面没有发生预期变化")

        wait_for = step.get("wait_for")
        if wait_for is not None:
            if not isinstance(wait_for, str) or not wait_for:
                raise SolutionError(f"第 {index} 步 wait_for 必须是非空 Pipeline 节点名")
            if not self.backend.wait_recognition(wait_for, timeout_ms, interval_ms):
                raise SolutionError(f"第 {index} 步未等到状态: {wait_for}")

        wait_until_gone = step.get("wait_until_gone")
        if wait_until_gone is not None:
            if not isinstance(wait_until_gone, str) or not wait_until_gone:
                raise SolutionError(
                    f"第 {index} 步 wait_until_gone 必须是非空 Pipeline 节点名"
                )
            if not self.backend.wait_recognition_gone(
                wait_until_gone, timeout_ms, interval_ms
            ):
                raise SolutionError(f"第 {index} 步状态一直没有消失: {wait_until_gone}")

    def _execute_step(self, solution: Solution, step: dict, index: int) -> None:
        action = step["action"]
        if action == "tap":
            x, y = self._point(solution, step, "point", index)
            self._require_success(self.backend.tap(x, y), index, action)
            return

        if action == "swipe":
            x1, y1 = self._point(solution, step, "from", index)
            x2, y2 = self._point(solution, step, "to", index)
            duration = self._milliseconds(step.get("duration_ms", 300), "duration_ms", index)
            self._require_success(
                self.backend.swipe(x1, y1, x2, y2, duration), index, action
            )
            return

        if action == "wait":
            duration = self._milliseconds(step.get("duration_ms"), "duration_ms", index)
            time.sleep(duration / 1000)
            return

        if action == "key":
            keycode = step.get("keycode")
            if not isinstance(keycode, int) or keycode < 0:
                raise SolutionError(f"第 {index} 步 keycode 必须是非负整数")
            self._require_success(self.backend.key(keycode), index, action)
            return

        if action == "verify":
            node = step.get("pipeline_node")
            if not isinstance(node, str) or not node:
                raise SolutionError(f"第 {index} 步缺少 pipeline_node")
            retries = step.get("retries", 1)
            if not isinstance(retries, int) or not 1 <= retries <= 20:
                raise SolutionError(f"第 {index} 步 retries 必须在 1 到 20 之间")
            interval = self._milliseconds(step.get("interval_ms", 500), "interval_ms", index)
            for attempt in range(retries):
                if self.backend.verify(node):
                    return
                if attempt + 1 < retries:
                    time.sleep(interval / 1000)
            raise SolutionError(f"第 {index} 步识别校验失败: {node}")

        if action == "play_card":
            layout = self._require_layout(index)
            hand_index = self._positive_int(step.get("hand_index"), "hand_index", index)
            authored_hand_count = self._positive_int(
                step.get("hand_count"), "hand_count", index
            )
            hand_count = self._validate_hand_count(
                authored_hand_count, hand_index, index
            )
            expand_hand = step.get("expand_hand")
            if expand_hand is not None and not isinstance(expand_hand, bool):
                raise SolutionError(f"第 {index} 步 expand_hand 必须是布尔值")
            observed_expanded = self._observe_hand_expanded(layout, hand_count)
            if expand_hand is None:
                should_expand = (
                    not observed_expanded
                    if observed_expanded is not None
                    else not self._hand_expanded
                )
            else:
                should_expand = expand_hand
            if should_expand:
                self._require_success(
                    self.backend.tap(*layout.fixed_point("hand_expand")),
                    index,
                    action,
                )
                expand_delay = self._milliseconds(
                    step.get("expand_delay_ms", 350), "expand_delay_ms", index
                )
                if expand_delay:
                    time.sleep(expand_delay / 1000)
            # 普通出牌后手牌保持展开；显式 false 也表示调用方确认它已经展开。
            self._hand_expanded = True
            source = layout.indexed_point("hand", hand_count, hand_index)
            destination = layout.fixed_point("play_area")
            duration = self._milliseconds(step.get("duration_ms", 350), "duration_ms", index)
            self._require_success(
                self.backend.swipe(*source, *destination, duration), index, action
            )
            target = step.get("target")
            if target is not None:
                delay = self._milliseconds(
                    step.get("target_delay_ms", 600), "target_delay_ms", index
                )
                if delay:
                    time.sleep(delay / 1000)
                self._tap_target(layout, target, index)
                # 指定目标完成后游戏会把手牌收回右下角；下一次出牌需重新展开。
                self._hand_expanded = False
            return

        if action == "attack":
            layout = self._require_layout(index)
            attacker_index = self._positive_int(
                step.get("attacker_index"), "attacker_index", index
            )
            ally_count = self._positive_int(step.get("ally_count"), "ally_count", index)
            source = layout.indexed_point("ally_followers", ally_count, attacker_index)
            target = self._target_point(layout, step.get("target"), index)
            duration = self._milliseconds(step.get("duration_ms", 300), "duration_ms", index)
            self.logger.info(
                "攻击拖拽：当前己方随从 %d/%d，%s -> %s，目标=%s",
                attacker_index,
                ally_count,
                source,
                target,
                step.get("target", {}).get("type"),
            )
            self._require_success(
                self.backend.swipe(*source, *target, duration), index, action
            )
            return

        if action == "select_target":
            layout = self._require_layout(index)
            self._tap_target(layout, step.get("target"), index)
            return

        if action == "select_choice":
            layout = self._require_layout(index)
            choice_index = self._positive_int(
                step.get("choice_index"), "choice_index", index
            )
            choice_count = self._positive_int(
                step.get("choice_count"), "choice_count", index
            )
            point = layout.indexed_point("choices", choice_count, choice_index)
            self._require_success(
                self.backend.tap(*point), index, "select_choice"
            )
            # 模式选择完成后回到盘面，手牌会收回右下角。
            self._hand_expanded = False
            return

        if action == "evolve":
            layout = self._require_layout(index)
            evolution_type = step.get("evolution_type", "normal")
            evolution_nodes = {
                "normal": "识别_进化按钮",
                "super": "识别_超进化按钮",
            }
            if evolution_type not in evolution_nodes:
                raise SolutionError(
                    f"第 {index} 步 evolution_type 必须是 normal 或 super"
                )
            self._tap_target(layout, step.get("target"), index)
            detail_delay = self._milliseconds(
                step.get("detail_delay_ms", 500), "detail_delay_ms", index
            )
            if detail_delay:
                time.sleep(detail_delay / 1000)
            self._require_success(
                self.backend.tap_recognition(
                    evolution_nodes[evolution_type],
                    self._milliseconds(
                        step.get("evolution_timeout_ms", 5_000),
                        "evolution_timeout_ms",
                        index,
                    ),
                ),
                index,
                action,
            )
            self._hand_expanded = False
            return

        if action == "end_turn":
            layout = self._require_layout(index)
            self._require_success(
                self.backend.tap(*layout.fixed_point("end_turn")), index, action
            )
            return

        if action == "skip_dialogue":
            layout = self._require_layout(index)
            node = step.get("pipeline_node", "识别_教程主战者框可操作")
            if not isinstance(node, str) or not node:
                raise SolutionError(f"第 {index} 步 pipeline_node 必须是非空字符串")
            max_clicks = self._positive_int(step.get("max_clicks", 30), "max_clicks", index)
            stable_hits = self._positive_int(
                step.get("stable_hits", 2), "stable_hits", index
            )
            if max_clicks > 100:
                raise SolutionError(f"第 {index} 步 max_clicks 不能超过 100")
            if stable_hits > 5:
                raise SolutionError(f"第 {index} 步 stable_hits 不能超过 5")
            interval = self._milliseconds(
                step.get("interval_ms", 500), "interval_ms", index
            )
            click_x, click_y = layout.fixed_point("dialog_advance")
            self._require_success(
                self.backend.skip_dialogue(
                    node,
                    click_x,
                    click_y,
                    max_clicks,
                    interval,
                    stable_hits,
                ),
                index,
                action,
            )
            return

    @staticmethod
    def _milliseconds(value: object, field: str, index: int) -> int:
        if not isinstance(value, int) or not 0 <= value <= 30_000:
            raise SolutionError(f"第 {index} 步 {field} 必须在 0 到 30000 毫秒之间")
        return value

    @staticmethod
    def _positive_int(value: object, field: str, index: int) -> int:
        if not isinstance(value, int) or value < 1:
            raise SolutionError(f"第 {index} 步 {field} 必须是正整数")
        return value

    def _require_layout(self, index: int) -> BoardLayout:
        if self.layout is None:
            raise SolutionError(f"第 {index} 步需要加载棋盘布局")
        return self.layout

    def _validate_hand_count(
        self, authored_count: int, hand_index: int, index: int
    ) -> int:
        observed = self.backend.read_hand_count()
        if observed is None:
            return authored_count
        if observed < hand_index:
            raise SolutionError(
                f"第 {index} 步实时手牌只有 {observed} 张，无法选择第 {hand_index} 张"
            )
        if observed != authored_count:
            raise SolutionError(
                f"第 {index} 步实时手牌为 {observed} 张，与脚本预期的 "
                f"{authored_count} 张不一致；上一动作可能未成功结算"
            )
        return observed

    def _observe_hand_expanded(
        self, layout: BoardLayout, hand_count: int
    ) -> bool | None:
        # 始终探测最左侧展开卡位，避免右侧收拢牌扇与目标牌位重叠而误判。
        return self.backend.hand_is_expanded(
            layout.indexed_point("hand", hand_count, 1)
        )

    def _tap_target(self, layout: BoardLayout, target: object, index: int) -> None:
        point = self._target_point(layout, target, index)
        self._require_success(self.backend.tap(*point), index, "select_target")

    def _target_point(self, layout: BoardLayout, target: object, index: int) -> tuple[int, int]:
        if not isinstance(target, dict):
            raise SolutionError(f"第 {index} 步 target 必须是对象")
        target_type = target.get("type")
        fixed_targets = {
            "enemy_leader": "enemy_leader",
            "ally_leader": "ally_leader",
        }
        if target_type in fixed_targets:
            return layout.fixed_point(fixed_targets[target_type])

        indexed_targets = {
            "enemy_follower": "enemy_followers",
            "ally_follower": "ally_followers",
        }
        if target_type in indexed_targets:
            target_index = self._positive_int(target.get("index"), "target.index", index)
            target_count = self._positive_int(target.get("count"), "target.count", index)
            return layout.indexed_point(
                indexed_targets[target_type], target_count, target_index
            )
        raise SolutionError(f"第 {index} 步包含未知目标类型: {target_type!r}")

    @staticmethod
    def _require_success(success: bool, index: int, action: str) -> None:
        if not success:
            raise SolutionError(f"第 {index} 步 {action} 执行失败")

    @staticmethod
    def _point(solution: Solution, step: dict, field: str, index: int) -> tuple[int, int]:
        value = step.get(field)
        if isinstance(value, str):
            try:
                return solution.points[value]
            except KeyError as exc:
                raise SolutionError(f"第 {index} 步引用了未知坐标点: {value}") from exc
        if (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(coordinate, int) for coordinate in value)
        ):
            return value[0], value[1]
        raise SolutionError(f"第 {index} 步 {field} 必须是坐标点名称或 [x, y]")
