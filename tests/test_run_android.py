from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from run_android import main, request_task_stop, start_stop_monitor, wait_task_interruptibly  # noqa: E402


class _PollingJob:
    def __init__(self, done_after: int) -> None:
        self.done_after = done_after
        self.polls = 0

    @property
    def done(self) -> bool:
        self.polls += 1
        return self.polls >= self.done_after


class RunAndroidTests(unittest.TestCase):
    @patch("run_android.emit_event")
    def test_monitor_consumes_an_existing_stop_without_deleting_it(self, _emit) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stop_file = Path(temporary) / "run.stop"
            stop_file.write_text("stop", encoding="utf-8")
            done, stopped = threading.Event(), threading.Event()
            tasker = MagicMock()
            monitor = start_stop_monitor(tasker, stop_file, done, stopped)
            assert monitor is not None
            try:
                self.assertTrue(stopped.wait(1))
                monitor.join(timeout=1)
                self.assertTrue(stop_file.is_file())
                tasker.post_stop.assert_called_once_with()
            finally:
                done.set()
                monitor.join(timeout=1)

    def test_main_does_not_submit_after_stop_during_connection_or_startup(self) -> None:
        for phase in ("connection", "submission"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                stop_file = Path(temporary) / "run.stop"
                tasker = MagicMock()

                def connect(_device):
                    if phase == "connection":
                        stop_file.write_text("stop", encoding="utf-8")
                    return MagicMock()

                def event(category, _message, **fields):
                    if phase == "submission" and category == "run" and fields.get("state") == "starting":
                        stop_file.write_text("stop", encoding="utf-8")

                with ExitStack() as stack:
                    stack.enter_context(patch("sys.argv", ["run_android", "--execute", "--stop-file", str(stop_file)]))
                    stack.enter_context(patch("run_android.configure_utf8_stdio"))
                    stack.enter_context(patch("run_android.Toolkit.init_option"))
                    stack.enter_context(patch("run_android.choose_device"))
                    stack.enter_context(patch("run_android.connect_controller", side_effect=connect))
                    stack.enter_context(patch("run_android.save_screenshot", return_value=(1280, 720)))
                    stack.enter_context(patch("run_android.create_tasker", return_value=tasker))
                    stack.enter_context(patch("run_android.emit_event", side_effect=event))
                    self.assertEqual(main(), 130)
                tasker.post_task.assert_not_called()
                self.assertFalse(stop_file.exists())

    def test_stop_arriving_during_submission_stops_the_submitted_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stop_file = Path(temporary) / "run.stop"
            stop_received = threading.Event()
            tasker = MagicMock()

            def submit(*_args):
                stop_file.write_text("stop", encoding="utf-8")
                return MagicMock()

            def stop():
                stop_received.set()
                return MagicMock()

            def wait(*_args):
                self.assertTrue(stop_received.wait(2))
                return True

            tasker.post_task.side_effect = submit
            tasker.post_stop.side_effect = stop
            with ExitStack() as stack:
                stack.enter_context(patch("sys.argv", ["run_android", "--execute", "--stop-file", str(stop_file)]))
                for name in ("configure_utf8_stdio", "Toolkit.init_option", "choose_device", "connect_controller", "emit_event"):
                    stack.enter_context(patch("run_android." + name))
                stack.enter_context(patch("run_android.save_screenshot", return_value=(1280, 720)))
                stack.enter_context(patch("run_android.create_tasker", return_value=tasker))
                stack.enter_context(patch("run_android.wait_task_interruptibly", side_effect=wait))
                self.assertEqual(main(), 130)
            tasker.post_task.assert_called_once()
            tasker.post_stop.assert_called_once()
            self.assertFalse(stop_file.exists())

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
