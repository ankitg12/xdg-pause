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
import datetime
import argparse
import subprocess
import logging
import pathlib
import atexit
import signal
import glob

# Strip legacy Ubuntu Unity appmenu-gtk-module from GTK_MODULES before GTK loads.
# appmenu-gtk-module attaches to window realization and asserts on Wayland surfaces without menus.
if "GTK_MODULES" in os.environ:
    os.environ["GTK_MODULES"] = ":".join(
        [m for m in os.environ["GTK_MODULES"].split(":") if "appmenu" not in m]
    )

# Native GTK3 Wayland ignores fullscreen_on_monitor and keep_above under Mutter, so the
# overlay lands on the wrong screen and can be covered. Xwayland honours both; no-op on Xorg.
os.environ.setdefault("GDK_BACKEND", "x11")


def _ensure_xauthority():
    """Discover Mutter Xwayland auth cookie when invoked from shells missing XAUTHORITY."""
    if os.environ.get("XAUTHORITY"):
        return
    try:
        env_out = subprocess.check_output(
            ["systemctl", "--user", "show-environment"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in env_out.splitlines():
            if line.startswith("XAUTHORITY="):
                candidate = line.split("=", 1)[1].strip()
                if os.path.exists(candidate):
                    os.environ["XAUTHORITY"] = candidate
                    return
    except Exception:
        pass
    rt_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    auths = sorted(
        glob.glob(os.path.join(rt_dir, ".mutter-Xwaylandauth.*")),
        key=os.path.getmtime,
    )
    if auths:
        os.environ["XAUTHORITY"] = auths[-1]


_ensure_xauthority()

ACTIVE_MARKER = (
    pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "xdg-pause.active"
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
    _fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )

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
        "long_end": "silence",
    },
    "durations": {
        "mini_seconds": 30,
        "long_seconds": 600,
        "strict_interval_seconds": 30,
        "require_early_exit_reason": True,
        "min_reason_chars": 5,
    },
    "hooks": {
        "break_start": None,
        "break_complete": None,
        "early_exit": None,
        "snooze_start": None,
        "snooze_end": None,
    },
    "ui": {
        "bar_width": "auto",
        "bar_height": 6,
        "bar_color": "#cecece",
        "bar_border_color": "#707070",
        "bg_color": "#000000",
        "text_color": "#ffffff",
        "clock_color": "#ffffff",
        "clock_font_size": 28,
        "clock_format": "%H:%M  •  %a, %d %b",
        "clock_position": "bottom-right",
    },
    "locales": {
        "hi": {
            "seconds_remaining": "{s} सेकंड शेष है",
            "minutes_remaining": "{m} मिनट शेष है",
            "minutes_seconds_remaining": "{m} मिनट {s} सेकंड शेष है",
            "resume_button": "वापस जाएं (Esc)",
            "early_exit_prompt": "समय से पहले ब्रेक छोड़ने का कारण लिखें (Enter दबाएं):",
            "early_exit_placeholder": "कम से कम {min_chars} अक्षर...",
        },
        "en": {
            "seconds_remaining": "{s} second{s_plural} remaining",
            "minutes_remaining": "{m} minute{m_plural} remaining",
            "minutes_seconds_remaining": "{m}m {s}s remaining",
            "resume_button": "Resume Work (Esc)",
            "early_exit_prompt": "Why end this break early? (Press Enter to confirm):",
            "early_exit_placeholder": "At least {min_chars} characters...",
        },
    },
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
            merged = json.loads(json.dumps(DEFAULT_CONFIG))
            for k, v in user_cfg.items():
                if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
                    merged[k] = {**merged[k], **v}
                    for sub_k, sub_v in v.items():
                        if isinstance(sub_v, dict) and isinstance(
                            DEFAULT_CONFIG[k].get(sub_k), dict
                        ):
                            merged[k][sub_k] = {
                                **DEFAULT_CONFIG[k][sub_k],
                                **sub_v,
                            }
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
        "resume_button": "Resume Work (Esc)",
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
            "s_plural": "s" if rem_s != 1 else "",
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

    def get_early_exit_prompt(self):
        return self.strings.get(
            "early_exit_prompt",
            "Why end this break early? (Press Enter to confirm):",
        )

    def get_early_exit_placeholder(self, min_chars=5):
        tmpl = self.strings.get(
            "early_exit_placeholder", "At least {min_chars} characters..."
        )
        return tmpl.format(min_chars=min_chars)


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

        self.require_reason = bool(dur_cfg.get("require_early_exit_reason", True))
        self.min_reason_chars = int(dur_cfg.get("min_reason_chars", 5))
        self.prompting_reason = False
        self._syncing_entries = False

        self.ui_cfg = self.cfg.get("ui", {})
        self.sounds_cfg = self.cfg.get("sounds", {})
        self.hooks_cfg = self.cfg.get("hooks", {})
        lang = self.cfg.get("language", "hi")
        self.locale = LocaleAdapter(
            language=lang, locales_dict=self.cfg.get("locales", {})
        )

        self.windows = []
        self.labels = []
        self.progress_bars = []
        self.resume_buttons = []
        self.reason_boxes = []
        self.reason_entries = []
        self.clock_labels = []
        self.clock_format = self.ui_cfg.get("clock_format", "%H:%M  •  %a, %d %b")
        self.clock_position = self.ui_cfg.get("clock_position", "bottom-right").lower()

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

        # Marker for other tools (e.g. voxtype pre_output_command) to defer keystroke
        # injection until the overlay is gone. Holds our PID so readers can ignore a
        # stale file left by a SIGKILL.
        self.active_marker = ACTIVE_MARKER
        try:
            self.active_marker.write_text(str(os.getpid()))
        except OSError as e:
            logger.warning(f"Could not write active marker {self.active_marker}: {e}")
        atexit.register(self.remove_active_marker)
        atexit.register(self.restore_gnome_switchers)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self.start_time = time.time()
        start_key = f"{self.break_type}_start"
        self.play_sound(self.sounds_cfg.get(start_key, "silence"))
        self.run_hook("break_start")

        self.timer_source_id = GLib.timeout_add(100, self.update_timer)

    def run_hook(self, event_name, reason=None):
        """Execute optional lifecycle hook from config['hooks'] or ~/.config/xdg-pause/hooks/<event>.d/."""
        elapsed = int(round(time.time() - getattr(self, "start_time", time.time())))
        remaining = max(0, int(round(self.total_duration - elapsed)))
        dispatch_hook(
            event_name,
            hooks_cfg=self.hooks_cfg,
            mode=self.break_type,
            duration=self.total_duration,
            elapsed=elapsed,
            remaining=remaining,
            reason=reason,
        )

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
        clock_col = self.ui_cfg.get("clock_color", "#ffffff")
        clock_size = self.ui_cfg.get("clock_font_size", 28)
        bar_h = self.ui_cfg.get("bar_height", 6)

        css = f"""
        window.break-window {{
            background-color: {bg};
        }}
        progressbar {{
            background: transparent;
            border: none;
            padding: 0;
            margin: 0;
        }}
        progressbar trough {{
            min-height: {bar_h}px;
            background-color: transparent;
            border-radius: 3px;
            border: 1px solid {bar_border};
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
            font-size: 15px;
            font-weight: 300;
            margin-top: 20px;
        }}
        label.clock-text {{
            color: {clock_col};
            font-family: 'Noto Sans Light', 'Noto Sans Devanagari Light', 'Noto Sans', -apple-system, sans-serif;
            font-size: {clock_size}px;
            font-weight: 300;
            letter-spacing: 0.5px;
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
        label.reason-prompt {{
            color: #aaaaaa;
            font-family: 'Noto Sans Devanagari', 'Noto Sans', sans-serif;
            font-size: 13px;
            margin-top: 16px;
            margin-bottom: 6px;
        }}
        entry.reason-entry {{
            background-color: #111111;
            color: #ffffff;
            caret-color: #ffffff;
            font-family: 'Noto Sans Devanagari', 'Noto Sans', sans-serif;
            font-size: 14px;
            padding: 6px 12px;
            border-radius: 4px;
            border: 1px solid #444444;
        }}
        entry.reason-entry.invalid {{
            border-color: #aa3333;
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

            # Stretchly formula: width = min(50vw, 50vh) = min(width, height) // 2
            cfg_w = self.ui_cfg.get("bar_width")
            if not cfg_w or cfg_w == "auto":
                mon_bar_w = min(geom.width, geom.height) // 2
            else:
                mon_bar_w = int(cfg_w)

            pbar = Gtk.ProgressBar()
            pbar.set_fraction(1.0)
            pbar.set_size_request(mon_bar_w, bar_h)

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
                btn.connect("clicked", lambda b: self.request_early_exit())
                box.pack_start(btn, False, False, 0)
                self.resume_buttons.append(btn)

                rbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                rbox.set_halign(Gtk.Align.CENTER)
                rbox.set_no_show_all(True)

                rlbl = Gtk.Label(label=self.locale.get_early_exit_prompt())
                rlbl.get_style_context().add_class("reason-prompt")
                rlbl.show()

                rentry = Gtk.Entry()
                rentry.get_style_context().add_class("reason-entry")
                rentry.set_width_chars(36)
                rentry.set_placeholder_text(
                    self.locale.get_early_exit_placeholder(self.min_reason_chars)
                )
                rentry.connect("changed", self.on_reason_changed)
                rentry.connect("activate", self.on_reason_activate)
                rentry.show()

                rbox.pack_start(rlbl, False, False, 0)
                rbox.pack_start(rentry, False, False, 0)
                box.pack_start(rbox, False, False, 0)
                self.reason_boxes.append(rbox)
                self.reason_entries.append(rentry)

            overlay = Gtk.Overlay()
            overlay.add(box)

            # Configurable clock alignment (bottom-right / top-right / etc.)
            valign = (
                Gtk.Align.END if "bottom" in self.clock_position else Gtk.Align.START
            )
            halign = Gtk.Align.START if "left" in self.clock_position else Gtk.Align.END

            clock_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            clock_box.set_valign(valign)
            clock_box.set_halign(halign)

            if valign == Gtk.Align.END:
                clock_box.set_margin_bottom(24)
            else:
                clock_box.set_margin_top(24)

            if halign == Gtk.Align.START:
                clock_box.set_margin_start(32)
            else:
                clock_box.set_margin_end(32)

            now_str = datetime.datetime.now().strftime(self.clock_format)
            clock_label = Gtk.Label(label=now_str)
            clock_label.get_style_context().add_class("clock-text")
            clock_box.pack_start(clock_label, False, False, 0)
            overlay.add_overlay(clock_box)

            win.add(overlay)
            win.show_all()
            win.present()

            logger.info(
                f"Monitor {mon_idx} ({desc} {geom.width}x{geom.height}): Window fullscreened and mapped"
            )

            self.windows.append(win)
            self.labels.append(timer_label)
            self.progress_bars.append(pbar)
            self.clock_labels.append(clock_label)

    def request_early_exit(self):
        if not self.require_reason:
            self.finish_break(early=True)
            return
        if not self.prompting_reason:
            self.prompting_reason = True
            logger.info("Prompting user for early break exit reason")
            for btn in self.resume_buttons:
                btn.hide()
            for rbox in self.reason_boxes:
                rbox.show()
            if self.reason_entries:
                self.reason_entries[0].grab_focus()

    def cancel_early_exit_prompt(self):
        if not self.prompting_reason:
            return
        self.prompting_reason = False
        for rentry in self.reason_entries:
            rentry.set_text("")
            rentry.get_style_context().remove_class("invalid")
        for rbox in self.reason_boxes:
            rbox.hide()
        for btn in self.resume_buttons:
            btn.show()
            btn.set_sensitive(True)

    def on_reason_changed(self, entry):
        if self._syncing_entries:
            return
        self._syncing_entries = True
        try:
            txt = entry.get_text()
            for e in self.reason_entries:
                e.get_style_context().remove_class("invalid")
                if e is not entry:
                    e.set_text(txt)
        finally:
            self._syncing_entries = False

    def on_reason_activate(self, entry):
        reason = entry.get_text().strip()
        if len(reason) < self.min_reason_chars:
            for e in self.reason_entries:
                e.get_style_context().add_class("invalid")
            return
        self.finish_break(early=True, reason=reason)

    def on_key_press(self, win, event):
        elapsed = time.time() - self.start_time
        logger.debug(
            f"Key press intercepted: keyval={event.keyval}, elapsed={elapsed:.1f}s"
        )
        if self.break_type == "long" and elapsed >= self.strict_interval:
            if self.prompting_reason:
                if event.keyval == Gdk.KEY_Escape:
                    self.cancel_early_exit_prompt()
                    return True
                # Let key events reach Gtk.Entry so the user can type their reason
                return False
            if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_space):
                logger.info("Early break exit requested by user via keypress")
                self.request_early_exit()
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

        now_str = datetime.datetime.now().strftime(self.clock_format)
        for clk in self.clock_labels:
            clk.set_text(now_str)

        if (
            self.break_type == "long"
            and elapsed >= self.strict_interval
            and not self.prompting_reason
        ):
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
                    None,
                )
                logger.info("GNOME Shell overview suppressor registered")
        except Exception as e:
            logger.debug(f"GNOME Shell overview suppressor not available: {e}")

    def on_gnome_shell_prop_changed(
        self, connection, sender, path, iface, signal, params, user_data
    ):
        try:
            props = params.get_child_value(1)
            if "OverviewActive" in props.keys():
                val = props["OverviewActive"]
                is_open = bool(
                    val.get_boolean() if hasattr(val, "get_boolean") else val
                )
                if is_open:
                    logger.info(
                        "GNOME Shell Overview opened during break; dismissing..."
                    )
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
                None,
            )
            is_open = res.get_child_value(0).get_variant().get_boolean()
            if is_open:
                now = time.time()
                # Debounce logging to once every 0.5s during animation
                if (
                    not hasattr(self, "_last_overview_log")
                    or now - self._last_overview_log > 0.5
                ):
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
                GLib.Variant(
                    "(ssv)",
                    ("org.gnome.Shell", "OverviewActive", GLib.Variant("b", False)),
                ),
                None,
                Gio.DBusCallFlags.NONE,
                200,
                None,
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
        logger.info(
            f"Received termination signal ({signum}), restoring keybindings and exiting"
        )
        self.restore_gnome_switchers()
        sys.exit(0)

    def remove_active_marker(self):
        try:
            if self.active_marker.read_text().strip() == str(os.getpid()):
                self.active_marker.unlink()
        except OSError:
            pass

    def finish_break(self, early=False, reason=None):
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

        if early and reason:
            status = f"early user resume (reason: {reason!r})"
        elif early:
            status = "early user resume"
        else:
            status = "completed countdown"
        logger.info(f"Destroying overlay windows ({status})")

        self.run_hook("early_exit" if early else "break_complete", reason=reason)

        for win in self.windows:
            win.destroy()
        self.remove_active_marker()
        if Gtk.main_level() > 0:
            Gtk.main_quit()


def dispatch_hook(
    event_name,
    hooks_cfg=None,
    mode="",
    duration=0,
    elapsed=0,
    remaining=0,
    reason=None,
):
    """Fire non-blocking hook command from config['hooks'][event_name] and ~/.config/xdg-pause/hooks/<event_name>.d/."""
    if hooks_cfg is None:
        hooks_cfg = load_config().get("hooks", {})
    env = os.environ.copy()
    env.update(
        {
            "XDG_PAUSE_EVENT": str(event_name),
            "XDG_PAUSE_MODE": str(mode),
            "XDG_PAUSE_DURATION": str(duration),
            "XDG_PAUSE_ELAPSED": str(elapsed),
            "XDG_PAUSE_REMAINING": str(remaining),
            "XDG_PAUSE_REASON": str(reason or ""),
        }
    )
    cmd = hooks_cfg.get(event_name)
    if cmd:
        try:
            logger.info(f"Running hook '{event_name}': {cmd}")
            subprocess.Popen(
                cmd,
                shell=True,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.warning(f"Hook '{event_name}' failed to launch: {e}")

    hook_dir = pathlib.Path(CONFIG_DIR) / "hooks" / f"{event_name}.d"
    if hook_dir.is_dir():
        for script in sorted(hook_dir.iterdir()):
            if script.is_file() and os.access(script, os.X_OK):
                try:
                    logger.info(f"Running hook script '{event_name}': {script}")
                    subprocess.Popen(
                        [str(script)],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    logger.warning(f"Hook script {script} failed: {e}")


SNOOZE_TIMER = os.environ.get("XDG_PAUSE_TIMER", "xdg-fixed-break.timer")
SNOOZE_RESUME_UNIT = "break-snooze-resume"


def _snooze_cancel_resume():
    subprocess.run(
        ["systemctl", "--user", "stop", f"{SNOOZE_RESUME_UNIT}.timer"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "systemctl",
            "--user",
            "reset-failed",
            f"{SNOOZE_RESUME_UNIT}.service",
            f"{SNOOZE_RESUME_UNIT}.timer",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _snooze_status():
    res = subprocess.run(
        ["systemctl", "--user", "is-active", SNOOZE_TIMER],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    print(f"break timer: {res.stdout.strip() or 'inactive'}")
    subprocess.run(
        [
            "systemctl",
            "--user",
            "list-timers",
            "--all",
            "--no-pager",
            SNOOZE_TIMER,
            f"{SNOOZE_RESUME_UNIT}.timer",
        ]
    )


def _kill_running_overlays():
    my_pid = str(os.getpid())
    res = subprocess.run(
        ["pgrep", "-f", "xdg_pause.py|bin/xdg-pause"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    for pid in res.stdout.split():
        if pid != my_pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass


def handle_snooze(args_list):
    """Pause or resume the xdg-fixed-break systemd user timer."""
    usage_msg = "usage: xdg-pause snooze [start [MINUTES] | MINUTES | end | resume | on | status]"
    if not args_list:
        action = "start"
        mins = None
    elif args_list[0] in ("-h", "--help"):
        print(usage_msg)
        return 0
    elif args_list[0] == "start":
        action = "start"
        mins = args_list[1] if len(args_list) > 1 else None
        if len(args_list) > 2 or (mins is not None and not mins.isdigit()):
            print(usage_msg, file=sys.stderr)
            return 2
    elif args_list[0] in ("end", "resume", "on"):
        if len(args_list) > 1:
            print(usage_msg, file=sys.stderr)
            return 2
        _snooze_cancel_resume()
        subprocess.run(["systemctl", "--user", "start", SNOOZE_TIMER], check=True)
        dispatch_hook("snooze_end", mode="snooze")
        _snooze_status()
        return 0
    elif args_list[0] == "status":
        if len(args_list) > 1:
            print(usage_msg, file=sys.stderr)
            return 2
        _snooze_status()
        return 0
    elif args_list[0].isdigit() and len(args_list) == 1:
        action = "start"
        mins = args_list[0]
    else:
        print(usage_msg, file=sys.stderr)
        return 2

    if action == "start":
        _snooze_cancel_resume()
        subprocess.run(["systemctl", "--user", "stop", SNOOZE_TIMER], check=True)
        _kill_running_overlays()
        if mins:
            subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--quiet",
                    f"--unit={SNOOZE_RESUME_UNIT}",
                    f"--on-active={mins}m",
                    "--description=Resume xdg-pause breaks after snooze",
                    "systemctl",
                    "--user",
                    "start",
                    SNOOZE_TIMER,
                ],
                check=True,
            )
            until = (
                datetime.datetime.now() + datetime.timedelta(minutes=int(mins))
            ).strftime("%H:%M")
            print(f"Breaks snoozed for {mins} min (until {until}).")
        else:
            print("Breaks snoozed until 'xdg-pause snooze end'.")
        dispatch_hook(
            "snooze_start",
            mode="snooze",
            duration=int(mins) * 60 if mins else 0,
        )
        _snooze_status()
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() == "snooze":
        sys.exit(handle_snooze(sys.argv[2:]))

    parser = argparse.ArgumentParser(
        description="xdg-pause: Minimalist native multi-monitor break overlay for Linux Wayland/X11",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  xdg-pause                     # Mini break using configured duration\n"
            "  xdg-pause long                # Long break (600s with 30s strict interval)\n"
            "  xdg-pause 45                  # Custom 45-second break\n"
            "  xdg-pause snooze 90           # Snooze break timer for 90 minutes\n"
            "  xdg-pause snooze start        # Snooze break timer indefinitely\n"
            "  xdg-pause snooze end          # Resume break timer immediately\n"
            "  xdg-pause snooze status       # Show break timer and snooze status\n"
        ),
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="mini",
        help="Break mode ('mini', 'long', integer seconds, or 'snooze')",
    )
    parser.add_argument(
        "extra",
        nargs="*",
        help="Subcommand arguments when mode is 'snooze' (start [MINUTES] | MINUTES | end | status)",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"xdg-pause {__version__}"
    )
    parser.add_argument(
        "-s",
        "--strict",
        type=int,
        default=None,
        help="Override strict non-cancellable interval in seconds",
    )

    args = parser.parse_args()

    mode_lower = args.mode.lower()
    if mode_lower == "snooze":
        sys.exit(handle_snooze(args.extra))
    if args.extra:
        logger.error(f"Unexpected extra arguments: {' '.join(args.extra)}")
        sys.exit(2)

    b_type = "mini"
    override_dur = None
    override_strict = args.strict

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
    XdgPauseOverlay(
        break_type=b_type,
        override_duration=override_dur,
        override_strict=override_strict,
    )
    Gtk.main()


if __name__ == "__main__":
    main()
