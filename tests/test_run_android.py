from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from run_android import request_task_stop, wait_task_interruptibly  # noqa: E402


class _PollingJob:
    def __init__(self, done_after: int) -> None:
        self.done_after = done_after
        self.polls = 0

    @property
    def done(self) -> bool:
        self.polls += 1
        return self.polls >= self.done_after


class RunAndroidTests(unittest.TestCase):
    @patch("run_android.time.sleep")
    def test_task_wait_uses_interruptible_status_polling(self, _sleep: MagicMock) -> None:
        task = _PollingJob(done_after=3)

        completed = wait_task_interruptibly(MagicMock(), task)

        self.assertTrue(completed)
        self.assertEqual(task.polls, 3)

    @patch("run_android.emit_event")
    @patch("run_android.time.sleep", side_effect=KeyboardInterrupt)
    def test_ctrl_c_requests_tasker_stop(
        self, _sleep: MagicMock, emit_event: MagicMock
    ) -> None:
        tasker = MagicMock()
        tasker.post_stop.return_value = _PollingJob(done_after=1)

        completed = wait_task_interruptibly(tasker, _PollingJob(done_after=2))

        self.assertFalse(completed)
        tasker.post_stop.assert_called_once_with()
        emit_event.assert_called_once_with(
            "control", "收到 Ctrl+C，正在停止 Maa 任务", state="stopping"
        )

    @patch("run_android.emit_event")
    def test_shared_stop_request_waits_for_completion(
        self, emit_event: MagicMock
    ) -> None:
        tasker = MagicMock()
        stop_job = MagicMock()
        tasker.post_stop.return_value = stop_job

        self.assertTrue(request_task_stop(tasker, "停止测试"))

        tasker.post_stop.assert_called_once_with()
        stop_job.wait.assert_called_once_with()
        emit_event.assert_called_once_with(
            "control", "停止测试", state="stopping"
        )


if __name__ == "__main__":
    unittest.main()
