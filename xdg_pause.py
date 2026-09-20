#!/usr/bin/env python3
"""
xdg-pause — Minimalist, native multi-monitor break overlay for Linux (Wayland / X11).

Features:
- Native GTK3 fullscreen surface spanning all connected displays without DPMS signal drops.
- Eliminates the external monitor disconnect trap (windows stay on their original monitors).
- Pitch-black minimal UI with a depleting progress bar and exact countdown.
- Full keyboard input isolation: consumes keystrokes to prevent background typing.
- Decoupled LocaleAdapter: configurable translation templates (Hindi, English, etc.) without hardcoded branches.
- Configurable via ~/.config/xdg-pause/config.json (sounds, durations, styling, locales).
"""

import sys
import os
import json
import time
import argparse
import subprocess
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

__version__ = "0.1.0"

CONFIG_DIR = os.path.expanduser("~/.config/xdg-pause")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

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
    if not os.path.exists(CONFIG_PATH):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            return DEFAULT_CONFIG
        except Exception:
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
    except Exception:
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


class XdgPauseOverlay:
    def __init__(self, break_type="mini", override_duration=None, override_strict=None):
        self.cfg = load_config()
        self.break_type = break_type

        # Durations
        dur_cfg = self.cfg.get("durations", {})
        default_dur = dur_cfg.get("long_seconds", 600) if break_type == "long" else dur_cfg.get("mini_seconds", 30)
        self.total_duration = override_duration if override_duration is not None else default_dur
        self.strict_interval = override_strict if override_strict is not None else dur_cfg.get("strict_interval_seconds", 30)

        # Locale adapter
        lang = self.cfg.get("language", "hi")
        locales_dict = self.cfg.get("locales", {})
        self.locale = LocaleAdapter(language=lang, locales_dict=locales_dict)

        self.ui_cfg = self.cfg.get("ui", DEFAULT_CONFIG["ui"])
        self.sounds_cfg = self.cfg.get("sounds", DEFAULT_CONFIG["sounds"])

        self.start_time = time.time()
        self.windows = []
        self.labels = []
        self.progress_bars = []
        self.resume_buttons = []

        self.apply_css()
        self.create_windows()

        GLib.timeout_add(50, self.update_timer)

        # Start sound
        start_key = f"{break_type}_start"
        self.play_sound(self.sounds_cfg.get(start_key, "silence"))

    def play_sound(self, sound_name):
        if not self.sounds_cfg.get("enabled", False):
            return
        if not sound_name or sound_name.lower() in ("silence", "none", "off"):
            return
        try:
            subprocess.run(["canberra-gtk-play", "-i", sound_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def apply_css(self):
        bg = self.ui_cfg.get("bg_color", "#000000")
        bar_col = self.ui_cfg.get("bar_color", "#cecece")
        border_col = self.ui_cfg.get("bar_border_color", "#707070")
        text_col = self.ui_cfg.get("text_color", "#ffffff")
        bar_h = self.ui_cfg.get("bar_height", 6)

        css = f"""
        window.break-window {{
            background-color: {bg};
        }}
        progressbar trough {{
            background: transparent;
            border: 1px solid {border_col};
            border-radius: 3px;
            min-height: {bar_h}px;
            padding: 0;
            margin: 0;
        }}
        progressbar progress {{
            background-color: {bar_col};
            border-radius: 3px;
            min-height: {bar_h}px;
            border: none;
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

        for mon_idx in range(n_monitors):
            win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            win.get_style_context().add_class("break-window")
            win.set_title("xdg-pause")
            win.set_keep_above(True)
            win.fullscreen_on_monitor(screen, mon_idx)

            win.connect("delete-event", lambda w, e: True)
            win.connect("key-press-event", self.on_key_press)
            win.connect("focus-out-event", self.on_focus_out)

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

            self.windows.append(win)
            self.labels.append(timer_label)
            self.progress_bars.append(pbar)

    def on_focus_out(self, win, event):
        GLib.idle_add(win.present)
        return False

    def on_key_press(self, win, event):
        elapsed = time.time() - self.start_time
        if self.break_type == "long" and elapsed >= self.strict_interval:
            if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_space):
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

        if remaining <= 0:
            self.finish_break(early=False)
            return False

        return True

    def finish_break(self, early=False):
        end_key = f"{self.break_type}_end"
        self.play_sound(self.sounds_cfg.get(end_key, "silence"))

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
        print(f"Unknown mode: {args.mode}. Use 'mini', 'long', or duration in seconds.", file=sys.stderr)
        sys.exit(1)

    Gtk.init_check()
    XdgPauseOverlay(break_type=b_type, override_duration=override_dur, override_strict=override_strict)
    Gtk.main()


if __name__ == "__main__":
    main()
