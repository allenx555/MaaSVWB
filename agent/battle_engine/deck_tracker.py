from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import BattleProfile, CardCatalog, ObservedCard

# Matches the canonical deck code: two version numbers followed by card short-IDs,
# e.g. "2.5.e3ls.e3ls.fGAU". Used to extract the code from multi-line share text.
_DECK_CODE_RE = re.compile(r"\d+\.\d+(?:\.[A-Za-z0-9_-]+)+")


@dataclass
class DeckTracker:
    """Tracks own-deck cards remaining during a battle.

    Mutable deck ledger; unknown slots preserve the observed deck size.

    换牌不计入：记牌器只在正式回合出牌时被更新，换回牌库的
    起手牌会随第一次手牌快照自然扣除，不需要单独记录。

    played_total includes confirmed automatic plays and observed disappearances.
    Snapshot differences cannot distinguish generated cards, returns or hidden
    same-name replacements. Values are estimates, never authoritative deck state.
    """

    initial_counts: dict[str, int]
    played_total: dict[str, int] = field(default_factory=dict)
    hand_snapshot: dict[str, int] = field(default_factory=dict)
    deck_counts: dict[str, int] = field(init=False)
    unknown_count: int = 0
    observed_total: int | None = None

    def __post_init__(self) -> None:
        self.deck_counts = dict(self.initial_counts)

    def reconcile_total(self, total: int) -> None:
        """Reconcile a stable OCR total without inventing card identities.

        An unexplained loss could be any named card. Reduce each named lower
        bound by that loss and retain the rest as unknown composition.
        """
        if total < 0:
            raise ValueError("牌库数量不能为负数")
        deficit = self.total_remaining - total
        if deficit > 0:
            self.deck_counts = {cid: max(0, n - deficit)
                                for cid, n in self.deck_counts.items()}
        self.unknown_count = total - sum(self.deck_counts.values())
        self.observed_total = total

    def record_returned(self, card_id: str, *, source: str = "other", count: int = 1) -> None:
        """Apply a confirmed return, not a guess from hand disappearance."""
        if source not in {"hand", "other"} or count <= 0:
            raise ValueError("无效的洗回事件")
        if source == "hand":
            if self.hand_snapshot.get(card_id, 0) < count:
                raise ValueError("洗回数量超过已知手牌")
            self.hand_snapshot[card_id] -= count
        self.deck_counts[card_id] = self.deck_counts.get(card_id, 0) + count
        self.observed_total = None

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
        """Accept a complete hand; disappearance never puts a card back in deck.

        Callers must reject partial OCR results before calling this method.
        Unobserved same-name replacements and generated/returned cards remain
        ambiguous, so snapshot-based counts are estimates.
        """
        snapshot: dict[str, int] = {}
        for card in hand:
            snapshot[card.card_id] = snapshot.get(card.card_id, 0) + 1
        for card_id, count in snapshot.items():
            drawn = max(0, count - self.hand_snapshot.get(card_id, 0))
            self.deck_counts[card_id] = max(0, self.deck_counts.get(card_id, 0) - drawn)
        for card_id, old_count in self.hand_snapshot.items():
            disappeared = max(0, old_count - snapshot.get(card_id, 0))
            self.played_total[card_id] = self.played_total.get(card_id, 0) + disappeared
        self.hand_snapshot = snapshot

    def record_played(self, card_id: str) -> None:
        """Record one copy of card_id successfully played from hand."""
        self.played_total[card_id] = self.played_total.get(card_id, 0) + 1
        if not self.hand_snapshot.get(card_id, 0):
            # Automatic play can confirm a card missed by the last hand OCR.
            self.deck_counts[card_id] = max(0, self.deck_counts.get(card_id, 0) - 1)
        # Atomically move the known card out of the hand. A failed next OCR must
        # not count the same physical copy both in hand and as played.
        self.hand_snapshot[card_id] = max(0, self.hand_snapshot.get(card_id, 0) - 1)

    @property
    def remaining(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for card_id, count in self.deck_counts.items():
            if count > 0:
                result[card_id] = count
        return result

    @property
    def total_remaining(self) -> int:
        return sum(self.remaining.values()) + self.unknown_count

