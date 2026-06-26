import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from ks_includes.screen_panel import ScreenPanel


class SurfaceMap(Gtk.DrawingArea):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.set_size_request(260, 170)
        self.connect("draw", self.draw_map)

    def draw_map(self, widget, ctx):
        result = self.panel.surface_result()
        width = max(self.get_allocated_width(), 1)
        height = max(self.get_allocated_height(), 1)
        ctx.set_source_rgb(0.07, 0.09, 0.10)
        ctx.rectangle(0, 0, width, height)
        ctx.fill()
        ctx.set_source_rgba(1, 1, 1, 0.16)
        ctx.rectangle(8, 8, width - 16, height - 16)
        ctx.stroke()
        if not result:
            self._text(ctx, width / 2 - 58, height / 2, "No surface map", 16, 0.65)
            return False

        points = result.get("points") or []
        if not points:
            return False
        bounds = result.get("bounds") or {}
        x_min = float(bounds.get("x_min", min(point["x"] for point in points)))
        x_max = float(bounds.get("x_max", max(point["x"] for point in points)))
        y_min = float(bounds.get("y_min", min(point["y"] for point in points)))
        y_max = float(bounds.get("y_max", max(point["y"] for point in points)))
        z_values = [float(point["z"]) for point in points]
        z_min = min(z_values)
        z_max = max(z_values)
        z_range = max(z_max - z_min, 0.000001)

        label_size = min(max(width * 0.014, 12), 15)
        marker_radius = min(max(width * 0.006, 5), 7)
        frame_left = 22
        frame_top = 14
        frame_w = width - frame_left * 2
        frame_h = height - frame_top * 2
        label_pad_x = min(max(width * 0.09, 58), 86)
        label_pad_y = min(max(height * 0.14, 24), 32)
        left = frame_left + label_pad_x
        top = frame_top + label_pad_y
        plot_w = max(frame_w - label_pad_x * 2, 1)
        plot_h = max(frame_h - label_pad_y * 2, 1)
        ctx.set_source_rgba(1, 1, 1, 0.10)
        ctx.rectangle(frame_left, frame_top, frame_w, frame_h)
        ctx.stroke()

        by_name = {point.get("name"): point for point in points}
        if result.get("pattern") == "CROSS_5":
            self._line(ctx, by_name, "FRONT", "REAR", left, top, plot_w, plot_h, x_min, x_max, y_min, y_max)
            self._line(ctx, by_name, "LEFT", "RIGHT", left, top, plot_w, plot_h, x_min, x_max, y_min, y_max)
        else:
            for a, b in (("FL", "FR"), ("FR", "RR"), ("RR", "RL"), ("RL", "FL")):
                self._line(ctx, by_name, a, b, left, top, plot_w, plot_h, x_min, x_max, y_min, y_max)

        for point in points:
            x, y = self._plot(point["x"], point["y"], left, top, plot_w, plot_h, x_min, x_max, y_min, y_max)
            ratio = (float(point["z"]) - z_min) / z_range
            color = (
                0.28 + 0.72 * ratio,
                0.55 - 0.25 * ratio,
                1.0 - 0.78 * ratio,
            )
            ctx.set_source_rgb(*color)
            ctx.arc(x, y, marker_radius, 0, 6.283)
            ctx.fill()
            self._point_label(
                ctx,
                x,
                y,
                point.get("name", ""),
                f"{float(point['z']):+.3f}",
                color,
                label_size,
                width,
                height,
                left + plot_w / 2,
                top + plot_h / 2,
                result.get("pattern") == "CROSS_5",
            )
        return False

    def _plot(self, x, y, left, top, width, height, x_min, x_max, y_min, y_max):
        span_x = max(x_max - x_min, 0.000001)
        span_y = max(y_max - y_min, 0.000001)
        return (
            left + (float(x) - x_min) / span_x * width,
            top + height - (float(y) - y_min) / span_y * height,
        )

    def _line(self, ctx, by_name, a, b, left, top, width, height, x_min, x_max, y_min, y_max):
        if a not in by_name or b not in by_name:
            return
        ax, ay = self._plot(by_name[a]["x"], by_name[a]["y"], left, top, width, height, x_min, x_max, y_min, y_max)
        bx, by = self._plot(by_name[b]["x"], by_name[b]["y"], left, top, width, height, x_min, x_max, y_min, y_max)
        ctx.set_source_rgba(1, 1, 1, 0.28)
        ctx.set_line_width(2)
        ctx.move_to(ax, ay)
        ctx.line_to(bx, by)
        ctx.stroke()

    @staticmethod
    def _text(ctx, x, y, text, size, alpha=1.0, dark=False):
        ctx.set_source_rgba(0, 0, 0, alpha) if dark else ctx.set_source_rgba(1, 1, 1, alpha)
        ctx.set_font_size(size)
        ctx.move_to(x, y)
        ctx.show_text(text)

    @staticmethod
    def _center_text(ctx, x, y, text, size, alpha=1.0, dark=False):
        ctx.set_source_rgba(0, 0, 0, alpha) if dark else ctx.set_source_rgba(1, 1, 1, alpha)
        ctx.set_font_size(size)
        extents = ctx.text_extents(str(text))
        ctx.move_to(
            x - extents.width / 2 - extents.x_bearing,
            y - extents.height / 2 - extents.y_bearing,
        )
        ctx.show_text(str(text))

    def _point_label(self, ctx, x, y, name, value, color, label_size, width, height, center_x, center_y, cross_mode=False):
        text = f"{name} {value}"
        padding_x = 11
        padding_y = 6
        offset = 20
        ctx.set_font_size(label_size)
        extents = ctx.text_extents(text)
        box_w = max(extents.width + padding_x * 2, 96)
        box_h = extents.height + padding_y * 2

        dx = 0
        dy = 0
        horizontal_bias = x - center_x
        vertical_bias = y - center_y

        if cross_mode and name in {"REAR", "CENTER", "FRONT"}:
            dy = {"REAR": -34, "CENTER": 0, "FRONT": 34}[name]
        elif abs(horizontal_bias) > box_w / 2:
            dx = offset if horizontal_bias < 0 else -offset
            if abs(vertical_bias) > box_h:
                dy = offset if vertical_bias < 0 else -offset
        else:
            if abs(vertical_bias) > box_h:
                dy = offset if vertical_bias < 0 else -offset
            else:
                dy = -offset if vertical_bias >= 0 else offset

        box_x = min(max(x + dx - box_w / 2, 12), width - box_w - 12)
        box_y = min(max(y + dy - box_h / 2, 12), height - box_h - 12)

        ctx.set_source_rgba(0.09, 0.13, 0.15, 0.94)
        self._rounded_rect(ctx, box_x, box_y, box_w, box_h, 8)
        ctx.fill()
        ctx.set_source_rgba(color[0], color[1], color[2], 0.95)
        ctx.set_line_width(2)
        self._rounded_rect(ctx, box_x, box_y, box_w, box_h, 8)
        ctx.stroke()

        self._center_text(
            ctx,
            box_x + box_w / 2,
            box_y + box_h / 2,
            text,
            label_size,
            1.0,
            dark=False,
        )

    @staticmethod
    def _rounded_rect(ctx, x, y, width, height, radius):
        radius = min(radius, width / 2, height / 2)
        ctx.new_sub_path()
        ctx.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        ctx.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        ctx.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        ctx.close_path()


class Panel(ScreenPanel):
    def __init__(self, screen, title):
        super().__init__(screen, title or "Surface Measure")
        self.coord = "WCS"
        self.pattern = "CORNERS_4"
        self.buttons = {}
        self.entries = {}

        self.labels["summary"] = self._status_label("No surface map")
        self.labels["detail"] = Gtk.Label(label="Measure stock or machine area. Report only; no compensation.", xalign=0, wrap=True)
        self.labels["detail"].get_style_context().add_class("cnc-probe-detail")

        options = Gtk.Grid(column_homogeneous=True)
        options.set_column_spacing(8)
        for index, (key, label) in enumerate((("WCS", "Stock / WCS"), ("MACHINE", "Machine"))):
            button = self._gtk.Button(label=label, style=f"color{index + 1}")
            button.get_style_context().add_class("buttons_slim")
            button.connect("clicked", self.set_coord, key)
            self.buttons[f"coord_{key}"] = button
            options.attach(button, index, 0, 1, 1)
        for index, (key, label) in enumerate((("CORNERS_4", "Corners 4"), ("CROSS_5", "Cross 5"))):
            button = self._gtk.Button(label=label, style=f"color{index + 3}")
            button.get_style_context().add_class("buttons_slim")
            button.connect("clicked", self.set_pattern, key)
            self.buttons[f"pattern_{key}"] = button
            options.attach(button, index + 2, 0, 1, 1)

        fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        fields.get_style_context().add_class("cnc-surface-fields")
        fields.pack_start(self._field_row("Size", ("WIDTH", "HEIGHT", "MARGIN")), False, False, 0)
        fields.pack_start(
            self._field_row("Bounds override", ("X_MIN", "X_MAX", "Y_MIN", "Y_MAX")),
            False,
            False,
            0,
        )

        actions = Gtk.Grid(column_homogeneous=True)
        actions.set_column_spacing(8)
        self.buttons["measure"] = self._gtk.Button(label="Measure", style="color4")
        self.buttons["measure"].get_style_context().add_class("cnc-probe-action")
        self.buttons["measure"].connect("clicked", self.measure)
        actions.attach(self.buttons["measure"], 0, 0, 1, 1)
        self.buttons["refresh"] = self._gtk.Button(label="Refresh Map", style="color3")
        self.buttons["refresh"].get_style_context().add_class("cnc-probe-action")
        self.buttons["refresh"].connect("clicked", self.update_status)
        actions.attach(self.buttons["refresh"], 1, 0, 1, 1)

        self.map = SurfaceMap(self)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.pack_start(self.labels["summary"], False, False, 0)
        content.pack_start(self.labels["detail"], False, False, 0)
        content.pack_start(self.map, False, False, 0)
        content.pack_start(options, False, False, 0)
        content.pack_start(actions, False, False, 0)
        content.pack_start(fields, False, False, 0)
        scroll = self._gtk.ScrolledWindow()
        scroll.get_style_context().add_class("gcode-list-scroll")
        scroll.add(content)
        self.content.add(scroll)
        self.update_toggles()

    @staticmethod
    def _status_label(text):
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("cnc-status")
        return label

    def _field_row(self, title, names):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        label = Gtk.Label(label=title, xalign=0)
        label.get_style_context().add_class("cnc-probe-detail")
        grid = Gtk.Grid(column_homogeneous=True)
        grid.set_column_spacing(8)
        columns = 2 if self._screen.vertical_mode else len(names)
        for index, name in enumerate(names):
            entry = Gtk.Entry(placeholder_text=name.replace("_", " ").title())
            entry.set_input_purpose(Gtk.InputPurpose.NUMBER)
            if name in {"WIDTH", "HEIGHT"}:
                entry.set_width_chars(7)
                entry.set_max_width_chars(8)
            entry.connect("touch-event", self.show_keyboard)
            entry.connect("button-press-event", self.show_keyboard)
            entry.connect("focus-out-event", self._screen.remove_keyboard)
            self.entries[name] = entry
            grid.attach(entry, index % columns, index // columns, 1, 1)
        row.pack_start(label, False, False, 0)
        row.pack_start(grid, False, False, 0)
        return row

    def activate(self):
        self.update_status()

    def process_update(self, action, data):
        if action == "notify_status_update" and "touch_probe" in data:
            self.update_status()
        elif action == "notify_gcode_response" and "Surface tilt" in str(data):
            GLib.timeout_add_seconds(1, self.update_status)

    def surface_result(self):
        status = self._printer.get_stat("touch_probe") or {}
        return status.get("surface_result")

    def set_coord(self, widget, coord):
        self.coord = coord
        self.update_toggles()

    def set_pattern(self, widget, pattern):
        self.pattern = pattern
        self.update_toggles()

    def update_toggles(self):
        for key in ("WCS", "MACHINE"):
            context = self.buttons[f"coord_{key}"].get_style_context()
            if key == self.coord:
                context.add_class("button_active")
            else:
                context.remove_class("button_active")
        for key in ("CORNERS_4", "CROSS_5"):
            context = self.buttons[f"pattern_{key}"].get_style_context()
            if key == self.pattern:
                context.add_class("button_active")
            else:
                context.remove_class("button_active")
        self.entries["WIDTH"].set_sensitive(self.coord == "WCS")
        self.entries["HEIGHT"].set_sensitive(self.coord == "WCS")
        self.entries["WIDTH"].set_placeholder_text("Stock width")
        self.entries["HEIGHT"].set_placeholder_text("Stock height")
        self.entries["MARGIN"].set_placeholder_text(
            "Margin 5" if self.coord == "WCS" else "Margin 10"
        )

    def show_keyboard(self, entry, event):
        self._screen.show_keyboard(entry, event)

    def _entry(self, name):
        value = self.entries[name].get_text().strip()
        return value if value else None

    def _bounds_complete(self):
        return all(self._entry(name) is not None for name in ("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"))

    def build_script(self):
        parts = ["MEASURE_SURFACE_TILT", f"COORD={self.coord}", f"PATTERN={self.pattern}"]
        margin = self._entry("MARGIN")
        if margin is not None:
            parts.append(f"MARGIN={margin}")
        if self.coord == "WCS":
            width = self._entry("WIDTH")
            height = self._entry("HEIGHT")
            if width and height:
                parts.extend((f"WIDTH={width}", f"HEIGHT={height}"))
            elif self._bounds_complete():
                parts.extend(f"{name}={self._entry(name)}" for name in ("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"))
            else:
                self._screen.show_popup_message("Stock measuring needs Width/Height or XY bounds")
                return None
        elif self._bounds_complete():
            parts.extend(f"{name}={self._entry(name)}" for name in ("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"))
        return " ".join(parts)

    def measure(self, widget):
        script = self.build_script()
        if not script:
            return
        self.confirm_measure(script)

    def confirm_measure(self, script):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_size_request(min(int(self._screen.width * 0.78), 780), -1)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        heading = Gtk.Label(
            label="<big><b>Measure Surface Tilt</b></big>",
            xalign=0,
            use_markup=True,
        )
        badge = Gtk.Label(label="Motion only · no compensation", xalign=0)
        badge.get_style_context().add_class("cnc-confirm-badge")
        note = Gtk.Label(
            label="This will probe Z at the selected surface points and only report the map.",
            xalign=0,
            wrap=True,
        )
        note.get_style_context().add_class("cnc-probe-detail")
        checklist = Gtk.Label(
            label="✓ Spindle off\n✓ Probe connected\n✓ Surface points are clear",
            xalign=0,
        )
        checklist.get_style_context().add_class("cnc-confirm-checklist")
        command = Gtk.Label(label=f"<tt>{script}</tt>", xalign=0, wrap=True, use_markup=True)
        command.get_style_context().add_class("cnc-confirm-script")
        content.pack_start(heading, False, False, 0)
        content.pack_start(badge, False, False, 0)
        content.pack_start(note, False, False, 0)
        content.pack_start(checklist, False, False, 0)
        content.pack_start(command, False, False, 0)
        wrapper = Gtk.Alignment.new(0.5, 0.5, 0, 0)
        wrapper.set_vexpand(True)
        wrapper.add(content)
        buttons = [
            {"name": "Run", "response": Gtk.ResponseType.OK, "style": "dialog-info"},
            {"name": "Cancel", "response": Gtk.ResponseType.CANCEL, "style": "dialog-error"},
        ]
        if self._screen.confirm is not None:
            self._gtk.remove_dialog(self._screen.confirm)
        self._screen.confirm = self._gtk.Dialog(
            "Measure Surface", buttons, wrapper, self.run_measure, script
        )

    def run_measure(self, dialog, response_id, script):
        self._gtk.remove_dialog(dialog)
        if response_id == Gtk.ResponseType.OK:
            self._screen._send_action(None, "printer.gcode.script", {"script": script})
            GLib.timeout_add_seconds(2, self.update_status)
            GLib.timeout_add_seconds(6, self.update_status)

    def update_status(self, *args):
        result = self.surface_result()
        if not result:
            self.labels["summary"].set_label("No surface map")
            self.labels["detail"].set_label("Measure stock or machine area. Report only; no compensation.")
            self.map.queue_draw()
            return
        summary = result.get("summary") or {}
        self.labels["summary"].set_label(
            "Range %.3f mm" % float(summary.get("range", 0))
        )
        self.labels["detail"].set_label(
            "%s · %s · High %s · Low %s"
            % (
                str(result.get("coord", "--")).upper(),
                result.get("pattern", "--"),
                summary.get("high_point", "--"),
                summary.get("low_point", "--"),
            )
        )
        self.map.queue_draw()
