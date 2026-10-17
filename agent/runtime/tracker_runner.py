from __future__ import annotations

import time

from battle_engine.deck_tracker import DeckTracker
from battle_engine.models import CardCatalog
from pipeline_nodes import BATTLE_MULLIGAN, BATTLE_PLAYER_TURN, BATTLE_VICTORY, BATTLE_DEFEAT
from .backend import MaaBackend
from .hand_observer import HandObserver
from .tracker_session import DeckTrackingSession


class TrackerRunner:
    """One device owner, screenshot/recognition only. No automation policy."""

    def __init__(self, backend: MaaBackend, catalog: CardCatalog, deck_code: str) -> None:
        self.backend = backend
        self.catalog = catalog
        self.deck_code = deck_code
        self.session = self._new_session()
        self.phase = "waiting"
        self._pending_phase = ""
        self._phase_hits = 0

    def _new_session(self) -> DeckTrackingSession:
        tracker = DeckTracker.from_deck_code(self.deck_code, self.catalog)
        if tracker.total_remaining != 40:
            raise ValueError("独立记牌需要完整的 40 张牌组码")
        unknown = set(tracker.initial_counts) - set(self.catalog.cards)
        if unknown:
            raise ValueError("卡牌目录缺少这些牌组码 ID：" + ", ".join(sorted(unknown)))
        session = DeckTrackingSession(tracker, self.catalog, "standalone")
        self.observer = HandObserver(self.backend, session.candidate_catalog())
        return session

    def tick(self, frame) -> None:
        if frame is None:
            self._phase_hits = 0
            self.session.invalidate("截图失败，保留上次结果")
            return
        if self.backend.verify(BATTLE_MULLIGAN, frame):
            detected = "mulligan"
        elif self.backend.verify(BATTLE_PLAYER_TURN, frame):
            detected = "playing"
        elif (self.backend.verify(BATTLE_VICTORY, frame)
              or self.backend.verify(BATTLE_DEFEAT, frame)
              or self.backend.verify("识别_记牌器通用结算", frame)):
            detected = "ended"
        else:
            detected = "waiting"
        self._phase_hits = self._phase_hits + 1 if detected == self._pending_phase else 1
        self._pending_phase = detected
        if self._phase_hits < 2:
            self.session.invalidate("正在确认对局画面")
            return
        if detected == "mulligan":
            if self.phase != "mulligan":
                self.session = self._new_session()
            self.phase = "mulligan"
            self.session.invalidate("换牌中；正式回合开始后记录", "mulligan")
        elif detected == "playing":
            if self.phase == "ended":
                self.session = self._new_session()
            self.phase = "playing"
            self.session.observe(self.observer.observe(frame))
        elif detected == "ended":
            self.phase = "ended"
            self.session.invalidate("对局结束，等待下一局", "ended")
        else:
            # Opponent turns and transient overlays must not reset the deck.
            self.session.invalidate("等待己方回合或展开手牌；保留上次结果", "waiting")

    def run(self) -> None:
        self.session.publish("waiting", "监听已启动，请从开局开始并在己方回合展开手牌")
        try:
            while not self.backend.is_stopping():
                self.tick(self.backend.capture_frame())
                time.sleep(0.5)
        finally:
            self.session.invalidate("监听已停止，显示最后一次估计", "stopped")
