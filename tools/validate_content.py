from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from solution_engine.repository import SolutionRepository, VALID_ID  # noqa: E402


CATALOG_NAME = re.compile(r"^(?P<category>[a-z0-9_-]+)_catalog\.json$")
SCHEMA_DIR = PROJECT_ROOT / "assets" / "schemas"


def validate_document(data: object, schema_name: str, source: Path) -> None:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(cast(Any, data)),
        key=lambda item: list(item.path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(f"{source.name}:{location}: {error.message}")


def load_catalog(path: Path) -> tuple[str, dict[str, dict]]:
    match = CATALOG_NAME.fullmatch(path.name)
    if match is None:
        raise ValueError(f"非法目录文件名: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_document(data, "catalog.schema.json", path)
    if data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError(f"{path.name} 必须包含 version=1 和 items 数组")

    items: dict[str, dict] = {}
    for index, item in enumerate(data["items"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path.name} 第 {index} 项必须是对象")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not VALID_ID.fullmatch(item_id):
            raise ValueError(f"{path.name} 第 {index} 项包含非法 id: {item_id!r}")
        if item_id in items:
            raise ValueError(f"{path.name} 包含重复 id: {item_id}")
        for field in ("name", "series"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{path.name} 的 {item_id}.{field} 必须是非空字符串")
        if "group" in item and (
            not isinstance(item["group"], str) or not item["group"].strip()
        ):
            raise ValueError(f"{path.name} 的 {item_id}.group 必须是非空字符串")
        if "sequence" in item and (
            not isinstance(item["sequence"], int) or item["sequence"] < 1
        ):
            raise ValueError(f"{path.name} 的 {item_id}.sequence 必须是正整数")
        items[item_id] = item

    for item_id, item in items.items():
        requirement = item.get("requires")
        if requirement is not None and requirement not in items:
            raise ValueError(f"{path.name} 的 {item_id} 依赖不存在: {requirement}")
    ensure_acyclic(path.name, items)
    return match.group("category"), items


def ensure_acyclic(name: str, items: dict[str, dict]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visiting:
            raise ValueError(f"{name} 存在循环依赖，涉及: {item_id}")
        if item_id in visited:
            return
        visiting.add(item_id)
        requirement = items[item_id].get("requires")
        if requirement is not None:
            visit(requirement)
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in items:
        visit(item_id)


def main() -> int:
    catalogs: dict[str, dict[str, dict]] = {}
    for path in sorted((PROJECT_ROOT / "assets" / "catalog").glob("*_catalog.json")):
        category, items = load_catalog(path)
        catalogs[category] = items
        print(f"OK  {path.name}: {len(items)} 项")

    solution_dir = PROJECT_ROOT / "assets" / "resource" / "solutions"
    repository = SolutionRepository(solution_dir)
    files = sorted(solution_dir.glob("*.json"))
    if not files:
        raise ValueError("未找到解法文件")
    for path in files:
        validate_document(
            json.loads(path.read_text(encoding="utf-8")),
            "solution.schema.json",
            path,
        )
        solution = repository.load(path.stem)
        category_items = catalogs.get(solution.category)
        if category_items is None or solution.id not in category_items:
            raise ValueError(
                f"解法 {solution.id} 未出现在 {solution.category}_catalog.json"
            )
        print(f"OK  {solution.id}: {solution.name} ({len(solution.steps)} 步)")

    for path in sorted((PROJECT_ROOT / "assets" / "resource" / "layouts").glob("*.json")):
        validate_document(
            json.loads(path.read_text(encoding="utf-8")),
            "layout.schema.json",
            path,
        )
        print(f"OK  {path.name}: layout schema")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR  {error}", file=sys.stderr)
        raise SystemExit(1) from error
