"""Select published-release boundaries for git-cliff, ignoring failed build tags."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.request import Request, urlopen


VERSION_TAG = re.compile(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
STABLE_TAG = re.compile(r"v\d+\.\d+\.\d+")


def fetch_releases(repository: str) -> list[dict[str, Any]]:
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repository) is None:
        raise ValueError("Expected repository in owner/name form")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "MaaSVWB-release-notes"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        request = Request(
            f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}",
            headers=headers,
        )
        # API errors must fail the job rather than silently choosing all history.
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("Expected a GitHub release list")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], text=True, encoding="utf-8").strip()


def select_base(releases: list[dict[str, Any]], tag: str, prerelease: bool,
                target: str = "HEAD") -> str | None:
    """Find the closest published ancestor; stable releases exclude prereleases."""
    candidates: dict[str, str] = {}
    # For two published tags on the same commit, prefer the later publication.
    for release in sorted(releases, key=lambda item: item.get("published_at") or "", reverse=True):
        previous = release["tag_name"]
        if previous == tag or release.get("draft") or not release.get("published_at"):
            continue
        if VERSION_TAG.fullmatch(previous) is None:
            continue
        if not prerelease and (release.get("prerelease") or STABLE_TAG.fullmatch(previous) is None):
            continue
        # Full tag history is required. Missing refs must not silently omit notes.
        commit = git("rev-parse", "--verify", f"refs/tags/{previous}^{{commit}}")
        candidates.setdefault(commit, previous)
    for commit in git("rev-list", "--topo-order", target).splitlines():
        if commit in candidates:
            return candidates[commit]
    return None


def prepare(releases: list[dict[str, Any]], tag: str, prerelease: bool,
            target: str = "HEAD") -> dict[str, str]:
    if VERSION_TAG.fullmatch(tag) is None:
        raise ValueError(f"Invalid version tag: {tag}")
    # Resolve the endpoint so a moving branch cannot change the selected history.
    target_commit = git("rev-parse", "--verify", f"{target}^{{commit}}")
    base = select_base(releases, tag, prerelease, target_commit)
    return {
        "base": base or "",
        "range": f"{base}..{target_commit}" if base else target_commit,
        # Only the current version divides history into a changelog section.
        "tag_pattern": f"^{re.escape(tag)}$",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "allenx555/MaaSVWB"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--prerelease", choices=("true", "false"), required=True)
    args = parser.parse_args()
    result = prepare(fetch_releases(args.repository), args.tag, args.prerelease == "true")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            for key, value in result.items():
                stream.write(f"{key}={value}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
