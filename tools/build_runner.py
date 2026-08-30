from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import maa


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_PATH = PROJECT_ROOT / "install" / "runtime"
BUILD_PATH = PROJECT_ROOT / "build" / "pyinstaller"
MAA_AGENT_BINARY_PATH = Path(maa.__file__).resolve().parent.parent / "MaaAgentBinary"


def build(name: str, entry: Path) -> None:
    if not MAA_AGENT_BINARY_PATH.is_dir():
        raise FileNotFoundError(
            f"MaaAgentBinary was not found next to the maa package: {MAA_AGENT_BINARY_PATH}"
        )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--paths",
        str(PROJECT_ROOT / "agent"),
        "--collect-all",
        "maa",
        "--add-data",
        f"{MAA_AGENT_BINARY_PATH}{os.pathsep}MaaAgentBinary",
        "--name",
        name,
        "--distpath",
        str(DIST_PATH),
        "--workpath",
        str(BUILD_PATH / name),
        "--specpath",
        str(BUILD_PATH),
        str(entry),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    DIST_PATH.mkdir(parents=True, exist_ok=True)
    BUILD_PATH.mkdir(parents=True, exist_ok=True)
    build("MaaSVWB.Runner", PROJECT_ROOT / "tools" / "run_android.py")
    build("MaaSVWB.Agent", PROJECT_ROOT / "agent" / "main.py")
    print(f"Bundled runtime created in {DIST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
