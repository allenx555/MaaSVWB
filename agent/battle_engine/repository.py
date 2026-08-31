from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .models import (
    BattleProfile,
    BattleProfileError,
    CardCatalog,
    Target,
    VALID_ID,
)


MAX_CONFIG_BYTES = 1_048_576


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise BattleProfileError(f"{label} 超过 1 MiB 限制: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
    except BattleProfileError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise BattleProfileError(f"无法读取{label} {path}: {error}") from error
    if not isinstance(data, dict):
        raise BattleProfileError(f"{label}根节点必须是对象: {path}")
    return data


class CardCatalogRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    @classmethod
    def for_project(cls, project_root: Path) -> "CardCatalogRepository":
        root = project_root.resolve()
        candidates = (
            root / "assets" / "battle" / "card_catalog.json",
            root / "battle" / "card_catalog.json",
        )
        for candidate in candidates:
            if candidate.is_file():
                return cls(candidate)
        raise BattleProfileError(
            "找不到卡牌注册表（assets/battle/card_catalog.json 或 battle/card_catalog.json）"
        )

    def load(self) -> CardCatalog:
        return CardCatalog.from_dict(_read_json_object(self.path, "卡牌注册表"))


class BattleProfileRepository:
    def __init__(self, root: Path, catalog: CardCatalog) -> None:
        self.root = root.resolve()
        self.catalog = catalog

    @classmethod
    def for_project(
        cls, project_root: Path, catalog: CardCatalog | None = None
    ) -> "BattleProfileRepository":
        root = project_root.resolve()
        resolved_catalog = catalog or CardCatalogRepository.for_project(root).load()
        candidates = (
            root / "assets" / "battle" / "profiles",
            root / "battle" / "profiles",
        )
        profile_root = next((path for path in candidates if path.is_dir()), candidates[0])
        return cls(profile_root, resolved_catalog)

    @staticmethod
    def user_profile_root() -> Path:
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / ".config"
        return base / "MaaSVWB" / "battle_profiles"

    def load(self, profile_id: str) -> BattleProfile:
        if not isinstance(profile_id, str) or not VALID_ID.fullmatch(profile_id):
            raise BattleProfileError(f"非法策略 ID: {profile_id!r}")
        path = (self.root / f"{profile_id}.json").resolve()
        if path.parent != self.root:
            raise BattleProfileError("策略路径越界")
        profile = self.load_path(path)
        if profile.id != profile_id:
            raise BattleProfileError(
                f"文件名对应 ID {profile_id!r}，但文件内 ID 为 {profile.id!r}"
            )
        return profile

    def load_path(self, path: Path) -> BattleProfile:
        resolved = path.expanduser().resolve()
        if resolved.suffix.lower() != ".json":
            raise BattleProfileError("对战策略文件必须使用 .json 扩展名")
        if not resolved.is_file():
            raise BattleProfileError(f"找不到对战策略文件: {resolved}")
        profile = BattleProfile.from_dict(_read_json_object(resolved, "对战策略"))
        self._validate_references(profile)
        return profile

    def _validate_references(self, profile: BattleProfile) -> None:
        deck_ids = {item.card_id for item in profile.deck}
        self._require_known_cards(deck_ids, "deck")

        rule_ids = set(profile.cards)
        generated_ids = {
            card_id
            for card_id, definition in self.catalog.cards.items()
            if "generated" in definition.traits
        }
        extra_rules = sorted(rule_ids - deck_ids - generated_ids)
        if extra_rules:
            raise BattleProfileError(
                f"cards 包含不在 deck 中的卡牌: {', '.join(extra_rules)}"
            )
        self._require_known_cards(rule_ids, "cards")
        for card_id, rule in profile.cards.items():
            if rule.target is not None:
                self._validate_target(card_id, rule.target, f"cards.{card_id}.target")

        for combo in profile.combos:
            for index, step in enumerate(combo.steps, start=1):
                if step.card_id not in deck_ids:
                    raise BattleProfileError(
                        f"combos.{combo.id}.steps[{index}] 引用了不在 deck 中的卡牌: "
                        f"{step.card_id}"
                    )
                self._require_known_cards(
                    {step.card_id}, f"combos.{combo.id}.steps[{index}]"
                )
                if step.target is not None:
                    self._validate_target(
                        step.card_id,
                        step.target,
                        f"combos.{combo.id}.steps[{index}].target",
                    )

        for label, card_ids in (
            ("evolution.card_priority", set(profile.evolution.card_priority)),
            ("mulligan.keep", set(profile.mulligan.keep)),
        ):
            outside = sorted(card_ids - deck_ids)
            if outside:
                raise BattleProfileError(
                    f"{label} 包含不在 deck 中的卡牌: {', '.join(outside)}"
                )
            self._require_known_cards(card_ids, label)

    def _require_known_cards(self, card_ids: set[str], label: str) -> None:
        unknown = sorted(card_ids - set(self.catalog.cards))
        if unknown:
            raise BattleProfileError(
                f"{label} 引用了卡牌注册表中不存在的卡牌: {', '.join(unknown)}"
            )

    def _validate_target(self, card_id: str, target: Target, label: str) -> None:
        definition = self.catalog.cards[card_id]
        if target.type not in definition.allowed_targets:
            allowed = ", ".join(sorted(definition.allowed_targets))
            raise BattleProfileError(
                f"{label}={target.type!r} 不适用于 {card_id}；允许值: {allowed}"
            )
