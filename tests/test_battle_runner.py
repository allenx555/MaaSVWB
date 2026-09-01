from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from runtime.battle_runner import BattleRunner  # noqa: E402


class BattleRunnerTests(unittest.TestCase):
    def test_first_attached_turn_can_resume_after_partial_actions(self) -> None:
        self.assertTrue(BattleRunner._is_new_turn_energy(1, 1, None))
        self.assertTrue(BattleRunner._is_new_turn_energy(1, 3, None))

    def test_new_turn_requires_increased_and_refilled_energy(self) -> None:
        self.assertFalse(BattleRunner._is_new_turn_energy(0, 2, 1))
        self.assertFalse(BattleRunner._is_new_turn_energy(1, 1, 1))
        self.assertTrue(BattleRunner._is_new_turn_energy(2, 2, 1))

    def test_tenth_turn_uses_full_energy_as_boundary(self) -> None:
        self.assertFalse(BattleRunner._is_new_turn_energy(0, 10, 10))
        self.assertTrue(BattleRunner._is_new_turn_energy(10, 10, 10))


if __name__ == "__main__":
    unittest.main()
