"""Prepare local evidence for semantic puzzle authoring; never calls an LLM/device."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PTS_PATTERN = re.compile(r"\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([\d.eE+-]+)")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str], log: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if log:
        log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"{Path(command[0]).name} failed (exit {result.returncode}); log: {log}")
    return result


def bilibili_url(value: str, part: int) -> tuple[str, str]:
    parsed = urlsplit(value)
    match = re.fullmatch(r"/video/(BV[0-9A-Za-z]+)/?", parsed.path)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"www.bilibili.com", "bilibili.com"} or not match:
        raise ValueError("Use a full https://www.bilibili.com/video/BV... URL")
    if part < 1:
        raise ValueError("--part must be positive")
    bvid = match[1]
    return f"https://www.bilibili.com/video/{bvid}?p={part}", bvid


def probe(video: Path) -> dict[str, Any]:
    result = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)])
    data = json.loads(result.stdout)
    stream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if stream is None:
        raise ValueError("Input has no video stream")
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "duration": float(data["format"].get("duration", stream.get("duration", 0)))}


def init_case(case: Path) -> None:
    case.mkdir(parents=True, exist_ok=True)
    (case / "drafts").mkdir(exist_ok=True)
    notes = case / "evidence.md"
    if not notes.exists():
        notes.write_text("""# 解法证据

- 目录 ID / 游戏版本 / 题名：待填写
- 通关目标 / 初始盘面：待填写
- 状态：素材已准备，尚未完成视频分析或实机验证

| 源时间 | 动作前手牌/场上占位 | 主动动作与目标 | 结算后状态 | 证据帧 | 待确认 |
| --- | --- | --- | --- | --- | --- |

## 固定解法成立依据

记录自动效果与主动操作的区别；列出随机结果及共同的后续操作。

## 需要补读的时间段

仅补读不能确定目标、计数、结算的局部片段。

## 验证

- 视频完成证据：待填写
- Schema / 加载器：未执行
- 安卓重置执行 / 完成 / 返回列表：未执行
""", encoding="utf-8")
    usage = case / "usage-template.json"
    if not usage.exists():
        write_json(usage, {"requested_model": "gpt-6.1-sol", "actual_model": None,
                           "reasoning_effort": None, "speed_mode": None,
                           "started_at": None, "finished_at": None, "images_sent": None,
                           "input_tokens": None, "cached_input_tokens": None,
                           "output_tokens": None, "reasoning_tokens": None,
                           "reasoning_included_in_output": None,
                           "window_reset_before": None, "window_reset_after": None,
                           "used_percent_before": None, "used_percent_after": None,
                           "concurrent_account_usage": None,
                           "note": "unknown values stay null; record each call/model separately"})


def download(args: argparse.Namespace) -> None:
    url, bvid = bilibili_url(args.url, args.part)
    case = (args.output / f"{bvid}_p{args.part}").resolve()
    init_case(case)
    source = case / "source"
    source.mkdir(exist_ok=True)
    command = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-progress",
               "--no-overwrites", "--write-info-json", "--socket-timeout", "30", "--retries", "2",
               "-f", "bv+ba/b" if args.audio else "bv/b", "-o", str(source / "%(id)s.%(ext)s"), url]
    run(command, source / "download.log")
    infos = list(source.glob("*.info.json"))
    if len(infos) != 1:
        raise ValueError("Expected one part's metadata; inspect source directory")
    data = json.loads(infos[0].read_text(encoding="utf-8"))
    write_json(case / "source.json", {"url": url, "bvid": bvid, "part": args.part,
                                      **{key: data.get(key) for key in ("id", "title", "duration", "width", "height", "format_id")},
                                      "yt_dlp_version": importlib.metadata.version("yt-dlp")})
    print(f"Downloaded one part: {case}\nRead source.json, then run prepare on the downloaded video.")


def parse_pts(log: str) -> list[float]:
    return [float(m[1]) for m in PTS_PATTERN.finditer(log)]


def select_indices(signatures: list[list[int]], times: list[float], threshold: float, keep_every: float) -> list[int]:
    """Deduplicate against last kept sample, retaining endpoints and periodic context."""
    if not signatures:
        return []
    kept = [0]
    for index in range(1, len(signatures)):
        previous = kept[-1]
        difference = sum(abs(a - b) for a, b in zip(signatures[index], signatures[previous])) / len(signatures[index])
        if difference >= threshold or times[index] - times[previous] >= keep_every:
            kept.append(index)
    if kept[-1] != len(signatures) - 1:
        kept.append(len(signatures) - 1)
    return kept


def prepare(args: argparse.Namespace) -> None:
    image_module = importlib.import_module("PIL.Image")
    draw_module = importlib.import_module("PIL.ImageDraw")
    video = args.video.resolve()
    info = probe(video)
    end = info["duration"] if args.end is None else min(args.end, info["duration"])
    if not all(math.isfinite(v) for v in (args.start, end, args.interval, args.threshold, args.keep_every)):
        raise ValueError("Sampling arguments must be finite")
    if not 0 <= args.start < end or args.interval <= 0 or args.keep_every <= 0 or args.threshold < 0:
        raise ValueError("Require 0 <= start < end, positive interval/keep-every, and nonnegative threshold")
    if not 160 <= args.width <= 3840:
        raise ValueError("--width must be between 160 and 3840")
    if (end - args.start) / args.interval > 600:
        raise ValueError("More than 600 samples: increase --interval or narrow --start/--end")
    filters = [f"select='gte(t,{args.start})*lt(t,{end})*(isnan(prev_selected_t)+gte(t-prev_selected_t,{args.interval}))'", "showinfo"]
    if args.crop:
        x, y, width, height = args.crop
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > info["width"] or y + height > info["height"]:
            raise ValueError("Crop is outside the source video")
        filters.append(f"crop={width}:{height}:{x}:{y}")
    filters.append(f"scale='min({args.width},iw)':-2")
    case = args.output.resolve()
    init_case(case)
    runs = case / "runs"
    runs.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="frames-", dir=runs))
    frames = work / "frames"
    frames.mkdir()
    result = run(["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video),
                  "-an", "-vf", ",".join(filters), "-fps_mode", "vfr", "-q:v", "3",
                  str(frames / "%05d.jpg")], work / "ffmpeg.log")
    paths = sorted(frames.glob("*.jpg"))
    times = parse_pts(result.stderr)
    if not paths or len(paths) != len(times):
        raise ValueError(f"Frame/timestamp mismatch: {len(paths)} / {len(times)}; inspect {work}")
    signatures = []
    for path in paths:
        with image_module.open(path) as img:
            signatures.append(list(img.convert("L").resize((160, 90)).tobytes()))
    kept = select_indices(signatures, times, args.threshold, args.keep_every)
    sheets = []
    for offset in range(0, len(kept), 12):
        batch = kept[offset:offset + 12]
        sheet = image_module.new("RGB", (1440, math.ceil(len(batch) / 3) * 300), "#202020")
        draw = draw_module.Draw(sheet)
        for slot, index in enumerate(batch):
            x, y = slot % 3 * 480, slot // 3 * 300
            with image_module.open(paths[index]) as img:
                img.thumbnail((480, 270))
                sheet.paste(img, (x, y))
            draw.text((x + 8, y + 276), f"{times[index]:.3f}s | {paths[index].name}", fill="white")
        name = f"overview_{offset // 12 + 1:03d}.jpg"
        sheet.save(work / name, quality=90)
        sheets.append(name)
    selected_set = set(kept)
    write_json(work / "frames.json", {"video": str(video), **info, "start": args.start, "end": end,
                                      "interval": args.interval, "crop": args.crop,
                                      "threshold": args.threshold, "keep_every": args.keep_every,
                                      "sample_count": len(paths), "overview_count": len(kept), "sheets": sheets,
                                      "frames": [{"time_seconds": t, "path": f"frames/{p.name}", "in_overview": i in selected_set}
                                                 for i, (p, t) in enumerate(zip(paths, times))]})
    print(f"Prepared {len(paths)} samples; {len(kept)} in {len(sheets)} overview sheets.\n{work}\n"
          "Timestamps are source presentation times. All samples retained; deduplication can miss small actions.")


def validate(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(ROOT / "agent"))
    models = importlib.import_module("solution_engine.models")
    schema_module = importlib.import_module("jsonschema")
    schema = json.loads((ROOT / "assets/schemas/solution.schema.json").read_text(encoding="utf-8"))
    for path in args.files:
        data = json.loads(path.read_text(encoding="utf-8"))
        schema_module.Draft202012Validator(schema).validate(data)
        models.Solution.from_dict(data)
        for step in data["steps"]:
            for index_key, count_key in (("hand_index", "hand_count"), ("attacker_index", "ally_count"),
                                         ("amulet_index", "ally_count"), ("choice_index", "choice_count")):
                if index_key in step and count_key in step and step[index_key] > step[count_key]:
                    raise ValueError(f"{path.name}: {index_key} exceeds {count_key}")
            target = step.get("target", {})
            if "index" in target and "count" in target and target["index"] > target["count"]:
                raise ValueError(f"{path.name}: target index exceeds count")
        print(f"PASS {path.name}: schema, loader, supplied index/count bounds; not emulator verification")


def doctor() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise ValueError(f"Missing {tool} in PATH")
        print(run([tool, "-version"]).stdout.splitlines()[0])
    for package in ("yt-dlp", "Pillow", "jsonschema"):
        print(f"{package} {importlib.metadata.version(package)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("doctor")
    fetch = subs.add_parser("download", help="Download one explicitly selected Bilibili part")
    fetch.add_argument("url")
    fetch.add_argument("--part", type=int, required=True)
    fetch.add_argument("--output", type=Path, default=ROOT / "artifacts/puzzle-video")
    fetch.add_argument("--audio", action="store_true")
    prep = subs.add_parser("prepare", help="Sample, deduplicate, and make timestamped overview sheets")
    prep.add_argument("video", type=Path)
    prep.add_argument("--output", type=Path, required=True, help="Case directory; each run creates a new subdirectory")
    prep.add_argument("--start", type=float, default=0)
    prep.add_argument("--end", type=float)
    prep.add_argument("--interval", type=float, default=2)
    prep.add_argument("--width", type=int, default=1280)
    prep.add_argument("--threshold", type=float, default=2.0)
    prep.add_argument("--keep-every", type=float, default=8)
    prep.add_argument("--crop", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    check = subs.add_parser("validate", help="Validate candidate JSON without registering or executing it")
    check.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            doctor()
        else:
            {"download": download, "prepare": prepare, "validate": validate}[args.command](args)
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
