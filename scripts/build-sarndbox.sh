#!/bin/bash
# Downloads, verifies, patches, builds and installs Vrui 8.0-002, Kinect 3.10
# and SARndbox 2.8 (the AR Sandbox software from UC Davis / Oliver Kreylos).
#
# Usage: scripts/build-sarndbox.sh [--prefix DIR] [--src DIR] [--jobs N] [--no-udev]
#   --prefix DIR  where Vrui and the Kinect package are installed (default /usr/local)
#   --src DIR     where sources are unpacked and SARndbox is built (default ~/src)
#   --jobs N      parallel compile jobs (default: number of CPUs)
#   --no-udev     do not install the Kinect USB permission rule
# Safe to run again: finished downloads, patches and builds are reused.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PREFIX=/usr/local
SRC=$HOME/src
JOBS=$(nproc)
UDEV=1

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$(realpath -m "$2"); shift 2 ;;
        --src) SRC=$(realpath -m "$2"); shift 2 ;;
        --jobs) JOBS=$2; shift 2 ;;
        --no-udev) UDEV=0; shift ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

BASE_URL=https://web.cs.ucdavis.edu/~okreylos/ResDev
PACKAGES=(
    "Vrui-8.0-002|$BASE_URL/Vrui/Vrui-8.0-002.tar.gz|8bb1f89a649a1c86ad0fa953a86d737ff4daeccb5fbc46149b696c4ddae16e6c"
    "Kinect-3.10|$BASE_URL/Kinect/Kinect-3.10.tar.gz|5ec3bd12a958bd9f087eac2464c0bffa433f24a25e939e196b2833dd8d76409e"
    "SARndbox-2.8|$BASE_URL/SARndbox/SARndbox-2.8.tar.gz|2b8e88077ded8b5783b7d5345c50ae86ff4c296b96c6b2b682cefe592f4ba88f"
)
VRUI_MAKEDIR=$PREFIX/share/Vrui-8.0/make

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Install with sudo only when the prefix is not writable by this user.
as_installer() {
    mkdir -p "$PREFIX" 2>/dev/null || true
    if [ -w "$PREFIX" ]; then "$@"; else sudo "$@"; fi
}

# Apply a patch once; succeed quietly if it is already in the tree.
apply_patch() {
    local tree=$1 patch_file=$2
    if patch -d "$tree" -p1 -R --dry-run -s -f <"$patch_file" >/dev/null 2>&1; then
        echo "Already applied: $(basename "$patch_file")"
    elif patch -d "$tree" -p1 --dry-run -s -f <"$patch_file" >/dev/null 2>&1; then
        patch -d "$tree" -p1 -s <"$patch_file"
        echo "Applied: $(basename "$patch_file")"
    else
        die "$(basename "$patch_file") does not apply to $tree. Was the source modified?"
    fi
}

step "Downloading and verifying sources in $SRC"
mkdir -p "$SRC"
for entry in "${PACKAGES[@]}"; do
    IFS='|' read -r name url sha <<<"$entry"
    archive="$SRC/$name.tar.gz"
    if [ ! -f "$archive" ]; then
        echo "Downloading $url"
        curl -fL --retry 3 -o "$archive.part" "$url" || die "Download failed: $url"
        mv "$archive.part" "$archive"
    fi
    echo "$sha  $archive" | sha256sum -c --quiet - \
        || die "$archive does not match the expected checksum. Delete it and run again."
    [ -d "$SRC/$name" ] || tar -xzf "$archive" -C "$SRC"
done

step "Building Vrui 8.0-002 (the longest step, often 10–30 minutes)"
cd "$SRC/Vrui-8.0-002"
# Vrui's bundled OpenAL declarations conflict with OpenAL 1.23+ headers.
apply_patch . "$REPO/patches/vrui-8.0-002-openal-headers.patch"
make -j"$JOBS" INSTALLDIR="$PREFIX"
step "Installing Vrui into $PREFIX"
as_installer make INSTALLDIR="$PREFIX" install

step "Building the Kinect 3.10 package"
cd "$SRC/Kinect-3.10"
# The makefile probes glxinfo itself, which gives a different answer under
# sudo (no display). Decide once here and pass it to every make call.
if [ -z "${KINECT_PROJECTORTYPE:-}" ]; then
    # grep without -q reads all input, so pipefail does not see glxinfo die of SIGPIPE.
    if glxinfo 2>/dev/null | grep GL_EXT_gpu_shader4 >/dev/null; then
        KINECT_PROJECTORTYPE=1
    else
        KINECT_PROJECTORTYPE=0
        echo "GL_EXT_gpu_shader4 not reported (or no display); using the CPU depth projector."
    fi
fi
echo "KINECT_PROJECTORTYPE=$KINECT_PROJECTORTYPE"
KINECT_ARGS=(VRUI_MAKEDIR="$VRUI_MAKEDIR" KINECT_PROJECTORTYPE="$KINECT_PROJECTORTYPE")
make "${KINECT_ARGS[@]}" config
make -j"$JOBS" "${KINECT_ARGS[@]}"
step "Installing the Kinect package into $PREFIX"
as_installer make "${KINECT_ARGS[@]}" install
if [ "$UDEV" = 1 ]; then
    step "Installing the Kinect USB permission rule"
    sudo make "${KINECT_ARGS[@]}" installudevrules
    sudo udevadm control --reload-rules
    sudo udevadm trigger || true
fi

step "Building SARndbox 2.8 in $SRC/SARndbox-2.8"
cd "$SRC/SARndbox-2.8"
# Prints each captured disk position so the Control Center can show heights.
apply_patch . "$REPO/patches/sarndbox-2.8-calibrateprojector-point-heights.patch"
make -j"$JOBS" VRUI_MAKEDIR="$VRUI_MAKEDIR"

step "Checking the result"
missing=0
for program in "$PREFIX/bin/KinectUtil" "$PREFIX/bin/RawKinectViewer" \
               "$SRC/SARndbox-2.8/bin/SARndbox" "$SRC/SARndbox-2.8/bin/CalibrateProjector"; do
    if [ -x "$program" ]; then echo "OK       $program"; else echo "MISSING  $program"; missing=1; fi
done
[ "$missing" = 0 ] || die "Some programs were not built. Scroll up for the first error."

cat <<EOF

Build complete.
  Vrui and Kinect tools: $PREFIX/bin
  SARndbox:              $SRC/SARndbox-2.8
Next: scripts/install-tools.sh --sandbox-root "$SRC/SARndbox-2.8" --prefix "$PREFIX"
EOF
