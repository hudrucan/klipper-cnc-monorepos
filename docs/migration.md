# Migration Notes

This fork intentionally breaks some upstream names to better match the CNC target.

## Runtime Names

- `KlipperScreen.conf` is no longer searched automatically. Use `klipper_screen.conf`.
- `~/.config/KlipperScreen` was replaced by `~/.config/klipper_screen`.
- `~/.KlipperScreen-env` was replaced by `~/.klipper-screen-env`.
- `KlipperScreen.service` was replaced by `klipper-screen.service`.
- The expected checkout path in scripts and docs is `~/klipper-screen-cnc`.

## Documentation

The upstream documentation tree was removed and replaced with this placeholder set. CNC-specific docs will be added as features are rebuilt.
