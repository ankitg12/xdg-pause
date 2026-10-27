#!/bin/bash
# install.sh — set up xdg-pause inside a ChromeOS Crostini (penguin) container.
# Installs GTK deps, the xdg-pause CLI, a first-run config (ChromeOS backend is
# auto-detected; no env needed), and a GUI autostart entry for the cadence loop.
#
# Run once inside the Linux container:
#   bash crostini/install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
AUTOSTART_DIR="${HOME}/.config/autostart"

echo "==> Installing GTK3 + PyGObject deps (Debian/penguin default)"
sudo apt-get update
sudo apt-get install -y \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    libcanberra-gtk-module \
    fonts-noto-core fonts-noto-extra

echo "==> Installing xdg-pause CLI to ${BIN_DIR}"
mkdir -p "${BIN_DIR}"
if command -v pipx >/dev/null 2>&1; then
    pipx install "${REPO_DIR}" --force 2>/dev/null || pipx reinstall xdg-pause
else
    pip install --user "${REPO_DIR}"
fi
case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *) echo "NOTE: add to ~/.bashrc: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo "==> First-run config (auto-detects chromeos backend under Sommelier)"
export PATH="${BIN_DIR}:${PATH}"
xdg-pause --version
XDG_PAUSE_BACKEND=chromeos xdg-pause --help >/dev/null

echo "==> Autostart cadence loop (every 10 min, clock-aligned)"
mkdir -p "${AUTOSTART_DIR}"
cat > "${AUTOSTART_DIR}/xdg-pause-loop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=xdg-pause break loop
Comment=Clock-aligned break cadence (Crostini-safe, no systemd timer)
Exec=${REPO_DIR}/crostini/pause-loop.sh ${BIN_DIR}/xdg-pause
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "==> Starting loop now (also starts on next login via autostart)"
nohup "${REPO_DIR}/crostini/pause-loop.sh" "${BIN_DIR}/xdg-pause" \
    >> "${HOME}/.local/state/xdg-pause/pause-loop.log" 2>&1 &
echo
echo "Done. Breaks fire every 10 min (:45-:54 = long). Commands:"
echo "  xdg-pause              # mini break now"
echo "  xdg-pause long         # long break now"
echo "  xdg-pause snooze 90    # pause cadence 90 min (file marker, no systemd)"
echo "  xdg-pause snooze end   # resume cadence"
