from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.models import BattleProfile, BattleState, CardCatalog, ObservedCard  # noqa: E402
from battle_engine.policy import BattlePolicy  # noqa: E402
from runtime.backend import LeaderHealth, MaaBackend, ObservedBoardState  # noqa: E402
from runtime.battle_runner import BattleOutcome, BattleRunner, TurnReady  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402
from test_battle_engine import catalog_data, profile_data  # noqa: E402
from test_battle_integration import _BattleDevice  # noqa: E402


class _TacticsDevice(_BattleDevice):
    def __init__(self, catalog: CardCatalog, hand: list[str], bodies: int, energy: int, enemy_health: int = 20):
        super().__init__(catalog, hand, energy)
        self.bodies = list(range(bodies))
        self.next_body = bodies
        self.enemy_health = enemy_health
        self.ally_health = 20
        self.ward = True
        self.die_on_first_attack = True
        self.draw_on_death: str | None = None
        self.attack_attempts: list[int] = []
        self.layout = BoardLayout.load(PROJECT_ROOT / "assets/resource/layouts/default.json")

    def is_stopping(self):
        return False

    def verify(self, node, _frame):
        return node == "识别_基础战斗胜利结算" and self.enemy_health <= 0

    def read_leader_health(self, **_kwargs):
        return LeaderHealth(self.ally_health, self.enemy_health) if self.enemy_health > 0 else None

    def observe_board_state(self, **_kwargs):
        return ObservedBoardState(len(self.bodies), int(self.ward), (1,) if self.ward else (), (1,) * len(self.bodies))

    def _commit(self):
        card_id = self.pending
        assert card_id is not None
        super()._commit()
        if self.catalog.cards[card_id].type == "follower":
            self.bodies.append(self.next_body)
            self.next_body += 1
        if card_id == "leader_burn":
            self.enemy_health -= 3

    def swipe(self, x1, y1, x2, y2, duration):
        if y1 != 465:
            return super().swipe(x1, y1, x2, y2, duration)
        index = next(i for i in range(len(self.bodies)) if
                     self.layout.indexed_point("ally_followers", len(self.bodies), i + 1)[0] == x1)
        identity = self.bodies[index]
        if identity in self.attack_attempts:
            raise AssertionError("An exhausted body was attempted again after resuming play")
        self.attack_attempts.append(identity)
        if self.die_on_first_attack and len(self.attack_attempts) == 1:
            self.bodies.pop(index)
            self.ward = False
            if self.draw_on_death:
                self.hand.append(self.draw_on_death)
        else:
            self.enemy_health -= 1
        return True


class BattleTacticsTests(unittest.TestCase):
    def make_runner(self, hand, *, bodies=1, energy=3, enemy_health=20, limit=30, uses=3):
        raw_catalog = catalog_data()
        raw_catalog["cards"][2]["effects"] = {"leader_damage": 3}
        catalog = CardCatalog.from_dict(raw_catalog)
        data = profile_data()
        data["combos"] = []
        data["attack"]["resume_play"] = True
        data["evolution"]["enabled"] = False
        data["cards"]["setup_spell"]["max_uses_per_turn"] = uses
        data["safety"]["max_actions_per_turn"] = limit
        profile = BattleProfile.from_dict(data)
        device = _TacticsDevice(catalog, hand, bodies, energy, enemy_health)
        runner = BattleRunner(cast(MaaBackend, device), device.layout, catalog, BattlePolicy(profile, catalog))
        return runner, device

    def run_turn(self, runner):
        with patch("runtime.battle_runner.time.sleep"), patch("runtime.tracker_session.emit_deck_update"):
            return runner._execute_turn()

    def test_attack_opens_slot_then_play_and_attack_new_body_without_repeating_old_ones(self):
        runner, device = self.make_runner(["basic_follower"], bodies=5, energy=1)
        self.assertIsNone(self.run_turn(runner))
        self.assertEqual(device.played, ["basic_follower"])
        self.assertEqual(device.attack_attempts, [0, 1, 2, 3, 4, 5])

    def test_last_words_card_can_be_played_for_lethal_immediately_after_attack(self):
        runner, device = self.make_runner([], energy=2, enemy_health=3)
        device.draw_on_death = "leader_burn"
        self.assertEqual(self.run_turn(runner), BattleOutcome.VICTORY)
        self.assertEqual(device.played, ["leader_burn"])
        self.assertEqual(device.attack_attempts, [0])

    def test_per_card_use_limit_survives_attack_and_draw(self):
        runner, device = self.make_runner(["setup_spell"], uses=1)
        device.draw_on_death = "setup_spell"
        self.run_turn(runner)
        self.assertEqual(device.played, ["setup_spell"])
        self.assertEqual(device.hand, ["setup_spell"])

    def test_action_budget_is_shared_across_resumed_play_and_attacks(self):
        runner, device = self.make_runner(["basic_follower"], bodies=5, energy=1, limit=3)
        self.run_turn(runner)
        self.assertEqual(len(device.played) + len(device.attack_attempts), 3)
        self.assertEqual(device.played, ["basic_follower"])

    def test_no_progress_attack_does_not_restart_endlessly(self):
        runner, device = self.make_runner([], bodies=1, energy=0)
        device.die_on_first_attack = False
        self.run_turn(runner)
        self.assertEqual(device.attack_attempts, [0])

    def test_interleaved_turn_evolves_at_most_once(self):
        runner, device = self.make_runner(["basic_follower"], bodies=2)
        runner.policy = BattlePolicy(replace(runner.policy.profile, evolution=replace(
            runner.policy.profile.evolution, enabled=True, after_play=True,
        )), runner.catalog)
        with patch.object(runner, "_try_evolve_after_play", return_value=True) as evolve:
            self.run_turn(runner)
        evolve.assert_called_once()

    def test_observed_settlement_returns_without_end_turn_click(self):
        runner, _device = self.make_runner([])
        with (
            patch.object(runner, "_wait_for_turn_or_settlement", return_value=TurnReady(3, 3)),
            patch.object(runner, "_execute_turn", return_value=BattleOutcome.VICTORY),
            patch.object(runner, "_end_turn") as end,
        ):
            self.assertEqual(runner._play_until_settlement(), BattleOutcome.VICTORY)
        end.assert_not_called()


if __name__ == "__main__":
    unittest.main()
