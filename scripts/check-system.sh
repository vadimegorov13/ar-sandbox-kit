#!/bin/bash
# Prints a readiness report for the AR Sandbox: OS, graphics, Kinect,
# displays, built programs and calibration files. Changes nothing.
# Usage: scripts/check-system.sh
set -u

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# The repository copy reads the same ~/.config/ar-sandbox/ar-sandbox.conf as the installed tools.
# shellcheck source=/dev/null
source "$REPO/tools/common.sh" >/dev/null 2>&1

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; }

echo "System"
. /etc/os-release 2>/dev/null && ok "$PRETTY_NAME, kernel $(uname -r)"
[ "${XDG_SESSION_TYPE:-}" = wayland ] && warn "Wayland session: choose \"Ubuntu on Xorg\" at login for reliable projector placement" \
    || ok "Session type: ${XDG_SESSION_TYPE:-unknown}"
echo "  CPU: $(nproc) cores, RAM: $(awk '/MemTotal/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)"

echo "Graphics"
renderer=$(glxinfo -B 2>/dev/null | sed -n 's/OpenGL renderer string: //p')
if lspci 2>/dev/null | grep -Eqi '(vga|3d).*nvidia'; then
    if [ -d /sys/module/nvidia ]; then ok "NVIDIA driver loaded"
    else bad "NVIDIA card present but driver not loaded (run: sudo ubuntu-drivers install, then reboot)"; fi
fi
case "$renderer" in
    "") warn "glxinfo unavailable (install mesa-utils) or no display" ;;
    *llvmpipe*|*softpipe*) bad "Software rendering: $renderer" ;;
    *) ok "OpenGL renderer: $renderer" ;;
esac
glxinfo 2>/dev/null | grep -q GL_EXT_gpu_shader4 && ok "GL_EXT_gpu_shader4 available (fast Kinect projector)"

echo "Kinect"
if lsusb 2>/dev/null | grep -qi '045e:02ae'; then ok "Kinect v1 camera on USB"
else bad "No Kinect v1 camera (045e:02ae) on USB. Check its power adapter and USB cable"; fi
[ -f /etc/udev/rules.d/69-Kinect.rules ] && ok "Kinect USB permission rule installed" \
    || warn "Kinect udev rule missing (build-sarndbox.sh installs it)"
if compgen -G "$KINECT_CONFIG/IntrinsicParameters-*.dat" >/dev/null; then ok "Kinect factory calibration retrieved"
else warn "Kinect factory calibration not retrieved yet (Control Center > Kinect Factory Calibration)"; fi

echo "Displays"
xrandr --query 2>/dev/null | awk '$2=="connected" {print "  " $0}'
connected=$(xrandr --query 2>/dev/null | grep -c ' connected')
[ "$connected" -ge 2 ] && ok "$connected displays (operator monitor + projector)" \
    || warn "$connected display connected; a separate operator monitor is recommended"

echo "Software"
for program in "$VRUI_PREFIX/bin/KinectUtil" "$VRUI_PREFIX/bin/RawKinectViewer" \
               "$SANDBOX_ROOT/bin/SARndbox" "$SANDBOX_ROOT/bin/CalibrateProjector"; do
    [ -x "$program" ] && ok "$program" || bad "missing $program"
done
[ -x "$HOME/.local/share/ar-sandbox/bin/control-center" ] && ok "Control Center installed" \
    || warn "Control Center not installed (scripts/install-tools.sh)"
[ -f "$AR_CONFIG_FILE" ] && ok "Settings: $AR_CONFIG_FILE" || warn "No settings file yet; defaults in use"

echo "Calibration"
[ -f "$SANDBOX_CONFIG/BoxLayout.txt" ] && ok "Sandbox geometry (BoxLayout.txt)" || warn "Sandbox geometry not measured"
[ -f "$SANDBOX_CONFIG/ProjectorMatrix.dat" ] && ok "Projector calibration (ProjectorMatrix.dat)" \
    || warn "Projector not calibrated yet"
