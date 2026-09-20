#!/usr/bin/env python3
"""
xdg-pause — Minimalist, native multi-monitor break overlay for Linux (Wayland / X11).

Features:
- Native GTK3 fullscreen surfaces spanning all connected displays without DPMS signal drops.
- Eliminates the external monitor disconnect trap (preserves multi-monitor window layouts).
- Pitch-black minimal UI with a depleting progress bar and exact countdown.
- Full keyboard input isolation: consumes keystrokes to prevent background typing.
- Structured file and systemd journal logging (~/.local/state/xdg-pause/xdg-pause.log).
- Decoupled LocaleAdapter: configurable translation templates without hardcoded language branches.
- Fully configurable via ~/.config/xdg-pause/config.json.
"""

import sys
import os
import json
import time
import argparse
import subprocess
import logging
import pathlib
import atexit
import signal

# Strip legacy Ubuntu Unity appmenu-gtk-module from GTK_MODULES before GTK loads.
# appmenu-gtk-module attaches to window realization and asserts on Wayland surfaces without menus.
if "GTK_MODULES" in os.environ:
    os.environ["GTK_MODULES"] = ":".join(
        [m for m in os.environ["GTK_MODULES"].split(":") if "appmenu" not in m]
    )

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gtk, Gdk, Gio, GLib

__version__ = "0.2.0"

# Paths
CONFIG_DIR = os.path.expanduser("~/.config/xdg-pause")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_DIR = pathlib.Path.home() / ".local" / "state" / "xdg-pause"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = STATE_DIR / "xdg-pause.log"

# Logger Configuration
logger = logging.getLogger("xdg-pause")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    # File handler
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)

    # Console / systemd journal handler
    _ch = logging.StreamHandler(sys.stderr)
    _ch.setLevel(logging.INFO)
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)

DEFAULT_CONFIG = {
    "language": "hi",
    "sounds": {
        "enabled": False,
        "mini_start": "silence",
        "mini_end": "silence",
        "long_start": "silence",
        "long_end": "silence"
    },
    "durations": {
        "mini_seconds": 30,
        "long_seconds": 600,
        "strict_interval_seconds": 30
    },
    "ui": {
        "bar_width": 560,
        "bar_height": 6,
        "bar_color": "#cecece",
        "bar_border_color": "#707070",
        "bg_color": "#000000",
        "text_color": "#ffffff"
    },
    "locales": {
        "hi": {
            "seconds_remaining": "{s} सेकंड शेष है",
            "minutes_remaining": "{m} मिनट शेष है",
            "minutes_seconds_remaining": "{m} मिनट {s} सेकंड शेष है",
            "resume_button": "वापस जाएं (Esc)"
        },
        "en": {
            "seconds_remaining": "{s} second{s_plural} remaining",
            "minutes_remaining": "{m} minute{m_plural} remaining",
            "minutes_seconds_remaining": "{m}m {s}s remaining",
            "resume_button": "Resume Work (Esc)"
        }
    }
}


def load_config():
    """Load configuration from ~/.config/xdg-pause/config.json with default fallback."""
    if not os.path.exists(CONFIG_PATH):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            logger.info(f"Created default configuration at {CONFIG_PATH}")
            return DEFAULT_CONFIG
        except Exception as e:
            logger.warning(f"Failed to create default configuration: {e}")
            return DEFAULT_CONFIG

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            for k, v in user_cfg.items():
                if isinstance(v, dict) and k in merged:
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
            return merged
    except Exception as e:
        logger.error(f"Failed to read {CONFIG_PATH}, using defaults: {e}")
        return DEFAULT_CONFIG


class LocaleAdapter:
    """Decoupled locale translation adapter driven entirely by configuration templates."""

    FALLBACK = {
        "seconds_remaining": "{s} seconds remaining",
        "minutes_remaining": "{m} minutes remaining",
        "minutes_seconds_remaining": "{m}m {s}s remaining",
        "resume_button": "Resume Work (Esc)"
    }

    def __init__(self, language="hi", locales_dict=None):
        self.language = language
        locales = locales_dict or {}
        self.strings = locales.get(language, locales.get("en", self.FALLBACK))

    def format_remaining(self, total_seconds):
        s = int(round(total_seconds))
        mins = s // 60
        rem_s = s % 60
        params = {
            "m": mins,
            "s": rem_s,
            "m_plural": "s" if mins > 1 else "",
            "s_plural": "s" if rem_s != 1 else ""
        }
        if mins > 0 and rem_s > 0:
            tmpl = self.strings.get("minutes_seconds_remaining", "{m}m {s}s remaining")
        elif mins > 0:
            tmpl = self.strings.get("minutes_remaining", "{m} minutes remaining")
        else:
            tmpl = self.strings.get("seconds_remaining", "{s} seconds remaining")
        return tmpl.format(**params)

    def get_resume_button_label(self):
        return self.strings.get("resume_button", "Resume Work (Esc)")


SUSPEND_KEYBINDINGS = [
    "switch-applications",
    "switch-applications-backward",
    "switch-windows",
    "switch-windows-backward",
    "switch-group",
    "switch-group-backward",
    "switch-panels",
    "switch-panels-backward",
]


class XdgPauseOverlay:
    """Multi-monitor GTK3 break overlay with complete keyboard input swallowing."""

    def __init__(self, break_type="mini", override_duration=None, override_strict=None):
        self.cfg = load_config()
        self.break_type = break_type

        dur_cfg = self.cfg.get("durations", {})
        if override_duration is not None:
            self.total_duration = override_duration
        else:
            self.total_duration = dur_cfg.get(f"{break_type}_seconds", 30)

        if override_strict is not None:
            self.strict_interval = override_strict
        else:
            self.strict_interval = dur_cfg.get("strict_interval_seconds", 30)

        self.ui_cfg = self.cfg.get("ui", {})
        self.sounds_cfg = self.cfg.get("sounds", {})
        lang = self.cfg.get("language", "hi")
        self.locale = LocaleAdapter(language=lang, locales_dict=self.cfg.get("locales", {}))

        self.windows = []
        self.labels = []
        self.progress_bars = []
        self.resume_buttons = []

        logger.info(
            f"Initializing break overlay: mode={self.break_type}, "
            f"duration={self.total_duration}s, strict_interval={self.strict_interval}s, lang={lang}"
        )

        self.apply_css()
        self.create_windows()

        self.gnome_bus = None
        self.gnome_sub_id = None
        self.saved_keybindings = {}
        self.wm_settings = None

        self.setup_gnome_overview_suppressor()
        self.suspend_gnome_switchers()

        atexit.register(self.restore_gnome_switchers)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self.start_time = time.time()
        start_key = f"{self.break_type}_start"
        self.play_sound(self.sounds_cfg.get(start_key, "silence"))

        self.timer_source_id = GLib.timeout_add(100, self.update_timer)

    def play_sound(self, sound_name):
        if not self.sounds_cfg.get("enabled", False) or sound_name == "silence":
            return
        if sound_name == "bell":
            print("\a", end="", flush=True)

    def apply_css(self):
        bg = self.ui_cfg.get("bg_color", "#000000")
        bar_col = self.ui_cfg.get("bar_color", "#cecece")
        bar_border = self.ui_cfg.get("bar_border_color", "#707070")
        text_col = self.ui_cfg.get("text_color", "#ffffff")
        bar_w = self.ui_cfg.get("bar_width", 560)
        bar_h = self.ui_cfg.get("bar_height", 6)

        css = f"""
        window.break-window {{
            background-color: {bg};
        }}
        progressbar trough {{
            min-height: {bar_h}px;
            min-width: {bar_w}px;
            background-color: {bg};
            border-radius: 3px;
            border: 1px solid {bar_border};
            padding: 0;
            margin: 0;
        }}
        progressbar progress {{
            background-color: {bar_col};
            border-radius: 3px;
            min-height: {bar_h}px;
            padding: 0;
            margin: 0;
        }}
        label.countdown-text {{
            color: {text_col};
            font-family: 'Noto Sans Devanagari Light', 'Noto Sans Devanagari', 'Noto Sans Light', 'Noto Sans', sans-serif;
            font-size: 16px;
            font-weight: 300;
            margin-top: 20px;
        }}
        button.resume-btn {{
            background: transparent;
            color: #888888;
            font-family: 'Noto Sans Devanagari', 'Noto Sans', sans-serif;
            font-size: 14px;
            padding: 6px 16px;
            border-radius: 4px;
            border: 1px solid #333333;
            margin-top: 16px;
        }}
        button.resume-btn:hover {{
            color: #ffffff;
            border-color: #666666;
            background-color: #111111;
        }}
        """.encode("utf-8")

        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def create_windows(self):
        display = Gdk.Display.get_default()
        screen = display.get_default_screen()
        n_monitors = display.get_n_monitors()
        bar_w = self.ui_cfg.get("bar_width", 560)
        bar_h = self.ui_cfg.get("bar_height", 6)

        logger.info(f"Detected {n_monitors} monitors on display")

        for mon_idx in range(n_monitors):
            mon = display.get_monitor(mon_idx)
            geom = mon.get_geometry()
            desc = mon.get_model() or f"Monitor-{mon_idx}"

            win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            win.get_style_context().add_class("break-window")
            win.set_title("xdg-pause")
            win.set_keep_above(True)
            win.fullscreen_on_monitor(screen, mon_idx)

            win.connect("delete-event", lambda w, e: True)
            win.connect("key-press-event", self.on_key_press)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.set_valign(Gtk.Align.CENTER)
            box.set_halign(Gtk.Align.CENTER)

            pbar = Gtk.ProgressBar()
            pbar.set_fraction(1.0)
            pbar.set_size_request(bar_w, bar_h)

            initial_text = self.locale.format_remaining(self.total_duration)
            timer_label = Gtk.Label(label=initial_text)
            timer_label.get_style_context().add_class("countdown-text")

            box.pack_start(pbar, False, False, 0)
            box.pack_start(timer_label, False, False, 0)

            btn = None
            if self.break_type == "long":
                btn = Gtk.Button(label=self.locale.get_resume_button_label())
                btn.get_style_context().add_class("resume-btn")
                btn.set_sensitive(False)
                btn.set_no_show_all(True)
                btn.connect("clicked", lambda b: self.finish_break(early=True))
                box.pack_start(btn, False, False, 0)
                self.resume_buttons.append(btn)

            win.add(box)
            win.show_all()
            win.present()

            logger.info(f"Monitor {mon_idx} ({desc} {geom.width}x{geom.height}): Window fullscreened and mapped")

            self.windows.append(win)
            self.labels.append(timer_label)
            self.progress_bars.append(pbar)

    def on_key_press(self, win, event):
        elapsed = time.time() - self.start_time
        logger.debug(f"Key press intercepted: keyval={event.keyval}, elapsed={elapsed:.1f}s")
        if self.break_type == "long" and elapsed >= self.strict_interval:
            if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_space):
                logger.info("Early break exit triggered by user via keypress")
                self.finish_break(early=True)
                return True
        return True

    def update_timer(self):
        elapsed = time.time() - self.start_time
        remaining = max(0.0, self.total_duration - elapsed)
        fraction = max(0.0, remaining / self.total_duration)

        text = self.locale.format_remaining(remaining)

        for lbl in self.labels:
            lbl.set_text(text)

        for pb in self.progress_bars:
            pb.set_fraction(fraction)

        if self.break_type == "long" and elapsed >= self.strict_interval:
            for btn in self.resume_buttons:
                if not btn.is_visible():
                    btn.show()
                btn.set_sensitive(True)

        if self.gnome_bus:
            self.check_and_dismiss_gnome_overview()

        # Overview suppression handled via D-Bus signal and poll above

        if remaining <= 0:
            logger.info(f"Break completed after {elapsed:.1f}s")
            self.finish_break(early=False)
            return False

        return True

    def setup_gnome_overview_suppressor(self):
        try:
            self.gnome_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            if self.gnome_bus:
                self.gnome_sub_id = self.gnome_bus.signal_subscribe(
                    None,
                    "org.freedesktop.DBus.Properties",
                    "PropertiesChanged",
                    "/org/gnome/Shell",
                    "org.gnome.Shell",
                    Gio.DBusSignalFlags.NONE,
                    self.on_gnome_shell_prop_changed,
                    None
                )
                logger.info("GNOME Shell overview suppressor registered")
        except Exception as e:
            logger.debug(f"GNOME Shell overview suppressor not available: {e}")

    def on_gnome_shell_prop_changed(self, connection, sender, path, iface, signal, params, user_data):
        try:
            props = params.get_child_value(1)
            if "OverviewActive" in props.keys():
                val = props["OverviewActive"]
                is_open = bool(val.get_boolean() if hasattr(val, "get_boolean") else val)
                if is_open:
                    logger.info("GNOME Shell Overview opened during break; dismissing...")
                    self.dismiss_gnome_overview()
        except Exception as e:
            logger.debug(f"Error handling GNOME Shell property change: {e}")

    def check_and_dismiss_gnome_overview(self):
        if not self.gnome_bus:
            return
        try:
            res = self.gnome_bus.call_sync(
                "org.gnome.Shell",
                "/org/gnome/Shell",
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", ("org.gnome.Shell", "OverviewActive")),
                GLib.VariantType("(v)"),
                Gio.DBusCallFlags.NONE,
                200,
                None
            )
            is_open = res.get_child_value(0).get_variant().get_boolean()
            if is_open:
                now = time.time()
                # Debounce logging to once every 0.5s during animation
                if not hasattr(self, "_last_overview_log") or now - self._last_overview_log > 0.5:
                    logger.info("GNOME Shell Overview detected active; dismissing...")
                    self._last_overview_log = now
                self.dismiss_gnome_overview()
        except Exception as e:
            pass

    def dismiss_gnome_overview(self):
        if not self.gnome_bus:
            return
        try:
            self.gnome_bus.call_sync(
                "org.gnome.Shell",
                "/org/gnome/Shell",
                "org.freedesktop.DBus.Properties",
                "Set",
                GLib.Variant("(ssv)", ("org.gnome.Shell", "OverviewActive", GLib.Variant("b", False))),
                None,
                Gio.DBusCallFlags.NONE,
                200,
                None
            )
            for win in self.windows:
                win.present()
        except Exception as e:
            logger.debug(f"Error dismissing GNOME overview: {e}")

    def suspend_gnome_switchers(self):
        try:
            self.wm_settings = Gio.Settings.new("org.gnome.desktop.wm.keybindings")
            for key in SUSPEND_KEYBINDINGS:
                self.saved_keybindings[key] = self.wm_settings.get_strv(key)
                self.wm_settings.set_strv(key, [])
            logger.info("GNOME Shell switcher keybindings suspended for break")
        except Exception as e:
            logger.debug(f"Could not suspend GNOME switcher keybindings: {e}")

    def restore_gnome_switchers(self):
        if hasattr(self, "wm_settings") and self.wm_settings and self.saved_keybindings:
            for key, val in self.saved_keybindings.items():
                try:
                    self.wm_settings.set_strv(key, val)
                except Exception:
                    pass
            self.saved_keybindings = {}
            logger.info("GNOME Shell switcher keybindings restored")

    def _handle_signal(self, signum, frame):
        logger.info(f"Received termination signal ({signum}), restoring keybindings and exiting")
        self.restore_gnome_switchers()
        sys.exit(0)

    def finish_break(self, early=False):
        if hasattr(self, "timer_source_id") and self.timer_source_id:
            GLib.source_remove(self.timer_source_id)
            self.timer_source_id = None

        if self.gnome_bus and self.gnome_sub_id:
            try:
                self.gnome_bus.signal_unsubscribe(self.gnome_sub_id)
            except Exception:
                pass
            self.gnome_sub_id = None

        self.restore_gnome_switchers()

        end_key = f"{self.break_type}_end"
        self.play_sound(self.sounds_cfg.get(end_key, "silence"))

        status = "early user resume" if early else "completed countdown"
        logger.info(f"Destroying overlay windows ({status})")

        for win in self.windows:
            win.destroy()
        if Gtk.main_level() > 0:
            Gtk.main_quit()


def main():
    parser = argparse.ArgumentParser(
        description="xdg-pause: Minimalist native multi-monitor break overlay for Linux Wayland/X11",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  xdg-pause              # Mini break using configured duration\n  xdg-pause long         # Long break (600s with 30s strict interval)\n  xdg-pause 45           # Custom 45-second break\n"
    )
    parser.add_argument("mode", nargs="?", default="mini", help="Break mode ('mini', 'long', or integer seconds)")
    parser.add_argument("-v", "--version", action="version", version=f"xdg-pause {__version__}")
    parser.add_argument("-s", "--strict", type=int, default=None, help="Override strict non-cancellable interval in seconds")

    args = parser.parse_args()

    b_type = "mini"
    override_dur = None
    override_strict = args.strict

    mode_lower = args.mode.lower()
    if mode_lower in ("long", "break"):
        b_type = "long"
    elif mode_lower in ("mini", "microbreak"):
        b_type = "mini"
    elif mode_lower.isdigit():
        override_dur = int(mode_lower)
        if override_strict is None:
            override_strict = min(30, override_dur)
    else:
        logger.error(f"Unknown mode: {args.mode}")
        sys.exit(1)

    Gtk.init_check()
    XdgPauseOverlay(break_type=b_type, override_duration=override_dur, override_strict=override_strict)
    Gtk.main()


if __name__ == "__main__":
    main()
