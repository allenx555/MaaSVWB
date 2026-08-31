from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


MIN_BATTLE_COUNT = 1
MAX_BATTLE_COUNT = 99
MAX_CONSECUTIVE_FAILURES = 3


class SettlementAction(str, Enum):
    """下一步结算动作；STOP 用于失败或无法确认结果的安全停止。"""

    REPLAY = "replay"
    RETURN_TO_DUNGEON = "return_to_dungeon"
    STOP = "stop"


@dataclass
class BattleSession:
    """记录一次地城试炼会话的目标胜场和连续失败次数。

    battle_count 包含首次挑战。失败不计入完成数；连续失败超过三次时安全停止。
    """

    battle_count: int
    victories: int = 0
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.battle_count, bool) or not isinstance(
            self.battle_count, int
        ):
            raise ValueError("battle_count 必须是整数")
        if not MIN_BATTLE_COUNT <= self.battle_count <= MAX_BATTLE_COUNT:
            raise ValueError(
                "battle_count 必须在 "
                f"{MIN_BATTLE_COUNT} 到 {MAX_BATTLE_COUNT} 之间"
            )
        if isinstance(self.victories, bool) or not isinstance(self.victories, int):
            raise ValueError("victories 必须是整数")
        if not 0 <= self.victories <= self.battle_count:
            raise ValueError("victories 超出本次会话的目标战斗次数")
        if (
            isinstance(self.consecutive_failures, bool)
            or not isinstance(self.consecutive_failures, int)
            or self.consecutive_failures < 0
        ):
            raise ValueError("consecutive_failures 必须是非负整数")

    @property
    def remaining_victories(self) -> int:
        return max(0, self.battle_count - self.victories)

    def record_victory(self) -> SettlementAction:
        if self.victories >= self.battle_count:
            raise RuntimeError("本次地城试炼会话已经结束")
        self.victories += 1
        self.consecutive_failures = 0
        return (
            SettlementAction.REPLAY
            if self.victories < self.battle_count
            else SettlementAction.RETURN_TO_DUNGEON
        )

    def record_defeat(self) -> SettlementAction:
        self.consecutive_failures += 1
        return (
            SettlementAction.STOP
            if self.consecutive_failures > MAX_CONSECUTIVE_FAILURES
            else SettlementAction.REPLAY
        )

    @staticmethod
    def record_unknown() -> SettlementAction:
        return SettlementAction.STOP
