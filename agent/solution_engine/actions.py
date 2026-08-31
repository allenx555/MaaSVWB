from __future__ import annotations


SUPPORTED_ACTIONS = frozenset(
    {
        "tap",
        "swipe",
        "wait",
        "key",
        "verify",
        "confirm_mulligan",
        "read_energy",
        "use_extra_energy",
        "play_card",
        "attack",
        "select_target",
        "select_choice",
        "evolve",
        "activate_amulet",
        "end_turn",
        "skip_dialogue",
    }
)

