from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from battle_engine.repository import (  # noqa: E402
    BattleProfileRepository,
    CardCatalogRepository,
)
from import_battle_deck import DeckImportError, generate_import  # noqa: E402


class BattleDeckImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.base = self.root / "SVWBData" / "Base"
        self.image_dir = self.base / "cards" / "png" / "wizard2"
        self.image_dir.mkdir(parents=True)
        self._write_source_image("100100_100100.png")
        self._write_source_image("200100_200100.png")
        self._write_source_image("300100_300100.png")

        staging = {
            "schema_version": 1,
            "cards": [
                self._source_card("100", "测试随从", "follower", "100100_100100.png"),
                self._source_card("200", "同名卡", "spell", "200100_200100.png"),
                self._source_card("300", "同名卡", "spell", "300100_300100.png"),
            ],
        }
        staging["cards"][0]["style_aliases"] = [
            {"name": "测试异画", "resource_id": "100100", "style_id": "1"}
        ]
        self._write_json(
            self.base / "maa" / "wizard2_card_staging.json", staging
        )
        self._write_json(
            self.base
            / "master"
            / "wizard2"
            / "decoded"
            / "tables"
            / "CardResourceMaster.json",
            [
                {
                    "CardResourceId": resource_id,
                    "TillingNormalX": 0.5,
                    "TillingNormalY": 0.5,
                    "OffsetNormalX": 0.25,
                    "OffsetNormalY": 0.25,
                }
                for resource_id in (100100, 200100, 300100)
            ],
        )
        self._write_json(
            self.base / "master" / "wizard2" / "decoded" / "summary.json",
            {"sha256": "fixture-hash"},
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _source_card(
        self, card_id: str, name: str, card_type: str, image_name: str
    ) -> dict:
        return {
            "id": card_id,
            "name": name,
            "type": card_type,
            "base_cost": 1,
            "resource_ids": [image_name.split("_", 1)[0]],
            "style_aliases": [],
            "skill_text": "【疾驰】",
            "templates": {
                "status": "offline_asset_png_ready",
                "paths": [str(self.image_dir / image_name)],
            },
            "traits": [
                {
                    "trait": "storm",
                    "status": "auto_exact",
                    "evidence": "【疾驰】",
                },
                {
                    "trait": "ward",
                    "status": "review_required",
                    "evidence": "给予其他随从【守护】",
                },
            ],
            "target_review": {
                "status": "review_required",
                "candidate_allowed_targets": ["none"],
                "default_target": None,
                "reasons": ["fixture"],
            },
        }

    def _write_source_image(self, name: str) -> None:
        image = Image.new("RGBA", (128, 128), (20, 40, 60, 255))
        image.save(self.image_dir / name)

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _write_request(self, cards: list[dict]) -> Path:
        path = self.root / "deck.json"
        self._write_json(
            path,
            {
                "schema_version": 1,
                "id": "fixture_deck",
                "name": "测试卡组",
                "cards": cards,
            },
        )
        return path

    def test_generates_runtime_catalog_profile_and_uv_cropped_image(self) -> None:
        request = self._write_request(
            [
                {
                    "ref": "测试随从",
                    "copies": 3,
                    "default_target": "none",
                    "allowed_targets": ["none"],
                    "play_priority": 80,
                    "mulligan_keep": True,
                    "evolution_priority": 20,
                }
            ]
        )
        output = self.root / "generated"

        report = generate_import(request, output, self.base)

        catalog_path = output / "battle" / "card_catalog.json"
        catalog = CardCatalogRepository(catalog_path).load()
        self.assertEqual(set(catalog.cards), {"100"})
        self.assertEqual(catalog.cards["100"].traits, {"storm"})
        self.assertEqual(catalog.cards["100"].aliases, ("测试异画",))
        profile = BattleProfileRepository(
            output / "battle" / "profiles", catalog
        ).load("fixture_deck")
        self.assertEqual(profile.deck[0].card_id, "100")
        self.assertEqual(profile.mulligan.keep, ("100",))
        self.assertEqual(profile.evolution.card_priority, ("100",))

        feature_path = (
            output / "resource" / "image" / "cards" / "100" / "100100_100100.png"
        )
        with Image.open(feature_path) as image:
            self.assertEqual(image.size, (64, 64))
        self.assertEqual(report["source_sha256"], "fixture-hash")
        self.assertEqual(report["cards"][0]["source_target_review"]["status"], "review_required")

    def test_rejects_ambiguous_card_name(self) -> None:
        request = self._write_request(
            [
                {
                    "ref": "同名卡",
                    "copies": 3,
                    "default_target": "enemy_leader",
                    "allowed_targets": ["enemy_leader"],
                }
            ]
        )
        with self.assertRaisesRegex(DeckImportError, "名称不唯一"):
            generate_import(request, self.root / "generated", self.base)

    def test_requires_explicit_target_review(self) -> None:
        request = self._write_request(
            [{"ref": "100", "copies": 3}]
        )
        with self.assertRaisesRegex(DeckImportError, "default_target"):
            generate_import(request, self.root / "generated", self.base)

    def test_optional_standard_deck_size_check(self) -> None:
        request = self._write_request(
            [
                {
                    "ref": "100",
                    "copies": 3,
                    "default_target": "none",
                    "allowed_targets": ["none"],
                }
            ]
        )
        with self.assertRaisesRegex(DeckImportError, "必须为 40"):
            generate_import(
                request,
                self.root / "generated",
                self.base,
                require_40=True,
            )

    def test_refuses_to_replace_output_without_force(self) -> None:
        request = self._write_request(
            [
                {
                    "ref": "100",
                    "copies": 3,
                    "default_target": "none",
                    "allowed_targets": ["none"],
                }
            ]
        )
        output = self.root / "generated"
        generate_import(request, output, self.base)
        with self.assertRaisesRegex(DeckImportError, "--force"):
            generate_import(request, output, self.base)

        report = generate_import(request, output, self.base, force=True)
        self.assertEqual(report["unique_cards"], 1)

    def test_force_does_not_delete_unmarked_directory(self) -> None:
        request = self._write_request(
            [
                {
                    "ref": "100",
                    "copies": 3,
                    "default_target": "none",
                    "allowed_targets": ["none"],
                }
            ]
        )
        output = self.root / "manual-files"
        output.mkdir()
        important = output / "important.txt"
        important.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(DeckImportError, "拒绝递归删除"):
            generate_import(request, output, self.base, force=True)
        self.assertEqual(important.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
