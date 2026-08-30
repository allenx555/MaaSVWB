from __future__ import annotations

from pathlib import Path
from typing import Callable

from maa.controller import AdbController
from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit


def choose_device(
    adb_path: Path | None = None,
    serial: str | None = None,
    on_multiple: Callable[[str], None] | None = None,
):
    devices = Toolkit.find_adb_devices(adb_path) if adb_path else Toolkit.find_adb_devices()
    if serial:
        devices = [device for device in devices if device.address == serial]
    if not devices:
        raise RuntimeError(
            "未找到 ADB 设备。请启动模拟器、开启 ADB，并通过 --adb 指定 adb.exe。"
        )
    if len(devices) > 1 and not serial and on_multiple is not None:
        on_multiple("发现多台设备，默认使用第一台；可用 --serial 精确指定：")
        for device in devices:
            on_multiple(f"  {device.name}: {device.address}")
    return devices[0]


def connect_controller(device, short_side: int = 720) -> AdbController:
    controller = AdbController(
        adb_path=device.adb_path,
        address=device.address,
        screencap_methods=device.screencap_methods,
        input_methods=device.input_methods,
        config=device.config,
    )
    controller.set_screenshot_target_short_side(short_side)
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError("ADB Controller 连接失败，请检查 debug 日志")
    return controller


def create_tasker(
    project_root: Path,
    controller: AdbController,
    action: CustomAction,
) -> Tasker:
    resource_root = next(
        (
            candidate
            for candidate in (
                project_root / "assets" / "resource",
                project_root / "resource",
            )
            if candidate.is_dir()
        ),
        None,
    )
    if resource_root is None:
        raise RuntimeError("找不到 MaaSVWB resource 目录")
    resource = Resource()
    bundle = resource.post_bundle(str(resource_root)).wait()
    if not bundle.succeeded:
        raise RuntimeError("资源加载失败，请检查 Pipeline 和 debug 日志")
    if not resource.register_custom_action("ExecuteSolution", action):
        raise RuntimeError("注册 ExecuteSolution 自定义动作失败")

    tasker = Tasker()
    tasker.bind(resource, controller)
    if not tasker.inited:
        raise RuntimeError("MaaFramework Tasker 初始化失败")
    return tasker
