import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

from ks_includes.screen_panel import ScreenPanel


class Panel(ScreenPanel):
    touch_actions = (
        ("stock_z", "Stock Z0", "FIND_SURFACE_Z SET_ZERO=1", True, "Probe stock surface and set WCS Z0"),
        ("center_xy", "Center XY", "FIND_CENTER_XY", True, "Probe X/Y edges and set center XY0"),
        ("bore", "Bore XY", "PROBE_BORE SET_ZERO=1", True, "Probe a bore and set center XY0"),
        ("query_touch", "Check", "QUERY_TOUCH_PROBE", False, "Report touch probe state"),
        ("x_min", "X Min", "FIND_EDGE_X_POS SET_ZERO=1", True, "Start outside X-min and probe toward X+ to set WCS X0"),
        ("x_max", "X Max", "FIND_EDGE_X_NEG SET_ZERO=1", True, "Start outside X-max and probe toward X- to set WCS X0"),
        ("y_min", "Y Min", "FIND_EDGE_Y_POS SET_ZERO=1", True, "Start outside Y-min and probe toward Y+ to set WCS Y0"),
        ("y_max", "Y Max", "FIND_EDGE_Y_NEG SET_ZERO=1", True, "Start outside Y-max and probe toward Y- to set WCS Y0"),
        ("center_x", "Center X", "FIND_CENTER_X", True, "Probe both X edges and set center X0"),
        ("center_y", "Center Y", "FIND_CENTER_Y", True, "Probe both Y edges and set center Y0"),
    )
    setter_actions = (
        ("apply_bit", "Apply Bit Z", "SET_BIT_Z APPLY=1", True, "Measure bit and update active WCS Z"),
        ("check_bit", "Check Bit Z", "SET_BIT_Z", True, "Measure bit and report WCS Z delta"),
        ("calibrate", "Calibrate Z", "CALIBRATE_SETTER_Z", True, "Store fixed setter height after stock Z0"),
        ("query_setter", "Check", "QUERY_TOOL_SETTER", False, "Report tool setter state"),
        ("accuracy", "Accuracy", "TOOL_SETTER_ACCURACY", True, "Probe setter repeatability"),
    )
    surface_actions = (
        ("surface", "Surface Map", "PANEL:surface_measure", False, "Measure and view surface tilt"),
        ("history", "Result History", "PANEL:probe_history", False, "Review latest probe, setter, and surface results"),
    )

    def __init__(self, screen, title):
        super().__init__(screen, title or "Probe")
        self.buttons = {}

        self.labels["state"] = self._chip("READY")
        self.labels["homed"] = self._chip("Homed: none")
        self.labels["wcs"] = self._chip("WCS --")
        chips = Gtk.Grid(column_homogeneous=True)
        chips.set_column_spacing(8)
        chips.attach(self.labels["state"], 0, 0, 1, 1)
        chips.attach(self.labels["homed"], 1, 0, 1, 1)
        chips.attach(self.labels["wcs"], 2, 0, 1, 1)

        status_grid = Gtk.Grid(column_homogeneous=True)
        status_grid.set_column_spacing(10)
        status_grid.set_row_spacing(10)
        status_grid.attach(
            self._status_card("touch", "TOUCH PROBE", "Not configured"), 0, 0, 1, 1
        )
        status_grid.attach(
            self._status_card("setter", "TOOL SETTER", "Not configured"), 1, 0, 1, 1
        )

        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        actions.pack_start(
            self._section(
                "Tool Setter",
                "Calibrate the fixed setter, check repeatability, and re-touch Z after bit changes.",
                self.setter_actions,
            ),
            False,
            False,
            0,
        )
        actions.pack_start(
            self._section(
                "Touch Probe",
                "Find stock edges, centers, bore centers, and stock Z with the spindle-mounted probe.",
                self.touch_actions,
            ),
            False,
            False,
            0,
        )
        actions.pack_start(
            self._section(
                "Surface Measure",
                "Inspect stock or machine surface tilt without changing compensation.",
                self.surface_actions,
            ),
            False,
            False,
            0,
        )

        scroll = self._gtk.ScrolledWindow()
        scroll.get_style_context().add_class("gcode-list-scroll")
        scroll.add(actions)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.pack_start(chips, False, False, 0)
        content.pack_start(status_grid, False, False, 0)
        content.pack_start(scroll, True, True, 0)
        self.content.add(content)

    @staticmethod
    def _chip(text):
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("cnc-status")
        return label

    def _status_card(self, key, heading, value):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class("cnc-probe-card")
        label = Gtk.Label(label=heading, xalign=0)
        label.get_style_context().add_class("cnc-status-heading")
        self.labels[f"{key}_value"] = Gtk.Label(label=value, xalign=0)
        self.labels[f"{key}_value"].set_ellipsize(Pango.EllipsizeMode.END)
        self.labels[f"{key}_value"].get_style_context().add_class("cnc-status-value")
        self.labels[f"{key}_detail"] = Gtk.Label(label="--", xalign=0, wrap=True)
        self.labels[f"{key}_detail"].set_lines(3)
        self.labels[f"{key}_detail"].set_ellipsize(Pango.EllipsizeMode.END)
        self.labels[f"{key}_detail"].get_style_context().add_class("cnc-probe-detail")
        card.pack_start(label, False, False, 0)
        card.pack_start(self.labels[f"{key}_value"], False, False, 0)
        card.pack_start(self.labels[f"{key}_detail"], False, False, 0)
        return card

    def _section(self, title, subtitle, actions):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("cnc-probe-section")
        heading = Gtk.Label(label=f"<b>{title}</b>", xalign=0, use_markup=True)
        heading.get_style_context().add_class("cnc-probe-heading")
        note = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        note.get_style_context().add_class("cnc-probe-detail")
        grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True)
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        columns = 2 if self._screen.vertical_mode else 3
        for index, (name, label, script, confirm, tooltip) in enumerate(actions):
            button = self._gtk.Button(None, label, f"color{index % 4 + 1}")
            button.get_style_context().add_class("buttons_slim")
            button.get_style_context().add_class("cnc-probe-action")
            button.set_tooltip_text(tooltip)
            button.connect("clicked", self.run_action, name, script, confirm)
            self.buttons[name] = button
            grid.attach(button, index % columns, index // columns, 1, 1)
        box.pack_start(heading, False, False, 0)
        box.pack_start(note, False, False, 0)
        box.pack_start(grid, False, False, 0)
        return box

    def activate(self):
        self.update_status()

    def process_update(self, action, data):
        if action == "notify_status_update":
            self.update_status()

    def update_status(self):
        state = self._printer.state or "unknown"
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        wcs = self._printer.get_stat("work_coordinate_systems") or {}
        active_wcs = "G53" if wcs.get("machine_mode") else wcs.get("active_wcs", "G54")

        self.labels["state"].set_label(state.upper())
        self.labels["homed"].set_label(f"Homed: {homed_axes.upper() or 'none'}")
        self.labels["wcs"].set_label(active_wcs)

        self._update_touch_status()
        self._update_setter_status()
        self._update_buttons()

    def _update_touch_status(self):
        status = self._printer.get_stat("touch_probe")
        if not status:
            self.labels["touch_value"].set_label("Not configured")
            self.labels["touch_detail"].set_label("Install [touch_probe] to enable stock probing.")
            return
        triggered = status.get("triggered")
        state = "Unknown" if triggered is None else ("TRIGGERED" if triggered else "Ready")
        self.labels["touch_value"].set_label(state)
        self.labels["touch_detail"].set_label(self._touch_detail(status))

    def _update_setter_status(self):
        status = self._printer.get_stat("tool_setter")
        if not status:
            self.labels["setter_value"].set_label("Not configured")
            self.labels["setter_detail"].set_label("Install [tool_setter] to enable bit Z workflows.")
            return
        triggered = status.get("triggered")
        calibration = status.get("calibration")
        if calibration:
            active_wcs = calibration.get("active_wcs", "--")
            setter_z = float(calibration.get("setter_work_z", 0))
            state = "Unknown" if triggered is None else ("TRIGGERED" if triggered else "Calibrated")
            self.labels["setter_value"].set_label(state)
            self.labels["setter_detail"].set_label(
                self._setter_detail(status, active_wcs, setter_z)
            )
        else:
            state = (
                "Unknown"
                if triggered is None
                else ("TRIGGERED" if triggered else "Needs calibration")
            )
            self.labels["setter_value"].set_label(state)
            self.labels["setter_detail"].set_label(self._setter_detail(status))

    def _touch_detail(self, status):
        last_result = status.get("last_result") or {}
        position = last_result.get("position")
        samples = last_result.get("samples") or []
        if position:
            detail = "Last %s  X%s Y%s Z%s" % (
                last_result.get("direction", status.get("last_command") or "probe"),
                self._fmt(position, 0),
                self._fmt(position, 1),
                self._fmt(position, 2),
            )
            if samples:
                detail += f" · {len(samples)} sample{'s' if len(samples) != 1 else ''}"
            return detail
        return status.get("last_command") or "No probe move yet"

    def _setter_detail(self, status, active_wcs=None, setter_z=None):
        lines = []
        setter_x = status.get("setter_x")
        setter_y = status.get("setter_y")
        safe_z = status.get("safe_z")
        if setter_x is not None and setter_y is not None:
            position = f"X{float(setter_x):.3f} Y{float(setter_y):.3f}"
            if safe_z is not None:
                position += f" safe Z{float(safe_z):.3f}"
            lines.append(position)

        calibration = status.get("calibration") or {}
        if active_wcs is not None and setter_z is not None:
            reference = calibration.get("reference_contact_z")
            line = f"{active_wcs} setter Z {setter_z:.3f}"
            if reference is not None:
                line += f" · ref {float(reference):.3f}"
            lines.append(line)
        else:
            lines.append("Run Calibrate Z after stock Z0 is set.")

        last_result = status.get("last_result") or {}
        if "delta" in last_result:
            lines.append(
                "Last bit ΔZ %+.3f · target offset %.3f"
                % (
                    float(last_result["delta"]),
                    float(last_result.get("new_wcs_z_offset", 0)),
                )
            )
        elif "contact_z" in last_result:
            lines.append(f"Last contact Z {float(last_result['contact_z']):.3f}")
        return "\n".join(lines)

    @staticmethod
    def _fmt(values, index):
        try:
            return f"{float(values[index]):.3f}"
        except (TypeError, ValueError, IndexError):
            return "--"

    def _update_buttons(self):
        ready = self._printer.state == "ready"
        homed_axes = self._printer.get_stat("toolhead", "homed_axes") or ""
        xyz_homed = all(axis in homed_axes for axis in ("x", "y", "z"))
        has_touch = bool(self._printer.get_stat("touch_probe"))
        has_setter = bool(self._printer.get_stat("tool_setter"))
        calibration = (self._printer.get_stat("tool_setter") or {}).get("calibration")

        for name in self.buttons:
            if name.startswith(("query_touch", "query_setter")):
                self.buttons[name].set_sensitive(
                    (has_touch if name == "query_touch" else has_setter) and ready
                )
            elif name == "surface":
                self.buttons[name].set_sensitive(has_touch and ready)
            elif name == "history":
                self.buttons[name].set_sensitive(has_touch or has_setter)
            elif name in {item[0] for item in self.touch_actions}:
                self.buttons[name].set_sensitive(has_touch and ready and xyz_homed)
            elif name == "calibrate":
                self.buttons[name].set_sensitive(has_setter and ready and xyz_homed)
            elif name in {"check_bit", "apply_bit", "accuracy"}:
                self.buttons[name].set_sensitive(
                    has_setter and ready and xyz_homed and (calibration is not None or name == "accuracy")
                )

    def run_action(self, widget, name, script, confirm):
        if script.startswith("PANEL:"):
            self._screen.show_panel(script.split(":", 1)[1])
            return
        if confirm:
            self.confirm_cnc_action(widget, name, script)
        else:
            self._screen._send_action(widget, "printer.gcode.script", {"script": script})

    def confirm_cnc_action(self, widget, name, script):
        data = {
            "stock_z": ("Set Stock Z0", "Updates active WCS Z", "This will probe Z and set active WCS Z0."),
            "x_min": ("Probe X Min", "Updates active WCS X", "Start outside the X-min edge. This will move toward X+ and set X0."),
            "x_max": ("Probe X Max", "Updates active WCS X", "Start outside the X-max edge. This will move toward X- and set X0."),
            "y_min": ("Probe Y Min", "Updates active WCS Y", "Start outside the Y-min edge. This will move toward Y+ and set Y0."),
            "y_max": ("Probe Y Max", "Updates active WCS Y", "Start outside the Y-max edge. This will move toward Y- and set Y0."),
            "center_x": ("Center Stock X", "Updates active WCS X", "This will probe both X edges and set center X0."),
            "center_y": ("Center Stock Y", "Updates active WCS Y", "This will probe both Y edges and set center Y0."),
            "center_xy": ("Center Stock XY", "Updates active WCS XY", "This will probe X/Y edges and set center XY0."),
            "bore": ("Probe Bore", "Updates active WCS XY", "This will probe the bore and set center XY0."),
            "accuracy": ("Setter Accuracy", "Motion only", "This will touch the fixed setter repeatedly."),
            "calibrate": ("Calibrate Setter Z", "Stores calibration", "Use this only after stock Z0 is correct."),
            "check_bit": ("Check Bit Z", "Dry run", "This measures the bit and reports WCS Z delta only."),
            "apply_bit": ("Apply Bit Z", "Updates active WCS Z", "This will measure the bit and update active WCS Z."),
        }
        title, badge, message = data.get(name, ("Run Probe Action", "CNC motion", "Run this probing command?"))
        self._show_cnc_confirm(
            title,
            badge,
            message,
            name,
            script,
            self._run_confirmed_script,
        )

    def _show_cnc_confirm(self, title, badge, message, name, script, callback):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        content.set_size_request(min(int(self._screen.width * 0.70), 720), -1)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        heading = Gtk.Label(label=f"<big><b>{title}</b></big>", xalign=0, use_markup=True)
        badge_label = Gtk.Label(label=badge, xalign=0)
        badge_label.get_style_context().add_class("cnc-confirm-badge")
        note = Gtk.Label(label=message, xalign=0, wrap=True)
        note.get_style_context().add_class("cnc-probe-detail")
        checklist = Gtk.Label(
            label="✓ Spindle off\n✓ Probe path clear\n✓ XYZ homed",
            xalign=0,
        )
        checklist.get_style_context().add_class("cnc-confirm-checklist")
        params, entries = self._confirm_param_fields(name)
        preview_script = self._build_confirm_script(name, script, entries)
        command = Gtk.Label(label=f"<tt>{preview_script}</tt>", xalign=0, wrap=True, use_markup=True)
        command.get_style_context().add_class("cnc-confirm-script")
        content.pack_start(heading, False, False, 0)
        content.pack_start(badge_label, False, False, 0)
        content.pack_start(note, False, False, 0)
        if params is not None:
            content.pack_start(params, False, False, 0)
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
            title, buttons, wrapper, callback, name, script, entries
        )
        run_button = self._screen.confirm.get_widget_for_response(Gtk.ResponseType.OK)
        if entries:
            run_button.set_sensitive(False)
        for entry in entries.values():
            entry.connect(
                "changed",
                self._update_confirm_preview,
                name,
                script,
                entries,
                command,
                run_button,
            )

    def _confirm_param_fields(self, name):
        specs = {
            "center_x": (("DISTANCE", "Stock X width"),),
            "center_y": (("DISTANCE", "Stock Y width"),),
            "center_xy": (("DISTANCE_X", "Stock X width"), ("DISTANCE_Y", "Stock Y width")),
        }.get(name)
        if not specs:
            return None, {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(label="Required stock span", xalign=0)
        label.get_style_context().add_class("cnc-probe-detail")
        grid = Gtk.Grid(column_homogeneous=False)
        grid.set_column_spacing(10)
        grid.set_row_spacing(8)
        entries = {}
        for row, (key, placeholder) in enumerate(specs):
            row_label = Gtk.Label(label=placeholder, xalign=0)
            row_label.get_style_context().add_class("cnc-probe-detail")
            entry = Gtk.Entry(text="")
            entry.set_width_chars(5)
            entry.set_max_width_chars(6)
            entry.set_alignment(0.5)
            entry.set_input_purpose(Gtk.InputPurpose.NUMBER)
            entry.set_hexpand(False)
            entry.set_size_request(88, 46)
            entries[key] = entry
            grid.attach(row_label, 0, row, 1, 1)
            for col, step in enumerate((-10, -1)):
                button = self._gtk.Button(label=f"+{step}")
                if step < 0:
                    button.set_label(str(step))
                button.get_style_context().add_class("buttons_slim")
                button.set_size_request(48, 46)
                button.connect("clicked", self._adjust_confirm_entry, entry, step)
                grid.attach(button, col + 1, row, 1, 1)
            grid.attach(entry, 3, row, 1, 1)
            for col, step in enumerate((1, 10)):
                button = self._gtk.Button(label=f"+{step}")
                button.get_style_context().add_class("buttons_slim")
                button.set_size_request(48, 46)
                button.connect("clicked", self._adjust_confirm_entry, entry, step)
                grid.attach(button, col + 4, row, 1, 1)
        box.pack_start(label, False, False, 0)
        box.pack_start(grid, False, False, 0)
        return box, entries

    def _adjust_confirm_entry(self, widget, entry, step):
        try:
            current = float(entry.get_text().strip() or 0)
        except ValueError:
            current = 0
        value = max(0, current + step)
        entry.set_text("%g" % value)

    def _update_confirm_preview(self, entry, name, script, entries, command, run_button):
        command.set_label(
            f"<tt>{self._build_confirm_script(name, script, entries)}</tt>"
        )
        run_button.set_sensitive(self._valid_confirm_params(entries))

    def _build_confirm_script(self, name, script, entries):
        if name not in {"center_x", "center_y", "center_xy"}:
            return script
        parts = [script]
        for key, entry in entries.items():
            value = entry.get_text().strip()
            if value:
                parts.append(f"{key}={value}")
        parts.append("SET_ZERO=1")
        return " ".join(parts)

    def _run_confirmed_script(self, dialog, response_id, name, script, entries):
        if response_id == Gtk.ResponseType.OK:
            if name in {"center_x", "center_y", "center_xy"} and not self._valid_confirm_params(entries):
                self._screen.show_popup_message("Enter a positive stock span before probing")
                return
            final_script = self._build_confirm_script(name, script, entries)
            self._gtk.remove_dialog(dialog)
            self._screen._send_action(None, "printer.gcode.script", {"script": final_script})
            return
        self._gtk.remove_dialog(dialog)

    @staticmethod
    def _valid_confirm_params(entries):
        if not entries:
            return True
        for entry in entries.values():
            try:
                if float(entry.get_text().strip()) <= 0:
                    return False
            except ValueError:
                return False
        return True
