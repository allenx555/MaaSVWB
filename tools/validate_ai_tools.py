from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = PROJECT_ROOT / "tools" / "ai-tools.lock.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_https_url(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    parsed = urlparse(value)
    require(parsed.scheme == "https" and bool(parsed.netloc), f"{field} must be an HTTPS URL")
    return value


def validate_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts, f"{field} must stay inside the project")
    return value


def main() -> int:
    data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    require(data.get("schema_version") == 1, "unsupported AI tools lock schema")

    skills = data.get("skills")
    require(isinstance(skills, list) and bool(skills), "at least one skill must be pinned")
    skill_names: set[str] = set()
    for index, skill in enumerate(skills):
        prefix = f"skills[{index}]"
        require(isinstance(skill, dict), f"{prefix} must be an object")
        name = skill.get("name")
        require(isinstance(name, str) and bool(name), f"{prefix}.name is required")
        require(name not in skill_names, f"duplicate skill name: {name}")
        skill_names.add(name)
        validate_https_url(skill.get("source"), f"{prefix}.source")
        require(bool(SHA_PATTERN.fullmatch(str(skill.get("commit", "")))), f"{prefix}.commit must be a full SHA")
        validate_relative_path(skill.get("subdirectory"), f"{prefix}.subdirectory")
        install_path = validate_relative_path(skill.get("install_path"), f"{prefix}.install_path")
        require(install_path.startswith(".agents/skills/"), f"{prefix}.install_path must use .agents/skills")
        require(isinstance(skill.get("license_note"), str) and bool(skill["license_note"]), f"{prefix}.license_note is required")

    servers = data.get("mcp_servers")
    require(isinstance(servers, list), "mcp_servers must be a list")
    server_names: set[str] = set()
    for index, server in enumerate(servers):
        prefix = f"mcp_servers[{index}]"
        require(isinstance(server, dict), f"{prefix} must be an object")
        name = server.get("name")
        require(isinstance(name, str) and bool(name), f"{prefix}.name is required")
        require(name not in server_names, f"duplicate MCP server name: {name}")
        server_names.add(name)
        validate_https_url(server.get("source"), f"{prefix}.source")
        require(isinstance(server.get("package"), str) and bool(server["package"]), f"{prefix}.package is required")
        require(bool(VERSION_PATTERN.fullmatch(str(server.get("version", "")))), f"{prefix}.version must be pinned")
        require(bool(SHA_PATTERN.fullmatch(str(server.get("commit", "")))), f"{prefix}.commit must be a full SHA")
        require(isinstance(server.get("license"), str) and bool(server["license"]), f"{prefix}.license is required")
        require(server.get("optional") is True, f"{prefix} must remain optional")

    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    require(".agents/skills/maaframework/" in gitignore, "downloaded skill must be ignored")
    require(".ai-tools/" in gitignore, "isolated AI tool environments must be ignored")

    print(f"OK  {LOCK_FILE.name}: {len(skills)} skill(s), {len(servers)} optional MCP server(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
