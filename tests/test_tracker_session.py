from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
from typing import cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from battle_engine.deck_tracker import DeckTracker
from battle_engine.models import ObservedCard
from battle_engine.observer import ObservedHandCard
from runtime.backend import MaaBackend
from runtime.hand_observer import HandObservation, HandObserver
from runtime.tracker_session import DeckTrackingSession
from runtime.tracker_runner import TrackerRunner
from battle_engine.models import CardCatalog
from battle_engine.repository import CardCatalogRepository
from pipeline_nodes import BATTLE_MULLIGAN, BATTLE_PLAYER_TURN, BATTLE_VICTORY
from test_deck_tracker import _make_catalog


def observation(*ids: str) -> HandObservation:
    return HandObservation(tuple(
        ObservedHandCard(ObservedCard(cid, i, True), cid, (0, 0), 1.0)
        for i, cid in enumerate(ids, 1)
    ), True, "ok")


class ReadOnlyBackend:
    # Deliberately no tap/swipe/input methods: the standalone path must be read-only.
    def __init__(self) -> None:
        self.scene = BATTLE_PLAYER_TURN
        self.count: int | None = 1
        self.names = ["alpha"]
        self.frames: list[object] = []

    def verify(self, node, frame):
        return self.scene == node

    def read_hand_count(self, *, frame):
        self.frames.append(frame)
        return self.count

    def read_deck_count(self, *, frame):
        self.frames.append(frame)
        return None

    def recognize(self, node, *, frame):
        self.frames.append(frame)
        return SimpleNamespace(hit=True, all_results=[
            SimpleNamespace(text=name, box=[300 + 150 * i, 580, 100, 20])
            for i, name in enumerate(self.names)
        ])


class TrackerSessionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _make_catalog(("alpha", "aaa"), ("beta", "bbb"))
        self.session = DeckTrackingSession(DeckTracker({"alpha": 3, "beta": 3}), self.catalog, "test")
        self.events = patch("runtime.tracker_session.emit_deck_update").start()
        self.addCleanup(patch.stopall)

    def accept(self, value):
        self.session.observe(value)
        self.session.observe(value)

    def test_partial_and_unstable_frames_do_not_change_counts(self):
        self.accept(observation("alpha", "beta"))
        self.assertEqual(self.session.tracker.total_remaining, 4)
        self.session.observe(observation("alpha"))
        self.session.observe(HandObservation(reason="partial"))
        self.session.observe(observation("alpha"))
        self.assertEqual(self.session.tracker.hand_snapshot, {"alpha": 1, "beta": 1})
        self.assertEqual(self.session.tracker.total_remaining, 4)

    def test_unknown_return_then_redraw_keeps_observed_total(self):
        self.accept(replace(observation("alpha"), deck_count=5))
        self.accept(replace(observation(), deck_count=6))
        self.assertEqual(self.session.tracker.total_remaining, 6)
        self.assertEqual(self.session.tracker.unknown_count, 1)
        self.assertEqual(self.session.tracker.remaining["alpha"], 2)
        self.accept(replace(observation("alpha"), deck_count=5))
        self.assertEqual(self.session.tracker.total_remaining, 5)
        self.assertEqual(sum(self.events.call_args.args[0].values()), 5)
        self.assertEqual(self.events.call_args.args[1]["__unknown__"], "构成未知")

    def test_deck_total_must_stabilize_with_hand(self):
        self.accept(replace(observation("alpha"), deck_count=5))
        self.session.observe(replace(observation(), deck_count=6))
        self.session.observe(replace(observation(), deck_count=7))
        self.assertEqual(self.session.tracker.total_remaining, 5)
        self.accept(replace(observation(), deck_count=6))
        self.assertEqual(self.session.tracker.total_remaining, 6)

    def test_explicit_hand_return_does_not_double_count_next_observation(self):
        self.accept(replace(observation("alpha"), deck_count=5))
        self.session.record_returned("alpha", source="hand")
        self.accept(replace(observation(), deck_count=6))
        self.assertEqual(self.session.tracker.remaining, {"alpha": 3, "beta": 3})
        self.assertEqual(self.session.tracker.unknown_count, 0)

    def test_unseen_deck_loss_marks_composition_uncertain(self):
        self.accept(replace(observation("alpha"), deck_count=5))
        self.accept(replace(observation("alpha"), deck_count=4))
        self.assertEqual(self.session.tracker.total_remaining, 4)
        self.assertEqual(self.session.tracker.remaining, {"alpha": 1, "beta": 2})
        self.assertEqual(self.session.tracker.unknown_count, 1)

    def test_generated_card_can_be_shuffled_above_initial_counts(self):
        self.session.record_returned("token", count=4)
        self.assertEqual(self.session.tracker.remaining["token"], 4)
        self.assertEqual(self.session.tracker.total_remaining, 10)

    def test_incomplete_hand_cannot_commit_a_return(self):
        self.accept(replace(observation("alpha"), deck_count=5))
        self.accept(HandObservation(complete=False, deck_count=6))
        self.assertEqual(self.session.tracker.total_remaining, 5)
        self.assertEqual(self.session.tracker.unknown_count, 0)

    def test_missing_deck_ocr_preserves_unknown_returns(self):
        self.accept(replace(observation("alpha"), deck_count=5))
        self.accept(replace(observation(), deck_count=6))
        self.accept(observation())
        self.assertEqual(self.session.tracker.total_remaining, 6)
        self.assertIsNone(self.session.tracker.observed_total)

    def test_returned_card_can_be_drawn_and_played_again(self):
        self.accept(replace(observation("alpha"), deck_count=5))
        self.session.record_returned("alpha", source="hand")
        self.accept(replace(observation(), deck_count=6))
        self.accept(replace(observation("alpha"), deck_count=5))
        self.session.record_played("alpha")
        self.accept(replace(observation(), deck_count=5))
        self.assertEqual(self.session.tracker.remaining, {"alpha": 2, "beta": 3})
        self.assertEqual(self.session.tracker.unknown_count, 0)

    def test_deck_ocr_uses_supplied_frame_and_rejects_non_numeric_text(self):
        backend = object.__new__(MaaBackend)
        frame = object()
        for raw, expected in [("33", 33), ("0", 0), ("41", 41),
                              ("3/3", None), ("牌库33", None), ("", None)]:
            with self.subTest(raw=raw), patch.object(backend, "recognize", return_value=
                    SimpleNamespace(hit=True, best_result=SimpleNamespace(text=raw))) as recognize:
                self.assertEqual(backend.read_deck_count(frame=frame), expected)
                recognize.assert_called_once_with("识别_当前牌库数量", frame=frame)

    def test_manual_play_and_later_draw_count_once(self):
        self.accept(observation("alpha"))
        self.accept(observation())
        self.assertEqual(self.session.tracker.total_remaining, 5)
        self.accept(observation("alpha"))
        self.assertEqual(self.session.tracker.total_remaining, 4)
        self.accept(observation("alpha"))
        self.assertEqual(self.session.tracker.total_remaining, 4)

    def test_automatic_play_then_failed_ocr_preserves_count(self):
        self.accept(observation("alpha"))
        self.session.record_played("alpha")
        self.session.observe(HandObservation(reason="failed"))
        self.assertEqual(self.session.tracker.total_remaining, 5)
        self.accept(observation())
        self.assertEqual(self.session.tracker.total_remaining, 5)

    def test_events_are_deduplicated_and_ordered(self):
        self.accept(observation("alpha"))
        self.accept(observation("alpha"))
        events = self.events.call_args_list
        self.assertEqual([e.kwargs["sequence"] for e in events], [1, 2])
        self.assertTrue(all(e.kwargs["confidence"] == "estimated" for e in events))

    def test_observer_checks_full_count_and_uses_same_frame(self):
        backend = ReadOnlyBackend()
        reader = HandObserver(cast(MaaBackend, backend), self.catalog)
        frame = object()
        backend.count = 2
        self.assertFalse(reader.observe(frame).complete)
        backend.names.append("beta")
        self.assertTrue(reader.observe(frame).complete)
        self.assertTrue(all(f is frame for f in backend.frames))
        backend.count = None
        self.assertFalse(reader.observe(frame).complete)
        backend.count = 0
        self.assertEqual(reader.observe(frame).cards, ())

    def test_observer_rejects_unknown_and_ambiguous_names(self):
        backend = ReadOnlyBackend()
        reader = HandObserver(cast(MaaBackend, backend), self.catalog)
        backend.names = ["unregistered"]
        self.assertFalse(reader.observe(object()).complete)
        backend.names = ["alpha"]
        ambiguous = CardCatalog(cards={
            "alpha": self.catalog.cards["alpha"],
            "other": replace(self.catalog.cards["alpha"], id="other"),
        })
        self.assertFalse(HandObserver(cast(MaaBackend, backend), ambiguous).observe(object()).complete)

    def test_live_mumu_first_turn_single_glyph_error_is_accepted(self):
        # Live 1280x720 OCR from the authorized dungeon test: five real cards,
        # one of the duplicate 幽冥中尉 titles has a consistently wrong glyph.
        catalog = CardCatalogRepository.for_project(Path(__file__).resolve().parents[1]).load()
        ids = {"10501110", "10951120", "10051130", "10951110"}
        catalog = CardCatalog(cards={cid: c for cid, c in catalog.cards.items() if cid in ids})
        backend = ReadOnlyBackend()
        backend.count = 5
        backend.names = ["挥毫的怪物", "幽其中尉", "幽冥中尉", "恶靠的小木乃伊", "强袭的特攻队长"]
        result = HandObserver(cast(MaaBackend, backend), catalog).observe(object())
        self.assertTrue(result.complete)
        self.assertEqual([c.card.card_id for c in result.cards],
                         ["10501110", "10951120", "10951120", "10051130", "10951110"])

    def test_stop_is_checked_without_sending_device_inputs(self):
        backend = ReadOnlyBackend()
        runner = TrackerRunner(cast(MaaBackend, backend), self.catalog,
                               "2.5." + ".".join(["aaa"] * 20 + ["bbb"] * 20))
        with patch.object(backend, "is_stopping", return_value=True, create=True):
            runner.run()
        self.assertEqual(self.events.call_args.kwargs["state"], "stopped")

    def test_standalone_lifecycle_and_no_inputs(self):
        backend = ReadOnlyBackend()
        runner = TrackerRunner(cast(MaaBackend, backend), self.catalog,
                               "2.5." + ".".join(["aaa"] * 20 + ["bbb"] * 20))
        frame = object()
        for _ in range(3):
            runner.tick(frame)
        self.assertEqual(runner.session.tracker.total_remaining, 39)
        session_id = runner.session.session_id
        backend.scene = "opponent_or_overlay"
        for _ in range(3):
            runner.tick(frame)
        self.assertEqual(runner.session.session_id, session_id)
        backend.scene = BATTLE_MULLIGAN
        runner.tick(frame)
        self.assertEqual(runner.session.session_id, session_id)
        runner.tick(frame)
        self.assertNotEqual(runner.session.session_id, session_id)
        self.assertEqual(runner.session.tracker.total_remaining, 40)
        session_id = runner.session.session_id
        runner.tick(frame)
        self.assertEqual(runner.session.session_id, session_id)
        backend.scene = BATTLE_PLAYER_TURN
        for _ in range(3):
            runner.tick(frame)
        backend.scene = BATTLE_VICTORY
        runner.tick(frame)
        runner.tick(frame)
        self.assertEqual(runner.phase, "ended")
        backend.scene = BATTLE_PLAYER_TURN
        for _ in range(3):
            runner.tick(frame)
        self.assertNotEqual(runner.session.session_id, session_id)

    def test_invalid_or_unknown_deck_rejected(self):
        for code in ("", "2.5.aaa", "2.5." + ".".join(["missing"] * 40)):
            with self.subTest(code=code), self.assertRaises(ValueError):
                TrackerRunner(cast(MaaBackend, ReadOnlyBackend()), self.catalog, code)
