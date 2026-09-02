from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from battle_engine.models import MulliganPolicy  # noqa: E402
from battle_engine.policy import BattlePolicy  # noqa: E402
from battle_engine.repository import (  # noqa: E402
    BattleProfileRepository,
    CardCatalogRepository,
)
from runtime.backend import MaaBackend, ObservedBoardState  # noqa: E402
from runtime.battle_runner import BattleRunner  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402
from solution_engine.models import SolutionError  # noqa: E402


class _MulliganBackend:
    def __init__(self) -> None:
        self.swipes: list[tuple[int, int, int, int, int]] = []

    def recognize(self, _node: str, *, frame=None):
        return SimpleNamespace(
            hit=True,
            all_results=(
                SimpleNamespace(text="蛇神之怒", box=[200, 400, 100, 30]),
                SimpleNamespace(text="浑浊之民", box=[400, 400, 100, 30]),
            ),
        )

    def capture_frame(self):
        return object()

    def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int
    ) -> bool:
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return True

    def wait_changed(self, *_args) -> bool:
        return True


class _AttackBackend:
    def __init__(self) -> None:
        self.swipes: list[tuple[int, int, int, int, int]] = []
        self._states = iter(
            (
                ObservedBoardState(3, 0, ()),
                ObservedBoardState(3, 0, ()),
                ObservedBoardState(2, 0, ()),
                ObservedBoardState(2, 0, ()),
            )
        )
        self._last = ObservedBoardState(2, 0, ())

    def observe_board_state(self) -> ObservedBoardState:
        self._last = next(self._states, self._last)
        return self._last

    def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int
    ) -> bool:
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return True


class _HandObservationBackend:
    def __init__(self, hand_count: int | None, *, tap_succeeds: bool = True) -> None:
        self.hand_count = hand_count
        self.tap_succeeds = tap_succeeds
        self.taps: list[tuple[int, int]] = []
        self._recognitions = iter(
            (
                SimpleNamespace(hit=False),
                SimpleNamespace(
                    hit=True,
                    all_results=(
                        SimpleNamespace(
                            text="怨恨的栽培者", box=[700, 550, 100, 30]
                        ),
                    ),
                ),
            )
        )

    def capture_frame(self):
        return object()

    def recognize(self, _node: str, *, frame=None):
        return next(self._recognitions)

    def read_hand_count(self) -> int | None:
        return self.hand_count

    def tap(self, x: int, y: int) -> bool:
        self.taps.append((x, y))
        return self.tap_succeeds


class BattleRunnerTests(unittest.TestCase):
    @staticmethod
    def _runner_with_backend(backend) -> BattleRunner:
        catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        profile = BattleProfileRepository.for_project(PROJECT_ROOT, catalog).load(
            "aggro_nightmare"
        )
        layout = BoardLayout.load(
            PROJECT_ROOT / "assets" / "resource" / "layouts" / "default.json"
        )
        return BattleRunner(
            cast(MaaBackend, backend),
            layout,
            catalog,
            BattlePolicy(profile, catalog),
        )

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

    def test_hand_observation_expands_from_rightmost_early_hand_card(self) -> None:
        for hand_count, expected_point in ((4, (805, 665)), (5, (860, 665))):
            with self.subTest(hand_count=hand_count):
                backend = _HandObservationBackend(hand_count=hand_count)
                runner = self._runner_with_backend(backend)

                with patch("runtime.battle_runner.time.sleep"):
                    observed = runner._observe_hand(energy=1)

                self.assertEqual(backend.taps, [expected_point])
                self.assertIsNotNone(observed)
                assert observed is not None
                self.assertEqual(
                    [item.name for item in observed], ["怨恨的栽培者"]
                )

    def test_hand_observation_falls_back_when_count_is_unavailable(self) -> None:
        backend = _HandObservationBackend(hand_count=None)
        runner = self._runner_with_backend(backend)

        with patch("runtime.battle_runner.time.sleep"):
            runner._observe_hand(energy=1)

        self.assertEqual(backend.taps, [(1025, 665)])

    def test_hand_observation_returns_empty_only_for_confirmed_empty_hand(self) -> None:
        backend = _HandObservationBackend(hand_count=0)
        runner = self._runner_with_backend(backend)

        observed = runner._observe_hand(energy=1)

        self.assertEqual(observed, ())
        self.assertEqual(backend.taps, [])

    def test_hand_observation_raises_when_expand_tap_fails(self) -> None:
        backend = _HandObservationBackend(hand_count=4, tap_succeeds=False)
        runner = self._runner_with_backend(backend)

        with self.assertRaisesRegex(SolutionError, "点击手牌展开失败"):
            runner._observe_hand(energy=1)

        self.assertEqual(backend.taps, [(805, 665)])

    def test_mulligan_swipes_only_cards_outside_keep_list(self) -> None:
        catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        profile = BattleProfileRepository.for_project(PROJECT_ROOT, catalog).load(
            "aggro_nightmare"
        )
        profile = replace(
            profile,
            mulligan=MulliganPolicy(enabled=True, keep=("10153310",)),
        )
        layout = BoardLayout.load(
            PROJECT_ROOT / "assets" / "resource" / "layouts" / "default.json"
        )
        backend = _MulliganBackend()
        runner = BattleRunner(
            cast(MaaBackend, backend),
            layout,
            catalog,
            BattlePolicy(profile, catalog),
        )

        runner._apply_mulligan(object())

        self.assertEqual(backend.swipes, [(450, 520, 450, 210, 450)])

    def test_attack_recalculates_source_layout_after_follower_dies(self) -> None:
        catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        profile = BattleProfileRepository.for_project(PROJECT_ROOT, catalog).load(
            "aggro_nightmare"
        )
        layout = BoardLayout.load(
            PROJECT_ROOT / "assets" / "resource" / "layouts" / "default.json"
        )
        backend = _AttackBackend()
        runner = BattleRunner(
            cast(MaaBackend, backend),
            layout,
            catalog,
            BattlePolicy(profile, catalog),
        )

        with patch("runtime.battle_runner.time.sleep"):
            runner._attack_phase()

        enemy_leader = layout.fixed_point("enemy_leader")
        self.assertEqual(
            backend.swipes,
            [
                (820, 465, *enemy_leader, 350),
                (730, 465, *enemy_leader, 350),
                (550, 465, *enemy_leader, 350),
            ],
        )


if __name__ == "__main__":
    unittest.main()
