import unittest
import tempfile
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import xdg_pause


class TestConfig(unittest.TestCase):
    def test_default_config_schema(self):
        cfg = xdg_pause.DEFAULT_CONFIG
        self.assertIn("sounds", cfg)
        self.assertIn("durations", cfg)
        self.assertIn("ui", cfg)
        self.assertIn("locales", cfg)
        self.assertEqual(cfg["durations"]["mini_seconds"], 30)
        self.assertEqual(cfg["durations"]["long_seconds"], 600)
        self.assertEqual(cfg["durations"]["strict_interval_seconds"], 30)

    def test_config_merging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cfg_path = os.path.join(tmpdir, "config.json")
            user_data = {
                "language": "en",
                "durations": {
                    "mini_seconds": 15
                },
                "ui": {
                    "bar_height": 10
                }
            }
            with open(tmp_cfg_path, "w", encoding="utf-8") as f:
                json.dump(user_data, f)

            orig_path = xdg_pause.CONFIG_PATH
            orig_dir = xdg_pause.CONFIG_DIR
            try:
                xdg_pause.CONFIG_PATH = tmp_cfg_path
                xdg_pause.CONFIG_DIR = tmpdir
                loaded = xdg_pause.load_config()

                self.assertEqual(loaded["language"], "en")
                self.assertEqual(loaded["durations"]["mini_seconds"], 15)
                # Ensure un-overridden values remain intact
                self.assertEqual(loaded["durations"]["long_seconds"], 600)
                self.assertEqual(loaded["durations"]["strict_interval_seconds"], 30)
                self.assertEqual(loaded["ui"]["bar_height"], 10)
                self.assertEqual(loaded["ui"]["bar_width"], "auto")
            finally:
                xdg_pause.CONFIG_PATH = orig_path
                xdg_pause.CONFIG_DIR = orig_dir

    def test_corrupted_config_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cfg_path = os.path.join(tmpdir, "config.json")
            with open(tmp_cfg_path, "w", encoding="utf-8") as f:
                f.write("{invalid_json: true,")

            orig_path = xdg_pause.CONFIG_PATH
            try:
                xdg_pause.CONFIG_PATH = tmp_cfg_path
                loaded = xdg_pause.load_config()
                self.assertEqual(loaded, xdg_pause.DEFAULT_CONFIG)
            finally:
                xdg_pause.CONFIG_PATH = orig_path


if __name__ == "__main__":
    unittest.main()
