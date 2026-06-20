#!/usr/bin/env python3
"""Generate a Moonraker-compatible thumbnail from CNC G-code.

The renderer is intentionally dependency-free so it can run on small ARM
hosts. It understands modal G0/G1/G2/G3 motion in the XY plane, renders rapid
and cutting moves differently, and embeds the resulting PNG in the G-code.
"""

from __future__ import annotations

import argparse
import base64
import math
import os
import re
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

MARKER = "; CNC-THUMBNAIL-V1"
DEFAULT_SIZE = 300
ARC_SEGMENT_LENGTH = 1.5
MAX_SEGMENTS = 100_000
MAX_RENDERED_SEGMENTS = 25_000

MOTION_RE = re.compile(r"(?<![A-Z])G(0?[0-3])(?:\D|$)", re.IGNORECASE)
WORD_RE = re.compile(r"([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", re.IGNORECASE)
AXIS_LINE_RE = (
    r"^;\s*([XYZ]):\s*Min=([+-]?\d+(?:\.\d+)?)\s+"
    r"Max=([+-]?\d+(?:\.\d+)?)\s+Size=[^\n]*$"
)
THUMBNAIL_RE = re.compile(
    r"^;\s*thumbnail(?:_[A-Za-z0-9]+)?\s+begin\b.*?"
    r"^;\s*thumbnail(?:_[A-Za-z0-9]+)?\s+end\s*\r?\n?",
    re.MULTILINE | re.DOTALL,
)
EXTRUSION_MOVE_RE = re.compile(
    r"^[^;\n]*\bG0?[123]\b[^\n]*\bE[+-]?(?:\d+(?:\.\d*)?|\.\d+)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point
    rapid: bool


@dataclass(frozen=True)
class Bounds:
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    @property
    def width(self) -> float:
        return max(self.x_max - self.x_min, 0.001)

    @property
    def height(self) -> float:
        return max(self.y_max - self.y_min, 0.001)


class Canvas:
    def __init__(self, width: int, height: int, color: Tuple[int, int, int, int]):
        self.width = width
        self.height = height
        self.pixels = bytearray(color * (width * height))

    def pixel(self, x: int, y: int, color: Tuple[int, int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            index = (y * self.width + x) * 4
            self.pixels[index : index + 4] = bytes(color)

    def blend(self, x: int, y: int, color: Tuple[int, int, int, int]) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        index = (y * self.width + x) * 4
        alpha = color[3] / 255.0
        for channel in range(3):
            current = self.pixels[index + channel]
            self.pixels[index + channel] = round(current * (1.0 - alpha) + color[channel] * alpha)

    def line(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        color: Tuple[int, int, int, int],
        width: int = 1,
        dash: Optional[Tuple[int, int]] = None,
    ) -> None:
        x0, y0 = start
        x1, y1 = end
        dx = x1 - x0
        dy = y1 - y0
        steps = max(abs(dx), abs(dy), 1)
        radius = max(width // 2, 0)
        for step in range(steps + 1):
            if dash:
                on, off = dash
                if step % (on + off) >= on:
                    continue
            x = round(x0 + dx * step / steps)
            y = round(y0 + dy * step / steps)
            for oy in range(-radius, radius + 1):
                for ox in range(-radius, radius + 1):
                    if ox * ox + oy * oy <= radius * radius + 1:
                        self.blend(x + ox, y + oy, color)

    def rectangle(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        fill: Tuple[int, int, int, int],
        outline: Tuple[int, int, int, int],
    ) -> None:
        for y in range(max(top, 0), min(bottom + 1, self.height)):
            for x in range(max(left, 0), min(right + 1, self.width)):
                self.blend(x, y, fill)
        self.line((left, top), (right, top), outline)
        self.line((right, top), (right, bottom), outline)
        self.line((right, bottom), (left, bottom), outline)
        self.line((left, bottom), (left, top), outline)

    def png(self) -> bytes:
        raw = bytearray()
        stride = self.width * 4
        for row in range(self.height):
            raw.append(0)
            start = row * stride
            raw.extend(self.pixels[start : start + stride])
        signature = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", self.width, self.height, 8, 6, 0, 0, 0)
        return (
            signature
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _png_chunk(b"IEND", b"")
        )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def strip_comments(line: str) -> str:
    line = line.split(";", 1)[0]
    return re.sub(r"\([^)]*\)", "", line).strip().upper()


def parse_axis_table(header: str, title: str) -> Optional[Bounds]:
    table = re.search(
        r"^;\s*"
        + re.escape(title)
        + r":\s*$\n((?:"
        + AXIS_LINE_RE
        + r"\n?){1,3})",
        header,
        re.MULTILINE,
    )
    if not table:
        return None
    axes = {
        match.group(1): (float(match.group(2)), float(match.group(3)))
        for match in re.finditer(AXIS_LINE_RE, table.group(1), re.MULTILINE)
    }
    if "X" not in axes or "Y" not in axes:
        return None
    return Bounds(axes["X"][0], axes["X"][1], axes["Y"][0], axes["Y"][1])


def parse_stock(header: str) -> Optional[Bounds]:
    return parse_axis_table(header, "Stock Box") or parse_axis_table(header, "Ranges Table")


def looks_like_cnc(text: str) -> bool:
    header = text[:1_048_576]
    return not EXTRUSION_MOVE_RE.search(header)


def _arc_points(
    start: Point,
    end: Point,
    words: Dict[str, float],
    clockwise: bool,
) -> Iterable[Point]:
    if "I" in words or "J" in words:
        cx = start.x + words.get("I", 0.0)
        cy = start.y + words.get("J", 0.0)
    elif "R" in words:
        radius = abs(words["R"])
        dx = end.x - start.x
        dy = end.y - start.y
        chord = math.hypot(dx, dy)
        if chord == 0 or chord > radius * 2:
            yield end
            return
        mx = (start.x + end.x) / 2
        my = (start.y + end.y) / 2
        height = math.sqrt(max(radius * radius - (chord / 2) ** 2, 0.0))
        nx, ny = -dy / chord, dx / chord
        candidates = ((mx + nx * height, my + ny * height), (mx - nx * height, my - ny * height))
        cx, cy = min(
            candidates,
            key=lambda center: _arc_sweep(
                start,
                end,
                center[0],
                center[1],
                clockwise,
                words["R"] < 0,
            ),
        )
    else:
        yield end
        return

    start_angle = math.atan2(start.y - cy, start.x - cx)
    end_angle = math.atan2(end.y - cy, end.x - cx)
    sweep = end_angle - start_angle
    if clockwise and sweep >= 0:
        sweep -= math.tau
    elif not clockwise and sweep <= 0:
        sweep += math.tau
    if start.x == end.x and start.y == end.y:
        sweep = -math.tau if clockwise else math.tau
    radius = math.hypot(start.x - cx, start.y - cy)
    count = max(8, min(720, math.ceil(abs(sweep) * radius / ARC_SEGMENT_LENGTH)))
    for index in range(1, count + 1):
        ratio = index / count
        angle = start_angle + sweep * ratio
        yield Point(
            cx + math.cos(angle) * radius,
            cy + math.sin(angle) * radius,
            start.z + (end.z - start.z) * ratio,
        )


def _arc_sweep(
    start: Point,
    end: Point,
    cx: float,
    cy: float,
    clockwise: bool,
    prefer_major: bool,
) -> float:
    a0 = math.atan2(start.y - cy, start.x - cx)
    a1 = math.atan2(end.y - cy, end.x - cx)
    sweep = a1 - a0
    if clockwise and sweep >= 0:
        sweep -= math.tau
    elif not clockwise and sweep <= 0:
        sweep += math.tau
    magnitude = abs(sweep)
    return abs(magnitude - (math.tau if prefer_major else 0.0))


def parse_gcode(text: str) -> Tuple[List[Segment], Optional[Bounds]]:
    position = Point(0.0, 0.0, 0.0)
    absolute = True
    scale = 1.0
    motion = 0
    segments: List[Segment] = []
    header = text[:1_048_576]
    stock = parse_stock(header)

    for raw_line in text.splitlines():
        line = strip_comments(raw_line)
        if not line:
            continue
        g_codes = [int(value) for value in re.findall(r"(?<![A-Z])G0*(\d+)", line)]
        if 20 in g_codes:
            scale = 25.4
        if 21 in g_codes:
            scale = 1.0
        words = {
            letter: float(value) * (scale if letter in "XYZIJKR" else 1.0)
            for letter, value in WORD_RE.findall(line)
        }
        if 90 in g_codes:
            absolute = True
        if 91 in g_codes:
            absolute = False
        matched_motion = MOTION_RE.search(line)
        if matched_motion:
            motion = int(matched_motion.group(1))
        if not any(axis in words for axis in "XYZ") or motion not in (0, 1, 2, 3):
            continue

        end = Point(
            words["X"] + (0 if absolute else position.x) if "X" in words else position.x,
            words["Y"] + (0 if absolute else position.y) if "Y" in words else position.y,
            words["Z"] + (0 if absolute else position.z) if "Z" in words else position.z,
        )
        if end.x == position.x and end.y == position.y:
            position = end
            continue
        if motion in (0, 1):
            segments.append(Segment(position, end, motion == 0))
        else:
            arc_start = position
            for arc_end in _arc_points(position, end, words, clockwise=motion == 2):
                segments.append(Segment(arc_start, arc_end, False))
                arc_start = arc_end
                if len(segments) >= MAX_SEGMENTS:
                    break
        position = end
        if len(segments) >= MAX_SEGMENTS:
            break
    return segments, stock


def segment_bounds(segments: List[Segment], stock: Optional[Bounds]) -> Bounds:
    points = [point for segment in segments for point in (segment.start, segment.end)]
    x_values = [point.x for point in points]
    y_values = [point.y for point in points]
    bounds = Bounds(min(x_values), max(x_values), min(y_values), max(y_values))
    if stock:
        return Bounds(
            min(bounds.x_min, stock.x_min),
            max(bounds.x_max, stock.x_max),
            min(bounds.y_min, stock.y_min),
            max(bounds.y_max, stock.y_max),
        )
    return bounds


def render_thumbnail(segments: List[Segment], stock: Optional[Bounds], size: int) -> bytes:
    if not segments:
        raise ValueError("No XY motion found")
    bounds = segment_bounds(segments, stock)
    canvas = Canvas(size, size, (20, 24, 30, 255))
    margin = max(18, round(size * 0.075))
    drawable = size - margin * 2
    scale = min(drawable / bounds.width, drawable / bounds.height)
    used_width = bounds.width * scale
    used_height = bounds.height * scale
    x_offset = (size - used_width) / 2
    y_offset = (size - used_height) / 2

    def screen(point: Point) -> Tuple[int, int]:
        x = x_offset + (point.x - bounds.x_min) * scale
        y = size - (y_offset + (point.y - bounds.y_min) * scale)
        return round(x), round(y)

    grid_color = (105, 120, 138, 25)
    for index in range(1, 6):
        pos = margin + round(drawable * index / 6)
        canvas.line((margin, pos), (size - margin, pos), grid_color)
        canvas.line((pos, margin), (pos, size - margin), grid_color)

    if stock:
        left, bottom = screen(Point(stock.x_min, stock.y_min, 0))
        right, top = screen(Point(stock.x_max, stock.y_max, 0))
        canvas.rectangle(
            min(left, right),
            min(top, bottom),
            max(left, right),
            max(top, bottom),
            (104, 115, 128, 38),
            (162, 174, 188, 135),
        )

    rapid_lines = []
    cut_lines = []
    seen_rapid = set()
    seen_cut = set()
    for segment in segments:
        start = screen(segment.start)
        end = screen(segment.end)
        if start == end:
            continue
        key = (start, end) if start <= end else (end, start)
        target = rapid_lines if segment.rapid else cut_lines
        seen = seen_rapid if segment.rapid else seen_cut
        if key in seen:
            continue
        seen.add(key)
        target.append((start, end))
        if len(rapid_lines) + len(cut_lines) >= MAX_RENDERED_SEGMENTS:
            break

    rapid_color = (255, 174, 66, 145)
    cut_shadow = (0, 0, 0, 130)
    cut_color = (55, 224, 196, 240)
    for start, end in rapid_lines:
        canvas.line(start, end, rapid_color, width=1, dash=(4, 4))
    for start, end in cut_lines:
        canvas.line(start, end, cut_shadow, width=4)
        canvas.line(start, end, cut_color, width=2)

    origin = screen(Point(0, 0, 0))
    canvas.line((origin[0] - 5, origin[1]), (origin[0] + 5, origin[1]), (255, 255, 255, 210))
    canvas.line((origin[0], origin[1] - 5), (origin[0], origin[1] + 5), (255, 255, 255, 210))
    return canvas.png()


def thumbnail_block(png: bytes, size: int) -> str:
    encoded = base64.b64encode(png).decode("ascii")
    lines = [encoded[index : index + 78] for index in range(0, len(encoded), 78)]
    body = "\n".join(f"; {line}" for line in lines)
    return f"; thumbnail begin {size}x{size} {len(encoded)}\n{body}\n; thumbnail end\n"


def embed_thumbnail(path: Path, png: bytes, size: int) -> None:
    original = path.read_text(encoding="utf-8", errors="replace")
    cleaned = THUMBNAIL_RE.sub("", original)
    cleaned = re.sub(
        r"^" + re.escape(MARKER) + r"\s*$\r?\n?",
        "",
        cleaned,
        flags=re.MULTILINE,
    ).rstrip() + "\n"
    content = thumbnail_block(png, size) + cleaned + f"{MARKER}\n"
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def process(
    path: Path,
    size: int,
    preview: Optional[Path],
    embed: bool,
    force: bool,
) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text and not force and preview is None:
        return
    if not looks_like_cnc(text):
        return
    segments, stock = parse_gcode(text)
    if not segments:
        return
    png = render_thumbnail(segments, stock, size)
    if preview:
        preview.write_bytes(png)
    if embed:
        embed_thumbnail(path, png, size)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gcode", type=Path)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--preview", type=Path, help="also write the raw PNG here")
    parser.add_argument("--no-embed", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 128 <= args.size <= 1024:
        parser.error("--size must be between 128 and 1024")
    process(args.gcode, args.size, args.preview, not args.no_embed, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
