from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = PROJECT_ROOT / "assets" / "interface.base.json"
OUTPUT_PATH = PROJECT_ROOT / "assets" / "interface.json"
CATEGORY_CONFIG = {
    "puzzle": ("运行盘面解密", "选择盘面解密"),
    "tutorial": ("运行对战教程", "选择对战教程"),
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_interface() -> dict[str, Any]:
    interface = load_json(BASE_PATH)
    solution_dir = PROJECT_ROOT / "assets" / "resource" / "solutions"
    solution_ids = {path.stem for path in solution_dir.glob("*.json")}

    tasks: list[dict[str, Any]] = []
    options: dict[str, Any] = {}
    for category, (task_label, option_label) in CATEGORY_CONFIG.items():
        catalog_path = PROJECT_ROOT / "assets" / "catalog" / f"{category}_catalog.json"
        catalog = load_json(catalog_path)
        scripted = [item for item in catalog["items"] if item["id"] in solution_ids]
        if not scripted:
            continue

        option_name = f"{category}_solution"
        cases = [
            {
                "name": item["id"],
                "label": item["name"],
                "pipeline_override": {
                    "执行解法": {
                        "custom_action_param": {
                            "solution": item["id"],
                        }
                    }
                },
            }
            for item in scripted
        ]
        tasks.append(
            {
                "name": f"run_{category}",
                "label": task_label,
                "entry": "执行解法",
                "controller": ["安卓模拟器"],
                "resource": ["默认资源"],
                "option": [option_name],
            }
        )
        options[option_name] = {
            "type": "select",
            "label": option_label,
            "default_case": cases[0]["name"],
            "cases": cases,
        }

    interface["task"] = tasks
    interface["option"] = options
    return interface


def serialize(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=4) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="从目录和解法生成 Maa Project Interface")
    parser.add_argument("--check", action="store_true", help="只检查文件是否已同步")
    args = parser.parse_args()
    expected = serialize(build_interface())

    if args.check:
        actual = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if actual != expected:
            raise ValueError("assets/interface.json 已过期，请运行 tools/generate_interface.py")
        print("OK  assets/interface.json is generated from catalogs and solutions")
        return 0

    OUTPUT_PATH.write_text(expected, encoding="utf-8")
    print(f"Generated {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR  {error}")
        raise SystemExit(1) from error
