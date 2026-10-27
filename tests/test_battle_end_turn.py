from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from pipeline_nodes import BATTLE_END_CONFIRM, BATTLE_PLAYER_TURN  # noqa: E402
from runtime.battle_runner import BattleRunner  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402


class BattleEndTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MagicMock()
        self.backend.is_stopping.return_value = False
        self.backend.verify.side_effect = lambda node, frame: (
            (node == BATTLE_END_CONFIRM and frame == "confirm")
            or (node == BATTLE_PLAYER_TURN and frame == "player")
        )
        self.runner = object.__new__(BattleRunner)
        self.runner.backend = self.backend
        self.runner.layout = BoardLayout.load(PROJECT_ROOT / "assets/resource/layouts/default.json")
        sleep_patch = patch("runtime.battle_runner.time.sleep")
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_swallowed_click_retries_until_turn_switches(self) -> None:
        self.backend.capture_frame.side_effect = ["player"] * 10 + ["opponent"]
        self.assertTrue(self.runner._end_turn())
        self.assertEqual(self.backend.tap.call_count, 2)
        self.backend.tap.assert_called_with(1170, 320)

    def test_late_confirmation_is_handled_before_accepting_switch(self) -> None:
        self.backend.capture_frame.side_effect = ["player", "confirm", "opponent"]
        self.assertTrue(self.runner._end_turn())
        self.backend.tap.assert_called_once()
        self.backend.tap_recognition.assert_called_once_with(BATTLE_END_CONFIRM, 3_000)

    def test_stuck_player_turn_is_bounded(self) -> None:
        self.backend.capture_frame.return_value = "player"
        self.assertFalse(self.runner._end_turn())
        self.assertEqual(self.backend.tap.call_count, 3)

    def test_missing_frames_do_not_confirm_switch(self) -> None:
        self.backend.capture_frame.return_value = None
        self.assertFalse(self.runner._end_turn())

    def test_stop_does_not_click(self) -> None:
        self.backend.is_stopping.return_value = True
        self.assertFalse(self.runner._end_turn())
        self.backend.tap.assert_not_called()

    def test_failed_confirmation_stops(self) -> None:
        self.backend.capture_frame.return_value = "confirm"
        self.backend.tap_recognition.return_value = False
        self.assertFalse(self.runner._end_turn())
        self.backend.tap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
