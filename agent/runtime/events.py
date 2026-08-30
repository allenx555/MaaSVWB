from __future__ import annotations

import json
from typing import Any

from maa.context import ContextEventSink
from maa.tasker import TaskerEventSink


EVENT_PREFIX = "@maasvwb-event "


def emit_event(event: str, message: str, **details: Any) -> None:
    payload = {"event": event, "message": message, **details}
    print(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)


class JsonTaskEventSink(TaskerEventSink):
    def on_raw_notification(self, _tasker, msg: str, details: dict[str, Any]) -> None:
        if not msg.startswith("Tasker.Task."):
            return
        state = msg.rsplit(".", 1)[-1].lower()
        entry = details.get("entry", "")
        labels = {
            "starting": "Maa 任务开始",
            "succeeded": "Maa 任务完成",
            "failed": "Maa 任务失败",
        }
        emit_event("maa_task", labels.get(state, msg), state=state, name=entry)


class JsonContextEventSink(ContextEventSink):
    def on_raw_notification(self, _context, msg: str, details: dict[str, Any]) -> None:
        if not (
            msg.startswith("Node.PipelineNode.")
            or msg.startswith("Node.WaitFreezes.")
        ):
            return
        state = msg.rsplit(".", 1)[-1].lower()
        name = details.get("name", "")
        emit_event("maa_node", f"{name}: {state}", state=state, name=name)
