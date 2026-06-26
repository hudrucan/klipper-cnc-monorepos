# Installation

Klipper Screen CNC is intended to replace upstream KlipperScreen on the target display.
Do not run both interfaces at the same time.

## Remove the old runtime

Stop the upstream service and preserve its files as backups:

```sh
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

Some installations use a lowercase unit name. Check for another active screen service:

```sh
systemctl list-unit-files | grep -Ei 'klipper.?screen'
```

Disable any old unit that still launches `~/KlipperScreen/screen.py`. Do not remove
Moonraker or Klipper.

## Install the fork

```sh
git clone https://github.com/hudrucan/klipper-screen-cnc.git
cd klipper-screen-cnc
./scripts/KlipperScreen-install.sh
sudo systemctl restart klipper-screen
```

Runtime locations:

- Source: `~/klipper-screen-cnc`
- Service: `klipper-screen.service`
- Virtual environment: `~/.klipper-screen-env`
- User config: `~/printer_data/config/klipper_screen.conf` or
  `~/.config/klipper_screen/klipper_screen.conf`
- Log: `~/printer_data/logs/klipper_screen.log`, falling back to
  `/tmp/klipper_screen.log`

## Update

```sh
cd ~/klipper-screen-cnc
git pull --ff-only
./scripts/KlipperScreen-update.sh
```

The update script refreshes the Python environment, copies bundled
`klipper-extras/*.py` modules into `~/klipper/klippy/extras/` when that Klipper
checkout exists, restarts Klipper when possible, and restarts the screen
service.

If Klipper lives outside `~/klipper`, set `KLIPPER_PATH`:

```sh
KLIPPER_PATH=/path/to/klipper ./scripts/KlipperScreen-update.sh
```

To skip installing the experimental Klipper extras:

```sh
INSTALL_KLIPPER_EXTRAS=0 ./scripts/KlipperScreen-update.sh
```

## Moonraker update manager

Add this to `~/printer_data/config/moonraker.conf` if you want updates from
Mainsail/Fluidd's update manager:

```ini
[update_manager klipper-screen]
type: git_repo
path: ~/klipper-screen-cnc
origin: https://github.com/hudrucan/klipper-screen-cnc.git
primary_branch: master
install_script: scripts/KlipperScreen-update.sh
```

Use `klipper-screen` as the update manager component name even though the checkout
directory is `~/klipper-screen-cnc`. Moonraker derives the systemd service from the
component name, so this lets Mainsail/Fluidd restart the real
`klipper-screen.service` after pulling updates. The bundled update script also
tries to copy Klipper CNC extras automatically when it can find the active Klipper
checkout. Set `KLIPPER_PATH` or `KLIPPER_EXTRAS_PATH` if Klipper lives in a
nonstandard location.

If you previously used `[update_manager klipper-screen-cnc]`, remove that block
before adding the one above. Otherwise Moonraker may keep trying to restart a
non-existent `klipper-screen-cnc.service`.

Restart Moonraker after editing its config:

```sh
sudo systemctl restart moonraker
```

Manual restart remains:

```sh
sudo systemctl restart klipper-screen
```

## Optional Moonraker CNC Integrations

This repository also includes optional Moonraker-side CNC helpers in
[`tools/moonraker`](../tools/moonraker/README.md):

- `cnc_thumbnail.py` for top-down CNC toolpath thumbnails
- `cnc_metadata.py` for `<file>.cnc-meta.json` sidecars
- `cnc_agent.py` for a minimal `/server/cnc/*` compatibility API
- `machine_profile.example.yaml` for profile/capability hints used by the
  upstream E3CNC frontend

The upstream frontend/reference project for that compatibility layer is
[E3CNC](https://github.com/E3CNC/E3CNC).

These are not required to run Klipper Screen CNC itself. Install them only if
you want Moonraker-side CNC metadata processing or if you are experimenting
with the vendored snapshot of the upstream E3CNC frontend.

## Verify

```sh
systemctl status klipper-screen --no-pager
journalctl -u klipper-screen -n 100 --no-pager
```

Only one Klipper Screen process should own the display.
