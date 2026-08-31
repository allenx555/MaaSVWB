from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.models import (  # noqa: E402
    BattleProfile,
    BattleProfileError,
    BattleState,
    CardCatalog,
    ObservedCard,
)
from battle_engine.policy import BattlePolicy  # noqa: E402
from battle_engine.repository import BattleProfileRepository  # noqa: E402


def catalog_data() -> dict:
    return {
        "schema_version": 1,
        "cards": [
            {
                "id": "basic_follower",
                "name": "基础随从",
                "type": "follower",
                "base_cost": 1,
                "templates": ["cards/basic_follower.png"],
                "default_target": "none",
                "allowed_targets": ["none"],
                "traits": [],
            },
            {
                "id": "setup_spell",
                "name": "准备法术",
                "type": "spell",
                "base_cost": 1,
                "templates": ["cards/setup_spell.png"],
                "default_target": "none",
                "allowed_targets": ["none"],
                "traits": [],
            },
            {
                "id": "leader_burn",
                "name": "主战者直伤",
                "type": "spell",
                "base_cost": 2,
                "templates": ["cards/leader_burn.png"],
                "default_target": "enemy_leader",
                "allowed_targets": ["enemy_leader"],
                "traits": [],
            },
        ],
    }


def profile_data() -> dict:
    return {
        "schema_version": 1,
        "id": "test_aggro",
        "name": "测试快攻",
        "description": "离线策略测试",
        "deck": [
            {"card_id": "basic_follower", "copies": 3},
            {"card_id": "setup_spell", "copies": 3},
            {"card_id": "leader_burn", "copies": 3},
        ],
        "cards": {
            "basic_follower": {"play_priority": 50},
            "setup_spell": {"play_priority": 40},
            "leader_burn": {
                "play_priority": 100,
                "target": {"type": "enemy_leader"},
                "max_uses_per_turn": 2,
            },
        },
        "combos": [
            {
                "id": "setup_then_burn",
                "priority": 200,
                "steps": [
                    {"card_id": "setup_spell"},
                    {
                        "card_id": "leader_burn",
                        "target": {"type": "enemy_leader"},
                    },
                ],
            }
        ],
        "attack": {
            "clear_ward": True,
            "otherwise": "enemy_leader",
            "attacker_order": "lowest_attack_first",
        },
        "evolution": {
            "enabled": True,
            "prefer_can_attack": True,
            "card_priority": ["basic_follower"],
            "type_order": ["super", "normal"],
        },
        "mulligan": {
            "enabled": True,
            "keep": ["basic_follower"],
            "maximum_keep_cost": 2,
        },
        "safety": {
            "max_actions_per_turn": 30,
            "max_retries_per_action": 1,
            "no_progress_limit": 3,
        },
    }


class BattleProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = CardCatalog.from_dict(catalog_data())

    def load_profile(self, data: dict) -> BattleProfile:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return BattleProfileRepository(path.parent, self.catalog).load_path(path)

    def test_catalog_and_profile_examples_match_json_schemas(self) -> None:
        schema_dir = PROJECT_ROOT / "assets" / "schemas"
        catalog_schema = json.loads(
            (schema_dir / "card-catalog.schema.json").read_text(encoding="utf-8")
        )
        profile_schema = json.loads(
            (schema_dir / "battle-profile.schema.json").read_text(encoding="utf-8")
        )

        Draft202012Validator(catalog_schema).validate(catalog_data())
        Draft202012Validator(profile_schema).validate(profile_data())

    def test_profile_loads_and_resolves_user_target(self) -> None:
        profile = self.load_profile(profile_data())
        self.assertEqual(profile.id, "test_aggro")
        target = profile.cards["leader_burn"].target
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.type, "enemy_leader")

    def test_unknown_card_is_rejected(self) -> None:
        data = profile_data()
        data["deck"].append({"card_id": "missing_card", "copies": 1})
        with self.assertRaisesRegex(BattleProfileError, "不存在的卡牌"):
            self.load_profile(data)

    def test_target_not_allowed_by_catalog_is_rejected(self) -> None:
        data = profile_data()
        data["cards"]["basic_follower"]["target"] = {
            "type": "enemy_leader"
        }
        with self.assertRaisesRegex(BattleProfileError, "不适用于"):
            self.load_profile(data)

    def test_unknown_fields_are_rejected_at_runtime(self) -> None:
        data = profile_data()
        data["python_expression"] = "do_anything()"
        with self.assertRaisesRegex(BattleProfileError, "未知字段"):
            BattleProfile.from_dict(data)

    def test_complete_combo_wins_by_priority(self) -> None:
        profile = self.load_profile(profile_data())
        state = BattleState(
            energy=3,
            board_slots=5,
            enemy_has_ward=False,
            hand=(
                ObservedCard("leader_burn", 1, True),
                ObservedCard("setup_spell", 2, True),
                ObservedCard("basic_follower", 3, True),
            ),
        )

        plan = BattlePolicy(profile, self.catalog).choose_play_plan(state)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "combo:setup_then_burn")
        self.assertEqual(
            [step.card_id for step in plan.steps],
            ["setup_spell", "leader_burn"],
        )
        self.assertEqual(plan.steps[1].target.type, "enemy_leader")

    def test_incomplete_combo_falls_back_to_single_priority(self) -> None:
        profile = self.load_profile(profile_data())
        state = BattleState(
            energy=2,
            board_slots=5,
            enemy_has_ward=False,
            hand=(
                ObservedCard("basic_follower", 1, True),
                ObservedCard("leader_burn", 2, True),
            ),
        )

        plan = BattlePolicy(profile, self.catalog).choose_play_plan(state)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "card:leader_burn@hand:2")
        self.assertEqual(plan.steps[0].target.type, "enemy_leader")

    def test_combo_reserves_energy_before_starting(self) -> None:
        profile = self.load_profile(profile_data())
        state = BattleState(
            energy=2,
            board_slots=5,
            enemy_has_ward=False,
            hand=(
                ObservedCard("setup_spell", 1, True),
                ObservedCard("leader_burn", 2, True),
            ),
        )

        plan = BattlePolicy(profile, self.catalog).choose_play_plan(state)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.reason, "card:leader_burn@hand:2")

    def test_observed_cost_overrides_catalog_cost(self) -> None:
        profile = self.load_profile(profile_data())
        state = BattleState(
            energy=1,
            board_slots=5,
            enemy_has_ward=False,
            hand=(ObservedCard("leader_burn", 1, True, observed_cost=1),),
        )

        plan = BattlePolicy(profile, self.catalog).choose_play_plan(state)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.steps[0].card_id, "leader_burn")

    def test_usage_limit_disables_card_for_current_turn(self) -> None:
        profile = self.load_profile(profile_data())
        state = BattleState(
            energy=10,
            board_slots=5,
            enemy_has_ward=False,
            hand=(ObservedCard("leader_burn", 1, True),),
            played_counts={"leader_burn": 2},
        )

        self.assertIsNone(BattlePolicy(profile, self.catalog).choose_play_plan(state))

    def test_follower_requires_board_slot(self) -> None:
        profile = self.load_profile(profile_data())
        state = BattleState(
            energy=10,
            board_slots=0,
            enemy_has_ward=False,
            hand=(ObservedCard("basic_follower", 1, True),),
        )

        self.assertIsNone(BattlePolicy(profile, self.catalog).choose_play_plan(state))

    def test_observed_state_rejects_invalid_indexes(self) -> None:
        with self.assertRaisesRegex(ValueError, "hand_index"):
            ObservedCard("basic_follower", 0, True)

        with self.assertRaisesRegex(ValueError, "重复 hand_index"):
            BattleState(
                energy=1,
                board_slots=5,
                enemy_has_ward=False,
                hand=(
                    ObservedCard("basic_follower", 1, True),
                    ObservedCard("leader_burn", 1, True),
                ),
            )


if __name__ == "__main__":
    unittest.main()
