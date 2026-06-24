# Fixed CNC tool setter support for Klipper.
#
# The probe/endstop approach is derived from touch probing work originally
# developed by Shadowphyre from the E3CNC Discord community and shared for
# beta testing. This fixed-setter workflow is maintained by Klipper Screen CNC.
#
# Experimental: this module probes a fixed machine-mounted tool setter and can
# adjust the active G54-G59 Z offset after manual tool changes. Never run it
# with the spindle enabled.

import json
import logging
import math
import os
import tempfile


class ToolSetterEndstop:
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


class ToolSetter:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.persist_path = os.path.expanduser(
            config.get("persist_file", "~/tool_setter.json")
        )
        self.setter_x = config.getfloat("setter_x", None)
        self.setter_y = config.getfloat("setter_y", None)
        self.safe_z = config.getfloat("safe_z", None)
        self.travel_speed = config.getfloat("travel_speed", 30.0, above=0.0)
        self.z_speed = config.getfloat("z_speed", 10.0, above=0.0)
        self.fast_speed = config.getfloat("fast_speed", 5.0, above=0.0)
        self.slow_speed = config.getfloat("slow_speed", 0.5, above=0.0)
        self.max_distance = config.getfloat("max_distance", 25.0, above=0.0)
        self.retract_distance = config.getfloat(
            "retract_distance", 2.0, above=0.0
        )
        self.final_retract = config.getfloat(
            "final_retract", 5.0, minval=0.0
        )
        self.trigger_offset = config.getfloat(
            "trigger_offset", 0.0, minval=0.0
        )
        self.samples = config.getint("samples", 1, minval=1)
        self.spindle_object = config.get("spindle_object", "output_pin spindle")
        self.endstop = ToolSetterEndstop(config)
        self.calibration = None
        self.last_result = None
        self.probe_triggered = None

        self.gcode.register_command(
            "QUERY_TOOL_SETTER",
            self.cmd_QUERY_TOOL_SETTER,
            desc="Report fixed tool setter input and calibration state",
        )
        self.gcode.register_command(
            "CALIBRATE_SETTER_Z",
            self.cmd_CALIBRATE_SETTER_Z,
            desc="Measure the fixed setter after stock Z0 is set",
        )
        self.gcode.register_command(
            "SET_BIT_Z",
            self.cmd_SET_BIT_Z,
            desc="Measure the current bit on the fixed setter and update work Z",
        )
        self.gcode.register_command(
            "TOOL_SETTER_ACCURACY",
            self.cmd_TOOL_SETTER_ACCURACY,
            desc="Probe the fixed setter repeatedly and report repeatability",
        )

        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        self._load()

    def _load(self):
        if not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path, "r") as handle:
                data = json.load(handle)
            if data.get("version") != 1:
                return
            required = (
                "active_wcs",
                "wcs_z_offset",
                "setter_work_z",
                "reference_contact_z",
            )
            if not all(key in data for key in required):
                return
            calibration = {
                "active_wcs": str(data["active_wcs"]),
                "wcs_z_offset": float(data["wcs_z_offset"]),
                "setter_work_z": float(data["setter_work_z"]),
                "reference_contact_z": float(data["reference_contact_z"]),
            }
            if all(
                math.isfinite(value)
                for key, value in calibration.items()
                if key != "active_wcs"
            ):
                self.calibration = calibration
        except Exception:
            logging.exception("Tool setter: could not read %s", self.persist_path)

    def _persist(self):
        if self.calibration is None:
            return
        directory = os.path.dirname(self.persist_path) or "."
        os.makedirs(directory, exist_ok=True)
        data = {"version": 1}
        data.update(self.calibration)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=directory, prefix=".tool-setter-", delete=False
            ) as handle:
                temporary = handle.name
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.persist_path)
        except Exception:
            logging.exception("Tool setter: could not write %s", self.persist_path)
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

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
        if not all(axis in homed for axis in "xyz"):
            raise gcmd.error("Tool setter requires homed XYZ")

        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            state = print_stats.get_status(
                self.printer.get_reactor().monotonic()
            ).get("state", "")
            if state in ("printing", "paused"):
                raise gcmd.error("Tool setter is disabled during an active job")

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
            raise gcmd.error("Tool setter requires the spindle to be off")

        if self._query_triggered():
            raise gcmd.error("Tool setter is already triggered")

    def _z_limits(self):
        status = self._kinematics_status()
        return status["axis_minimum"][2], status["axis_maximum"][2]

    def _axis_limits(self, axis):
        status = self._kinematics_status()
        return status["axis_minimum"][axis], status["axis_maximum"][axis]

    def _move(self, position, speed):
        toolhead = self.printer.lookup_object("toolhead")
        toolhead.manual_move(position, speed)
        toolhead.wait_moves()

    def _move_z(self, coordinate, speed):
        position = list(self.printer.lookup_object("toolhead").get_position())
        position[2] = coordinate
        self._move(position, speed)

    def _move_to_setter(self, gcmd):
        move = gcmd.get_int("MOVE", 1, minval=0, maxval=1)
        if not move:
            return

        axis_min, axis_max = self._z_limits()
        safe_z = gcmd.get_float("SAFE_Z", self.safe_z)
        if safe_z is None:
            safe_z = axis_max
        if safe_z < axis_min or safe_z > axis_max:
            raise gcmd.error("SAFE_Z is outside machine travel")

        x = gcmd.get_float("X", self.setter_x)
        y = gcmd.get_float("Y", self.setter_y)
        if x is None or y is None:
            raise gcmd.error("Tool setter MOVE=1 requires setter_x and setter_y")
        x_min, x_max = self._axis_limits(0)
        y_min, y_max = self._axis_limits(1)
        if x < x_min or x > x_max or y < y_min or y > y_max:
            raise gcmd.error("Tool setter XY target is outside machine travel")

        travel_speed = gcmd.get_float(
            "TRAVEL_SPEED", self.travel_speed, above=0.0
        )
        z_speed = gcmd.get_float("Z_SPEED", self.z_speed, above=0.0)
        position = list(self.printer.lookup_object("toolhead").get_position())
        if position[2] < safe_z - 0.000001:
            self._move_z(safe_z, z_speed)
        position = list(self.printer.lookup_object("toolhead").get_position())
        position[0] = x
        position[1] = y
        self._move(position, travel_speed)

    def _retract(self, hit_z, distance, speed):
        _, axis_max = self._z_limits()
        destination = min(axis_max, hit_z + distance)
        if destination <= hit_z + 0.000001:
            raise self.printer.command_error(
                "No positive Z travel available after tool setter probe"
            )
        self._move_z(destination, speed)

    def _probe(self, gcmd, report_samples=True):
        self._require_safe(gcmd)
        self._move_to_setter(gcmd)
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
            raise gcmd.error("No negative Z travel available for tool setter")

        logging.info("Tool setter fast Z move to %.6f", target[2])
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
                "Tool setter sample %d/%d: %.6f",
                sample + 1,
                samples,
                last_hit[2],
            )

        raw_contact_z = sum(readings) / len(readings)
        contact_z = raw_contact_z + self.trigger_offset
        if report_samples and len(readings) > 1:
            gcmd.respond_info(
                "Tool setter samples: %s\nmin=%.6f max=%.6f range=%.6f avg=%.6f"
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

    def _format_accuracy(self, readings):
        ordered = sorted(readings)
        count = len(ordered)
        average = sum(ordered) / count
        if count % 2:
            median = ordered[count // 2]
        else:
            median = (ordered[count // 2 - 1] + ordered[count // 2]) / 2.0
        variance = sum((value - average) ** 2 for value in ordered) / count
        return (
            "tool setter accuracy results: maximum %.6f, minimum %.6f, "
            "range %.6f, average %.6f, median %.6f, standard deviation %.6f"
            % (
                max(ordered),
                min(ordered),
                max(ordered) - min(ordered),
                average,
                median,
                math.sqrt(variance),
            )
        )

    def _active_wcs(self, gcmd):
        wcs = self.printer.lookup_object("work_coordinate_systems", None)
        if wcs is None:
            raise gcmd.error("Tool setter requires [work_coordinate_systems]")
        if wcs.machine_mode:
            raise gcmd.error("Select G54-G59 before using the tool setter")
        if not wcs.applied:
            raise gcmd.error("Home XYZ before using the tool setter")
        return wcs

    def _should_apply(self, gcmd):
        apply_offset = gcmd.get_int("APPLY", 0, minval=0, maxval=1)
        set_zero = gcmd.get_int("SET_ZERO", 0, minval=0, maxval=1)
        return bool(apply_offset or set_zero)

    def cmd_QUERY_TOOL_SETTER(self, gcmd):
        state = "TRIGGERED" if self._query_triggered() else "ready"
        if self.calibration is None:
            gcmd.respond_info("Tool setter: %s, not calibrated" % (state,))
            return
        gcmd.respond_info(
            "Tool setter: %s, calibrated for %s, setter Z=%.6f in work coords"
            % (
                state,
                self.calibration["active_wcs"],
                self.calibration["setter_work_z"],
            )
        )

    def cmd_CALIBRATE_SETTER_Z(self, gcmd):
        wcs = self._active_wcs(gcmd)
        contact_z = self._probe(gcmd)
        wcs_z_offset = float(wcs.wcs[wcs.active_wcs][2])
        setter_work_z = contact_z - wcs_z_offset
        self.calibration = {
            "active_wcs": wcs.active_wcs,
            "wcs_z_offset": wcs_z_offset,
            "setter_work_z": setter_work_z,
            "reference_contact_z": contact_z,
        }
        self._persist()
        gcmd.respond_info(
            "Setter Z calibrated for %s: contact Z=%.6f, setter work Z=%.6f"
            % (wcs.active_wcs, contact_z, setter_work_z)
        )

    def cmd_SET_BIT_Z(self, gcmd):
        wcs = self._active_wcs(gcmd)
        if self.calibration is None:
            raise gcmd.error("Run CALIBRATE_SETTER_Z before SET_BIT_Z")
        if self.calibration["active_wcs"] != wcs.active_wcs:
            raise gcmd.error(
                "Tool setter was calibrated for %s, but %s is active"
                % (self.calibration["active_wcs"], wcs.active_wcs)
            )
        contact_z = self._probe(gcmd)
        setter_work_z = self.calibration["setter_work_z"]
        new_wcs_z_offset = contact_z - setter_work_z
        current_wcs_z_offset = float(wcs.wcs[wcs.active_wcs][2])
        delta = new_wcs_z_offset - current_wcs_z_offset
        self.last_result = dict(self.last_result or {})
        self.last_result.update(
            {
                "setter_work_z": setter_work_z,
                "new_wcs_z_offset": new_wcs_z_offset,
                "current_wcs_z_offset": current_wcs_z_offset,
                "delta": delta,
            }
        )
        if self._should_apply(gcmd):
            machine_position = list(
                self.printer.lookup_object("toolhead").get_position()
            )
            machine_position[2] = contact_z
            wcs.set_from_machine_position(
                wcs.active_wcs, machine_position, {2: setter_work_z}
            )
            action = "updated"
        else:
            action = "not updated; add APPLY=1 or SET_ZERO=1 to apply"
        gcmd.respond_info(
            "Bit Z for %s: contact Z=%.6f, target WCS Z offset=%.6f, "
            "delta=%.6f (%s)"
            % (
                wcs.active_wcs,
                contact_z,
                new_wcs_z_offset,
                delta,
                action,
            )
        )

    def cmd_TOOL_SETTER_ACCURACY(self, gcmd):
        self._probe(gcmd, report_samples=False)
        readings = (self.last_result or {}).get("samples", [])
        if not readings:
            raise gcmd.error("No tool setter accuracy samples captured")
        gcmd.respond_info(self._format_accuracy(readings))

    def get_status(self, eventtime=None):
        return {
            "triggered": self.probe_triggered,
            "setter_x": self.setter_x,
            "setter_y": self.setter_y,
            "safe_z": self.safe_z,
            "calibration": self.calibration,
            "last_result": self.last_result,
        }


def load_config(config):
    return ToolSetter(config)
