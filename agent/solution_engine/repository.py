from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Solution, SolutionError


VALID_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SolutionRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @classmethod
    def for_project(cls, project_root: Path) -> "SolutionRepository":
        """同时兼容源码目录和 tools/install.py 生成的发布目录。"""
        root = project_root.resolve()
        candidates = (
            root / "assets" / "resource" / "solutions",
            root / "resource" / "solutions",
        )
        for candidate in candidates:
            if candidate.is_dir():
                return cls(candidate)
        raise SolutionError("找不到解法目录（assets/resource/solutions 或 resource/solutions）")

    def load(self, solution_id: str) -> Solution:
        if not isinstance(solution_id, str) or not VALID_ID.fullmatch(solution_id):
            raise SolutionError(f"非法解法 ID: {solution_id!r}")

        path = (self.root / f"{solution_id}.json").resolve()
        if path.parent != self.root:
            raise SolutionError("解法路径越界")
        if not path.is_file():
            raise SolutionError(f"找不到解法文件: {path.name}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SolutionError(f"无法读取解法 {solution_id}: {exc}") from exc

        solution = Solution.from_dict(data)
        if solution.id != solution_id:
            raise SolutionError(
                f"文件名对应 ID {solution_id!r}，但文件内 ID 为 {solution.id!r}"
            )
        return solution
