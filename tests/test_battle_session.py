from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.session import BattleSession, SettlementAction  # noqa: E402


class BattleSessionTests(unittest.TestCase):
    def test_battle_count_includes_initial_battle(self) -> None:
        session = BattleSession(battle_count=1)

        self.assertEqual(
            session.record_victory(), SettlementAction.RETURN_TO_DUNGEON
        )
        self.assertEqual(session.remaining_victories, 0)

    def test_victories_advance_battle_count(self) -> None:
        session = BattleSession(battle_count=2)

        self.assertEqual(session.record_victory(), SettlementAction.REPLAY)
        self.assertEqual(session.remaining_victories, 1)
        self.assertEqual(
            session.record_victory(), SettlementAction.RETURN_TO_DUNGEON
        )

    def test_failure_replays_but_does_not_advance_count(self) -> None:
        session = BattleSession(battle_count=2)

        self.assertEqual(session.record_defeat(), SettlementAction.REPLAY)
        self.assertEqual(session.victories, 0)
        self.assertEqual(session.remaining_victories, 2)

    def test_fourth_consecutive_failure_stops(self) -> None:
        session = BattleSession(battle_count=2)

        for expected_failures in range(1, 4):
            self.assertEqual(session.record_defeat(), SettlementAction.REPLAY)
            self.assertEqual(session.consecutive_failures, expected_failures)
        self.assertEqual(session.record_defeat(), SettlementAction.STOP)

    def test_victory_resets_consecutive_failures(self) -> None:
        session = BattleSession(battle_count=2)

        session.record_defeat()
        session.record_defeat()
        self.assertEqual(session.record_victory(), SettlementAction.REPLAY)
        self.assertEqual(session.consecutive_failures, 0)

    def test_unknown_result_never_replays(self) -> None:
        self.assertEqual(
            BattleSession.record_unknown(), SettlementAction.STOP
        )

    def test_battle_count_is_bounded(self) -> None:
        for invalid in (0, 100, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                BattleSession(battle_count=invalid)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
