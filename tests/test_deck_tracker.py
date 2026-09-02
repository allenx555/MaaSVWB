from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.deck_tracker import DeckTracker  # noqa: E402
from battle_engine.models import ObservedCard  # noqa: E402
from battle_engine.repository import (  # noqa: E402
    BattleProfileRepository,
    CardCatalogRepository,
)


def _make_card(card_id: str, hand_index: int = 1) -> ObservedCard:
    return ObservedCard(card_id=card_id, hand_index=hand_index, playable=True)


class DeckTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        profile = BattleProfileRepository.for_project(PROJECT_ROOT, catalog).load(
            "aggro_nightmare"
        )
        self.tracker = DeckTracker.from_profile(profile)
        self.initial_total = sum(
            entry.copies for entry in profile.deck
        )

    def test_initial_remaining_equals_full_deck(self) -> None:
        self.assertEqual(self.tracker.total_remaining, self.initial_total)

    def test_hand_snapshot_reduces_remaining(self) -> None:
        card_id = next(iter(self.tracker.initial_counts))
        self.tracker.update_hand((_make_card(card_id),))
        remaining = self.tracker.remaining
        initial = self.tracker.initial_counts[card_id]
        self.assertEqual(remaining.get(card_id, 0), initial - 1)

    def test_record_played_reduces_remaining(self) -> None:
        card_id = next(iter(self.tracker.initial_counts))
        self.tracker.record_played(card_id)
        remaining = self.tracker.remaining
        initial = self.tracker.initial_counts[card_id]
        self.assertEqual(remaining.get(card_id, 0), initial - 1)

    def test_hand_and_played_together_reduce_remaining(self) -> None:
        card_id = next(iter(self.tracker.initial_counts))
        initial = self.tracker.initial_counts[card_id]
        # Simulate drawing and then playing the same card on the same turn:
        # hand snapshot says 1 in hand, played_total says 1 played
        # remaining = initial - 1 (in hand) - 1 (played) = initial - 2
        self.tracker.update_hand((_make_card(card_id),))
        self.tracker.record_played(card_id)
        remaining = self.tracker.remaining
        self.assertEqual(remaining.get(card_id, 0), max(0, initial - 2))

    def test_remaining_never_goes_below_zero(self) -> None:
        card_id = next(iter(self.tracker.initial_counts))
        copies = self.tracker.initial_counts[card_id]
        for _ in range(copies + 3):
            self.tracker.record_played(card_id)
        self.assertGreaterEqual(self.tracker.remaining.get(card_id, 0), 0)

    def test_unknown_card_id_does_not_crash(self) -> None:
        self.tracker.record_played("nonexistent-card")
        self.tracker.update_hand((_make_card("nonexistent-card"),))
        # nonexistent card is not in initial_counts so remaining is unchanged
        self.assertEqual(self.tracker.total_remaining, self.initial_total)

    def test_update_hand_replaces_previous_snapshot(self) -> None:
        card_id = next(iter(self.tracker.initial_counts))
        initial = self.tracker.initial_counts[card_id]
        self.tracker.update_hand((_make_card(card_id),))
        self.assertEqual(self.tracker.remaining.get(card_id, 0), initial - 1)
        # Replace snapshot with empty hand (card was played, new hand has no copies)
        self.tracker.update_hand(())
        self.assertEqual(self.tracker.remaining.get(card_id, 0), initial)


if __name__ == "__main__":
    unittest.main()
