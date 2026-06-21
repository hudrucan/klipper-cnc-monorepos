# CNC cutting-tool Z touch-off for Klipper.
#
# The probe/endstop approach is derived from touch probing work originally
# developed by Shadowphyre from the E3CNC Discord community and shared for
# beta testing. This separate cutting-tool workflow is maintained by
# Klipper Screen CNC.
#
# Experimental: this module electrically probes the cutting tool against a
# touch plate. Never run it with the spindle enabled.

import logging


class ToolProbeEndstop:
    def __init__(self, config):
        self.printer = config.get_printer()
        pins = self.printer.lookup_object("pins")
        pin = config.get("pin")
        pins.allow_multi_use_pin(pin.replace("^", "").replace("!", ""))
        pin_params = pins.lookup_pin(pin, can_invert=True, can_pullup=True)
        self.mcu_endstop = pin_params["chip"].setup_pin("endstop", pin_params)
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self.mcu_endstop.get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop

    def _handle_mcu_identify(self):
        kinematics = self.printer.lookup_object("toolhead").get_kinematics()
        for stepper in kinematics.get_steppers():
            if stepper.is_active_axis("z"):
                self.add_stepper(stepper)

    def get_position_endstop(self):
        return 0.0


class ToolTouchProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.fast_speed = config.getfloat("fast_speed", 5.0, above=0.0)
        self.slow_speed = config.getfloat("slow_speed", 0.5, above=0.0)
        self.max_distance = config.getfloat("max_distance", 25.0, above=0.0)
        self.retract_distance = config.getfloat(
            "retract_distance", 2.0, above=0.0
        )
        self.final_retract = config.getfloat(
            "final_retract", 5.0, minval=0.0
        )
        self.plate_thickness = config.getfloat(
            "plate_thickness", above=0.0
        )
        self.trigger_offset = config.getfloat(
            "trigger_offset", 0.0, minval=0.0
        )
        self.samples = config.getint("samples", 1, minval=1)
        self.spindle_object = config.get("spindle_object", "output_pin spindle")
        self.endstop = ToolProbeEndstop(config)
        self.last_result = None
        self.probe_triggered = None

        self.gcode.register_command(
            "QUERY_TOOL_TOUCH_PROBE", self.cmd_QUERY_TOOL_TOUCH_PROBE
        )
        self.gcode.register_command("PROBE_TOOL_Z", self.cmd_PROBE_TOOL_Z)
        self.gcode.register_command("TOUCH_OFF_Z", self.cmd_TOUCH_OFF_Z)

    def _kinematics_status(self):
        eventtime = self.printer.get_reactor().monotonic()
        toolhead = self.printer.lookup_object("toolhead")
        return toolhead.get_kinematics().get_status(eventtime)

    def _query_triggered(self):
        toolhead = self.printer.lookup_object("toolhead")
        toolhead.wait_moves()
        self.probe_triggered = bool(
            self.endstop.query_endstop(toolhead.get_last_move_time())
        )
        return self.probe_triggered

    def _require_safe(self, gcmd):
        homed = self._kinematics_status().get("homed_axes", "")
        if "z" not in homed:
            raise gcmd.error("Tool touch-off requires homed Z")

        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            state = print_stats.get_status(
                self.printer.get_reactor().monotonic()
            ).get("state", "")
            if state in ("printing", "paused"):
                raise gcmd.error("Tool touch-off is disabled during an active job")

        spindle = self.printer.lookup_object(self.spindle_object, None)
        if spindle is None:
            raise gcmd.error(
                "Cannot verify spindle state: unknown %s"
                % (self.spindle_object,)
            )
        value = spindle.get_status(
            self.printer.get_reactor().monotonic()
        ).get("value", 0.0)
        if abs(float(value)) > 0.000001:
            raise gcmd.error("Tool touch-off requires the spindle to be off")

        if self._query_triggered():
            raise gcmd.error("Tool touch probe is already triggered")

    def _z_limits(self):
        status = self._kinematics_status()
        return status["axis_minimum"][2], status["axis_maximum"][2]

    def _move_z(self, coordinate, speed):
        toolhead = self.printer.lookup_object("toolhead")
        position = list(toolhead.get_position())
        position[2] = coordinate
        toolhead.manual_move(position, speed)
        toolhead.wait_moves()

    def _retract(self, hit_z, distance, speed):
        _, axis_max = self._z_limits()
        destination = min(axis_max, hit_z + distance)
        if destination <= hit_z + 0.000001:
            raise self.printer.command_error(
                "No positive Z travel available after touch-off"
            )
        self._move_z(destination, speed)

    def _probe(self, gcmd):
        self._require_safe(gcmd)
        toolhead = self.printer.lookup_object("toolhead")
        homing = self.printer.lookup_object("homing")
        axis_min, _ = self._z_limits()
        fast_speed = gcmd.get_float(
            "FAST_SPEED", self.fast_speed, above=0.0
        )
        slow_speed = gcmd.get_float(
            "SLOW_SPEED", self.slow_speed, above=0.0
        )
        max_distance = gcmd.get_float(
            "MAX_DISTANCE", self.max_distance, above=0.0
        )
        retract_distance = gcmd.get_float(
            "RETRACT_DISTANCE", self.retract_distance, above=0.0
        )
        samples = gcmd.get_int("SAMPLES", self.samples, minval=1)

        position = list(toolhead.get_position())
        target = list(position)
        target[2] = max(axis_min, position[2] - max_distance)
        if position[2] - target[2] < 0.000001:
            raise gcmd.error("No negative Z travel available for touch-off")

        logging.info("Tool touch probe fast Z move to %.6f", target[2])
        try:
            hit = homing.probing_move(self.endstop, target, fast_speed)
        except self.printer.command_error as error:
            raise gcmd.error(str(error))
        self._retract(hit[2], retract_distance, fast_speed)

        readings = []
        last_hit = hit
        for sample in range(samples):
            position = list(toolhead.get_position())
            target = list(position)
            target[2] = max(axis_min, position[2] - retract_distance * 2.0)
            if position[2] - target[2] < retract_distance:
                raise gcmd.error("Insufficient Z travel for slow probe pass")
            try:
                last_hit = homing.probing_move(
                    self.endstop, target, slow_speed
                )
            except self.printer.command_error as error:
                raise gcmd.error(str(error))
            readings.append(last_hit[2])
            self._retract(last_hit[2], retract_distance, fast_speed)
            logging.info(
                "Tool touch probe sample %d/%d: %.6f",
                sample + 1,
                samples,
                last_hit[2],
            )

        raw_contact_z = sum(readings) / len(readings)
        contact_z = raw_contact_z + self.trigger_offset
        if len(readings) > 1:
            gcmd.respond_info(
                "Z samples: %s\nmin=%.6f max=%.6f range=%.6f avg=%.6f"
                % (
                    ", ".join("%.6f" % value for value in readings),
                    min(readings),
                    max(readings),
                    max(readings) - min(readings),
                    raw_contact_z,
                )
            )
        final_retract = gcmd.get_float(
            "FINAL_RETRACT", self.final_retract, minval=0.0
        )
        if final_retract > retract_distance:
            self._retract(raw_contact_z, final_retract, fast_speed)
        self.last_result = {
            "raw_contact_z": raw_contact_z,
            "contact_z": contact_z,
            "samples": list(readings),
            "retracted_z": toolhead.get_position()[2],
        }
        return contact_z

    def _set_wcs_z(self, gcmd, contact_z, plate_thickness):
        wcs = self.printer.lookup_object("work_coordinate_systems", None)
        if wcs is None:
            raise gcmd.error("TOUCH_OFF_Z requires [work_coordinate_systems]")
        if wcs.machine_mode:
            raise gcmd.error("Select G54-G59 before tool touch-off")
        machine_position = list(
            self.printer.lookup_object("toolhead").get_position()
        )
        machine_position[2] = contact_z
        wcs.set_from_machine_position(
            wcs.active_wcs, machine_position, {2: plate_thickness}
        )

    def _require_wcs_ready(self, gcmd):
        homed = self._kinematics_status().get("homed_axes", "")
        if not all(axis in homed for axis in "xyz"):
            raise gcmd.error("Setting work Z requires homed XYZ")
        wcs = self.printer.lookup_object("work_coordinate_systems", None)
        if wcs is None:
            raise gcmd.error("TOUCH_OFF_Z requires [work_coordinate_systems]")
        if wcs.machine_mode:
            raise gcmd.error("Select G54-G59 before tool touch-off")

    def cmd_QUERY_TOOL_TOUCH_PROBE(self, gcmd):
        state = "TRIGGERED" if self._query_triggered() else "open"
        gcmd.respond_info("Tool touch probe: %s" % (state,))

    def cmd_PROBE_TOOL_Z(self, gcmd):
        contact_z = self._probe(gcmd)
        gcmd.respond_info("Tool contact Z=%.6f" % (contact_z,))

    def cmd_TOUCH_OFF_Z(self, gcmd):
        self._require_wcs_ready(gcmd)
        plate_thickness = gcmd.get_float(
            "PLATE_THICKNESS", self.plate_thickness, above=0.0
        )
        contact_z = self._probe(gcmd)
        self._set_wcs_z(gcmd, contact_z, plate_thickness)
        gcmd.respond_info(
            "Tool Z set from contact %.6f with %.6f mm plate"
            % (contact_z, plate_thickness)
        )

    def get_status(self, eventtime=None):
        return {
            "triggered": self.probe_triggered,
            "last_result": self.last_result,
        }


def load_config(config):
    return ToolTouchProbe(config)
