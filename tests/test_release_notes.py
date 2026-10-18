from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from release_notes import fetch_releases, prepare  # noqa: E402


def published(tag: str, **options):
    return {"tag_name": tag, "draft": False, "prerelease": False,
            "published_at": "2026-10-18T09:00:00Z", **options}


class ReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.original)
        self.git("init", "-q")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release@example.test")
        self.commit("v1.0.0")
        self.commit("v1.1.0")  # tag with a failed build, no Release
        self.commit("v1.1.1-rc.1")
        self.commit("v1.1.1")

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], text=True, encoding="utf-8").strip()

    def commit(self, tag):
        self.git("commit", "--allow-empty", "-qm", f"feat: {tag}")
        self.git("tag", tag)

    def test_failed_tags_and_prereleases_are_folded_into_stable_release(self):
        result = prepare([published("v1.0.0"), published("v1.1.1-rc.1", prerelease=True),
                          published("v1.1.1")], "v1.1.1", False)
        self.assertEqual(result["base"], "v1.0.0")
        self.assertEqual(len(self.git("rev-list", result["range"]).splitlines()), 3)
        self.assertEqual(result["tag_pattern"], r"^v1\.1\.1$")

    def test_prerelease_can_use_previous_published_prerelease(self):
        result = prepare([published("v1.0.0"), published("v1.1.1-rc.1", prerelease=True)],
                         "v1.1.1-rc.2", True)
        self.assertEqual(result["base"], "v1.1.1-rc.1")

    def test_drafts_and_unrelated_branch_releases_are_ignored(self):
        self.git("checkout", "-qb", "unrelated", "v1.0.0")
        self.commit("v9.0.0")
        self.git("checkout", "-q", "v1.1.1")
        result = prepare([published("v1.0.0"), published("v1.1.0", draft=True),
                          published("v9.0.0")], "v1.1.1", False)
        self.assertEqual(result["base"], "v1.0.0")

    def test_first_release_includes_all_history(self):
        result = prepare([], "v1.1.1", False)
        self.assertEqual(result["base"], "")
        self.assertEqual(len(self.git("rev-list", result["range"]).splitlines()), 4)

    def test_closest_ancestor_wins_over_publication_order(self):
        result = prepare([published("v1.0.0", published_at="2027-01-01T00:00:00Z"),
                          published("v1.1.0")], "v1.1.1", False)
        self.assertEqual(result["base"], "v1.1.0")


class ReleaseApiTests(unittest.TestCase):
    def test_all_pages_are_fetched(self):
        pages = [[published("v1.0.0")] * 100, [published("v1.1.0")]]
        responses = []
        for page in pages:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(page)
            responses.append(response)
        with patch("release_notes.urlopen", side_effect=responses) as request:
            self.assertEqual(len(fetch_releases("owner/repo")), 101)
        self.assertIn("page=2", request.call_args_list[1].args[0].full_url)

    def test_api_failure_is_not_treated_as_first_release(self):
        with patch("release_notes.urlopen", side_effect=OSError("API unavailable")):
            with self.assertRaisesRegex(OSError, "API unavailable"):
                fetch_releases("owner/repo")


if __name__ == "__main__":
    unittest.main()
