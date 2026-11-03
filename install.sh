#!/bin/bash
# One-step AR Sandbox installer for Ubuntu 24.04 (and other apt-based systems).
#   1. installs build and runtime packages        (scripts/install-dependencies.sh)
#   2. downloads, patches and builds the software (scripts/build-sarndbox.sh)
#   3. installs the Control Center and launchers  (scripts/install-tools.sh)
#
# Usage: ./install.sh [--prefix DIR] [--src DIR]
#   --prefix DIR  install prefix for Vrui and the Kinect package (default /usr/local)
#   --src DIR     where sources are unpacked and SARndbox is built (default ~/src)
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PREFIX=/usr/local
SRC=$HOME/src
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$(realpath -m "$2"); shift 2 ;;
        --src) SRC=$(realpath -m "$2"); shift 2 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

[ "$(id -u)" -ne 0 ] || { echo "Run this as your normal user, not with sudo; it asks for the password when needed." >&2; exit 1; }

"$REPO/scripts/install-dependencies.sh"
"$REPO/scripts/build-sarndbox.sh" --prefix "$PREFIX" --src "$SRC"
"$REPO/scripts/install-tools.sh" --sandbox-root "$SRC/SARndbox-2.8" --prefix "$PREFIX"

echo
"$REPO/scripts/check-system.sh" || true
cat <<'EOF'

Installation finished. Next:
  1. Connect the Kinect (USB + power) and the projector, then log out and back in.
  2. Open "AR Sandbox Control Center" and follow "First-time setup" in the guide.
EOF
