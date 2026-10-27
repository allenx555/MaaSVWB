from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from pipeline_nodes import DUNGEON_REPLAY, DUNGEON_RETURN  # noqa: E402
from runtime.battle_runner import BattleOutcome  # noqa: E402
from runtime.dungeon_runner import DungeonRunner  # noqa: E402
from runtime.dungeon_session import DungeonSession  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402
from solution_engine.models import SolutionError  # noqa: E402


class DungeonRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MagicMock()
        self.backend.is_stopping.return_value = False
        self.backend.verify.side_effect = lambda node, frame: node == DUNGEON_REPLAY and frame == "settlement"
        self.backend.tap.return_value = True
        self.battle = MagicMock()
        self.battle.is_start_state.side_effect = lambda frame: frame == "battle"
        self.layout = BoardLayout.load(PROJECT_ROOT / "assets/resource/layouts/default.json")
        self.runner = DungeonRunner(self.backend, self.layout, self.battle, DungeonSession(2))
        sleep_patch = patch("runtime.dungeon_runner.time.sleep")
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_retries_replay_until_battle_really_starts(self) -> None:
        self.backend.capture_frame.side_effect = ["settlement", "settlement", "battle"]

        self.runner._enter_or_resume_battle()

        self.assertEqual(self.backend.tap.call_count, 2)
        self.backend.tap.assert_called_with(1110, 465)
        self.backend.tap_recognition.assert_not_called()

    def test_replay_is_bounded_when_settlement_never_leaves(self) -> None:
        self.backend.capture_frame.return_value = "settlement"

        with self.assertRaisesRegex(SolutionError, "点击再战 3 次后仍停留"):
            self.runner._enter_or_resume_battle()

        self.assertEqual(self.backend.tap.call_count, 3)

    def test_failed_replay_click_stops(self) -> None:
        self.backend.capture_frame.return_value = "settlement"
        self.backend.tap.return_value = False

        with self.assertRaisesRegex(SolutionError, "点击再战失败"):
            self.runner._enter_or_resume_battle()

        self.backend.tap.assert_called_once()

    def test_loading_frame_does_not_trigger_blind_replay_click(self) -> None:
        self.backend.capture_frame.side_effect = [None, "loading", "battle"]

        self.runner._enter_or_resume_battle()

        self.backend.tap.assert_not_called()

    def test_two_victories_count_once_each_despite_replay_retry(self) -> None:
        self.backend.capture_frame.side_effect = ["battle", "settlement", "settlement", "battle"]
        self.battle.run.return_value = BattleOutcome.VICTORY

        with patch("runtime.dungeon_runner.emit_event"):
            self.runner.run()

        self.assertEqual(self.runner.session.victories, 2)
        self.assertEqual(self.battle.run.call_count, 2)
        self.assertEqual(self.battle.reset_tracker.call_count, 2)
        self.assertEqual(self.backend.tap.call_count, 2)
        self.backend.tap_recognition.assert_called_once_with(DUNGEON_RETURN, 15_000)


if __name__ == "__main__":
    unittest.main()
