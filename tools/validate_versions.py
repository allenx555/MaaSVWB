from __future__ import annotations

import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    versions = json.loads(
        (PROJECT_ROOT / "tools" / "project_versions.json").read_text(encoding="utf-8")
    )
    maafw = versions["maafw"]
    require(
        re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", maafw) is not None,
        f"非法 MaaFramework 版本: {maafw}",
    )

    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    require(f"maafw=={maafw}" in requirements, "requirements.txt 的 maafw 版本未同步")

    maatools = (PROJECT_ROOT / "maatools.config.mts").read_text(encoding="utf-8")
    require(f"maaVersion: '{maafw}'" in maatools, "maatools.config.mts 的版本未同步")

    schema_workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "sync_schema_files.yml"
    ).read_text(encoding="utf-8")
    require(
        f'MAAFW_VERSION: "v{maafw}"' in schema_workflow,
        "sync_schema_files.yml 的版本未同步",
    )

    print(f"OK  MaaFramework version pins: {maafw}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR  {error}")
        raise SystemExit(1) from error
