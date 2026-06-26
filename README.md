# Klipper Screen CNC

A CNC-focused fork of [KlipperScreen](https://github.com/KlipperScreen/KlipperScreen), built for touchscreen control of Klipper-based CNC machines.

This fork removes most 3D-printer-specific UI and replaces it with a compact CNC workflow:

- DRO with machine and work coordinates
- Safer incremental jogging
- Interactive WCS selection and XY map
- MDI and G-code macro access
- Spindle clockwise, counter-clockwise, and stop controls
- Motion Override control using Klipper's native `M220`
- Probe dashboard for touch probe, fixed tool setter, surface measure, and result history
- CNC G-code file list with upload-date sorting and optional CAM thumbnails
- CNC-oriented run status, progress, pause, resume, restart, and cancel
- Optional `cnc-dark-red` theme for a darker CNC controller look
- Limits, network, system, and shutdown controls
- Optional Moonraker-side CNC metadata sidecars and toolpath thumbnails
- Optional Moonraker-side `/server/cnc/*` compatibility API for the upstream
  E3CNC frontend

## Status

This project is under active development and currently targets our own Klipper CNC setup. Treat it as experimental machine-control software: verify motion directions, limits, spindle wiring, and emergency-stop behavior before running a toolpath.

## Requirements

- Klipper
- Moonraker
- A Linux host with a GTK 3-compatible display
- Python 3.9 or newer
- A configured touchscreen or mouse

Spindle controls are shown when Klipper exposes the `M3` and `M5` commands and an
`[output_pin spindle]` section. `M4` enables the counter-clockwise control.
If a wired touch probe can be left attached near the spindle, use the guarded
`M3` example in `config/examples/cnc_spindle.cfg`. For normally-closed probes,
spindle start is allowed only after the probe wire is removed and the probe input
reports triggered/open.

## Install

Remove or disable an existing upstream KlipperScreen installation first. Running both
services can open two interfaces on the same display and cause confusing restart or
configuration behavior.

```bash
sudo systemctl disable --now KlipperScreen.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/KlipperScreen.service
sudo systemctl daemon-reload
mv ~/KlipperScreen ~/KlipperScreen.backup 2>/dev/null || true
mv ~/.KlipperScreen-env ~/.KlipperScreen-env.backup 2>/dev/null || true
mv ~/.config/KlipperScreen ~/.config/KlipperScreen.backup 2>/dev/null || true
mv ~/printer_data/config/KlipperScreen.conf \
  ~/printer_data/config/KlipperScreen.conf.backup 2>/dev/null || true
rm -f ~/.local/share/applications/KlipperScreen.desktop
```

Keep the old config as a reference, then install the fork:

```bash
git clone https://github.com/hudrucan/klipper-screen-cnc.git
cd klipper-screen-cnc
./scripts/KlipperScreen-install.sh
sudo systemctl restart klipper-screen
```

The installer creates `klipper-screen.service` and uses `~/.klipper-screen-env` for
the Python virtual environment by default.

For Mainsail/Fluidd updates, add the optional Moonraker
`[update_manager klipper-screen]` block from
[installation](docs/installation.md#moonraker-update-manager). The repo includes
`scripts/KlipperScreen-update.sh` for non-interactive dependency and Klipper-extra
updates.

Useful docs:

- [Installation](docs/installation.md), [controls](docs/controls.md), and
  [migration](docs/migration.md) notes cover setup and troubleshooting.
- [Example CNC Macros](docs/cnc-macros.md) covers guarded spindle start,
  pause/resume/cancel, Fusion start/end hooks, touch-probe buttons,
  tool-setter workflows, and parameter-aware homing.
- [Experimental Klipper CNC Extras](docs/klipper-extras.md) covers persistent
  WCS, XY stylus probing, surface measurement, and cutting-tool Z touch-off.
- [`tools/fusion360`](tools/fusion360/README.md) includes the adapted Fusion 360
  post processor.
- [`tools/moonraker`](tools/moonraker/README.md) includes optional Moonraker-side
  CNC integrations:
  thumbnails, metadata sidecars, a minimal `cnc_agent`, and machine-profile
  examples.

## E3CNC Frontend Status

This repository also vendors a debloated snapshot of the upstream E3CNC frontend under
`vendor/e3cnc-debloated/frontend`.
The upstream project is [E3CNC](https://github.com/E3CNC/E3CNC).

Current status:

- the frontend snapshot is kept as a reference/customization base
- E3CNC update, rollback, and release-management UI dependencies were removed
- Moonraker-side compatibility work in this repo currently targets:
  metadata sidecars and `/server/cnc/*`
- the frontend is not yet integrated as the primary shipped UI in this fork

## Sonic Pad Debian

On [SonicPad-Debian](https://github.com/Jpe230/SonicPad-Debian), the bundled `display-sleep.service` may switch off the physical backlight when X11 is temporarily unavailable. If the screen unexpectedly stays black after Klipper Screen starts or restarts, inspect that service separately from this application.

## Upstream

Klipper Screen CNC is derived from KlipperScreen by Jordan Ruthe and its contributors. Refer to the [upstream project](https://github.com/KlipperScreen/KlipperScreen) for the original project and general architecture.

## License

This fork remains licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).
