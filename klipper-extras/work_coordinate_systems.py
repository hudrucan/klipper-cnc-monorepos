# Work Coordinate Systems (G54-G59) for Klipper CNC.
#
# Originally developed by Shadowphyre from the E3CNC Discord community
# and shared for beta testing. Hardened and extended by Klipper Screen CNC.
#
# Experimental: this module uses Klipper's internal gcode_move coordinate
# state because Klipper does not provide a public WCS API.

import json
import logging
import math
import os
import tempfile

WCS_NAMES = ("G54", "G55", "G56", "G57", "G58", "G59")
WCS_P_MAP = {index + 1: name for index, name in enumerate(WCS_NAMES)}
WCS_NAME_TO_P = {name: index for index, name in WCS_P_MAP.items()}


class WorkCoordinateSystems:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.persist_path = os.path.expanduser(
            config.get("persist_file", "~/wcs_offsets.json")
        )
        self.wcs = {name: [0.0, 0.0, 0.0] for name in WCS_NAMES}
        self.active_wcs = "G54"
        self.machine_mode = False
        self.applied = False

        for name in WCS_NAMES:
            self.gcode.register_command(name, self.cmd_select_wcs)
        self.gcode.register_command("G53", self.cmd_G53)
        self.prev_g10 = self.gcode.register_command("G10", None)
        self.gcode.register_command("G10", self.cmd_G10)
        self.gcode.register_command(
            "WCS_STATUS", self.cmd_wcs_status, desc="Report WCS state and offsets"
        )
        self.gcode.register_command(
            "SAVE_WCS", self.cmd_save_wcs, desc="Persist WCS state"
        )

        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.printer.register_event_handler(
            "homing:home_rails_end", self._handle_home_rails_end
        )

    def _handle_ready(self):
        self._load()
        # Machine coordinates are unknown after restart. Keep gcode_move at its
        # native unhomed state and apply the persisted WCS only after homing.
        self.applied = False
        self.machine_mode = False
        logging.info(
            "WCS: ready, pending home before applying %s offsets=%s",
            self.active_wcs,
            self.wcs,
        )

    def _handle_home_rails_end(self, homing_state, rails):
        toolhead = self.printer.lookup_object("toolhead")
        homed = toolhead.get_kinematics().get_status(
            self.printer.get_reactor().monotonic()
        ).get("homed_axes", "")
        if not all(axis in homed for axis in "xyz"):
            self.applied = False
            return
        self._apply_wcs(self.active_wcs)
        logging.info("WCS: XYZ homed, restored %s", self.active_wcs)

    def _load(self):
        if not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path, "r") as handle:
                data = json.load(handle)
            loaded = data.get("wcs", {})
            for name in WCS_NAMES:
                values = loaded.get(name)
                if not isinstance(values, list) or len(values) != 3:
                    continue
                values = [float(value) for value in values]
                if all(math.isfinite(value) for value in values):
                    self.wcs[name] = values
            active = data.get("active_wcs", "G54")
            if active in WCS_NAMES:
                self.active_wcs = active
        except Exception:
            logging.exception("WCS: could not read %s", self.persist_path)

    def _persist(self):
        directory = os.path.dirname(self.persist_path) or "."
        os.makedirs(directory, exist_ok=True)
        data = {
            "version": 2,
            "active_wcs": self.active_wcs,
            "wcs": {name: list(self.wcs[name]) for name in WCS_NAMES},
        }
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=directory, prefix=".wcs-", delete=False
            ) as handle:
                temporary = handle.name
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.persist_path)
        except Exception:
            logging.exception("WCS: could not write %s", self.persist_path)
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def _require_homed(self, gcmd):
        toolhead = self.printer.lookup_object("toolhead")
        homed = toolhead.get_kinematics().get_status(
            self.printer.get_reactor().monotonic()
        ).get("homed_axes", "")
        if not all(axis in homed for axis in "xyz"):
            raise gcmd.error("WCS command requires homed XYZ")

    def _sync_gcode_position(self):
        self.printer.lookup_object("gcode_move").reset_last_position()

    def _apply_wcs(self, name):
        gcode_move = self.printer.lookup_object("gcode_move")
        self._sync_gcode_position()
        gcode_move.base_position[:3] = self.wcs[name]
        self.active_wcs = name
        self.machine_mode = False
        self.applied = True

    def _apply_machine_mode(self):
        gcode_move = self.printer.lookup_object("gcode_move")
        self._sync_gcode_position()
        gcode_move.base_position[:3] = [0.0, 0.0, 0.0]
        self.machine_mode = True
        self.applied = True

    def _wcs_from_p(self, gcmd):
        return WCS_P_MAP[gcmd.get_int("P", 1, minval=1, maxval=6)]

    def set_from_machine_position(self, name, machine_position, values):
        """Set selected WCS axes using a known machine-space position.

        Used by CNC probing so offsets can be calculated at the trigger
        coordinate without moving the tool back into the probe surface.
        """
        toolhead = self.printer.lookup_object("toolhead")
        homed = toolhead.get_kinematics().get_status(
            self.printer.get_reactor().monotonic()
        ).get("homed_axes", "")
        if not all(axis in homed for axis in "xyz"):
            raise self.printer.command_error(
                "Setting a WCS from probing requires homed XYZ"
            )
        if name not in WCS_NAMES:
            raise self.printer.command_error("Unknown WCS %s" % (name,))
        for index, value in values.items():
            value = float(value)
            if index not in (0, 1, 2) or not math.isfinite(value):
                raise self.printer.command_error("Invalid WCS probe result")
            self.wcs[name][index] = float(machine_position[index]) - value
        if name == self.active_wcs and not self.machine_mode:
            self._apply_wcs(name)
        self._persist()

    def cmd_select_wcs(self, gcmd):
        self._require_homed(gcmd)
        name = gcmd.get_command()
        self._apply_wcs(name)
        self._persist()
        offset = self.wcs[name]
        gcmd.respond_info(
            "WCS: %s active (machine origin X=%.4f Y=%.4f Z=%.4f)"
            % (name, offset[0], offset[1], offset[2])
        )

    def cmd_G53(self, gcmd):
        self._require_homed(gcmd)
        self._apply_machine_mode()
        gcmd.respond_info(
            "WCS: G53 machine mode active; issue G54-G59 to restore work coordinates"
        )

    def cmd_G10(self, gcmd):
        mode = gcmd.get_int("L", None)
        if mode == 2:
            self._cmd_G10_L2(gcmd)
        elif mode == 20:
            self._cmd_G10_L20(gcmd)
        elif self.prev_g10 is not None:
            self.prev_g10(gcmd)
        else:
            raise gcmd.error("G10 requires L2 or L20")

    def _cmd_G10_L2(self, gcmd):
        self._require_homed(gcmd)
        name = self._wcs_from_p(gcmd)
        for index, axis in enumerate("XYZ"):
            value = gcmd.get_float(axis, None)
            if value is not None:
                self.wcs[name][index] = value
        if name == self.active_wcs and not self.machine_mode:
            self._apply_wcs(name)
        self._persist()
        gcmd.respond_info("WCS: %s updated with G10 L2" % (name,))

    def _cmd_G10_L20(self, gcmd):
        self._require_homed(gcmd)
        name = self._wcs_from_p(gcmd)
        machine_position = self.printer.lookup_object("toolhead").get_position()
        values = {}
        for index, axis in enumerate("XYZ"):
            value = gcmd.get_float(axis, None)
            if value is not None:
                values[index] = value
        self.set_from_machine_position(name, machine_position, values)
        gcmd.respond_info("WCS: %s updated with G10 L20" % (name,))

    def cmd_wcs_status(self, gcmd):
        mode = "G53 machine" if self.machine_mode else self.active_wcs
        applied = "applied" if self.applied else "pending home"
        lines = ["WCS status: %s (%s)" % (mode, applied)]
        for name in WCS_NAMES:
            offset = self.wcs[name]
            lines.append(
                "  %s: X=%.4f Y=%.4f Z=%.4f%s"
                % (
                    name,
                    offset[0],
                    offset[1],
                    offset[2],
                    " <--" if name == self.active_wcs else "",
                )
            )
        gcmd.respond_info("\n".join(lines))

    def cmd_save_wcs(self, gcmd):
        self._persist()
        gcmd.respond_info("WCS: saved to %s" % (self.persist_path,))

    def get_status(self, eventtime=None):
        return {
            "active_wcs": self.active_wcs,
            "active_p": WCS_NAME_TO_P[self.active_wcs],
            "machine_mode": self.machine_mode,
            "applied": self.applied,
            "wcs": {name: list(values) for name, values in self.wcs.items()},
        }


def load_config(config):
    return WorkCoordinateSystems(config)
