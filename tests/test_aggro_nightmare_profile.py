from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.repository import (  # noqa: E402
    BattleProfileRepository,
    CardCatalogRepository,
)


class AggroNightmareProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        cls.profile = BattleProfileRepository.for_project(
            PROJECT_ROOT, cls.catalog
        ).load("aggro_nightmare")

    def test_mulligan_keeps_every_one_cost_card_in_deck(self) -> None:
        expected = {
            entry.card_id
            for entry in self.profile.deck
            if self.catalog.cards[entry.card_id].base_cost == 1
        }

        self.assertTrue(self.profile.mulligan.enabled)
        self.assertEqual(set(self.profile.mulligan.keep), expected)

    def test_world_is_first_and_brush_monster_is_last(self) -> None:
        priorities = {
            card_id: rule.play_priority
            for card_id, rule in self.profile.cards.items()
        }

        self.assertEqual(priorities["10503210"], max(priorities.values()))
        self.assertEqual(priorities["10501110"], min(priorities.values()))

    def test_followers_except_brush_monster_precede_spells(self) -> None:
        follower_priorities = [
            self.profile.cards[card_id].play_priority
            for card_id, definition in self.catalog.cards.items()
            if definition.type == "follower" and card_id != "10501110"
        ]
        spell_priorities = [
            self.profile.cards[card_id].play_priority
            for card_id, definition in self.catalog.cards.items()
            if definition.type == "spell"
        ]

        self.assertGreater(min(follower_priorities), max(spell_priorities))

    def test_higher_cost_followers_are_preferred_within_same_category(self) -> None:
        priorities_by_cost: dict[int, set[int]] = {}
        for card_id, definition in self.catalog.cards.items():
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


if __name__ == "__main__":
    unittest.main()
