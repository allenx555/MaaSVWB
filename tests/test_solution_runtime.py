from __future__ import annotations

import sys
import json
import unittest
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, MagicMock, call, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from runtime.backend import MaaBackend  # noqa: E402
from runtime.puzzle_navigator import PuzzleNavigator  # noqa: E402
from runtime.runner import reset_puzzle_for_debug, wait_for_puzzle_list  # noqa: E402
from actions.execute_solution import ExecuteSolution  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402


class _SuccessfulJob:
    succeeded = True

    def wait(self):
        return self


class SolutionRuntimeTests(unittest.TestCase):
    def make_backend(self, hits: list[bool]) -> tuple[Any, PuzzleNavigator, Any]:
        controller = SimpleNamespace(
            cached_image=object(),
            post_screencap=MagicMock(side_effect=lambda: _SuccessfulJob()),
            post_click=MagicMock(side_effect=lambda _x, _y: _SuccessfulJob()),
            post_swipe=MagicMock(
                side_effect=lambda _x1, _y1, _x2, _y2, _duration: _SuccessfulJob()
            ),
        )
        context = SimpleNamespace(
            tasker=SimpleNamespace(controller=controller),
            run_recognition=MagicMock(
                side_effect=[SimpleNamespace(hit=hit) for hit in hits]
            ),
        )
        layout = BoardLayout.load(
            PROJECT_ROOT / "assets" / "resource" / "layouts" / "default.json"
        )
        backend = cast(Any, MaaBackend(cast(Any, context), layout))
        return backend, PuzzleNavigator(backend), controller

    @patch("runtime.runner.time.sleep")
    def test_reward_screen_is_dismissed_before_waiting_for_puzzle_list(
        self, _sleep: MagicMock
    ) -> None:
        backend = MagicMock()
        backend.is_stopping.return_value = False
        backend.verify.side_effect = [False, True, False, False, True]
        backend.tap.return_value = True

        result = wait_for_puzzle_list(
            backend, (640, 650), timeout_ms=5_000, interval_ms=100
        )

        self.assertTrue(result)
        backend.tap.assert_called_once_with(640, 650)
        self.assertEqual(
            [item.args[0] for item in backend.verify.call_args_list],
            [
                "识别_盘面解密列表",
                "识别_盘面解密奖励领取",
                "识别_盘面解密列表",
                "识别_盘面解密奖励领取",
                "识别_盘面解密列表",
            ],
        )

    @patch("runtime.runner.time.sleep")
    def test_reward_screen_is_retried_until_it_disappears(
        self, _sleep: MagicMock
    ) -> None:
        backend = MagicMock()
        backend.is_stopping.return_value = False
        backend.verify.side_effect = [False, True, False, True, True]
        backend.tap.return_value = True

        result = wait_for_puzzle_list(
            backend, (640, 650), timeout_ms=5_000, interval_ms=100
        )

        self.assertTrue(result)
        self.assertEqual(backend.tap.call_count, 2)
        backend.tap.assert_called_with(640, 650)

    @patch("actions.execute_solution.run_solution")
    def test_shared_custom_action_forwards_batch_option(
        self, run_solution: MagicMock
    ) -> None:
        argv = SimpleNamespace(
            custom_action_param=json.dumps(
                {
                    "solution": "puzzle_001",
                    "skip_completed": True,
                    "reset_before_execute": True,
                }
            ),
            node_name="执行解法",
        )

        self.assertTrue(
            ExecuteSolution().run(cast(Any, SimpleNamespace()), cast(Any, argv))
        )
        run_solution.assert_called_once_with(
            ANY,
            "puzzle_001",
            skip_completed=True,
            reset_before_execute=True,
            start_step=1,
        )

    @patch("runtime.runner.time.sleep")
    def test_debug_reset_uses_layout_point(self, sleep: MagicMock) -> None:
        backend = MagicMock()
        backend.tap.return_value = True
        layout = MagicMock()
        layout.fixed_point.return_value = (105, 220)

        reset_puzzle_for_debug(backend, layout)

        layout.fixed_point.assert_called_once_with("puzzle_reset")
        backend.tap.assert_called_once_with(105, 220)
        sleep.assert_called_once_with(1.2)

    @patch("runtime.backend.time.sleep")
    def test_already_operable_does_not_click(self, _sleep: MagicMock) -> None:
        backend, _navigator, controller = self.make_backend([True, True])

        result = backend.skip_dialogue(
            "识别_教程主战者框可操作", 640, 635, 30, 350, 2
        )

        self.assertTrue(result)
        controller.post_click.assert_not_called()

    @patch("runtime.backend.time.sleep")
    def test_stops_clicking_as_soon_as_operable(self, _sleep: MagicMock) -> None:
        backend, _navigator, controller = self.make_backend([False, True, True])

        result = backend.skip_dialogue(
            "识别_教程主战者框可操作", 640, 635, 30, 350, 2
        )

        self.assertTrue(result)
        controller.post_click.assert_called_once_with(640, 635)

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_select_puzzle_clicks_ocr_box_then_confirm(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        backend.context.run_recognition.side_effect = [
            SimpleNamespace(
                hit=True,
                box=SimpleNamespace(x=97, y=464, w=250, h=21),
            ),
            SimpleNamespace(
                hit=True,
                box=SimpleNamespace(x=98, y=465, w=250, h=21),
            ),
            SimpleNamespace(hit=True, box=SimpleNamespace(x=1060, y=425, w=150, h=150)),
        ]

        result = navigator.select_puzzle(
            ".*守护.*疾驰.*", 1135, 500, (430, 260), (430, 570), 20
        )

        self.assertTrue(result)
        self.assertEqual(result, "selected")
        self.assertEqual(
            controller.post_click.call_args_list,
            [
                call(223, 475),
                call(1135, 500),
            ],
        )
        controller.post_swipe.assert_not_called()

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_select_puzzle_searches_by_swiping(self, _sleep: MagicMock) -> None:
        backend, navigator, controller = self.make_backend([])
        backend.context.run_recognition.side_effect = [
            SimpleNamespace(hit=False, box=None),
            SimpleNamespace(
                hit=True,
                box=SimpleNamespace(x=100, y=300, w=200, h=30),
            ),
            SimpleNamespace(
                hit=True,
                box=SimpleNamespace(x=101, y=301, w=200, h=30),
            ),
            SimpleNamespace(hit=True, box=SimpleNamespace(x=1060, y=425, w=150, h=150)),
        ]

        result = navigator.select_puzzle(
            ".*守护.*疾驰.*", 1135, 500, (430, 260), (430, 570), 20
        )

        self.assertTrue(result)
        self.assertEqual(result, "selected")
        controller.post_swipe.assert_called_once_with(430, 570, 430, 260, 900)
        self.assertEqual(
            controller.post_click.call_args_list,
            [
                call(201, 316),
                call(1135, 500),
            ],
        )

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_select_puzzle_does_not_click_when_ocr_misses(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        backend.context.run_recognition.side_effect = None
        backend.context.run_recognition.return_value = SimpleNamespace(
            hit=False, box=None
        )

        result = navigator.select_puzzle(
            ".*守护.*疾驰.*", 1135, 500, (430, 260), (430, 570), 2
        )

        self.assertFalse(result)
        controller.post_click.assert_not_called()
        self.assertEqual(controller.post_swipe.call_count, 4)

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_select_puzzle_skips_completed_and_claimed_row(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        name_box = SimpleNamespace(x=91, y=447, w=270, h=25)
        backend.context.run_recognition.side_effect = [
            SimpleNamespace(hit=True, box=name_box),
            SimpleNamespace(hit=True, box=name_box),
            SimpleNamespace(hit=True, box=SimpleNamespace(x=68, y=420, w=42, h=24)),
            SimpleNamespace(hit=True, box=SimpleNamespace(x=422, y=443, w=63, h=28)),
        ]

        result = navigator.select_puzzle(
            ".*守护.*疾驰.*",
            1135,
            500,
            (430, 260),
            (430, 570),
            20,
            skip_completed=True,
        )

        self.assertEqual(result, "completed")
        controller.post_click.assert_not_called()
        completion_override = backend.context.run_recognition.call_args_list[2].args[2]
        claimed_override = backend.context.run_recognition.call_args_list[3].args[2]
        self.assertEqual(
            completion_override["识别_盘面解密完成标记"]["roi"],
            [55, 402, 105, 90],
        )
        self.assertEqual(
            claimed_override["识别_盘面解密已领取"]["roi"],
            [390, 402, 130, 90],
        )

    def test_completed_status_requires_both_markers(self) -> None:
        _backend, navigator, _controller = self.make_backend([True, False])
        name_detail = SimpleNamespace(
            hit=True,
            box=SimpleNamespace(x=91, y=447, w=270, h=25),
        )

        self.assertFalse(navigator.is_puzzle_completed(name_detail))

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_confirms_tabs_then_expands_list_category(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        backend.context.run_recognition.side_effect = [
            SimpleNamespace(
                hit=True, box=SimpleNamespace(x=90, y=95, w=140, h=30)
            ),
            SimpleNamespace(
                hit=True, box=SimpleNamespace(x=95, y=150, w=130, h=30)
            ),
            SimpleNamespace(
                hit=True, box=SimpleNamespace(x=70, y=220, w=180, h=35)
            ),
            SimpleNamespace(
                hit=True, box=SimpleNamespace(x=70, y=220, w=180, h=35)
            ),
        ]
        categories = [
            {"display_name": "盘面解谜", "pattern": "盘面解谜", "scope": "tab"},
            {"display_name": "指定系列", "pattern": "指定系列", "scope": "tab"},
            {"display_name": "基本能力①", "pattern": "基本能力①", "scope": "list"},
        ]

        result = navigator.confirm_categories(
            categories, (430, 260), (430, 570), 20
        )

        self.assertTrue(result)
        self.assertEqual(
            controller.post_click.call_args_list,
            [
                call(160, 110),
                call(160, 165),
                call(160, 237),
            ],
        )
        controller.post_swipe.assert_not_called()

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_activates_category_until_decide_appears(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        category_box = SimpleNamespace(x=79, y=240, w=105, h=23)
        backend.context.run_recognition.side_effect = [
            SimpleNamespace(hit=True, box=category_box),
            SimpleNamespace(hit=True, box=category_box),
            SimpleNamespace(hit=True, box=category_box),
            SimpleNamespace(hit=True, box=category_box),
        ]
        backend.wait_recognition = MagicMock(side_effect=[False, True])

        result = navigator.activate_category(
            {
                "display_name": "基本能力①",
                "pattern": "基本能力(①|1)",
                "scope": "list",
            },
            (430, 260),
            (430, 570),
            2,
        )

        self.assertTrue(result)
        self.assertEqual(
            controller.post_click.call_args_list,
            [call(131, 251), call(131, 251)],
        )

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_expanded_category_is_not_clicked(self, _sleep: MagicMock) -> None:
        backend, navigator, controller = self.make_backend([])
        category_box = SimpleNamespace(x=79, y=240, w=105, h=23)
        backend.context.run_recognition.side_effect = [
            SimpleNamespace(hit=True, box=category_box),
            SimpleNamespace(hit=True, box=category_box),
        ]
        backend.category_expanded = MagicMock(return_value=True)

        result = navigator.activate_category(
            {
                "display_name": "基本能力①",
                "pattern": "基本能力(①|1)",
                "scope": "list",
            },
            (430, 260),
            (430, 570),
            0,
            ".*守护.*疾驰.*",
        )

        self.assertTrue(result)
        controller.post_click.assert_not_called()

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_category_suffix_is_verified_with_precise_ocr_roi(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        category_box = SimpleNamespace(x=78, y=513, w=97, h=23)
        base_detail = SimpleNamespace(hit=True, box=category_box)
        suffix_detail = SimpleNamespace(hit=True, box=category_box)
        backend.context.run_recognition.side_effect = [
            base_detail,
            base_detail,
            suffix_detail,
        ]
        backend.category_expanded = MagicMock(return_value=True)

        result = navigator.activate_category(
            {
                "display_name": "护符主教2",
                "pattern": "^护符主教$",
                "suffix_pattern": ".*(2|②)$",
                "scope": "list",
            },
            (430, 260),
            (430, 570),
            0,
        )

        self.assertTrue(result)
        suffix_override = backend.context.run_recognition.call_args_list[2].args[2]
        self.assertEqual(
            suffix_override["识别_盘面解密类别"],
            {
                "roi": [170, 505, 35, 39],
                "only_rec": True,
                "expected": ".*(2|②)$",
                "threshold": 0.1,
            },
        )
        controller.post_click.assert_not_called()

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_category_suffix_mismatch_rejects_wrong_group(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        category_box = SimpleNamespace(x=78, y=513, w=97, h=23)
        base_detail = SimpleNamespace(hit=True, box=category_box)
        suffix_miss = SimpleNamespace(hit=False, box=None)
        backend.context.run_recognition.side_effect = [
            base_detail,
            base_detail,
            suffix_miss,
        ]

        result = navigator.activate_category(
            {
                "display_name": "护符主教2",
                "pattern": "^护符主教$",
                "suffix_pattern": ".*(2|②)$",
                "scope": "list",
            },
            (430, 260),
            (430, 570),
            0,
            max_clicks=1,
        )

        self.assertFalse(result)
        controller.post_click.assert_not_called()

    @patch("runtime.puzzle_navigator.time.sleep")
    def test_collapsed_category_is_clicked_until_target_appears(
        self, _sleep: MagicMock
    ) -> None:
        backend, navigator, controller = self.make_backend([])
        category_box = SimpleNamespace(x=79, y=240, w=105, h=23)
        puzzle_box = SimpleNamespace(x=85, y=350, w=260, h=28)
        backend.context.run_recognition.side_effect = [
            SimpleNamespace(hit=True, box=category_box),
            SimpleNamespace(hit=True, box=category_box),
            SimpleNamespace(hit=True, box=puzzle_box),
            SimpleNamespace(hit=True, box=puzzle_box),
        ]
        backend.category_expanded = MagicMock(return_value=False)

        result = navigator.activate_category(
            {
                "display_name": "基本能力①",
                "pattern": "基本能力(①|1)",
                "scope": "list",
            },
            (430, 260),
            (430, 570),
            0,
            ".*守护.*疾驰.*",
        )

        self.assertTrue(result)
        controller.post_click.assert_called_once_with(131, 251)

    def test_category_arrow_direction_is_detected(self) -> None:
        backend, _navigator, controller = self.make_backend([])
        category_box = SimpleNamespace(x=79, y=240, w=105, h=23)
        center_y = category_box.y + category_box.h // 2 + 14

        def arrow_image(expanded: bool):
            image = np.zeros((720, 1280, 3), dtype=np.uint8)
            for offset in range(11):
                y = center_y - 8 + offset
                spread = offset if expanded else 10 - offset
                for x in (500 - spread, 500 + spread):
                    image[y - 1 : y + 2, x - 1 : x + 2] = 255
            return image

        controller.cached_image = arrow_image(True)
        self.assertTrue(backend.category_expanded(category_box))
        controller.cached_image = arrow_image(False)
        self.assertFalse(backend.category_expanded(category_box))

    def test_reads_current_hand_count_from_ocr(self) -> None:
        backend, _navigator, _controller = self.make_backend([])
        backend.context.run_recognition.side_effect = None
        backend.context.run_recognition.return_value = SimpleNamespace(
            hit=True,
            best_result=SimpleNamespace(text="5"),
        )

        self.assertEqual(backend.read_hand_count(), 5)

    def test_reads_current_energy_points_from_ocr(self) -> None:
        backend, _navigator, _controller = self.make_backend([])
        backend.context.run_recognition.side_effect = None
        backend.context.run_recognition.return_value = SimpleNamespace(
            hit=True,
            best_result=SimpleNamespace(text="1 / 1"),
        )

        self.assertEqual(backend.read_energy_points(), (1, 1))

    def test_reads_follower_counts_from_blue_attack_stats(self) -> None:
        backend, _navigator, controller = self.make_backend([])
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Maa 截图为 BGR；用蓝色块模拟攻击力数字。相邻杂色峰会被抑制。
        for x in (280, 440, 600, 760, 920):
            frame[425:470, x - 8 : x + 8] = [200, 40, 30]
        controller.cached_image = frame
        self.assertEqual(backend.read_follower_count("ally"), 5)

        frame = np.zeros_like(frame)
        frame[250:295, 580:596] = [200, 40, 30]
        controller.cached_image = frame
        self.assertEqual(backend.read_follower_count("enemy"), 1)

        controller.cached_image = np.zeros_like(frame)
        self.assertEqual(backend.read_follower_count("enemy"), 0)

    def test_explicit_failed_frame_does_not_trigger_second_capture(self) -> None:
        backend, _navigator, controller = self.make_backend([])
        controller.post_screencap.reset_mock()

        self.assertIsNone(backend.recognize("任意识别节点", frame=None))

        controller.post_screencap.assert_not_called()

    def test_hand_expansion_uses_highlight_pixels_at_probe_point(self) -> None:
        backend, _navigator, controller = self.make_backend([])
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Maa 截图是 BGR；在探测区放入足量青绿色高亮像素。
        frame[570:590, 410:430] = [200, 200, 50]
        controller.cached_image = frame

        self.assertTrue(backend.hand_is_expanded((420, 665)))

        controller.cached_image = np.zeros_like(frame)
        self.assertFalse(backend.hand_is_expanded((420, 665)))

    def test_replays_mumu_script_as_maa_click(self) -> None:
        backend, _navigator, controller = self.make_backend([])
        payload = {
            "actions": [
                {
                    "type": "touch",
                    "timing": 0,
                    "data": "press_rel:(0.3125,1.625)",
                    "extra1": "1",
                },
                {
                    "type": "touch",
                    "timing": 100,
                    "data": "release",
                    "extra1": "1",
                },
            ],
            "info": {
                "resolution_x": 1280,
                "resolution_y": 720,
                "total_running_time": 100,
            },
        }
        with (
            patch(
                "runtime.backend.Path.read_text",
                return_value=json.dumps(payload),
            ),
            patch.object(backend, "_sleep_interruptible", return_value=True),
        ):
            self.assertTrue(backend.replay_mumu_script("test.mmor"))

        controller.post_click.assert_called_once_with(1170, 320)
        controller.post_swipe.assert_not_called()

    def test_replays_mumu_script_as_maa_swipe(self) -> None:
        backend, _navigator, controller = self.make_backend([])
        payload = {
            "actions": [
                {
                    "type": "touch",
                    "timing": 10,
                    "data": "press_rel:(0.5,1.0)",
                    "extra1": "1",
                },
                {
                    "type": "touch",
                    "timing": 50,
                    "data": "press_rel:(0.4,0.8)",
                    "extra1": "1",
                },
                {
                    "type": "touch",
                    "timing": 100,
                    "data": "release",
                    "extra1": "1",
                },
            ],
            "info": {
                "resolution_x": 1280,
                "resolution_y": 720,
                "total_running_time": 160,
            },
        }
        with (
            patch(
                "runtime.backend.Path.read_text",
                return_value=json.dumps(payload),
            ),
            patch.object(backend, "_sleep_interruptible", return_value=True),
        ):
            self.assertTrue(backend.replay_mumu_script("test.mmor"))

        controller.post_click.assert_not_called()
        controller.post_swipe.assert_called_once_with(720, 80, 576, 208, 150)

    @patch("runtime.backend.time.sleep")
    def test_tap_recognition_clicks_detected_box_center(
        self, _sleep: MagicMock
    ) -> None:
        backend, _navigator, controller = self.make_backend([])
        backend.context.run_recognition.side_effect = None
        backend.context.run_recognition.return_value = SimpleNamespace(
            hit=True,
            box=SimpleNamespace(x=240, y=330, w=180, h=55),
        )

        self.assertTrue(backend.tap_recognition("识别_超进化按钮", 5000))
        controller.post_click.assert_called_once_with(330, 357)

    @patch("runtime.backend.time.sleep")
    def test_newly_entered_puzzle_accepts_stable_ready_without_overlay(
        self, _sleep: MagicMock
    ) -> None:
        backend, _navigator, controller = self.make_backend([True, True, True])

        with patch(
            "runtime.backend.time.monotonic",
            side_effect=[0.0, 0.0, 3.1, 3.2],
        ):
            result = backend.skip_dialogue(
                "识别_教程主战者框可操作",
                640,
                635,
                30,
                350,
                2,
                ready_grace_ms=3000,
            )

        self.assertTrue(result)
        controller.post_click.assert_not_called()

    @patch("runtime.backend.time.sleep")
    def test_overlay_resets_ready_grace_and_is_clicked(
        self, _sleep: MagicMock
    ) -> None:
        backend, _navigator, controller = self.make_backend([True, False, True, True, True, True])

        with patch(
            "runtime.backend.time.monotonic",
            side_effect=[0.0, 0.0, 0.5, 1.0, 1.0, 4.1, 4.2],
        ):
            result = backend.skip_dialogue(
                "识别_教程主战者框可操作",
                640,
                635,
                30,
                350,
                2,
                ready_grace_ms=3000,
            )

        self.assertTrue(result)
        controller.post_click.assert_called_once_with(640, 635)


if __name__ == "__main__":
    unittest.main()
