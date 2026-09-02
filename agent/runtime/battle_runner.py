from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from battle_engine.deck_tracker import DeckTracker
from battle_engine.models import BattleState, CardCatalog
from battle_engine.observer import (
    HandText,
    ObservedHandCard,
    normalize_card_name,
    parse_hand_texts,
    recognition_results_to_hand_texts,
)
from battle_engine.policy import BattlePolicy
from pipeline_nodes import (
    BATTLE_DEFEAT,
    BATTLE_END_CONFIRM,
    BATTLE_HAND_NAMES,
    BATTLE_MULLIGAN,
    BATTLE_MULLIGAN_NAMES,
    BATTLE_PLAYER_TURN,
    BATTLE_VICTORY,
    EVOLVE_BUTTON,
    SUPER_EVOLVE_BUTTON,
)
from solution_engine.layout import BoardLayout
from solution_engine.models import SolutionError

from .backend import MaaBackend
from .events import emit_deck_update


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
        deck_code: str | None = None,
    ) -> None:
        self.backend = backend
        self.layout = layout
        self.catalog = catalog
        self.policy = policy
        self._deck_code = deck_code
        self._deck_tracker = self._make_tracker()
        self._hand_expanded = False

    def _make_tracker(self) -> DeckTracker:
        if self._deck_code:
            return DeckTracker.from_deck_code(self._deck_code, self.catalog)
        return DeckTracker.from_profile(self.policy.profile)

    def reset_tracker(self) -> None:
        """Reinitialise the deck tracker at the start of a new battle."""
        self._deck_tracker = self._make_tracker()

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
                self._apply_mulligan(frame)
                if not self.backend.tap(*self.layout.fixed_point("mulligan_confirm")):
                    raise SolutionError("换牌阶段点击决定失败")
                time.sleep(4.0)
                continue
            time.sleep(0.5)
        raise SolutionError("120 秒内未能进入己方回合")

    def _apply_mulligan(self, frame) -> None:
        if not self.policy.profile.mulligan.enabled:
            LOGGER.info("[开局] 当前策略不交换起手，直接决定")
            return

        detail = self.backend.recognize(BATTLE_MULLIGAN_NAMES, frame=frame)
        if not detail or not detail.hit:
            LOGGER.warning("[开局] 未识别到起手卡名，安全保留全部手牌")
            return
        source_y = self.layout.fixed_point("mulligan_card_anchor")[1]
        target_y = self.layout.fixed_point("mulligan_replace_anchor")[1]
        texts = recognition_results_to_hand_texts(detail.all_results)
        observed = parse_hand_texts(texts, self.catalog, energy=20, source_y=source_y)
        replacement_indexes = frozenset(
            self.policy.choose_mulligan_replacements(
                tuple(item.card for item in observed)
            )
        )
        replacements = tuple(
            item for item in observed if item.card.hand_index in replacement_indexes
        )
        LOGGER.info(
            "[开局] 起手识别：%s；交换：%s",
            ", ".join(item.name for item in observed) or "无",
            ", ".join(item.name for item in replacements) or "无",
        )

        for item in replacements:
            changed = False
            for attempt in range(self.policy.profile.safety.max_retries_per_action + 1):
                before = self.backend.capture_frame()
                if before is None:
                    continue
                if not self.backend.swipe(
                    *item.source,
                    item.source[0],
                    target_y,
                    450,
                ):
                    continue
                changed = self.backend.wait_changed(
                    before,
                    self.layout.region("mulligan_selection"),
                    3_000,
                    1.0,
                    250,
                )
                if changed:
                    break
                LOGGER.warning(
                    "[开局] 选择交换卡牌后画面未变化：%s（第 %d 次）",
                    item.name,
                    attempt + 1,
                )
            if not changed:
                raise SolutionError(f"选择交换起手失败: {item.name}")
            time.sleep(0.4)

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
        self._hand_expanded = False
        evolved = False
        if self.policy.profile.evolution.enabled:
            evolved = self._try_evolve_existing_follower()

        played_followers = self._play_cards()
        if self.policy.profile.evolution.enabled and not evolved:
            self._try_evolve_played_followers(played_followers)

        self._attack_phase()
        self._emit_tracker_events()

    def _play_cards(self) -> tuple[str, ...]:
        played_counts: dict[str, int] = {}
        played_followers: list[str] = []
        no_progress = 0
        for _ in range(self.policy.profile.safety.max_actions_per_turn):
            energy_pair = self.backend.read_energy_points()
            if energy_pair is None:
                break
            energy, _maximum = energy_pair
            hand = self._observe_hand(energy)
            if hand is None:
                LOGGER.warning("[出牌] 截图失败，跳过本次观测并重试")
                time.sleep(0.2)
                continue
            if not hand:
                break
            self._deck_tracker.update_hand(tuple(item.card for item in hand))
            board = self.backend.observe_board_state()
            if board is None:
                LOGGER.warning("[出牌] 场上状态截图失败，跳过本次观测并重试")
                time.sleep(0.2)
                continue
            state = BattleState(
                energy=energy,
                board_slots=max(0, 5 - board.ally_count),
                enemy_has_ward=bool(board.enemy_ward_indexes),
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
            if before is None:
                LOGGER.warning("[出牌] 动作前截图失败，本次不执行卡牌操作")
                time.sleep(0.2)
                continue
            if not self.backend.swipe(
                *selected.source, *self.layout.fixed_point("play_area"), 350
            ):
                raise SolutionError(f"使用卡牌失败: {selected.name}")
            if step.target.type == "enemy_leader":
                time.sleep(0.7)
                if not self.backend.tap(*self.layout.fixed_point("enemy_leader")):
                    raise SolutionError(f"选择敌方主战者失败: {selected.name}")
                self._hand_expanded = False
            changed = self.backend.wait_changed(
                before,
                self.layout.region("hand_and_board"),
                5_000,
                2.0,
                350,
            )
            if changed:
                # 成功打出任意卡牌后游戏都会重新收拢手牌；下一轮观测
                # 必须再次展开，不能沿用本地缓存状态。
                self._hand_expanded = False
                played_counts[step.card_id] = played_counts.get(step.card_id, 0) + 1
                self._deck_tracker.record_played(step.card_id)
                definition = self.catalog.cards.get(step.card_id)
                if definition is not None and definition.type == "follower":
                    played_followers.append(step.card_id)
                no_progress = 0
            else:
                no_progress += 1
                LOGGER.warning("出牌后未检测到盘面变化: %s", selected.name)
                if no_progress >= self.policy.profile.safety.no_progress_limit:
                    break
            time.sleep(0.6)

        return tuple(played_followers)

    def _try_evolve_existing_follower(self) -> bool:
        board = self.backend.observe_board_state()
        if board is None or board.ally_count <= 0:
            return False
        candidates = tuple(
            (index, None) for index in range(1, board.ally_count + 1)
        )
        return self._try_evolve_candidates(board.ally_count, candidates)

    def _try_evolve_played_followers(
        self, played_followers: tuple[str, ...]
    ) -> bool:
        if not played_followers:
            return False
        board = self.backend.observe_board_state()
        if board is None or board.ally_count <= 0:
            return False

        known_count = min(len(played_followers), board.ally_count)
        known_cards = played_followers[-known_count:]
        first_index = board.ally_count - known_count + 1
        candidates = [
            (first_index + offset, card_id)
            for offset, card_id in enumerate(known_cards)
        ]
        priority = {
            card_id: index
            for index, card_id in enumerate(
                self.policy.profile.evolution.card_priority
            )
        }
        candidates.sort(
            key=lambda item: (
                0 if "storm" in self.catalog.cards[item[1]].traits else 1,
                priority.get(item[1], len(priority)),
                item[0],
            )
        )
        return self._try_evolve_candidates(board.ally_count, tuple(candidates))

    def _try_evolve_candidates(
        self,
        ally_count: int,
        candidates: tuple[tuple[int, str | None], ...],
    ) -> bool:
        evolution_nodes = {
            "normal": EVOLVE_BUTTON,
            "super": SUPER_EVOLVE_BUTTON,
        }
        for index, card_id in candidates:
            point = self.layout.indexed_point("ally_followers", ally_count, index)
            if not self.backend.tap(*point):
                raise SolutionError("选择进化随从失败")
            time.sleep(0.35)
            for evolution_type in self.policy.profile.evolution.type_order:
                node = evolution_nodes[evolution_type]
                if self.backend.tap_recognition(node, 900, 150):
                    name = self.catalog.cards[card_id].name if card_id else f"随从 {index}"
                    LOGGER.info("[进化] %s（%s）", name, evolution_type)
                    time.sleep(1.0)
                    return True

        # 没有任何候选随从出现可用进化按钮，点击盘面空白关闭详情。
        if candidates:
            self.backend.tap(*self.layout.fixed_point("play_area"))
        return False

    def _observe_hand(self, energy: int) -> tuple[ObservedHandCard, ...] | None:
        for attempt in range(2):
            expanded = self._expand_hand_for_observation()
            if expanded is None:
                return ()
            time.sleep(0.4)
            frame = self.backend.capture_frame()
            if frame is None:
                return None
            detail = self.backend.recognize(BATTLE_HAND_NAMES, frame=frame)
            texts = recognition_results_to_hand_texts(
                detail.all_results if detail and detail.hit else ()
            )
            if self._hand_texts_are_expanded(texts):
                observed = parse_hand_texts(texts, self.catalog, energy)
                LOGGER.info(
                    "[手牌] %s",
                    ", ".join(
                        f"{item.name}({item.score:.2f})" for item in observed
                    )
                    or "已展开，但未匹配到已登记卡名",
                )
                return observed

            LOGGER.warning(
                "[手牌] 第 %d 次识别仍是折叠牌扇，重新点击展开",
                attempt + 1,
            )
            self._hand_expanded = False

        LOGGER.warning("[手牌] 连续两次未确认展开，本次按观测失败重试")
        return None

    @staticmethod
    def _hand_texts_are_expanded(texts: tuple[HandText, ...]) -> bool:
        """用卡名文本框位置区分展开手牌与右侧折叠牌扇。"""
        for text in texts:
            normalized = normalize_card_name(text.text)
            if (
                len(normalized) >= 2
                and not normalized.isdigit()
                and 560 <= text.y <= 610
                and text.height >= 14
            ):
                return True
        return False

    def _expand_hand_for_observation(self) -> bool | None:
        if self._hand_expanded:
            return True
        hand_count = self.backend.read_hand_count()
        if hand_count == 0:
            LOGGER.info("[手牌] 当前没有手牌，无需展开")
            return None
        point = self.layout.fixed_point("hand_expand")
        LOGGER.info(
            "[手牌] 点击实机校准位置展开手牌（数量=%s，坐标=%s）",
            hand_count if hand_count is not None else "未知",
            point,
        )
        if not self.backend.tap(*point):
            raise SolutionError("点击手牌展开失败")
        self._hand_expanded = True
        return True

    def _attack_phase(self) -> None:
        board = self.backend.observe_board_state()
        if board is None or board.ally_count <= 0:
            return
        remaining_index = board.ally_count
        observation_failures = 0
        # 从右向左尝试，可降低左侧随从死亡后其余序号变化的影响。
        while remaining_index > 0:
            board = self.backend.observe_board_state()
            if board is None:
                observation_failures += 1
                if observation_failures > self.policy.profile.safety.max_retries_per_action:
                    LOGGER.warning("[攻击] 连续截图失败，停止当前攻击阶段")
                    return
                time.sleep(0.2)
                continue
            observation_failures = 0
            if board.ally_count <= 0:
                return

            # 若刚才的攻击者被反击消灭，当前随从数量会变小；以实时数量
            # 修正源序号，避免仍按旧布局计算坐标。
            index = min(remaining_index, board.ally_count)
            if board.enemy_ward_indexes:
                target = self.layout.indexed_point(
                    "enemy_followers",
                    board.enemy_count,
                    board.enemy_ward_indexes[0],
                )
                target_name = f"敌方守护 {board.enemy_ward_indexes[0]}"
            else:
                target = self.layout.fixed_point("enemy_leader")
                target_name = "敌方主战者"
            source = self.layout.indexed_point(
                "ally_followers", board.ally_count, index
            )
            LOGGER.info("[攻击] 我方随从 %d -> %s", index, target_name)
            if not self.backend.swipe(*source, *target, 350):
                raise SolutionError("随从攻击操作失败")
            remaining_index = index - 1
            time.sleep(0.8)

    def _emit_tracker_events(self) -> None:
        name_map = {cid: defn.name for cid, defn in self.catalog.cards.items()}
        emit_deck_update(self._deck_tracker.remaining, name_map)
