import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "moonraker" / "cnc_thumbnail.py"
FIXTURE = ROOT / "tests" / "fixtures" / "cnc_thumbnail.gcode"
SPEC = importlib.util.spec_from_file_location("cnc_thumbnail", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CncThumbnailTests(unittest.TestCase):
    def test_parser_supports_lines_and_arcs(self):
        segments, stock = MODULE.parse_gcode(FIXTURE.read_text())
        self.assertIsNotNone(stock)
        self.assertEqual((stock.x_min, stock.x_max), (0.0, 100.0))
        self.assertGreater(len(segments), 100)
        self.assertTrue(any(segment.rapid for segment in segments))
        self.assertTrue(any(not segment.rapid for segment in segments))

    def test_png_dimensions(self):
        segments, stock = MODULE.parse_gcode(FIXTURE.read_text())
        png = MODULE.render_thumbnail(segments, stock, 300)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", png[16:24])
        self.assertEqual((width, height), (300, 300))

    def test_embedding_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "job.gcode"
            target.write_text(FIXTURE.read_text())
            MODULE.process(target, 300, None, True, True)
            MODULE.process(target, 300, None, True, True)
            content = target.read_text()
            self.assertEqual(content.count("; thumbnail begin"), 1)
            self.assertEqual(content.count(MODULE.MARKER), 1)

    def test_extrusion_gcode_is_ignored(self):
        gcode = "G90\nG1 X10 Y10 E0.4 F1200\n"
        self.assertFalse(MODULE.looks_like_cnc(gcode))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "print.gcode"
            target.write_text(gcode)
            MODULE.process(target, 300, None, True, True)
            self.assertEqual(target.read_text(), gcode)

    def test_generic_non_extrusion_gcode_is_cnc(self):
        self.assertTrue(MODULE.looks_like_cnc("G1 X10 Y10 F1200\n"))


if __name__ == "__main__":
    unittest.main()
