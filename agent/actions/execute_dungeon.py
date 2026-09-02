from __future__ import annotations

import json
import logging

from maa.context import Context
from maa.custom_action import CustomAction

from runtime.dungeon_runner import run_dungeon


LOGGER = logging.getLogger("maasvwb.dungeon")


class ExecuteDungeon(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        try:
            params = json.loads(argv.custom_action_param or "{}")
            profile_id = str(params.get("profile", "aggro_nightmare"))
            battle_count = int(params.get("battle_count", 1))
            deck_code = params.get("deck_code") or None
            print(
                f"自定义动作开始: dungeon / {profile_id} / {battle_count}",
                flush=True,
            )
            run_dungeon(context, profile_id, battle_count, deck_code=deck_code)
            print("自定义动作结束: dungeon", flush=True)
            return True
        except Exception:
            LOGGER.exception("地城试炼执行失败，节点=%s", argv.node_name)
            return False
