"""Device-free runtime check shared by the CLI Runner and Agent executable."""
from __future__ import annotations

import json
from pathlib import Path

from maa.resource import Resource

from actions.execute_dungeon import ExecuteDungeon
from actions.execute_solution import ExecuteSolution
from actions.execute_tracker import ExecuteDeckTracker
from battle_engine.repository import BattleProfileRepository, CardCatalogRepository
from solution_engine.layout import BoardLayout
from solution_engine.repository import SolutionRepository
from .runner import find_resource_root
from .events import emit_event


def check_runtime(project_root: Path, role: str) -> dict:
    root = project_root.resolve()
    resource_root = find_resource_root(root)
    for name in ("det.onnx", "rec.onnx", "keys.txt"):
        path = resource_root / "model" / "ocr" / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"OCR model is missing or empty: {path}")
    BoardLayout.load(resource_root / "layouts" / "default.json")
    catalog = CardCatalogRepository.for_project(root).load()
    profiles = BattleProfileRepository.for_project(root, catalog)
    profile_files = sorted(profiles.root.glob("*.json"))
    if not profile_files:
        raise RuntimeError("No battle profiles were packaged")
    for path in profile_files:
        profiles.load(path.stem)
    solutions = SolutionRepository.for_project(root)
    solution_files = sorted(solutions.root.glob("*.json"))
    if not solution_files:
        raise RuntimeError("No solutions were packaged")
    for path in solution_files:
        solutions.load(path.stem)
    interface_path = root / "interface.json"
    if not interface_path.is_file():
        interface_path = root / "assets" / "interface.json"
    interface = json.loads(interface_path.read_text(encoding="utf-8"))
    if not interface.get("task"):
        raise RuntimeError("Project Interface contains no tasks")
    catalog_root = root / "catalog" if (root / "catalog").is_dir() else root / "assets" / "catalog"
    for category in ("puzzle", "tutorial"):
        data = json.loads((catalog_root / f"{category}_catalog.json").read_text(encoding="utf-8"))
        if not data.get("items"):
            raise RuntimeError(f"Empty catalog: {category}")

    actions = {"ExecuteSolution": ExecuteSolution(), "ExecuteDungeon": ExecuteDungeon(),
               "ExecuteDeckTracker": ExecuteDeckTracker()}
    if role == "runner":
        resource = Resource()
        if not resource.post_bundle(str(resource_root)).wait().succeeded:
            raise RuntimeError("MaaFramework could not load the resource bundle")
        for name, action in actions.items():
            if not resource.register_custom_action(name, action):
                raise RuntimeError(f"Could not register resource action: {name}")
    elif role == "agent":
        # Importing AgentServer switches maa.Library into Agent mode. It must
        # not be imported by the Runner or used to create a local Resource.
        from maa.library import Library
        from maa.agent.agent_server import AgentServer
        # Loading the native server validates packaging without creating its
        # ZeroMQ singleton or opening a socket. Registration belongs to startup.
        if Library.agent_server() is None:
            raise RuntimeError("Could not load MaaAgentServer")
    else:
        raise ValueError(f"Unknown runtime role: {role}")
    result = {"state": "succeeded", "role": role, "project_root": str(root),
              "profiles": len(profile_files), "solutions": len(solution_files),
              "cards": len(catalog.cards), "actions": sorted(actions),
              "native_check": "resource_registration" if role == "runner" else "agent_library_load"}
    emit_event("self_check", "Runtime self-check passed (no device operations)", **result)
    return result
