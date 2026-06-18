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

        status = Gtk.Grid(column_homogeneous=True, hexpand=True)
        status.set_column_spacing(8)
        status.set_row_spacing(8)
        for index, name in enumerate(("wcs", "mode", "velocity", "homed")):
            status.attach(self.labels[name], index % 2, index // 2, 1, 1)

        axes = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True)
        axes.set_column_spacing(10)
        axes.set_row_spacing(10)
        for index, axis in enumerate(self.axes):
            card = self._axis_card(axis)
            if self._screen.vertical_mode:
                axes.attach(card, 0, index, 1, 1)
            else:
                axes.attach(card, index, 0, 1, 1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.pack_start(status, False, False, 0)
        content.pack_start(axes, True, True, 0)
        self.content.add(content)

    def _axis_card(self, axis):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.set_hexpand(True)
        card.set_vexpand(True)
        card.get_style_context().add_class("cnc-dro-card")
        card.get_style_context().add_class(f"cnc-dro-card-{axis.lower()}")

        header = Gtk.Box(spacing=6)
        self.labels[f"axis_{axis}"] = Gtk.Label(label=axis, xalign=0)
        self.labels[f"axis_{axis}"].get_style_context().add_class("cnc-dro-axis")
        self.labels[f"homed_{axis}"] = Gtk.Label(label="OPEN", xalign=1)
        self.labels[f"homed_{axis}"].get_style_context().add_class("cnc-dro-homed")
        header.pack_start(self.labels[f"axis_{axis}"], True, True, 0)
        header.pack_end(self.labels[f"homed_{axis}"], False, False, 0)
        card.pack_start(header, False, False, 0)

        for field, heading in (("machine", "MACHINE"), ("work", "WORK"), ("offset", "OFFSET")):
            label = Gtk.Label(label=heading, xalign=0)
            label.get_style_context().add_class("cnc-dro-field")
            card.pack_start(label, False, False, 0)

            self.labels[f"{field}_{axis}"] = Gtk.Label(label="--", xalign=0)
            self.labels[f"{field}_{axis}"].get_style_context().add_class("cnc-dro-value")
            card.pack_start(self.labels[f"{field}_{axis}"], False, False, 0)

        self.labels[f"limits_{axis}"] = Gtk.Label(label="Min --    Max --", xalign=0)
        self.labels[f"limits_{axis}"].get_style_context().add_class("cnc-dro-limits")
        card.pack_end(self.labels[f"limits_{axis}"], False, False, 0)
        return card

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

            self.labels[f"homed_{axis}"].set_label("HOMED" if homed else "OPEN")
            homed_context = self.labels[f"homed_{axis}"].get_style_context()
            if homed:
                homed_context.add_class("cnc-dro-homed-active")
            else:
                homed_context.remove_class("cnc-dro-homed-active")
            self.labels[f"machine_{axis}"].set_label(f"{machine_position:.{digits}f}")
            self.labels[f"work_{axis}"].set_label(f"{work_position:.{digits}f}")
            self.labels[f"offset_{axis}"].set_label(f"{offset:+.{digits}f}")
            self.labels[f"limits_{axis}"].set_label(
                f"Min {self._position(minimum, index):.{digits}f}    "
                f"Max {self._position(maximum, index):.{digits}f}"
            )
