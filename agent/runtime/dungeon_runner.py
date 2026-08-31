from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from maa.context import Context

from battle_engine.models import BattleState, CardCatalog
from battle_engine.observer import HandText, ObservedHandCard, parse_hand_texts
from battle_engine.policy import BattlePolicy
from battle_engine.repository import BattleProfileRepository, CardCatalogRepository
from battle_engine.session import BattleSession, SettlementAction
from pipeline_nodes import (
    DUNGEON_CHALLENGE,
    DUNGEON_DECK_CONFIRM,
    DUNGEON_DEFEAT,
    DUNGEON_END_CONFIRM,
    DUNGEON_HAND_NAMES,
    DUNGEON_LIST,
    DUNGEON_MULLIGAN,
    DUNGEON_PLAYER_TURN,
    DUNGEON_REPLAY,
    DUNGEON_RETURN,
    DUNGEON_VICTORY,
)
from solution_engine.layout import BoardLayout
from solution_engine.models import SolutionError

from .backend import MaaBackend
from .events import emit_event
from .runner import _load_layout, resolve_project_root


LOGGER = logging.getLogger("maasvwb.dungeon")


class BattleOutcome(str, Enum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TurnReady:
    current_energy: int
    maximum_energy: int


class DungeonBattleRunner:
    def __init__(
        self,
        backend: MaaBackend,
        layout: BoardLayout,
        catalog: CardCatalog,
        policy: BattlePolicy,
        session: BattleSession,
    ) -> None:
        self.backend = backend
        self.layout = layout
        self.catalog = catalog
        self.policy = policy
        self.session = session

    def run(self) -> None:
        while True:
            self._enter_or_resume_battle()
            outcome = self._play_until_settlement()
            if outcome is BattleOutcome.VICTORY:
                action = self.session.record_victory()
                emit_event(
                    "dungeon",
                    f"胜利 {self.session.victories}/{self.session.battle_count}",
                    state="progress",
                )
            elif outcome is BattleOutcome.DEFEAT:
                action = self.session.record_defeat()
                emit_event(
                    "dungeon",
                    f"本局失败，连续失败 {self.session.consecutive_failures} 次",
                    state="progress",
                )
            else:
                action = self.session.record_unknown()

            if action is SettlementAction.RETURN_TO_DUNGEON:
                if not self.backend.tap_recognition(DUNGEON_RETURN, 15_000):
                    raise SolutionError("达到目标胜场后未能点击返回地城")
                LOGGER.info("地城目标已完成：%d 场胜利", self.session.victories)
                return
            if action is SettlementAction.STOP:
                if outcome is BattleOutcome.UNKNOWN:
                    raise SolutionError("无法确认地城试炼结算状态，已安全停止")
                raise SolutionError("连续失败超过三次，已停止地城试炼")
            if not self.backend.tap_recognition(DUNGEON_REPLAY, 15_000):
                raise SolutionError("结算后未能点击再战")
            time.sleep(2.0)

    def _enter_or_resume_battle(self) -> None:
        deadline = time.monotonic() + 120
        stage_clicked = False
        while time.monotonic() < deadline:
            if self.backend.is_stopping():
                raise SolutionError("地城试炼已停止")
            frame = self.backend.capture_frame()
            if frame is None:
                time.sleep(0.5)
                continue
            if self.backend.verify(DUNGEON_PLAYER_TURN, frame):
                return
            if self.backend.verify(DUNGEON_MULLIGAN, frame):
                LOGGER.info("[开局] 不交换手牌，直接决定")
                if not self.backend.tap(*self.layout.fixed_point("mulligan_confirm")):
                    raise SolutionError("换牌阶段点击决定失败")
                time.sleep(4.0)
                continue
            if self.backend.verify(DUNGEON_DECK_CONFIRM, frame):
                LOGGER.info("[开局] 使用游戏当前牌组并点击决定")
                if not self.backend.tap(*self.layout.fixed_point("dungeon_deck_decide")):
                    raise SolutionError("确认当前牌组失败")
                time.sleep(4.0)
                continue
            if self.backend.verify(DUNGEON_CHALLENGE, frame):
                if not self.backend.tap_recognition(DUNGEON_CHALLENGE, 3_000):
                    raise SolutionError("点击地城挑战按钮失败")
                time.sleep(1.0)
                continue
            if self.backend.verify(DUNGEON_LIST, frame) and not stage_clicked:
                LOGGER.info("[入口] 选择当前第一个地城关卡")
                if not self.backend.tap(*self.layout.fixed_point("dungeon_stage_first")):
                    raise SolutionError("点击地城关卡失败")
                stage_clicked = True
                time.sleep(1.0)
                continue
            time.sleep(0.5)
        raise SolutionError("120 秒内未能进入地城战斗")

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
        raise SolutionError("地城战斗超过 50 个己方回合，已安全停止")

    def _end_turn(self) -> bool:
        if not self.backend.tap(*self.layout.fixed_point("end_turn")):
            return False
        time.sleep(0.7)
        frame = self.backend.capture_frame()
        if frame is not None and self.backend.verify(DUNGEON_END_CONFIRM, frame):
            LOGGER.info("[回合] 仍有可用卡牌，确认结束回合")
            if not self.backend.tap_recognition(DUNGEON_END_CONFIRM, 3_000):
                return False
            if not self.backend.wait_recognition_gone(
                DUNGEON_END_CONFIRM, 5_000, 250
            ):
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
                raise SolutionError("地城试炼已停止")
            frame = self.backend.capture_frame()
            if frame is None:
                time.sleep(0.5)
                continue
            if self.backend.verify(DUNGEON_REPLAY, frame):
                return self._classify_settlement(frame)
            if self.backend.verify(DUNGEON_PLAYER_TURN, frame):
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

    def _classify_settlement(self, initial_frame) -> BattleOutcome:
        deadline = time.monotonic() + 6.0
        frame = initial_frame
        while time.monotonic() < deadline:
            if self.backend.verify(DUNGEON_VICTORY, frame):
                return BattleOutcome.VICTORY
            if self.backend.verify(DUNGEON_DEFEAT, frame):
                return BattleOutcome.DEFEAT
            time.sleep(0.5)
            next_frame = self.backend.capture_frame()
            if next_frame is not None:
                frame = next_frame
        # 结算页已有“再战”但没有胜利奖励区时，按失败处理。
        return BattleOutcome.DEFEAT

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
        detail = self.backend.recognize(DUNGEON_HAND_NAMES, frame=frame)
        if not detail or not detail.hit:
            if not self.backend.tap(*self.layout.fixed_point("hand_expand")):
                return ()
            time.sleep(0.4)
            frame = self.backend.capture_frame()
            detail = self.backend.recognize(DUNGEON_HAND_NAMES, frame=frame)
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


def run_dungeon(context: Context, profile_id: str, battle_count: int) -> None:
    project_root = resolve_project_root()
    catalog = CardCatalogRepository.for_project(project_root).load()
    profile = BattleProfileRepository.for_project(project_root, catalog).load(profile_id)
    layout = _load_layout(project_root)
    backend = MaaBackend(context, layout)
    session = BattleSession(battle_count=battle_count)
    emit_event(
        "dungeon",
        f"开始地城试炼：目标 {battle_count} 场胜利",
        state="starting",
    )
    DungeonBattleRunner(
        backend,
        layout,
        catalog,
        BattlePolicy(profile, catalog),
        session,
    ).run()
    emit_event("dungeon", "地城试炼目标完成", state="succeeded")
