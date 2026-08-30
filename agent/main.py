import sys
from pathlib import Path


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main():
    configure_utf8_stdio()
    if len(sys.argv) < 2:
        print("用法: MaaSVWB.Agent <socket_id>")
        print("socket_id 由 MaaFramework 通用 UI 注入。")
        return 1

    from maa.agent.agent_server import AgentServer
    from maa.tasker import Tasker

    from actions.execute_solution import ExecuteSolution

    project_root = (
        Path(sys.executable).resolve().parent.parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    Tasker.set_log_dir(project_root / "debug")
    AgentServer.custom_action("ExecuteSolution")(ExecuteSolution)

    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
