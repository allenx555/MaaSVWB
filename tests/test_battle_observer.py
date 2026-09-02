from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.observer import (  # noqa: E402
    HandText,
    match_card_name,
    parse_hand_texts,
    recognition_results_to_hand_texts,
)
from battle_engine.repository import CardCatalogRepository  # noqa: E402


class BattleObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()

    def test_exact_name_resolves_card(self) -> None:
        self.assertEqual(match_card_name("蛇神之怒", self.catalog), ("10153310", 1.0))

    def test_style_aliases_resolve_to_base_cards(self) -> None:
        self.assertEqual(match_card_name("新的旅途", self.catalog), ("10503210", 1.0))
        self.assertEqual(match_card_name("服从魔法", self.catalog), ("10552310", 1.0))

    def test_ocr_punctuation_and_one_wrong_character_are_tolerated(self) -> None:
        matched = match_card_name("可爱恶魔 莉莉姆", self.catalog)
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched[0], "10851120")

    def test_hand_indexes_follow_screen_order_and_keep_duplicates(self) -> None:
        observed = parse_hand_texts(
            [
                HandText("蛇神之怒", 700, 550, 100, 30),
                HandText("怨灵", 300, 550, 80, 30),
                HandText("怨灵", 490, 550, 80, 30),
            ],
            self.catalog,
            energy=1,
        )
        self.assertEqual([item.card.card_id for item in observed], ["90051130", "90051130", "10153310"])
        self.assertEqual([item.card.hand_index for item in observed], [1, 2, 3])
        self.assertEqual([item.card.playable for item in observed], [True, True, False])
        self.assertEqual([item.source for item in observed], [(340, 665), (530, 665), (750, 665)])

    def test_overlapping_ocr_boxes_are_deduplicated_without_removing_real_duplicates(self) -> None:
        observed = parse_hand_texts(
            [
                HandText("怨灵", 300, 550, 90, 30),
                HandText("怨灵", 305, 552, 84, 28),
                HandText("怨灵", 500, 550, 90, 30),
            ],
            self.catalog,
            energy=1,
        )

        self.assertEqual([item.card.card_id for item in observed], ["90051130", "90051130"])
        self.assertEqual([item.card.hand_index for item in observed], [1, 2])

    def test_maa_ocr_results_are_converted_to_hand_texts(self) -> None:
        texts = recognition_results_to_hand_texts(
            (
                SimpleNamespace(text="怨灵", box=[300, 400, 80, 30]),
                SimpleNamespace(
                    text="蛇神之怒",
                    box=SimpleNamespace(x=600, y=400, w=100, h=30),
                ),
            )
        )

        self.assertEqual(
            texts,
            (
                HandText("怨灵", 300, 400, 80, 30),
                HandText("蛇神之怒", 600, 400, 100, 30),
            ),
        )


if __name__ == "__main__":
    unittest.main()
