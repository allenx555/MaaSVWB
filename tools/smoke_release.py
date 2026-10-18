from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from zipfile import ZipFile

from archive_release import executable_paths, validate_archive


def extract_release(archive_path: Path, destination: Path, os_name: str) -> None:
    validate_archive(archive_path, os_name)
    destination = destination.resolve()
    with ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            path = (destination / entry.filename).resolve()
            if not path.is_relative_to(destination):
                raise ValueError(f"Release entry escapes extraction directory: {entry.filename}")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"Unexpected symlink in release: {entry.filename}")
        archive.extractall(destination)
        if os_name != "win":
            # zipfile does not restore Unix permissions. Apply only the stored
            # ordinary rwx bits after validating the archive's executable modes.
            for entry in archive.infolist():
                (destination / entry.filename).chmod((entry.external_attr >> 16) & 0o777)


def check_executables(package_root: Path, working_directory: Path, os_name: str) -> None:
    env = os.environ.copy()
    for key in ("MAASVWB_ROOT", "MAAFW_BINARY_PATH", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for relative, role in zip(executable_paths(os_name)[1:], ("runner", "agent")):
        completed = subprocess.run(
            [str(package_root / relative), "--self-check"], cwd=working_directory,
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"{relative} failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}")
        events = [json.loads(line.removeprefix("@maasvwb-event "))
                  for line in completed.stdout.splitlines() if line.startswith("@maasvwb-event ")]
        checks = [event for event in events if event.get("event") == "self_check"]
        if len(checks) != 1 or checks[0].get("state") != "succeeded" or checks[0].get("role") != role:
            raise RuntimeError(f"{relative} did not report a successful self-check")
        if Path(checks[0].get("project_root", "")).resolve() != package_root.resolve():
            raise RuntimeError(f"{relative} loaded resources outside the extracted package")
        print(f"PASS extracted {relative}: resources, imports and native runtime")


def smoke_release(archive_path: Path, os_name: str) -> None:
    with tempfile.TemporaryDirectory(prefix="maasvwb-release-smoke-") as temporary:
        root = Path(temporary)
        package = root / "package with spaces"
        working = root / "unrelated-working-directory"
        working.mkdir()
        extract_release(archive_path, package, os_name)
        check_executables(package, working, os_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the downloaded final release ZIP without a device")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--os", choices=("win", "linux", "macos"), required=True)
    args = parser.parse_args()
    smoke_release(args.archive.resolve(), args.os)


if __name__ == "__main__":
    main()
