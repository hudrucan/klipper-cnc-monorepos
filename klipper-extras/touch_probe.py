# CNC XY touch probing for Klipper.
#
# Originally developed by Shadowphyre from the E3CNC Discord community
# and shared for beta testing. Hardened and extended by Klipper Screen CNC.
#
# Experimental: prove every direction at low speed with the spindle disabled
# before relying on these commands near a workpiece.

import logging

DIRECTIONS = {
    "X+": (0, 1),
    "X-": (0, -1),
    "Y+": (1, 1),
    "Y-": (1, -1),
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

        self.endstops = {
            0: ProbeEndstopWrapper(config, "x"),
            1: ProbeEndstopWrapper(config, "y"),
        }
        self.last_result = None
        self.last_command = None
        self.probe_triggered = None

        commands = {
            "QUERY_TOUCH_PROBE": self.cmd_QUERY_TOUCH_PROBE,
            "PROBE_X_POS": self.cmd_PROBE_X_POS,
            "PROBE_X_NEG": self.cmd_PROBE_X_NEG,
            "PROBE_Y_POS": self.cmd_PROBE_Y_POS,
            "PROBE_Y_NEG": self.cmd_PROBE_Y_NEG,
            "FIND_EDGE_X_POS": self.cmd_FIND_EDGE_X_POS,
            "FIND_EDGE_X_NEG": self.cmd_FIND_EDGE_X_NEG,
            "FIND_EDGE_Y_POS": self.cmd_FIND_EDGE_Y_POS,
            "FIND_EDGE_Y_NEG": self.cmd_FIND_EDGE_Y_NEG,
            "FIND_CENTER_X": self.cmd_FIND_CENTER_X,
            "FIND_CENTER_Y": self.cmd_FIND_CENTER_Y,
            "FIND_CENTER_XY": self.cmd_FIND_CENTER_XY,
            "PROBE_BORE": self.cmd_PROBE_BORE,
        }
        for name, handler in commands.items():
            self.gcode.register_command(name, handler)

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
            gcmd.get_float("FAST_SPEED", self.fast_speed, above=0.0),
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

    def _find_center(
        self, gcmd, axis, distance, leave_hopped=True, set_zero=True
    ):
        self._require_safe(gcmd, "XYZ")
        direction_pos = AXIS_NAMES[axis] + "+"
        direction_neg = AXIS_NAMES[axis] + "-"
        fast_speed = gcmd.get_float(
            "FAST_SPEED", self.fast_speed, above=0.0
        )
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
        self._move_axis(axis, travel, fast_speed)
        self._z_hop_down(gcmd, actual_hop)
        negative = self._edge(self._probe(gcmd, direction_neg), direction_neg)
        final_hop = self._z_hop_up(gcmd)
        center = (positive[axis] + negative[axis]) / 2.0
        self._move_axis(axis, center, fast_speed)
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
        state = "TRIGGERED" if self._query_triggered() else "open"
        gcmd.respond_info("Touch probe: %s" % (state,))

    def cmd_PROBE_X_POS(self, gcmd):
        self._raw_probe(gcmd, "X+")

    def cmd_PROBE_X_NEG(self, gcmd):
        self._raw_probe(gcmd, "X-")

    def cmd_PROBE_Y_POS(self, gcmd):
        self._raw_probe(gcmd, "Y+")

    def cmd_PROBE_Y_NEG(self, gcmd):
        self._raw_probe(gcmd, "Y-")

    def cmd_FIND_EDGE_X_POS(self, gcmd):
        self._find_edge(gcmd, "X+")

    def cmd_FIND_EDGE_X_NEG(self, gcmd):
        self._find_edge(gcmd, "X-")

    def cmd_FIND_EDGE_Y_POS(self, gcmd):
        self._find_edge(gcmd, "Y+")

    def cmd_FIND_EDGE_Y_NEG(self, gcmd):
        self._find_edge(gcmd, "Y-")

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
        fast_speed = gcmd.get_float(
            "FAST_SPEED", self.fast_speed, above=0.0
        )
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
        self._move_axis(1, y_start, fast_speed)
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
        fast_speed = gcmd.get_float(
            "FAST_SPEED", self.fast_speed, above=0.0
        )
        edges = {}
        for direction in ("X+", "X-", "Y+", "Y-"):
            edges[direction] = self._edge(
                self._probe(gcmd, direction), direction
            )
            self._move_axis(0, start[0], fast_speed)
            self._move_axis(1, start[1], fast_speed)
        center_x = (edges["X+"][0] + edges["X-"][0]) / 2.0
        center_y = (edges["Y+"][1] + edges["Y-"][1]) / 2.0
        diameter_x = abs(edges["X+"][0] - edges["X-"][0])
        diameter_y = abs(edges["Y+"][1] - edges["Y-"][1])
        average_diameter = (diameter_x + diameter_y) / 2.0
        actual_hop = self._z_hop_up(gcmd)
        self._move_axis(0, center_x, fast_speed)
        self._move_axis(1, center_y, fast_speed)
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
        }


def load_config(config):
    return TouchProbe(config)
