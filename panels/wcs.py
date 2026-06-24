import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ks_includes.screen_panel import ScreenPanel


class MachineMap(Gtk.DrawingArea):
    padding = 28

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.minimum = [0.0, 0.0]
        self.maximum = [1.0, 1.0]
        self.tool = [0.0, 0.0]
        self.offsets = {}
        self.active_wcs = "G54"
        self.snap = 10.0
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_size_request(280, 280)
        self.connect("draw", self.draw_map)
        self.gesture = Gtk.GestureMultiPress.new(self)
        self.gesture.set_button(1)
        self.gesture.connect("released", self.on_tap)

    def update_state(self, minimum, maximum, tool, offsets, active_wcs):
        self.minimum = self._xy(minimum, self.minimum)
        self.maximum = self._xy(maximum, self.maximum)
        self.tool = self._xy(tool, self.tool)
        self.offsets = offsets if isinstance(offsets, dict) else {}
        self.active_wcs = active_wcs
        self.queue_draw()

    def set_snap(self, snap):
        self.snap = float(snap)
        self.queue_draw()

    @staticmethod
    def _xy(values, fallback):
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            return list(fallback)
        return [float(values[0]), float(values[1])]

    def _plot(self):
        width = max(self.get_allocated_width(), 1)
        height = max(self.get_allocated_height(), 1)
        available_width = max(width - self.padding * 2, 1)
        available_height = max(height - self.padding * 2, 1)
        range_x = max(self.maximum[0] - self.minimum[0], 1)
        range_y = max(self.maximum[1] - self.minimum[1], 1)
        scale = min(available_width / range_x, available_height / range_y)
        plot_width = range_x * scale
        plot_height = range_y * scale
        left = (width - plot_width) / 2
        top = (height - plot_height) / 2
        return left, top, plot_width, plot_height, scale

    def to_screen(self, x, y):
        left, top, _, plot_height, scale = self._plot()
        return (
            left + (x - self.minimum[0]) * scale,
            top + plot_height - (y - self.minimum[1]) * scale,
        )

    def to_machine(self, screen_x, screen_y):
        left, top, plot_width, plot_height, scale = self._plot()
        x = self.minimum[0] + (screen_x - left) / scale
        y = self.minimum[1] + (top + plot_height - screen_y) / scale
        x = min(max(x, self.minimum[0]), self.maximum[0])
        y = min(max(y, self.minimum[1]), self.maximum[1])
        if self.snap > 0:
            x = round((x - self.minimum[0]) / self.snap) * self.snap + self.minimum[0]
            y = round((y - self.minimum[1]) / self.snap) * self.snap + self.minimum[1]
            x = min(max(x, self.minimum[0]), self.maximum[0])
            y = min(max(y, self.minimum[1]), self.maximum[1])
        return x, y

    def on_tap(self, gesture, presses, event_x, event_y):
        if presses != 1:
            return
        left, top, plot_width, plot_height, _ = self._plot()
        if not (
            left <= event_x <= left + plot_width
            and top <= event_y <= top + plot_height
        ):
            return
        machine_x, machine_y = self.to_machine(event_x, event_y)
        logging.info(
            "WCS map tap: screen=(%.1f, %.1f) machine=(%.3f, %.3f)",
            event_x,
            event_y,
            machine_x,
            machine_y,
        )
        self.panel.move_to_machine_xy(machine_x, machine_y)

    def draw_map(self, widget, ctx):
        left, top, plot_width, plot_height, scale = self._plot()
        ctx.set_source_rgb(0.08, 0.10, 0.11)
        ctx.rectangle(left, top, plot_width, plot_height)
        ctx.fill_preserve()
        ctx.set_source_rgb(0.20, 0.55, 0.78)
        ctx.set_line_width(2)
        ctx.stroke()

        self._draw_grid(ctx, left, top, plot_width, plot_height, scale)
        self._draw_origins(ctx)
        self._draw_tool(ctx)
        self._draw_labels(ctx, left, top, plot_width, plot_height)
        return False

    def _draw_grid(self, ctx, left, top, plot_width, plot_height, scale):
        step = self.snap if self.snap > 0 else 10
        if step * scale < 12:
            step *= max(1, round(12 / max(step * scale, 1)))
        ctx.set_source_rgba(1, 1, 1, 0.08)
        ctx.set_line_width(1)

        x = self.minimum[0] + step
        while x < self.maximum[0]:
            screen_x, _ = self.to_screen(x, self.minimum[1])
            ctx.move_to(screen_x, top)
            ctx.line_to(screen_x, top + plot_height)
            x += step

        y = self.minimum[1] + step
        while y < self.maximum[1]:
            _, screen_y = self.to_screen(self.minimum[0], y)
            ctx.move_to(left, screen_y)
            ctx.line_to(left + plot_width, screen_y)
            y += step
        ctx.stroke()

    def _draw_origins(self, ctx):
        colors = (
            (0.93, 0.40, 0.00),
            (0.69, 0.00, 0.50),
            (0.00, 0.58, 0.52),
            (0.65, 0.88, 0.00),
            (0.25, 0.60, 0.90),
            (0.85, 0.35, 0.40),
        )
        for index, name in enumerate(self.panel.wcs_names):
            values = self.offsets.get(name, ())
            if not isinstance(values, (list, tuple)) or len(values) < 2:
                continue
            x, y = self.to_screen(float(values[0]), float(values[1]))
            color = colors[index]
            ctx.set_source_rgb(*color)
            ctx.set_line_width(3 if name == self.active_wcs else 1.5)
            ctx.move_to(x - 7, y)
            ctx.line_to(x + 7, y)
            ctx.move_to(x, y - 7)
            ctx.line_to(x, y + 7)
            ctx.stroke()

    def _draw_tool(self, ctx):
        x, y = self.to_screen(*self.tool)
        ctx.set_source_rgb(1, 1, 1)
        ctx.arc(x, y, 5, 0, 6.283)
        ctx.fill_preserve()
        ctx.set_source_rgb(0.20, 0.55, 0.78)
        ctx.set_line_width(2)
        ctx.stroke()

    def _draw_labels(self, ctx, left, top, plot_width, plot_height):
        ctx.set_source_rgba(1, 1, 1, 0.65)
        ctx.set_font_size(12)
        ctx.move_to(left, top + plot_height + 18)
        ctx.show_text(f"X {self.minimum[0]:.0f}")
        ctx.move_to(left + plot_width - 42, top + plot_height + 18)
        ctx.show_text(f"{self.maximum[0]:.0f}")
        ctx.move_to(max(left - 26, 0), top + 10)
        ctx.show_text(f"{self.maximum[1]:.0f}")
        ctx.move_to(max(left - 18, 0), top + plot_height)
        ctx.show_text(f"{self.minimum[1]:.0f}")


class Panel(ScreenPanel):
    wcs_names = ("G54", "G55", "G56", "G57", "G58", "G59")
    axes = ("X", "Y", "Z")

    def __init__(self, screen, title):
        super().__init__(screen, title or "WCS & Offsets")
        self.buttons = {}

        self.labels["active"] = self._status_label("Active G54")
        self.labels["position"] = self._status_label("Work X --  Y --  Z --")
        machine_button = self._gtk.Button(label="G53", style="color4")
        machine_button.connect("clicked", self.select_machine_coordinates)
        machine_button.get_style_context().add_class("buttons_slim")
        self.buttons["G53"] = machine_button

        status = Gtk.Grid(column_homogeneous=True, hexpand=True)
        status.set_column_spacing(8)
        status.attach(self.labels["active"], 0, 0, 1, 1)
        status.attach(self.labels["position"], 1, 0, 1, 1)
        status.attach(machine_button, 2, 0, 1, 1)

        self.machine_map = MachineMap(self)

        snap_grid = Gtk.Grid(column_homogeneous=True)
        for index, snap in enumerate((1, 5, 10, 25)):
            button = self._gtk.Button(label=f"{snap} mm")
            button.connect("clicked", self.change_snap, snap)
            button.get_style_context().add_class("horizontal_togglebuttons")
            if snap == 10:
                button.get_style_context().add_class("horizontal_togglebuttons_active")
            self.buttons[f"snap_{snap}"] = button
            snap_grid.attach(button, index, 0, 1, 1)

        map_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        map_box.pack_start(self.machine_map, True, True, 0)
        map_box.pack_end(snap_grid, False, False, 0)

        selector = Gtk.Grid(column_homogeneous=True, row_homogeneous=True)
        selector.set_column_spacing(8)
        selector.set_row_spacing(8)
        for index, name in enumerate(self.wcs_names):
            button = self._gtk.Button(label=name, style=f"color{index % 4 + 1}")
            button.connect("clicked", self.select_wcs, name)
            button.get_style_context().add_class("cnc-wcs-button")
            self.buttons[name] = button

            offset = Gtk.Label(label="X 0.000\nY 0.000\nZ 0.000")
            offset.set_xalign(0)
            offset.get_style_context().add_class("cnc-wcs-offset")
            self.labels[f"offset_{name}"] = offset

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.get_style_context().add_class("cnc-wcs-card")
            card.pack_start(button, False, False, 0)
            card.pack_start(offset, True, True, 0)

            columns = 2 if self._screen.vertical_mode else 3
            selector.attach(card, index % columns, index // columns, 1, 1)

        zero_grid = Gtk.Grid(column_homogeneous=True)
        zero_grid.set_column_spacing(8)
        for index, axis in enumerate((*self.axes, "ALL")):
            label = f"Zero {axis.title()}" if axis == "ALL" else f"Zero {axis}"
            button = self._gtk.Button("hashtag", label, f"color{index % 4 + 1}")
            button.connect("clicked", self.confirm_zero, axis)
            button.get_style_context().add_class("buttons_slim")
            self.buttons[f"zero_{axis}"] = button
            zero_grid.attach(button, index, 0, 1, 1)

        workspace = Gtk.Grid(hexpand=True, vexpand=True)
        workspace.set_column_spacing(10)
        workspace.set_row_spacing(10)
        if self._screen.vertical_mode:
            workspace.attach(map_box, 0, 0, 1, 1)
            workspace.attach(selector, 0, 1, 1, 1)
        else:
            workspace.attach(map_box, 0, 0, 1, 1)
            workspace.attach(selector, 1, 0, 2, 1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.pack_start(status, False, False, 0)
        content.pack_start(workspace, True, True, 0)
        content.pack_end(zero_grid, False, False, 0)
        self.content.add(content)

    @staticmethod
    def _status_label(text):
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("cnc-status")
        return label

    @staticmethod
    def _values(values):
        values = values if isinstance(values, (list, tuple)) else ()
        return [float(values[index]) if len(values) > index else 0.0 for index in range(3)]

    def process_update(self, action, data):
        if action != "notify_status_update":
            return

        state = self._printer.get_stat("work_coordinate_systems") or {}
        active = state.get("active_wcs", "G54")
        machine_mode = bool(state.get("machine_mode"))
        offsets = state.get("wcs", {})
        work_position = self._values(self._printer.get_stat("gcode_move", "gcode_position"))
        minimum = self._printer.get_stat("toolhead", "axis_minimum")
        maximum = self._printer.get_stat("toolhead", "axis_maximum")
        tool_position = self._printer.get_stat("motion_report", "live_position")
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        xyz_homed = all(axis in homed_axes for axis in ("x", "y", "z"))
        running = self._printer.state in {"printing", "paused"}

        self.labels["active"].set_label(f"Active {'G53' if machine_mode else active}")
        self.labels["position"].set_label(
            f"Work X {work_position[0]:.2f}  Y {work_position[1]:.2f}  "
            f"Z {work_position[2]:.3f}"
        )
        self.machine_map.update_state(minimum, maximum, tool_position, offsets, active)

        for name in self.wcs_names:
            x, y, z = self._values(offsets.get(name))
            self.labels[f"offset_{name}"].set_label(
                f"X {x:+.3f}\nY {y:+.3f}\nZ {z:+.3f}"
            )
            context = self.buttons[name].get_style_context()
            if name == active and not machine_mode:
                context.add_class("cnc-wcs-active")
            else:
                context.remove_class("cnc-wcs-active")
            self.buttons[name].set_sensitive(not running and xyz_homed)
        if machine_mode:
            self.buttons["G53"].get_style_context().add_class("cnc-wcs-active")
        else:
            self.buttons["G53"].get_style_context().remove_class("cnc-wcs-active")
        self.buttons["G53"].set_sensitive(not running and xyz_homed)

        for axis in self.axes:
            self.buttons[f"zero_{axis}"].set_sensitive(
                not running and not machine_mode and xyz_homed
            )
        self.buttons["zero_ALL"].set_sensitive(
            not running and not machine_mode and xyz_homed
        )

    def change_snap(self, widget, snap):
        for value in (1, 5, 10, 25):
            self.buttons[f"snap_{value}"].get_style_context().remove_class(
                "horizontal_togglebuttons_active"
            )
        widget.get_style_context().add_class("horizontal_togglebuttons_active")
        self.machine_map.set_snap(snap)

    def move_to_machine_xy(self, machine_x, machine_y):
        if self._printer.state in {"printing", "paused"}:
            self._screen.show_popup_message("XY map is locked while a job is running")
            return
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        if not all(axis in homed_axes for axis in ("x", "y", "z")):
            self._screen.show_popup_message("Home XYZ before using the WCS map")
            return

        state = self._printer.get_stat("work_coordinate_systems") or {}
        active = state.get("active_wcs", "G54")
        if state.get("machine_mode"):
            target_x = machine_x
            target_y = machine_y
        else:
            offset = self._values(state.get("wcs", {}).get(active))
            target_x = machine_x - offset[0]
            target_y = machine_y - offset[1]

        printer_cfg = self._printer.get_config_section("printer")
        max_velocity = max(int(float(printer_cfg["max_velocity"])), 1)
        speed = (
            None if self.ks_printer_cfg is None
            else self.ks_printer_cfg.getint("move_speed_xy", None)
        )
        if speed is None:
            speed = self._config.get_main_config().getint("move_speed_xy", max_velocity)
        feedrate = 60 * min(max(1, speed), max_velocity)

        script = (
            "SAVE_GCODE_STATE NAME=_ks_cnc_map_move\n"
            "G90\n"
            f"G1 X{target_x:.4f} Y{target_y:.4f} F{feedrate}\n"
            "RESTORE_GCODE_STATE NAME=_ks_cnc_map_move"
        )
        logging.info(
            "WCS map move: mode=%s machine=(%.3f, %.3f) target=(%.3f, %.3f) feed=%d",
            "G53" if state.get("machine_mode") else active,
            machine_x,
            machine_y,
            target_x,
            target_y,
            feedrate,
        )
        self._screen._send_action(None, "printer.gcode.script", {"script": script})

    def select_wcs(self, widget, name):
        if self._printer.state in {"printing", "paused"}:
            self._screen.show_popup_message("WCS cannot be changed while a job is running")
            return
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        if not all(axis in homed_axes for axis in ("x", "y", "z")):
            self._screen.show_popup_message("Home XYZ before changing WCS")
            return
        state = self._printer.get_stat("work_coordinate_systems") or {}
        if name == state.get("active_wcs") and not state.get("machine_mode"):
            return
        self._screen._send_action(
            widget,
            "printer.gcode.script",
            {"script": name},
        )

    def select_machine_coordinates(self, widget):
        if self._printer.state in {"printing", "paused"}:
            self._screen.show_popup_message("WCS cannot be changed while a job is running")
            return
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        if not all(axis in homed_axes for axis in ("x", "y", "z")):
            self._screen.show_popup_message("Home XYZ before changing WCS")
            return
        state = self._printer.get_stat("work_coordinate_systems") or {}
        if state.get("machine_mode"):
            return
        self._screen._send_action(
            widget,
            "printer.gcode.script",
            {"script": "G53"},
        )

    def confirm_zero(self, widget, axis):
        state = self._printer.get_stat("work_coordinate_systems") or {}
        active = state.get("active_wcs", "G54")
        active_p = self.wcs_names.index(active) + 1 if active in self.wcs_names else 1
        if state.get("machine_mode"):
            self._screen.show_popup_message("Cannot set a work zero while G53 is active")
            return

        requested_axes = self.axes if axis == "ALL" else (axis,)
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        if not all(item in homed_axes for item in ("x", "y", "z")):
            self._screen.show_popup_message("Home XYZ before setting a work zero")
            return

        arguments = " ".join(f"{item}0" for item in requested_axes)
        script = f"G10 L20 P{active_p} {arguments}"
        axis_label = "XYZ" if axis == "ALL" else axis
        self._screen._confirm_send_action(
            widget,
            f"Set {axis_label} work zero for <b>{active}</b> at the current position?",
            "printer.gcode.script",
            {"script": script},
        )
