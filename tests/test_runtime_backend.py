from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from runtime.backend import MaaBackend  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402


class RuntimeBackendTests(unittest.TestCase):
    def backend(self) -> MaaBackend:
        return MaaBackend(MagicMock(), BoardLayout.load(
            PROJECT_ROOT / "assets/resource/layouts/default.json",
        ))

    def test_attack_digits_use_same_frame_and_separate_blue_stat_rois(self) -> None:
        backend = self.backend()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for x in (440, 760):
            frame[425:470, x - 8:x + 8] = [200, 40, 30]
        recognition = MagicMock(side_effect=[
            SimpleNamespace(hit=True, all_results=[SimpleNamespace(text="5")]),
            SimpleNamespace(hit=True, all_results=[SimpleNamespace(text="0")]),
        ])
        with patch.object(backend.context, "run_recognition", recognition), patch.object(backend, "capture_frame") as capture:
            self.assertEqual(backend.read_follower_attacks(2, frame=frame), (5, 0))
        capture.assert_not_called()
        calls = recognition.call_args_list
        self.assertIs(calls[0].args[1], frame)
        for call, x in zip(calls, (440, 760)):
            roi = call.args[2]["识别_基础战斗随从攻击力"]["roi"]
            self.assertLessEqual(roi[0], x)
            self.assertGreater(roi[0] + roi[2], x)
            self.assertLess(roi[2], 60)

    def test_attack_ocr_missing_or_ambiguous_digits_remain_unknown(self) -> None:
        backend = self.backend()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        results = (
            SimpleNamespace(hit=False, all_results=[]),
            SimpleNamespace(hit=True, all_results=[SimpleNamespace(text="3"), SimpleNamespace(text="4")]),
            SimpleNamespace(hit=True, all_results=[SimpleNamespace(text="-1")]),
        )
        for detail in results:
            with self.subTest(detail=detail), patch.object(backend, "_follower_stat_peaks", return_value=(440,)), patch.object(backend, "recognize", return_value=detail):
                self.assertEqual(backend.read_follower_attacks(1, frame=frame), (None,))

    def test_attack_ocr_reads_only_requested_indexes_and_preserves_positions(self) -> None:
        backend = self.backend()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with (
            patch.object(backend, "_follower_stat_peaks", return_value=(300, 500, 700)),
            patch.object(backend, "recognize", return_value=SimpleNamespace(
                hit=True, all_results=[SimpleNamespace(text="4")],
            )) as recognize,
        ):
            self.assertEqual(backend.read_follower_attacks(3, frame=frame, indexes=(2,)), (None, 4, None))
            recognize.assert_called_once()
            recognize.reset_mock()
            self.assertEqual(backend.read_follower_attacks(3, frame=frame, indexes=()), (None, None, None))
            recognize.assert_not_called()

    def test_board_attack_observation_is_opt_in_and_reuses_the_count_frame(self) -> None:
        backend = self.backend()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with (
            patch.object(backend, "capture_frame", return_value=frame) as capture,
            patch.object(backend, "read_follower_count", return_value=2),
            patch.object(backend, "read_ward_indexes", return_value=()),
            patch.object(backend, "read_follower_attacks", return_value=(1, 4)) as attacks,
        ):
            board = backend.observe_board_state()
            assert board is not None
            self.assertEqual(board.ally_attacks, ())
            attacks.assert_not_called()
            board = backend.observe_board_state(include_attacks=True)
            assert board is not None
            self.assertEqual(board.ally_attacks, (1, 4))
            attacks.assert_called_once_with(2, frame=frame)
            self.assertEqual(capture.call_count, 2)
    def test_energy_text_with_visible_separator(self) -> None:
        self.assertEqual(MaaBackend._parse_energy_text("2/3"), (2, 3))
        self.assertEqual(MaaBackend._parse_energy_text("10|10"), (10, 10))

    def test_health_requires_two_complete_matching_samples_and_uses_hand_geometry(self) -> None:
        backend = self.backend()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for expanded, expected_y in ((False, 545), (True, 500)):
            recognition = MagicMock(side_effect=[
                SimpleNamespace(hit=True, all_results=[SimpleNamespace(text=value)])
                for value in ("20", "3", "20", "3")
            ])
            with (
                patch.object(backend, "capture_frame", return_value=frame),
                patch.object(backend.context, "run_recognition", recognition),
                patch("runtime.backend.time.sleep"),
            ):
                health = backend.read_leader_health(hand_expanded=expanded)
            assert health is not None
            self.assertEqual((health.ally, health.enemy), (20, 3))
            roi = recognition.call_args_list[0].args[2]["识别_基础战斗主战者生命值"]["roi"]
            self.assertEqual(roi[1], expected_y)
            self.assertTrue(all(call.args[1] is frame for call in recognition.call_args_list))

    def test_health_rejects_changed_missing_and_malformed_observations(self) -> None:
        backend = self.backend()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for samples in (("20", "3", "20", "4"), ("0",), ("3/3",), ("100",), ("-2",)):
            with (
                self.subTest(samples=samples),
                patch.object(backend, "capture_frame", return_value=frame),
                patch.object(backend, "recognize", side_effect=[
                    SimpleNamespace(hit=True, all_results=[SimpleNamespace(text=value)]) for value in samples
                ]),
                patch("runtime.backend.time.sleep"),
            ):
                self.assertIsNone(backend.read_leader_health())
        with patch.object(backend, "capture_frame", return_value=None):
            self.assertIsNone(backend.read_leader_health())

    def test_energy_text_with_slash_recognized_as_one(self) -> None:
        self.assertEqual(MaaBackend._parse_energy_text("313"), (3, 3))
        self.assertEqual(MaaBackend._parse_energy_text("213"), (2, 3))
        self.assertEqual(MaaBackend._parse_energy_text("10110"), (10, 10))

    def test_energy_text_without_separator(self) -> None:
        self.assertEqual(MaaBackend._parse_energy_text("33"), (3, 3))
        self.assertEqual(MaaBackend._parse_energy_text("1010"), (10, 10))
        self.assertEqual(MaaBackend._parse_energy_text("010"), (0, 10))
        self.assertIsNone(MaaBackend._parse_energy_text("0/0"))
        self.assertIsNone(MaaBackend._parse_energy_text("energy"))


if __name__ == "__main__":
    unittest.main()
