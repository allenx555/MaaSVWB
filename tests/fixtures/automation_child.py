"""Controlled child process for the C# AutomationService integration tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main() -> int:
    root = Path.cwd()
    source = Path((root / "source-root.txt").read_text(encoding="utf-8"))
    sys.path[:0] = [str(source / "tools"), str(source / "agent")]
    # Exercise the real CLI parser and Python event producer consumed by C#.
    from run_android import parse_args
    from runtime.events import emit_deck_update, emit_event

    args = parse_args()
    mode = (root / "mode.txt").read_text(encoding="utf-8")
    data = vars(args).copy()
    project_root = os.environ.get("MAASVWB_ROOT")
    data.update(
        pid=os.getpid(),
        cwd=str(root),
        project_root=project_root,
        # macOS can expose the same temporary directory through /var and
        # /private/var. Verify filesystem identity, not the spelling of getcwd().
        cwd_matches_project_root=project_root is not None and root.samefile(project_root),
    )
    (root / "arguments.json").write_text(json.dumps(data, default=str), encoding="utf-8")
    if mode in {"ignore-stop", "cancel", "dispose"}:
        # The parent must also clean up descendants when forcing termination.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        (root / "descendant.pid").write_text(str(child.pid), encoding="utf-8")
    emit_event("fixture", "子进程就绪", state="ready")
    if mode in {"graceful", "ignore-stop", "cancel", "dispose"}:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if mode == "graceful" and args.stop_file and args.stop_file.is_file():
                emit_event("run", "任务已由用户停止", state="stopped")
                return 130
            time.sleep(0.02)
        return 99
    if mode == "crash":
        print("预期的测试错误", file=sys.stderr, flush=True)
        return 7
    if mode == "malformed":
        print('@maasvwb-event {broken', flush=True)
        print('@maasvwb-event {"event":"deck_update","total":"bad","entries":[]}', flush=True)
    emit_deck_update({"test": 3}, {"test": "测试卡牌"},
                     session_id="integration-session", sequence=1,
                     state="tracking", reason="已更新")
    print("最后一行输出", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
