from __future__ import annotations

import json
import logging

from maa.context import Context
from maa.custom_action import CustomAction
from battle_engine.repository import CardCatalogRepository
from runtime.backend import MaaBackend
from runtime.runner import _load_layout, resolve_project_root
from runtime.tracker_runner import TrackerRunner


class ExecuteDeckTracker(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        try:
            params = json.loads(argv.custom_action_param or "{}")
            root = resolve_project_root()
            TrackerRunner(MaaBackend(context, _load_layout(root)),
                          CardCatalogRepository.for_project(root).load(),
                          str(params.get("deck_code") or "")).run()
            return True
        except Exception:
            logging.getLogger("maasvwb.tracker").exception("记牌器监听失败")
            return False
