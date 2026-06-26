import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THUMBNAIL_SCRIPT = ROOT / "tools" / "moonraker" / "cnc_thumbnail.py"
METADATA_SCRIPT = ROOT / "tools" / "moonraker" / "cnc_metadata.py"
FIXTURE = ROOT / "tests" / "fixtures" / "cnc_thumbnail.gcode"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


THUMBNAIL = load_module("cnc_thumbnail", THUMBNAIL_SCRIPT)
METADATA = load_module("cnc_metadata", METADATA_SCRIPT)


class CncMetadataTests(unittest.TestCase):
    def test_build_metadata_extracts_expected_fields(self):
        head, tail = METADATA.read_head_and_tail(FIXTURE)
        cam = METADATA.detect_cam(head, tail)
        self.assertIsNotNone(cam)
        metadata = METADATA.build_metadata(FIXTURE, cam)
        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(metadata["cam_tool"], "Fusion 360")
        self.assertEqual(metadata["post_processor"], "klipper_screen_cnc.cps")
        self.assertEqual(metadata["document"], "fixture-part")
        self.assertEqual(metadata["setup"], "Setup1")
        self.assertIn("work_envelope", metadata)
        self.assertIn("stock", metadata)
        self.assertIn("cam_wcs_origin", metadata)
        self.assertEqual(metadata["cam_wcs_origin"]["z"]["from_min"], 4.0)
        self.assertEqual(metadata["cam_wcs_origin"]["z"]["from_max"], -12.0)
        self.assertIn("tools", metadata)
        self.assertEqual(metadata["tools"][0]["id"], "T1")
        self.assertEqual(metadata["tools"][0]["diameter_mm"], 3.175)
        self.assertIn("spindle_rpm", metadata)
        self.assertIn("feeds_mm_per_min", metadata)

    def test_process_writes_sidecar_footer_and_thumbnail(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "job.gcode"
            target.write_text(FIXTURE.read_text())
            self.assertEqual(METADATA.process(target, force=True, no_thumb=False), 0)

            sidecar = Path(f"{target}.cnc-meta.json")
            self.assertTrue(sidecar.exists())
            payload = json.loads(sidecar.read_text())
            self.assertEqual(payload["cam_tool"], "Fusion 360")

            content = target.read_text()
            self.assertIn(METADATA.FOOTER_MARKER.decode("ascii").strip(), content)
            self.assertIn("; thumbnail begin", content)
            self.assertIn(THUMBNAIL.MARKER, content)

    def test_process_is_idempotent_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "job.gcode"
            target.write_text(FIXTURE.read_text())
            METADATA.process(target, force=True, no_thumb=True)
            first = target.read_text()
            METADATA.process(target, force=False, no_thumb=True)
            self.assertEqual(first, target.read_text())


if __name__ == "__main__":
    unittest.main()
