from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def executable_paths() -> tuple[str, ...]:
    return (
        "MaaSVWB.exe",
        "runtime/MaaSVWB.Runner.exe",
        "runtime/MaaSVWB.Agent.exe",
    )


def validate_archive(path: Path) -> None:
    """Check final ZIP integrity and required release executables."""
    with ZipFile(path) as archive:
        damaged = archive.testzip()
        if damaged is not None:
            raise ValueError(f"Corrupt release entry: {damaged}")
        for name in executable_paths():
            try:
                entry = archive.getinfo(name)
            except KeyError as error:
                raise ValueError(f"Missing release executable: {name}") from error
            if entry.is_dir():
                raise ValueError(f"Release executable is a directory: {name}")


def archive_release(source: Path, output: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise ValueError(f"Release directory does not exist: {source}")
    if output.is_relative_to(source):
        raise ValueError("Release archive must be outside the source directory")
    for name in executable_paths():
        if not (source / name).is_file():
            raise ValueError(f"Missing release executable: {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            archive.write(path, path.relative_to(source).as_posix())
    validate_archive(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive a release before Artifact upload")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive_release(args.source, args.output)
    print(f"Release archive verified: {args.output}")


if __name__ == "__main__":
    main()
