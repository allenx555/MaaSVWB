from __future__ import annotations

import logging
import time

from maa.context import Context

from battle_engine.policy import BattlePolicy
from battle_engine.repository import BattleProfileRepository, CardCatalogRepository
from pipeline_nodes import (
    DUNGEON_CHALLENGE,
    DUNGEON_DECK_CONFIRM,
    DUNGEON_LIST,
    DUNGEON_REPLAY,
    DUNGEON_RETURN,
)
from solution_engine.layout import BoardLayout
from solution_engine.models import SolutionError

from .backend import MaaBackend
from .battle_runner import BattleOutcome, BattleRunner
from .dungeon_session import DungeonSession, DungeonSettlementAction
from .events import emit_event
from .runner import _load_layout, resolve_project_root


LOGGER = logging.getLogger("maasvwb.dungeon")


class DungeonRunner:
    """负责地城入口、牌组确认和战后连战，不包含基础对战逻辑。"""

    def __init__(
        self,
        backend: MaaBackend,
        layout: BoardLayout,
        battle_runner: BattleRunner,
        session: DungeonSession,
    ) -> None:
        self.backend = backend
        self.layout = layout
        self.battle_runner = battle_runner
        self.session = session

    def run(self) -> None:
        while True:
            self._enter_or_resume_battle()
            outcome = self.battle_runner.run()
            if outcome is BattleOutcome.VICTORY:
                action = self.session.record_victory()
                emit_event(
                    "dungeon",
                    f"胜利 {self.session.victories}/{self.session.battle_count}",
                    state="progress",
                )
            elif outcome is BattleOutcome.DEFEAT:
                action = self.session.record_defeat()
                emit_event(
                    "dungeon",
                    f"本局失败，连续失败 {self.session.consecutive_failures} 次",
                    state="progress",
                )
            else:
                action = self.session.record_unknown()

            if action is DungeonSettlementAction.RETURN_TO_DUNGEON:
                if not self.backend.tap_recognition(DUNGEON_RETURN, 15_000):
                    raise SolutionError("达到目标胜场后未能点击返回地城")
                LOGGER.info("地城目标已完成：%d 场胜利", self.session.victories)
                return
            if action is DungeonSettlementAction.STOP:
                if outcome is BattleOutcome.UNKNOWN:
                    raise SolutionError("无法确认战斗结算状态，已安全停止")
                raise SolutionError("连续失败超过两次，已停止地城试炼")
            if not self.backend.tap_recognition(DUNGEON_REPLAY, 15_000):
                raise SolutionError("结算后未能点击再战")
            time.sleep(2.0)

    def _enter_or_resume_battle(self) -> None:
        deadline = time.monotonic() + 120
        stage_clicked = False
        while time.monotonic() < deadline:
            if self.backend.is_stopping():
                raise SolutionError("地城试炼已停止")
            frame = self.backend.capture_frame()
            if frame is None:
                time.sleep(0.5)
                continue
            if self.battle_runner.is_start_state(frame):
                return
            if self.backend.verify(DUNGEON_DECK_CONFIRM, frame):
                LOGGER.info("[开局] 使用游戏当前牌组并点击决定")
                if not self.backend.tap(*self.layout.fixed_point("dungeon_deck_decide")):
                    raise SolutionError("确认当前牌组失败")
                time.sleep(4.0)
                continue
            if self.backend.verify(DUNGEON_CHALLENGE, frame):
                if not self.backend.tap_recognition(DUNGEON_CHALLENGE, 3_000):
                    raise SolutionError("点击地城挑战按钮失败")
                time.sleep(1.0)
                continue
            if self.backend.verify(DUNGEON_LIST, frame) and not stage_clicked:
                LOGGER.info("[入口] 选择当前第一个地城关卡")
                if not self.backend.tap(*self.layout.fixed_point("dungeon_stage_first")):
                    raise SolutionError("点击地城关卡失败")
                stage_clicked = True
                time.sleep(1.0)
                continue
            time.sleep(0.5)
        raise SolutionError("120 秒内未能进入地城战斗")


def run_dungeon(context: Context, profile_id: str, battle_count: int) -> None:
    project_root = resolve_project_root()
    catalog = CardCatalogRepository.for_project(project_root).load()
    profile = BattleProfileRepository.for_project(project_root, catalog).load(profile_id)
    layout = _load_layout(project_root)
    backend = MaaBackend(context, layout)
    battle_runner = BattleRunner(
        backend,
        layout,
        catalog,
        BattlePolicy(profile, catalog),
    )
    session = DungeonSession(battle_count=battle_count)
    emit_event(
        "dungeon",
        f"开始地城试炼：目标 {battle_count} 场胜利",
        state="starting",
    )
    DungeonRunner(backend, layout, battle_runner, session).run()
    emit_event("dungeon", "地城试炼目标完成", state="succeeded")
