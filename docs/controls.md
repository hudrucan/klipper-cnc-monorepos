# CNC Controls

## Jog and DRO

- Jog uses incremental relative moves and restores the previous G-code state.
- DRO shows machine, work, and offset coordinates.
- Home the relevant axes before jogging or setting a work zero.

## WCS

The WCS panel displays available work offsets and the active coordinate system. It can
set the current X, Y, Z, or all axes to zero and move in the XY map after confirmation.

## Spindle

The spindle panel appears when Klipper exposes `M3`, `M5`, and an
`[output_pin spindle]` section. `M4` enables counter-clockwise control.

Verify spindle direction and emergency-stop behavior before attaching a cutting tool.

## Motion Override

Open Motion Override by tapping the override card in CNC Status or CNC Run.

- Adjustment buttons: `-10%`, `-5%`, `+5%`, `+10%`
- Presets: `25%`, `50%`, `75%`, `100%`, `125%`, `150%`
- Allowed range: `10%` to `150%`
- Reset returns to `100%`

The control sends Klipper's native `M220 S<percent>` command. In Klipper, this scales
both `G0` and `G1` motion, so it is intentionally named Motion Override rather than a
cutting-feed-only override.

The configured velocity and acceleration limits remain hard runtime limits. Motion
Override cannot command movement beyond those limits.

## MDI

The MDI panel stores the last 50 submitted commands and reloads them after
Klipper Screen CNC restarts. By default the history is saved to
`~/printer_data/config/mdi_history.json`, falling back to
`~/.config/klipper_screen/mdi_history.json` when `printer_data` is unavailable.

Override the location in `klipper_screen.conf`:

```ini
[main]
mdi_history_path: ~/printer_data/config/cnc_mdi_history.json
```

## Emergency stop

Emergency Stop sends Moonraker's printer emergency-stop request. A touchscreen control
is not a substitute for a hard-wired emergency-stop circuit.
