from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.deck_tracker import DeckTracker  # noqa: E402
from battle_engine.models import CardCatalog, CardDefinition, ObservedCard, Target  # noqa: E402
from battle_engine.repository import (  # noqa: E402
    BattleProfileRepository,
    CardCatalogRepository,
)


def _make_card(card_id: str, hand_index: int = 1) -> ObservedCard:
    return ObservedCard(card_id=card_id, hand_index=hand_index, playable=True)


def _make_catalog(*entries: tuple[str, str]) -> CardCatalog:
    """Build a minimal CardCatalog from (catalog_id, deck_code_id) pairs."""
    cards: dict[str, CardDefinition] = {}
    for catalog_id, deck_code_id in entries:
        cards[catalog_id] = CardDefinition(
            id=catalog_id,
            name=catalog_id,
            type="follower",
            base_cost=1,
            templates=(f"unused/{catalog_id}.png",),
            default_target=Target("none"),
            allowed_targets=frozenset({"none"}),
            traits=frozenset(),
            deck_code_id=deck_code_id,
        )
    return CardCatalog(cards=cards)


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


class DeckTrackerFromCodeTests(unittest.TestCase):
    def test_prefix_stripped_and_counts_correct(self) -> None:
        catalog = _make_catalog(("aaa", "aaa"), ("bbb", "bbb"))
        tracker = DeckTracker.from_deck_code("2.5.aaa.aaa.bbb", catalog)
        self.assertEqual(tracker.initial_counts.get("aaa"), 2)
        self.assertEqual(tracker.initial_counts.get("bbb"), 1)

    def test_known_short_id_maps_to_catalog_id(self) -> None:
        catalog = _make_catalog(("10501110", "e3ls"), ("10503210", "e4Gg"))
        tracker = DeckTracker.from_deck_code("2.5.e3ls.e3ls.e3ls.e4Gg.e4Gg.e4Gg", catalog)
        self.assertEqual(tracker.initial_counts.get("10501110"), 3)
        self.assertEqual(tracker.initial_counts.get("10503210"), 3)

    def test_unknown_short_id_falls_back_to_raw(self) -> None:
        catalog = _make_catalog(("10501110", "e3ls"))
        tracker = DeckTracker.from_deck_code("2.5.e3ls.zzz9.zzz9", catalog)
        self.assertEqual(tracker.initial_counts.get("10501110"), 1)
        self.assertEqual(tracker.initial_counts.get("zzz9"), 2)

    def test_empty_code_returns_empty_tracker(self) -> None:
        catalog = _make_catalog(("10501110", "e3ls"))
        tracker = DeckTracker.from_deck_code("", catalog)
        self.assertEqual(tracker.total_remaining, 0)

    def test_multiline_share_text_is_extracted(self) -> None:
        catalog = _make_catalog(("aaa", "aaa"), ("bbb", "bbb"))
        multiline = "牌组名称\n作者名\n类别\n2.5.aaa.aaa.bbb\n粘贴说明"
        tracker = DeckTracker.from_deck_code(multiline, catalog)
        self.assertEqual(tracker.initial_counts.get("aaa"), 2)
        self.assertEqual(tracker.initial_counts.get("bbb"), 1)
        self.assertEqual(tracker.total_remaining, 3)

    def test_no_valid_code_returns_empty_tracker(self) -> None:
        catalog = _make_catalog(("aaa", "aaa"))
        tracker = DeckTracker.from_deck_code("not a deck code at all", catalog)
        self.assertEqual(tracker.total_remaining, 0)

    def test_reset_restores_full_deck(self) -> None:
        catalog = _make_catalog(("aaa", "aaa"), ("bbb", "bbb"))
        code = "2.5.aaa.aaa.bbb"
        tracker = DeckTracker.from_deck_code(code, catalog)
        tracker.record_played("aaa")
        tracker.record_played("bbb")
        self.assertEqual(tracker.total_remaining, 1)
        # Simulates BattleRunner.reset_tracker() — create a fresh tracker
        tracker2 = DeckTracker.from_deck_code(code, catalog)
        self.assertEqual(tracker2.total_remaining, 3)


        catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        code = (
            "2.5.e3ls.e3ls.e3ls.e4Gg.e4Gg.e4Gg.d6jm.d6jm.d6jm.fPCm.fPCm.fPCm."
            "eSAM.eSAM.eSAM.cLuw.cLuw.cLuw.eeNc.eeNc.eeNc.fPCw.fPCw.fPCw.fnd6."
            "fnd6.fnd6.ckrU.ckrU.ckrU.eGFs.eGFs.eGFs.ckJ6.ckJ6.ckJ6.ckoq.ckoq."
            "d7D0.d7D0"
        )
        tracker = DeckTracker.from_deck_code(code, catalog)
        self.assertEqual(tracker.total_remaining, 40)
        # Verify a known card maps correctly
        self.assertEqual(tracker.initial_counts.get("10501110"), 3)  # 挥毫的怪物
        self.assertEqual(tracker.initial_counts.get("10253120"), 2)  # 夜曲将军·艾瑟拉


if __name__ == "__main__":
    unittest.main()
