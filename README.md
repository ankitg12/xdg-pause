# xdg-pause

**Minimalist, native multi-monitor break overlay for Linux (Wayland & X11).**

`xdg-pause` delivers a pitch-black, distraction-free break overlay across all connected monitors. It is engineered specifically for Linux desktop environments where Electron-based break timers fail to enforce input discipline or damage multi-monitor window layouts.

---

## The Problems It Solves

### 1. The Wayland Input Leak
Under Wayland (`xdg_shell`), client applications are strictly sandboxed. Conventional Electron break tools (like Stretchly) instantiate break windows with `focusable: false` and `showInactive()`. On Windows, the OS `HWND_TOPMOST` z-order layer intercepts input. On Wayland, however, client applications cannot force coordinate placement or steal focus. Keystrokes continue routing straight to your active terminal or editor during breaks.

### 2. The DPMS Window Migration Trap
Attempting to enforce breaks by putting displays into power-saving standby via D-Bus (`org.gnome.Mutter.DisplayConfig PowerSaveMode i 1`) drops the video signal on external monitors. The Wayland compositor interprets this as a hardware disconnect, collapses all virtual workspaces, and migrates every open window onto the primary laptop display. Waking up does not restore the original window placement.

### 3. Solution: Native GTK3 Multi-Monitor Surfaces
`xdg-pause` creates dedicated, borderless toplevel GTK surfaces across every detected monitor (`Gdk.Display` enumeration). Because displays stay continuously powered on, **zero window rearrangement occurs**. All keyboard events are cleanly absorbed at the surface level, preventing accidental typing into background windows.

---

## Features

- **Minimalist Aesthetic**: Pure pitch-black background (`#000000`) with a thin, 6px depleting progress bar and centered countdown label.
- **Multi-Monitor Safe**: Spans all connected monitors without dropping display signals.
- **Strict Mode**:
  - **Mini Breaks (30s)**: Non-cancellable. Closes automatically when countdown completes.
  - **Long Breaks (600s)**: Strict for the first 30 seconds; permits voluntary early return (`Esc` or resume button) afterward.
- **Decoupled Localization (`LocaleAdapter`)**: Translation strings are template-driven in `config.json` (Hindi, English, etc.) without hardcoded conditionals.
- **Configurable Audio**: Supports silent operation or native XDG sound events (`canberra-gtk-play`).
- **Zero Heavy Overhead**: Pure Python + PyGObject (~250 lines). Eliminates hundreds of megabytes of Electron background memory.

---

## Installation

### Dependencies
Requires Python 3.8+ and PyGObject (GTK3):

```bash
# Ubuntu / Debian
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 libcanberra-gtk-module

# Arch Linux
sudo pacman -S python-gobject gtk3 libcanberra

# Fedora
sudo dnf install python3-gobject gtk3 libcanberra-gtk3
```

### Install CLI
Install directly with `pip` or `uv`:

```bash
git clone https://github.com/ankitg12/xdg-pause.git
cd xdg-pause
pip install .
```

Or run standalone without installing:
```bash
./xdg_pause.py
```

---

## Usage

```bash
# Mini break (defaults to configured duration, e.g. 30s)
xdg-pause

# Long break (600s total, first 30s strict, then allows Esc)
xdg-pause long

# Custom duration in seconds
xdg-pause 45

# Custom duration with custom strict interval
xdg-pause 300 --strict 60
```

---

## Configuration

Configuration file is automatically created at `~/.config/xdg-pause/config.json`:

```json
{
  "language": "hi",
  "sounds": {
    "enabled": false,
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
```

---

## Automated Systemd Cadence

To trigger breaks automatically every 10 minutes (clock-aligned with long breaks at `:50`):

1. Copy systemd units:
   ```bash
   mkdir -p ~/.config/systemd/user
   cp systemd/xdg-pause.service systemd/xdg-pause.timer ~/.config/systemd/user/
   ```

2. Enable and start timer:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now xdg-pause.timer
   ```

---

## Authors

- **Ankit Gaur** ([@ankitg12](https://github.com/ankitg12))
- **Gemini 3.8 Flash**

## License

[MIT License](LICENSE)
