#!/usr/bin/python3
"""AR Sandbox Control Center.

A persistent window that starts the existing sandbox scripts, shows live
hardware/calibration status, and runs projector calibration with a result
screen that allows retrying instead of closing.
"""
import glob
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

BIN = os.path.dirname(os.path.realpath(__file__))


def load_settings():
    """Read the effective settings through common.sh so bash and Python agree."""
    names = ("SANDBOX_CONFIG", "SANDBOX_ROOT", "AR_STATE", "AR_GUIDE", "AR_PROFILES_DIR",
             "AR_ACTIVE_PROFILE_FILE", "PROJECTOR_WIDTH", "PROJECTOR_HEIGHT", "NVIDIA_DRIVER")
    out = subprocess.run(
        ["bash", "-c", 'source "$1/common.sh" >/dev/null 2>&1; shift; '
         'for n in "$@"; do printf "%s\\0" "${!n}"; done', "bash", BIN, *names],
        capture_output=True, text=True, check=True).stdout
    return dict(zip(names, out.split("\0")))


SETTINGS = load_settings()
SANDBOX_ROOT = SETTINGS["SANDBOX_ROOT"]
SANDBOX_CONFIG = SETTINGS["SANDBOX_CONFIG"]
AR_STATE = SETTINGS["AR_STATE"]
AR_GUIDE = SETTINGS["AR_GUIDE"]
PROFILES_DIR = SETTINGS["AR_PROFILES_DIR"]
ACTIVE_PROFILE_FILE = SETTINGS["AR_ACTIVE_PROFILE_FILE"]
PROJECTOR_SIZE = (int(SETTINGS["PROJECTOR_WIDTH"]), int(SETTINGS["PROJECTOR_HEIGHT"]))
LAYOUT = SANDBOX_CONFIG + "/BoxLayout.txt"
MATRIX = SANDBOX_CONFIG + "/ProjectorMatrix.dat"
NUM_POINTS = 12

GREEN, AMBER, RED, GREY = "#2e9e4f", "#d98a00", "#d03030", "#888888"

DRIVER_HELP = (
    "The NVIDIA graphics driver is not loaded, so everything is being drawn "
    "by the CPU and the monitor and projector show the same picture.\n\n"
    "This usually happens when Ubuntu installs a new kernel without the "
    "matching NVIDIA module.\n\n"
    "Click “Repair driver”. A terminal window opens, asks for your password, "
    "reinstalls the driver for every installed kernel, and offers to restart. "
    "After the restart this line should read “NVIDIA driver loaded”.\n\n"
    "If the repair says no module is published yet, choose the previous kernel "
    "from “Advanced options for Ubuntu” in the boot menu (hold Shift while "
    "the computer starts) and try the repair again a day later."
)

CALIBRATION_STEPS = (
    "<b>Target</b>  A rigid, flat, matte disk 12 cm across (11–13 cm works) "
    "with a cross drawn exactly on its center. Tape a thin stiff wire or "
    "skewer underneath as a handle so your hand stays well away from it.\n\n"
    "<b>1.</b>  Flatten the sand, take everything out of the box, then press "
    "<b>Start calibration</b>. The red screen is the background capture "
    "(5–10 s). Do not disturb the sand afterwards; if you do, clear the box "
    "and press <b>2</b> to capture it again.\n\n"
    "<b>2.</b>  White crossing lines show the next point. Hold the disk "
    "level with its center under the crossing.\n\n"
    "<b>3.</b>  Wait until the projection shows the disk in <b>green</b>. "
    "Yellow means it was seen but rejected: tilted, a hand or support is "
    "touching it in the camera’s view, or the size is wrong. Before the "
    "first calibration the green image can sit away from the real disk.\n\n"
    "<b>4.</b>  Press <b>1</b> and hold still about 2 seconds until the "
    "lines jump to the next point.\n\n"
    "<b>5.</b>  <b>Change the height at every point.</b> Alternate low "
    "(5–10 cm above the sand) and high (20–35 cm). Twelve points at one "
    "height cannot be solved, however carefully they are placed.\n\n"
    "<b>6.</b>  After point 12, red crosshairs follow the disk. Check that "
    "they stay on its center low and high, then press <b>Esc</b>."
)


def esc(text):
    return GLib.markup_escape_text(str(text))


def bash_common(command):
    """Run a function from common.sh; returns its exit status."""
    return subprocess.run(
        ["bash", "-c", 'source "$1/common.sh"; ' + command, "bash", BIN],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# ---------------------------------------------------------------- status ----

def kinect_present():
    for product in glob.glob("/sys/bus/usb/devices/*/idProduct"):
        try:
            with open(product) as f:
                if f.read().strip() not in ("02ae", "02bf"):
                    continue
            with open(os.path.dirname(product) + "/idVendor") as f:
                if f.read().strip() == "045e":
                    return True
        except OSError:
            pass
    return False


def nvidia_gpu_present():
    for device in glob.glob("/sys/bus/pci/devices/*"):
        try:
            with open(device + "/vendor") as f:
                vendor = f.read().strip()
            with open(device + "/class") as f:
                is_display = f.read().strip().startswith("0x03")
        except OSError:
            continue
        if vendor == "0x10de" and is_display:
            return True
    return False


_renderer_cache = [0.0, ""]


def opengl_renderer():
    """OpenGL renderer name, refreshed at most once a minute."""
    if time.monotonic() - _renderer_cache[0] > 60:
        try:
            out = subprocess.run(["glxinfo", "-B"], capture_output=True, text=True,
                                 timeout=10).stdout
            match = re.search(r"OpenGL renderer string:\s*(.+)", out)
            _renderer_cache[1] = match.group(1).strip() if match else ""
        except (OSError, subprocess.SubprocessError):
            _renderer_cache[1] = ""
        _renderer_cache[0] = time.monotonic()
    return _renderer_cache[1]


def graphics_state():
    """(accelerated, description, repairable) for the status panel."""
    if nvidia_gpu_present():
        if os.path.isdir("/sys/module/nvidia"):
            return True, "NVIDIA driver loaded", False
        return False, "NVIDIA driver not loaded (slow software rendering)", True
    renderer = opengl_renderer()
    if not renderer:
        return True, "Unknown (glxinfo not available)", False
    if re.search(r"llvmpipe|softpipe|software", renderer, re.I):
        return False, f"Software rendering only ({renderer})", False
    return True, renderer, False


def list_monitors():
    try:
        out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [(m.group(3), int(m.group(1)), int(m.group(2))) for m in re.finditer(
        r"^\s*\d+:\s+\S+\s+(\d+)/\d+x(\d+)/\d+\+\d+\+\d+\s+(\S+)", out, re.M)]


def running_programs():
    found = []
    for name, args in (("SARndbox", ["-x", "SARndbox"]),
                       ("Kinect Viewer", ["-x", "RawKinectViewer"]),
                       ("Projector calibration",
                        ["-f", r"/bin/CalibrateProjector([[:space:]]|$)"])):
        if subprocess.run(["pgrep"] + args, stdout=subprocess.DEVNULL).returncode == 0:
            found.append(name)
    return found


def active_profile():
    try:
        with open(ACTIVE_PROFILE_FILE) as f:
            name = f.read().strip()
    except OSError:
        return None
    return name if name and os.path.isdir(os.path.join(PROFILES_DIR, name)) else None


# ----------------------------------------------------------- calibration ----

def read_layout(path=LAYOUT):
    """Return (plane normal, plane offset, four corners) from BoxLayout.txt."""
    with open(path) as f:
        text = f.read()
    num = r"([-+0-9.eE]+)"
    plane = re.search(rf"^\(\s*{num},\s*{num},\s*{num}\),\s*{num}", text, re.M)
    corners = [tuple(map(float, m.groups())) for m in re.finditer(
        rf"^\(\s*{num},\s*{num},\s*{num}\)\s*$", text, re.M)]
    if not plane or len(corners) != 4:
        raise ValueError("BoxLayout.txt does not hold a plane and four corners")
    normal = tuple(float(plane.group(i)) for i in (1, 2, 3))
    return normal, float(plane.group(4)), corners


def solve3(a, b):
    def det(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    d = det(a)
    if abs(d) < 1e-12:
        return None
    result = []
    for col in range(3):
        m = [list(row) for row in a]
        for row in range(3):
            m[row][col] = b[row]
        result.append(det(m) / d)
    return result


def analyse_matrix(matrix_path=None, layout_path=None):
    """Check a projector matrix against the sandbox geometry.

    Returns a dict with 'invalid' and 'poor' reason lists and some numbers.
    """
    report = {"invalid": [], "poor": []}
    matrix_path = matrix_path or MATRIX
    layout_path = layout_path or LAYOUT
    try:
        with open(matrix_path, "rb") as f:
            values = struct.unpack("<16d", f.read())
        normal, offset, corners = read_layout(layout_path)
    except (OSError, ValueError, struct.error) as exc:
        report["invalid"].append(f"The calibration files could not be read ({exc}).")
        return report
    rows = [values[i * 4:(i + 1) * 4] for i in range(4)]

    # Where the four box corners land on the projector image.
    xs, ys, weights = [], [], []
    for corner in corners:
        v = corner + (1.0,)
        q = [sum(rows[r][c] * v[c] for c in range(4)) for r in range(4)]
        if not all(math.isfinite(x) for x in q) or abs(q[3]) < 1e-8:
            report["invalid"].append("A sandbox corner has no finite projection.")
            return report
        xs.append(q[0] / q[3])
        ys.append(q[1] / q[3])
        weights.append(q[3])
    xspan, yspan = max(xs) - min(xs), max(ys) - min(ys)
    half_w, half_h = PROJECTOR_SIZE[0] / 2, PROJECTOR_SIZE[1] / 2
    report["span"] = (xspan * half_w, yspan * half_h)
    same_sign = all(w > 0 for w in weights) or all(w < 0 for w in weights)
    if not (same_sign and 0.5 <= xspan <= 3.0 and 0.5 <= yspan <= 3.0
            and max(abs(v) for v in xs + ys) <= 2.0):
        report["invalid"].append(
            f"The sandbox would be drawn {xspan * half_w:.0f} × {yspan * half_h:.0f} "
            f"pixels on a {PROJECTOR_SIZE[0]} × {PROJECTOR_SIZE[1]} projector, far "
            "outside the image.")

    # Where the matrix says the projector lens is, relative to the sand.
    lens_rows = (rows[0], rows[1], rows[3])
    center = solve3([r[:3] for r in lens_rows], [-r[3] for r in lens_rows])
    kinect_height = -offset
    if center is None:
        report["invalid"].append("The matrix does not describe a real projector.")
    else:
        height = sum(n * c for n, c in zip(normal, center)) - offset
        report["projector_height"] = height
        report["kinect_height"] = kinect_height
        if height < 0.25 * kinect_height:
            where = (f"{-height:.0f} cm below the sand surface" if height < 0
                     else f"only {height:.0f} cm above the sand")
            report["invalid"].append(
                f"The matrix places the projector {where} (the Kinect is "
                f"{kinect_height:.0f} cm above it), which is physically "
                "impossible. This is what happens when all points are "
                "captured at nearly the same height.")
        elif not 0.5 * kinect_height <= height <= 2.5 * kinect_height:
            report["poor"].append(
                f"The matrix places the projector {height:.0f} cm above the sand "
                f"while the Kinect is {kinect_height:.0f} cm above it. Unless the "
                "projector really is mounted there, the points did not vary "
                "enough in height.")
    return report


def point_heights(text):
    """Height above the flat-sand plane (cm) of every captured disk center."""
    try:
        normal, offset, _ = read_layout()
    except (OSError, ValueError):
        return []
    heights = []
    for match in re.finditer(
            r"Tie point position: ([-+0-9.eE]+), ([-+0-9.eE]+), ([-+0-9.eE]+)", text):
        point = [float(v) for v in match.groups()]
        heights.append(sum(n * c for n, c in zip(normal, point)) - offset)
    return heights


def parse_calibration_log(text):
    info = {
        "background_done": bool(re.search(r"background frames\.\.\..*?done", text, re.S)),
        "points": len(re.findall(r"tie point frames\.\.\.\s*done", text)),
        "capturing": text.rstrip().endswith("tie point frames..."),
        "negative": "negative projection weights" in text,
        "rms": None, "spread": None,
        "output_error": re.search(r'Output "[^"]*" not found', text) is not None,
    }
    info["heights"] = point_heights(text)
    rms = re.findall(r"RMS calibration residual:\s*([-+0-9.eE]+)", text)
    if rms:
        info["rms"] = float(rms[-1])
    zrange = re.findall(
        r"Z range of collected tie points: \[([-+0-9.eE]+), ([-+0-9.eE]+)\]", text)
    if zrange:
        low, high = (float(v) for v in zrange[-1])
        if low and high:
            # The calibrator prints -1/distance for the nearest and farthest point.
            info["spread"] = abs(1.0 / low - 1.0 / high)
    return info


def judge_calibration(info, report):
    """Combine log and matrix checks into ('good'|'poor'|'invalid', reasons)."""
    invalid, poor = list(report["invalid"]), list(report["poor"])
    if info["rms"] is not None and info["rms"] > 5.0:
        poor.append(
            f"The fit error is {info['rms']:.1f} pixels (under 2 is good). The "
            "disk center was off the crossing lines, or the disk moved, at "
            "some of the points.")
    heights = info["heights"][:NUM_POINTS]
    if heights and max(heights) - min(heights) < 10.0:
        poor.insert(0,
            f"The Kinect measured every disk between {min(heights):.0f} and "
            f"{max(heights):.0f} cm above the sand. The points must differ by at "
            "least 10 cm in height, ideally 15–25 cm.")
    elif info["spread"] is not None and info["spread"] < 8.0 and not invalid and not heights:
        poor.append(
            f"The captured points span only about {info['spread']:.1f} cm in "
            "distance from the projector. Mix low and high positions.")
    if invalid:
        return "invalid", invalid + poor
    if poor:
        return "poor", poor
    return "good", []


# -------------------------------------------------------------------- UI ----

class ControlCenter(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AR Sandbox Control Center")
        self.set_default_size(880, 680)
        self.set_icon_name("applications-science")
        self.tasks = {}            # label -> Popen
        self.cal_proc = None
        self.cal_log = None
        self.cal_backup = None
        self.cal_rejected = None
        self.cal_wait_since = None
        self.message = "Ready."

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        outer.pack_start(self.stack, True, True, 0)
        self.stack.add_named(self.build_home(), "home")
        self.stack.add_named(self.build_calibration(), "calibration")

        outer.pack_start(Gtk.Separator(), False, False, 0)
        footer = Gtk.Box(spacing=12, margin=10)
        self.activity = Gtk.Label(xalign=0, ellipsize=3)
        footer.pack_start(self.activity, True, True, 0)
        stop = Gtk.Button(label="Stop Everything")
        stop.get_style_context().add_class("destructive-action")
        stop.connect("clicked", lambda *_: self.stop_everything())
        footer.pack_end(stop, False, False, 0)
        outer.pack_start(footer, False, False, 0)

        self.refresh_status()
        GLib.timeout_add_seconds(3, self.refresh_status)
        GLib.timeout_add(500, self.poll)

    # ---- home page ----

    def build_home(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=16)

        self.status_grid = Gtk.Grid(column_spacing=14, row_spacing=4)
        self.status_labels = {}
        for row, key in enumerate(("Kinect", "Graphics", "Displays", "Geometry",
                                   "Projector calibration", "Profile")):
            name = Gtk.Label(xalign=0)
            name.set_markup(f"<b>{esc(key)}</b>")
            value = Gtk.Label(xalign=0, wrap=True, selectable=False)
            value.set_xalign(0)
            self.status_grid.attach(name, 0, row, 1, 1)
            self.status_grid.attach(value, 1, row, 1, 1)
            self.status_labels[key] = value
        frame = Gtk.Frame(label="Status")
        self.status_grid.set_property("margin", 10)
        frame.add(self.status_grid)
        page.pack_start(frame, False, False, 0)

        self.driver_bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        label = Gtk.Label(
            label="Graphics driver not loaded: the sandbox is running in slow "
                  "software mode. Fix this before calibrating.", wrap=True, xalign=0)
        self.driver_bar.get_content_area().add(label)
        self.driver_bar.get_content_area().show_all()
        self.driver_bar.get_action_area().show_all()
        self.driver_bar.add_button("What happened?", 1)
        self.repair_button = self.driver_bar.add_button("Repair driver", 2)
        self.driver_bar.connect("response", lambda _bar, response: self.show_text(
            "Graphics driver not loaded", DRIVER_HELP) if response == 1
            else self.repair_driver())
        self.driver_bar.set_no_show_all(True)
        page.pack_start(self.driver_bar, False, False, 0)

        sections = (
            ("Run", (
                ("Start Sandbox", "Water and automatic hand rain",
                 lambda: self.launch("Sandbox", ["start-sandbox", "water"])),
                ("Start Without Water", "Elevation colors and contours only",
                 lambda: self.launch("Sandbox", ["start-sandbox", "no-water"])),
                ("Leveling Grid", "Project a grid for flattening the sand",
                 lambda: self.launch("Leveling grid", ["level-grid"])),
            )),
            ("Calibration", (
                ("Projector Calibration", "Align the projection with the sand",
                 self.open_calibration),
                ("Geometry Wizard", "Re-measure the base plane and corners",
                 lambda: self.launch("Geometry wizard", ["geometry-calibration"])),
                ("Manual Geometry", "Type in exact sandbox dimensions",
                 lambda: self.launch("Manual geometry", ["manual-geometry"])),
                ("Calibration Profiles", "Save, activate and inspect profiles",
                 lambda: self.launch("Profiles", ["profile-manager"])),
                ("Kinect Viewer", "Check the depth and color images",
                 lambda: self.launch("Kinect viewer", ["kinect-viewer"])),
                ("Kinect Factory Calibration", "Only after replacing the Kinect",
                 lambda: self.launch("Kinect factory calibration",
                                     ["kinect-factory-calibration"])),
            )),
            ("Help", (
                ("User Guide", "Instructions and troubleshooting",
                 lambda: self.open_path(AR_GUIDE)),
                ("Logs", "Open the diagnostic log folder",
                 lambda: self.open_path(AR_STATE)),
                ("Repair Graphics Driver", "Reinstall the NVIDIA driver",
                 self.repair_driver),
                ("Detailed Status", "Full hardware and file report",
                 lambda: self.launch("Status report", ["show-status"])),
            )),
        )
        for title, tiles in sections:
            heading = Gtk.Label(xalign=0)
            heading.set_markup(f"<span size='large'><b>{esc(title)}</b></span>")
            page.pack_start(heading, False, False, 0)
            grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
            for index, (name, hint, action) in enumerate(tiles):
                grid.attach(self.tile(name, hint, action), index % 3, index // 3, 1, 1)
            page.pack_start(grid, False, False, 0)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add(page)
        return scroller

    def tile(self, name, hint, action):
        button = Gtk.Button()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=6)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{esc(name)}</b>")
        subtitle = Gtk.Label(label=hint, xalign=0, wrap=True, max_width_chars=26)
        subtitle.set_xalign(0)
        subtitle.get_style_context().add_class("dim-label")
        box.pack_start(title, False, False, 0)
        box.pack_start(subtitle, False, False, 0)
        button.add(box)
        button.connect("clicked", lambda *_: action())
        return button

    # ---- calibration page ----

    def build_calibration(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        heading = Gtk.Label(xalign=0)
        heading.set_markup("<span size='x-large'><b>Projector Calibration</b></span>")
        page.pack_start(heading, False, False, 0)

        self.cal_banner = Gtk.Label(xalign=0, wrap=True)
        self.cal_banner.set_xalign(0)
        page.pack_start(self.cal_banner, False, False, 0)

        self.cal_body = Gtk.Label(xalign=0, yalign=0, wrap=True)
        self.cal_body.set_xalign(0)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add(self.cal_body)
        page.pack_start(scroller, True, True, 0)

        self.cal_progress = Gtk.ProgressBar(show_text=True)
        self.cal_progress.set_no_show_all(True)
        page.pack_start(self.cal_progress, False, False, 0)

        buttons = Gtk.Box(spacing=10)
        self.btn_back = Gtk.Button(label="← Back to menu")
        self.btn_back.connect("clicked", lambda *_: self.stack.set_visible_child_name("home"))
        self.btn_start = Gtk.Button(label="Start calibration")
        self.btn_start.get_style_context().add_class("suggested-action")
        self.btn_start.connect("clicked", lambda *_: self.start_calibration())
        self.btn_abort = Gtk.Button(label="Cancel calibration")
        self.btn_abort.connect("clicked", lambda *_: self.stop_everything())
        self.btn_use = Gtk.Button(label="Use this result anyway")
        self.btn_use.connect("clicked", lambda *_: self.use_rejected())
        self.btn_run = Gtk.Button(label="Start sandbox to check")
        self.btn_run.connect("clicked", lambda *_: (
            self.stack.set_visible_child_name("home"),
            self.launch("Sandbox", ["start-sandbox", "water"])))
        self.btn_log = Gtk.Button(label="Open log")
        self.btn_log.connect("clicked", lambda *_: self.cal_log and self.open_path(self.cal_log))
        buttons.pack_start(self.btn_back, False, False, 0)
        for button in (self.btn_start, self.btn_abort, self.btn_run, self.btn_use, self.btn_log):
            button.set_no_show_all(True)
            buttons.pack_end(button, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def cal_show(self, state, banner, body, color=None):
        """Switch the calibration page between prepare/running/result states."""
        self.cal_state = state
        if color:
            banner = f"<span foreground='{color}'><b>{banner}</b></span>"
        self.cal_banner.set_markup(banner)
        self.cal_body.set_markup(body)
        running = state == "running"
        self.btn_back.set_sensitive(not running)
        self.btn_start.set_visible(not running)
        self.btn_start.set_label("Start calibration" if state == "prepare" else "Try again")
        self.btn_abort.set_visible(running)
        self.cal_progress.set_visible(running)
        self.btn_run.set_visible(state == "good")
        self.btn_use.set_visible(state == "poor" and self.cal_rejected is not None)
        self.btn_log.set_visible(state in ("good", "poor", "invalid") and self.cal_log is not None)

    def open_calibration(self):
        if self.cal_proc is None:
            if graphics_state()[0]:
                banner = "Read the steps once, then start. You can retry as often as needed."
            else:
                banner = (f"<span foreground='{RED}'><b>The graphics driver is not "
                          "working.</b></span> Fix that first (see the menu); a "
                          "calibration made now may not match once it is repaired.")
            self.cal_show("prepare", banner, CALIBRATION_STEPS)
        self.stack.set_visible_child_name("calibration")

    def start_calibration(self):
        if self.cal_proc is not None:
            return
        if not kinect_present():
            self.cal_show("prepare", "The Kinect was not detected. Check its power "
                          "adapter and USB cable, then try again.", CALIBRATION_STEPS, RED)
            return
        self.cal_rejected = None
        self.cal_log = None
        self.cal_wait_since = None
        self.cal_show("running", "Preparing the projector…", CALIBRATION_STEPS)
        self.cal_progress.set_fraction(0)
        self.cal_progress.set_text("Starting")
        threading.Thread(target=self.calibration_worker, daemon=True).start()

    def calibration_worker(self):
        if bash_common("stop_ar_programs; configure_displays") != 0:
            GLib.idle_add(self.cal_show, "invalid", "The projector display could not "
                          "be configured. Check its power and video cable.",
                          CALIBRATION_STEPS, RED)
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = None
        if os.path.exists(MATRIX):
            backup = f"{MATRIX}.backup-{stamp}"
            os.rename(MATRIX, backup)
        log_path = f"{AR_STATE}/CalibrateProjector-{stamp}.log"
        with open(log_path, "ab") as log:
            # -bmd 1 keeps a low target from merging with the sand around it.
            proc = subprocess.Popen(
                ["stdbuf", "-oL", "-eL", "./bin/CalibrateProjector",
                 "-s", str(PROJECTOR_SIZE[0]), str(PROJECTOR_SIZE[1]), "-bmd", "1"],
                cwd=SANDBOX_ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT)

        def started():
            self.cal_backup, self.cal_log, self.cal_stamp = backup, log_path, stamp
            self.cal_proc = proc
        GLib.idle_add(started)

    def update_calibration_progress(self):
        try:
            with open(self.cal_log, errors="replace") as f:
                info = parse_calibration_log(f.read())
        except OSError:
            return
        points = info["points"]
        self.cal_progress.set_fraction(min(points, NUM_POINTS) / NUM_POINTS)
        self.cal_progress.set_text(f"{min(points, NUM_POINTS)} of {NUM_POINTS} points"
                                   + (f"  (+{points - NUM_POINTS} extra)" if points > NUM_POINTS else ""))
        if not info["capturing"]:
            self.cal_wait_since = None
        elif self.cal_wait_since is None:
            self.cal_wait_since = time.monotonic()

        if not info["background_done"]:
            banner = "Capturing the empty sandbox. Keep everything out of the box."
        elif info["capturing"] and time.monotonic() - self.cal_wait_since > 6:
            banner = (f"<span foreground='{AMBER}'><b>1 was pressed, but the Kinect does "
                      "not see exactly one valid disk.</b></span> Level the disk and move "
                      "your hand away until it turns green; the capture then continues "
                      "by itself.")
        elif info["capturing"]:
            banner = "Capturing. Hold the disk still."
        elif points >= NUM_POINTS and info["rms"] is not None:
            banner = (f"<span foreground='{GREEN}'><b>All {NUM_POINTS} points captured "
                      f"(fit error {info['rms']:.1f} px).</b></span> Check that the red "
                      "crosshairs follow the disk, then press Esc.")
        elif info["negative"]:
            banner = (f"<span foreground='{RED}'><b>The points contradict each other."
                      "</b></span> Press Esc and try again.")
        else:
            level = "LOW (5–10 cm above the sand)" if points % 2 == 0 else "HIGH (20–35 cm)"
            banner = (f"Point {points + 1} of {NUM_POINTS}: hold the disk <b>{level}</b> "
                      "under the crossing lines, wait for green, press 1.")
        if info["heights"]:
            measured = "  ".join(f"{h:.0f}" for h in info["heights"])
            spread = max(info["heights"]) - min(info["heights"])
            color = GREEN if spread >= 10 or len(info["heights"]) < 2 else RED
            banner += (f"\n\nLast disk was measured <b>{info['heights'][-1]:.0f} cm</b> "
                       f"above the sand.  All so far (cm): <span foreground='{color}'>"
                       f"<b>{measured}</b></span>")
            if len(info["heights"]) >= 2 and spread < 10:
                banner += ("\n<span foreground='%s'>These are all about the same height. "
                           "The next disk must be at least 10 cm higher or lower.</span>" % RED)
        self.cal_banner.set_markup(banner)

    def finish_calibration(self):
        self.cal_proc = None
        try:
            with open(self.cal_log, errors="replace") as f:
                info = parse_calibration_log(f.read())
        except OSError:
            info = parse_calibration_log("")

        if not os.path.exists(MATRIX):
            self.restore_backup()
            if info["output_error"]:
                why = "The calibrator could not open the projector display."
            elif not info["background_done"]:
                why = "The calibrator closed before the background capture finished."
            elif info["negative"]:
                why = ("The captured points contradict each other, so no calibration "
                       "could be calculated.")
            else:
                why = (f"Only {info['points']} of {NUM_POINTS} points were captured "
                       "before the calibrator closed. Nothing is saved until all "
                       f"{NUM_POINTS} are done.")
            kept = " Your previous calibration is still in place." if self.cal_backup else ""
            self.cal_show("invalid", "No calibration was saved.",
                          esc(why + kept) + "\n\n" + CALIBRATION_STEPS, RED)
            return

        report = analyse_matrix()
        verdict, reasons = judge_calibration(info, report)
        numbers = []
        if info["rms"] is not None:
            numbers.append(f"Fit error: {info['rms']:.2f} pixels (under 2 is good)")
        if info["heights"]:
            numbers.append("Measured disk heights above the sand (cm): "
                           + "  ".join(f"{h:.0f}" for h in info["heights"]))
        elif info["spread"] is not None:
            numbers.append(f"Depth range of the captured points: about {info['spread']:.0f} cm")
        if "projector_height" in report:
            numbers.append(f"Calculated projector height above the sand: "
                           f"{report['projector_height']:.0f} cm "
                           f"(Kinect: {report['kinect_height']:.0f} cm)")
        if "span" in report:
            numbers.append("Sandbox size on the projector: %.0f × %.0f of %d × %d pixels"
                           % (report["span"] + PROJECTOR_SIZE))
        details = "\n".join("•  " + esc(line) for line in numbers)

        if verdict == "good":
            self.sync_profile()
            self.cal_show("good", "Calibration saved.", details + "\n\nStart the sandbox "
                          "and check that contour lines sit on the real hills and "
                          "valleys everywhere in the box.", GREEN)
            return

        self.cal_rejected = f"{MATRIX}.rejected-{self.cal_stamp}"
        os.rename(MATRIX, self.cal_rejected)
        self.restore_backup()
        problems = "\n\n".join("<b>Problem:</b> " + esc(reason) for reason in reasons)
        kept = ("\n\nYour previous calibration was put back." if self.cal_backup
                else "\n\nNo calibration is active.")
        title = ("Calibration rejected." if verdict == "invalid"
                 else "Calibration looks unreliable and was not activated.")
        self.cal_show(verdict, title, problems + "\n\n" + details + esc(kept)
                      + "\n\n" + CALIBRATION_STEPS, RED if verdict == "invalid" else AMBER)

    def restore_backup(self):
        if self.cal_backup and os.path.exists(self.cal_backup) and not os.path.exists(MATRIX):
            os.rename(self.cal_backup, MATRIX)

    def use_rejected(self):
        if not self.cal_rejected or not os.path.exists(self.cal_rejected):
            return
        if os.path.exists(MATRIX):
            os.rename(MATRIX, f"{MATRIX}.backup-{time.strftime('%Y%m%d-%H%M%S')}")
        os.rename(self.cal_rejected, MATRIX)
        self.cal_rejected = None
        self.sync_profile()
        self.cal_show("good", "The result was activated at your request.",
                      "Start the sandbox and check the alignment. Run the calibration "
                      "again if contour lines drift away from the sand.", AMBER)

    def sync_profile(self):
        name = active_profile()
        if name and os.path.exists(MATRIX):
            shutil.copy(MATRIX, os.path.join(PROFILES_DIR, name, "ProjectorMatrix.dat"))

    # ---- actions ----

    def launch(self, label, command):
        if self.cal_proc is not None:
            self.message = "Projector calibration is running. Finish or cancel it first."
            self.open_calibration()
            return
        proc = self.tasks.get(label)
        if proc is not None and proc.poll() is None:
            self.message = f"{label} is already open."
            self.update_activity()
            return
        self.tasks[label] = subprocess.Popen(
            [os.path.join(BIN, command[0])] + command[1:], start_new_session=True)
        self.message = f"Opened {label.lower()}."
        self.update_activity()

    def repair_driver(self):
        if not nvidia_gpu_present() or not SETTINGS["NVIDIA_DRIVER"]:
            self.show_text("No NVIDIA driver to repair",
                           "Repair Graphics Driver reinstalls the NVIDIA driver on Ubuntu. "
                           "This computer has no NVIDIA graphics card, or NVIDIA_DRIVER is "
                           "empty in ~/.config/ar-sandbox/ar-sandbox.conf. For AMD or Intel "
                           "graphics, install the latest system updates and restart.")
            return
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL, text="Reinstall the graphics driver?")
        dialog.format_secondary_text(
            "The sandbox will be closed and a terminal window will open. It asks "
            "for your password, needs an internet connection, and takes a few "
            "minutes. A restart is needed afterwards.")
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK:
            self.stop_everything()
            self.launch("Driver repair", ["open-driver-repair"])

    def stop_everything(self):
        self.message = "Stopping sandbox programs…"
        self.update_activity()

        def worker():
            bash_common("stop_ar_programs")
            GLib.idle_add(self.set_message, "Sandbox programs stopped.")
        threading.Thread(target=worker, daemon=True).start()

    def set_message(self, text):
        self.message = text
        self.update_activity()

    def open_path(self, path):
        Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(path, None), None)

    def show_text(self, title, text):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.INFO,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(text)
        for label in dialog.get_message_area().get_children():
            label.set_selectable(True)
        dialog.run()
        dialog.destroy()

    # ---- periodic updates ----

    def poll(self):
        for label, proc in list(self.tasks.items()):
            code = proc.poll()
            if code is not None:
                del self.tasks[label]
                self.message = (f"{label} closed." if code == 0 else
                                f"{label} stopped with a problem. See Logs for details.")
        if self.cal_proc is not None:
            if self.cal_proc.poll() is None:
                self.update_calibration_progress()
            else:
                self.finish_calibration()
                self.refresh_status()
                self.present()
        self.update_activity()
        return True

    def update_activity(self):
        active = [label for label, proc in self.tasks.items() if proc.poll() is None]
        if self.cal_proc is not None:
            active.append("Projector calibration")
        if active:
            self.activity.set_markup("<b>Open now:</b> " + esc(", ".join(active)))
        else:
            self.activity.set_text(self.message)

    def set_status(self, key, color, text):
        self.status_labels[key].set_markup(
            f"<span foreground='{color}'>●</span>  {esc(text)}")

    def refresh_status(self):
        if kinect_present():
            self.set_status("Kinect", GREEN, "Connected")
        else:
            self.set_status("Kinect", RED, "Not detected. Check power adapter and USB cable")

        accelerated, description, repairable = graphics_state()
        self.driver_bar.set_visible(not accelerated)
        self.repair_button.set_visible(repairable)
        self.set_status("Graphics", GREEN if accelerated else RED, description)

        monitors = list_monitors()
        text = ",  ".join(f"{name} {w}×{h}" for name, w, h in monitors) or "None found"
        if len(monitors) >= 2:
            self.set_status("Displays", GREEN, text)
        else:
            self.set_status("Displays", AMBER, text + "  (only one display: the monitor is off "
                            "or mirrored, or the graphics driver is not working)")

        try:
            _, _, corners = read_layout()
            width = math.dist(corners[0], corners[1])
            depth = math.dist(corners[0], corners[2])
            self.set_status("Geometry", GREEN, f"Measured, {width:.0f} × {depth:.0f} cm")
        except (OSError, ValueError):
            self.set_status("Geometry", RED, "Missing. Run the Geometry Wizard")

        if not os.path.exists(MATRIX):
            self.set_status("Projector calibration", AMBER,
                            "Not done. The projection will not line up with the sand")
        else:
            report = analyse_matrix()
            if report["invalid"]:
                self.set_status("Projector calibration", RED, "Installed but invalid. Recalibrate")
            elif report["poor"]:
                self.set_status("Projector calibration", AMBER, "Installed, looks unreliable")
            else:
                when = time.strftime("%b %d, %H:%M", time.localtime(os.path.getmtime(MATRIX)))
                self.set_status("Projector calibration", GREEN, f"Installed ({when})")

        name = active_profile()
        self.set_status("Profile", GREEN if name else GREY, name or "None active")
        return True


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.arsandbox.ControlCenter")
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = ControlCenter(self)
            self.window.show_all()
        self.window.present()


def self_test():
    """Print what the checks say about every matrix on disk, then exit."""
    print("kinect:", kinect_present(), "| graphics:", graphics_state(),
          "| monitors:", list_monitors(), "| profile:", active_profile())
    for path in sorted(glob.glob(MATRIX + "*")):
        report = analyse_matrix(path)
        print(os.path.basename(path), {k: v for k, v in report.items() if v})
    for path in sorted(glob.glob(AR_STATE + "/CalibrateProjector-*.log")):
        with open(path, errors="replace") as f:
            print(os.path.basename(path), parse_calibration_log(f.read()))


if __name__ == "__main__":
    os.makedirs(AR_STATE, exist_ok=True)
    if "--self-test" in sys.argv:
        self_test()
    else:
        sys.exit(App().run(None))
