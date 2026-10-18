from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.models import CardEffects  # noqa: E402
from battle_engine.observer import HandText, parse_hand_texts  # noqa: E402
from runtime.backend import MaaBackend  # noqa: E402
from runtime.hand_observer import HandObservation  # noqa: E402
import test_battle_runner as helpers  # noqa: E402
import test_battle_tactics as tactics  # noqa: E402


class BattleOptimizationTests(unittest.TestCase):
    def test_tracker_reuses_confirmed_hand_but_deck_change_and_uncertainty_invalidate(self):
        backend = MagicMock(spec=MaaBackend)
        backend.read_deck_count.return_value = 30
        runner = helpers.BattleRunnerTests._runner_with_backend(backend)
        hand = parse_hand_texts((HandText("怨灵", 400, 580, 80, 20),), runner.catalog, 1)
        with (
            patch.object(runner._tracker_observer, "observe", return_value=HandObservation(hand, True, deck_count=30)) as observe,
            patch("runtime.battle_runner.time.sleep"),
            patch("runtime.tracker_session.emit_deck_update"),
        ):
            runner._sync_tracker(hand)
            runner._sync_tracker(hand)
            self.assertEqual(observe.call_count, 2)
            backend.read_deck_count.return_value = 29
            observe.return_value = HandObservation(hand, True, deck_count=29)
            runner._sync_tracker(hand)
            self.assertEqual(observe.call_count, 4)
            runner._sync_tracker(None)
            runner._sync_tracker(hand)
            self.assertEqual(observe.call_count, 6)

    def test_zero_energy_defers_repeated_hand_expansion_until_attacks_finish(self):
        fixture = tactics.BattleTacticsTests()
        runner, device = fixture.make_runner([], bodies=4, energy=0)
        with patch.object(runner, "_observe_hand", wraps=runner._observe_hand) as hand:
            fixture.run_turn(runner)
        self.assertEqual(len(device.attack_attempts), 4)
        self.assertEqual(hand.call_count, 1)

    def test_zero_cost_candidate_still_plays_at_zero_energy(self):
        fixture = tactics.BattleTacticsTests()
        runner, device = fixture.make_runner(["setup_spell"], bodies=0, energy=0)
        definition = replace(runner.catalog.cards["setup_spell"], base_cost=0, effects=CardEffects())
        # Rebuild through the real constructor so zero-cost eligibility is not a
        # manually patched optimization flag.
        catalog = replace(runner.catalog, cards={**runner.catalog.cards, "setup_spell": definition})
        device.catalog = catalog
        runner = type(runner)(runner.backend, runner.layout, catalog, type(runner.policy)(runner.policy.profile, catalog))
        fixture.run_turn(runner)
        self.assertEqual(device.played, ["setup_spell"])

    def test_health_reader_does_not_run_for_an_unrelated_hand(self):
        fixture = tactics.BattleTacticsTests()
        runner, device = fixture.make_runner(["setup_spell"], bodies=0, energy=1)
        with patch.object(device, "read_leader_health", wraps=device.read_leader_health) as health:
            fixture.run_turn(runner)
        self.assertEqual(device.played, ["setup_spell"])
        health.assert_not_called()

    def test_confirmed_settlement_is_not_recognized_again_by_the_caller(self):
        fixture = tactics.BattleTacticsTests()
        runner, device = fixture.make_runner(["leader_burn"], bodies=0, energy=2, enemy_health=3)
        confirmed: list[str] = []
        original_verify = device.verify

        def verify(node, frame):
            result = original_verify(node, frame)
            if result:
                confirmed.append(node)
            return result

        with patch.object(device, "verify", side_effect=verify):
            fixture.run_turn(runner)
        self.assertEqual(confirmed, ["识别_基础战斗胜利结算"])

    def test_tracker_does_not_cache_a_probe_that_disagrees_with_strict_observations(self):
        backend = MagicMock(spec=MaaBackend)
        backend.read_deck_count.return_value = 30
        runner = helpers.BattleRunnerTests._runner_with_backend(backend)
        with (
            patch.object(runner._tracker_observer, "observe", return_value=HandObservation((), True, deck_count=29)) as observe,
            patch("runtime.battle_runner.time.sleep"),
            patch("runtime.tracker_session.emit_deck_update"),
        ):
            runner._sync_tracker(())
            runner._sync_tracker(())
        self.assertEqual(observe.call_count, 4)


if __name__ == "__main__":
    unittest.main()
