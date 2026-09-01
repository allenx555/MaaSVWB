from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from battle_engine.models import BattleState, CardCatalog
from battle_engine.observer import HandText, ObservedHandCard, parse_hand_texts
from battle_engine.policy import BattlePolicy
from pipeline_nodes import (
    BATTLE_DEFEAT,
    BATTLE_END_CONFIRM,
    BATTLE_HAND_NAMES,
    BATTLE_MULLIGAN,
    BATTLE_PLAYER_TURN,
    BATTLE_VICTORY,
)
from solution_engine.layout import BoardLayout
from solution_engine.models import SolutionError

from .backend import MaaBackend


LOGGER = logging.getLogger("maasvwb.battle")


class BattleOutcome(str, Enum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TurnReady:
    current_energy: int
    maximum_energy: int


class BattleRunner:
    """可由不同玩法复用的基础对战状态机。"""

    def __init__(
        self,
        backend: MaaBackend,
        layout: BoardLayout,
        catalog: CardCatalog,
        policy: BattlePolicy,
    ) -> None:
        self.backend = backend
        self.layout = layout
        self.catalog = catalog
        self.policy = policy

    def is_start_state(self, frame) -> bool:
        """判断画面是否已经进入基础战斗流程。"""
        return self.backend.verify(
            BATTLE_MULLIGAN, frame
        ) or self.backend.verify(BATTLE_PLAYER_TURN, frame)

    def run(self) -> BattleOutcome:
        """从换牌或己方回合开始，运行到能够确认胜负为止。"""
        self._prepare_initial_hand()
        return self._play_until_settlement()

    def _prepare_initial_hand(self) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.backend.is_stopping():
                raise SolutionError("战斗已停止")
            frame = self.backend.capture_frame()
            if frame is None:
                time.sleep(0.5)
                continue
            if self.backend.verify(BATTLE_PLAYER_TURN, frame):
                return
            if self.backend.verify(BATTLE_MULLIGAN, frame):
                LOGGER.info("[开局] 不交换手牌，直接决定")
                if not self.backend.tap(*self.layout.fixed_point("mulligan_confirm")):
                    raise SolutionError("换牌阶段点击决定失败")
                time.sleep(4.0)
                continue
            time.sleep(0.5)
        raise SolutionError("120 秒内未能进入己方回合")

    def _play_until_settlement(self) -> BattleOutcome:
        previous_maximum: int | None = None
        for turn in range(1, 51):
            state = self._wait_for_turn_or_settlement(
                120_000, previous_maximum=previous_maximum
            )
            if isinstance(state, BattleOutcome):
                return state
            LOGGER.info(
                "[回合 %d] 开始自动操作，能量 %d/%d",
                turn,
                state.current_energy,
                state.maximum_energy,
            )
            self._execute_turn()
            if not self._end_turn():
                raise SolutionError("点击结束回合失败")
            previous_maximum = state.maximum_energy
            time.sleep(1.0)
        raise SolutionError("战斗超过 50 个己方回合，已安全停止")

    def _end_turn(self) -> bool:
        if not self.backend.tap(*self.layout.fixed_point("end_turn")):
            return False
        time.sleep(0.7)
        frame = self.backend.capture_frame()
        if frame is not None and self.backend.verify(BATTLE_END_CONFIRM, frame):
            LOGGER.info("[回合] 仍有可用卡牌，确认结束回合")
            if not self.backend.tap_recognition(BATTLE_END_CONFIRM, 3_000):
                return False
            if not self.backend.wait_recognition_gone(BATTLE_END_CONFIRM, 5_000, 250):
                return False
        return True

    def _wait_for_turn_or_settlement(
        self,
        timeout_ms: int,
        *,
        previous_maximum: int | None,
    ) -> TurnReady | BattleOutcome:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self.backend.is_stopping():
                raise SolutionError("战斗已停止")
            frame = self.backend.capture_frame()
            if frame is None:
                time.sleep(0.5)
                continue
            outcome = self._recognize_outcome(frame)
            if outcome is not None:
                return outcome
            if self.backend.verify(BATTLE_PLAYER_TURN, frame):
                energy = self.backend.read_energy_points()
                if energy is None:
                    time.sleep(0.3)
                    continue
                current, maximum = energy
                if self._is_new_turn_energy(current, maximum, previous_maximum):
                    return TurnReady(current, maximum)
                LOGGER.debug(
                    "结束回合按钮已出现，但能量尚未满足新回合条件: "
                    "%d/%d，上回合上限=%d",
                    current,
                    maximum,
                    previous_maximum,
                )
            time.sleep(0.5)
        return BattleOutcome.UNKNOWN

    def _recognize_outcome(self, frame) -> BattleOutcome | None:
        if self.backend.verify(BATTLE_VICTORY, frame):
            return BattleOutcome.VICTORY
        if self.backend.verify(BATTLE_DEFEAT, frame):
            return BattleOutcome.DEFEAT
        return None

    @staticmethod
    def _is_new_turn_energy(
        current: int,
        maximum: int,
        previous_maximum: int | None,
    ) -> bool:
        if previous_maximum is None:
            # 允许从用户已操作过一部分的己方回合中途接管。
            return 0 <= current <= maximum
        if previous_maximum < 10:
            return maximum > previous_maximum and current == maximum
        return current == maximum == 10

    def _execute_turn(self) -> None:
        played_counts: dict[str, int] = {}
        no_progress = 0
        for _ in range(self.policy.profile.safety.max_actions_per_turn):
            energy_pair = self.backend.read_energy_points()
            if energy_pair is None:
                break
            energy, _maximum = energy_pair
            hand = self._observe_hand(energy)
            if not hand:
                break
            ally_count = self.backend.read_follower_count("ally") or 0
            state = BattleState(
                energy=energy,
                board_slots=max(0, 5 - ally_count),
                enemy_has_ward=bool(
                    self.backend.read_ward_indexes(
                        self.backend.read_follower_count("enemy") or 0
                    )
                ),
                hand=tuple(item.card for item in hand),
                played_counts=played_counts,
            )
            plan = self.policy.choose_play_plan(state)
            if plan is None:
                break
            step = plan.steps[0]
            selected = next(
                (item for item in hand if item.card.hand_index == step.hand_index),
                None,
            )
            if selected is None:
                break
            LOGGER.info(
                "[出牌] %s（手牌 %d，策略优先级 %d）",
                selected.name,
                selected.card.hand_index,
                plan.priority,
            )
            before = self.backend.capture_frame()
            if not self.backend.swipe(
                *selected.source, *self.layout.fixed_point("play_area"), 350
            ):
                raise SolutionError(f"使用卡牌失败: {selected.name}")
            if step.target.type == "enemy_leader":
                time.sleep(0.7)
                if not self.backend.tap(*self.layout.fixed_point("enemy_leader")):
                    raise SolutionError(f"选择敌方主战者失败: {selected.name}")
            changed = self.backend.wait_changed(
                before,
                self.layout.region("hand_and_board"),
                5_000,
                2.0,
                350,
            )
            if changed:
                played_counts[step.card_id] = played_counts.get(step.card_id, 0) + 1
                no_progress = 0
            else:
                no_progress += 1
                LOGGER.warning("出牌后未检测到盘面变化: %s", selected.name)
                if no_progress >= self.policy.profile.safety.no_progress_limit:
                    break
            time.sleep(0.6)

        self._attack_phase()

    def _observe_hand(self, energy: int) -> tuple[ObservedHandCard, ...]:
        frame = self.backend.capture_frame()
        if frame is None:
            return ()
        detail = self.backend.recognize(BATTLE_HAND_NAMES, frame=frame)
        if not detail or not detail.hit:
            if not self.backend.tap(*self.layout.fixed_point("hand_expand")):
                return ()
            time.sleep(0.4)
            frame = self.backend.capture_frame()
            detail = self.backend.recognize(BATTLE_HAND_NAMES, frame=frame)
        if not detail or not detail.hit:
            return ()
        texts = []
        for result in detail.all_results:
            text = getattr(result, "text", "")
            box = getattr(result, "box", None)
            if not text or box is None:
                continue
            if isinstance(box, (list, tuple)) and len(box) == 4:
                x, y, width, height = (int(value) for value in box)
            else:
                x = int(getattr(box, "x"))
                y = int(getattr(box, "y"))
                width = int(getattr(box, "w"))
                height = int(getattr(box, "h"))
            texts.append(HandText(text, x, y, width, height))
        observed = parse_hand_texts(texts, self.catalog, energy)
        LOGGER.info(
            "[手牌] %s",
            ", ".join(f"{item.name}({item.score:.2f})" for item in observed)
            or "未识别到卡名",
        )
        return observed

    def _attack_phase(self) -> None:
        ally_count = self.backend.read_follower_count("ally") or 0
        if ally_count <= 0:
            return
        # 从右向左尝试，可降低左侧随从死亡后其余序号变化的影响。
        for index in range(ally_count, 0, -1):
            enemy_count = self.backend.read_follower_count("enemy") or 0
            wards = self.backend.read_ward_indexes(enemy_count)
            if wards:
                target = self.layout.indexed_point(
                    "enemy_followers", enemy_count, wards[0]
                )
                target_name = f"敌方守护 {wards[0]}"
            else:
                target = self.layout.fixed_point("enemy_leader")
                target_name = "敌方主战者"
            source = self.layout.indexed_point("ally_followers", ally_count, index)
            LOGGER.info("[攻击] 我方随从 %d -> %s", index, target_name)
            if not self.backend.swipe(*source, *target, 350):
                raise SolutionError("随从攻击操作失败")
            time.sleep(0.8)
