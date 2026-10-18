from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from enum import Enum

from battle_engine.deck_tracker import DeckTracker
from battle_engine.models import ActionPlan, BattleState, CardCatalog, CardRule, Target
from battle_engine.observer import (
    HandText,
    ObservedHandCard,
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

from .backend import LeaderHealth, MaaBackend
from .hand_observer import HandObserver, hand_is_expanded
from .tracker_session import DeckTrackingSession


LOGGER = logging.getLogger("maasvwb.battle")


class BattleOutcome(str, Enum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TurnReady:
    current_energy: int
    maximum_energy: int


@dataclass
class _TurnSession:
    remaining_actions: int
    played_counts: dict[str, int] = field(default_factory=dict)
    evolved: bool = False
    outcome: BattleOutcome | None = None
    deferred_hand: bool = False


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
        self._validate_play_targets()
        self._deck_code = deck_code
        self._deck_tracker = self._make_tracker()
        self._tracker_session = DeckTrackingSession(self._deck_tracker, catalog, "dungeon")
        self._tracker_observer = HandObserver(backend, self._tracker_session.candidate_catalog())
        self._hand_expanded = False
        self._turn_followers: list[tuple[str | None, bool]] | None = None
        self._turn_session: _TurnSession | None = None
        self._turn_attack_flags: list[bool] | None = None
        self._last_hand_frame = None
        self._tracker_signature: tuple | None = None
        self._has_zero_cost_cards = any(catalog.cards[card_id].base_cost == 0 for card_id in policy.playable_ids)

    @staticmethod
    def _validate_play_target(target: Target) -> None:
        if target.type not in {"none", "enemy_leader", "ally_leader"}:
            raise SolutionError(
                f"当前自动战斗暂不支持出牌目标 {target.type!r}"
                f"（selector={target.selector!r}），请使用无需目标或主战者目标的策略"
            )

    def _validate_play_targets(self) -> None:
        # Validate effective targets, including defaults and combo overrides,
        # before the first mulligan, play or other device action.
        for card_id in sorted(self.policy.playable_ids):
            rule = self.policy.profile.cards.get(card_id, CardRule())
            if rule.enabled:
                self._validate_play_target(rule.target or self.catalog.cards[card_id].default_target)
        for combo in self.policy.profile.combos:
            for step in combo.steps:
                rule = self.policy.profile.cards.get(step.card_id, CardRule())
                self._validate_play_target(
                    step.target or rule.target or self.catalog.cards[step.card_id].default_target
                )

    def _make_tracker(self) -> DeckTracker:
        if self._deck_code:
            return DeckTracker.from_deck_code(self._deck_code, self.catalog)
        return DeckTracker.from_profile(self.policy.profile)

    def reset_tracker(self) -> None:
        """Reinitialise the deck tracker at the start of a new battle."""
        self._deck_tracker = self._make_tracker()
        self._tracker_signature = None
        self._tracker_session = DeckTrackingSession(self._deck_tracker, self.catalog, "dungeon")
        self._tracker_observer = HandObserver(self.backend, self._tracker_session.candidate_catalog())
        self._tracker_session.publish("waiting", "新对局：等待确认起手")

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
            outcome = self._execute_turn()
            if outcome is not None:
                return outcome
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

    def _execute_turn(self) -> BattleOutcome | None:
        self._hand_expanded = False
        self._turn_followers = None
        if self.policy.profile.attack.resume_play:
            return self._execute_interleaved_turn()
        if self.policy.profile.evolution.enabled and self.policy.profile.evolution.after_play:
            board = self.backend.observe_board_state()
            if board is not None:
                self._turn_followers = [(None, True) for _ in range(board.ally_count)]
            self._play_cards()
            self._try_evolve_after_play()
            self._turn_followers = None
            self._attack_phase()
            return
        evolved = False
        if self.policy.profile.evolution.enabled:
            evolved = self._try_evolve_existing_follower()

        played_followers = self._play_cards()
        if self.policy.profile.evolution.enabled and not evolved:
            self._try_evolve_played_followers(played_followers)

        self._attack_phase()
        return None

    def _current_outcome(self) -> BattleOutcome | None:
        if self._turn_session is not None and self._turn_session.outcome is not None:
            return self._turn_session.outcome
        frame = self.backend.capture_frame()
        outcome = self._recognize_outcome(frame) if frame is not None else None
        if self._turn_session is not None:
            self._turn_session.outcome = outcome
        return outcome

    def _execute_interleaved_turn(self) -> BattleOutcome | None:
        session = _TurnSession(self.policy.profile.safety.max_actions_per_turn)
        self._turn_session = session
        board = self.backend.observe_board_state()
        self._turn_followers = [(None, True) for _ in range(board.ally_count)] if board is not None else []
        self._turn_attack_flags = [True for _ in self._turn_followers]
        evolution_checked = False
        try:
            if self.policy.profile.evolution.enabled and not self.policy.profile.evolution.after_play:
                session.evolved = self._try_evolve_existing_follower()
                if session.evolved:
                    session.remaining_actions -= 1
            while session.remaining_actions > 0:
                if self.backend.is_stopping():
                    raise SolutionError("战斗已停止")
                outcome = self._current_outcome()
                if outcome is not None:
                    return outcome
                played = self._play_cards()
                outcome = self._current_outcome()
                if outcome is not None:
                    return outcome
                if session.remaining_actions <= 0:
                    break
                if self.policy.profile.evolution.enabled and not session.evolved and (played or not evolution_checked):
                    session.evolved = self._try_evolve_after_play()
                    evolution_checked = True
                    if session.evolved:
                        session.remaining_actions -= 1
                if session.remaining_actions <= 0 or not self._attack_phase(one_action=True):
                    break
            outcome = self._current_outcome()
            if outcome is None and session.deferred_hand and not self.backend.is_stopping():
                # At zero energy and without registered zero-cost candidates,
                # defer tracking-only expansion until attacks have finished.
                self._sync_tracker(self._observe_hand(0))
            return outcome
        finally:
            self._turn_session = None
            self._turn_attack_flags = None
            self._turn_followers = None

    def _play_cards(self) -> tuple[str, ...]:
        session = self._turn_session
        played_counts: dict[str, int] = session.played_counts if session is not None else {}
        played_followers: list[str] = []
        pending_plan: ActionPlan | None = None
        no_progress = 0
        for _ in range(self.policy.profile.safety.max_actions_per_turn):
            if session is not None and session.remaining_actions <= 0:
                break
            energy_pair = self.backend.read_energy_points()
            if energy_pair is None:
                self._tracker_signature = None
                self._tracker_session.invalidate("能量识别失败，保留上次记牌结果")
                break
            energy, _maximum = energy_pair
            if session is not None and energy == 0 and not self._has_zero_cost_cards:
                session.deferred_hand = True
                break
            hand = self._observe_hand(energy)
            if session is not None:
                session.deferred_hand = False
            self._sync_tracker(hand)
            if hand is None:
                LOGGER.warning("[出牌] 截图失败，跳过本次观测并重试")
                time.sleep(0.2)
                continue
            if not hand:
                if pending_plan is not None:
                    raise SolutionError("组合剩余步骤无法执行：未识别到所需手牌，已停止")
                break
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
                remaining_actions=session.remaining_actions if session is not None else None,
            )
            if self.policy.needs_health(state):
                observed_health = self.backend.read_leader_health(hand_expanded=self._hand_expanded)
                if isinstance(observed_health, LeaderHealth):
                    state = replace(state, ally_health=observed_health.ally, enemy_health=observed_health.enemy)
            if pending_plan is not None:
                plan = self.policy.refresh_play_plan(pending_plan, state)
                if plan is None:
                    raise SolutionError("组合剩余步骤无法执行：手牌、能量或盘面条件已变化，已停止")
            else:
                plan = self.policy.choose_play_plan(state)
            if plan is None or not plan.steps:
                break
            step = plan.steps[0]
            if len(plan.steps) > 1:
                pending_plan = plan
            self._validate_play_target(step.target)
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
            if session is not None:
                session.remaining_actions -= 1
            if step.target.type in {"enemy_leader", "ally_leader"}:
                time.sleep(0.7)
                if not self.backend.tap(*self.layout.fixed_point(step.target.type)):
                    raise SolutionError(f"选择目标 {step.target.type} 失败: {selected.name}")
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
                self._tracker_session.record_played(step.card_id)
                self._tracker_signature = None
                definition = self.catalog.cards.get(step.card_id)
                if definition is not None and definition.type == "follower":
                    played_followers.append(step.card_id)
                no_progress = 0
                pending_plan = replace(plan, steps=plan.steps[1:]) if len(plan.steps) > 1 else None
            else:
                no_progress += 1
                LOGGER.warning("出牌后未检测到盘面变化: %s", selected.name)
                if no_progress >= self.policy.profile.safety.no_progress_limit:
                    break
            time.sleep(0.6)
            if changed and self._turn_followers is not None:
                self._record_follower_positions(step.card_id, board.ally_count)
            if session is not None and self._current_outcome() is not None:
                # Settlement is an observed result, not inferred from predicted
                # lethal damage. The caller propagates the actual outcome.
                pending_plan = None
                break

        if pending_plan is not None:
            raise SolutionError("组合尚未完成：观测失败或达到安全限制，已停止")
        return tuple(played_followers)

    def _sync_tracker(self, hand: tuple[ObservedHandCard, ...] | None) -> None:
        if hand is None:
            self._tracker_signature = None
            self._tracker_session.invalidate("手牌观测失败，保留上次记牌结果")
            return
        frame = self._last_hand_frame
        if frame is None:
            frame = self.backend.capture_frame()
        if frame is None:
            self._tracker_signature = None
            return
        deck_count = self.backend.read_deck_count(frame=frame)
        deck_count = deck_count if isinstance(deck_count, int) else None
        hand_signature = (tuple(item.card.card_id for item in hand), deck_count)
        signature = (*hand_signature, self._tracker_session.sequence)
        if signature == self._tracker_signature:
            return
        # Only cache a hand that the independent strict observer has confirmed
        # twice. Deck total changes also force a new confirmation, even if card
        # names/count stay the same. Never use this cache for play decisions.
        confirmed = False
        for sample in range(2):
            if sample:
                time.sleep(0.15)
            observed = self._tracker_observer.observe(frame if sample == 0 else self.backend.capture_frame())
            confirmed = self._tracker_session.observe(observed)
        strict_signature = (tuple(item.card.card_id for item in observed.cards), observed.deck_count)
        self._tracker_signature = (*hand_signature, self._tracker_session.sequence) if confirmed and hand_signature == strict_signature else None

    def _record_follower_positions(self, card_id: str, before_count: int) -> None:
        """Bind identities only when the observed addition matches the card's slot model."""
        board = self.backend.observe_board_state()
        if board is None:
            self._turn_followers = []
            if self._turn_attack_flags is not None:
                self._turn_attack_flags = []
            return
        known = self._turn_followers or []
        definition = self.catalog.cards[card_id]
        added = board.ally_count - before_count
        if len(known) == before_count:
            if definition.type == "follower" and 1 <= added <= 1 + definition.effects.summon_count:
                self._turn_followers = known + [(card_id, False)] + [(None, False)] * (added - 1)
                if self._turn_attack_flags is not None:
                    if len(self._turn_attack_flags) == before_count:
                        self._turn_attack_flags.extend([True] * added)
                    else:
                        self._turn_attack_flags = [False] * before_count + [True] * added
                return
            if definition.type != "follower" and added == 0:
                return
        # Deaths, unexpected summons or uncertain observations invalidate index
        # identities; do not guess that the last N bodies are the N played cards.
        self._turn_followers = [(None, False) for _ in range(board.ally_count)]
        if self._turn_attack_flags is not None:
            self._turn_attack_flags = [False] * board.ally_count

    def _try_evolve_after_play(self) -> bool:
        board = self.backend.observe_board_state()
        if board is None or board.ally_count <= 0:
            return False
        known = self._turn_followers or []
        if len(known) != board.ally_count:
            known = [(None, False)] * board.ally_count
        priority = {card_id: index for index, card_id in enumerate(self.policy.profile.evolution.card_priority)}

        def rank(item: tuple[int, tuple[str | None, bool]]) -> tuple[int, int, int]:
            index, (card_id, existing) = item
            storm = card_id is not None and "storm" in self.catalog.cards[card_id].traits
            # Readiness is a preference based on known unconditional storm or a
            # surviving turn-start body, not a claim to detect freezes/exhaustion.
            readiness = (0 if storm else 1 if existing else 2) if self.policy.profile.evolution.prefer_can_attack else 0
            return readiness, priority.get(card_id or "", len(priority)), index

        ordered = sorted(enumerate(known, 1), key=rank)
        return self._try_evolve_candidates(board.ally_count, tuple(
            (index, card_id) for index, (card_id, _existing) in ordered
        ))

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
        if any(self.catalog.cards[card_id].effects.summon_count for card_id in played_followers):
            # Legacy timing cannot reconstruct identities from played-card count
            # when any of those cards can add multiple bodies.
            return self._try_evolve_after_play()
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
                0 if self.policy.profile.evolution.prefer_can_attack and "storm" in self.catalog.cards[item[1]].traits else 1,
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
        self._last_hand_frame = None
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
                self._last_hand_frame = frame
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
        return hand_is_expanded(texts)

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

    def _attack_phase(self, *, one_action: bool = False) -> bool:
        board = self.backend.observe_board_state()
        if board is None or board.ally_count <= 0:
            return False
        if self._turn_attack_flags is None:
            pending = set(range(1, board.ally_count + 1))
        elif len(self._turn_attack_flags) == board.ally_count:
            pending = {index for index, ready in enumerate(self._turn_attack_flags, 1) if ready}
        else:
            # Losing the index mapping must not allow already-tried bodies to
            # attack again merely because a new phase started.
            self._turn_attack_flags = [False] * board.ally_count
            return False
        performed = False
        previous_count = board.ally_count
        previous_index: int | None = None
        observation_failures = 0
        policy = self.policy.profile.attack
        while pending:
            board = self.backend.observe_board_state(
                include_attacks=policy.attacker_order != "left_to_right",
                attack_indexes=tuple(sorted(pending)),
            )
            if board is None:
                observation_failures += 1
                if observation_failures > self.policy.profile.safety.max_retries_per_action:
                    LOGGER.warning("[攻击] 连续截图失败，停止当前攻击阶段")
                    return performed
                time.sleep(0.2)
                continue
            observation_failures = 0
            if board.ally_count <= 0:
                return performed
            if board.ally_count != previous_count:
                if board.ally_count == previous_count - 1 and previous_index is not None:
                    pending = {index - int(index > previous_index) for index in pending}
                else:
                    LOGGER.warning("[攻击] 随从数量异常变化，停止当前攻击阶段以避免重复操作")
                    return performed
            pending = {index for index in pending if index <= board.ally_count}
            if not pending:
                return performed
            attacks = board.ally_attacks
            if policy.attacker_order == "left_to_right":
                index = min(pending)
            elif len(attacks) == board.ally_count and all(attacks[index - 1] is not None for index in pending):
                direction = -1 if policy.attacker_order == "highest_attack_first" else 1
                index = min(pending, key=lambda index: (direction * int(attacks[index - 1] or 0), index))
            else:
                # Missing/ambiguous digits must not be interpreted as zero attack.
                index = max(pending)
                LOGGER.debug("[攻击] 攻击力识别不完整，回退从右向左尝试")
            if board.enemy_ward_indexes and policy.clear_ward:
                target = self.layout.indexed_point(
                    "enemy_followers",
                    board.enemy_count,
                    board.enemy_ward_indexes[0],
                )
                target_name = f"敌方守护 {board.enemy_ward_indexes[0]}"
            elif policy.otherwise == "enemy_follower" and board.enemy_count:
                target = self.layout.indexed_point("enemy_followers", board.enemy_count, 1)
                target_name = "敌方随从 1"
            elif board.enemy_ward_indexes:
                # The profile explicitly declines clearing wards; a leader
                # attack would be blocked, so keep the follower unspent.
                return performed
            else:
                target = self.layout.fixed_point("enemy_leader")
                target_name = "敌方主战者"
            source = self.layout.indexed_point(
                "ally_followers", board.ally_count, index
            )
            LOGGER.info("[攻击] 我方随从 %d -> %s", index, target_name)
            if not self.backend.swipe(*source, *target, 350):
                raise SolutionError("随从攻击操作失败")
            performed = True
            self._hand_expanded = False
            if self._turn_session is not None:
                self._turn_session.remaining_actions -= 1
            pending.remove(index)
            previous_index = index
            previous_count = board.ally_count
            time.sleep(0.8)
            if one_action:
                self._update_after_attack(board.ally_count, index, pending)
                return True
        return performed

    def _update_after_attack(self, before_count: int, index: int, pending: set[int]) -> None:
        after = self.backend.observe_board_state()
        if after is None:
            self._turn_followers = []
            self._turn_attack_flags = []
            return
        known = self._turn_followers or []
        flags = [position in pending for position in range(1, before_count + 1)]
        if len(known) == before_count and after.ally_count in {before_count, before_count - 1}:
            if after.ally_count < before_count:
                del known[index - 1]
                del flags[index - 1]
            self._turn_followers = known
            self._turn_attack_flags = flags
        else:
            self._turn_followers = [(None, False) for _ in range(after.ally_count)]
            self._turn_attack_flags = [False] * after.ally_count
