# Klipper Screen CNC

A CNC-focused fork of [KlipperScreen](https://github.com/KlipperScreen/KlipperScreen), built for touchscreen control of Klipper-based CNC machines.

This fork removes most 3D-printer-specific UI and replaces it with a compact CNC workflow:

- DRO with machine and work coordinates
- Safer incremental jogging
- Interactive WCS selection and XY map
- MDI and G-code macro access
- Spindle clockwise, counter-clockwise, and stop controls
- Motion Override control using Klipper's native `M220`
- CNC-oriented run status, progress, pause, resume, restart, and cancel
- Limits, network, system, and shutdown controls

## Status

This project is under active development and currently targets our own Klipper CNC setup. Treat it as experimental machine-control software: verify motion directions, limits, spindle wiring, and emergency-stop behavior before running a toolpath.

## Requirements

- Klipper
- Moonraker
- A Linux host with a GTK 3-compatible display
- Python 3.9 or newer
- A configured touchscreen or mouse

Spindle controls are shown when Klipper exposes the `M3` and `M5` commands and an `[output_pin spindle]` section. `M4` enables the counter-clockwise control.

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

See the quick [installation](docs/installation.md), [controls](docs/controls.md), and
[migration](docs/migration.md) notes for configuration and troubleshooting.
Optional Klipper-side examples for CNC pause/resume/cancel and parameter-aware homing
are documented in [Example CNC Macros](docs/cnc-macros.md).
Experimental persistent WCS, XY stylus probing, and cutting-tool Z touch-off
modules are documented in
[Experimental Klipper CNC Extras](docs/klipper-extras.md).
An adapted Fusion 360 post processor is included in
[`tools/fusion360`](tools/fusion360/README.md).
An optional Moonraker processor can generate
[CNC toolpath thumbnails](tools/moonraker/README.md) after upload.

## Sonic Pad Debian

On [SonicPad-Debian](https://github.com/Jpe230/SonicPad-Debian), the bundled `display-sleep.service` may switch off the physical backlight when X11 is temporarily unavailable. If the screen unexpectedly stays black after Klipper Screen starts or restarts, inspect that service separately from this application.

## Upstream

Klipper Screen CNC is derived from KlipperScreen by Jordan Ruthe and its contributors. Refer to the [upstream project](https://github.com/KlipperScreen/KlipperScreen) for the original project and general architecture.

## License

This fork remains licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).
