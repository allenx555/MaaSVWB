from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from maa.context import Context  # noqa: E402
from maa.custom_action import CustomAction  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402
from runtime.backend import MaaBackend  # noqa: E402
from runtime.puzzle_navigator import PuzzleNavigator  # noqa: E402
from runtime.session import choose_device, connect_controller, create_tasker  # noqa: E402


class DumpPuzzleText(CustomAction):
    def __init__(
        self,
        reset_to_top: bool,
        scroll_pages: int,
        scroll_distance: int,
        clicks: list[tuple[int, int]],
        find_clicks: list[str],
        tutorial_titles: bool,
        screenshot_path: Path | None,
    ) -> None:
        super().__init__()
        self.reset_to_top = reset_to_top
        self.scroll_pages = scroll_pages
        self.scroll_distance = scroll_distance
        self.clicks = clicks
        self.find_clicks = find_clicks
        self.tutorial_titles = tutorial_titles
        self.screenshot_path = screenshot_path

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        controller = context.tasker.controller
        for x, y in self.clicks:
            if not controller.post_click(x, y).wait().succeeded:
                raise RuntimeError(f"点击失败：({x}, {y})")
            time.sleep(1.5)
        if self.reset_to_top:
            for _ in range(8):
                if not controller.post_swipe(430, 260, 430, 570, 900).wait().succeeded:
                    raise RuntimeError("列表回顶失败")
                time.sleep(1.1)
        backend = MaaBackend(context)
        navigator = PuzzleNavigator(backend)
        for pattern in self.find_clicks:
            detail = navigator.find_in_scroll_list(
                "识别_盘面解密类别",
                pattern,
                (430, 260),
                (430, 570),
                20,
            )
            if detail is None or detail.box is None:
                raise RuntimeError(f"未找到列表分类：{pattern}")
            box = detail.box
            if not controller.post_click(
                box.x + box.w // 2,
                box.y + box.h // 2,
            ).wait().succeeded:
                raise RuntimeError(f"点击列表分类失败：{pattern}")
            time.sleep(1.5)

        pages = []
        for page_index in range(self.scroll_pages + 1):
            pages.append(self._recognize(context, page_index))
            if page_index < self.scroll_pages:
                if not controller.post_swipe(
                    430,
                    570,
                    430,
                    max(220, 570 - self.scroll_distance),
                    900,
                ).wait().succeeded:
                    raise RuntimeError("列表滚动失败")
                time.sleep(1.4)
        if self.screenshot_path is not None:
            self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            image = context.tasker.controller.cached_image
            Image.fromarray(image[:, :, ::-1]).save(self.screenshot_path)
        if self.tutorial_titles:
            seen = set()
            titles = []
            for page in pages:
                rows = page["rows"]
                for difficulty in (row for row in rows if row["text"].strip() == "难度"):
                    difficulty_y = difficulty["box"][1]
                    candidates = [
                        row
                        for row in rows
                        if row["box"][0] < 300
                        and 0 < difficulty_y - row["box"][1] < 55
                        and row["text"].strip() != "难度"
                    ]
                    if not candidates:
                        continue
                    candidate = min(
                        candidates,
                        key=lambda row: difficulty_y - row["box"][1],
                    )
                    title = candidate["text"].strip()
                    title_y = candidate["box"][1]
                    tag_candidates = [
                        row
                        for row in rows
                        if row["box"][0] >= 300
                        and 0 < title_y - row["box"][1] < 70
                        and not row["text"].strip().startswith("×")
                    ]
                    tag = (
                        min(
                            tag_candidates,
                            key=lambda row: title_y - row["box"][1],
                        )["text"].strip()
                        if tag_candidates
                        else ""
                    )
                    key = (title, tag)
                    if key not in seen:
                        seen.add(key)
                        titles.append(
                            {
                                "title": title,
                                "tag": tag,
                                "page": page["page"],
                                "box": candidate["box"],
                                "score": candidate["score"],
                            }
                        )
            print(json.dumps(titles, ensure_ascii=False, indent=2), flush=True)
        else:
            print(json.dumps(pages, ensure_ascii=False, indent=2), flush=True)
        return True

    @staticmethod
    def _recognize(context: Context, page_index: int) -> dict:
        capture = context.tasker.controller.post_screencap().wait()
        if not capture.succeeded:
            raise RuntimeError("模拟器截图失败")
        detail = context.run_recognition(
            "识别_盘面解密名称",
            context.tasker.controller.cached_image,
            {"识别_盘面解密名称": {"expected": ".+"}},
        )
        rows = []
        for result in detail.all_results if detail else []:
            result_box = getattr(result, "box", None)
            if result_box is None:
                continue
            box = list(result_box)
            rows.append(
                {
                    "text": getattr(result, "text", ""),
                    "box": box,
                    "score": getattr(result, "score", None),
                }
            )
        return {"page": page_index, "rows": rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读输出盘面解密列表 OCR 结果")
    parser.add_argument("--adb", type=Path, help="模拟器 adb.exe 的完整路径")
    parser.add_argument("--serial", help="设备地址/序列号")
    parser.add_argument("--reset-to-top", action="store_true", help="采集前将左侧列表慢速拖回顶部")
    parser.add_argument("--scroll-pages", type=int, default=0, help="向列表底部滚动并额外采集的页数")
    parser.add_argument("--scroll-distance", type=int, default=310, help="每次列表向下移动的近似距离")
    parser.add_argument(
        "--click",
        action="append",
        default=[],
        metavar="X,Y",
        help="采集前依次点击指定的 Maa 720p 坐标",
    )
    parser.add_argument(
        "--find-click",
        action="append",
        default=[],
        metavar="REGEX",
        help="回顶后按 OCR 正则查找并点击列表分类",
    )
    parser.add_argument(
        "--tutorial-titles",
        action="store_true",
        help="仅输出对战教程列表中的去重标题",
    )
    parser.add_argument("--screenshot", type=Path, help="保存采集结束时的模拟器截图")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    Toolkit.init_option(str(PROJECT_ROOT))
    device = choose_device(args.adb, args.serial)
    controller = connect_controller(device)
    clicks = []
    for value in args.click:
        try:
            x_text, y_text = value.split(",", 1)
            clicks.append((int(x_text), int(y_text)))
        except ValueError as error:
            raise ValueError(f"无效 --click 坐标：{value}") from error

    tasker = create_tasker(
        PROJECT_ROOT,
        controller,
        DumpPuzzleText(
            args.reset_to_top,
            max(0, args.scroll_pages),
            max(80, min(350, args.scroll_distance)),
            clicks,
            args.find_click,
            args.tutorial_titles,
            args.screenshot,
        ),
    )
    task = tasker.post_task("执行解法").wait()
    if not task.succeeded:
        raise RuntimeError("目录 OCR 失败")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
