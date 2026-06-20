# Fusion 360 Post Processor

`klipper_screen_cnc.cps` is a vendored and adapted version of
[Zergie/mpcnc_post_processor](https://github.com/Zergie/mpcnc_post_processor).

Install it through Fusion 360's **Manage → Post Library** workflow.

## Macro contract

The post emits:

```gcode
START_PRINT X=<job-min>,<job-max> Y=<job-min>,<job-max> Z=<job-min>,<job-max>
```

once per generated file, before spindle and coolant commands. At the end it emits:

```gcode
M400
END_PRINT
```

Use it with:

```ini
[include cnc_pause_resume.cfg]
[include cnc_start_end.cfg]
[include cnc_homing_override.cfg]
```

from `config/examples/`.

## Differences from upstream

- Emits `START_PRINT` once per complete job instead of once per Fusion section.
- Passes complete-file XYZ bounds for machine-limit validation.
- Emits Fusion stock bounds for the CNC thumbnail renderer.
- Fixes global maximum-range aggregation.
- Requires millimeter output to match Klipper's native coordinate units.
- Keeps spindle and coolant commands controlled by Fusion operation/tool settings.
- Retains upstream safe-rapid recovery and direct Moonraker upload support.

The original MIT license is included in `LICENSE.mpcnc-post-processor`.

For automatic top-down toolpath previews in KlipperScreen, see the
[Moonraker CNC thumbnail processor](../moonraker/README.md).
