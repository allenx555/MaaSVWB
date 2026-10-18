from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from archive_release import archive_release, executable_paths, validate_archive  # noqa: E402


class ArchiveReleaseTests(unittest.TestCase):
    def test_final_archive_survives_transport_and_keeps_package_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "install"
            for name in (*executable_paths("win"), "resource/pipeline/test.json"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"release-content")
            output = root / "dist" / "release.zip"
            archive_release(source, output, "win")
            transported = root / "downloaded.zip"
            shutil.copyfile(output, transported)
            validate_archive(transported, "win")
            with ZipFile(transported) as archive:
                self.assertEqual(archive.read("runtime/MaaSVWB.Runner.exe"), b"release-content")
                self.assertEqual(archive.read("resource/pipeline/test.json"), b"release-content")
                self.assertFalse(any(name.startswith("install/") for name in archive.namelist()))

    def test_unix_archive_rejects_lost_permissions_after_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.zip"
            for mode, valid in ((0o755, True), (0o644, False)):
                with self.subTest(mode=oct(mode)):
                    with ZipFile(path, "w") as archive:
                        for name in executable_paths("linux"):
                            entry = ZipInfo(name)
                            entry.create_system = 3
                            entry.external_attr = (stat.S_IFREG | mode) << 16
                            archive.writestr(entry, b"binary")
                    if valid:
                        validate_archive(path, "linux")
                        validate_archive(path, "macos")
                    else:
                        with self.assertRaisesRegex(ValueError, "executable permissions"):
                            validate_archive(path, "linux")

    @unittest.skipIf(os.name == "nt", "requires Unix permission semantics")
    def test_native_unix_archiving_preserves_execute_bits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in executable_paths("linux"):
                path = root / "install" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"binary")
                path.chmod(0o755)
            output = root / "release.zip"
            archive_release(root / "install", output, "linux")
            with ZipFile(output) as archive:
                for name in executable_paths("linux"):
                    self.assertEqual((archive.getinfo(name).external_attr >> 16) & 0o777, 0o755)

    def test_missing_runner_fails_before_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "install").mkdir()
            with self.assertRaisesRegex(ValueError, "Missing release executable"):
                archive_release(root / "install", root / "release.zip", "win")


if __name__ == "__main__":
    unittest.main()
