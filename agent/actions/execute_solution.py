from __future__ import annotations

import json
import logging

from maa.context import Context
from maa.custom_action import CustomAction

from runtime.runner import run_solution


LOGGER = logging.getLogger("maasvwb.solution")


class ExecuteSolution(CustomAction):
    """加载并执行一个人工录入的教程或盘面解密方案。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        try:
            params = json.loads(argv.custom_action_param or "{}")
            solution_id = params["solution"]
            print(f"自定义动作开始: {solution_id}", flush=True)
            run_solution(
                context,
                solution_id,
                skip_completed=bool(params.get("skip_completed", False)),
                reset_before_execute=bool(
                    params.get("reset_before_execute", False)
                ),
                start_step=int(params.get("start_step", 1)),
            )
            print(f"自定义动作结束: {solution_id}", flush=True)
            return True
        except Exception:
            LOGGER.exception("解法执行失败，节点=%s", argv.node_name)
            return False
