from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .actions import SUPPORTED_ACTIONS


class SolutionError(ValueError):
    """解法文件无效，或某一步执行失败。"""


@dataclass(frozen=True)
class Solution:
    id: str
    name: str
    category: str
    reference_resolution: tuple[int, int]
    points: dict[str, tuple[int, int]]
    steps: tuple[dict[str, Any], ...]
    navigation: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Solution":
        required = ("id", "name", "category", "reference_resolution", "steps")
        missing = [key for key in required if key not in data]
        if missing:
            raise SolutionError(f"解法缺少字段: {', '.join(missing)}")

        resolution = data["reference_resolution"]
        if (
            not isinstance(resolution, list)
            or len(resolution) != 2
            or not all(isinstance(value, int) and value > 0 for value in resolution)
        ):
            raise SolutionError("reference_resolution 必须是两个正整数")

        raw_points = data.get("points", {})
        if not isinstance(raw_points, dict):
            raise SolutionError("points 必须是对象")
        points: dict[str, tuple[int, int]] = {}
        for name, point in raw_points.items():
            if (
                not isinstance(point, list)
                or len(point) != 2
                or not all(isinstance(value, int) for value in point)
            ):
                raise SolutionError(f"坐标点 {name!r} 必须是两个整数")
            points[name] = (point[0], point[1])

        raw_steps = data["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise SolutionError("steps 必须是非空数组")
        if not all(isinstance(step, dict) for step in raw_steps):
            raise SolutionError("steps 中的每一步都必须是对象")
        for index, step in enumerate(raw_steps, start=1):
            action = step.get("action")
            if not isinstance(action, str) or not action:
                raise SolutionError(f"第 {index} 步 action 必须是非空字符串")
            if action == "mulligan":
                raise SolutionError(
                    f"第 {index} 步动作 mulligan 尚未实现，不能作为有效解法加载"
                )
            if action not in SUPPORTED_ACTIONS:
                raise SolutionError(f"第 {index} 步包含未知动作: {action!r}")

        category = data["category"]
        if category not in {"tutorial", "puzzle"}:
            raise SolutionError("category 只能是 tutorial 或 puzzle")

        navigation = data.get("navigation")
        if navigation is not None:
            if category != "puzzle" or not isinstance(navigation, dict):
                raise SolutionError("navigation 只能用于 puzzle，且必须是对象")
            for field in ("display_name", "name_pattern"):
                if not isinstance(navigation.get(field), str) or not navigation[field]:
                    raise SolutionError(f"navigation.{field} 必须是非空字符串")
            search_swipes = navigation.get("search_swipes", 20)
            if not isinstance(search_swipes, int) or not 1 <= search_swipes <= 50:
                raise SolutionError("navigation.search_swipes 必须在 1 到 50 之间")
            entry_wait_ms = navigation.get("entry_wait_ms", 3500)
            if (
                not isinstance(entry_wait_ms, int)
                or not 0 <= entry_wait_ms <= 15_000
            ):
                raise SolutionError("navigation.entry_wait_ms 必须在 0 到 15000 之间")
            categories = navigation.get("categories", [])
            if not isinstance(categories, list):
                raise SolutionError("navigation.categories 必须是数组")
            for category_item in categories:
                if not isinstance(category_item, dict):
                    raise SolutionError("navigation.categories 中的类别必须是对象")
                for field in ("display_name", "pattern"):
                    if (
                        not isinstance(category_item.get(field), str)
                        or not category_item[field]
                    ):
                        raise SolutionError(
                            f"navigation.categories[].{field} 必须是非空字符串"
                        )
                if category_item.get("scope") not in {"tab", "list"}:
                    raise SolutionError(
                        "navigation.categories[].scope 只能是 tab 或 list"
                    )
                suffix_pattern = category_item.get("suffix_pattern")
                if suffix_pattern is not None and (
                    category_item["scope"] != "list"
                    or not isinstance(suffix_pattern, str)
                    or not suffix_pattern
                ):
                    raise SolutionError(
                        "navigation.categories[].suffix_pattern "
                        "只能用于 list，且必须是非空字符串"
                    )

        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            category=category,
            reference_resolution=(resolution[0], resolution[1]),
            points=points,
            steps=tuple(raw_steps),
            navigation=dict(navigation) if navigation is not None else None,
        )
