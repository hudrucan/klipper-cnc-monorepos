"""Optional Moonraker component registering the CNC thumbnail processor."""

from __future__ import annotations

import os
import sys

PROCESSOR_NAME = "cnc_thumbnail"
DEFAULT_SCRIPT = "~/printer_data/scripts/cnc_thumbnail.py"


class CncThumbnail:
    def __init__(self, config):
        self.server = config.get_server()
        self.script_path = os.path.expanduser(config.get("script_path", DEFAULT_SCRIPT))
        self.timeout = config.getfloat("timeout", 30.0, above=0.0)

    async def component_init(self):
        if not os.path.isfile(self.script_path):
            raise self.server.error(f"CNC thumbnail script not found: {self.script_path}")
        file_manager = self.server.lookup_component("file_manager")
        metadata = file_manager.get_metadata_storage()
        metadata.register_gcode_processor(
            PROCESSOR_NAME,
            {
                "name": PROCESSOR_NAME,
                "version": "v1",
                "command": [sys.executable, self.script_path, "{gcode_file_path}"],
                "timeout": self.timeout,
                "ident": {
                    "regex": r"^; CNC-THUMBNAIL-V1$",
                    "location": "footer",
                },
            },
        )


def load_component(config):
    return CncThumbnail(config)
