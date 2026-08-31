from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from runtime.backend import MaaBackend  # noqa: E402


class RuntimeBackendTests(unittest.TestCase):
    def test_energy_text_with_visible_separator(self) -> None:
        self.assertEqual(MaaBackend._parse_energy_text("2/3"), (2, 3))
        self.assertEqual(MaaBackend._parse_energy_text("10|10"), (10, 10))

    def test_energy_text_with_slash_recognized_as_one(self) -> None:
        self.assertEqual(MaaBackend._parse_energy_text("313"), (3, 3))
        self.assertEqual(MaaBackend._parse_energy_text("213"), (2, 3))
        self.assertEqual(MaaBackend._parse_energy_text("10110"), (10, 10))

    def test_energy_text_without_separator(self) -> None:
        self.assertEqual(MaaBackend._parse_energy_text("33"), (3, 3))
        self.assertEqual(MaaBackend._parse_energy_text("1010"), (10, 10))
        self.assertIsNone(MaaBackend._parse_energy_text("energy"))


if __name__ == "__main__":
    unittest.main()
