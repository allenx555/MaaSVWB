from __future__ import annotations

import argparse
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def executable_paths(os_name: str) -> tuple[str, ...]:
    suffix = ".exe" if os_name == "win" else ""
    return (
        f"MaaSVWB{suffix}",
        f"runtime/MaaSVWB.Runner{suffix}",
        f"runtime/MaaSVWB.Agent{suffix}",
    )


def validate_archive(path: Path, os_name: str) -> None:
    """Check the final ZIP, including Unix mode bits inside the archive."""
    with ZipFile(path) as archive:
        damaged = archive.testzip()
        if damaged is not None:
            raise ValueError(f"Corrupt release entry: {damaged}")
        for name in executable_paths(os_name):
            try:
                entry = archive.getinfo(name)
            except KeyError as error:
                raise ValueError(f"Missing release executable: {name}") from error
            if entry.is_dir():
                raise ValueError(f"Release executable is a directory: {name}")
            if os_name != "win":
                mode = entry.external_attr >> 16
                if entry.create_system != 3 or not stat.S_ISREG(mode) or mode & 0o111 != 0o111:
                    raise ValueError(f"Release executable lacks Unix executable permissions: {name}")


def archive_release(source: Path, output: Path, os_name: str) -> None:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise ValueError(f"Release directory does not exist: {source}")
    if output.is_relative_to(source):
        raise ValueError("Release archive must be outside the source directory")
    for name in executable_paths(os_name):
        if not (source / name).is_file():
            raise ValueError(f"Missing release executable: {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # ZipFile.write records the build host's st_mode, before Artifact transport
    # can replace the executable files' permissions with 0644.
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            archive.write(path, path.relative_to(source).as_posix())
    validate_archive(output, os_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive a release before Artifact upload")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--os", choices=("win", "linux", "macos"), required=True)
    args = parser.parse_args()
    archive_release(args.source, args.output, args.os)
    print(f"Release archive verified: {args.output}")


if __name__ == "__main__":
    main()
