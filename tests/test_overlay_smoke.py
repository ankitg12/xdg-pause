import unittest
import sys
import os

if "GTK_MODULES" in os.environ:
    os.environ["GTK_MODULES"] = ":".join(
        [m for m in os.environ["GTK_MODULES"].split(":") if "appmenu" not in m]
    )

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import xdg_pause


class TestOverlaySmoke(unittest.TestCase):
    def setUp(self):
        Gtk.init_check()

    def test_multi_monitor_window_instantiation(self):
        display = Gdk.Display.get_default()
        if not display:
            self.skipTest("No GDK display available in headless environment")

        n_monitors = display.get_n_monitors()
        self.assertGreater(n_monitors, 0)

        overlay = xdg_pause.XdgPauseOverlay(
            break_type="mini",
            override_duration=1,
            override_strict=1
        )

        # Confirm one window, label, and progress bar per monitor
        self.assertEqual(len(overlay.windows), n_monitors)
        self.assertEqual(len(overlay.labels), n_monitors)
        self.assertEqual(len(overlay.progress_bars), n_monitors)

        # Confirm all windows are realized and visible
        for win in overlay.windows:
            self.assertTrue(win.is_visible())

        # Test single tick update
        res = overlay.update_timer()
        self.assertIn(res, [True, False])

        # Cleanly tear down
        overlay.finish_break(early=True)
        while Gtk.events_pending():
            Gtk.main_iteration()


if __name__ == "__main__":
    unittest.main()
