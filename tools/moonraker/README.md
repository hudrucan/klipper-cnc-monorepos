# CNC Toolpath Thumbnails

`cnc_thumbnail.py` renders a top-down CNC toolpath preview and embeds it in
the G-code using Moonraker's standard thumbnail format.

The preview uses:

- cyan for cutting moves (`G1`, `G2`, and `G3`);
- dashed amber for rapid moves (`G0`);
- a grey rectangle for Fusion's stock box;
- a white cross for the work origin.

It is dependency-free and supports metric/inch input, absolute/incremental
positioning, linear moves, and XY-plane arcs.
Files containing extrusion moves are ignored so existing 3D-printer
thumbnails are not replaced.

## Manual test

```sh
python3 cnc_thumbnail.py \
  --preview preview.png \
  --no-embed \
  example.gcode
```

## Moonraker installation

Copy the files:

```sh
mkdir -p ~/printer_data/scripts
cp cnc_thumbnail.py ~/printer_data/scripts/
chmod +x ~/printer_data/scripts/cnc_thumbnail.py

mkdir -p ~/moonraker/moonraker/components/cnc_thumbnail
cp cnc_thumbnail_component.py \
  ~/moonraker/moonraker/components/cnc_thumbnail/cnc_thumbnail.py
printf '%s\n' \
  'from .cnc_thumbnail import load_component' \
  > ~/moonraker/moonraker/components/cnc_thumbnail/__init__.py
```

Add this section to `moonraker.conf`:

```ini
[cnc_thumbnail]
script_path: ~/printer_data/scripts/cnc_thumbnail.py
timeout: 30.0
```

Restart Moonraker. New CNC G-code uploads will receive an embedded thumbnail
before Moonraker returns their metadata to Mainsail or KlipperScreen.

The component uses Moonraker's internal G-code processor API. Back up the
Moonraker installation first, especially on vendor images such as Sonic Pad.

## Background

The architecture was informed by the CNC metadata extractor in
[isaaceliape/mainsail-cnc](https://github.com/isaaceliape/mainsail-cnc).
This implementation is independent, limits its scope to standard Moonraker
thumbnails, and adds modal arc parsing plus distinct rapid/cut rendering.
