# Installing the AR Sandbox Kit

Tested on **Ubuntu 24.04 LTS** with an NVIDIA GTX 970, a Kinect v1 (model 1414) and a 1024×768 projector. Other apt-based distributions (Ubuntu 22.04, Debian 12, Linux Mint, Pop!_OS) should work with the same steps; see [Other distributions](#other-distributions).

Total time: about 1 hour, mostly waiting for compilation.

## 1. Prepare the computer

1. Install Ubuntu 24.04 LTS and all updates:

   ```bash
   sudo apt update && sudo apt full-upgrade
   ```

2. Install the graphics driver. For NVIDIA cards:

   ```bash
   sudo ubuntu-drivers install
   ```

   AMD and Intel graphics work with the built-in drivers.

3. Restart, and on the login screen click the gear icon and choose **Ubuntu on Xorg**. Wayland works for basic use, but cannot set the projector resolution or position reliably.

4. Check the graphics driver:

   ```bash
   glxinfo -B | grep "OpenGL renderer"
   ```

   It must name your graphics card. `llvmpipe` means the driver is not working; fix that before continuing.

## 2. Get the kit

```bash
sudo apt install git
git clone <this repository> ~/ar-sandbox-kit
cd ~/ar-sandbox-kit
```

## 3. Install

```bash
./install.sh
```

Run it as your normal user; it asks for your password when it needs it. It does three things, which you can also run one at a time:

| Step | Script | What it does |
|---|---|---|
| 1 | `scripts/install-dependencies.sh` | Installs about 40 Ubuntu packages (compilers, libraries, zenity, GTK for Python) |
| 2 | `scripts/build-sarndbox.sh` | Downloads Vrui 8.0-002, Kinect 3.10 and SARndbox 2.8 into `~/src`, checks their SHA-256 sums, applies the patches, builds them, installs Vrui and Kinect into `/usr/local`, and installs the Kinect USB permission rule |
| 3 | `scripts/install-tools.sh` | Installs the Control Center and helpers into `~/.local/share/ar-sandbox/bin`, the settings file, the Vrui key and window settings, desktop and menu launchers, and the user guide into `~/Documents/AR Sandbox` |

At the end it runs `scripts/check-system.sh` and prints a report.

Options:

| Option | Effect |
|---|---|
| `./install.sh --src DIR` | Build in `DIR` instead of `~/src` |
| `./install.sh --prefix DIR` | Install Vrui and Kinect into `DIR` instead of `/usr/local`. A folder in your home directory needs no password |

`build-sarndbox.sh` can be run again safely: finished downloads, patches and builds are reused.

### The patches

| Patch | Why |
|---|---|
| `vrui-8.0-002-openal-headers.patch` | Vrui 8.0 declares its own OpenAL types, which clash with OpenAL 1.23 in current Ubuntu and stop the build |
| `sarndbox-2.8-calibrateprojector-point-heights.patch` | Makes the projector calibrator print each captured disk position, so the Control Center can show point heights live |

## 4. Connect the hardware

1. Plug the Kinect's power adapter in, then its USB cable into a port directly on the computer.
2. Connect the projector, and the operator monitor if you have one.
3. Log out and back in (or restart) so the Kinect USB permission rule takes effect.
4. Check everything:

   ```bash
   scripts/check-system.sh
   ```

   Every line should say OK. Warnings about calibration are expected at this point.

## 5. Check the settings

Open `~/.config/ar-sandbox/ar-sandbox.conf` in a text editor. The defaults suit a 1024×768 projector next to one monitor. If the sandbox opens on the wrong screen, set the output names shown by `xrandr --query`:

```bash
PROJECTOR_OUTPUT=HDMI-0
MONITOR_OUTPUT=DVI-I-1
```

All settings are explained in the [user guide](USER_GUIDE.md#settings-file).

## 6. Calibrate

Open **AR Sandbox Control Center** from the desktop or the applications menu, then follow [First-time setup and full calibration](USER_GUIDE.md#first-time-setup-and-full-calibration) in the user guide:

1. Kinect Factory Calibration
2. Kinect Viewer (check the camera sees the whole box)
3. Geometry Wizard (or Manual Geometry)
4. Projector Calibration, with the printed target from `docs/calibration-target-12cm.pdf`

Then double-click **Start AR Sandbox**.

## Updating

```bash
cd ~/ar-sandbox-kit
git pull
scripts/install-tools.sh
```

Settings, calibrations, profiles and logs are kept. The previous tools are saved as `~/.local/share/ar-sandbox/bin.backup-<time>`.

## Uninstalling

```bash
scripts/uninstall-tools.sh
```

This removes the Control Center, helpers and launchers, and keeps settings, calibrations and the built software. To remove the built software too, delete `~/src/Vrui-8.0-002`, `~/src/Kinect-3.10` and `~/src/SARndbox-2.8`, then run `sudo make uninstall` in the Vrui and Kinect folders before deleting them.

## Other distributions

`install-dependencies.sh` needs apt. On Fedora, Arch or openSUSE, install the equivalent development packages listed in that script by hand, then run `scripts/build-sarndbox.sh` and `scripts/install-tools.sh` directly. The **Repair Graphics Driver** button only works on Ubuntu.

## Installation problems

| Problem | Fix |
|---|---|
| Checksum mismatch | Delete the named `.tar.gz` in `~/src` and run again; the download was incomplete |
| Vrui build stops at `SoundContext.h` | The OpenAL patch did not apply; the script prints why. Start from a freshly unpacked Vrui folder |
| Linking fails with `FancyFontStyleNode` | `fonts-freefont-ttf` was missing during the build. Install it, run `make config` in `~/src/Vrui-8.0-002`, and run the build again |
| `KINECT_PROJECTORTYPE=0` printed on a modern GPU | The build ran without a display (for example over SSH). Run it from a desktop terminal, or set `KINECT_PROJECTORTYPE=1` before the command |
| "Fewer than 1 3D cameras connected" | Kinect power or USB, or the permission rule needs a logout/login |
| Control Center does not open | Run `~/.local/share/ar-sandbox/bin/control-center` in a terminal to see the error; usually `python3-gi` or `gir1.2-gtk-3.0` is missing |
