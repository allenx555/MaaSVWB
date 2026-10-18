from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT_ROOT / "agent"), str(PROJECT_ROOT / "tools")]

from run_android import start_stop_monitor  # noqa: E402
from runtime.backend import MaaBackend  # noqa: E402
from solution_engine.executor import SolutionExecutor  # noqa: E402
from solution_engine.layout import BoardLayout  # noqa: E402
from solution_engine.models import Solution, SolutionError  # noqa: E402


class _Job:
    succeeded = True

    def wait(self):
        return self


class StopIntegrationTests(unittest.TestCase):
    def test_running_solution_stops_posting_inputs_after_monitor_accepts_stop(self):
        following_steps = [
            {"action": "tap", "point": [2, 2]},
            {"action": "swipe", "from": [2, 2], "to": [3, 3]},
            {"action": "key", "keycode": 4},
        ]
        for following in following_steps:
            with self.subTest(action=following["action"]), tempfile.TemporaryDirectory() as temporary:
                marker = Path(temporary) / "run.stop"
                done, stopped, stop_accepted = (threading.Event() for _ in range(3))
                controller = SimpleNamespace(post_click=MagicMock(), post_swipe=MagicMock(), post_click_key=MagicMock())
                tasker = SimpleNamespace(controller=controller, stopping=False, post_stop=MagicMock())

                def stop():
                    tasker.stopping = True
                    stop_accepted.set()
                    return _Job()

                def first_click(*_args):
                    marker.write_text("stop", encoding="utf-8")
                    self.assertTrue(stop_accepted.wait(2), "Stop monitor did not accept the request")
                    return _Job()

                tasker.post_stop.side_effect = stop
                controller.post_click.side_effect = first_click
                layout = BoardLayout.load(PROJECT_ROOT / "assets/resource/layouts/default.json")
                backend = MaaBackend(cast(Any, SimpleNamespace(tasker=tasker)), layout)
                solution = Solution.from_dict({"id": "stop_test", "name": "停止集成测试", "category": "puzzle",
                                               "reference_resolution": [1280, 720],
                                               "steps": [{"action": "tap", "point": [1, 1]}, following]})
                with patch("run_android.emit_event"):
                    monitor = start_stop_monitor(cast(Any, tasker), marker, done, stopped)
                    assert monitor is not None
                    try:
                        with self.assertRaisesRegex(SolutionError, "执行失败"):
                            SolutionExecutor(backend, layout=layout).execute(solution)
                        self.assertTrue(stopped.is_set())
                        controller.post_click.assert_called_once_with(1, 1)
                        controller.post_swipe.assert_not_called()
                        controller.post_click_key.assert_not_called()
                    finally:
                        done.set()
                        monitor.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
