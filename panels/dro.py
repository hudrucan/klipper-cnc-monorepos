import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ks_includes.screen_panel import ScreenPanel


class Panel(ScreenPanel):
    axes = ("X", "Y", "Z")

    def __init__(self, screen, title):
        super().__init__(screen, title or "DRO")

        self.labels["wcs"] = self._status_label("WCS --")
        self.labels["mode"] = self._status_label("--")
        self.labels["velocity"] = self._status_label("0.00 mm/s")
        self.labels["homed"] = self._status_label("Homed: none")

        status = Gtk.Box(spacing=8, hexpand=True)
        for name in ("wcs", "mode", "velocity", "homed"):
            status.pack_start(self.labels[name], True, True, 0)

        grid = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True)
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        for column, heading in enumerate(("", "Machine", "Work", "Offset", "Limits")):
            label = Gtk.Label(label=heading)
            label.get_style_context().add_class("cnc-dro-heading")
            grid.attach(label, column, 0, 1, 1)

        for row, axis in enumerate(self.axes, start=1):
            self.labels[f"axis_{axis}"] = Gtk.Label(label=axis)
            self.labels[f"axis_{axis}"].get_style_context().add_class("cnc-dro-axis")
            grid.attach(self.labels[f"axis_{axis}"], 0, row, 1, 1)

            for column, field in enumerate(("machine", "work", "offset", "limits"), start=1):
                self.labels[f"{field}_{axis}"] = Gtk.Label(label="--")
                self.labels[f"{field}_{axis}"].get_style_context().add_class("cnc-dro-value")
                grid.attach(self.labels[f"{field}_{axis}"], column, row, 1, 1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.pack_start(status, False, False, 0)
        content.pack_start(grid, True, True, 0)
        self.content.add(content)

    @staticmethod
    def _status_label(text):
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("cnc-status")
        return label

    @staticmethod
    def _position(data, key):
        values = data if isinstance(data, (list, tuple)) else ()
        return float(values[key]) if len(values) > key else 0.0

    def process_update(self, action, data):
        if action != "notify_status_update":
            return

        machine = self._printer.get_stat("motion_report", "live_position")
        work = self._printer.get_stat("gcode_move", "gcode_position")
        minimum = self._printer.get_stat("toolhead", "axis_minimum")
        maximum = self._printer.get_stat("toolhead", "axis_maximum")
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""

        wcs = self._printer.get_stat("work_coordinate_systems")
        if wcs:
            active_wcs = "G53" if wcs.get("machine_mode") else wcs.get("active_wcs", "G54")
        else:
            active_wcs = "Work"
        absolute = self._printer.get_stat("gcode_move", "absolute_coordinates")
        velocity = float(self._printer.get_stat("motion_report", "live_velocity") or 0)

        self.labels["wcs"].set_label(f"WCS {active_wcs}")
        self.labels["mode"].set_label("Absolute G90" if absolute else "Relative G91")
        self.labels["velocity"].set_label(f"{velocity:.2f} mm/s")
        self.labels["homed"].set_label(f"Homed: {homed_axes.upper() or 'none'}")

        for index, axis in enumerate(self.axes):
            machine_position = self._position(machine, index)
            work_position = self._position(work, index)
            offset = machine_position - work_position
            digits = 3 if axis == "Z" else 2
            homed = axis.lower() in homed_axes

            self.labels[f"axis_{axis}"].set_label(f"{axis} {'OK' if homed else '--'}")
            self.labels[f"machine_{axis}"].set_label(f"{machine_position:.{digits}f}")
            self.labels[f"work_{axis}"].set_label(f"{work_position:.{digits}f}")
            self.labels[f"offset_{axis}"].set_label(f"{offset:+.{digits}f}")
            self.labels[f"limits_{axis}"].set_label(
                f"{self._position(minimum, index):.{digits}f} .. "
                f"{self._position(maximum, index):.{digits}f}"
            )
