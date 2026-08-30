from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from solution_engine.executor import SolutionExecutor  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402
from solution_engine.models import Solution, SolutionError  # noqa: E402
from solution_engine.repository import SolutionRepository  # noqa: E402


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.change_success = True
        self.hand_counts: list[int | None] = []
        self.hand_expanded_states: list[bool | None] = []
        self.hand_probe_points: list[tuple[int, int]] = []

    def tap(self, x: int, y: int) -> bool:
        self.calls.append(("tap", x, y))
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> bool:
        self.calls.append(("swipe", x1, y1, x2, y2, duration_ms))
        return True

    def key(self, keycode: int) -> bool:
        self.calls.append(("key", keycode))
        return True

    def verify(self, pipeline_node: str) -> bool:
        self.calls.append(("verify", pipeline_node))
        return True

    def wait_recognition(
        self, pipeline_node: str, timeout_ms: int, interval_ms: int = 500
    ) -> bool:
        return True

    def wait_recognition_gone(
        self, pipeline_node: str, timeout_ms: int, interval_ms: int = 500
    ) -> bool:
        return True

    def capture_frame(self):
        return object()

    def read_hand_count(self) -> int | None:
        return self.hand_counts.pop(0) if self.hand_counts else None

    def hand_is_expanded(self, point) -> bool | None:
        self.hand_probe_points.append(point)
        return (
            self.hand_expanded_states.pop(0)
            if self.hand_expanded_states
            else None
        )

    def wait_changed(
        self, reference, roi, timeout_ms: int, threshold: float, settle_ms: int
    ) -> bool:
        return self.change_success

    def skip_dialogue(
        self,
        pipeline_node: str,
        click_x: int,
        click_y: int,
        max_clicks: int,
        interval_ms: int,
        stable_hits: int,
    ) -> bool:
        self.calls.append(
            (
                "skip_dialogue",
                pipeline_node,
                click_x,
                click_y,
                max_clicks,
                interval_ms,
                stable_hits,
            )
        )
        return True


class SolutionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.solution_dir = PROJECT_ROOT / "assets" / "resource" / "solutions"
        self.layout = BoardLayout.load(
            PROJECT_ROOT / "assets" / "resource" / "layouts" / "default.json"
        )

    def test_demo_solution_loads_and_executes(self) -> None:
        solution = SolutionRepository(PROJECT_ROOT / "docs" / "examples").load(
            "puzzle_demo"
        )
        backend = FakeBackend()
        with patch("solution_engine.executor.time.sleep"):
            SolutionExecutor(
                backend, logging.getLogger("test"), self.layout
            ).execute(solution)
        self.assertEqual(backend.calls[0], ("tap", 1025, 665))
        self.assertEqual(backend.calls[1], ("swipe", 420, 665, 640, 430, 350))
        self.assertEqual(backend.calls[-1], ("tap", 1170, 350))

    def test_change_postcondition_stops_failed_solution(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "change_failure",
                "name": "change failure",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "end_turn",
                        "change_roi": "battle_board",
                        "post_timeout_ms": 500,
                    }
                ],
            }
        )
        backend = FakeBackend()
        backend.change_success = False
        with self.assertRaisesRegex(SolutionError, "盘面没有发生预期变化"):
            SolutionExecutor(backend, layout=self.layout).execute(solution)

    def test_targeted_spell_uses_hand_and_target_indexes(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "targeted_spell",
                "name": "targeted spell",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "play_card",
                        "hand_index": 2,
                        "hand_count": 3,
                        "target_delay_ms": 0,
                        "target": {
                            "type": "enemy_follower",
                            "index": 1,
                            "count": 2,
                        },
                    }
                ],
            }
        )
        backend = FakeBackend()
        SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(
            backend.calls,
            [
                ("tap", 1025, 665),
                ("swipe", 640, 665, 640, 430, 350),
                ("tap", 550, 265),
            ],
        )

    def test_targeted_spell_reexpands_hand_before_next_card(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "targeted_spell_then_card",
                "name": "targeted spell then card",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "play_card",
                        "hand_index": 1,
                        "hand_count": 2,
                        "target_delay_ms": 0,
                        "target": {
                            "type": "enemy_follower",
                            "index": 1,
                            "count": 1,
                        },
                    },
                    {
                        "action": "play_card",
                        "hand_index": 2,
                        "hand_count": 2,
                        "expand_delay_ms": 0,
                    },
                ],
            }
        )
        backend = FakeBackend()
        SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(
            backend.calls,
            [
                ("tap", 1025, 665),
                ("swipe", 600, 665, 640, 430, 350),
                ("tap", 640, 265),
                ("tap", 1025, 665),
                ("swipe", 750, 665, 640, 430, 350),
            ],
        )

    def test_live_hand_count_mismatch_stops_solution(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "live_hand_count",
                "name": "live hand count",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "play_card",
                        "hand_index": 2,
                        "hand_count": 3,
                        "expand_delay_ms": 0,
                    }
                ],
            }
        )
        backend = FakeBackend()
        backend.hand_counts = [4]
        backend.hand_expanded_states = [False]
        with self.assertRaisesRegex(SolutionError, "与脚本预期的 3 张不一致"):
            SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(backend.calls, [])

    def test_collapsed_hand_is_reexpanded_after_ordinary_card(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "ordinary_card_collapses_hand",
                "name": "ordinary card collapses hand",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {"action": "play_card", "hand_index": 1, "hand_count": 2},
                    {"action": "play_card", "hand_index": 1, "hand_count": 1},
                ],
            }
        )
        backend = FakeBackend()
        backend.hand_expanded_states = [False, False]
        with patch("solution_engine.executor.time.sleep"):
            SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(
            backend.calls,
            [
                ("tap", 1025, 665),
                ("swipe", 600, 665, 640, 430, 350),
                ("tap", 1025, 665),
                ("swipe", 675, 665, 640, 430, 350),
            ],
        )

    def test_rightmost_card_uses_leftmost_expansion_probe(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "rightmost_card_probe",
                "name": "rightmost card probe",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "play_card",
                        "hand_index": 5,
                        "hand_count": 5,
                        "expand_delay_ms": 0,
                    }
                ],
            }
        )
        backend = FakeBackend()
        backend.hand_counts = [5]
        backend.hand_expanded_states = [False]

        SolutionExecutor(backend, layout=self.layout).execute(solution)

        self.assertEqual(backend.hand_probe_points, [(420, 665)])
        self.assertEqual(
            backend.calls,
            [
                ("tap", 1025, 665),
                ("swipe", 860, 665, 640, 430, 350),
            ],
        )

    def test_choice_uses_semantic_index_and_reexpands_hand(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "choice_then_card",
                "name": "choice then card",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "play_card",
                        "hand_index": 1,
                        "hand_count": 2,
                        "expand_delay_ms": 0,
                    },
                    {
                        "action": "select_choice",
                        "choice_index": 2,
                        "choice_count": 2,
                    },
                    {
                        "action": "play_card",
                        "hand_index": 1,
                        "hand_count": 1,
                        "expand_delay_ms": 0,
                    },
                ],
            }
        )
        backend = FakeBackend()
        SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(
            backend.calls,
            [
                ("tap", 1025, 665),
                ("swipe", 600, 665, 640, 430, 350),
                ("tap", 770, 415),
                ("tap", 1025, 665),
                ("swipe", 675, 665, 640, 430, 350),
            ],
        )

    def test_first_puzzle_uses_semantic_indexes(self) -> None:
        solution = SolutionRepository(self.solution_dir).load("puzzle_001")
        navigation = solution.navigation
        assert navigation is not None
        self.assertEqual(
            navigation["display_name"],
            "同时学习【守护】【突进】【疾驰】吧！",
        )
        self.assertEqual(
            [item["display_name"] for item in navigation["categories"]],
            ["盘面解密", "指定系列", "基本能力①"],
        )
        backend = FakeBackend()
        with patch("solution_engine.executor.time.sleep"):
            SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(
            backend.calls,
            [
                ("tap", 1025, 665),
                ("swipe", 750, 665, 640, 430, 350),
                ("swipe", 675, 665, 640, 430, 350),
                ("swipe", 550, 465, 640, 265, 300),
                ("swipe", 640, 465, 640, 70, 300),
            ],
        )

    def test_navigation_requires_name_fields(self) -> None:
        with self.assertRaises(SolutionError):
            Solution.from_dict(
                {
                    "id": "bad_navigation",
                    "name": "bad navigation",
                    "category": "puzzle",
                    "reference_resolution": [1280, 720],
                    "navigation": {"display_name": "missing pattern"},
                    "steps": [{"action": "wait", "duration_ms": 1}],
                }
            )

    def test_attack_uses_follower_indexes(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "attack_test",
                "name": "attack test",
                "category": "puzzle",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "attack",
                        "attacker_index": 2,
                        "ally_count": 3,
                        "target": {
                            "type": "enemy_follower",
                            "index": 2,
                            "count": 2,
                        },
                    }
                ],
            }
        )
        backend = FakeBackend()
        SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(backend.calls, [("swipe", 640, 465, 730, 265, 300)])

    def test_skip_dialogue_uses_global_layout_point(self) -> None:
        solution = Solution.from_dict(
            {
                "id": "skip_dialogue_test",
                "name": "skip dialogue test",
                "category": "tutorial",
                "reference_resolution": [1280, 720],
                "steps": [
                    {
                        "action": "skip_dialogue",
                        "pipeline_node": "识别_教程主战者框可操作",
                        "max_clicks": 30,
                        "interval_ms": 350,
                        "stable_hits": 2,
                    }
                ],
            }
        )
        backend = FakeBackend()
        SolutionExecutor(backend, layout=self.layout).execute(solution)
        self.assertEqual(
            backend.calls,
            [
                (
                    "skip_dialogue",
                    "识别_教程主战者框可操作",
                    640,
                    635,
                    30,
                    350,
                    2,
                )
            ],
        )

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(SolutionError):
            SolutionRepository(self.solution_dir).load("../secret")

    def test_source_project_layout_is_discovered(self) -> None:
        repository = SolutionRepository.for_project(PROJECT_ROOT)
        self.assertEqual(repository.root, self.solution_dir.resolve())

    def test_packaged_project_layout_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            solution_dir = Path(temp_dir) / "resource" / "solutions"
            solution_dir.mkdir(parents=True)
            repository = SolutionRepository.for_project(Path(temp_dir))
            self.assertEqual(repository.root, solution_dir.resolve())

    def test_file_id_must_match_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "expected.json"
            path.write_text(
                json.dumps(
                    {
                        "id": "different",
                        "name": "test",
                        "category": "puzzle",
                        "reference_resolution": [1280, 720],
                        "steps": [{"action": "wait", "duration_ms": 0}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SolutionError):
                SolutionRepository(Path(temp_dir)).load("expected")


if __name__ == "__main__":
    unittest.main()
