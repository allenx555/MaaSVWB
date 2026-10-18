from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.models import CardCatalog  # noqa: E402
from battle_engine.policy import BattlePolicy  # noqa: E402
from battle_engine.repository import BattleProfileRepository  # noqa: E402
from runtime.backend import MaaBackend, ObservedBoardState  # noqa: E402
from runtime.battle_runner import BattleRunner  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402
from solution_engine.models import SolutionError  # noqa: E402
from test_battle_engine import catalog_data, profile_data  # noqa: E402


class _BattleDevice:
    """Stateful device boundary; use the real OCR parser, policy and runner."""

    def __init__(self, catalog: CardCatalog, hand: list[str], energy: int = 3) -> None:
        self.catalog = catalog
        self.hand = list(hand)
        self.energy = energy
        self.played: list[str] = []
        self.sources: list[int] = []
        self.taps: list[tuple[int, int]] = []
        self.pending: str | None = None
        self.targeted: dict[str, str] = {}
        self.energy_after_first: int | None = None
        self.fail_changes = False
        self.fail_observations_after_first = False

    def capture_frame(self):
        return None if self.fail_observations_after_first and self.played else object()

    def read_energy_points(self):
        return self.energy, 3

    def read_hand_count(self, **_kwargs):
        return len(self.hand)

    def read_deck_count(self, **_kwargs):
        return None

    def recognize(self, _node, **_kwargs):
        return SimpleNamespace(hit=bool(self.hand), all_results=tuple(
            SimpleNamespace(text=self.catalog.cards[cid].name,
                            box=[150 + i * 200, 580, 100, 20])
            for i, cid in enumerate(self.hand)
        ))

    def observe_board_state(self):
        return ObservedBoardState(0, 0, ())

    def swipe(self, x1, _y1, _x2, _y2, _duration):
        index = (x1 - 200) // 200
        self.sources.append(x1)
        self.pending = self.hand[index]
        if self.pending not in self.targeted:
            self._commit()
        return True

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.pending:
            self._commit()
        return True

    def _commit(self):
        assert self.pending is not None
        card_id = self.pending
        self.pending = None
        self.hand.remove(card_id)
        self.energy -= self.catalog.cards[card_id].base_cost
        self.played.append(card_id)
        if len(self.played) == 1 and self.energy_after_first is not None:
            self.energy = self.energy_after_first

    def wait_changed(self, *_args):
        return not self.fail_changes


class BattleIntegrationTests(unittest.TestCase):
    @contextmanager
    def runner(self, hand, *, profile=None, catalog=None, energy=3):
        catalog = CardCatalog.from_dict(catalog or catalog_data())
        profile = profile or profile_data()
        # Compete with the second combo card, but not the complete combo.
        profile["cards"]["basic_follower"]["play_priority"] = 150
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            loaded = BattleProfileRepository(path.parent, catalog).load_path(path)
            device = _BattleDevice(catalog, hand, energy)
            layout = BoardLayout.load(PROJECT_ROOT / "assets/resource/layouts/default.json")
            runner = BattleRunner(cast(MaaBackend, device), layout, catalog, BattlePolicy(loaded, catalog))
            with patch("runtime.battle_runner.time.sleep"), patch("runtime.tracker_session.emit_deck_update"):
                yield runner, device

    def test_combo_finishes_before_higher_priority_single_and_rebinds_hand_indexes(self):
        with self.runner(["setup_spell", "basic_follower", "leader_burn"]) as (runner, device):
            device.targeted["leader_burn"] = "enemy_leader"
            runner._play_cards()
            self.assertEqual(device.played, ["setup_spell", "leader_burn"])
            self.assertEqual(device.sources, [200, 400])
            self.assertIn(runner.layout.fixed_point("enemy_leader"), device.taps)
            self.assertEqual(device.hand, ["basic_follower"])

    def test_combo_preserves_step_target_override(self):
        profile = profile_data()
        profile["combos"][0]["steps"][1]["target"] = {"type": "ally_leader"}
        catalog = catalog_data()
        catalog["cards"][2]["allowed_targets"].append("ally_leader")
        with self.runner(["setup_spell", "leader_burn"], profile=profile, catalog=catalog) as (runner, device):
            device.targeted["leader_burn"] = "ally_leader"
            runner._play_cards()
            self.assertIn(runner.layout.fixed_point("ally_leader"), device.taps)
            self.assertNotIn(runner.layout.fixed_point("enemy_leader"), device.taps)

    def test_combo_does_not_continue_or_insert_single_when_energy_changes(self):
        with self.runner(["setup_spell", "basic_follower", "leader_burn"]) as (runner, device):
            device.energy_after_first = 1
            with self.assertRaisesRegex(SolutionError, "组合剩余步骤无法执行"):
                runner._play_cards()
            self.assertEqual(device.played, ["setup_spell"])

    def test_combo_with_repeated_card_rebinds_each_remaining_copy(self):
        profile = profile_data()
        profile["combos"][0]["steps"] = [{"card_id": "setup_spell"}, {"card_id": "setup_spell"}]
        with self.runner(["setup_spell", "basic_follower", "setup_spell"], profile=profile, energy=2) as (runner, device):
            runner._play_cards()
            self.assertEqual(device.played, ["setup_spell", "setup_spell"])
            self.assertEqual(device.sources, [200, 400])

    def test_incomplete_combo_reports_failure_at_action_limit(self):
        profile = profile_data()
        profile["safety"]["max_actions_per_turn"] = 1
        with self.runner(["setup_spell", "leader_burn"], profile=profile) as (runner, device):
            with self.assertRaisesRegex(SolutionError, "组合尚未完成"):
                runner._play_cards()
            self.assertEqual(device.played, ["setup_spell"])

    def test_observation_failure_does_not_silently_abandon_combo(self):
        profile = profile_data()
        profile["safety"]["max_actions_per_turn"] = 3
        with self.runner(["setup_spell", "leader_burn"], profile=profile) as (runner, device):
            device.fail_observations_after_first = True
            with self.assertRaisesRegex(SolutionError, "组合尚未完成"):
                runner._play_cards()
            self.assertEqual(device.played, ["setup_spell"])

    def test_unconfirmed_combo_step_is_not_committed_or_followed_by_another_card(self):
        with self.runner(["setup_spell", "leader_burn"]) as (runner, device):
            device.fail_changes = True
            with patch.object(runner._tracker_session, "record_played") as record_played:
                with self.assertRaisesRegex(SolutionError, "组合剩余步骤无法执行"):
                    runner._play_cards()
                record_played.assert_not_called()
            self.assertEqual(device.played, ["setup_spell"])

    def test_single_card_can_target_ally_leader(self):
        profile = profile_data()
        profile["cards"]["leader_burn"]["target"] = {"type": "ally_leader"}
        catalog = catalog_data()
        catalog["cards"][2]["allowed_targets"].append("ally_leader")
        with self.runner(["leader_burn"], profile=profile, catalog=catalog, energy=2) as (runner, device):
            device.targeted["leader_burn"] = "ally_leader"
            runner._play_cards()
            self.assertEqual(device.played, ["leader_burn"])
            self.assertIn(runner.layout.fixed_point("ally_leader"), device.taps)

    def test_unsupported_effective_targets_are_rejected_before_device_actions(self):
        for location in ("default", "rule", "combo"):
            for target_type in ("enemy_follower", "ally_follower"):
                with self.subTest(location=location, target=target_type):
                    catalog = catalog_data()
                    catalog["cards"][2]["allowed_targets"].append(target_type)
                    profile = profile_data()
                    target = {"type": target_type, "selector": "lowest_defense"}
                    if location == "default":
                        catalog["cards"][2]["default_target"] = target_type
                        del profile["cards"]["leader_burn"]["target"]
                    elif location == "rule":
                        profile["cards"]["leader_burn"]["target"] = target
                    else:
                        profile["combos"][0]["steps"][1]["target"] = target
                    with patch.object(_BattleDevice, "swipe") as swipe, patch.object(_BattleDevice, "tap") as tap:
                        with self.assertRaisesRegex(SolutionError, "暂不支持出牌目标"):
                            with self.runner([], profile=profile, catalog=catalog):
                                self.fail("Unsupported profile was allowed to run")
                        swipe.assert_not_called()
                        tap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
