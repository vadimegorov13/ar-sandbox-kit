#!/bin/bash
# Removes the Control Center, helper scripts and launchers installed by
# install-tools.sh. Keeps settings, calibrations, profiles, logs and the
# built SARndbox/Vrui software.
# Usage: scripts/uninstall-tools.sh
set -euo pipefail

DESKTOP=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
rm -rf "$HOME/.local/share/ar-sandbox/bin"
rm -f "$HOME"/.local/share/applications/ar-sandbox-{control-center,start,stop,guide}.desktop
rm -f "$DESKTOP/AR Sandbox Control Center.desktop" "$DESKTOP/Start AR Sandbox.desktop" \
      "$DESKTOP/Stop AR Sandbox.desktop" "$DESKTOP/AR Sandbox Guide.desktop"

cat <<EOF
Removed the AR Sandbox tools and launchers.
Kept: ~/.config/ar-sandbox (settings), ~/.local/state/ar-sandbox (logs),
the guide and calibration profiles in ~/Documents/AR Sandbox, and the built software.
EOF
