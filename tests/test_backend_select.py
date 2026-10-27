import unittest
import ast
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_backend_fns():
    """Exec the pure (pre-gi) section of xdg_pause.py in isolation.

    xdg_pause imports Gtk at module level, which is unavailable headless, so
    extract just the backend-selection preamble (everything before `import gi`)
    and exec it. Keeps the test honest: it runs the real selection code.
    """
    with open(os.path.join(REPO, "xdg_pause.py"), encoding="utf-8") as f:
        src = f.read()
    pre_gi = src.split("import gi")[0]
    tree = ast.parse(pre_gi)
    ns = {}
    exec(compile(tree, "xdg_pause_premable", "exec"), ns)  # noqa: S102 - test only
    return ns


class TestBackendSelect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_backend_fns()

    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("XDG_PAUSE_BACKEND", None)
        os.environ.pop("SOMMELIER_VERSION", None)
        os.environ.pop("XDG_CURRENT_DESKTOP", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_explicit_chromeos_wins(self):
        os.environ["XDG_PAUSE_BACKEND"] = "chromeos"
        self.assertEqual(self.ns["_select_backend"](), "chromeos")

    def test_explicit_layer_shell_wins(self):
        os.environ["XDG_PAUSE_BACKEND"] = "layer-shell"
        os.environ["XDG_CURRENT_DESKTOP"] = "Hyprland"
        self.assertEqual(self.ns["_select_backend"](), "layer-shell")

    def test_explicit_x11_not_overridden_by_crostini(self):
        os.environ["XDG_PAUSE_BACKEND"] = "x11"
        os.environ["SOMMELIER_VERSION"] = "0.1"
        self.assertEqual(self.ns["_select_backend"](), "x11")

    def test_sommelier_env_detects_chromeos(self):
        os.environ["SOMMELIER_VERSION"] = "0.1"
        self.assertEqual(self.ns["_select_backend"](), "chromeos")
        self.assertTrue(self.ns["_detect_crostini"]())

    def test_hyprland_detects_layer_shell(self):
        os.environ["XDG_CURRENT_DESKTOP"] = "Hyprland"
        self.assertEqual(self.ns["_select_backend"](), "layer-shell")

    def test_plain_linux_defaults_x11(self):
        # This dev host may itself be Crostini; isolate by stubbing detection.
        orig = self.ns["_detect_crostini"]
        self.ns["_detect_crostini"] = lambda: False
        try:
            self.assertEqual(self.ns["_select_backend"](), "x11")
            self.assertFalse(self.ns["_detect_crostini"]())
        finally:
            self.ns["_detect_crostini"] = orig

    def test_backend_constants_consistent(self):
        backend = self.ns["_select_backend"]()
        self.assertEqual(self.ns["_USE_LAYER_SHELL"], backend == "layer-shell")
        self.assertEqual(self.ns["_USE_CHROMEOS"], backend == "chromeos")


if __name__ == "__main__":
    unittest.main()
