#!/usr/bin/python3
"""Full-screen projector grid for visually leveling the AR sandbox."""

import html
import os
import signal

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk


class LevelGrid(Gtk.Window):
    PALETTES = (
        ("#19f2f2", "#e6ffff"),
        ("#33ff4d", "#e6ffe6"),
        ("#ff4030", "#ffe6bf"),
        ("#b85aff", "#ffe6ff"),
    )

    def __init__(self):
        super().__init__(title="AR Sandbox Leveling Grid")
        self.spacing = 64
        self.palette = 0
        self.show_help = True
        self.show_diagonals = True

        self.set_decorated(False)
        self.set_keep_above(True)
        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key)

        screen = Gdk.Screen.get_default()
        monitor = int(os.environ.get("AR_GRID_MONITOR", "0"))
        monitor = max(0, min(monitor, max(0, screen.get_n_monitors() - 1)))
        geometry = screen.get_monitor_geometry(monitor)
        self.grid_width = geometry.width
        self.grid_height = geometry.height

        self.image = Gtk.Image()
        self.add(self.image)
        self.render_grid()
        self.fullscreen_on_monitor(screen, monitor)
        self.show_all()
        self.present()
        GLib.timeout_add_seconds(8, self.hide_help_once)

    def hide_help_once(self):
        self.show_help = False
        self.render_grid()
        return False

    def on_key(self, _widget, event):
        key = Gdk.keyval_name(event.keyval) or ""
        if key in ("Escape", "q", "Q"):
            self.close()
            return True
        if key in ("plus", "equal", "KP_Add"):
            self.spacing = min(160, self.spacing + 8)
        elif key in ("minus", "underscore", "KP_Subtract"):
            self.spacing = max(24, self.spacing - 8)
        elif key in ("c", "C"):
            self.palette = (self.palette + 1) % len(self.PALETTES)
        elif key in ("d", "D"):
            self.show_diagonals = not self.show_diagonals
        elif key in ("h", "H"):
            self.show_help = not self.show_help
        elif key in ("r", "R"):
            self.spacing = 64
            self.palette = 0
            self.show_diagonals = True
        else:
            return True
        self.render_grid()
        return True

    def render_grid(self):
        width, height = self.grid_width, self.grid_height
        minor, major = self.PALETTES[self.palette]
        elements = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#010203"/>',
        ]

        center_x, center_y = width / 2, height / 2
        start_x = center_x % self.spacing
        start_y = center_y % self.spacing

        index = 0
        x = start_x
        while x <= width:
            is_major = index % 4 == 0
            color = major if is_major else minor
            line_width = 2.2 if is_major else 1.0
            opacity = 0.95 if is_major else 0.48
            elements.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}" stroke="{color}" stroke-width="{line_width}" opacity="{opacity}"/>')
            x += self.spacing
            index += 1

        index = 0
        y = start_y
        while y <= height:
            is_major = index % 4 == 0
            color = major if is_major else minor
            line_width = 2.2 if is_major else 1.0
            opacity = 0.95 if is_major else 0.48
            elements.append(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}" stroke="{color}" stroke-width="{line_width}" opacity="{opacity}"/>')
            y += self.spacing
            index += 1

        if self.show_diagonals:
            elements.append(f'<line x1="0" y1="0" x2="{width}" y2="{height}" stroke="{major}" stroke-width="2" opacity="0.75"/>')
            elements.append(f'<line x1="{width}" y1="0" x2="0" y2="{height}" stroke="{major}" stroke-width="2" opacity="0.75"/>')

        elements.extend((
            f'<line x1="{center_x}" y1="0" x2="{center_x}" y2="{height}" stroke="{major}" stroke-width="3.5"/>',
            f'<line x1="0" y1="{center_y}" x2="{width}" y2="{center_y}" stroke="{major}" stroke-width="3.5"/>',
            f'<rect x="2" y="2" width="{width - 4}" height="{height - 4}" fill="none" stroke="{major}" stroke-width="4"/>',
        ))

        if self.show_help:
            help_text = "Esc: close    + / −: grid size    C: color    D: diagonals    H: hide help    R: reset"
            box_width = min(width - 40, 830)
            box_x = (width - box_width) / 2
            elements.append(f'<rect x="{box_x}" y="{height - 62}" width="{box_width}" height="44" rx="7" fill="#000" opacity="0.84"/>')
            elements.append(f'<text x="{width / 2}" y="{height - 34}" text-anchor="middle" fill="{major}" font-family="sans-serif" font-size="17" font-weight="bold">{html.escape(help_text)}</text>')

        elements.append("</svg>")
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.write("".join(elements).encode("utf-8"))
        loader.close()
        self.image.set_from_pixbuf(loader.get_pixbuf())


def stop_main_loop(*_args):
    GLib.idle_add(Gtk.main_quit)


signal.signal(signal.SIGTERM, stop_main_loop)
LevelGrid()
Gtk.main()
