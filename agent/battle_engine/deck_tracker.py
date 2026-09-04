from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import BattleProfile, CardCatalog, ObservedCard

# Matches the canonical deck code: two version numbers followed by card short-IDs,
# e.g. "2.5.e3ls.e3ls.fGAU". Used to extract the code from multi-line share text.
_DECK_CODE_RE = re.compile(r"\d+\.\d+(?:\.[A-Za-z0-9-]+)+")


@dataclass
class DeckTracker:
    """Tracks own-deck cards remaining during a battle.

    remaining = initial_copies - cards_in_hand_now - cards_played_total

    换牌不计入：记牌器只在正式回合出牌时被更新，换回牌库的
    起手牌会随第一次手牌快照自然扣除，不需要单独记录。

    已知限制：暂不支持被「洗回牌库」或「弹回手牌」的卡牌。这类卡一旦经
    ``record_played`` 记为打出便不会回退，而实际已重新回到牌库/手牌，因此
    remaining 可能偏少。若将来需要，应在卡牌被移出场时相应回退计数。
    """

    initial_counts: dict[str, int]
    played_total: dict[str, int] = field(default_factory=dict)
    hand_snapshot: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: BattleProfile) -> DeckTracker:
        initial = {entry.card_id: entry.copies for entry in profile.deck}
        return cls(initial_counts=initial)

    @classmethod
    def from_deck_code(cls, code: str, catalog: CardCatalog) -> DeckTracker:
        code_to_catalog = {
            defn.deck_code_id: cid
            for cid, defn in catalog.cards.items()
            if defn.deck_code_id
        }
        m = _DECK_CODE_RE.search(code)
        if not m:
            return cls(initial_counts={})
        parts = m.group().split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            parts = parts[2:]
        counts: dict[str, int] = {}
        for short_id in parts:
            if not short_id:
                continue
            catalog_id = code_to_catalog.get(short_id, short_id)
            counts[catalog_id] = counts.get(catalog_id, 0) + 1
        return cls(initial_counts=counts)

    def update_hand(self, hand: tuple[ObservedCard, ...]) -> None:
        """Snapshot the current hand (called each time the hand is observed)."""
        snapshot: dict[str, int] = {}
        for card in hand:
            snapshot[card.card_id] = snapshot.get(card.card_id, 0) + 1
        self.hand_snapshot = snapshot

    def record_played(self, card_id: str) -> None:
        """Record one copy of card_id successfully played from hand."""
        self.played_total[card_id] = self.played_total.get(card_id, 0) + 1

    @property
    def remaining(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for card_id, copies in self.initial_counts.items():
            used = self.played_total.get(card_id, 0) + self.hand_snapshot.get(card_id, 0)
            count = max(0, copies - used)
            if count > 0:
                result[card_id] = count
        return result

    @property
    def total_remaining(self) -> int:
        return sum(self.remaining.values())

