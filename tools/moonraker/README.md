# CNC Toolpath Metadata

This directory contains three Moonraker-side integrations:

- `cnc_agent.py`: exposes a minimal `/server/cnc/*` API for spindle, coolant,
  units, WCS, jog, settings, and profile/capabilities state
- `cnc_thumbnail.py`: renders and embeds a top-down CNC toolpath thumbnail
- `cnc_metadata.py`: writes a `<file>.cnc-meta.json` sidecar and optionally
  delegates thumbnail embedding to `cnc_thumbnail.py`

These integrations are intended to support this repository and the upstream
[E3CNC frontend](https://github.com/E3CNC/E3CNC).

The thumbnail preview uses:

- cyan for cutting moves (`G1`, `G2`, and `G3`);
- dashed amber for rapid moves (`G0`);
- a grey rectangle for Fusion's stock box;
- a white cross for the work origin.

Both scripts are dependency-free and ignore extrusion-style 3D-print G-code so
existing printer metadata is left alone.

## Manual test

```sh
python3 cnc_thumbnail.py \
  --preview preview.png \
  --no-embed \
  example.gcode
```

```sh
python3 cnc_metadata.py \
  --no-thumb \
  example.gcode
```

## Moonraker installation

Copy the files:

```sh
mkdir -p ~/printer_data/scripts
cp cnc_thumbnail.py ~/printer_data/scripts/
chmod +x ~/printer_data/scripts/cnc_thumbnail.py
cp cnc_metadata.py ~/printer_data/scripts/
chmod +x ~/printer_data/scripts/cnc_metadata.py
```

Install Moonraker components:

```sh
mkdir -p ~/moonraker/moonraker/components/cnc_thumbnail
cp cnc_thumbnail_component.py \
  ~/moonraker/moonraker/components/cnc_thumbnail/cnc_thumbnail.py
printf '%s\n' \
  'from .cnc_thumbnail import load_component' \
  > ~/moonraker/moonraker/components/cnc_thumbnail/__init__.py

mkdir -p ~/moonraker/moonraker/components/cnc_metadata
cp cnc_metadata_component.py \
  ~/moonraker/moonraker/components/cnc_metadata/cnc_metadata.py
printf '%s\n' \
  'from .cnc_metadata import load_component' \
  > ~/moonraker/moonraker/components/cnc_metadata/__init__.py

mkdir -p ~/moonraker/moonraker/components/cnc_agent
cp cnc_agent.py \
  ~/moonraker/moonraker/components/cnc_agent/cnc_agent.py
printf '%s\n' \
  'from .cnc_agent import load_component' \
  > ~/moonraker/moonraker/components/cnc_agent/__init__.py
```

Add these sections to `moonraker.conf`:

```ini
[cnc_thumbnail]
script_path: ~/printer_data/scripts/cnc_thumbnail.py
timeout: 30.0

[cnc_metadata]
script_path: ~/printer_data/scripts/cnc_metadata.py
timeout: 30.0

[cnc_agent]
settings_path: ~/printer_data/config/cnc_dashboard_settings.json
machine_profile_path: ~/printer_data/config/machine_profile.yaml
jog_rate_limit_ms: 50
```

If you want `profile`, `capabilities`, and `safety` data exposed to the
frontend, install `PyYAML` in the Moonraker environment and copy the example
profile:

```sh
cp machine_profile.example.yaml ~/printer_data/config/machine_profile.yaml
```

The bundled example matches the current target machine:

- `name: cnc`
- spindle is relay-only
- coolant is disabled
- probe is enabled
- tool setter is enabled

Restart Moonraker. New CNC G-code uploads will:

- receive an embedded thumbnail
- get a `<file>.cnc-meta.json` sidecar suitable for the upstream E3CNC
  frontend or other CNC-aware clients
- expose `/server/cnc/*` endpoints expected by the upstream E3CNC frontend

The component uses Moonraker's internal G-code processor API. Back up the
Moonraker installation first, especially on vendor images such as Sonic Pad.

## Background

The sidecar metadata schema is intentionally compatible with the vendored
snapshot of the upstream E3CNC frontend in this repository. The architecture was informed by
the CNC metadata extractor in
[isaaceliape/mainsail-cnc](https://github.com/isaaceliape/mainsail-cnc), while
the thumbnail renderer here remains independent and richer in arc/rapid
handling.
