# Experimental Klipper CNC Extras

This repository includes two optional Klipper modules:

- `work_coordinate_systems.py` adds persistent G54-G59 work coordinates,
  G53 machine mode, and G10 L2/L20.
- `touch_probe.py` adds guarded XY stylus probing for edges, centers, and
  bores.
- `tool_touch_probe.py` uses the installed cutting tool and a conductive plate
  to set work Z.

The WCS and XY probe modules were originally developed by **Shadowphyre from
the E3CNC Discord community** and shared for beta testing. Klipper Screen CNC
hardens and extends them for this fork. The cutting-tool Z workflow is a
separate module derived from the same endstop-probing approach.

!!! warning

    These modules can move a CNC machine outside ordinary G-code execution.
    Test every direction with the spindle off, low speeds, generous clearance,
    and immediate access to an emergency stop.

## Install

Copy the modules into the active Klipper source tree:

```sh
cp klipper-extras/work_coordinate_systems.py ~/klipper/klippy/extras/
cp klipper-extras/touch_probe.py ~/klipper/klippy/extras/
cp klipper-extras/tool_touch_probe.py ~/klipper/klippy/extras/
```

On installations where Klipper lives elsewhere, copy them into that
installation's `klippy/extras/` directory. Restart Klipper after adding or
updating either file.

## Work Coordinate Systems

Add:

```ini
[work_coordinate_systems]
persist_file: ~/printer_data/config/wcs_offsets.json
```

The module intentionally waits until XYZ are homed before applying the saved
WCS. This prevents stale offsets from altering the unhomed coordinate state
after a restart. Selecting G54-G59 is persisted automatically.

Available commands:

```gcode
G54
G55
G53
G10 L2 P1 X10 Y20 Z30
G10 L20 P1 X0 Y0 Z0
WCS_STATUS
SAVE_WCS
```

`G53` remains modal in this experimental implementation. Select G54-G59 again
after machine-coordinate work. The bundled cancel/end macros already restore
the active WCS after parking.

## XY Stylus Probe

This probe is mounted in the ER11 collet and locates workpiece geometry in X
and Y. Replacing it with a cutting tool does not invalidate XY because both
tools share the spindle centerline. It must not be used to establish Z: the
cutting tool has a different length after the stylus is removed.

Example configuration:

```ini
[touch_probe]
pin: ^!PC5
fast_speed: 10
slow_speed: 0.5
max_distance: 50
retract_distance: 2
tip_diameter: 4.97
trigger_offset: 0
z_hop: 10
z_hop_speed: 10
overshoot: 10
samples: 1
spindle_object: output_pin spindle
```

The plugin rejects probing while a virtual-SD job is printing or paused, while
the configured spindle output is nonzero, when required axes are unhomed, or
when the probe is already triggered. A hop-over command also aborts if the full
requested Z clearance is unavailable within machine limits.

Raw and diagnostic commands:

```gcode
QUERY_TOUCH_PROBE
PROBE_X_POS
PROBE_X_NEG
PROBE_Y_POS
PROBE_Y_NEG
```

Workpiece commands:

```gcode
FIND_EDGE_X_POS
FIND_EDGE_X_NEG
FIND_EDGE_Y_POS
FIND_EDGE_Y_NEG
FIND_CENTER_X DISTANCE=40
FIND_CENTER_Y DISTANCE=30
FIND_CENTER_XY DISTANCE_X=40 DISTANCE_Y=30
PROBE_BORE
```

Add `SET_ZERO=1` to a workpiece command to update the currently selected
G54-G59 coordinate directly:

```gcode
FIND_EDGE_X_NEG SET_ZERO=1
FIND_CENTER_XY DISTANCE_X=40 DISTANCE_Y=30 SET_ZERO=1
```

This does not use `G92`. The probe result is captured in machine coordinates,
then converted into a persistent WCS offset even though the tool has already
retracted from the contact surface.

## Calibration

`trigger_offset` is the empirical XY overtravel correction used together
with half the probe-tip diameter. It must be zero or positive.

Probe parameters such as `FAST_SPEED`, `SLOW_SPEED`, `MAX_DISTANCE`,
`RETRACT_DISTANCE`, `SAMPLES`, `Z_HOP`, `Z_HOP_SPEED`, and `OVERSHOOT` may be
overridden per command.

## Cutting-tool Z Touch-off

Configure the separate module:

```ini
[tool_touch_probe]
pin: ^!PC5
fast_speed: 5
slow_speed: 0.5
max_distance: 25
retract_distance: 2
final_retract: 5
plate_thickness: 5
trigger_offset: 0
samples: 1
spindle_object: output_pin spindle
```

The XY stylus and tool plate may share the same input pin. The modules attach
that pin to different machine axes and never probe them simultaneously.

After installing or changing a cutting tool:

1. Home XYZ and select the intended G54-G59 WCS.
2. Keep the spindle off.
3. Place the conductive plate on the workpiece surface.
4. Connect the probe lead and verify the circuit:

   ```gcode
   QUERY_TOOL_TOUCH_PROBE
   ```

5. Touch off using the configured plate thickness:

   ```gcode
   TOUCH_OFF_Z
   ```

   Override it for a different plate when needed:

   ```gcode
   TOUCH_OFF_Z PLATE_THICKNESS=10
   ```

6. Remove the lead and plate before starting the spindle.

`TOUCH_OFF_Z` probes down, retracts, repeats at slow speed, sets the active WCS
so the contact point equals the configured `plate_thickness` or command
`PLATE_THICKNESS` override, then leaves the tool retracted.
It always updates work Z; use `PROBE_TOOL_Z` for a raw diagnostic probe that
does not modify WCS.

Run Z touch-off again after every tool change. This workflow is for a movable
plate placed on the workpiece. A fixed machine tool setter requires tool-length
offset handling and should not directly rewrite WCS Z.

`trigger_offset` is a zero-or-positive correction added to the raw electrical
trigger coordinate. Calibrate it using a known plate at the same slow speed
used for normal touch-off.
