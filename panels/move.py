import logging
import re
from time import monotonic

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ks_includes.KlippyGcodes import KlippyGcodes
from ks_includes.screen_panel import ScreenPanel


class Panel(ScreenPanel):
    distances = [".01", ".1", "1", "5", "10", "25", "50"]
    distance = "5"

    def __init__(self, screen, title):
        title = title or _("Jog")
        super().__init__(screen, title)
        self.distances = list(type(self).distances)
        self.distance = type(self).distance
        self.last_jog = {}

        if self.ks_printer_cfg is not None:
            dis = self.ks_printer_cfg.get("move_distances", "")
            if re.match(r"^[0-9,\.\s]+$", dis):
                dis = [str(i.strip()) for i in dis.split(",")]
                if 1 < len(dis) <= 7:
                    self.distances = dis
                    self.distance = self.distances[min(3, len(self.distances) - 1)]

        self.settings = {}
        self.menu.append("move_menu")
        self.buttons = {
            "x+": self._gtk.Button("arrow-right", "X+", "color1"),
            "x-": self._gtk.Button("arrow-left", "X-", "color1"),
            "y+": self._gtk.Button("arrow-up", "Y+", "color2"),
            "y-": self._gtk.Button("arrow-down", "Y-", "color2"),
            "z+": self._gtk.Button("z-farther", "Z+", "color3"),
            "z-": self._gtk.Button("z-closer", "Z-", "color3"),
            "xy_zero": self._gtk.Button(label="XY0"),
            "home": self._gtk.Button("home", _("Home"), "color4"),
            "motors_off": self._gtk.Button("motor-off", _("Disable Motors"), "color4"),
        }
        self.buttons["x+"].connect("clicked", self.move, "X", "+")
        self.buttons["x-"].connect("clicked", self.move, "X", "-")
        self.buttons["y+"].connect("clicked", self.move, "Y", "+")
        self.buttons["y-"].connect("clicked", self.move, "Y", "-")
        self.buttons["z+"].connect("clicked", self.move, "Z", "+")
        self.buttons["z-"].connect("clicked", self.move, "Z", "-")
        self.buttons["xy_zero"].connect("clicked", self.move_to_xy_zero)
        self.buttons["home"].connect("clicked", self.home)
        script = {"script": "M18"}
        self.buttons["motors_off"].connect(
            "clicked",
            self._screen._confirm_send_action,
            _("Are you sure you wish to disable motors?"),
            "printer.gcode.script",
            script,
        )
        adjust = self._gtk.Button("settings", None, "color2", 1, Gtk.PositionType.LEFT, 1)
        adjust.connect("clicked", self.load_menu, "options", _("Settings"))
        adjust.set_hexpand(False)

        xm = "x-"
        xp = "x+"
        ym = "y-"
        yp = "y+"
        zm = "z-"
        zp = "z+"

        rotation = (
            0 if self.ks_printer_cfg is None else self.ks_printer_cfg.getint("screw_rotation", 0)
        )
        if rotation == 90:
            xm, yp, xp, ym = ym, xm, yp, xp
        elif rotation == 180:
            xm, yp, xp, ym = xp, ym, xm, yp
        elif rotation == 270:
            xm, yp, xp, ym = yp, xp, ym, xm

        if self._config.get_config()["main"].getboolean("invert_z", False):
            zm, zp = zp, zm

        scale = self._gtk.img_scale * self._gtk.button_image_scale * 0.62
        self.buttons[xm].set_image(self._gtk.Image("arrow-left", scale, scale))
        self.buttons[yp].set_image(self._gtk.Image("arrow-up", scale, scale))
        self.buttons[xp].set_image(self._gtk.Image("arrow-right", scale, scale))
        self.buttons[ym].set_image(self._gtk.Image("arrow-down", scale, scale))
        self.buttons[zm].set_image(self._gtk.Image("z-closer", scale, scale))
        self.buttons[zp].set_image(self._gtk.Image("z-farther", scale, scale))
        self.buttons["home"].set_image(self._gtk.Image("home", scale, scale))
        self.buttons["motors_off"].set_image(self._gtk.Image("motor-off", scale, scale))
        adjust.set_image(self._gtk.Image("settings", scale, scale))

        for name in ("x+", "x-", "y+", "y-", "z+", "z-"):
            self.buttons[name].get_style_context().add_class("cnc-jog-button")
        self.buttons["xy_zero"].get_style_context().add_class("cnc-jog-button")
        self.buttons["xy_zero"].get_style_context().add_class("cnc-jog-corner")

        xy_center = Gtk.Label(label="XY")
        xy_center.get_style_context().add_class("cnc-jog-center")
        xy_pad = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        xy_pad.set_row_spacing(4)
        xy_pad.set_column_spacing(4)
        xy_pad.get_style_context().add_class("cnc-jog-pad")
        xy_pad.attach(self.buttons[yp], 1, 0, 1, 1)
        xy_pad.attach(self.buttons[xm], 0, 1, 1, 1)
        xy_pad.attach(xy_center, 1, 1, 1, 1)
        xy_pad.attach(self.buttons[xp], 2, 1, 1, 1)
        xy_pad.attach(self.buttons["xy_zero"], 0, 2, 1, 1)
        xy_pad.attach(self.buttons[ym], 1, 2, 1, 1)

        z_center = Gtk.Label(label="Z")
        z_center.get_style_context().add_class("cnc-jog-center")
        z_pad = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        z_pad.set_row_spacing(4)
        z_pad.get_style_context().add_class("cnc-jog-pad")
        z_pad.attach(self.buttons[zp], 0, 0, 1, 1)
        z_pad.attach(z_center, 0, 1, 1, 1)
        z_pad.attach(self.buttons[zm], 0, 2, 1, 1)

        actions = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        actions.set_row_spacing(4)
        actions.get_style_context().add_class("cnc-jog-actions")
        actions.attach(self.buttons["home"], 0, 0, 1, 1)
        actions.attach(self.buttons["motors_off"], 0, 1, 1, 1)
        actions.attach(adjust, 0, 2, 1, 1)

        jog_area = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        jog_area.set_row_spacing(6)
        jog_area.set_column_spacing(6)
        jog_area.set_vexpand(True)
        if self._screen.vertical_mode:
            jog_area.attach(xy_pad, 0, 0, 2, 2)
            jog_area.attach(z_pad, 0, 2, 1, 1)
            jog_area.attach(actions, 1, 2, 1, 1)
        else:
            jog_area.attach(xy_pad, 0, 0, 3, 1)
            jog_area.attach(z_pad, 3, 0, 1, 1)
            jog_area.attach(actions, 4, 0, 1, 1)

        distgrid = Gtk.Grid()
        for j, i in enumerate(self.distances):
            self.labels[i] = self._gtk.Button(label=i)
            self.labels[i].set_direction(Gtk.TextDirection.LTR)
            self.labels[i].connect("clicked", self.change_distance, i)
            ctx = self.labels[i].get_style_context()
            ctx.add_class("horizontal_togglebuttons")
            if i == self.distance:
                ctx.add_class("horizontal_togglebuttons_active")
            distgrid.attach(self.labels[i], j, 0, 1, 1)

        for p in ("pos_x", "pos_y", "pos_z"):
            self.labels[p] = self._gtk.Button()
            self.labels[p].set_hexpand(False)
            self.labels[p].set_vexpand(False)
            self.labels[p].connect("clicked", self.menu_item_clicked, {"panel": "dro"})
            self.labels[p].get_style_context().add_class("no-margin")
        self.labels["move_dist"] = Gtk.Label(label=_("Jog Step (mm)"))
        self.labels["jog_status"] = Gtk.Label(label="WCS --")
        self.labels["jog_status"].get_style_context().add_class("cnc-status")

        bottomgrid = Gtk.Grid(column_homogeneous=True)
        bottomgrid.set_row_spacing(0)
        bottomgrid.get_style_context().add_class("no-margin")
        bottomgrid.get_style_context().add_class("no-padding")
        bottomgrid.attach(self.labels["pos_x"], 0, 0, 1, 1)
        bottomgrid.attach(self.labels["pos_y"], 1, 0, 1, 1)
        bottomgrid.attach(self.labels["pos_z"], 2, 0, 1, 1)
        bottomgrid.attach(self.labels["move_dist"], 0, 1, 1, 1)
        bottomgrid.attach(self.labels["jog_status"], 1, 1, 2, 1)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        footer.set_vexpand(False)
        footer.pack_start(bottomgrid, False, False, 0)
        footer.pack_start(distgrid, False, False, 0)

        self.labels["move_menu"] = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
        )
        self.labels["move_menu"].pack_start(jog_area, True, True, 0)
        self.labels["move_menu"].pack_end(footer, False, False, 0)

        self.content.add(self.labels["move_menu"])

        printer_cfg = self._printer.get_config_section("printer")
        # The max_velocity parameter is not optional in klipper config.
        # The minimum is 1, but least 2 values are needed to create a scale
        max_velocity = max(int(float(printer_cfg["max_velocity"])), 2)
        if "max_z_velocity" in printer_cfg:
            self.max_z_velocity = max(int(float(printer_cfg["max_z_velocity"])), 2)
        else:
            self.max_z_velocity = max_velocity

        configurable_options = [
            {
                "invert_x": {
                    "section": "main",
                    "name": _("Invert X"),
                    "type": "binary",
                    "tooltip": _("Invert the X jog direction"),
                    "value": "False",
                    "callback": self.reinit_panels,
                }
            },
            {
                "invert_y": {
                    "section": "main",
                    "name": _("Invert Y"),
                    "type": "binary",
                    "tooltip": _("Invert the Y jog direction"),
                    "value": "False",
                    "callback": self.reinit_panels,
                }
            },
            {
                "invert_z": {
                    "section": "main",
                    "name": _("Invert Z"),
                    "tooltip": _(
                        "Swaps buttons if they are on top of each other, affects other panels"
                    ),
                    "type": "binary",
                    "value": "False",
                    "callback": self.reinit_move,
                }
            },
            {
                "move_speed_xy": {
                    "section": "main",
                    "name": _("XY Speed (mm/s)"),
                    "type": "scale",
                    "tooltip": _("Jog feed for the X and Y axes"),
                    "value": "50",
                    "range": [1, max_velocity],
                    "step": 1,
                }
            },
            {
                "move_speed_z": {
                    "section": "main",
                    "name": _("Z Speed (mm/s)"),
                    "type": "scale",
                    "tooltip": _("Jog feed for the Z axis"),
                    "value": "10",
                    "range": [1, self.max_z_velocity],
                    "step": 1,
                }
            },
        ]

        self.labels["options_menu"] = self._gtk.ScrolledWindow()
        self.labels["options"] = Gtk.Grid()
        self.labels["options_menu"].add(self.labels["options"])
        self.options = {}
        for option in configurable_options:
            name = list(option)[0]
            self.options.update(self.add_option("options", self.settings, name, option[name]))

    def reinit_panels(self, value):
        return

    def reinit_move(self, widget):
        self._screen.panels_reinit.append("move")
        self.menu.clear()

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        if "toolhead" in data and "max_velocity" in data["toolhead"]:
            max_vel = max(int(float(data["toolhead"]["max_velocity"])), 2)
            adj = self.options["move_speed_xy"].get_adjustment()
            adj.set_upper(max_vel)
        if (
            "gcode_move" in data
            or "toolhead" in data
            or "motion_report" in data
            or "work_coordinate_systems" in data
            or "print_stats" in data
        ):
            homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
            position = self._printer.get_stat("gcode_move", "gcode_position")
            for i, axis in enumerate(("x", "y", "z")):
                if axis not in homed_axes:
                    self.labels[f"pos_{axis}"].set_label(f"{axis.upper()}: ?")
                elif isinstance(position, (list, tuple)) and len(position) > i:
                    self.labels[f"pos_{axis}"].set_label(
                        f"{axis.upper()}: {position[i]:.3f}" if axis == "z"
                        else f"{axis.upper()}: {position[i]:.2f}"
                    )
                self.buttons[f"{axis}+"].set_sensitive(self._jog_allowed(axis))
                self.buttons[f"{axis}-"].set_sensitive(self._jog_allowed(axis))

            wcs = self._printer.get_stat("work_coordinate_systems")
            active_wcs = (
                "G53"
                if wcs and wcs.get("machine_mode")
                else wcs.get("active_wcs", "G54") if wcs else "Work"
            )
            mode = (
                "G90"
                if self._printer.get_stat("gcode_move", "absolute_coordinates")
                else "G91"
            )
            velocity = float(self._printer.get_stat("motion_report", "live_velocity") or 0)
            self.labels["jog_status"].set_label(
                f"{active_wcs}  |  {mode}  |  {velocity:.2f} mm/s"
            )
            running = self._printer.state in {"printing", "paused"}
            self.buttons["home"].set_sensitive(not running)
            self.buttons["motors_off"].set_sensitive(not running)
            self.buttons["xy_zero"].set_sensitive(self._xy_zero_allowed())

    def change_distance(self, widget, distance):
        logging.info(f"### Distance {distance}")
        self.labels[f"{self.distance}"].get_style_context().remove_class(
            "horizontal_togglebuttons_active"
        )
        self.labels[f"{distance}"].get_style_context().add_class("horizontal_togglebuttons_active")
        self.distance = distance

    def move(self, widget, axis, direction):
        axis = axis.lower()
        if not self._jog_allowed(axis):
            self._screen.show_popup_message(
                _("Jog is unavailable while running or before the axis is homed")
            )
            return
        now = monotonic()
        if now - self.last_jog.get(axis, 0) < 0.05:
            return
        self.last_jog[axis] = now
        if self._config.get_config()["main"].getboolean(f"invert_{axis}", False) and axis != "z":
            direction = "-" if direction == "+" else "+"

        dist = f"{direction}{self.distance}"
        config_key = "move_speed_z" if axis == "z" else "move_speed_xy"
        speed = (
            None if self.ks_printer_cfg is None else self.ks_printer_cfg.getint(config_key, None)
        )
        if speed is None:
            speed = self._config.get_config()["main"].getint(config_key, self.max_z_velocity)
        speed = 60 * max(1, speed)
        script = (
            "SAVE_GCODE_STATE NAME=_ks_cnc_jog\n"
            f"{KlippyGcodes.MOVE_RELATIVE}\n"
            f"G1 {axis.upper()}{dist} F{speed}\n"
            "RESTORE_GCODE_STATE NAME=_ks_cnc_jog"
        )
        self._screen._send_action(widget, "printer.gcode.script", {"script": script})

    def _jog_allowed(self, axis):
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        return axis.lower() in homed_axes and self._printer.state not in {"printing", "paused"}

    def _xy_zero_allowed(self):
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        return "x" in homed_axes and "y" in homed_axes and self._printer.state not in {
            "printing",
            "paused",
        }

    def move_to_xy_zero(self, widget):
        if not self._xy_zero_allowed():
            self._screen.show_popup_message(
                _("Move to XY zero is unavailable while running or before X and Y are homed")
            )
            return

        printer_cfg = self._printer.get_config_section("printer")
        max_velocity = max(int(float(printer_cfg["max_velocity"])), 1)
        speed = (
            None
            if self.ks_printer_cfg is None
            else self.ks_printer_cfg.getint("move_speed_xy", None)
        )
        if speed is None:
            speed = self._config.get_main_config().getint("move_speed_xy", max_velocity)
        feedrate = 60 * min(max(1, speed), max_velocity)

        wcs = self._printer.get_stat("work_coordinate_systems") or {}
        active_wcs = wcs.get("active_wcs", "G54")
        script = (
            "SAVE_GCODE_STATE NAME=_ks_cnc_xy_zero\n"
            f"{active_wcs}\n"
            "G90\n"
            f"G1 X0 Y0 F{feedrate}\n"
            "RESTORE_GCODE_STATE NAME=_ks_cnc_xy_zero MOVE=0"
        )
        self._screen._confirm_send_action(
            widget,
            _("Move to X0 Y0 in the current WCS?") + "\n\n" + _("Jog Step is ignored."),
            "printer.gcode.script",
            {"script": script},
        )

    def home(self, widget):
        if "delta" in self._printer.get_config_section("printer")["kinematics"]:
            self._screen._send_action(widget, "printer.gcode.script", {"script": "G28"})
            return
        name = "homing"
        disname = self._screen._config.get_menu_name("move", name)
        menuitems = self._screen._config.get_menu_items("move", name)
        self._screen.show_panel("menu", disname, items=menuitems)
