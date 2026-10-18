from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.repository import (  # noqa: E402
    BattleProfileRepository,
    CardCatalogRepository,
)
from battle_engine.models import BattleState, ObservedCard  # noqa: E402
from battle_engine.policy import BattlePolicy  # noqa: E402


class AggroNightmareProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        cls.profile = BattleProfileRepository.for_project(
            PROJECT_ROOT, cls.catalog
        ).load("aggro_nightmare")

    def test_mulligan_keeps_entire_hand_when_it_contains_a_one_cost_card(self) -> None:
        expected = {
            entry.card_id
            for entry in self.profile.deck
            if self.catalog.cards[entry.card_id].base_cost == 1
        }

        self.assertTrue(self.profile.mulligan.enabled)
        self.assertEqual(set(self.profile.mulligan.keep), expected)
        self.assertTrue(self.profile.mulligan.keep_all_if_any_kept)

    def test_base_priorities_keep_eyethela_high_and_brush_monster_low(self) -> None:
        priorities = {
            card_id: rule.play_priority
            for card_id, rule in self.profile.cards.items()
        }

        # 10253120 = 夜曲将军·艾瑟拉（最高优先级随从）
        self.assertEqual(priorities["10253120"], max(priorities.values()))
        self.assertEqual(priorities["10501110"], min(priorities.values()))

    def test_followers_except_brush_monster_precede_spells(self) -> None:
        follower_priorities = [
            self.profile.cards[card_id].play_priority
            for card_id, definition in self.catalog.cards.items()
            if card_id in self.profile.cards
            if definition.type == "follower" and card_id != "10501110"
        ]
        spell_priorities = [
            self.profile.cards[card_id].play_priority
            for card_id, definition in self.catalog.cards.items()
            if card_id in self.profile.cards
            if definition.type == "spell"
        ]

        self.assertGreater(min(follower_priorities), max(spell_priorities))

    def test_higher_cost_followers_are_preferred_within_same_category(self) -> None:
        priorities_by_cost: dict[int, set[int]] = {}
        for card_id, definition in self.catalog.cards.items():
            if card_id not in self.profile.cards:
                continue
            if definition.type != "follower" or card_id == "10501110":
                continue
            priorities_by_cost.setdefault(definition.base_cost, set()).add(
                self.profile.cards[card_id].play_priority
            )

        ordered = sorted(priorities_by_cost)
        for lower, higher in zip(ordered, ordered[1:]):
            self.assertLess(
                max(priorities_by_cost[lower]),
                min(priorities_by_cost[higher]),
            )

    def test_evolution_is_enabled_and_prioritizes_storm_followers(self) -> None:
        self.assertTrue(self.profile.evolution.enabled)
        self.assertEqual(self.profile.evolution.type_order, ("normal",))
        self.assertTrue(self.profile.evolution.after_play)
        self.assertEqual(
            self.profile.evolution.card_priority,
            ("90051130", "10253120"),
        )
        for card_id in self.profile.evolution.card_priority:
            self.assertIn("storm", self.catalog.cards[card_id].traits)
        self.assertNotIn("storm", self.catalog.cards["10051130"].traits)

    def choose(self, energy: int, ids: tuple[str, ...], slots: int = 5) -> str:
        state = BattleState(
            energy=energy,
            board_slots=slots,
            enemy_has_ward=False,
            hand=tuple(ObservedCard(card_id, index, True) for index, card_id in enumerate(ids, 1)),
        )
        plan = BattlePolicy(self.profile, self.catalog).choose_play_plan(state)
        assert plan is not None
        # Optimization must not turn a speculative route into a locked combo.
        self.assertEqual(len(plan.steps), 1)
        return plan.steps[0].card_id

    def test_five_energy_chooses_three_plus_two_instead_of_four(self) -> None:
        self.assertEqual(self.profile.play_mode, "maximize_energy")
        self.assertEqual(
            self.choose(5, ("10253120", "10151110", "10601110")),
            "10151110",
        )

    def test_four_energy_chooses_two_plus_two_instead_of_three(self) -> None:
        self.assertEqual(
            self.choose(4, ("10151110", "10601110", "10851130")),
            "10601110",
        )

    def test_full_energy_tie_keeps_eyethela_priority(self) -> None:
        self.assertEqual(
            self.choose(4, ("10601110", "10851130", "10253120")),
            "10253120",
        )

    def test_one_board_slot_changes_best_route(self) -> None:
        self.assertEqual(
            self.choose(5, ("10151110", "10601110", "10253120"), slots=1),
            "10253120",
        )

    def test_spell_can_fill_energy_without_using_another_board_slot(self) -> None:
        self.assertEqual(
            self.choose(5, ("10253120", "10151110", "10153310"), slots=1),
            "10151110",
        )
        self.assertEqual(self.choose(2, ("10601110", "10153310"), slots=0), "10153310")

    def test_brush_monster_fills_remaining_energy_but_is_played_last(self) -> None:
        self.assertEqual(
            self.choose(4, ("10501110", "10151110", "10601110")),
            "10151110",
        )
        self.assertEqual(self.choose(1, ("10501110",)), "10501110")

    def test_priority_mode_retains_previous_greedy_behavior(self) -> None:
        profile = replace(self.profile, play_mode="priority")
        state = BattleState(5, 5, False, (
            ObservedCard("10253120", 1, True),
            ObservedCard("10151110", 2, True),
            ObservedCard("10601110", 3, True),
        ))
        plan = BattlePolicy(profile, self.catalog).choose_play_plan(state)
        assert plan is not None
        self.assertEqual(plan.steps[0].card_id, "10253120")

    def test_eyethela_follows_one_cost_follower_even_with_brush_priority(self) -> None:
        for first in ("10251120", "10501110"):
            with self.subTest(first=first):
                self.assertEqual(self.choose(5, ("10253120", first)), first)

    def test_eyethela_follows_summons_when_all_bodies_fit(self) -> None:
        self.assertEqual(self.choose(6, ("10253120", "10851130"), slots=4), "10851130")
        self.assertEqual(self.choose(7, ("10253120", "10151110"), slots=3), "10151110")

    def test_eyethela_is_reserved_before_summons_fill_the_board(self) -> None:
        self.assertEqual(self.choose(6, ("10851130", "10253120"), slots=3), "10253120")
        self.assertEqual(self.choose(7, ("10151110", "10253120"), slots=2), "10253120")
        self.assertEqual(self.choose(5, ("10251120", "10253120"), slots=1), "10253120")

    def test_eral_precedes_bat_summoner_and_play_remains_legal_with_one_slot(self) -> None:
        self.assertEqual(self.choose(5, ("10851130", "10151110")), "10151110")
        self.assertEqual(self.choose(3, ("10151110",), slots=1), "10151110")

    def lethal_state(self, energy, ids, *, own: int | None = 10, enemy: int | None = 3, slots=5, **kwargs):
        return BattleState(energy, slots, False, tuple(
            ObservedCard(card_id, index, True) for index, card_id in enumerate(ids, 1)
        ), ally_health=own, enemy_health=enemy, **kwargs)

    def test_direct_lethal_overrides_four_cost_follower_and_energy_planning(self) -> None:
        state = self.lethal_state(4, ("10253120", "10153310"))
        plan = BattlePolicy(self.profile, self.catalog).choose_play_plan(state)
        assert plan is not None
        self.assertEqual(plan.reason, "lethal:direct_damage")
        self.assertEqual(plan.steps[0].card_id, "10153310")
        self.assertEqual(len(plan.steps), 1)

    def test_combined_burn_is_replanned_after_each_card(self) -> None:
        policy = BattlePolicy(self.profile, self.catalog)
        state = self.lethal_state(4, ("10552310", "10153310"), enemy=6)
        plan = policy.choose_lethal_plan(state)
        assert plan is not None
        self.assertEqual(plan.steps[0].card_id, "10153310")
        next_state = self.lethal_state(2, ("10552310",), own=8, enemy=3)
        self.assertIsNotNone(policy.choose_lethal_plan(next_state))
        # Prevention/healing changing the observed result must cancel the claim.
        self.assertIsNone(policy.choose_lethal_plan(replace(next_state, enemy_health=8)))

    def test_lethal_includes_captain_but_respects_full_board(self) -> None:
        policy = BattlePolicy(self.profile, self.catalog)
        state = self.lethal_state(4, ("10951110", "10153310"), own=6, enemy=5)
        self.assertIsNotNone(policy.choose_lethal_plan(state))
        self.assertIsNone(policy.choose_lethal_plan(replace(state, board_slots=0)))
        spell = self.lethal_state(2, ("10153310",), slots=0)
        self.assertIsNotNone(policy.choose_lethal_plan(replace(spell, enemy_has_ward=True)))

    def test_lowest_health_burn_never_targets_only_self_or_causes_tied_death(self) -> None:
        policy = BattlePolicy(self.profile, self.catalog)
        for own, enemy in ((2, 3), (3, 3)):
            state = self.lethal_state(2, ("10552310",), own=own, enemy=enemy)
            self.assertIsNone(policy.choose_play_plan(state))
        self.assertIsNotNone(policy.choose_lethal_plan(self.lethal_state(2, ("10552310",), own=4)))

    def test_self_damage_is_checked_for_the_whole_route(self) -> None:
        policy = BattlePolicy(self.profile, self.catalog)
        state = self.lethal_state(4, ("10153310", "10153310"), own=4, enemy=6)
        self.assertIsNone(policy.choose_lethal_plan(state))
        self.assertIsNotNone(policy.choose_lethal_plan(replace(state, ally_health=5)))
        self.assertIsNone(policy.choose_play_plan(self.lethal_state(2, ("10153310",), own=2)))

    def test_missing_health_disables_lethal_and_conditional_burn(self) -> None:
        policy = BattlePolicy(self.profile, self.catalog)
        state = self.lethal_state(2, ("10552310",), own=None)
        self.assertIsNone(policy.choose_lethal_plan(state))
        self.assertIsNone(policy.choose_play_plan(state))

    def test_lethal_respects_usage_limits_action_budget_and_unknown_storm(self) -> None:
        policy = BattlePolicy(self.profile, self.catalog)
        state = self.lethal_state(4, ("10153310", "10153310"), enemy=6)
        self.assertIsNone(policy.choose_lethal_plan(replace(state, remaining_actions=1)))
        self.assertIsNone(policy.choose_lethal_plan(replace(state, played_counts={"10153310": 2})))
        self.assertIsNone(policy.choose_lethal_plan(self.lethal_state(4, ("10253120", "10051130"))))

    def test_generic_strategy_does_not_inherit_eyethela_order_or_anti_self_damage_preference(self) -> None:
        generic = BattlePolicy(replace(self.profile, strategy="generic"), self.catalog)
        state = self.lethal_state(5, ("10253120", "10251120"), own=20, enemy=20)
        plan = generic.choose_play_plan(state)
        assert plan is not None
        self.assertEqual(plan.steps[0].card_id, "10253120")
        self_only = self.lethal_state(2, ("10552310",), own=10, enemy=20)
        self.assertIsNotNone(generic.choose_play_plan(self_only))
        self.assertIsNone(BattlePolicy(self.profile, self.catalog).choose_play_plan(self_only))

    def test_health_is_requested_only_for_current_usable_damage_candidates(self) -> None:
        policy = BattlePolicy(self.profile, self.catalog)
        self.assertFalse(policy.needs_health(self.lethal_state(1, ("10251120",))))
        self.assertFalse(policy.needs_health(self.lethal_state(1, ("10253120",))))
        self.assertFalse(policy.needs_health(self.lethal_state(2, ("10951110",), slots=0)))
        self.assertFalse(policy.needs_health(self.lethal_state(2, ("10153310",), played_counts={"10153310": 3})))
        self.assertTrue(policy.needs_health(self.lethal_state(2, ("10153310",), slots=0)))


if __name__ == "__main__":
    unittest.main()
