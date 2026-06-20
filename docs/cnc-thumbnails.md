# CNC Toolpath Thumbnails

KlipperScreen displays thumbnails returned by Moonraker. CNC CAM output
normally does not include one, so this repository provides an optional
Moonraker file processor that renders a top-down preview after upload.

The renderer shows:

- cutting moves in cyan;
- rapid moves as dashed amber lines;
- the Fusion stock boundary in grey;
- the work origin as a white cross.

It supports `G0`, `G1`, `G2`, and `G3`, metric and inch files, and absolute
or incremental positioning. The PNG encoder uses only the Python standard
library so Pillow is not required on the printer host.
G-code containing extrusion moves is skipped to avoid replacing slicer
thumbnails on mixed-use Klipper installations.

The adapted Fusion post processor writes a `Stock Box` table into the G-code.
Other CAM output can still be rendered using its detected motion envelope.

See [`tools/moonraker`](https://github.com/hudrucan/klipper-screen-cnc/tree/master/tools/moonraker)
for installation and manual preview commands.

The processor uses Moonraker's internal G-code processor API. Treat it as an
optional host-side extension, back up vendor Moonraker installations first,
and test a newly uploaded file before relying on automatic processing.

The approach was informed by the CNC metadata pipeline in
[`isaaceliape/mainsail-cnc`](https://github.com/isaaceliape/mainsail-cnc).
The implementation in this repository is independent and focuses only on
standard Moonraker thumbnails.
