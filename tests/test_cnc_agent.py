import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "moonraker" / "cnc_agent.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CNC_AGENT = load_module("cnc_agent", SCRIPT)


class DummyKlippyApis:
    def __init__(self):
        self.commands = []
        self.query_result = {}

    async def run_gcode(self, script):
        self.commands.append(script)
        return {"ok": True}

    async def query_objects(self, objects):
        return self.query_result


class DummyServer:
    def __init__(self, klippy_apis):
        self.klippy_apis = klippy_apis
        self.endpoints = {}
        self.events = {}

    def register_event_handler(self, name, handler):
        self.events[name] = handler

    def register_endpoint(self, path, methods, handler):
        self.endpoints[path] = {"methods": methods, "handler": handler}

    def lookup_component(self, name):
        if name in {"klippy_apis", "klippy_connection"}:
            return self.klippy_apis
        raise KeyError(name)


class DummyConfig:
    def __init__(self, server, settings_path, machine_profile_path):
        self.server = server
        self.values = {
            "settings_path": str(settings_path),
            "machine_profile_path": str(machine_profile_path),
        }

    def get_server(self):
        return self.server

    def get(self, key, default=None):
        return self.values.get(key, default)


class CncAgentTests(unittest.TestCase):
    def test_component_registers_endpoints_and_tracks_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings_path = root / "cnc_settings.json"
            settings_path.write_text(json.dumps({"viewer": {"grid": 5}}))
            profile_path = root / "machine_profile.yaml"
            profile_path.write_text(
                "name: Test Router\ncapabilities:\n  spindle: true\nsafety:\n  confirm_spindle_start: true\n"
            )
            klippy = DummyKlippyApis()
            klippy.query_result = {
                "work_coordinate_systems": {
                    "active_wcs": "G55",
                    "machine_mode": False,
                    "wcs": {"G54": [0, 0, 0], "G55": [1.5, 2.5, -3.0]},
                }
            }
            server = DummyServer(klippy)
            config = DummyConfig(server, settings_path, profile_path)
            agent = CNC_AGENT.CncAgent(config)

            asyncio.run(agent.component_init())
            self.assertIn("/server/cnc/state", server.endpoints)
            self.assertIn("/server/cnc/jog", server.endpoints)

            state = asyncio.run(agent.handle_state())
            if CNC_AGENT.yaml is None:
                self.assertEqual(state["profile"]["name"], "")
                self.assertEqual(state["capabilities"], {})
            else:
                self.assertEqual(state["profile"]["name"], "Test Router")
                self.assertTrue(state["capabilities"]["spindle"])
            self.assertEqual(state["settings"]["viewer"]["grid"], 5)

            spindle = asyncio.run(agent.handle_spindle_post({"state": "cw", "rpm": 12000}))
            self.assertEqual(spindle["rpm"], 12000.0)
            self.assertEqual(klippy.commands[-1], "M3 S12000")

            coolant = asyncio.run(agent.handle_coolant_post({"flood": True, "mist": False}))
            self.assertTrue(coolant["flood"])
            self.assertEqual(klippy.commands[-1], "M8")

            units = asyncio.run(agent.handle_units_post({"units": "G20"}))
            self.assertEqual(units["units"], "G20")
            self.assertEqual(klippy.commands[-1], "G20")

            wcs = asyncio.run(agent.handle_wcs_get())
            self.assertEqual(wcs["active"], "G55")
            self.assertEqual(wcs["offsets"]["G55"]["Z"], -3.0)

            zero = asyncio.run(agent.handle_set_zero({"axes": ["X", "Z"]}))
            self.assertEqual(zero["axes"], ["X", "Z"])
            self.assertEqual(klippy.commands[-1], "G10 L20 P2 X0 Z0")

            settings = asyncio.run(agent.handle_settings_post({"viewer": {"grid": 10}, "ui": {"theme": "cnc"}}))
            self.assertEqual(settings["settings"]["viewer"]["grid"], 10)
            persisted = json.loads(settings_path.read_text())
            self.assertEqual(persisted["ui"]["theme"], "cnc")

    def test_coolant_profile_can_disable_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings_path = root / "cnc_settings.json"
            settings_path.write_text("{}")
            profile_path = root / "machine_profile.yaml"
            profile_path.write_text("{}")
            klippy = DummyKlippyApis()
            server = DummyServer(klippy)
            agent = CNC_AGENT.CncAgent(DummyConfig(server, settings_path, profile_path))
            agent._state["capabilities"] = {"coolant": {"channels": 0, "enabled": False}}

            with self.assertRaises(RuntimeError):
                asyncio.run(agent.handle_coolant_post({"flood": True}))


if __name__ == "__main__":
    unittest.main()
