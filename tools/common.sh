#!/bin/bash
# Shared settings and helpers for the AR Sandbox tools. Sourced by every script.

AR_BIN=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Defaults; ~/.config/ar-sandbox/ar-sandbox.conf overrides any of them.
SANDBOX_ROOT="$HOME/src/SARndbox-2.8"
VRUI_PREFIX=/usr/local
PROJECTOR_OUTPUT=auto
PROJECTOR_WIDTH=1024
PROJECTOR_HEIGHT=768
PROJECTOR_RATE=60
MONITOR_OUTPUT=auto
WATER_GRID_WIDTH=200
WATER_GRID_HEIGHT=150
NVIDIA_DRIVER=580
DOCS_DIR="$HOME/Documents/AR Sandbox"

AR_CONFIG_FILE=${AR_CONFIG_FILE:-$HOME/.config/ar-sandbox/ar-sandbox.conf}
# shellcheck source=/dev/null
[ -f "$AR_CONFIG_FILE" ] && source "$AR_CONFIG_FILE"

SANDBOX_CONFIG="$SANDBOX_ROOT/etc/SARndbox-2.8"
KINECT_CONFIG="$VRUI_PREFIX/etc/Vrui-8.0/Kinect-3.10"
VRUI_APP_CONFIG="$HOME/.config/Vrui-8.0/Applications"
AR_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/ar-sandbox"
AR_GUIDE="$DOCS_DIR/AR Sandbox User Guide.html"
AR_PROFILES_DIR="$DOCS_DIR/Calibration Profiles"
AR_ACTIVE_PROFILE_FILE="$HOME/.config/ar-sandbox/active-profile"

mkdir -p "$AR_STATE" "$AR_PROFILES_DIR" "$(dirname "$AR_ACTIVE_PROFILE_FILE")"

active_profile_dir() {
    [ -f "$AR_ACTIVE_PROFILE_FILE" ] || return 1
    local profile_name
    profile_name=$(cat "$AR_ACTIVE_PROFILE_FILE")
    [ -n "$profile_name" ] || return 1
    [ -d "$AR_PROFILES_DIR/$profile_name" ] || return 1
    printf '%s\n' "$AR_PROFILES_DIR/$profile_name"
}

sync_active_geometry() {
    local profile_dir
    profile_dir=$(active_profile_dir) || return 0
    cp "$SANDBOX_CONFIG/BoxLayout.txt" "$profile_dir/BoxLayout.txt"
}

sync_active_projector() {
    local profile_dir
    profile_dir=$(active_profile_dir) || return 0
    [ -f "$SANDBOX_CONFIG/ProjectorMatrix.dat" ] || return 0
    cp "$SANDBOX_CONFIG/ProjectorMatrix.dat" "$profile_dir/ProjectorMatrix.dat"
}

show_error() {
    zenity --error --title="AR Sandbox" --width=520 --text="$1"
}

show_info() {
    zenity --info --title="AR Sandbox" --width=520 --text="$1"
}

kinect_connected() {
    "$VRUI_PREFIX/bin/KinectUtil" list 2>/dev/null | grep -q '^Kinect 0:'
}

# Picks the projector and operator monitor, puts the projector at its
# configured resolution to the right of the monitor, and points the Vrui
# full-screen settings at it. Exports AR_PROJECTOR_OUTPUT.
configure_displays() {
    local outputs projector monitor mode
    local -a connected
    outputs=$(xrandr --query 2>/dev/null) || return 1
    mapfile -t connected < <(awk '$2=="connected" {print $1}' <<<"$outputs")
    [ "${#connected[@]}" -gt 0 ] || return 1

    projector=$PROJECTOR_OUTPUT
    if [ -z "$projector" ] || [ "$projector" = auto ]; then
        if [ "${#connected[@]}" -eq 1 ]; then
            projector=${connected[0]}
        else
            projector=$(awk '$2=="connected" && $3!="primary" {print $1}' <<<"$outputs" | tail -n 1)
            [ -n "$projector" ] || projector=${connected[-1]}
        fi
    elif ! printf '%s\n' "${connected[@]}" | grep -qxF "$projector"; then
        # Without the GPU driver (or under Wayland) outputs get generic names
        # such as None-1; a single remaining display must be the projector.
        [ "${#connected[@]}" -eq 1 ] || return 1
        projector=${connected[0]}
    fi

    monitor=$MONITOR_OUTPUT
    if [ "$monitor" = auto ]; then
        monitor=$(printf '%s\n' "${connected[@]}" | grep -vxF "$projector" | head -n 1)
    elif [ -n "$monitor" ] && ! printf '%s\n' "${connected[@]}" | grep -qxF "$monitor"; then
        monitor=""
    fi

    # Best effort: xrandr cannot change modes under Wayland, and some
    # projectors report 59.9 Hz instead of exactly 60.
    mode="${PROJECTOR_WIDTH}x${PROJECTOR_HEIGHT}"
    if [ -n "$monitor" ]; then
        xrandr --output "$monitor" --auto --primary \
               --output "$projector" --mode "$mode" --rate "$PROJECTOR_RATE" --right-of "$monitor" 2>/dev/null ||
        xrandr --output "$monitor" --auto --primary \
               --output "$projector" --mode "$mode" --right-of "$monitor" 2>/dev/null || true
    else
        xrandr --output "$projector" --mode "$mode" --rate "$PROJECTOR_RATE" --primary 2>/dev/null ||
        xrandr --output "$projector" --mode "$mode" --primary 2>/dev/null || true
    fi

    export AR_PROJECTOR_OUTPUT="$projector"

    local cfg
    for cfg in "$VRUI_APP_CONFIG/CalibrateProjector.cfg" "$VRUI_APP_CONFIG/SARndbox.cfg"; do
        if [ -f "$cfg" ]; then
            sed -i -E "s/^([[:space:]]*)outputName[[:space:]].*$/\\1outputName $projector/" "$cfg"
        fi
    done
}

stop_ar_programs() {
    if [ -f "$AR_STATE/level-grid.pid" ]; then
        grid_pid=$(cat "$AR_STATE/level-grid.pid" 2>/dev/null || true)
        if [[ "$grid_pid" =~ ^[0-9]+$ ]]; then
            kill -TERM "$grid_pid" 2>/dev/null || true
        fi
    fi
    pkill -INT -x SARndbox 2>/dev/null || true
    pkill -INT -x RawKinectViewer 2>/dev/null || true
    # Linux process names are limited to 15 characters, so match the full
    # executable path for CalibrateProjector.
    pkill -INT -f '/bin/CalibrateProjector([[:space:]]|$)' 2>/dev/null || true
    for unused_attempt in $(seq 1 30); do
        if ! pgrep -x SARndbox >/dev/null && \
           ! pgrep -x RawKinectViewer >/dev/null && \
           ! pgrep -f '/bin/CalibrateProjector([[:space:]]|$)' >/dev/null; then
            return 0
        fi
        sleep 0.1
    done
    pkill -TERM -f '/bin/CalibrateProjector([[:space:]]|$)' 2>/dev/null || true
}
