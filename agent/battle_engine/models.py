from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


VALID_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TARGET_TYPES = {
    "none",
    "enemy_leader",
    "ally_leader",
    "enemy_follower",
    "ally_follower",
}
TARGET_SELECTORS = {
    "leftmost",
    "rightmost",
    "lowest_attack",
    "highest_attack",
    "lowest_defense",
    "highest_defense",
}


class BattleProfileError(ValueError):
    """卡牌注册表或用户对战策略配置无效。"""


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise BattleProfileError(f"{label} 包含未知字段: {', '.join(unknown)}")


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BattleProfileError(f"{label} 必须是非空字符串")
    return value.strip()


def _require_id(value: object, label: str) -> str:
    result = _require_string(value, label)
    if not VALID_ID.fullmatch(result):
        raise BattleProfileError(f"{label} 包含非法 ID: {result!r}")
    return result


def _require_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BattleProfileError(f"{label} 必须是整数")
    if not minimum <= value <= maximum:
        raise BattleProfileError(f"{label} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _optional_bool(data: Mapping[str, Any], key: str, default: bool, label: str) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise BattleProfileError(f"{label}.{key} 必须是布尔值")
    return value


def _as_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BattleProfileError(f"{label} 必须是对象")
    return value


def _as_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BattleProfileError(f"{label} 必须是数组")
    return value


@dataclass(frozen=True)
class Target:
    type: str
    selector: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], label: str) -> "Target":
        _reject_unknown(data, {"type", "selector"}, label)
        target_type = _require_string(data.get("type"), f"{label}.type")
        if target_type not in TARGET_TYPES:
            raise BattleProfileError(f"{label}.type 不受支持: {target_type}")
        selector_value = data.get("selector")
        selector: str | None = None
        if selector_value is not None:
            selector = _require_string(selector_value, f"{label}.selector")
            if selector not in TARGET_SELECTORS:
                raise BattleProfileError(f"{label}.selector 不受支持: {selector}")
            if not target_type.endswith("_follower"):
                raise BattleProfileError(f"{label} 只有随从目标可以设置 selector")
        return cls(target_type, selector)


@dataclass(frozen=True)
class CardDefinition:
    id: str
    name: str
    type: str
    base_cost: int
    templates: tuple[str, ...]
    default_target: Target
    allowed_targets: frozenset[str]
    traits: frozenset[str]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], label: str) -> "CardDefinition":
        _reject_unknown(
            data,
            {
                "id",
                "name",
                "type",
                "base_cost",
                "templates",
                "default_target",
                "allowed_targets",
                "traits",
            },
            label,
        )
        card_id = _require_id(data.get("id"), f"{label}.id")
        name = _require_string(data.get("name"), f"{label}.name")
        card_type = _require_string(data.get("type"), f"{label}.type")
        if card_type not in {"follower", "spell", "amulet"}:
            raise BattleProfileError(f"{label}.type 不受支持: {card_type}")
        base_cost = _require_int(data.get("base_cost"), f"{label}.base_cost", 0, 20)

        templates = tuple(
            _require_string(item, f"{label}.templates[]")
            for item in _as_list(data.get("templates"), f"{label}.templates")
        )
        if not templates or len(set(templates)) != len(templates):
            raise BattleProfileError(f"{label}.templates 必须是非空且不重复的数组")

        allowed_targets = frozenset(
            _require_string(item, f"{label}.allowed_targets[]")
            for item in _as_list(data.get("allowed_targets"), f"{label}.allowed_targets")
        )
        if not allowed_targets or not allowed_targets <= TARGET_TYPES:
            raise BattleProfileError(f"{label}.allowed_targets 包含不支持的目标")
        default_target_name = _require_string(
            data.get("default_target"), f"{label}.default_target"
        )
        if default_target_name not in allowed_targets:
            raise BattleProfileError(
                f"{label}.default_target 必须出现在 allowed_targets 中"
            )

        traits = frozenset(
            _require_string(item, f"{label}.traits[]")
            for item in _as_list(data.get("traits", []), f"{label}.traits")
        )
        supported_traits = {"storm", "rush", "ward", "generated"}
        if not traits <= supported_traits:
            raise BattleProfileError(f"{label}.traits 包含不支持的特性")
        return cls(
            id=card_id,
            name=name,
            type=card_type,
            base_cost=base_cost,
            templates=templates,
            default_target=Target(default_target_name),
            allowed_targets=allowed_targets,
            traits=traits,
        )


@dataclass(frozen=True)
class CardCatalog:
    cards: Mapping[str, CardDefinition]
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CardCatalog":
        _reject_unknown(data, {"schema_version", "cards"}, "card_catalog")
        version = _require_int(data.get("schema_version"), "schema_version", 1, 1)
        cards: dict[str, CardDefinition] = {}
        for index, raw in enumerate(
            _as_list(data.get("cards"), "cards"), start=1
        ):
            card = CardDefinition.from_dict(
                _as_object(raw, f"cards[{index}]"), f"cards[{index}]"
            )
            if card.id in cards:
                raise BattleProfileError(f"card_catalog 包含重复卡牌 ID: {card.id}")
            cards[card.id] = card
        return cls(cards=cards, schema_version=version)


@dataclass(frozen=True)
class DeckEntry:
    card_id: str
    copies: int


@dataclass(frozen=True)
class PlayCondition:
    minimum_energy: int = 0
    minimum_board_slots: int = 0
    enemy_ward: str = "any"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], label: str) -> "PlayCondition":
        _reject_unknown(
            data,
            {"minimum_energy", "minimum_board_slots", "enemy_ward"},
            label,
        )
        minimum_energy = _require_int(
            data.get("minimum_energy", 0), f"{label}.minimum_energy", 0, 20
        )
        minimum_board_slots = _require_int(
            data.get("minimum_board_slots", 0),
            f"{label}.minimum_board_slots",
            0,
            5,
        )
        enemy_ward = _require_string(
            data.get("enemy_ward", "any"), f"{label}.enemy_ward"
        )
        if enemy_ward not in {"any", "present", "absent"}:
            raise BattleProfileError(f"{label}.enemy_ward 不受支持: {enemy_ward}")
        return cls(minimum_energy, minimum_board_slots, enemy_ward)


@dataclass(frozen=True)
class CardRule:
    enabled: bool = True
    play_priority: int = 0
    target: Target | None = None
    max_uses_per_turn: int = 3
    when: PlayCondition = field(default_factory=PlayCondition)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], label: str) -> "CardRule":
        _reject_unknown(
            data,
            {"enabled", "play_priority", "target", "max_uses_per_turn", "when"},
            label,
        )
        target_data = data.get("target")
        target = (
            Target.from_dict(_as_object(target_data, f"{label}.target"), f"{label}.target")
            if target_data is not None
            else None
        )
        when_data = _as_object(data.get("when", {}), f"{label}.when")
        return cls(
            enabled=_optional_bool(data, "enabled", True, label),
            play_priority=_require_int(
                data.get("play_priority", 0), f"{label}.play_priority", -1000, 1000
            ),
            target=target,
            max_uses_per_turn=_require_int(
                data.get("max_uses_per_turn", 3),
                f"{label}.max_uses_per_turn",
                1,
                20,
            ),
            when=PlayCondition.from_dict(when_data, f"{label}.when"),
        )


@dataclass(frozen=True)
class ComboStep:
    card_id: str
    target: Target | None = None


@dataclass(frozen=True)
class ComboRule:
    id: str
    priority: int
    steps: tuple[ComboStep, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], label: str) -> "ComboRule":
        _reject_unknown(data, {"id", "priority", "steps"}, label)
        steps: list[ComboStep] = []
        for index, raw in enumerate(_as_list(data.get("steps"), f"{label}.steps"), start=1):
            step_data = _as_object(raw, f"{label}.steps[{index}]")
            _reject_unknown(step_data, {"card_id", "target"}, f"{label}.steps[{index}]")
            target_data = step_data.get("target")
            steps.append(
                ComboStep(
                    card_id=_require_id(
                        step_data.get("card_id"), f"{label}.steps[{index}].card_id"
                    ),
                    target=(
                        Target.from_dict(
                            _as_object(target_data, f"{label}.steps[{index}].target"),
                            f"{label}.steps[{index}].target",
                        )
                        if target_data is not None
                        else None
                    ),
                )
            )
        if not steps:
            raise BattleProfileError(f"{label}.steps 不能为空")
        return cls(
            id=_require_id(data.get("id"), f"{label}.id"),
            priority=_require_int(
                data.get("priority"), f"{label}.priority", -1000, 1000
            ),
            steps=tuple(steps),
        )


@dataclass(frozen=True)
class AttackPolicy:
    clear_ward: bool = True
    otherwise: str = "enemy_leader"
    attacker_order: str = "lowest_attack_first"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AttackPolicy":
        label = "attack"
        _reject_unknown(data, {"clear_ward", "otherwise", "attacker_order"}, label)
        otherwise = _require_string(data.get("otherwise", "enemy_leader"), "attack.otherwise")
        if otherwise not in {"enemy_leader", "enemy_follower"}:
            raise BattleProfileError(f"attack.otherwise 不受支持: {otherwise}")
        attacker_order = _require_string(
            data.get("attacker_order", "lowest_attack_first"),
            "attack.attacker_order",
        )
        if attacker_order not in {
            "left_to_right",
            "lowest_attack_first",
            "highest_attack_first",
        }:
            raise BattleProfileError(
                f"attack.attacker_order 不受支持: {attacker_order}"
            )
        return cls(
            clear_ward=_optional_bool(data, "clear_ward", True, label),
            otherwise=otherwise,
            attacker_order=attacker_order,
        )


@dataclass(frozen=True)
class EvolutionPolicy:
    enabled: bool = True
    prefer_can_attack: bool = True
    card_priority: tuple[str, ...] = ()
    type_order: tuple[str, ...] = ("super", "normal")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvolutionPolicy":
        label = "evolution"
        _reject_unknown(
            data, {"enabled", "prefer_can_attack", "card_priority", "type_order"}, label
        )
        card_priority = tuple(
            _require_id(item, "evolution.card_priority[]")
            for item in _as_list(data.get("card_priority", []), "evolution.card_priority")
        )
        if len(set(card_priority)) != len(card_priority):
            raise BattleProfileError("evolution.card_priority 不能重复")
        type_order = tuple(
            _require_string(item, "evolution.type_order[]")
            for item in _as_list(
                data.get("type_order", ["super", "normal"]), "evolution.type_order"
            )
        )
        if not type_order or len(set(type_order)) != len(type_order):
            raise BattleProfileError("evolution.type_order 必须非空且不能重复")
        if not set(type_order) <= {"super", "normal"}:
            raise BattleProfileError("evolution.type_order 只能包含 super 和 normal")
        return cls(
            enabled=_optional_bool(data, "enabled", True, label),
            prefer_can_attack=_optional_bool(data, "prefer_can_attack", True, label),
            card_priority=card_priority,
            type_order=type_order,
        )


@dataclass(frozen=True)
class MulliganPolicy:
    enabled: bool = True
    keep: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MulliganPolicy":
        label = "mulligan"
        _reject_unknown(data, {"enabled", "keep"}, label)
        keep = tuple(
            _require_id(item, "mulligan.keep[]")
            for item in _as_list(data.get("keep", []), "mulligan.keep")
        )
        if len(set(keep)) != len(keep):
            raise BattleProfileError("mulligan.keep 不能重复")
        return cls(
            enabled=_optional_bool(data, "enabled", True, label),
            keep=keep,
        )


@dataclass(frozen=True)
class SafetyPolicy:
    max_actions_per_turn: int = 30
    max_retries_per_action: int = 1
    no_progress_limit: int = 3

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SafetyPolicy":
        _reject_unknown(
            data,
            {"max_actions_per_turn", "max_retries_per_action", "no_progress_limit"},
            "safety",
        )
        return cls(
            max_actions_per_turn=_require_int(
                data.get("max_actions_per_turn", 30),
                "safety.max_actions_per_turn",
                1,
                100,
            ),
            max_retries_per_action=_require_int(
                data.get("max_retries_per_action", 1),
                "safety.max_retries_per_action",
                0,
                5,
            ),
            no_progress_limit=_require_int(
                data.get("no_progress_limit", 3),
                "safety.no_progress_limit",
                1,
                10,
            ),
        )


@dataclass(frozen=True)
class BattleProfile:
    id: str
    name: str
    description: str
    deck: tuple[DeckEntry, ...]
    cards: Mapping[str, CardRule]
    combos: tuple[ComboRule, ...]
    attack: AttackPolicy
    evolution: EvolutionPolicy
    mulligan: MulliganPolicy
    safety: SafetyPolicy
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BattleProfile":
        _reject_unknown(
            data,
            {
                "$schema",
                "schema_version",
                "id",
                "name",
                "description",
                "deck",
                "cards",
                "combos",
                "attack",
                "evolution",
                "mulligan",
                "safety",
            },
            "battle_profile",
        )
        version = _require_int(data.get("schema_version"), "schema_version", 1, 1)
        deck: list[DeckEntry] = []
        for index, raw in enumerate(_as_list(data.get("deck"), "deck"), start=1):
            item = _as_object(raw, f"deck[{index}]")
            _reject_unknown(item, {"card_id", "copies"}, f"deck[{index}]")
            deck.append(
                DeckEntry(
                    _require_id(item.get("card_id"), f"deck[{index}].card_id"),
                    _require_int(item.get("copies"), f"deck[{index}].copies", 1, 3),
                )
            )
        if not deck:
            raise BattleProfileError("deck 不能为空")
        if len({item.card_id for item in deck}) != len(deck):
            raise BattleProfileError("deck 不能包含重复 card_id")
        if sum(item.copies for item in deck) > 40:
            raise BattleProfileError("deck 的卡牌总数不能超过 40")

        cards_data = _as_object(data.get("cards"), "cards")
        cards = {
            _require_id(card_id, "cards 的键"): CardRule.from_dict(
                _as_object(rule, f"cards.{card_id}"), f"cards.{card_id}"
            )
            for card_id, rule in cards_data.items()
        }

        combos = tuple(
            ComboRule.from_dict(_as_object(raw, f"combos[{index}]"), f"combos[{index}]")
            for index, raw in enumerate(
                _as_list(data.get("combos", []), "combos"), start=1
            )
        )
        if len({combo.id for combo in combos}) != len(combos):
            raise BattleProfileError("combos 不能包含重复 id")

        description = data.get("description", "")
        if not isinstance(description, str):
            raise BattleProfileError("description 必须是字符串")
        return cls(
            id=_require_id(data.get("id"), "id"),
            name=_require_string(data.get("name"), "name"),
            description=description,
            deck=tuple(deck),
            cards=cards,
            combos=combos,
            attack=AttackPolicy.from_dict(
                _as_object(data.get("attack", {}), "attack")
            ),
            evolution=EvolutionPolicy.from_dict(
                _as_object(data.get("evolution", {}), "evolution")
            ),
            mulligan=MulliganPolicy.from_dict(
                _as_object(data.get("mulligan", {}), "mulligan")
            ),
            safety=SafetyPolicy.from_dict(
                _as_object(data.get("safety", {}), "safety")
            ),
            schema_version=version,
        )


@dataclass(frozen=True)
class ObservedCard:
    card_id: str
    hand_index: int
    playable: bool
    observed_cost: int | None = None

    def __post_init__(self) -> None:
        if not VALID_ID.fullmatch(self.card_id):
            raise ValueError(f"非法观测卡牌 ID: {self.card_id!r}")
        if self.hand_index < 1:
            raise ValueError("hand_index 必须是正整数")
        if self.observed_cost is not None and self.observed_cost < 0:
            raise ValueError("observed_cost 不能是负数")


@dataclass(frozen=True)
class BattleState:
    energy: int
    board_slots: int
    enemy_has_ward: bool
    hand: tuple[ObservedCard, ...]
    played_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.energy <= 20:
            raise ValueError("energy 必须在 0 到 20 之间")
        if not 0 <= self.board_slots <= 5:
            raise ValueError("board_slots 必须在 0 到 5 之间")
        indexes = [card.hand_index for card in self.hand]
        if len(set(indexes)) != len(indexes):
            raise ValueError("hand 不能包含重复 hand_index")
        if any(count < 0 for count in self.played_counts.values()):
            raise ValueError("played_counts 不能包含负数")


@dataclass(frozen=True)
class PlannedCardPlay:
    card_id: str
    target: Target
    hand_index: int


@dataclass(frozen=True)
class ActionPlan:
    reason: str
    priority: int
    steps: tuple[PlannedCardPlay, ...]
