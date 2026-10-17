from __future__ import annotations

from collections import Counter
from uuid import uuid4

from battle_engine.deck_tracker import DeckTracker
from battle_engine.models import CardCatalog
from .events import emit_deck_update
from .hand_observer import HandObservation


class DeckTrackingSession:
    """Shared by automation and the standalone read-only observer.

    Only two consecutive complete, identical observations are committed.
    Counts are estimates: screenshots cannot prove the provenance of cards.
    """

    def __init__(self, tracker: DeckTracker, catalog: CardCatalog, mode: str) -> None:
        self.tracker = tracker
        self.catalog = catalog
        self.mode = mode
        self.session_id = uuid4().hex
        self.sequence = 0
        self._candidate: dict[str, int] | None = None
        self._last_payload: tuple | None = None

    def publish(self, state: str, reason: str) -> None:
        counts = self.tracker.remaining
        payload = (state, reason, tuple(sorted(counts.items())))
        if payload == self._last_payload:
            return
        self._last_payload = payload
        self.sequence += 1
        emit_deck_update(counts, {cid: c.name for cid, c in self.catalog.cards.items()},
                         session_id=self.session_id, sequence=self.sequence,
                         mode=self.mode, state=state, confidence="estimated", reason=reason)

    def invalidate(self, reason: str, state: str = "uncertain") -> None:
        self._candidate = None
        self.publish(state, reason)

    def observe(self, observation: HandObservation) -> bool:
        if not observation.complete:
            self.invalidate(observation.reason)
            return False
        counts = dict(Counter(c.card.card_id for c in observation.cards))
        if counts != self._candidate:
            self._candidate = counts
            self.publish("stabilizing", "正在确认手牌，请保持展开")
            return False
        self.tracker.update_hand(tuple(c.card for c in observation.cards))
        self.publish("tracking", "手牌已更新（估计；特殊效果及漏帧可能造成偏差）")
        return True

    def record_played(self, card_id: str) -> None:
        self.tracker.record_played(card_id)
        self._candidate = None
        self.publish("tracking", "已记录自动出牌，等待下一次手牌确认")

    def candidate_catalog(self) -> CardCatalog:
        # Include known generated cards so they do not get forced onto deck cards.
        return CardCatalog(cards={cid: c for cid, c in self.catalog.cards.items()
                                  if cid in self.tracker.initial_counts or "generated" in c.traits})
