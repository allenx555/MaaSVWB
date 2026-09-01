from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from .models import CardCatalog, ObservedCard


_IGNORED_NAME_CHARACTERS = re.compile(r"[^0-9A-Za-z\u3400-\u9fff]")


def normalize_card_name(value: str) -> str:
    return _IGNORED_NAME_CHARACTERS.sub("", value).lower()


def match_card_name(
    observed_name: str,
    catalog: CardCatalog,
    *,
    minimum_score: float = 0.52,
) -> tuple[str, float] | None:
    normalized = normalize_card_name(observed_name)
    if len(normalized) < 2:
        return None

    candidates: list[tuple[float, str]] = []
    for card_id, definition in catalog.cards.items():
        expected = normalize_card_name(definition.name)
        if normalized == expected:
            score = 1.0
        elif normalized in expected or expected in normalized:
            score = min(len(normalized), len(expected)) / max(
                len(normalized), len(expected)
            )
        else:
            score = SequenceMatcher(None, normalized, expected).ratio()
        candidates.append((score, card_id))

    score, card_id = max(candidates, default=(0.0, ""))
    if score < minimum_score:
        return None
    return card_id, score


@dataclass(frozen=True)
class HandText:
    text: str
    x: int
    y: int
    width: int
    height: int

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2


@dataclass(frozen=True)
class ObservedHandCard:
    card: ObservedCard
    name: str
    source: tuple[int, int]
    score: float


def recognition_results_to_hand_texts(results: Iterable[object]) -> tuple[HandText, ...]:
    """把 Maa OCR 结果转换为与具体玩法无关的卡名文本框。"""
    texts: list[HandText] = []
    for result in results:
        text = getattr(result, "text", "")
        box = getattr(result, "box", None)
        if not text or box is None:
            continue
        if isinstance(box, (list, tuple)) and len(box) == 4:
            x, y, width, height = (int(value) for value in box)
        else:
            x = int(getattr(box, "x"))
            y = int(getattr(box, "y"))
            width = int(getattr(box, "w"))
            height = int(getattr(box, "h"))
        texts.append(HandText(str(text), x, y, width, height))
    return tuple(texts)


def parse_hand_texts(
    texts: Iterable[HandText],
    catalog: CardCatalog,
    energy: int,
    *,
    source_y: int = 665,
) -> tuple[ObservedHandCard, ...]:
    matches: list[tuple[HandText, str, float]] = []
    for text in texts:
        matched = match_card_name(text.text, catalog)
        if matched is None:
            continue
        card_id, score = matched
        matches.append((text, card_id, score))

    matches.sort(key=lambda item: item[0].center_x)
    return tuple(
        ObservedHandCard(
            card=ObservedCard(
                card_id=card_id,
                hand_index=index,
                playable=catalog.cards[card_id].base_cost <= energy,
                observed_cost=catalog.cards[card_id].base_cost,
            ),
            name=catalog.cards[card_id].name,
            source=(text.center_x, source_y),
            score=score,
        )
        for index, (text, card_id, score) in enumerate(matches, start=1)
    )
