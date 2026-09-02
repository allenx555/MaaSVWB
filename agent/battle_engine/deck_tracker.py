from __future__ import annotations

from dataclasses import dataclass, field

from .models import BattleProfile, ObservedCard


@dataclass
class DeckTracker:
    """Tracks own-deck cards remaining during a battle.

    remaining = initial_copies - cards_in_hand_now - cards_played_total
    """

    initial_counts: dict[str, int]
    played_total: dict[str, int] = field(default_factory=dict)
    hand_snapshot: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: BattleProfile) -> DeckTracker:
        initial = {entry.card_id: entry.copies for entry in profile.deck}
        return cls(initial_counts=initial)

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
