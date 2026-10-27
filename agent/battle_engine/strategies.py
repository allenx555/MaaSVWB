from __future__ import annotations

from .models import BattleState


class GenericStrategy:
    use_extra_energy = False

    def allow_card(self, card_id: str, state: BattleState) -> bool:
        return True

    def setup_bonus(self, card_id: str, added_followers: int) -> int:
        return 0


class AggroNightmareStrategy(GenericStrategy):
    """Deck-specific choices, not card mechanics or device operations."""

    use_extra_energy = True

    def allow_card(self, card_id: str, state: BattleState) -> bool:
        if card_id == "10552310":  # 残虐的炸裂：快攻不主动用它只打自己。
            return (state.ally_health is not None and state.enemy_health is not None
                    and state.enemy_health <= state.ally_health)
        return True

    def setup_bonus(self, card_id: str, added_followers: int) -> int:
        return added_followers if card_id == "10253120" else 0  # 艾瑟拉
