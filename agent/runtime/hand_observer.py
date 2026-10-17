from __future__ import annotations

from dataclasses import dataclass

from battle_engine.models import CardCatalog
from battle_engine.observer import (
    HandText, ObservedHandCard, normalize_card_name, parse_hand_texts,
    recognition_results_to_hand_texts,
)
from pipeline_nodes import BATTLE_HAND_NAMES
from .backend import MaaBackend


def hand_is_expanded(texts: tuple[HandText, ...]) -> bool:
    return any(
        len(normalize_card_name(t.text)) >= 2
        and not normalize_card_name(t.text).isdigit()
        and 560 <= t.y <= 610 and t.height >= 14
        for t in texts
    )


@dataclass(frozen=True)
class HandObservation:
    cards: tuple[ObservedHandCard, ...] = ()
    complete: bool = False
    reason: str = "等待展开手牌"


class HandObserver:
    """Read-only hand recognition; never taps or changes the device state."""

    def __init__(self, backend: MaaBackend, catalog: CardCatalog) -> None:
        self.backend = backend
        self.catalog = catalog

    def observe(self, frame) -> HandObservation:
        if frame is None:
            return HandObservation(reason="截图失败，保留上次结果")
        count = self.backend.read_hand_count(frame=frame)
        if count is None:
            return HandObservation(reason="手牌数量未识别，保留上次结果")
        if count == 0:
            return HandObservation(complete=True, reason="空手牌")
        detail = self.backend.recognize(BATTLE_HAND_NAMES, frame=frame)
        texts = recognition_results_to_hand_texts(
            detail.all_results if detail and detail.hit else ()
        )
        if not hand_is_expanded(texts):
            return HandObservation(reason="请在游戏中展开手牌；当前保留上次结果")
        texts = tuple(t for t in texts if 560 <= t.y <= 610 and t.height >= 14)
        # A single glyph error in a four-character name scores 0.75 (live OCR:
        # 幽冥中尉 -> 幽其中尉). Candidates are deck-scoped, with an ambiguity
        # margin, full-hand count and consecutive-frame checks applied as well.
        cards = parse_hand_texts(texts, self.catalog, energy=20, minimum_score=0.72,
                                 minimum_margin=0.08)
        complete = len(cards) == count
        return HandObservation(cards, complete,
                               "手牌已识别" if complete else f"只识别到 {len(cards)}/{count} 张，保留上次结果")
