#!/bin/bash
# Installs the Ubuntu/Debian packages needed to build and run the AR Sandbox.
# Usage: scripts/install-dependencies.sh
set -euo pipefail

BUILD_PACKAGES=(
    build-essential g++ pkg-config curl patch
    libudev-dev libdbus-1-dev libusb-1.0-0-dev zlib1g-dev libssl-dev
    libpng-dev libjpeg-dev libtiff-dev libasound2-dev libspeex-dev libopenal-dev
    libv4l-dev libdc1394-dev libtheora-dev libbluetooth-dev libfreetype-dev
    libx11-dev libxi-dev libxrandr-dev mesa-common-dev libgl-dev libglu1-mesa-dev
    # Vrui links its fancy-text nodes only when GNU FreeFont is present.
    fonts-freefont-ttf
)
RUNTIME_PACKAGES=(
    mesa-utils x11-xserver-utils zenity libnotify-bin
    python3 python3-gi gir1.2-gtk-3.0 librsvg2-common
)

command -v apt-get >/dev/null || {
    echo "This script needs apt (Ubuntu, Debian, Linux Mint, Pop!_OS)." >&2
    echo "On other distributions install the equivalents of: ${BUILD_PACKAGES[*]} ${RUNTIME_PACKAGES[*]}" >&2
    exit 1
}

packages=("${BUILD_PACKAGES[@]}" "${RUNTIME_PACKAGES[@]}")
echo "Installing ${#packages[@]} packages (your password may be requested)."
sudo apt-get update
sudo apt-get install -y "${packages[@]}"
echo "Dependencies installed."
