import tempfile
import time
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import only the snooze-file helpers without triggering Gtk: stub gi first.
import types  # noqa: E402

gi_stub = types.ModuleType("gi")
gi_stub.require_version = lambda *a, **k: None
sys.modules.setdefault("gi", gi_stub)
repo_stub = types.ModuleType("gi.repository")
sys.modules.setdefault("gi.repository", repo_stub)

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "xdg_pause_snooze",
    os.path.join(
        os.path.dirname(__file__), "..", "xdg_pause.py"
    ),
)


class TestSnoozeFile(unittest.TestCase):
    def test_helpers_exist_and_parse(self):
        import ast

        with open(
            os.path.join(os.path.dirname(__file__), "..", "xdg_pause.py"),
            encoding="utf-8",
        ) as f:
            src = f.read()
        tree = ast.parse(src)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for fn in (
            "snoozed_remaining",
            "_read_snooze_file",
            "_write_snooze_file",
            "_has_systemd_user",
        ):
            self.assertIn(fn, names)

    def test_write_truncates_to_int_epoch(self):
        import ast

        with open(
            os.path.join(os.path.dirname(__file__), "..", "xdg_pause.py"),
            encoding="utf-8",
        ) as f:
            src = f.read()
        # _write_snooze_file stores int(epoch) — float text would break readers
        # that do int(text) on load.
        self.assertIn("str(int(until_epoch))", src)

    def test_main_honors_snooze_guard(self):
        with open(
            os.path.join(os.path.dirname(__file__), "..", "xdg_pause.py"),
            encoding="utf-8",
        ) as f:
            src = f.read()
        self.assertIn("snoozed_remaining()", src)
        # Guard must sit between the already-active check and Gtk.init_check
        active = src.index("_is_overlay_already_active()")
        guard = src.index("SKIP snoozed")
        gtk_init = src.index("Gtk.init_check()")
        self.assertLess(active, guard)
        self.assertLess(guard, gtk_init)


if __name__ == "__main__":
    unittest.main()
