# CNC touch probing for Klipper.
#
# Originally developed by Shadowphyre from the E3CNC Discord community
# and shared for beta testing. Hardened and extended by Klipper Screen CNC.
#
# Experimental: prove every direction at low speed with the spindle disabled
# before relying on these commands near a workpiece.

import json
import logging
import math
import os
import tempfile

DIRECTIONS = {
    "X+": (0, 1),
    "X-": (0, -1),
    "Y+": (1, 1),
    "Y-": (1, -1),
    "Z-": (2, -1),
}
AXIS_NAMES = "XYZ"


class ProbeEndstopWrapper:
    def __init__(self, config, axis):
        self.printer = config.get_printer()
        self.axis = axis
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
            if stepper.is_active_axis(self.axis):
                self.add_stepper(stepper)

    def get_position_endstop(self):
        return 0.0


class TouchProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.travel_speed = config.getfloat("travel_speed", 40.0, above=0.0)
        self.fast_speed = config.getfloat("fast_speed", 10.0, above=0.0)
        self.slow_speed = config.getfloat("slow_speed", 1.0, above=0.0)
        self.max_distance = config.getfloat("max_distance", 50.0, above=0.0)
        self.retract_distance = config.getfloat(
            "retract_distance", 2.0, above=0.0
        )
        self.tip_diameter = config.getfloat("tip_diameter", 1.0, above=0.0)
        self.trigger_offset = config.getfloat(
            "trigger_offset", 0.0, minval=0.0
        )
        self.z_hop = config.getfloat("z_hop", 10.0, above=0.0)
        self.z_hop_speed = config.getfloat("z_hop_speed", 10.0, above=0.0)
        self.overshoot = config.getfloat("overshoot", 5.0, above=0.0)
        self.samples = config.getint("samples", 1, minval=1)
        self.spindle_object = config.get("spindle_object", "output_pin spindle")
        self.surface_result_path = os.path.expanduser(
            config.get(
                "surface_result_file",
                "~/printer_data/config/touch_probe_surface.json",
            )
        )

        self.endstops = {
            0: ProbeEndstopWrapper(config, "x"),
            1: ProbeEndstopWrapper(config, "y"),
            2: ProbeEndstopWrapper(config, "z"),
        }
        self.last_result = None
        self.last_command = None
        self.probe_triggered = None
        self.surface_result = None

        commands = {
            "QUERY_TOUCH_PROBE": self.cmd_QUERY_TOUCH_PROBE,
            "PROBE_X_POS": self.cmd_PROBE_X_POS,
            "PROBE_X_NEG": self.cmd_PROBE_X_NEG,
            "PROBE_Y_POS": self.cmd_PROBE_Y_POS,
            "PROBE_Y_NEG": self.cmd_PROBE_Y_NEG,
            "PROBE_Z_NEG": self.cmd_PROBE_Z_NEG,
            "FIND_EDGE_X_POS": self.cmd_FIND_EDGE_X_POS,
            "FIND_EDGE_X_NEG": self.cmd_FIND_EDGE_X_NEG,
            "FIND_EDGE_Y_POS": self.cmd_FIND_EDGE_Y_POS,
            "FIND_EDGE_Y_NEG": self.cmd_FIND_EDGE_Y_NEG,
            "FIND_SURFACE_Z": self.cmd_FIND_SURFACE_Z,
            "FIND_STOCK_Z": self.cmd_FIND_SURFACE_Z,
            "FIND_CENTER_X": self.cmd_FIND_CENTER_X,
            "FIND_CENTER_Y": self.cmd_FIND_CENTER_Y,
            "FIND_CENTER_XY": self.cmd_FIND_CENTER_XY,
            "PROBE_BORE": self.cmd_PROBE_BORE,
            "MEASURE_SURFACE_TILT": self.cmd_MEASURE_SURFACE_TILT,
        }
        for name, handler in commands.items():
            self.gcode.register_command(name, handler)

        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        self._load_surface_result()

    def _load_surface_result(self):
        if not os.path.exists(self.surface_result_path):
            return
        try:
            with open(self.surface_result_path, "r") as handle:
                data = json.load(handle)
            if data.get("version") != 1:
                return
            result = data.get("surface_result")
            if not isinstance(result, dict):
                return
            points = result.get("points")
            summary = result.get("summary")
            if not isinstance(points, list) or not isinstance(summary, dict):
                return
            self.surface_result = result
        except Exception:
            logging.exception(
                "Touch probe: could not read %s", self.surface_result_path
            )

    def _persist_surface_result(self):
        if self.surface_result is None:
            return
        directory = os.path.dirname(self.surface_result_path) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=directory, prefix=".touch-probe-surface-", delete=False
            ) as handle:
                temporary = handle.name
                json.dump(
                    {"version": 1, "surface_result": self.surface_result},
                    handle,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.surface_result_path)
        except Exception:
            logging.exception(
                "Touch probe: could not write %s", self.surface_result_path
            )
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def _kinematics_status(self):
        eventtime = self.printer.get_reactor().monotonic()
        toolhead = self.printer.lookup_object("toolhead")
        return toolhead.get_kinematics().get_status(eventtime)

    def _require_safe(self, gcmd, axes):
        status = self._kinematics_status()
        homed = status.get("homed_axes", "")
        if not all(axis.lower() in homed for axis in axes):
            raise gcmd.error("Touch probe requires homed %s" % ("".join(axes),))

        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            state = print_stats.get_status(
                self.printer.get_reactor().monotonic()
            ).get("state", "")
            if state in ("printing", "paused"):
                raise gcmd.error("Touch probing is disabled during an active job")

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
            raise gcmd.error("Touch probing requires the spindle to be off")

        if self._query_triggered():
            raise gcmd.error("Touch probe is already triggered")

    def _query_triggered(self):
        toolhead = self.printer.lookup_object("toolhead")
        toolhead.wait_moves()
        self.probe_triggered = bool(
            self.endstops[0].query_endstop(toolhead.get_last_move_time())
        )
        return self.probe_triggered

    def _limits(self, axis):
        status = self._kinematics_status()
        return status["axis_minimum"][axis], status["axis_maximum"][axis]

    def _move_axis(self, axis, coordinate, speed):
        toolhead = self.printer.lookup_object("toolhead")
        position = list(toolhead.get_position())
        position[axis] = coordinate
        toolhead.manual_move(position, speed)
        toolhead.wait_moves()

    def _move_xy(self, x, y, speed):
        toolhead = self.printer.lookup_object("toolhead")
        position = list(toolhead.get_position())
        position[0] = x
        position[1] = y
        toolhead.manual_move(position, speed)
        toolhead.wait_moves()

    def _travel_speed(self, gcmd):
        return gcmd.get_float("TRAVEL_SPEED", self.travel_speed, above=0.0)

    def _probe(self, gcmd, direction):
        axis, sense = DIRECTIONS[direction]
        self._require_safe(gcmd, AXIS_NAMES[axis])
        toolhead = self.printer.lookup_object("toolhead")
        homing = self.printer.lookup_object("homing")
        axis_min, axis_max = self._limits(axis)
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
        requested = position[axis] + sense * max_distance
        target[axis] = min(axis_max, max(axis_min, requested))
        if abs(target[axis] - position[axis]) < 0.000001:
            raise gcmd.error("No travel available for probe %s" % (direction,))

        logging.info("Touch probe fast %s to %s", direction, target)
        try:
            hit = homing.probing_move(
                self.endstops[axis], target, fast_speed
            )
        except self.printer.command_error as error:
            raise gcmd.error(str(error))

        self._retract_from_hit(hit, axis, sense, retract_distance, fast_speed)
        readings = []
        last_hit = hit
        for sample in range(samples):
            position = list(toolhead.get_position())
            target = list(position)
            target[axis] = min(
                axis_max,
                max(axis_min, position[axis] + sense * retract_distance * 2.0),
            )
            if abs(target[axis] - position[axis]) < retract_distance:
                raise gcmd.error("Insufficient travel for slow probe pass")
            try:
                last_hit = homing.probing_move(
                    self.endstops[axis], target, slow_speed
                )
            except self.printer.command_error as error:
                raise gcmd.error(str(error))
            readings.append(last_hit[axis])
            self._retract_from_hit(
                last_hit, axis, sense, retract_distance, fast_speed
            )
            logging.info(
                "Touch probe %s sample %d/%d: %.6f",
                direction,
                sample + 1,
                samples,
                last_hit[axis],
            )

        result = list(last_hit)
        average = sum(readings) / len(readings)
        result[axis] = average
        if len(readings) > 1:
            gcmd.respond_info(
                "%s samples: %s\nmin=%.6f max=%.6f range=%.6f avg=%.6f"
                % (
                    AXIS_NAMES[axis],
                    ", ".join("%.6f" % value for value in readings),
                    min(readings),
                    max(readings),
                    max(readings) - min(readings),
                    average,
                )
            )
        self.last_command = gcmd.get_command()
        self.last_result = {
            "direction": direction,
            "position": result[:3],
            "samples": list(readings),
        }
        return result

    def _retract_from_hit(self, hit, axis, sense, distance, speed):
        axis_min, axis_max = self._limits(axis)
        coordinate = min(
            axis_max, max(axis_min, hit[axis] - sense * distance)
        )
        if abs(coordinate - hit[axis]) < 0.000001:
            raise self.printer.command_error(
                "No room to retract after touch probe"
            )
        self._move_axis(axis, coordinate, speed)

    def _edge(self, trigger_position, direction):
        axis, sense = DIRECTIONS[direction]
        edge = list(trigger_position)
        edge[axis] += sense * (
            self.tip_diameter / 2.0 - self.trigger_offset
        )
        return edge

    def _surface_z(self, trigger_position):
        surface = list(trigger_position)
        surface[2] += self.trigger_offset
        return surface

    def _active_wcs(self, gcmd):
        wcs = self.printer.lookup_object("work_coordinate_systems", None)
        if wcs is None:
            raise gcmd.error("COORD=WCS requires [work_coordinate_systems]")
        if wcs.machine_mode:
            raise gcmd.error("COORD=WCS requires active G54-G59")
        if not wcs.applied:
            raise gcmd.error("COORD=WCS requires homed and applied WCS")
        return wcs

    @staticmethod
    def _upper_param(gcmd, name, default):
        return str(gcmd.get(name, default)).strip().upper()

    @staticmethod
    def _finite(value):
        return math.isfinite(float(value))

    def _z_hop_up(self, gcmd):
        hop = gcmd.get_float("Z_HOP", self.z_hop, above=0.0)
        speed = gcmd.get_float(
            "Z_HOP_SPEED", self.z_hop_speed, above=0.0
        )
        toolhead = self.printer.lookup_object("toolhead")
        position = toolhead.get_position()
        _, axis_max = self._limits(2)
        destination = min(axis_max, position[2] + hop)
        actual = destination - position[2]
        if actual < hop - 0.000001:
            raise gcmd.error(
                "Insufficient positive Z travel for requested Z_HOP"
            )
        self._move_axis(2, destination, speed)
        return actual

    def _z_hop_down(self, gcmd, actual_hop):
        if actual_hop <= 0.0:
            return
        speed = gcmd.get_float(
            "Z_HOP_SPEED", self.z_hop_speed, above=0.0
        )
        position = self.printer.lookup_object("toolhead").get_position()
        axis_min, _ = self._limits(2)
        destination = max(axis_min, position[2] - actual_hop)
        self._move_axis(2, destination, speed)

    def _set_wcs(self, gcmd, machine_position, values):
        if not gcmd.get_int("SET_ZERO", 0, minval=0, maxval=1):
            return
        wcs = self.printer.lookup_object("work_coordinate_systems", None)
        if wcs is None:
            raise gcmd.error("SET_ZERO requires [work_coordinate_systems]")
        if wcs.machine_mode:
            raise gcmd.error("Select G54-G59 before setting a work zero")
        wcs.set_from_machine_position(wcs.active_wcs, machine_position, values)

    def _raw_probe(self, gcmd, direction):
        result = self._probe(gcmd, direction)
        gcmd.respond_info(
            "Probe %s triggered at X=%.6f Y=%.6f Z=%.6f"
            % (direction, result[0], result[1], result[2])
        )

    def _find_edge(self, gcmd, direction):
        axis, _ = DIRECTIONS[direction]
        self._require_safe(gcmd, "XYZ")
        result = self._probe(gcmd, direction)
        edge = self._edge(result, direction)
        self._set_wcs(gcmd, edge, {axis: 0.0})
        self._z_hop_up(gcmd)
        self._move_axis(
            axis,
            edge[axis],
            self._travel_speed(gcmd),
        )
        gcmd.respond_info(
            "%s edge: raw %.6f, compensated %.6f%s"
            % (
                AXIS_NAMES[axis],
                result[axis],
                edge[axis],
                ", work zero updated" if gcmd.get_int("SET_ZERO", 0) else "",
            )
        )

    def _find_surface_z(self, gcmd):
        self._require_safe(gcmd, "XYZ")
        result = self._probe(gcmd, "Z-")
        surface = self._surface_z(result)
        self._set_wcs(gcmd, surface, {2: 0.0})
        gcmd.respond_info(
            "Z surface: raw %.6f, compensated %.6f%s"
            % (
                result[2],
                surface[2],
                ", work zero updated" if gcmd.get_int("SET_ZERO", 0) else "",
            )
        )

    def _surface_bounds(self, gcmd):
        has_width = gcmd.get_float("WIDTH", None) is not None
        has_height = gcmd.get_float("HEIGHT", None) is not None
        explicit = {
            name: gcmd.get_float(name, None)
            for name in ("X_MIN", "X_MAX", "Y_MIN", "Y_MAX")
        }
        has_explicit = any(value is not None for value in explicit.values())
        if has_explicit and not all(value is not None for value in explicit.values()):
            raise gcmd.error("Explicit surface bounds require X_MIN X_MAX Y_MIN Y_MAX")

        coord = self._upper_param(gcmd, "COORD", "")
        if not coord:
            coord = "WCS" if has_width or has_height or has_explicit else "MACHINE"
        if coord not in ("MACHINE", "WCS"):
            raise gcmd.error("COORD must be MACHINE or WCS")

        if has_width != has_height:
            raise gcmd.error("WIDTH and HEIGHT must be provided together")

        if has_explicit:
            bounds = {
                "x_min": float(explicit["X_MIN"]),
                "x_max": float(explicit["X_MAX"]),
                "y_min": float(explicit["Y_MIN"]),
                "y_max": float(explicit["Y_MAX"]),
            }
            margin = gcmd.get_float("MARGIN", 0.0, minval=0.0)
        elif has_width:
            if coord != "WCS":
                raise gcmd.error("WIDTH/HEIGHT surface measuring requires COORD=WCS")
            margin = gcmd.get_float("MARGIN", 5.0, minval=0.0)
            width = gcmd.get_float("WIDTH", above=0.0)
            height = gcmd.get_float("HEIGHT", above=0.0)
            bounds = {
                "x_min": margin,
                "x_max": width - margin,
                "y_min": margin,
                "y_max": height - margin,
            }
        elif coord == "MACHINE":
            margin = gcmd.get_float("MARGIN", 10.0, minval=0.0)
            x_min, x_max = self._limits(0)
            y_min, y_max = self._limits(1)
            bounds = {
                "x_min": float(x_min) + margin,
                "x_max": float(x_max) - margin,
                "y_min": float(y_min) + margin,
                "y_max": float(y_max) - margin,
            }
        else:
            raise gcmd.error(
                "COORD=WCS requires WIDTH/HEIGHT or X_MIN/X_MAX/Y_MIN/Y_MAX"
            )

        if bounds["x_min"] >= bounds["x_max"] or bounds["y_min"] >= bounds["y_max"]:
            raise gcmd.error("Surface bounds are too small after margin")
        if not all(self._finite(value) for value in bounds.values()):
            raise gcmd.error("Invalid surface bounds")
        return coord, margin, bounds

    def _surface_points(self, gcmd, bounds):
        pattern = self._upper_param(gcmd, "PATTERN", "CORNERS_4")
        if pattern in ("4", "CORNERS", "CORNERS4"):
            pattern = "CORNERS_4"
        elif pattern in ("5", "CROSS", "CROSS5"):
            pattern = "CROSS_5"
        if pattern == "CORNERS_4":
            points = (
                ("FL", bounds["x_min"], bounds["y_min"]),
                ("FR", bounds["x_max"], bounds["y_min"]),
                ("RL", bounds["x_min"], bounds["y_max"]),
                ("RR", bounds["x_max"], bounds["y_max"]),
            )
        elif pattern == "CROSS_5":
            center_x = (bounds["x_min"] + bounds["x_max"]) / 2.0
            center_y = (bounds["y_min"] + bounds["y_max"]) / 2.0
            points = (
                ("CENTER", center_x, center_y),
                ("FRONT", center_x, bounds["y_min"]),
                ("RIGHT", bounds["x_max"], center_y),
                ("REAR", center_x, bounds["y_max"]),
                ("LEFT", bounds["x_min"], center_y),
            )
        else:
            raise gcmd.error("PATTERN must be CORNERS_4 or CROSS_5")
        return pattern, points

    def _to_machine_xy(self, gcmd, coord, x, y):
        if coord == "MACHINE":
            return x, y
        wcs = self._active_wcs(gcmd)
        offset = wcs.wcs[wcs.active_wcs]
        return x + float(offset[0]), y + float(offset[1])

    def _probe_surface_point(self, gcmd, coord, name, x, y):
        travel_speed = self._travel_speed(gcmd)
        machine_x, machine_y = self._to_machine_xy(gcmd, coord, x, y)
        x_min, x_max = self._limits(0)
        y_min, y_max = self._limits(1)
        if not (x_min <= machine_x <= x_max and y_min <= machine_y <= y_max):
            raise gcmd.error("Surface point %s is outside machine limits" % (name,))
        self._z_hop_up(gcmd)
        self._move_xy(machine_x, machine_y, travel_speed)
        hit = self._probe(gcmd, "Z-")
        surface = self._surface_z(hit)
        return {
            "name": name,
            "x": float(x),
            "y": float(y),
            "machine_x": float(machine_x),
            "machine_y": float(machine_y),
            "z": float(surface[2]),
        }

    def _surface_summary(self, pattern, points):
        z_values = [point["z"] for point in points]
        minimum = min(z_values)
        maximum = max(z_values)
        low = min(points, key=lambda point: point["z"])
        high = max(points, key=lambda point: point["z"])
        summary = {
            "min_z": minimum,
            "max_z": maximum,
            "range": maximum - minimum,
            "average": sum(z_values) / len(z_values),
            "low_point": low["name"],
            "high_point": high["name"],
        }
        by_name = {point["name"]: point for point in points}
        if pattern == "CORNERS_4":
            summary.update(
                {
                    "front_delta": by_name["FR"]["z"] - by_name["FL"]["z"],
                    "rear_delta": by_name["RR"]["z"] - by_name["RL"]["z"],
                    "left_delta": by_name["RL"]["z"] - by_name["FL"]["z"],
                    "right_delta": by_name["RR"]["z"] - by_name["FR"]["z"],
                    "twist": (
                        by_name["RR"]["z"]
                        + by_name["FL"]["z"]
                        - by_name["FR"]["z"]
                        - by_name["RL"]["z"]
                    ),
                }
            )
        elif pattern == "CROSS_5":
            edges = [
                by_name[name]["z"] for name in ("FRONT", "RIGHT", "REAR", "LEFT")
            ]
            summary.update(
                {
                    "x_delta": by_name["RIGHT"]["z"] - by_name["LEFT"]["z"],
                    "y_delta": by_name["REAR"]["z"] - by_name["FRONT"]["z"],
                    "center_error": by_name["CENTER"]["z"] - sum(edges) / len(edges),
                }
            )
        return summary

    def cmd_MEASURE_SURFACE_TILT(self, gcmd):
        self._require_safe(gcmd, "XYZ")
        start = list(self.printer.lookup_object("toolhead").get_position())
        coord, margin, bounds = self._surface_bounds(gcmd)
        if coord == "WCS":
            self._active_wcs(gcmd)
        pattern, requested_points = self._surface_points(gcmd, bounds)
        measured = [
            self._probe_surface_point(gcmd, coord, name, x, y)
            for name, x, y in requested_points
        ]
        self._z_hop_up(gcmd)
        if gcmd.get_int("RETURN", 1, minval=0, maxval=1):
            self._move_xy(start[0], start[1], self._travel_speed(gcmd))
        summary = self._surface_summary(pattern, measured)
        self.surface_result = {
            "type": "tilt",
            "coord": coord.lower(),
            "pattern": pattern,
            "bounds": bounds,
            "margin": margin,
            "points": measured,
            "summary": summary,
        }
        self.last_command = gcmd.get_command()
        self._persist_surface_result()
        gcmd.respond_info(
            "Surface tilt %s %s: range %.6f, high %s, low %s, saved %s"
            % (
                coord,
                pattern,
                summary["range"],
                summary["high_point"],
                summary["low_point"],
                self.surface_result_path,
            )
        )

    def _find_center(
        self, gcmd, axis, distance, leave_hopped=True, set_zero=True
    ):
        self._require_safe(gcmd, "XYZ")
        direction_pos = AXIS_NAMES[axis] + "+"
        direction_neg = AXIS_NAMES[axis] + "-"
        travel_speed = self._travel_speed(gcmd)
        overshoot = gcmd.get_float(
            "OVERSHOOT", self.overshoot, above=0.0
        )
        positive = self._edge(self._probe(gcmd, direction_pos), direction_pos)
        actual_hop = self._z_hop_up(gcmd)
        current = self.printer.lookup_object("toolhead").get_position()
        _, axis_max = self._limits(axis)
        requested_travel = positive[axis] + distance + overshoot
        travel = min(axis_max, requested_travel)
        if travel < requested_travel - 0.000001 or travel <= current[axis]:
            raise gcmd.error("Insufficient travel to cross the workpiece")
        self._move_axis(axis, travel, travel_speed)
        self._z_hop_down(gcmd, actual_hop)
        negative = self._edge(self._probe(gcmd, direction_neg), direction_neg)
        final_hop = self._z_hop_up(gcmd)
        center = (positive[axis] + negative[axis]) / 2.0
        self._move_axis(axis, center, travel_speed)
        if set_zero:
            self._set_wcs(
                gcmd,
                [center if i == axis else negative[i] for i in range(3)],
                {axis: 0.0},
            )
        if not leave_hopped:
            self._z_hop_down(gcmd, final_hop)
        gcmd.respond_info(
            "%s center %.6f, measured width %.6f%s"
            % (
                AXIS_NAMES[axis],
                center,
                abs(positive[axis] - negative[axis]),
                (
                    ", work zero updated"
                    if set_zero and gcmd.get_int("SET_ZERO", 0)
                    else ""
                ),
            )
        )
        return center, final_hop

    def cmd_QUERY_TOUCH_PROBE(self, gcmd):
        state = "TRIGGERED" if self._query_triggered() else "ready"
        gcmd.respond_info("Touch probe: %s" % (state,))

    def cmd_PROBE_X_POS(self, gcmd):
        self._raw_probe(gcmd, "X+")

    def cmd_PROBE_X_NEG(self, gcmd):
        self._raw_probe(gcmd, "X-")

    def cmd_PROBE_Y_POS(self, gcmd):
        self._raw_probe(gcmd, "Y+")

    def cmd_PROBE_Y_NEG(self, gcmd):
        self._raw_probe(gcmd, "Y-")

    def cmd_PROBE_Z_NEG(self, gcmd):
        self._raw_probe(gcmd, "Z-")

    def cmd_FIND_EDGE_X_POS(self, gcmd):
        self._find_edge(gcmd, "X+")

    def cmd_FIND_EDGE_X_NEG(self, gcmd):
        self._find_edge(gcmd, "X-")

    def cmd_FIND_EDGE_Y_POS(self, gcmd):
        self._find_edge(gcmd, "Y+")

    def cmd_FIND_EDGE_Y_NEG(self, gcmd):
        self._find_edge(gcmd, "Y-")

    def cmd_FIND_SURFACE_Z(self, gcmd):
        self._find_surface_z(gcmd)

    def cmd_FIND_CENTER_X(self, gcmd):
        self._find_center(
            gcmd, 0, gcmd.get_float("DISTANCE", above=0.0)
        )

    def cmd_FIND_CENTER_Y(self, gcmd):
        self._find_center(
            gcmd, 1, gcmd.get_float("DISTANCE", above=0.0)
        )

    def cmd_FIND_CENTER_XY(self, gcmd):
        distance_x = gcmd.get_float("DISTANCE_X", above=0.0)
        distance_y = gcmd.get_float("DISTANCE_Y", above=0.0)
        overshoot = gcmd.get_float(
            "OVERSHOOT", self.overshoot, above=0.0
        )
        travel_speed = self._travel_speed(gcmd)
        center_x, x_hop = self._find_center(
            gcmd,
            0,
            distance_x,
            set_zero=False,
        )

        toolhead = self.printer.lookup_object("toolhead")
        y_min, _ = self._limits(1)
        position = toolhead.get_position()
        y_start = position[1] - distance_y / 2.0 - overshoot
        if y_start < y_min:
            raise gcmd.error(
                "Insufficient negative Y travel to start center probing"
            )
        self._move_axis(1, y_start, travel_speed)
        self._z_hop_down(gcmd, x_hop)

        center_y, _ = self._find_center(
            gcmd, 1, distance_y, set_zero=False
        )
        position = list(toolhead.get_position())
        position[0] = center_x
        position[1] = center_y
        self._set_wcs(gcmd, position, {0: 0.0, 1: 0.0})
        gcmd.respond_info(
            "XY center X=%.6f Y=%.6f" % (center_x, center_y)
        )

    def cmd_PROBE_BORE(self, gcmd):
        self._require_safe(gcmd, "XYZ")
        toolhead = self.printer.lookup_object("toolhead")
        start = list(toolhead.get_position())
        travel_speed = self._travel_speed(gcmd)
        edges = {}
        for direction in ("X+", "X-", "Y+", "Y-"):
            edges[direction] = self._edge(
                self._probe(gcmd, direction), direction
            )
            self._move_axis(0, start[0], travel_speed)
            self._move_axis(1, start[1], travel_speed)
        center_x = (edges["X+"][0] + edges["X-"][0]) / 2.0
        center_y = (edges["Y+"][1] + edges["Y-"][1]) / 2.0
        diameter_x = abs(edges["X+"][0] - edges["X-"][0])
        diameter_y = abs(edges["Y+"][1] - edges["Y-"][1])
        average_diameter = (diameter_x + diameter_y) / 2.0
        actual_hop = self._z_hop_up(gcmd)
        self._move_axis(0, center_x, travel_speed)
        self._move_axis(1, center_y, travel_speed)
        self._set_wcs(
            gcmd,
            [center_x, center_y, start[2] + actual_hop],
            {0: 0.0, 1: 0.0},
        )
        gcmd.respond_info(
            "Bore center X=%.6f Y=%.6f, diameter X=%.6f Y=%.6f avg=%.6f%s"
            % (
                center_x,
                center_y,
                diameter_x,
                diameter_y,
                average_diameter,
                ", work zero updated" if gcmd.get_int("SET_ZERO", 0) else "",
            )
        )

    def get_status(self, eventtime=None):
        return {
            "triggered": self.probe_triggered,
            "last_command": self.last_command,
            "last_result": self.last_result,
            "surface_result": self.surface_result,
        }


def load_config(config):
    return TouchProbe(config)
