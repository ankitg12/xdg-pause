import unittest
import subprocess
import sys
import os

EXECUTABLE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "xdg_pause.py")
)


class TestCLI(unittest.TestCase):
    def test_version_flag(self):
        proc = subprocess.run(
            [sys.executable, EXECUTABLE, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("xdg-pause", proc.stdout)

    def test_help_flag(self):
        env = os.environ.copy()
        env.pop("XAUTHORITY", None)
        proc = subprocess.run(
            [sys.executable, EXECUTABLE, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")
        self.assertIn("Minimalist native multi-monitor break overlay", proc.stdout)
        self.assertIn("xdg-pause snooze", proc.stdout)

    def test_snooze_help_and_invalid(self):
        proc = subprocess.run(
            [sys.executable, EXECUTABLE, "snooze", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: xdg-pause snooze", proc.stdout)

        bad = subprocess.run(
            [sys.executable, EXECUTABLE, "snooze", "invalid_subarg"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(bad.returncode, 2)
        self.assertIn("usage: xdg-pause snooze", bad.stderr)

    def test_invalid_mode(self):
        proc = subprocess.run(
            [sys.executable, EXECUTABLE, "invalid_argument_xyz"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Unknown mode", proc.stderr)


if __name__ == "__main__":
    unittest.main()
