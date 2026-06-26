# Example CNC Macros

The repository includes optional Klipper configuration examples:

- [`cnc_pause_resume.cfg`](https://github.com/hudrucan/klipper-screen-cnc/blob/master/config/examples/cnc_pause_resume.cfg)
- [`cnc_spindle.cfg`](https://github.com/hudrucan/klipper-screen-cnc/blob/master/config/examples/cnc_spindle.cfg)
- [`cnc_start_end.cfg`](https://github.com/hudrucan/klipper-screen-cnc/blob/master/config/examples/cnc_start_end.cfg)
- [`cnc_homing_override.cfg`](https://github.com/hudrucan/klipper-screen-cnc/blob/master/config/examples/cnc_homing_override.cfg)
- [`cnc_touch_probe.cfg`](https://github.com/hudrucan/klipper-screen-cnc/blob/master/config/examples/cnc_touch_probe.cfg)
- [`cnc_tool_setter.cfg`](https://github.com/hudrucan/klipper-screen-cnc/blob/master/config/examples/cnc_tool_setter.cfg)

Copy the required files into `~/printer_data/config/`, review every machine-specific
value, then include them from `printer.cfg`:

```ini
[include cnc_pause_resume.cfg]
[include cnc_spindle.cfg]
[include cnc_start_end.cfg]
[include cnc_homing_override.cfg]
[include cnc_touch_probe.cfg]
[include cnc_tool_setter.cfg]
```

Run `RESTART` after validating the configuration.

## Pause, Resume, and Cancel

Remove the complete Mainsail include from `printer.cfg`:

```ini
# Remove this:
[include mainsail.cfg]
```

The CNC pause example replaces the required job-control sections itself:

- `[virtual_sdcard]`
- `[pause_resume]`
- `[display_status]`
- `PAUSE`
- `RESUME`
- `CANCEL_PRINT`

- Pause stops file motion, lifts Z while the spindle is still running, then stops it.
- Resume is rejected while the spindle output is off.
- The operator starts the spindle manually and waits for it to stabilize before Resume.
- Cancel stops file motion, retracts Z while the spindle is running, stops the spindle,
  parks XY in machine coordinates, then restores the previously active WCS.
- `on_error_gcode: CANCEL_PRINT` ensures a virtual SD error also stops the spindle.

The example expects `[work_coordinate_systems]`, `[output_pin spindle]`, `M3`, and `M5`
to exist. Adjust the pause lift, cancel clearance, park coordinates, and movement speeds
for the machine.

Do not include `mainsail.cfg` at the same time. Duplicate base sections and command
overrides will prevent Klipper from loading.

## Guarded Spindle

`cnc_spindle.cfg` defines guarded `M3` and `M5` macros for machines where the
touch probe has a wire or clip that must be removed before the spindle rotates.

- `M3` first checks `[touch_probe]`.
- If the probe is triggered, disconnected, or miswired so it reports triggered,
  `M3` forces the spindle output off and aborts.
- `M5` always turns the spindle output off.

Place this guard in the Klipper macro layer, not only in KlipperScreen, so MDI,
uploaded G-code, macros, and the Spindle panel all share the same safety check.
The example treats `M3 S1000` as full output and clamps larger Fusion RPM values
to full output. Adjust `variable_s_scale` if your spindle output uses a different
PWM convention.

## Homing Override

The homing example reads the axes passed to `G28`, allowing the touchscreen's Home X,
Home Y, Home Z, Home XY, and Home All actions to remain distinct.

The supplied example assumes Z and Y home at their upper limits while X homes at its
lower limit. Home All homes Z first, homes and releases X, then homes and releases Y.
The X/Y release moves use `G91`, so an active WCS offset cannot change their direction
or clearance distance.
Individual Home X and Home Y actions remain selectable, but first home Z when its
position is unknown or below the configured safe height.

Adjust `clearance_from_top`, `x_clearance`, `y_clearance`, and `clearance_speed` in the
example for the machine. With a Z maximum of 65 mm and `clearance_from_top: 10`, X/Y
homing requires Z to be at least 55 mm high. Test each axis with the spindle stopped and
enough physical clearance to reach an emergency stop.

## Fusion Job Start and End

`cnc_start_end.cfg` is separate from pause/resume/cancel because it defines the
interface used by the Fusion 360 post processor.

- `START_PRINT` validates complete job bounds against machine limits.
- A valid start explicitly selects millimeters and absolute positioning with
  `G21` and `G90`, preventing a previous manual `G91` jog from leaking into the
  toolpath.
- It does not home, select a WCS, or start the spindle.
- `END_PRINT` retracts Z, stops the spindle, and parks XY.
- Include `cnc_pause_resume.cfg` first because `END_PRINT` reuses its park helpers.

Use the bundled
[Fusion 360 post processor](https://github.com/hudrucan/klipper-screen-cnc/tree/master/tools/fusion360)
so `START_PRINT` receives complete-file bounds once per generated job.

## Touch Probe Macros

`cnc_touch_probe.cfg` wraps the guarded `[touch_probe]` commands with
KlipperScreen-friendly macro names:

- `CHECK_TOUCH_PROBE`
- `PROBE_STOCK_Z`
- `FIND_STOCK_X_MIN`
- `FIND_STOCK_X_MAX`
- `FIND_STOCK_Y_MIN`
- `FIND_STOCK_Y_MAX`
- `CENTER_STOCK_X`
- `CENTER_STOCK_Y`
- `CENTER_STOCK_XY`
- `PROBE_BORE_CENTER`

The macros update the active G54-G59 WCS directly through `SET_ZERO=1`.
The center macros accept `DISTANCE`, `DISTANCE_X`, and `DISTANCE_Y` overrides.
When omitted, they use the full machine travel for that axis so the button can
work without per-job input. Passing an approximate stock size plus clearance is
faster and reduces unnecessary travel:

```gcode
CENTER_STOCK_X DISTANCE=120
CENTER_STOCK_XY DISTANCE_X=120 DISTANCE_Y=80
```

## Fixed Tool Setter Macros

`cnc_tool_setter.cfg` wraps the guarded `[tool_setter]` commands:

- `CHECK_TOOL_SETTER`
- `CHECK_SETTER_ACCURACY`
- `CALIBRATE_TOOL_SETTER_Z`
- `CHECK_BIT_Z`
- `APPLY_BIT_Z`

Use the dry-run `CHECK_BIT_Z` first to review the calculated WCS Z change.
`APPLY_BIT_Z` probes again and applies the active WCS Z correction with
`SET_BIT_Z APPLY=1`.
