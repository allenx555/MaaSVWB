from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch


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
from runtime.hand_observer import HandObservation  # noqa: E402
from battle_engine.observer import HandText, parse_hand_texts  # noqa: E402
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

    def observe_board_state(self, **_kwargs) -> ObservedBoardState:
        self._last = next(self._states, self._last)
        return self._last

    def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int
    ) -> bool:
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return True


class _HandObservationBackend:
    def __init__(
        self,
        hand_count: int | None,
        *,
        tap_succeeds: bool = True,
        recognition_results: tuple[object, ...] = (),
    ) -> None:
        self.hand_count = hand_count
        self.tap_succeeds = tap_succeeds
        self.taps: list[tuple[int, int]] = []
        self.recognize_calls = 0
        self.recognition = SimpleNamespace(
            hit=True,
            all_results=(
                SimpleNamespace(
                    text="怨恨的栽培者", box=[700, 580, 100, 20]
                ),
            ),
        )
        self.recognition_results = list(recognition_results)

    def capture_frame(self):
        return object()

    def recognize(self, _node: str, *, frame=None):
        self.recognize_calls += 1
        if self.recognition_results:
            return self.recognition_results.pop(0)
        return self.recognition

    def read_hand_count(self) -> int | None:
        return self.hand_count

    def tap(self, x: int, y: int) -> bool:
        self.taps.append((x, y))
        return self.tap_succeeds

class _EvolutionBackend:
    def is_stopping(self) -> bool:
        return False

    def capture_frame(self):
        return object()

    def verify(self, _node, _frame) -> bool:
        return False

    def __init__(
        self,
        ally_count: int,
        recognition_results: tuple[bool, ...],
    ) -> None:
        self.ally_count = ally_count
        self.recognition_results = list(recognition_results)
        self.taps: list[tuple[int, int]] = []
        self.recognitions: list[tuple[str, int, int]] = []

    def observe_board_state(self) -> ObservedBoardState:
        return ObservedBoardState(self.ally_count, 0, ())

    def tap(self, x: int, y: int) -> bool:
        self.taps.append((x, y))
        return True

    def tap_recognition(
        self, pipeline_node: str, timeout_ms: int, interval_ms: int = 250
    ) -> bool:
        self.recognitions.append((pipeline_node, timeout_ms, interval_ms))
        return self.recognition_results.pop(0)


class BattleRunnerTests(unittest.TestCase):
    def test_extra_energy_is_used_once_before_planning_with_updated_energy(self):
        backend = MagicMock(spec=MaaBackend)
        backend.is_stopping.return_value = False
        backend.verify.return_value = True
        backend.tap.return_value = True
        backend.read_energy_points.side_effect = [(0, 1), None, (1, 1), (1, 1)]
        runner = self._runner_with_backend(backend)
        energies = []
        with (
            patch("runtime.battle_runner.time.sleep"),
            patch.object(runner, "_play_cards", side_effect=lambda: energies.append(backend.read_energy_points())),
            patch.object(runner, "_try_evolve_after_play"),
            patch.object(runner, "_attack_phase"),
        ):
            runner._execute_turn()
        backend.tap.assert_called_once_with(*runner.layout.fixed_point("extra_energy"))
        self.assertEqual(energies, [(1, 1)])

    def test_extra_energy_unavailable_or_unreadable_does_not_click(self):
        for available, energy in ((False, (1, 1)), (True, None)):
            with self.subTest(available=available, energy=energy):
                backend = MagicMock(spec=MaaBackend)
                backend.is_stopping.return_value = False
                backend.verify.return_value = available
                backend.read_energy_points.return_value = energy
                runner = self._runner_with_backend(backend)
                self.assertFalse(runner._try_use_extra_energy())
                backend.tap.assert_not_called()

    def test_generic_strategy_does_not_check_or_use_extra_energy(self):
        backend = MagicMock(spec=MaaBackend)
        runner = self._runner_with_backend(backend)
        runner.policy = BattlePolicy(replace(runner.policy.profile, strategy="generic"), runner.catalog)
        self.assertFalse(runner._try_use_extra_energy())
        backend.capture_frame.assert_not_called()
        backend.tap.assert_not_called()

    def test_unconfirmed_extra_energy_stops_without_repeated_clicks_or_playing(self):
        backend = MagicMock(spec=MaaBackend)
        backend.is_stopping.return_value = False
        backend.verify.return_value = True
        backend.tap.return_value = True
        backend.read_energy_points.return_value = (1, 1)
        runner = self._runner_with_backend(backend)
        with patch("runtime.battle_runner.time.sleep"), patch.object(runner, "_play_cards") as play:
            with self.assertRaisesRegex(SolutionError, "未确认能量增加"):
                runner._execute_turn()
        backend.tap.assert_called_once()
        play.assert_not_called()

    def test_play_then_energy_failure_does_not_double_count_or_wait_for_turn_end(self):
        backend = MagicMock(spec=MaaBackend)
        backend.read_energy_points.side_effect = [(1, 1), None]
        backend.observe_board_state.return_value = ObservedBoardState(0, 0, ())
        backend.wait_changed.return_value = True
        backend.swipe.return_value = True
        runner = self._runner_with_backend(backend)
        hand = parse_hand_texts((HandText("怨恨的栽培者", 400, 580, 100, 20),),
                                runner.catalog, energy=1)
        with (
            patch.object(runner, "_observe_hand", return_value=hand),
            patch.object(runner._tracker_observer, "observe", return_value=HandObservation(hand, True)),
            patch("runtime.battle_runner.time.sleep"),
            patch("runtime.tracker_session.emit_deck_update") as events,
        ):
            runner._play_cards()
        self.assertEqual(runner._deck_tracker.total_remaining, 39)
        self.assertEqual(runner._deck_tracker.hand_snapshot.get("10251120"), 0)
        self.assertEqual(runner._deck_tracker.played_total.get("10251120"), 1)
        backend.swipe.assert_called_once()
        self.assertTrue(any(call.kwargs["state"] == "tracking" for call in events.call_args_list))
        self.assertEqual(events.call_args.kwargs["state"], "uncertain")

    @staticmethod
    def _runner_with_backend(backend) -> BattleRunner:
        catalog = CardCatalogRepository.for_project(PROJECT_ROOT).load()
        profile = BattleProfileRepository.for_project(PROJECT_ROOT, catalog).load(
            "aggro_nightmare"
        )
        # These unit tests exercise the legacy timing and individual helpers.
        # Interleaved complete turns are covered by test_battle_tactics.
        profile = replace(profile, attack=replace(profile.attack, resume_play=False))
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

    def test_player_turn_recognition_excludes_generic_turn_label(self) -> None:
        pipeline = json.loads(
            (PROJECT_ROOT / "assets" / "resource" / "pipeline" / "battle.json")
            .read_text(encoding="utf-8")
        )

        expected = pipeline["识别_基础战斗玩家回合"]["expected"]
        self.assertEqual(expected, ["结束", "結束"])
        self.assertNotIn("回合", expected)

    def test_hand_observation_expands_from_calibrated_fan_point(self) -> None:
        for hand_count in (4, 5):
            with self.subTest(hand_count=hand_count):
                backend = _HandObservationBackend(hand_count=hand_count)
                runner = self._runner_with_backend(backend)

                with patch("runtime.battle_runner.time.sleep"):
                    observed = runner._observe_hand(energy=1)

                self.assertEqual(backend.taps, [(1025, 665)])
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

    def test_hand_observation_keeps_expanded_state_across_repeated_reads(self) -> None:
        backend = _HandObservationBackend(hand_count=4)
        runner = self._runner_with_backend(backend)

        with patch("runtime.battle_runner.time.sleep"):
            runner._observe_hand(energy=1)
            runner._observe_hand(energy=1)

        self.assertEqual(backend.taps, [(1025, 665)])
        self.assertEqual(backend.recognize_calls, 2)

    def test_hand_observation_rechecks_and_retries_failed_expansion(self) -> None:
        collapsed = SimpleNamespace(
            hit=True,
            all_results=(
                SimpleNamespace(
                    text="怨恨的栽培者", box=[803, 624, 45, 10]
                ),
            ),
        )
        expanded = SimpleNamespace(
            hit=True,
            all_results=(
                SimpleNamespace(
                    text="怨恨的栽培者", box=[700, 580, 100, 20]
                ),
            ),
        )
        backend = _HandObservationBackend(
            hand_count=5,
            recognition_results=(collapsed, expanded),
        )
        runner = self._runner_with_backend(backend)

        with patch("runtime.battle_runner.time.sleep"):
            observed = runner._observe_hand(energy=1)

        self.assertEqual(backend.taps, [(1025, 665), (1025, 665)])
        self.assertIsNotNone(observed)
        self.assertEqual(backend.recognize_calls, 2)

    def test_hand_observation_does_not_treat_collapsed_hand_as_empty(self) -> None:
        collapsed = SimpleNamespace(
            hit=True,
            all_results=(
                SimpleNamespace(
                    text="怨恨的栽培者", box=[803, 624, 45, 10]
                ),
            ),
        )
        backend = _HandObservationBackend(
            hand_count=5,
            recognition_results=(collapsed, collapsed),
        )
        runner = self._runner_with_backend(backend)

        with patch("runtime.battle_runner.time.sleep"):
            observed = runner._observe_hand(energy=1)

        self.assertIsNone(observed)
        self.assertEqual(backend.taps, [(1025, 665), (1025, 665)])
        self.assertEqual(backend.recognize_calls, 2)

    def test_expanded_hand_geometry_ignores_collapsed_titles_and_leader_hp(self) -> None:
        from battle_engine.observer import HandText

        self.assertFalse(
            BattleRunner._hand_texts_are_expanded(
                (
                    HandText("20", 751, 553, 44, 37),
                    HandText("蛇神之怒", 803, 624, 45, 10),
                )
            )
        )
        self.assertTrue(
            BattleRunner._hand_texts_are_expanded(
                (HandText("蛇神之怒", 433, 580, 53, 17),)
            )
        )

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

        self.assertEqual(backend.taps, [(1025, 665)])

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

    def test_existing_follower_evolution_uses_default_board_order(self) -> None:
        backend = _EvolutionBackend(ally_count=2, recognition_results=(False, True))
        runner = self._runner_with_backend(backend)

        with patch("runtime.battle_runner.time.sleep"):
            evolved = runner._try_evolve_existing_follower()

        self.assertTrue(evolved)
        self.assertEqual(backend.taps, [(550, 465), (730, 465)])
        self.assertEqual(
            backend.recognitions,
            [
                ("识别_进化按钮", 900, 150),
                ("识别_进化按钮", 900, 150),
            ],
        )

    def test_post_play_evolution_prioritizes_storm_follower(self) -> None:
        backend = _EvolutionBackend(ally_count=2, recognition_results=(True,))
        runner = self._runner_with_backend(backend)

        with patch("runtime.battle_runner.time.sleep"):
            evolved = runner._try_evolve_played_followers(
                ("10251120", "10253120")
            )

        self.assertTrue(evolved)
        self.assertEqual(backend.taps, [(730, 465)])
        self.assertEqual(
            backend.recognitions,
            [("识别_进化按钮", 900, 150)],
        )

    def test_successful_start_evolution_skips_post_play_evolution(self) -> None:
        runner = self._runner_with_backend(_EvolutionBackend(0, ()))
        runner.policy = BattlePolicy(replace(runner.policy.profile, evolution=replace(
            runner.policy.profile.evolution, after_play=False,
        )), runner.catalog)

        with (
            patch.object(
                runner, "_try_evolve_existing_follower", return_value=True
            ) as existing,
            patch.object(
                runner, "_play_cards", return_value=("10051130",)
            ) as play_cards,
            patch.object(runner, "_try_evolve_played_followers") as post_play,
            patch.object(runner, "_attack_phase") as attack,
        ):
            runner._execute_turn()

        existing.assert_called_once_with()
        play_cards.assert_called_once_with()
        post_play.assert_not_called()
        attack.assert_called_once_with()

    def test_failed_start_evolution_retries_after_playing_followers(self) -> None:
        runner = self._runner_with_backend(_EvolutionBackend(0, ()))
        runner.policy = BattlePolicy(replace(runner.policy.profile, evolution=replace(
            runner.policy.profile.evolution, after_play=False,
        )), runner.catalog)

        with (
            patch.object(
                runner, "_try_evolve_existing_follower", return_value=False
            ),
            patch.object(runner, "_play_cards", return_value=("10051130",)),
            patch.object(
                runner, "_try_evolve_played_followers", return_value=True
            ) as post_play,
            patch.object(runner, "_attack_phase"),
        ):
            runner._execute_turn()

        post_play.assert_called_once_with(("10051130",))

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

    def test_after_play_evolution_waits_for_play_and_precedes_attacks(self) -> None:
        runner = self._runner_with_backend(_EvolutionBackend(0, ()))
        calls: list[str] = []
        with (
            patch.object(runner, "_play_cards", side_effect=lambda: calls.append("play")),
            patch.object(runner, "_try_evolve_after_play", side_effect=lambda: calls.append("evolve")),
            patch.object(runner, "_try_evolve_existing_follower") as before,
            patch.object(runner, "_attack_phase", side_effect=lambda: calls.append("attack")),
        ):
            runner._execute_turn()
        self.assertEqual(calls, ["play", "evolve", "attack"])
        before.assert_not_called()

    def test_summons_do_not_shift_the_known_storm_identity_to_a_token(self) -> None:
        backend = _EvolutionBackend(ally_count=4, recognition_results=(True,))
        runner = self._runner_with_backend(backend)
        runner._turn_followers = [("10253120", False)]
        runner._record_follower_positions("10851130", before_count=1)
        self.assertEqual(runner._turn_followers, [
            ("10253120", False), ("10851130", False), (None, False), (None, False),
        ])
        with patch("runtime.battle_runner.time.sleep"):
            self.assertTrue(runner._try_evolve_after_play())
        self.assertEqual(backend.taps, [(400, 465)])

    def test_existing_body_is_preferred_over_new_conditional_storm(self) -> None:
        backend = _EvolutionBackend(ally_count=2, recognition_results=(True,))
        runner = self._runner_with_backend(backend)
        runner._turn_followers = [(None, True), ("10051130", False)]
        with patch("runtime.battle_runner.time.sleep"):
            runner._try_evolve_after_play()
        self.assertEqual(backend.taps, [(550, 465)])

    def test_known_storm_can_receive_evolution_before_existing_body(self) -> None:
        backend = _EvolutionBackend(ally_count=2, recognition_results=(True,))
        runner = self._runner_with_backend(backend)
        runner._turn_followers = [(None, True), ("10253120", False)]
        with patch("runtime.battle_runner.time.sleep"):
            runner._try_evolve_after_play()
        self.assertEqual(backend.taps, [(730, 465)])

    def test_uncertain_body_changes_invalidate_evolution_identity(self) -> None:
        backend = _EvolutionBackend(ally_count=2, recognition_results=(True,))
        runner = self._runner_with_backend(backend)
        runner._turn_followers = [("10253120", False), (None, True)]
        runner._record_follower_positions("10253120", before_count=2)
        self.assertEqual(runner._turn_followers, [(None, False), (None, False)])

    def test_attack_order_uses_stats_and_reindexes_after_middle_attacker_dies(self) -> None:
        backend = MagicMock(spec=MaaBackend)
        backend.swipe.return_value = True
        backend.observe_board_state.side_effect = [
            ObservedBoardState(3, 1, (1,)),
            ObservedBoardState(3, 1, (1,), (5, 1, 3)),
            ObservedBoardState(2, 0, (), (5, 3)),
            ObservedBoardState(2, 0, (), (5, 3)),
        ]
        runner = self._runner_with_backend(backend)
        with patch("runtime.battle_runner.time.sleep"):
            runner._attack_phase()
        self.assertEqual([call.args[:2] for call in backend.swipe.call_args_list], [
            (640, 465), (730, 465), (550, 465),
        ])
        self.assertEqual(backend.swipe.call_args_list[0].args[2:4], (640, 265))
        self.assertEqual(backend.swipe.call_args_list[1].args[2:4], (640, 70))

    def test_attack_configuration_selects_highest_or_leftmost_and_otherwise_target(self) -> None:
        for order, first_x in (("highest_attack_first", 820), ("left_to_right", 460)):
            with self.subTest(order=order):
                backend = MagicMock(spec=MaaBackend)
                backend.swipe.return_value = True
                backend.observe_board_state.return_value = ObservedBoardState(3, 1, (), (1, 2, 5))
                runner = self._runner_with_backend(backend)
                runner.policy = BattlePolicy(replace(runner.policy.profile, attack=replace(
                    runner.policy.profile.attack, attacker_order=order, otherwise="enemy_follower",
                )), runner.catalog)
                with patch("runtime.battle_runner.time.sleep"):
                    runner._attack_phase()
                self.assertEqual(backend.swipe.call_args_list[0].args, (first_x, 465, 640, 265, 350))

    def test_declining_ward_clear_does_not_waste_attacks_on_blocked_leader(self) -> None:
        backend = MagicMock(spec=MaaBackend)
        backend.observe_board_state.return_value = ObservedBoardState(2, 1, (1,))
        runner = self._runner_with_backend(backend)
        runner.policy = BattlePolicy(replace(runner.policy.profile, attack=replace(
            runner.policy.profile.attack, clear_ward=False,
        )), runner.catalog)
        runner._attack_phase()
        backend.swipe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
