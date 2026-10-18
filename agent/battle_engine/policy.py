from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from .models import (
    ActionPlan,
    BattleProfile,
    BattleState,
    CardCatalog,
    CardEffects,
    CardRule,
    ComboRule,
    ComboStep,
    ObservedCard,
    PlannedCardPlay,
    PlayCondition,
    Target,
)

from .strategies import AggroNightmareStrategy, GenericStrategy


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
        self.strategy = AggroNightmareStrategy() if profile.strategy == "aggro_nightmare" else GenericStrategy()
        self.playable_ids = frozenset(item.card_id for item in profile.deck) | frozenset(
            card_id
            for card_id, definition in catalog.cards.items()
            if "generated" in definition.traits
        )

    def choose_play_plan(self, state: BattleState) -> ActionPlan | None:
        """按策略选择完整组合或单张出牌计划；费用规划只执行第一张。"""
        lethal = self.choose_lethal_plan(state)
        if lethal is not None:
            return lethal
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
        if self.profile.play_mode == "maximize_energy":
            optimal_indexes = self._energy_optimal_first_cards(state)
            candidates = [
                item for item in candidates
                if item.combo or item.plan.steps[0].hand_index in optimal_indexes
            ]
        candidates.sort(
            key=lambda item: (
                -item.plan.priority,
                0 if item.combo else 1,
                item.tie_order,
                tuple(step.card_id for step in item.plan.steps),
            )
        )
        return candidates[0].plan

    def needs_health(self, state: BattleState) -> bool:
        """Only request HP for an otherwise usable damage card in this hand."""
        for card in state.hand:
            if not card.playable or card.card_id not in self.playable_ids:
                continue
            definition = self.catalog.cards[card.card_id]
            effects = definition.effects
            rule = self.profile.cards.get(card.card_id, CardRule())
            if not (effects.leader_damage or effects.self_damage):
                continue
            if self._cost(card) > state.energy or self._needs_slot(definition.type) and not state.board_slots:
                continue
            if state.remaining_actions != 0 and self._rule_available(rule, card.card_id, state):
                return True
        return False

    @staticmethod
    def _damage_after(effects: CardEffects, state: BattleState, target: Target) -> tuple[int | None, int | None]:
        own, enemy = state.ally_health, state.enemy_health
        if target.type not in {"none", "enemy_leader"}:
            return own, enemy
        own_hit, enemy_hit = effects.self_damage, effects.leader_damage
        if effects.damage_lowest_health:
            if own is None or enemy is None:
                return own, enemy
            enemy_hit = effects.leader_damage if enemy <= own else 0
            own_hit += effects.leader_damage if own <= enemy else 0
        return own - own_hit if own is not None else None, enemy - enemy_hit if enemy is not None else None

    def _damage_safe(self, card_id: str, state: BattleState, target: Target) -> bool:
        effects = self.catalog.cards[card_id].effects
        if effects.damage_lowest_health and (
            state.ally_health is None or state.enemy_health is None
        ):
            return False
        own, _enemy = self._damage_after(effects, state, target)
        return own is None or own > 0

    def choose_lethal_plan(self, state: BattleState) -> ActionPlan | None:
        """Find an affordable, non-suicidal direct-damage route; replan after one play.

        No follower readiness, storm, evolution, draws or ward trades are assumed.
        Leader damage comes from catalog effects, not a prediction of prevention effects.
        """
        if state.ally_health is None or state.enemy_health is None:
            return None
        cards = tuple(card for card in state.hand if card.playable and card.card_id in self.playable_ids
                      and self.catalog.cards[card.card_id].effects.leader_damage > 0)
        if not cards or len(cards) > 12 or sum(self.catalog.cards[card.card_id].effects.leader_damage for card in cards) < state.enemy_health:
            return None

        @lru_cache(maxsize=None)
        def search(mask: int, own: int, enemy: int, slots: int) -> tuple[int, ...] | None:
            if enemy <= 0:
                return ()
            if mask.bit_count() >= min(self.profile.safety.max_actions_per_turn,
                                       state.remaining_actions if state.remaining_actions is not None else 100):
                return None
            used = [card for index, card in enumerate(cards) if mask & (1 << index)]
            counts = dict(state.played_counts)
            for card in used:
                counts[card.card_id] = counts.get(card.card_id, 0) + 1
            current = replace(state, energy=state.energy - sum(self._cost(card) for card in used),
                              board_slots=slots, played_counts=counts, ally_health=own, enemy_health=enemy)
            routes: list[tuple[int, ...]] = []
            for index, card in enumerate(cards):
                if mask & (1 << index):
                    continue
                plan = self._plan_single(card, current)
                if plan is None:
                    continue
                effects = self.catalog.cards[card.card_id].effects
                next_own, next_enemy = self._damage_after(effects, current, plan.steps[0].target)
                if next_own is None or next_enemy is None or next_own <= 0 or next_enemy >= enemy:
                    continue
                occupied = int(self._needs_slot(self.catalog.cards[card.card_id].type)) + effects.summon_count
                rest = search(mask | (1 << index), next_own, next_enemy, max(0, slots - occupied))
                if rest is not None:
                    routes.append((index,) + rest)
            return min(routes, key=lambda route: (
                sum(self._cost(cards[index]) for index in route), len(route),
                tuple((-self.profile.cards.get(cards[index].card_id, CardRule()).play_priority,
                       cards[index].hand_index) for index in route),
            ), default=None)

        route = search(0, state.ally_health, state.enemy_health, state.board_slots)
        if not route:
            return None
        first = self._plan_single(cards[route[0]], state)
        assert first is not None
        return replace(first, reason="lethal:direct_damage", priority=1000)

    def _energy_optimal_first_cards(self, state: BattleState) -> frozenset[int]:
        """Compare legal routes through this hand; execute only their first card.

        Draws and discounts are not predicted. Summons use a configured upper
        bound; the runner observes the actual result after each individual play.
        Explicit combos retain their existing priority/atomic execution contract.
        """
        cards = tuple(
            card for card in state.hand
            if card.playable and card.card_id in self.playable_ids
        )
        # A real hand has at most nine cards. Bound subset search even for noisy
        # OCR/custom callers; oversized observations keep the priority fallback.
        if len(cards) > 12:
            return frozenset(card.hand_index for card in cards)
        costs = tuple(self._cost(card) for card in cards)
        base_slots = tuple(
            int(self._needs_slot(self.catalog.cards[card.card_id].type))
            for card in cards
        )
        rules = tuple(self.profile.cards.get(card.card_id, CardRule()) for card in cards)
        effects = tuple(self.catalog.cards[card.card_id].effects for card in cards)

        def simulated_state(mask: int, board_slots: int, own: int | None, enemy: int | None) -> BattleState:
            energy = state.energy
            counts = dict(state.played_counts)
            for index, card in enumerate(cards):
                if mask & (1 << index):
                    energy -= costs[index]
                    counts[card.card_id] = counts.get(card.card_id, 0) + 1
            return replace(state, energy=energy, board_slots=board_slots, played_counts=counts,
                           ally_health=own, enemy_health=enemy)

        @lru_cache(maxsize=None)
        def best_route(mask: int, board_slots: int, added_followers: int, own: int | None, enemy: int | None) -> tuple[int, int]:
            if mask.bit_count() >= min(self.profile.safety.max_actions_per_turn,
                                       state.remaining_actions if state.remaining_actions is not None else 100):
                return (0, 0)
            current = simulated_state(mask, board_slots, own, enemy)
            return max((
                route_score(index, mask, board_slots, added_followers, own, enemy)
                for index, card in enumerate(cards)
                if not mask & (1 << index) and self._plan_single(card, current) is not None
            ), default=(0, 0))

        def route_score(index: int, mask: int, board_slots: int, added_followers: int, own: int | None, enemy: int | None) -> tuple[int, int]:
            next_slots = max(0, board_slots - base_slots[index] - effects[index].summon_count)
            added = board_slots - next_slots
            if self.catalog.cards[cards[index].card_id].type == "amulet":
                added -= 1
            current = simulated_state(mask, board_slots, own, enemy)
            target = rules[index].target or self.catalog.cards[cards[index].card_id].default_target
            own, enemy = self._damage_after(effects[index], current, target)
            spent, setup = (0, 0) if enemy is not None and enemy <= 0 else best_route(
                mask | (1 << index), next_slots, added_followers + added, own, enemy,
            )
            # The bonus only breaks equal-energy routes. Counting occupied slots
            # added by this route avoids assuming identities of existing cards.
            setup += self.strategy.setup_bonus(cards[index].card_id, added_followers)
            return costs[index] + spent, setup

        optimum = best_route(0, state.board_slots, 0, state.ally_health, state.enemy_health)
        return frozenset(
            card.hand_index
            for index, card in enumerate(cards)
            if self._plan_single(card, state) is not None
            and route_score(index, 0, state.board_slots, 0, state.ally_health, state.enemy_health) == optimum
        )

    def choose_mulligan_replacements(
        self, hand: tuple[ObservedCard, ...]
    ) -> tuple[int, ...]:
        """返回应交换的起手序号；未识别卡牌不会出现在 hand 中，因而会安全保留。"""
        if not self.profile.mulligan.enabled:
            return ()
        keep = frozenset(self.profile.mulligan.keep)
        if self.profile.mulligan.keep_all_if_any_kept and any(
            card.card_id in keep for card in hand
        ):
            return ()
        return tuple(card.hand_index for card in hand if card.card_id not in keep)

    def _plan_single(
        self, observed: ObservedCard, state: BattleState
    ) -> ActionPlan | None:
        if state.remaining_actions == 0 or not observed.playable or observed.card_id not in self.playable_ids:
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
        if not self.strategy.allow_card(observed.card_id, state) or not self._damage_safe(observed.card_id, state, target):
            return None
        return ActionPlan(
            reason=f"card:{observed.card_id}@hand:{observed.hand_index}",
            priority=rule.play_priority,
            steps=(PlannedCardPlay(observed.card_id, target, observed.hand_index),),
        )

    def _plan_combo(self, combo: ComboRule, state: BattleState) -> ActionPlan | None:
        planned = self._plan_steps(combo.steps, state)
        if planned is None:
            return None
        return ActionPlan(
            reason=f"combo:{combo.id}", priority=combo.priority, steps=planned
        )

    def refresh_play_plan(self, plan: ActionPlan, state: BattleState) -> ActionPlan | None:
        """重新校验待执行步骤并绑定实时手牌序号，不重新竞争优先级。"""
        steps = tuple(ComboStep(step.card_id, step.target) for step in plan.steps)
        planned = self._plan_steps(steps, state)
        return replace(plan, steps=planned) if planned is not None else None

    def _plan_steps(
        self, steps: tuple[ComboStep, ...], state: BattleState
    ) -> tuple[PlannedCardPlay, ...] | None:
        available = sorted(state.hand, key=lambda card: card.hand_index)
        remaining_energy = state.energy
        remaining_slots = state.board_slots
        own, enemy = state.ally_health, state.enemy_health
        if state.remaining_actions is not None and len(steps) > state.remaining_actions:
            return None
        local_uses = dict(state.played_counts)
        planned: list[PlannedCardPlay] = []

        for index, step in enumerate(steps):
            rule = self.profile.cards.get(step.card_id, CardRule())
            step_state = replace(
                state,
                energy=remaining_energy,
                board_slots=remaining_slots,
                ally_health=own,
                enemy_health=enemy,
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
            remaining_slots = max(0, remaining_slots - int(needs_slot) - definition.effects.summon_count)
            available.remove(match)
            local_uses[step.card_id] = local_uses.get(step.card_id, 0) + 1
            target = step.target or rule.target or definition.default_target
            if not self.strategy.allow_card(step.card_id, step_state) or not self._damage_safe(step.card_id, step_state, target):
                return None
            own, enemy = self._damage_after(definition.effects, step_state, target)
            if enemy is not None and enemy <= 0 and index < len(steps) - 1:
                return None
            planned.append(PlannedCardPlay(step.card_id, target, match.hand_index))

        return tuple(planned)

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
