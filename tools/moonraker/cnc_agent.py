"""Optional Moonraker component exposing a minimal CNC control API."""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Dict, Iterable, Mapping, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - optional in target runtime
    yaml = None
    YAMLError = Exception
else:
    YAMLError = yaml.YAMLError

DEFAULT_SETTINGS_PATH = os.path.expanduser("~/printer_data/config/cnc_dashboard_settings.json")
DEFAULT_MACHINE_PROFILE_PATH = os.path.expanduser("~/printer_data/config/machine_profile.yaml")
DEFAULT_WCS = "G54"
DEFAULT_JOG_RATE_LIMIT_MS = 50
VALID_UNITS = {"G20", "G21"}
VALID_WCS = {"G53", "G54", "G55", "G56", "G57", "G58", "G59"}
VALID_SPINDLE_STATES = {"off", "cw", "ccw"}


class CncAgent:
    def __init__(self, config):
        self.server = config.get_server()
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.settings_path = os.path.expanduser(config.get("settings_path", DEFAULT_SETTINGS_PATH))
        self.machine_profile_path = os.path.expanduser(
            config.get("machine_profile_path", DEFAULT_MACHINE_PROFILE_PATH)
        )
        self._state = self._build_default_state()
        self._state["settings"].update(self._load_settings())
        self._state["profile"] = self._load_machine_profile()
        self._state["capabilities"] = copy.deepcopy(self._state["profile"].get("capabilities", {}))
        self._klippy_apis: Any = None
        self._jog_rate_limit_ms = float(config.get("jog_rate_limit_ms", DEFAULT_JOG_RATE_LIMIT_MS))
        self._last_jog: Dict[str, float] = {}
        self.server.register_event_handler("server:klippy_ready", self._on_klippy_ready)

    def _build_default_state(self) -> Dict[str, Any]:
        return {
            "spindle": {"state": "off", "rpm": 0.0, "override": 1.0},
            "coolant": {"flood": False, "mist": False},
            "units": "G21",
            "wcs": {
                "active": DEFAULT_WCS,
                "machine_mode": False,
                "offsets": {code: {"X": 0.0, "Y": 0.0, "Z": 0.0} for code in VALID_WCS},
            },
            "capabilities": {},
            "profile": {"name": "", "frontend": {}, "capabilities": {}, "safety": {}},
            "settings": {},
        }

    def _capability_config(self, name: str) -> Dict[str, Any]:
        value = self._state["capabilities"].get(name)
        if isinstance(value, dict):
            return value
        if isinstance(value, bool):
            return {"enabled": value}
        return {}

    def _capability_enabled(self, name: str, default: bool = True) -> bool:
        config = self._capability_config(name)
        if "enabled" in config:
            return bool(config["enabled"])
        return default

    def _coolant_channels(self) -> int:
        config = self._capability_config("coolant")
        channels = config.get("channels")
        if channels is None:
            return 1
        try:
            return max(0, int(channels))
        except (TypeError, ValueError):
            return 0

    async def component_init(self):
        self._register_http_endpoints()

    def _register_http_endpoints(self):
        register_endpoint = getattr(self.server, "register_endpoint", None)
        if not callable(register_endpoint):
            self.logger.debug("CncAgent: register_endpoint unavailable; skipping")
            return

        endpoint_groups = {
            "/server/cnc/state": {"GET": self.handle_state},
            "/server/cnc/spindle": {"GET": self.handle_spindle_get, "POST": self.handle_spindle_post},
            "/server/cnc/coolant": {"GET": self.handle_coolant_get, "POST": self.handle_coolant_post},
            "/server/cnc/units": {"GET": self.handle_units_get, "POST": self.handle_units_post},
            "/server/cnc/wcs": {"GET": self.handle_wcs_get},
            "/server/cnc/wcs/select": {"POST": self.handle_wcs_select},
            "/server/cnc/wcs/set-zero": {"POST": self.handle_set_zero},
            "/server/cnc/jog": {"POST": self.handle_jog},
            "/server/cnc/settings": {"GET": self.handle_settings_get, "POST": self.handle_settings_post},
        }
        for path, handlers in endpoint_groups.items():
            methods = list(handlers.keys())
            handler = next(iter(handlers.values())) if len(handlers) == 1 else self._make_dispatcher(handlers)
            register_endpoint(path, methods, handler)

    @staticmethod
    def _make_dispatcher(handlers):
        async def dispatch(request):
            method = getattr(request, "method", "GET")
            handler = handlers.get(method)
            if handler is None:
                raise RuntimeError(f"Unsupported method {method} for endpoint")
            return await handler(request)

        return dispatch

    async def _on_klippy_ready(self):
        self.logger.info("Klipper is ready, CncAgent is active.")

    def _get_klippy_apis(self) -> Any:
        if self._klippy_apis is not None:
            return self._klippy_apis
        lookup_component = getattr(self.server, "lookup_component", None)
        if not callable(lookup_component):
            return None
        for name in ("klippy_apis", "klippy_connection"):
            try:
                component = lookup_component(name)
            except Exception:
                continue
            if component is not None and hasattr(component, "run_gcode"):
                self._klippy_apis = component
                return component
        return None

    async def _execute_gcode(self, script: str):
        klippy_apis = self._get_klippy_apis()
        if klippy_apis is None:
            raise RuntimeError("Moonraker klippy_apis component is not available")
        return await klippy_apis.run_gcode(script)

    async def _query_klipper_objects(self, objects: Dict[str, Any]) -> Dict[str, Any]:
        klippy_apis = self._get_klippy_apis()
        if klippy_apis is None:
            return {}
        query = getattr(klippy_apis, "query_objects", None)
        if not callable(query):
            return {}
        try:
            result = await query(objects)
            return result if isinstance(result, dict) else {}
        except Exception:
            self.logger.warning("CncAgent: query_objects failed", exc_info=True)
            return {}

    @staticmethod
    def _format_number(value: Any) -> str:
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:g}"

    def get_state(self) -> Dict[str, Any]:
        return copy.deepcopy(self._state)

    def set_spindle_state(self, state: str, rpm: Optional[float] = None, override: Optional[float] = None):
        normalized = state.lower()
        if normalized not in VALID_SPINDLE_STATES:
            raise ValueError(f"unsupported spindle state: {state!r}")
        self._state["spindle"]["state"] = normalized
        if rpm is not None:
            self._state["spindle"]["rpm"] = float(rpm)
        if override is not None:
            self._state["spindle"]["override"] = float(override)
        return copy.deepcopy(self._state["spindle"])

    def set_coolant_state(self, flood: Optional[bool] = None, mist: Optional[bool] = None):
        if flood is not None:
            self._state["coolant"]["flood"] = bool(flood)
        if mist is not None:
            self._state["coolant"]["mist"] = bool(mist)
        return copy.deepcopy(self._state["coolant"])

    def set_units(self, units: str):
        normalized = units.upper()
        if normalized not in VALID_UNITS:
            raise ValueError(f"unsupported units: {units!r}")
        self._state["units"] = normalized
        return normalized

    def set_active_wcs(self, wcs: str):
        normalized = wcs.upper()
        if normalized not in VALID_WCS:
            raise ValueError(f"unsupported WCS: {wcs!r}")
        self._state["wcs"]["active"] = normalized
        return copy.deepcopy(self._state["wcs"])

    def update_settings(self, patch: Mapping[str, Any]):
        self._merge_dict(self._state["settings"], dict(patch))
        self._save_settings(self._state["settings"])
        return copy.deepcopy(self._state["settings"])

    def _merge_dict(self, target: Dict[str, Any], patch: Dict[str, Any]):
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._merge_dict(target[key], value)
            else:
                target[key] = copy.deepcopy(value)

    def _coerce_payload(self, request: Any) -> Dict[str, Any]:
        if request is None:
            return {}
        if isinstance(request, dict):
            return dict(request)
        if hasattr(request, "args") and isinstance(request.args, dict):
            return dict(request.args)
        if hasattr(request, "get_args"):
            try:
                args = request.get_args()
            except Exception:
                args = None
            if isinstance(args, dict):
                return dict(args)
        if hasattr(request, "to_dict"):
            payload = request.to_dict()
            if isinstance(payload, dict):
                return payload
        if hasattr(request, "json"):
            payload = request.json
            if callable(payload):
                payload = payload()
            if isinstance(payload, dict):
                return payload
        return {}

    def _parse_axes(self, request: Any) -> Iterable[str]:
        payload = self._coerce_payload(request)
        axes = payload.get("axes")
        if isinstance(axes, str):
            return [axis.strip().upper() for axis in axes.replace(",", " ").split() if axis.strip()]
        if isinstance(axes, (list, tuple)):
            return [str(axis).upper() for axis in axes]
        axis = payload.get("axis")
        return [str(axis).upper()] if axis else []

    def _load_machine_profile(self) -> Dict[str, Any]:
        empty = {"name": "", "frontend": {}, "capabilities": {}, "safety": {}}
        if not self.machine_profile_path:
            return empty
        try:
            with open(self.machine_profile_path, "r", encoding="utf-8") as handle:
                if yaml is None:
                    self.logger.warning("CncAgent: PyYAML unavailable, skipping %s", self.machine_profile_path)
                    return empty
                data = yaml.safe_load(handle) or {}
                if not isinstance(data, dict):
                    return empty
                return {
                    "name": str(data.get("name", "")),
                    "frontend": dict(data.get("frontend", {})) if isinstance(data.get("frontend", {}), dict) else {},
                    "capabilities": self._normalize_capabilities(data.get("capabilities", {})),
                    "safety": dict(data.get("safety", {})) if isinstance(data.get("safety", {}), dict) else {},
                }
        except FileNotFoundError:
            return empty
        except YAMLError:
            self.logger.warning("CncAgent: invalid YAML at %s", self.machine_profile_path)
            return empty
        except OSError:
            self.logger.exception("CncAgent: unable to read machine profile from %s", self.machine_profile_path)
            return empty

    def _normalize_capabilities(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        normalized: Dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, dict):
                normalized[key] = copy.deepcopy(item)
            elif isinstance(item, bool):
                normalized[key] = {"enabled": item}
        return normalized

    def _load_settings(self) -> Dict[str, Any]:
        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            self.logger.warning("CncAgent: invalid JSON at %s", self.settings_path)
            return {}
        except OSError:
            self.logger.exception("CncAgent: unable to read settings from %s", self.settings_path)
            return {}

    def _save_settings(self, data: Mapping[str, Any]):
        try:
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except OSError:
            self.logger.exception("CncAgent: unable to persist settings to %s", self.settings_path)

    async def handle_state(self, request: Any = None):
        return self.get_state()

    async def handle_spindle_get(self, request: Any = None):
        return copy.deepcopy(self._state["spindle"])

    async def handle_spindle_post(self, request: Any = None):
        if not self._capability_enabled("spindle", default=True):
            raise RuntimeError("spindle is disabled by machine profile")
        payload = self._coerce_payload(request)
        state = str(payload.get("state", self._state["spindle"]["state"])).lower()
        if state not in VALID_SPINDLE_STATES:
            raise ValueError(f"unsupported spindle state: {state!r}")
        rpm = payload.get("rpm", self._state["spindle"]["rpm"])
        override = payload.get("override")
        if state == "off":
            await self._execute_gcode("M5")
            rpm_value = 0.0
        else:
            command = "M3" if state == "cw" else "M4"
            rpm_value = float(rpm) if rpm is not None else float(self._state["spindle"]["rpm"] or 0)
            await self._execute_gcode(f"{command} S{self._format_number(rpm_value)}")
        self.set_spindle_state(state, rpm=rpm_value, override=override)
        return {"ok": True, "type": "spindle", **copy.deepcopy(self._state["spindle"])}

    async def handle_coolant_get(self, request: Any = None):
        return copy.deepcopy(self._state["coolant"])

    async def handle_coolant_post(self, request: Any = None):
        channels = self._coolant_channels()
        if channels <= 0 or not self._capability_enabled("coolant", default=channels > 0):
            raise RuntimeError("coolant is disabled by machine profile")
        payload = self._coerce_payload(request)
        flood = payload.get("flood", self._state["coolant"]["flood"])
        mist = payload.get("mist", self._state["coolant"]["mist"])
        scripts = []
        if flood and channels >= 1:
            scripts.append("M8")
        if mist and channels >= 2:
            scripts.append("M7")
        if not scripts:
            scripts.append("M9")
        for script in scripts:
            await self._execute_gcode(script)
        self.set_coolant_state(flood=flood, mist=mist)
        return {"ok": True, "type": "coolant", **copy.deepcopy(self._state["coolant"])}

    async def handle_units_get(self, request: Any = None):
        return {"units": self._state["units"]}

    async def handle_units_post(self, request: Any = None):
        payload = self._coerce_payload(request)
        units = payload.get("units", self._state["units"])
        normalized = self.set_units(units)
        await self._execute_gcode(normalized)
        return {"ok": True, "type": "units", "units": normalized}

    async def handle_wcs_get(self, request: Any = None):
        wcs_state = await self._query_klipper_objects({"work_coordinate_systems": None})
        remote = wcs_state.get("work_coordinate_systems", {})
        if remote:
            self._state["wcs"]["active"] = remote.get("active_wcs", DEFAULT_WCS)
            self._state["wcs"]["machine_mode"] = remote.get("machine_mode", False)
            raw_wcs = remote.get("wcs", {})
            if raw_wcs:
                self._state["wcs"]["offsets"] = {name: dict(zip("XYZ", vals)) for name, vals in raw_wcs.items()}
        return copy.deepcopy(self._state["wcs"])

    async def handle_wcs_select(self, request: Any = None):
        payload = self._coerce_payload(request)
        wcs = str(payload.get("wcs", DEFAULT_WCS)).upper()
        if wcs not in VALID_WCS:
            raise ValueError(f"unsupported WCS: {wcs!r}")
        if wcs != "G53":
            await self._execute_gcode(wcs)
        remote = (await self._query_klipper_objects({"work_coordinate_systems": None})).get(
            "work_coordinate_systems", {}
        )
        if remote:
            self._state["wcs"]["active"] = remote.get("active_wcs", wcs)
            self._state["wcs"]["machine_mode"] = remote.get("machine_mode", False)
            raw_wcs = remote.get("wcs", {})
            if raw_wcs:
                self._state["wcs"]["offsets"] = {name: dict(zip("XYZ", vals)) for name, vals in raw_wcs.items()}
        else:
            self.set_active_wcs(wcs)
        active = self._state["wcs"]["active"]
        return {
            "ok": True,
            "type": "wcs_select",
            "wcs": active,
            "machine_mode": self._state["wcs"]["machine_mode"],
            "offsets": copy.deepcopy(self._state["wcs"]["offsets"].get(active, {"X": 0.0, "Y": 0.0, "Z": 0.0})),
        }

    async def handle_set_zero(self, request: Any = None):
        axes = [axis for axis in self._parse_axes(request) if axis in {"X", "Y", "Z"}]
        if not axes:
            axes = ["X", "Y", "Z"]
        active = self._state["wcs"]["active"]
        if active == "G53":
            raise ValueError("cannot zero axes in G53 machine-coordinate mode")
        wcs_p = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6}.get(active, 1)
        axis_args = " ".join(f"{axis}0" for axis in axes)
        await self._execute_gcode(f"G10 L20 P{wcs_p} {axis_args}")
        return {"ok": True, "type": "set_zero", "wcs": active, "axes": axes}

    async def handle_jog(self, request: Any = None):
        payload = self._coerce_payload(request)
        axis = str(payload.get("axis", "")).upper()
        if axis not in {"X", "Y", "Z"}:
            raise ValueError(f"unsupported jog axis: {axis!r}")
        distance = payload.get("distance")
        feedrate = payload.get("feedrate")
        if distance is None:
            raise ValueError("jog requires a distance")
        if feedrate is None:
            raise ValueError("jog requires a feedrate")
        import time as _time

        now = _time.monotonic()
        last = self._last_jog.get(axis)
        if last is not None and (now - last) * 1000 < self._jog_rate_limit_ms:
            raise RuntimeError(f"jog rate limit on {axis}")
        self._last_jog[axis] = now
        script = (
            "SAVE_GCODE_STATE NAME=_ui_movement\n"
            "G91\n"
            f"G1 {axis}{self._format_number(distance)} F{self._format_number(float(feedrate) * 60)}\n"
            "RESTORE_GCODE_STATE NAME=_ui_movement"
        )
        await self._execute_gcode(script)
        return {"ok": True, "type": "jog", "axis": axis, "distance": float(distance), "feedrate": float(feedrate)}

    async def handle_settings_get(self, request: Any = None):
        return copy.deepcopy(self._state["settings"])

    async def handle_settings_post(self, request: Any = None):
        self.update_settings(self._coerce_payload(request))
        return {"ok": True, "type": "settings", "settings": copy.deepcopy(self._state["settings"])}


def load_component(config):
    return CncAgent(config)
