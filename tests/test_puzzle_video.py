from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from puzzle_video import bilibili_url, init_case, parse_pts, select_indices


class PuzzleVideoTests(unittest.TestCase):
    def test_part_is_explicit_and_tracking_query_is_removed(self) -> None:
        url, bvid = bilibili_url("https://www.bilibili.com/video/BV1V64R6UE6d?p=2&tracking=abc", 5)
        self.assertEqual(url, "https://www.bilibili.com/video/BV1V64R6UE6d?p=5")
        self.assertEqual(bvid, "BV1V64R6UE6d")

    def test_rejects_unrelated_host_and_bad_part(self) -> None:
        for url, part in [("https://bilibili.com.evil/video/BVabc", 1),
                          ("file:///video/BVabc", 1),
                          ("https://www.bilibili.com/video/BVabc", 0)]:
            with self.subTest(url=url, part=part), self.assertRaises(ValueError):
                bilibili_url(url, part)

    def test_source_pts_is_not_reconstructed_from_frame_index(self) -> None:
        log = ("[Parsed_showinfo_1] n:   0 pts: 432000 pts_time:43.2 duration: 1\n"
               "[Parsed_showinfo_1] n:   1 pts: 434667 pts_time:43.4667 duration: 1\n"
               "frame=2 time=00:00:01\n")
        self.assertEqual(parse_pts(log), [43.2, 43.4667])

    def test_duplicate_frames_keep_endpoints_and_periodic_context(self) -> None:
        self.assertEqual(select_indices([[10]] * 6, [0, 2, 4, 6, 8, 10], 2, 8), [0, 4, 5])

    def test_slow_changes_compared_with_last_kept_frame(self) -> None:
        self.assertEqual(select_indices([[0], [1], [2], [3]], [0, 1, 2, 3], 2, 8), [0, 2, 3])

    def test_repeated_setup_preserves_authored_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            init_case(case)
            notes = case / "evidence.md"
            notes.write_text("Reviewed evidence", encoding="utf-8")
            init_case(case)
            self.assertEqual(notes.read_text(encoding="utf-8"), "Reviewed evidence")


if __name__ == "__main__":
    unittest.main()
