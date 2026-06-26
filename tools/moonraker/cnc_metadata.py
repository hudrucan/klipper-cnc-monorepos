#!/usr/bin/env python3
"""Extract CNC metadata sidecars for Moonraker-managed G-code files.

The extractor writes `<file>.cnc-meta.json` next to CNC G-code files and marks
processed files with a footer so Moonraker can skip repeated work. Thumbnail
embedding is delegated to `cnc_thumbnail.py` so there is only one renderer to
maintain in this repository.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cnc_thumbnail

SCHEMA_VERSION = 2
FOOTER_MARKER = b"; CNC-METADATA-V1\n"
HEADER_READ_BYTES = 1_048_576

LOG = logging.getLogger("cnc_metadata")

CAM_DETECTORS: List[Tuple[str, str, re.Pattern[str]]] = [
    (
        "Fusion 360",
        "fusion",
        re.compile(
            r"(?:^; ?Fusion CAM\b|; ?Autodesk Fusion|; ?F360 CAM|; ?Posts processor:)",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    ("EstlCam", "estlcam", re.compile(r"(?:^; ?ESTLCAM|estlcam|camext)", re.IGNORECASE | re.MULTILINE)),
    ("VCarve", "vcarve", re.compile(r"(?:VCarve Post Processor|; ?VCarve Pro)", re.IGNORECASE | re.MULTILINE)),
    ("FreeCAD Path", "freecad", re.compile(r"(?:; ?FreeCAD Path|\(FreeCAD\))", re.IGNORECASE | re.MULTILINE)),
    ("bCNC", "bcnc", re.compile(r"(?:^; ?bCNC|;BCN)", re.IGNORECASE | re.MULTILINE)),
    ("CamBam", "cambam", re.compile(r"(?:\(CamBam|; ?CamBam)", re.IGNORECASE | re.MULTILINE)),
    ("MeshCAM", "meshcam", re.compile(r"(?:\(MeshCAM|; ?MeshCAM)", re.IGNORECASE | re.MULTILINE)),
]


def sidecar_path_for(gcode_path: Path) -> Path:
    return Path(f"{gcode_path}.cnc-meta.json")


def has_footer(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            size = path.stat().st_size
            if size > 8192:
                handle.seek(-8192, os.SEEK_END)
            return FOOTER_MARKER in handle.read()
    except OSError:
        return False


def read_head_and_tail(path: Path) -> Tuple[str, str]:
    size = path.stat().st_size
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        head = handle.read(HEADER_READ_BYTES)
        if size > HEADER_READ_BYTES * 2:
            handle.seek(size - HEADER_READ_BYTES)
            tail = handle.read()
        elif size > HEADER_READ_BYTES:
            tail = head[-(size - HEADER_READ_BYTES) :] + handle.read()
        else:
            tail = head
    return head, tail


def detect_cam(head: str, tail: str) -> Optional[Dict[str, str]]:
    sample = head + "\n" + tail[:4096]
    for nice_name, slug, pattern in CAM_DETECTORS:
        if not pattern.search(sample):
            continue
        info: Dict[str, str] = {"cam_tool": nice_name, "cam_tool_slug": slug}
        if slug == "fusion":
            for key, regex in (
                ("cam_tool_version", r";Fusion CAM\s+([\d.]+)"),
                ("post_processor", r";\s*Posts processor:\s*(\S+)"),
                ("document", r";\s*Document:\s*(.+)"),
                ("setup", r";\s*Setup:\s*(.+)"),
            ):
                match = re.search(regex, head)
                if match:
                    info[key] = match.group(1).strip()
        return info
    return None


def extract_envelope(path: Path) -> Optional[Dict[str, float]]:
    xmin = ymin = zmin = float("inf")
    xmax = ymax = zmax = float("-inf")
    found = False
    move_re = re.compile(r"^G[01]\b")
    coord_re = re.compile(r"\b([XYZ])([+-]?\d*\.?\d+)")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if index > 10_000:
                break
            if not move_re.match(line):
                continue
            coords = {axis: float(value) for axis, value in coord_re.findall(line)}
            if not coords:
                continue
            found = True
            if "X" in coords:
                xmin = min(xmin, coords["X"])
                xmax = max(xmax, coords["X"])
            if "Y" in coords:
                ymin = min(ymin, coords["Y"])
                ymax = max(ymax, coords["Y"])
            if "Z" in coords:
                zmin = min(zmin, coords["Z"])
                zmax = max(zmax, coords["Z"])
    if not found:
        return None
    return {
        "x_min": round(xmin, 3),
        "x_max": round(xmax, 3),
        "y_min": round(ymin, 3),
        "y_max": round(ymax, 3),
        "z_min": round(zmin, 3),
        "z_max": round(zmax, 3),
    }


def extract_axis_table(header: str, title: str) -> Optional[Dict[str, Dict[str, float]]]:
    pattern = re.compile(
        rf"^;\s*{re.escape(title)}:\s*$\n((?:^;\s+[XYZ]:\s+Min=[^\n]+$\n?){{1,3}})",
        re.MULTILINE,
    )
    match = pattern.search(header)
    if not match:
        return None
    axes: Dict[str, Dict[str, float]] = {}
    for axis in ("X", "Y", "Z"):
        line_match = re.search(
            rf"^;\s+{axis}:\s+Min=([+-]?\d*\.?\d+)\s+Max=([+-]?\d*\.?\d+)\s+Size=([+-]?\d*\.?\d+)",
            match.group(1),
            re.MULTILINE,
        )
        if line_match:
            axes[axis.lower()] = {
                "min": round(float(line_match.group(1)), 3),
                "max": round(float(line_match.group(2)), 3),
                "size": round(float(line_match.group(3)), 3),
            }
    return axes or None


def extract_stock(header: str) -> Optional[Dict[str, Dict[str, float]]]:
    axes = extract_axis_table(header, "Stock Box") or extract_axis_table(header, "Ranges Table")
    if not axes:
        return None
    return {"x": axes.get("x", {}), "y": axes.get("y", {}), "z": axes.get("z", {})}


def extract_cam_wcs_origin(header: str) -> Optional[Dict[str, Dict[str, float]]]:
    pattern = re.compile(
        r"^;\s*CAM WCS Origin:\s*$\n((?:^;\s+[XYZ]:\s+stock\s+min[^\n]+$\n?){1,3})",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(header)
    if not match:
        return None
    origin: Dict[str, Dict[str, float]] = {}
    block = match.group(1)
    for axis in ("X", "Y", "Z"):
        line_match = re.search(
            rf"^;\s+{axis}:\s+stock\s+min\s+([+-]?\d*\.?\d+)\s+=\s+stock\s+max\s+([+-]?\d*\.?\d+)",
            block,
            re.IGNORECASE | re.MULTILINE,
        )
        if line_match:
            origin[axis.lower()] = {
                "from_min": round(float(line_match.group(1)), 3),
                "from_max": round(float(line_match.group(2)), 3),
            }
    return origin or None


def extract_tools(head: str, slug: str) -> List[Dict[str, Any]]:
    if slug == "fusion":
        tools = []
        pattern = re.compile(
            r"^;\s+T(\d+)\s+D=([+-]?\d*\.?\d+)"
            r"(?:\s+CR=([+-]?\d*\.?\d+))?"
            r"(?:\s+TAPER=([+-]?\d*\.?\d+)deg)?"
            r"(?:\s+-\s+ZMIN=([+-]?\d*\.?\d+))?"
            r"\s+-\s+(.+?)$",
            re.MULTILINE,
        )
        for match in pattern.finditer(head):
            descriptor = match.group(6).strip()
            tool_type = descriptor
            comment = ""
            if " " in descriptor:
                tool_type, comment = descriptor.split(" ", 1)
            tools.append(
                {
                    "id": f"T{match.group(1)}",
                    "diameter_mm": float(match.group(2)),
                    "corner_radius_mm": float(match.group(3)) if match.group(3) else None,
                    "taper_deg": float(match.group(4)) if match.group(4) else None,
                    "z_min": float(match.group(5)) if match.group(5) else None,
                    "type": tool_type.strip(),
                    "comment": comment.strip() or None,
                }
            )
        return tools
    if slug == "estlcam":
        return [
            {"id": f"T{match.group(1)}", "name": match.group(2).strip()}
            for match in re.finditer(r"^T(\d+)\s*=\s*(.+)$", head, re.MULTILINE)
        ]
    return []


def extract_spindle(head: str) -> Optional[float]:
    match = re.search(r"\bS(\d+(?:\.\d+)?)\b", head)
    return float(match.group(1)) if match else None


def extract_feeds(head: str) -> Dict[str, float]:
    feeds: Dict[str, float] = {}
    last_feed: Optional[float] = None
    move_re = re.compile(r"^(G0?[01])\b")
    feed_re = re.compile(r"\bF(\d+(?:\.\d+)?)")
    for line in head.splitlines():
        feed_match = feed_re.search(line)
        if feed_match:
            last_feed = float(feed_match.group(1))
        move_match = move_re.match(line)
        if not move_match or last_feed is None:
            continue
        motion = move_match.group(1).upper()
        if motion.startswith("G0"):
            feeds["rapid"] = last_feed
        elif motion.startswith("G1"):
            feeds["cut"] = last_feed
            if "Z" in line:
                feeds["plunge"] = last_feed
    return feeds


def extract_operations(head: str) -> List[Dict[str, str]]:
    operations: List[Dict[str, str]] = []
    for match in re.finditer(r"\(([^)]+)\)", head):
        name = match.group(1).strip()
        if name and not name.startswith(("T", "M", "G")) and "\n" not in name:
            operations.append({"name": name})
    for match in re.finditer(r";\s*(?:Toolpath|Operation|Op|Operation Name)\s*:\s*(.+)", head, re.IGNORECASE):
        name = match.group(1).strip()
        if name:
            operations.append({"name": name})
    seen = set()
    deduped = []
    for operation in operations:
        if operation["name"] in seen:
            continue
        seen.add(operation["name"])
        deduped.append(operation)
    return deduped[:32]


def build_metadata(path: Path, cam: Dict[str, str]) -> Dict[str, Any]:
    head, _tail = read_head_and_tail(path)
    metadata: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_file": path.name,
    }
    metadata.update(cam)
    envelope = extract_envelope(path)
    if envelope:
        metadata["work_envelope"] = envelope
    stock = extract_stock(head)
    if stock:
        metadata["stock"] = stock
    cam_wcs_origin = extract_cam_wcs_origin(head)
    if cam_wcs_origin:
        metadata["cam_wcs_origin"] = cam_wcs_origin
    tools = extract_tools(head, cam.get("cam_tool_slug", ""))
    if tools:
        metadata["tools"] = tools
    spindle = extract_spindle(head)
    if spindle is not None:
        metadata["spindle_rpm"] = spindle
    feeds = extract_feeds(head)
    if feeds:
        metadata["feeds_mm_per_min"] = feeds
    operations = extract_operations(head)
    if operations:
        metadata["operations"] = operations
        metadata["operation_count"] = len(operations)
    return metadata


def append_footer(path: Path) -> None:
    if has_footer(path):
        return
    with path.open("ab") as handle:
        handle.write(b"\n")
        handle.write(FOOTER_MARKER)


def write_sidecar(path: Path, metadata: Dict[str, Any]) -> Path:
    output = sidecar_path_for(path)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, output)
    return output


def process(path: Path, force: bool = False, no_thumb: bool = False) -> int:
    if not path.is_file():
        LOG.error("file not found: %s", path)
        return 1
    if has_footer(path) and not force:
        LOG.info("already processed: %s", path)
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    if not cnc_thumbnail.looks_like_cnc(text):
        return 0
    head, tail = read_head_and_tail(path)
    cam = detect_cam(head, tail)
    if cam is None:
        LOG.info("no CAM signature in %s", path)
        return 0
    metadata = build_metadata(path, cam)
    write_sidecar(path, metadata)
    append_footer(path)
    if not no_thumb:
        cnc_thumbnail.process(path, cnc_thumbnail.DEFAULT_SIZE, None, True, True)
    LOG.info("wrote %s", sidecar_path_for(path))
    return 0


def main(argv: List[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = list(argv[1:])
    force = False
    no_thumb = False
    while args and args[0].startswith("-"):
        if args[0] == "--force":
            force = True
            args.pop(0)
        elif args[0] == "--no-thumb":
            no_thumb = True
            args.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        return process(Path(args[0]), force=force, no_thumb=no_thumb)
    except Exception:
        LOG.exception("extractor failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
