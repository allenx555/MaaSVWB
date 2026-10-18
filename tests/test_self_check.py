from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT_ROOT / "agent"), str(PROJECT_ROOT / "tools")]

from runtime.self_check import check_runtime  # noqa: E402
from run_android import main as runner_main  # noqa: E402


class SelfCheckTests(unittest.TestCase):
    @contextmanager
    def packaged_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for source, destination in (("battle", "battle"), ("catalog", "catalog"),
                                        ("resource/layouts", "resource/layouts"),
                                        ("resource/solutions", "resource/solutions")):
                shutil.copytree(PROJECT_ROOT / "assets" / source, root / destination)
            shutil.copyfile(PROJECT_ROOT / "assets/interface.json", root / "interface.json")
            models = root / "resource/model/ocr"
            models.mkdir(parents=True)
            for name in ("det.onnx", "rec.onnx", "keys.txt"):
                (models / name).write_bytes(b"fixture: native loader is mocked")
            yield root

    def test_runner_checks_packaged_layout_and_registers_real_action_instances(self):
        with self.packaged_assets() as root, patch("runtime.self_check.Resource") as resource, patch("runtime.self_check.emit_event") as emit:
            result = check_runtime(root, "runner")
            self.assertEqual(result["project_root"], str(root.resolve()))
            self.assertGreater(result["cards"], 0)
            self.assertGreater(result["profiles"], 0)
            self.assertGreater(result["solutions"], 0)
            instance = resource.return_value
            instance.post_bundle.assert_called_once_with(str(root / "resource"))
            self.assertEqual({call.args[0] for call in instance.register_custom_action.call_args_list},
                             {"ExecuteSolution", "ExecuteDungeon", "ExecuteDeckTracker"})
            emit.assert_called_once()

    def test_missing_model_or_corrupt_profile_fails_before_native_load(self):
        for kind in ("model", "profile", "catalog"):
            with self.subTest(kind=kind), self.packaged_assets() as root, patch("runtime.self_check.Resource") as resource:
                if kind == "model":
                    (root / "resource/model/ocr/det.onnx").unlink()
                elif kind == "profile":
                    next((root / "battle/profiles").glob("*.json")).write_text("{}", encoding="utf-8")
                else:
                    (root / "catalog/puzzle_catalog.json").write_text(json.dumps({"items": []}), encoding="utf-8")
                with self.assertRaises((RuntimeError, ValueError)):
                    check_runtime(root, "runner")
                resource.assert_not_called()

    def test_resource_or_action_registration_failure_is_reported(self):
        for failure in ("bundle", "action"):
            with self.subTest(failure=failure), self.packaged_assets() as root, patch("runtime.self_check.Resource") as resource:
                instance = resource.return_value
                instance.post_bundle.return_value.wait.return_value.succeeded = failure != "bundle"
                instance.register_custom_action.return_value = failure != "action"
                with self.assertRaises(RuntimeError):
                    check_runtime(root, "runner")

    def test_runner_self_check_never_discovers_or_connects_a_device(self):
        with patch("sys.argv", ["run_android", "--self-check"]), patch("run_android.configure_utf8_stdio"), \
                patch("runtime.self_check.check_runtime") as check, patch("run_android.choose_device") as discover, \
                patch("run_android.connect_controller") as connect, patch("run_android.create_tasker") as tasker:
            self.assertEqual(runner_main(), 0)
            self.assertEqual(check.call_args.args[1], "runner")
            discover.assert_not_called()
            connect.assert_not_called()
            tasker.assert_not_called()

    def test_agent_self_check_never_starts_a_socket_server(self):
        spec = importlib.util.spec_from_file_location("maasvwb_agent_entry", PROJECT_ROOT / "agent/main.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Only call the entry-point dispatch here; Agent's native library mode
        # is verified in its own process by the extracted-release smoke test.
        with patch("sys.argv", ["MaaSVWB.Agent", "--self-check"]), patch.object(module, "configure_utf8_stdio"), \
                patch("runtime.self_check.check_runtime") as check:
            self.assertEqual(module.main(), 0)
            self.assertEqual(check.call_args.args[1], "agent")


if __name__ == "__main__":
    unittest.main()
