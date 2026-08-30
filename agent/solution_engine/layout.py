from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SolutionError


Point = tuple[int, int]
Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class BoardLayout:
    """把手牌/随从序号转换为 MaaFramework 的触控位置。"""

    fixed: dict[str, Point]
    indexed: dict[str, dict[int, tuple[Point, ...]]]
    regions: dict[str, Rect]

    @classmethod
    def load(cls, path: Path) -> "BoardLayout":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SolutionError(f"无法读取布局文件 {path}: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BoardLayout":
        fixed = {
            name: cls._parse_point(point, f"fixed.{name}")
            for name, point in data.get("fixed", {}).items()
        }
        indexed: dict[str, dict[int, tuple[Point, ...]]] = {}
        for zone_name, count_map in data.get("indexed", {}).items():
            if not isinstance(count_map, dict):
                raise SolutionError(f"indexed.{zone_name} 必须是对象")
            indexed[zone_name] = {}
            for raw_count, raw_points in count_map.items():
                try:
                    count = int(raw_count)
                except (TypeError, ValueError) as exc:
                    raise SolutionError(f"indexed.{zone_name} 包含非法数量 {raw_count!r}") from exc
                if not isinstance(raw_points, list) or len(raw_points) != count:
                    raise SolutionError(
                        f"indexed.{zone_name}.{count} 必须包含 {count} 个坐标"
                    )
                indexed[zone_name][count] = tuple(
                    cls._parse_point(point, f"indexed.{zone_name}.{count}")
                    for point in raw_points
                )
        regions = {
            name: cls._parse_rect(rect, f"regions.{name}")
            for name, rect in data.get("regions", {}).items()
        }
        return cls(fixed=fixed, indexed=indexed, regions=regions)

    def fixed_point(self, name: str) -> Point:
        try:
            return self.fixed[name]
        except KeyError as exc:
            raise SolutionError(f"布局中没有固定位置: {name}") from exc

    def indexed_point(self, zone: str, count: int, index: int) -> Point:
        if not isinstance(count, int) or count < 1:
            raise SolutionError(f"{zone} 的 count 必须是正整数")
        if not isinstance(index, int) or index < 1:
            raise SolutionError(f"{zone} 的 index 从 1 开始")
        try:
            points = self.indexed[zone][count]
        except KeyError as exc:
            raise SolutionError(f"布局不支持 {zone} 数量={count}") from exc
        if index > len(points):
            raise SolutionError(f"{zone} 只有 {count} 个对象，无法选择第 {index} 个")
        return points[index - 1]

    def region(self, name: str) -> Rect:
        try:
            return self.regions[name]
        except KeyError as exc:
            raise SolutionError(f"布局中没有状态校验区域: {name}") from exc

    @staticmethod
    def _parse_point(value: object, field: str) -> Point:
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(coordinate, int) for coordinate in value)
        ):
            raise SolutionError(f"{field} 必须是 [x, y]")
        return value[0], value[1]

    @staticmethod
    def _parse_rect(value: object, field: str) -> Rect:
        if (
            not isinstance(value, list)
            or len(value) != 4
            or not all(isinstance(coordinate, int) for coordinate in value)
            or value[2] <= 0
            or value[3] <= 0
        ):
            raise SolutionError(f"{field} 必须是 [x, y, width, height]，且宽高为正数")
        return value[0], value[1], value[2], value[3]
