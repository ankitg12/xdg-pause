import unittest
import sys
import os

if "GTK_MODULES" in os.environ:
    os.environ["GTK_MODULES"] = ":".join(
        [m for m in os.environ["GTK_MODULES"].split(":") if "appmenu" not in m]
    )

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import xdg_pause


import tempfile


class TestOverlaySmoke(unittest.TestCase):
    def setUp(self):
        Gtk.init_check()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_xdg_config = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmpdir.name

    def tearDown(self):
        if self._old_xdg_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg_config
        self._tmpdir.cleanup()

    def test_multi_monitor_window_instantiation(self):
        display = Gdk.Display.get_default()
        if not display:
            self.skipTest("No GDK display available in headless environment")

        n_monitors = display.get_n_monitors()
        self.assertGreater(n_monitors, 0)

        overlay = xdg_pause.XdgPauseOverlay(
            break_type="mini", override_duration=1, override_strict=1
        )

        # Confirm one window, label, progress bar, and clock label per monitor
        self.assertEqual(len(overlay.windows), n_monitors)
        self.assertEqual(len(overlay.labels), n_monitors)
        self.assertEqual(len(overlay.progress_bars), n_monitors)
        self.assertEqual(len(overlay.clock_labels), n_monitors)

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

    def test_long_break_reason_prompt(self):
        display = Gdk.Display.get_default()
        if not display:
            self.skipTest("No GDK display available in headless environment")

        overlay = xdg_pause.XdgPauseOverlay(
            break_type="long",
            override_duration=600,
            override_strict=0,
        )
        overlay.request_early_exit()
        self.assertTrue(overlay.prompting_reason)
        self.assertTrue(overlay.reason_boxes[0].get_visible())

        # Too-short reason should mark entry invalid and NOT finish break
        overlay.reason_entries[0].set_text("abc")
        overlay.on_reason_activate(overlay.reason_entries[0])
        self.assertTrue(
            overlay.reason_entries[0].get_style_context().has_class("invalid")
        )

        # Cancel returns to button
        overlay.cancel_early_exit_prompt()
        self.assertFalse(overlay.prompting_reason)
        # Valid reason (>= 5 chars) finishes break with reason logged and runs early_exit hook
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            hook_out = tf.name
        try:
            overlay.hooks_cfg["early_exit"] = f"cat > {hook_out}"
            overlay.request_early_exit()
            overlay.reason_entries[0].set_text("production call")
            overlay.on_reason_activate(overlay.reason_entries[0])
            while Gtk.events_pending():
                Gtk.main_iteration()
            import time as _t

            for _ in range(20):
                if os.path.exists(hook_out) and os.path.getsize(hook_out) > 0:
                    break
                _t.sleep(0.05)
            with open(hook_out, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
                self.assertEqual(data["event"], "early_exit")
                self.assertEqual(data["mode"], "long")
                self.assertEqual(data["reason"], "production call")
        finally:
            if os.path.exists(hook_out):
                os.unlink(hook_out)


if __name__ == "__main__":
    unittest.main()
