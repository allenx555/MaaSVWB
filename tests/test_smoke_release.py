from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from archive_release import executable_paths  # noqa: E402
from smoke_release import check_executables, extract_release  # noqa: E402


class ReleaseSmokeTests(unittest.TestCase):
    def test_self_checks_run_outside_checkout_without_development_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "extracted package"
            working = Path(temporary) / "elsewhere"

            def run(command, **options):
                self.assertEqual(command[1:], ["--self-check"])
                self.assertEqual(options["cwd"], working)
                for key in ("MAASVWB_ROOT", "MAAFW_BINARY_PATH", "PYTHONPATH", "PYTHONHOME"):
                    self.assertNotIn(key, options["env"])
                role = "runner" if "Runner" in command[0] else "agent"
                event = {"event": "self_check", "state": "succeeded", "role": role,
                         "project_root": str(root)}
                return SimpleNamespace(returncode=0, stdout="@maasvwb-event " + json.dumps(event), stderr="")

            with patch.dict(os.environ, {"MAASVWB_ROOT": str(PROJECT_ROOT), "MAAFW_BINARY_PATH": "poison", "PYTHONPATH": "poison", "PYTHONHOME": "poison"}), \
                    patch("smoke_release.subprocess.run", side_effect=run) as child:
                check_executables(root, working)
                self.assertEqual(child.call_count, 2)

    def test_exit_zero_without_self_check_or_with_wrong_root_is_rejected(self):
        for output in ("", "@maasvwb-event " + json.dumps({"event": "self_check", "state": "succeeded", "role": "runner", "project_root": str(PROJECT_ROOT)})):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as temporary, \
                    patch("smoke_release.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=output, stderr="")):
                with self.assertRaises(RuntimeError):
                    check_executables(Path(temporary), Path(temporary))

    def test_nonzero_child_exit_is_rejected_even_if_success_was_printed(self):
        with patch("smoke_release.subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="native import failed")):
            with self.assertRaisesRegex(RuntimeError, "native import failed"):
                check_executables(PROJECT_ROOT, PROJECT_ROOT)

    def test_extraction_preserves_contents_and_rejects_path_escape(self):
        for escape in (False, True):
            with self.subTest(escape=escape), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive_path = root / "release.zip"
                with ZipFile(archive_path, "w") as archive:
                    for name in executable_paths():
                        archive.writestr(name, b"binary")
                    if escape:
                        archive.writestr("../escaped", b"bad")
                if escape:
                    with self.assertRaisesRegex(ValueError, "escapes"):
                        extract_release(archive_path, root / "package")
                    self.assertFalse((root / "escaped").exists())
                else:
                    extract_release(archive_path, root / "package")
                    for name in executable_paths():
                        path = root / "package" / name
                        self.assertEqual(path.read_bytes(), b"binary")


if __name__ == "__main__":
    unittest.main()
