from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.tool_paths import resolve_adb_path


class ToolPathTests(unittest.TestCase):
    def test_explicit_existing_path_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "custom-adb"
            explicit.write_text("placeholder", encoding="utf-8")
            with patch("bot.tool_paths.bundled_adb_path") as bundled, \
                 patch("bot.tool_paths.shutil.which", return_value="system-adb"):
                bundled.return_value = Path(tmp) / "bundled-adb"
                self.assertEqual(resolve_adb_path(str(explicit)), str(explicit.resolve()))

    def test_bundled_adb_preferred_over_system_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled_path = Path(tmp) / "adb"
            bundled_path.write_text("placeholder", encoding="utf-8")
            with patch("bot.tool_paths.bundled_adb_path", return_value=bundled_path), \
                 patch("bot.tool_paths.shutil.which", return_value="system-adb"):
                self.assertEqual(resolve_adb_path("adb"), str(bundled_path.resolve()))

    def test_system_path_is_fallback_when_bundle_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "adb"
            with patch("bot.tool_paths.bundled_adb_path", return_value=missing), \
                 patch("bot.tool_paths.shutil.which", return_value="system-adb"):
                self.assertEqual(resolve_adb_path("auto"), "system-adb")

    def test_stale_explicit_path_falls_back_to_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled_path = Path(tmp) / "adb"
            bundled_path.write_text("placeholder", encoding="utf-8")
            with patch("bot.tool_paths.bundled_adb_path", return_value=bundled_path), \
                 patch("bot.tool_paths.shutil.which", return_value=None):
                result = resolve_adb_path(str(Path(tmp) / "old-machine" / "adb.exe"))
                self.assertEqual(result, str(bundled_path.resolve()))


if __name__ == "__main__":
    unittest.main()
