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
        self._candidate_total: int | None = None

    def publish(self, state: str, reason: str) -> None:
        counts = self.tracker.remaining
        names = {cid: c.name for cid, c in self.catalog.cards.items()}
        if self.tracker.unknown_count:
            counts["__unknown__"] = self.tracker.unknown_count
            names["__unknown__"] = "构成未知"
            reason += f"；{self.tracker.unknown_count} 张构成未知（洗回或未完整观察的效果）"
        payload = (state, reason, tuple(sorted(counts.items())))
        if payload == self._last_payload:
            return
        self._last_payload = payload
        self.sequence += 1
        emit_deck_update(counts, names,
                         session_id=self.session_id, sequence=self.sequence,
                         mode=self.mode, state=state, confidence="estimated", reason=reason,
                         unknown_count=self.tracker.unknown_count,
                         observed_total=self.tracker.observed_total)

    def invalidate(self, reason: str, state: str = "uncertain") -> None:
        self._candidate = None
        self._candidate_total = None
        self.publish(state, reason)

    def observe(self, observation: HandObservation) -> bool:
        if not observation.complete:
            self.invalidate(observation.reason)
            return False
        counts = dict(Counter(c.card.card_id for c in observation.cards))
        if counts != self._candidate or observation.deck_count != self._candidate_total:
            self._candidate = counts
            self._candidate_total = observation.deck_count
            self.publish("stabilizing", "正在确认手牌，请保持展开")
            return False
        self.tracker.update_hand(tuple(c.card for c in observation.cards))
        if observation.deck_count is not None:
            self.tracker.reconcile_total(observation.deck_count)
        else:
            self.tracker.observed_total = None
        self.publish("tracking", "手牌已更新；牌库总数已校验" if observation.deck_count is not None
                     else "手牌已更新（估计）；牌库数字未识别，洗回校验暂不可用")
        return True

    def record_played(self, card_id: str) -> None:
        self.tracker.record_played(card_id)
        self._candidate = None
        self.publish("tracking", "已记录自动出牌，等待下一次手牌确认")

    def record_returned(self, card_id: str, *, source: str = "other", count: int = 1) -> None:
        # Effect adapters must emit once, before observing the resulting hand.
        self.tracker.record_returned(card_id, source=source, count=count)
        self._candidate = None
        self._candidate_total = None
        self.publish("tracking", "已记录确认的洗回事件，等待牌库总数校验")

    def candidate_catalog(self) -> CardCatalog:
        # Include known generated cards so they do not get forced onto deck cards.
        return CardCatalog(cards={cid: c for cid, c in self.catalog.cards.items()
                                  if cid in self.tracker.initial_counts
                                  or cid in self.tracker.deck_counts or "generated" in c.traits})
