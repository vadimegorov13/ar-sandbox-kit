#!/bin/bash
# Installs the AR Sandbox Control Center, helper scripts, desktop launchers,
# Vrui settings and the user guide for the current user (no root needed).
#
# Usage: scripts/install-tools.sh [--sandbox-root DIR] [--prefix DIR] [--no-desktop-icons]
#   --sandbox-root DIR  folder where SARndbox-2.8 was built (default ~/src/SARndbox-2.8)
#   --prefix DIR        Vrui/Kinect install prefix (default /usr/local)
#   --no-desktop-icons  only add menu entries, not desktop icons
# Run it again after pulling updates; settings and calibrations are kept.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SANDBOX_ROOT=""
PREFIX=""
DESKTOP_ICONS=1
while [ $# -gt 0 ]; do
    case "$1" in
        --sandbox-root) SANDBOX_ROOT=$(realpath -m "$2"); shift 2 ;;
        --prefix) PREFIX=$(realpath -m "$2"); shift 2 ;;
        --no-desktop-icons) DESKTOP_ICONS=0; shift ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

BIN="$HOME/.local/share/ar-sandbox/bin"
CONFIG_DIR="$HOME/.config/ar-sandbox"
CONFIG="$CONFIG_DIR/ar-sandbox.conf"
STAMP=$(date +%Y%m%d-%H%M%S)

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

step "Settings: $CONFIG"
mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG" ]; then
    echo "Keeping existing settings."
else
    cp "$REPO/config/ar-sandbox.conf.example" "$CONFIG"
    echo "Created from config/ar-sandbox.conf.example."
fi
set_setting() {
    local key=$1 value=$2
    if grep -q "^$key=" "$CONFIG"; then
        sed -i "s|^$key=.*|$key=\"$value\"|" "$CONFIG"
    else
        printf '%s="%s"\n' "$key" "$value" >>"$CONFIG"
    fi
    echo "$key=$value"
}
[ -z "$SANDBOX_ROOT" ] || set_setting SANDBOX_ROOT "$SANDBOX_ROOT"
[ -z "$PREFIX" ] || set_setting VRUI_PREFIX "$PREFIX"
if ! lspci 2>/dev/null | grep -qi 'vga.*nvidia\|3d.*nvidia' && grep -q '^NVIDIA_DRIVER=580$' "$CONFIG"; then
    set_setting NVIDIA_DRIVER ""
fi

step "Programs: $BIN"
if [ -d "$BIN" ] && ! diff -rq "$REPO/tools" "$BIN" >/dev/null 2>&1; then
    cp -a "$BIN" "$BIN.backup-$STAMP"
    echo "Previous version saved as $BIN.backup-$STAMP"
fi
rm -rf "$BIN"
mkdir -p "$BIN"
cp "$REPO"/tools/* "$BIN/"
chmod +x "$BIN"/*

# Read back the effective settings (defaults + config file).
eval "$(bash -c 'source "$1/common.sh" >/dev/null 2>&1
    printf "SANDBOX_ROOT=%q\nDOCS_DIR=%q\nVRUI_PREFIX=%q\nVRUI_APP_CONFIG=%q\n" \
        "$SANDBOX_ROOT" "$DOCS_DIR" "$VRUI_PREFIX" "$VRUI_APP_CONFIG"' bash "$BIN")"

step "Vrui settings: $VRUI_APP_CONFIG"
mkdir -p "$VRUI_APP_CONFIG"
for cfg in "$REPO"/vrui-config/*.cfg; do
    target="$VRUI_APP_CONFIG/$(basename "$cfg")"
    if [ -f "$target" ] && ! cmp -s "$cfg" "$target"; then
        cp "$target" "$target.backup-$STAMP"
    fi
    cp "$cfg" "$target"
    echo "Installed $(basename "$cfg")"
done

step "User guide: $DOCS_DIR"
mkdir -p "$DOCS_DIR/images"
python3 "$REPO/scripts/make-guide-html.py" "$REPO/docs/USER_GUIDE.md" "$DOCS_DIR/AR Sandbox User Guide.html"
cp "$REPO/docs/USER_GUIDE.md" "$DOCS_DIR/AR Sandbox User Guide.md"
cp "$REPO"/docs/images/* "$DOCS_DIR/images/"
cp "$REPO/docs/calibration-target-12cm.pdf" "$DOCS_DIR/Calibration Target 12cm.pdf"
echo "Guide, images and printable calibration target installed."

step "Launchers"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
DESKTOP=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
names=(ar-sandbox-control-center ar-sandbox-start ar-sandbox-stop ar-sandbox-guide)
titles=("AR Sandbox Control Center" "Start AR Sandbox" "Stop AR Sandbox" "AR Sandbox Guide")
for i in "${!names[@]}"; do
    sed -e "s|@BIN@|$BIN|g" -e "s|@GUIDE@|$DOCS_DIR/AR Sandbox User Guide.html|g" \
        "$REPO/desktop/${names[$i]}.desktop.in" >"$APPS/${names[$i]}.desktop"
    chmod +x "$APPS/${names[$i]}.desktop"
    if [ "$DESKTOP_ICONS" = 1 ] && [ -d "$DESKTOP" ]; then
        icon="$DESKTOP/${titles[$i]}.desktop"
        cp "$APPS/${names[$i]}.desktop" "$icon"
        chmod +x "$icon"
        # GNOME only runs desktop icons that are marked trusted.
        gio set "$icon" metadata::trusted true 2>/dev/null || true
    fi
done
echo "Menu entries added$( [ "$DESKTOP_ICONS" = 1 ] && echo " and desktop icons placed in $DESKTOP")."

step "Checking the installation"
problems=0
for program in "$SANDBOX_ROOT/bin/SARndbox" "$SANDBOX_ROOT/bin/CalibrateProjector" \
               "$VRUI_PREFIX/bin/KinectUtil" "$VRUI_PREFIX/bin/RawKinectViewer"; do
    if [ -x "$program" ]; then echo "OK       $program"; else echo "MISSING  $program"; problems=1; fi
done
if [ "$problems" = 1 ]; then
    echo
    echo "Some sandbox programs are missing. Build them with scripts/build-sarndbox.sh,"
    echo "or set SANDBOX_ROOT / VRUI_PREFIX in $CONFIG."
fi

cat <<EOF

Done. Open "AR Sandbox Control Center" from the desktop or the applications menu.
First-time setup steps are in "$DOCS_DIR/AR Sandbox User Guide.html".
EOF
