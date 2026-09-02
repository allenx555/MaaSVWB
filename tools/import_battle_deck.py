from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, cast

from jsonschema import Draft202012Validator
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORT_SCHEMA = PROJECT_ROOT / "assets" / "schemas" / "battle-deck-import.schema.json"
SUPPORTED_TRAITS = {"storm", "rush", "ward", "generated"}
OUTPUT_MARKER = ".maasvwb-battle-import.json"


class DeckImportError(ValueError):
    """卡组导入请求或 SVWBData 数据无效。"""


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeckImportError(f"无法读取{label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise DeckImportError(f"{label}根节点必须是对象: {path}")
    return cast(dict[str, Any], value)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def _remove_previous_output(output: Path, force: bool) -> None:
    if not output.exists():
        return
    if not force:
        raise DeckImportError(f"输出目录已存在；如需替换请增加 --force: {output}")
    if not output.is_dir():
        raise DeckImportError(f"输出路径不是目录，拒绝替换: {output}")

    marker = output / OUTPUT_MARKER
    legacy_generated = (
        (output / "import_request.json").is_file()
        and (output / "battle" / "target_review.json").is_file()
    )
    if any(output.iterdir()) and not marker.is_file() and not legacy_generated:
        raise DeckImportError(
            "输出目录不包含 MaaSVWB 导入标记，拒绝递归删除；"
            f"请改用新的空目录: {output}"
        )
    shutil.rmtree(output)


def _validate_request(request: dict[str, Any], source: Path) -> None:
    schema = _load_json_object(IMPORT_SCHEMA, "卡组导入 Schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(request),
        key=lambda item: list(item.path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise DeckImportError(f"{source.name}:{location}: {error.message}")

    for index, raw in enumerate(cast(list[object], request["cards"]), start=1):
        card = cast(dict[str, Any], raw)
        if card["default_target"] not in card["allowed_targets"]:
            raise DeckImportError(
                f"cards[{index}].default_target 必须出现在 allowed_targets 中"
            )


def find_svwb_base(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    environment = os.environ.get("SVWB_DATA_ROOT")
    if environment:
        candidates.append(Path(environment).expanduser())
    candidates.extend(
        [
            PROJECT_ROOT.parent / "SVWBData",
            PROJECT_ROOT.parent / "svwbdata",
        ]
    )

    checked: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        bases = (resolved / "Base", resolved)
        for base in bases:
            if base in checked:
                continue
            checked.append(base)
            if (base / "maa" / "wizard2_card_staging.json").is_file():
                return base
    locations = "、".join(str(path) for path in checked)
    raise DeckImportError(
        "找不到 SVWBData 卡牌暂存表。请使用 --svwb-data 指定目录，"
        f"或设置 SVWB_DATA_ROOT。已检查: {locations}"
    )


def _source_hash(base: Path) -> str:
    summary_path = base / "master" / "wizard2" / "decoded" / "summary.json"
    if summary_path.is_file():
        summary = _load_json_object(summary_path, "SVWBData 摘要")
        value = summary.get("sha256")
        if isinstance(value, str) and value:
            return value
    staging_path = base / "maa" / "wizard2_card_staging.json"
    return hashlib.sha256(staging_path.read_bytes()).hexdigest()


def _load_source_cards(base: Path) -> list[dict[str, Any]]:
    staging_path = base / "maa" / "wizard2_card_staging.json"
    staging = _load_json_object(staging_path, "卡牌暂存表")
    cards = staging.get("cards")
    if not isinstance(cards, list):
        raise DeckImportError(f"卡牌暂存表缺少 cards 数组: {staging_path}")
    if not all(isinstance(card, dict) for card in cards):
        raise DeckImportError(f"卡牌暂存表 cards 包含非对象项: {staging_path}")
    return cast(list[dict[str, Any]], cards)


def _load_resources(base: Path) -> dict[int, dict[str, Any]]:
    path = (
        base
        / "master"
        / "wizard2"
        / "decoded"
        / "tables"
        / "CardResourceMaster.json"
    )
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeckImportError(f"无法读取卡图资源表 {path}: {error}") from error
    if not isinstance(rows, list):
        raise DeckImportError(f"卡图资源表根节点必须是数组: {path}")
    result: dict[int, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        resource_id = raw.get("CardResourceId")
        if isinstance(resource_id, int):
            result[resource_id] = cast(dict[str, Any], raw)
    return result


def _resolve_cards(
    request_cards: list[dict[str, Any]],
    source_cards: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in source_cards:
        card_id = str(card.get("id", ""))
        name = card.get("name")
        if card_id:
            by_id[card_id] = card
        if isinstance(name, str) and name:
            by_name[name].append(card)

    resolved: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for index, request_card in enumerate(request_cards, start=1):
        reference = cast(str, request_card["ref"]).strip()
        source = by_id.get(reference)
        if source is None:
            matches = by_name.get(reference, [])
            if not matches:
                raise DeckImportError(
                    f"cards[{index}].ref 找不到卡牌: {reference!r}"
                )
            if len(matches) > 1:
                ids = ", ".join(str(card["id"]) for card in matches)
                raise DeckImportError(
                    f"cards[{index}].ref 的名称不唯一: {reference!r}；"
                    f"请改用 ID（候选: {ids}）"
                )
            source = matches[0]
        card_id = str(source["id"])
        if card_id in seen:
            raise DeckImportError(f"导入卡组包含重复卡牌: {card_id}")
        seen.add(card_id)
        resolved.append((request_card, source))
    return resolved


def _find_source_image(base: Path, raw_path: object) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    original = Path(raw_path)
    candidates = (
        original,
        base / "cards" / "png" / "wizard2" / original.name,
    )
    return next((path for path in candidates if path.is_file()), None)


def _resource_id_from_image(path: Path) -> int | None:
    prefix = path.stem.split("_", 1)[0]
    return int(prefix) if prefix.isdigit() else None


def _crop_box(
    size: tuple[int, int], resource: Mapping[str, Any] | None
) -> tuple[int, int, int, int] | None:
    if resource is None:
        return None
    try:
        tile_x = float(resource["TillingNormalX"])
        tile_y = float(resource["TillingNormalY"])
        offset_x = float(resource["OffsetNormalX"])
        offset_y = float(resource["OffsetNormalY"])
    except (KeyError, TypeError, ValueError):
        return None
    if tile_x <= 0 or tile_y <= 0:
        return None

    width, height = size
    left = max(0, min(width, round(offset_x * width)))
    right = max(0, min(width, round((offset_x + tile_x) * width)))
    top = max(0, min(height, round((1.0 - offset_y - tile_y) * height)))
    bottom = max(0, min(height, round((1.0 - offset_y) * height)))
    if right - left < 64 or bottom - top < 64:
        return None
    if left == 0 and top == 0 and right == width and bottom == height:
        return None
    return left, top, right, bottom


def _write_feature_image(
    source: Path,
    destination: Path,
    resource: Mapping[str, Any] | None,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        original_size = image.size
        box = _crop_box(image.size, resource)
        if box is not None:
            image = image.crop(box)
        image.save(destination, format="PNG", optimize=True)
    return {
        "source": str(source),
        "output": destination.name,
        "original_size": list(original_size),
        "output_size": list(image.size),
        "uv_crop": list(box) if box is not None else None,
    }


def _catalog_traits(source: Mapping[str, Any]) -> list[str]:
    result: set[str] = set()
    traits = source.get("traits", [])
    if not isinstance(traits, list):
        return []
    for raw in traits:
        if not isinstance(raw, dict):
            continue
        trait = raw.get("trait")
        if raw.get("status") == "auto_exact" and trait in SUPPORTED_TRAITS:
            result.add(cast(str, trait))
    return sorted(result)


def _catalog_aliases(source: Mapping[str, Any]) -> list[str]:
    canonical = source.get("name")
    result: set[str] = set()
    aliases = source.get("style_aliases", [])
    if not isinstance(aliases, list):
        return []
    for raw in aliases:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if isinstance(name, str) and name and name != canonical:
            result.add(name)
    return sorted(result)


def _build_profile(
    request: Mapping[str, Any],
    resolved: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    deck = []
    rules: dict[str, dict[str, Any]] = {}
    mulligan_keep: list[str] = []
    evolution_ranking: list[tuple[int, int, str]] = []
    for order, (configured, source) in enumerate(resolved):
        card_id = str(source["id"])
        deck.append({"card_id": card_id, "copies": configured["copies"]})
        rules[card_id] = {
            "play_priority": configured.get("play_priority", 0),
            "target": {"type": configured["default_target"]},
            "max_uses_per_turn": configured.get("max_uses_per_turn", 3),
        }
        if configured.get("mulligan_keep", False):
            mulligan_keep.append(card_id)
        evolution_priority = configured.get("evolution_priority")
        if isinstance(evolution_priority, int):
            evolution_ranking.append((evolution_priority, -order, card_id))

    evolution_ranking.sort(reverse=True)
    description = request.get("description")
    return {
        "$schema": (
            "https://raw.githubusercontent.com/allenx555/MaaSVWB/main/"
            "assets/schemas/battle-profile.schema.json"
        ),
        "schema_version": 1,
        "id": request["id"],
        "name": request["name"],
        "description": (
            description
            if isinstance(description, str)
            else "由 SVWBData 卡组导入器生成，请继续校对策略。"
        ),
        "deck": deck,
        "cards": rules,
        "combos": [],
        "attack": {
            "clear_ward": True,
            "otherwise": "enemy_leader",
            "attacker_order": "lowest_attack_first",
        },
        "evolution": {
            "enabled": True,
            "prefer_can_attack": True,
            "card_priority": [item[2] for item in evolution_ranking],
            "type_order": ["super", "normal"],
        },
        "mulligan": {
            "enabled": True,
            "keep": mulligan_keep,
        },
        "safety": {
            "max_actions_per_turn": 30,
            "max_retries_per_action": 1,
            "no_progress_limit": 3,
        },
    }


def generate_import(
    request_path: Path,
    output: Path,
    svwb_data: Path | None = None,
    *,
    require_40: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    request_path = request_path.expanduser().resolve()
    request = _load_json_object(request_path, "卡组导入配置")
    _validate_request(request, request_path)
    request_cards = cast(list[dict[str, Any]], request["cards"])
    copy_count = sum(cast(int, card["copies"]) for card in request_cards)
    if require_40 and copy_count != 40:
        raise DeckImportError(f"卡组总张数必须为 40，当前为 {copy_count}")

    base = find_svwb_base(svwb_data)
    source_cards = _load_source_cards(base)
    resources = _load_resources(base)
    resolved = _resolve_cards(request_cards, source_cards)

    output = output.expanduser().resolve()
    if output == output.parent or output in {PROJECT_ROOT, base, base.parent}:
        raise DeckImportError(f"拒绝使用过宽的输出目录: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    _remove_previous_output(output, force)

    temporary = Path(tempfile.mkdtemp(prefix=".battle-import-", dir=output.parent))
    try:
        catalog_cards: list[dict[str, Any]] = []
        report_cards: list[dict[str, Any]] = []
        for configured, source in resolved:
            card_id = str(source["id"])
            templates = source.get("templates")
            raw_paths = templates.get("paths", []) if isinstance(templates, dict) else []
            if not isinstance(raw_paths, list):
                raw_paths = []
            source_images = [
                image
                for raw in raw_paths
                if (image := _find_source_image(base, raw)) is not None
            ]
            if not source_images:
                raise DeckImportError(
                    f"卡牌 {card_id}（{source.get('name')}）没有可用 PNG，无法生成识别素材"
                )

            template_paths: list[str] = []
            image_report: list[dict[str, Any]] = []
            for source_image in source_images:
                resource_id = _resource_id_from_image(source_image)
                relative = Path("cards") / card_id / source_image.name
                destination = temporary / "resource" / "image" / relative
                image_report.append(
                    _write_feature_image(
                        source_image,
                        destination,
                        resources.get(resource_id) if resource_id is not None else None,
                    )
                )
                template_paths.append(relative.as_posix())

            catalog_cards.append(
                {
                    "id": card_id,
                    "name": source["name"],
                    "aliases": _catalog_aliases(source),
                    "type": source["type"],
                    "base_cost": source["base_cost"],
                    "templates": template_paths,
                    "default_target": configured["default_target"],
                    "allowed_targets": configured["allowed_targets"],
                    "traits": _catalog_traits(source),
                }
            )
            report_cards.append(
                {
                    "id": card_id,
                    "name": source["name"],
                    "configured_targets": {
                        "default_target": configured["default_target"],
                        "allowed_targets": configured["allowed_targets"],
                    },
                    "source_target_review": source.get("target_review"),
                    "source_traits": source.get("traits", []),
                    "skill_text": source.get("skill_text", ""),
                    "images": image_report,
                }
            )

        catalog = {"schema_version": 1, "cards": catalog_cards}
        profile = _build_profile(request, resolved)
        source_hash = _source_hash(base)
        warnings = []
        if copy_count != 40:
            warnings.append(f"卡组总张数为 {copy_count}，不是标准的 40 张")
        warnings.append(
            "识别图片是由 AssetBundle 原图和 CardResourceMaster 普通状态 UV 参数生成的 "
            "FeatureMatch 候选素材，仍需使用 1280x720 实际画面校准。"
        )
        report = {
            "schema_version": 1,
            "profile_id": request["id"],
            "source_root": str(base),
            "source_sha256": source_hash,
            "unique_cards": len(catalog_cards),
            "deck_size": copy_count,
            "warnings": warnings,
            "cards": report_cards,
        }

        _write_json(temporary / "battle" / "card_catalog.json", catalog)
        _write_json(
            temporary / "battle" / "profiles" / f"{request['id']}.json",
            profile,
        )
        _write_json(temporary / "battle" / "target_review.json", report)
        _write_json(temporary / "import_request.json", request)
        _write_json(
            temporary / OUTPUT_MARKER,
            {"schema_version": 1, "generator": "tools/import_battle_deck.py"},
        )
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从外部 SVWBData 生成卡组限定注册表、Battle Profile 和识别素材"
    )
    parser.add_argument("request", type=Path, help="卡组导入配置 JSON")
    parser.add_argument(
        "--svwb-data",
        type=Path,
        help="SVWBData 或 SVWBData/Base；默认读取相邻目录或 SVWB_DATA_ROOT",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出目录；默认 build/battle-import/<配置 ID>",
    )
    parser.add_argument(
        "--require-40",
        action="store_true",
        help="要求配置中的卡牌总张数恰好为 40",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="替换已存在的精确输出目录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request_path = cast(Path, args.request)
    request = _load_json_object(request_path, "卡组导入配置")
    profile_id = request.get("id")
    if not isinstance(profile_id, str) or not profile_id:
        raise DeckImportError("卡组导入配置缺少 id")
    output = cast(Path | None, args.output) or (
        PROJECT_ROOT / "build" / "battle-import" / profile_id
    )
    report = generate_import(
        request_path,
        output,
        cast(Path | None, args.svwb_data),
        require_40=cast(bool, args.require_40),
        force=cast(bool, args.force),
    )
    print(
        f"已生成 {report['unique_cards']} 种 / {report['deck_size']} 张卡牌: "
        f"{output.resolve()}"
    )
    for warning in cast(list[str], report["warnings"]):
        print(f"警告: {warning}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeckImportError as error:
        print(f"ERROR  {error}")
        raise SystemExit(1) from error
