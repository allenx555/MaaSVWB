from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from PIL import Image

PROJECT_ROOT = (
    Path(os.environ["MAASVWB_ROOT"]).resolve()
    if os.environ.get("MAASVWB_ROOT")
    else (
        Path(sys.executable).resolve().parent.parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
)
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

from actions.execute_solution import ExecuteSolution  # noqa: E402
from actions.execute_dungeon import ExecuteDungeon  # noqa: E402
from runtime.events import JsonContextEventSink, JsonTaskEventSink, emit_event  # noqa: E402
from runtime.session import choose_device, connect_controller, create_tasker  # noqa: E402


REFERENCE_RESOLUTION = (1280, 720)
STOP_WAIT_TIMEOUT_SECONDS = 5


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 MaaSVWB 安卓模拟器任务")
    parser.add_argument("--adb", type=Path, help="模拟器 adb.exe 的完整路径")
    parser.add_argument("--serial", help="设备地址/序列号；不填时使用发现到的第一台设备")
    parser.add_argument(
        "--task",
        choices=("tutorial", "puzzle", "dungeon"),
        default="puzzle",
        help="执行的任务类型",
    )
    parser.add_argument("--solution", help="解法 ID；盘面解密默认使用 puzzle_001")
    parser.add_argument("--profile", default="aggro_nightmare", help="地城对战策略 ID")
    parser.add_argument("--battle-count", type=int, default=1, help="地城目标胜利场数")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真正执行点击/拖动；不加此参数时只连接并截图",
    )
    parser.add_argument(
        "--skip-completed",
        action="store_true",
        help="从列表启动时，若目标题目同时显示完成和已领取则跳过",
    )
    parser.add_argument(
        "--reset-before-execute",
        action="store_true",
        help="调试用：当前在关卡内时先点击左侧重置按钮",
    )
    parser.add_argument(
        "--start-step",
        type=int,
        default=1,
        help="调试用：从解法的指定步骤开始执行（从 1 开始）",
    )
    parser.add_argument("--stop-file", type=Path, help="前端用于请求优雅停止的控制文件")
    parser.add_argument(
        "--save-draw",
        action="store_true",
        help="保存 Maa 识别绘制图到 debug/vision",
    )
    return parser.parse_args()


def save_screenshot(controller) -> tuple[int, int]:
    screenshot = controller.post_screencap().wait()
    if not screenshot.succeeded:
        raise RuntimeError("模拟器截图失败")
    image = screenshot.get()
    height, width = image.shape[:2]
    print(f"截图成功: {width} x {height}；设备原始分辨率: {controller.resolution}")
    output_path = PROJECT_ROOT / "debug" / "smoke.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if image.ndim == 3 and image.shape[2] >= 3:
        Image.fromarray(image[:, :, :3][:, :, ::-1]).save(output_path)
    else:
        Image.fromarray(image).save(output_path)
    print(f"截图已保存: {output_path}")
    if height > width:
        print("警告：当前是竖屏，请先把游戏切换为横屏。")
    return width, height


def start_stop_monitor(
    tasker: Tasker,
    stop_file: Path | None,
    done_event: threading.Event,
    stop_event: threading.Event,
) -> threading.Thread | None:
    if stop_file is None:
        return None
    stop_file = stop_file.resolve()
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.unlink(missing_ok=True)

    def monitor() -> None:
        while not done_event.wait(0.2):
            if not stop_file.is_file():
                continue
            stop_event.set()
            request_task_stop(tasker, "收到停止请求，正在停止 Maa 任务")
            return

    thread = threading.Thread(target=monitor, name="maasvwb-stop-monitor", daemon=True)
    thread.start()
    return thread


def request_task_stop(
    tasker: Tasker,
    message: str,
    timeout_seconds: float | None = None,
) -> bool:
    """发送统一的 Maa 停止请求，并可选地限制等待时间。"""
    emit_event("control", message, state="stopping")
    try:
        stop_job = tasker.post_stop()
        if timeout_seconds is None:
            stop_job.wait()
            return True
        deadline = time.monotonic() + timeout_seconds
        while not stop_job.done and time.monotonic() < deadline:
            time.sleep(0.05)
        return bool(stop_job.done)
    except Exception as error:
        emit_event("control", f"Maa 停止请求失败：{error}", state="failed")
        return False


def wait_task_interruptibly(tasker: Tasker, task, poll_interval: float = 0.1) -> bool:
    """等待 Maa 任务，同时让 Windows 主线程能够及时处理 Ctrl+C。"""
    try:
        while not task.done:
            time.sleep(poll_interval)
        return True
    except KeyboardInterrupt:
        print("\n[停止] 收到 Ctrl+C，正在停止 Maa 任务", flush=True)
        request_task_stop(
            tasker,
            "收到 Ctrl+C，正在停止 Maa 任务",
            STOP_WAIT_TIMEOUT_SECONDS,
        )
        return False


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    solution_id = args.solution or ("puzzle_001" if args.task == "puzzle" else None)
    if args.battle_count < 1 or args.battle_count > 99:
        raise RuntimeError("战斗次数必须在 1 到 99 之间。")
    if args.execute and args.task != "dungeon" and not solution_id:
        raise RuntimeError("执行教程时必须通过 --solution 指定已录入的教程脚本。")

    Toolkit.init_option(str(PROJECT_ROOT))
    if args.save_draw:
        Tasker.set_save_draw(True)
        Tasker.set_debug_mode(True)
    device = choose_device(args.adb, args.serial, print)
    print(f"连接设备: {device.name} ({device.address})")
    controller = connect_controller(device)
    screenshot_size = save_screenshot(controller)

    if not args.execute:
        print("只读连接测试完成。")
        return 0

    if screenshot_size != REFERENCE_RESOLUTION:
        raise RuntimeError(
            "当前 Maa 截图为 "
            f"{screenshot_size[0]}x{screenshot_size[1]}，必须将模拟器设为 1280x720 后再执行"
        )

    tasker = create_tasker(
        PROJECT_ROOT,
        controller,
        ExecuteSolution(),
        {"ExecuteDungeon": ExecuteDungeon()},
    )
    tasker.add_sink(JsonTaskEventSink())
    tasker.add_context_sink(JsonContextEventSink())
    if args.task == "dungeon":
        entry = "执行地城试炼"
        display_target = f"{args.profile} / {args.battle_count} 场胜利"
        override = {
            entry: {
                "custom_action_param": {
                    "profile": args.profile,
                    "battle_count": args.battle_count,
                }
            }
        }
    else:
        entry = "执行解法"
        display_target = str(solution_id)
        override = {
            entry: {
                "custom_action_param": {
                    "solution": solution_id,
                    "skip_completed": args.skip_completed,
                    "reset_before_execute": args.reset_before_execute,
                    "start_step": args.start_step,
                }
            }
        }
    done_event = threading.Event()
    stop_event = threading.Event()
    monitor = start_stop_monitor(tasker, args.stop_file, done_event, stop_event)
    try:
        print(f"即将执行: {args.task} / {display_target}")
        emit_event("run", f"即将执行：{args.task} / {display_target}", state="starting")
        task = tasker.post_task(entry, override)
        if not wait_task_interruptibly(tasker, task):
            emit_event("run", "任务已由用户停止", state="stopped")
            return 130
        if stop_event.is_set():
            emit_event("run", "任务已由用户停止", state="stopped")
            return 130
        if not task.succeeded:
            raise RuntimeError("任务执行失败，请检查 debug/maafw.log")
        detail = task.get()
        if detail is None:
            raise RuntimeError("任务成功但未能读取任务详情，请检查 debug/maafw.log")
        print(f"任务执行完成: task_id={detail.task_id}, entry={detail.entry}")
        return 0
    finally:
        done_event.set()
        if monitor is not None:
            monitor.join(timeout=1)
        if args.stop_file is not None:
            args.stop_file.resolve().unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
