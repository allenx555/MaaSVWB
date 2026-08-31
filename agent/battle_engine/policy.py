from __future__ import annotations

from dataclasses import dataclass, replace

from .models import (
    ActionPlan,
    BattleProfile,
    BattleState,
    CardCatalog,
    CardRule,
    ComboRule,
    ObservedCard,
    PlannedCardPlay,
    PlayCondition,
    Target,
)


@dataclass(frozen=True)
class _RankedPlan:
    plan: ActionPlan
    tie_order: int
    combo: bool


class BattlePolicy:
    """把已识别盘面映射为确定性的出牌计划，不执行任何设备操作。"""

    def __init__(self, profile: BattleProfile, catalog: CardCatalog) -> None:
        self.profile = profile
        self.catalog = catalog
        self.playable_ids = frozenset(item.card_id for item in profile.deck) | frozenset(
            card_id
            for card_id, definition in catalog.cards.items()
            if "generated" in definition.traits
        )

    def choose_play_plan(self, state: BattleState) -> ActionPlan | None:
        """选择当前最高优先级的完整组合或单张出牌计划。"""
        candidates: list[_RankedPlan] = []
        for index, combo in enumerate(self.profile.combos):
            plan = self._plan_combo(combo, state)
            if plan is not None:
                candidates.append(_RankedPlan(plan, index, True))

        for card in state.hand:
            plan = self._plan_single(card, state)
            if plan is not None:
                candidates.append(
                    _RankedPlan(plan, card.hand_index, False)
                )

        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                -item.plan.priority,
                0 if item.combo else 1,
                item.tie_order,
                tuple(step.card_id for step in item.plan.steps),
            )
        )
        return candidates[0].plan

    def _plan_single(
        self, observed: ObservedCard, state: BattleState
    ) -> ActionPlan | None:
        if not observed.playable or observed.card_id not in self.playable_ids:
            return None
        definition = self.catalog.cards.get(observed.card_id)
        if definition is None:
            return None
        rule = self.profile.cards.get(observed.card_id, CardRule())
        if not self._rule_available(rule, observed.card_id, state):
            return None
        cost = self._cost(observed)
        if cost > state.energy or self._needs_slot(definition.type) and state.board_slots < 1:
            return None
        target = rule.target or definition.default_target
        return ActionPlan(
            reason=f"card:{observed.card_id}@hand:{observed.hand_index}",
            priority=rule.play_priority,
            steps=(PlannedCardPlay(observed.card_id, target, observed.hand_index),),
        )

    def _plan_combo(self, combo: ComboRule, state: BattleState) -> ActionPlan | None:
        available = sorted(state.hand, key=lambda card: card.hand_index)
        remaining_energy = state.energy
        remaining_slots = state.board_slots
        local_uses = dict(state.played_counts)
        planned: list[PlannedCardPlay] = []

        for step in combo.steps:
            rule = self.profile.cards.get(step.card_id, CardRule())
            step_state = replace(
                state,
                energy=remaining_energy,
                board_slots=remaining_slots,
            )
            if not self._rule_available(
                rule, step.card_id, step_state, played_counts=local_uses
            ):
                return None
            match = next(
                (
                    card
                    for card in available
                    if card.card_id == step.card_id and card.playable
                ),
                None,
            )
            if match is None:
                return None
            definition = self.catalog.cards.get(step.card_id)
            if definition is None:
                return None
            cost = self._cost(match)
            needs_slot = self._needs_slot(definition.type)
            if cost > remaining_energy or needs_slot and remaining_slots < 1:
                return None
            remaining_energy -= cost
            if needs_slot:
                remaining_slots -= 1
            available.remove(match)
            local_uses[step.card_id] = local_uses.get(step.card_id, 0) + 1
            target = step.target or rule.target or definition.default_target
            planned.append(PlannedCardPlay(step.card_id, target, match.hand_index))

        return ActionPlan(
            reason=f"combo:{combo.id}",
            priority=combo.priority,
            steps=tuple(planned),
        )

    def _rule_available(
        self,
        rule: CardRule,
        card_id: str,
        state: BattleState,
        *,
        played_counts: dict[str, int] | None = None,
    ) -> bool:
        counts = played_counts if played_counts is not None else state.played_counts
        if not rule.enabled or counts.get(card_id, 0) >= rule.max_uses_per_turn:
            return False
        return self._condition_matches(rule.when, state)

    @staticmethod
    def _condition_matches(condition: PlayCondition, state: BattleState) -> bool:
        if state.energy < condition.minimum_energy:
            return False
        if state.board_slots < condition.minimum_board_slots:
            return False
        if condition.enemy_ward == "present" and not state.enemy_has_ward:
            return False
        if condition.enemy_ward == "absent" and state.enemy_has_ward:
            return False
        return True

    def _cost(self, observed: ObservedCard) -> int:
        if observed.observed_cost is not None:
            return observed.observed_cost
        return self.catalog.cards[observed.card_id].base_cost

    @staticmethod
    def _needs_slot(card_type: str) -> bool:
        return card_type in {"follower", "amulet"}
