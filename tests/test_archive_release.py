from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from archive_release import archive_release, executable_paths, validate_archive  # noqa: E402


class ArchiveReleaseTests(unittest.TestCase):
    def test_final_archive_survives_transport_and_keeps_package_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "install"
            for name in (*executable_paths(), "resource/pipeline/test.json"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"release-content")
            output = root / "dist" / "release.zip"
            archive_release(source, output)
            transported = root / "downloaded.zip"
            shutil.copyfile(output, transported)
            validate_archive(transported)
            with ZipFile(transported) as archive:
                self.assertEqual(archive.read("runtime/MaaSVWB.Runner.exe"), b"release-content")
                self.assertEqual(archive.read("resource/pipeline/test.json"), b"release-content")
                self.assertFalse(any(name.startswith("install/") for name in archive.namelist()))

    def test_missing_runner_fails_before_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "install").mkdir()
            with self.assertRaisesRegex(ValueError, "Missing release executable"):
                archive_release(root / "install", root / "release.zip")


if __name__ == "__main__":
    unittest.main()
