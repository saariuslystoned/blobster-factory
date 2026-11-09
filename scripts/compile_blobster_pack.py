#!/usr/bin/env python3
"""Blobster Factory — OpenClaw Blobster SVG, Tier 1 Fast Pack, QA Contact Sheet & Sprite Compiler.

Compiles and validates:
1. OpenClaw-compliant `256x256` (`viewBox="-12 -18 144 144"`) layered SVG avatars (`avatars/blobster.svg`)
   that strictly match `src/agents/blobster-generation.ts` geometry and `24px` silhouette legibility.
2. Tier 1 Fast Pack (`tier1`):
   - `512x512` 3D hero PNG (`avatars/hero-512.png`)
   - `2x2` `#FF00FF` chroma-key animation sheet -> transparent looping `avatars/blobster-idle.gif`,
     `avatars/blobster-wave.gif` (< 2 MiB), and `avatars/cutout-256.png`
   - Optional `--qa-out <path>` dark/light QA contact sheet (`24px`, `64px`, `256px` + `#FF00FF` spill & border-clip check)
3. Standalone Visual QA (`qa`):
   - Audits any `avatars/` directory for `#FF00FF` chroma-key fringe spill, border clipping, SVG shape count,
     and `< 2 MiB` OpenClaw file budgets, emitting `qa-contact-sheet.png` outside the template tree.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# Exact OpenClaw Blobster geometry from src/agents/blobster-generation.ts (MIT © 2026 OpenClaw Foundation)
OPENCLAW_LICENSE = """MIT License

Copyright (c) 2026 OpenClaw Foundation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

BODY_PATH = (
    "M60 8 C32 8 16 32 16 52 C16 72 30 90 44 95 L44 104 L54 104 L54 96 "
    "C58 97.5 62 97.5 66 96 L66 104 L76 104 L76 95 C90 90 104 72 104 52 "
    "C104 32 88 8 60 8 Z"
)
LEFT_CLAW_PATH = "M20 42 C5 37 0 47 5 57 C10 67 20 62 25 52 C28 45 25 42 20 42 Z"
RIGHT_CLAW_PATH = "M100 42 C115 37 120 47 115 57 C110 67 100 62 95 52 C92 45 95 42 100 42 Z"

LAYERS = ("back", "left_prop", "right_prop", "shell_overlay", "accessory")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SLUG_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_TAGS = {"g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}
SHAPE_TAGS = {"path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}
NUMERIC_ATTRS = {
    "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry",
    "width", "height", "stroke-width", "stroke-miterlimit", "stroke-dashoffset",
}
ENUM_ATTRS = {
    "stroke-linecap": {"butt", "round", "square"},
    "stroke-linejoin": {"miter", "round", "bevel"},
    "fill-rule": {"nonzero", "evenodd"},
    "clip-rule": {"nonzero", "evenodd"},
}
NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
NUMBER_EXACT_RE = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")
TRANSFORM_RE = re.compile(r"^(?:(?:translate|scale|rotate)\([\s,0-9eE.+-]+\)\s*)+$")
TRANSFORM_CALL_RE = re.compile(r"(translate|scale|rotate)\(([^)]*)\)")
PATH_TOKEN_RE = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
OPENCLAW_AVATAR_MAX_BYTES = 2 * 1024 * 1024
BASE_TEMPLATE_SHAPE_COUNT = 10  # 2 antennae + 2 claws + 1 body + 1 highlight + 4 eye circles
MAX_CUSTOM_SVG_SHAPES = 24


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def validate_svg_attr(name: str, value: str) -> bool:
    if name in ("fill", "stroke"):
        return value == "none" or bool(HEX_COLOR_RE.match(value))
    if name == "class":
        return bool(re.match(r"^[A-Za-z0-9_ -]+$", value))
    if name in ENUM_ATTRS:
        return value in ENUM_ATTRS[name]
    nums = NUMBER_RE.findall(value)
    if any(not math.isfinite(float(n)) or abs(float(n)) > 2000 for n in nums):
        return False
    if name in NUMERIC_ATTRS:
        return bool(NUMBER_EXACT_RE.match(value))
    if name in ("opacity", "fill-opacity", "stroke-opacity"):
        return bool(NUMBER_EXACT_RE.match(value)) and 0.0 <= float(value) <= 1.0
    if name == "d":
        stripped = NUMBER_RE.sub("", value)
        return len(nums) > 0 and bool(re.match(r"^[MmZzLlHhVvCcSsQqTtAa\s,]*$", stripped))
    if name in ("points", "stroke-dasharray"):
        stripped = NUMBER_RE.sub("", value)
        return value == "none" or (len(nums) > 0 and bool(re.match(r"^[\s,]*$", stripped)))
    if name == "transform":
        return bool(TRANSFORM_RE.match(value))
    return False


def sanitize_svg_fragment(source: str) -> str:
    if not source.strip():
        return ""
    if "<!" in source or "<?" in source:
        raise ValueError("SVG declarations are not allowed")
    wrapped = f'<svg xmlns="http://www.w3.org/2000/svg">{source}</svg>'
    root = ET.fromstring(wrapped)
    count = 0

    def render_node(elem: ET.Element, depth: int) -> str:
        nonlocal count
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag not in ALLOWED_TAGS:
            raise ValueError(f"Unsupported SVG element: {tag}")
        count += 1
        if count > 128 or depth > 12:
            raise ValueError("SVG fragment is too complex")
        attrs_list: list[str] = []
        for k, v in elem.attrib.items():
            attr_name = k.split("}")[-1] if "}" in k else k
            if not validate_svg_attr(attr_name, v):
                raise ValueError(f"Unsupported or invalid SVG attribute: {attr_name}={v!r}")
            attrs_list.append(f' {attr_name}="{escape_xml(v)}"')
        children_str = "".join(render_node(child, depth + 1) for child in list(elem))
        return f"<{tag}{''.join(attrs_list)}>{children_str}</{tag}>"

    return "".join(render_node(child, 0) for child in list(root))


def render_blobster_svg(design: dict[str, Any]) -> str:
    if design.get("version") != 1:
        raise ValueError("Blobster design version must be 1")
    design_id = design.get("id", "")
    if not SLUG_ID_RE.match(design_id) or len(design_id) > 80:
        raise ValueError(f"Invalid Blobster id: {design_id!r}")
    name = str(design.get("name", "")).strip()
    description = str(design.get("description", "")).strip()
    if not name or not description:
        raise ValueError("Blobster design requires non-empty name and description")
    palette = design.get("palette", {})
    for key in ("shell", "claw", "glint"):
        if not HEX_COLOR_RE.match(str(palette.get(key, ""))):
            raise ValueError(f"Invalid palette.{key}: {palette.get(key)!r}")
    raw_layers = design.get("layers", {})
    if raw_layers.get("back", "") != "":
        raise ValueError("Blobster layer 'back' must be an empty string (no background allowed)")
    rendered_layers = {
        layer: sanitize_svg_fragment(str(raw_layers.get(layer, "")))
        for layer in LAYERS
    }
    shell = palette["shell"]
    claw = palette["claw"]
    glint = palette["glint"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="-12 -18 144 144" role="img">
<metadata>{escape_xml(OPENCLAW_LICENSE)}</metadata>
<title>{escape_xml(name)}</title><desc>{escape_xml(description)}</desc>
<defs><clipPath id="blobster-body-clip"><path d="{BODY_PATH}"/></clipPath></defs>
<g stroke="{shell}" stroke-width="4" stroke-linecap="round" fill="none"><path d="M46 14 Q38 4 31 7"/><path d="M74 14 Q82 4 89 7"/></g>
<g>{rendered_layers["left_prop"]}<path d="{LEFT_CLAW_PATH}" fill="{claw}"/></g>
<g>{rendered_layers["right_prop"]}<path d="{RIGHT_CLAW_PATH}" fill="{claw}"/></g>
<path d="{BODY_PATH}" fill="{shell}"/>
<g clip-path="url(#blobster-body-clip)">{rendered_layers["shell_overlay"]}</g>
<ellipse cx="48" cy="28" rx="20" ry="11" fill="#ffffff" opacity="0.1"/>
<g>{rendered_layers["accessory"]}</g>
<g><circle cx="45" cy="32" r="5.5" fill="#0a1014"/><circle cx="75" cy="32" r="5.5" fill="#0a1014"/><circle cx="46.5" cy="30.5" r="2.2" fill="{glint}"/><circle cx="76.5" cy="30.5" r="2.2" fill="{glint}"/></g>
</svg>
"""


# ---------------------------------------------------------------------------
# Pure-Pillow Supersampled SVG Rasterizer (for 24px / 64px / 256px QA sheets)
# ---------------------------------------------------------------------------

Matrix2D = tuple[float, float, float, float, float, float]  # (a, b, c, d, e, f)


def _mat_mul(m1: Matrix2D, m2: Matrix2D) -> Matrix2D:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _mat_apply(m: Matrix2D, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _parse_transform(expr: str) -> Matrix2D:
    mat: Matrix2D = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for fn, raw_args in TRANSFORM_CALL_RE.findall(expr):
        nums = [float(x) for x in NUMBER_RE.findall(raw_args)]
        if fn == "translate":
            tx = nums[0] if len(nums) >= 1 else 0.0
            ty = nums[1] if len(nums) >= 2 else 0.0
            sub: Matrix2D = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif fn == "scale":
            sx = nums[0] if len(nums) >= 1 else 1.0
            sy = nums[1] if len(nums) >= 2 else sx
            sub = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif fn == "rotate":
            ang = math.radians(nums[0] if len(nums) >= 1 else 0.0)
            ca, sa = math.cos(ang), math.sin(ang)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                sub = _mat_mul(
                    (1.0, 0.0, 0.0, 1.0, cx, cy),
                    _mat_mul((ca, sa, -sa, ca, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0, -cx, -cy)),
                )
            else:
                sub = (ca, sa, -sa, ca, 0.0, 0.0)
        else:
            sub = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        mat = _mat_mul(mat, sub)
    return mat


def _sample_svg_arc(
    x1: float,
    y1: float,
    rx: float,
    ry: float,
    phi_deg: float,
    large_arc: int,
    sweep: int,
    x2: float,
    y2: float,
    steps: int = 24,
) -> list[tuple[float, float]]:
    if abs(x1 - x2) < 1e-7 and abs(y1 - y2) < 1e-7:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-7 or ry < 1e-7:
        return [(x2, y2)]

    phi = math.radians(phi_deg % 360.0)
    c_phi, s_phi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = c_phi * dx2 + s_phi * dy2
    y1p = -s_phi * dx2 + c_phi * dy2

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    num = max(0.0, rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p)
    den = max(1e-12, rx * rx * y1p * y1p + ry * ry * x1p * x1p)
    rad = math.sqrt(num / den)
    if bool(large_arc) == bool(sweep):
        rad = -rad

    cxp = rad * (rx * y1p / ry)
    cyp = rad * (-ry * x1p / rx)
    cx = c_phi * cxp - s_phi * cyp + (x1 + x2) / 2.0
    cy = s_phi * cxp + c_phi * cyp + (y1 + y2) / 2.0

    def vec_angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        mag = max(1e-12, math.hypot(ux, uy) * math.hypot(vx, vy))
        val = max(-1.0, min(1.0, dot / mag))
        ang = math.acos(val)
        return -ang if (ux * vy - uy * vx) < 0 else ang

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = vec_angle(1.0, 0.0, ux, uy)
    dtheta = vec_angle(ux, uy, vx, vy)
    if not sweep and dtheta > 0:
        dtheta -= 2.0 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2.0 * math.pi

    pts: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = theta1 + dtheta * (i / steps)
        px = cx + c_phi * rx * math.cos(t) - s_phi * ry * math.sin(t)
        py = cy + s_phi * rx * math.cos(t) + c_phi * ry * math.sin(t)
        pts.append((px, py))
    return pts


def _parse_svg_path_subpaths(d_str: str, curve_steps: int = 20) -> list[tuple[list[tuple[float, float]], bool]]:
    tokens = PATH_TOKEN_RE.findall(d_str)
    subpaths: list[tuple[list[tuple[float, float]], bool]] = []
    cur_pts: list[tuple[float, float]] = []
    cx, cy = 0.0, 0.0
    sx, sy = 0.0, 0.0
    prev_cmd = ""
    last_c2: tuple[float, float] | None = None
    last_q1: tuple[float, float] | None = None
    idx = 0
    cmd = ""

    def next_float() -> float:
        nonlocal idx
        val = float(tokens[idx])
        idx += 1
        return val

    while idx < len(tokens):
        tok = tokens[idx]
        if tok.isalpha():
            cmd = tok
            idx += 1
        elif not cmd:
            break

        if cmd in ("M", "m"):
            if cur_pts:
                subpaths.append((cur_pts, False))
                cur_pts = []
            x, y = next_float(), next_float()
            if cmd == "m":
                cx, cy = cx + x, cy + y
            else:
                cx, cy = x, y
            sx, sy = cx, cy
            cur_pts = [(cx, cy)]
            prev_cmd = cmd
            last_c2 = None
            last_q1 = None
            cmd = "l" if cmd == "m" else "L"
        elif cmd in ("Z", "z"):
            if cur_pts:
                cur_pts.append((sx, sy))
                subpaths.append((cur_pts, True))
                cur_pts = []
            cx, cy = sx, sy
            prev_cmd = cmd
            last_c2 = None
            last_q1 = None
            cmd = ""
        elif cmd in ("L", "l"):
            x, y = next_float(), next_float()
            cx, cy = (cx + x, cy + y) if cmd == "l" else (x, y)
            cur_pts.append((cx, cy))
            prev_cmd = cmd
            last_c2 = None
            last_q1 = None
        elif cmd in ("H", "h"):
            x = next_float()
            cx = cx + x if cmd == "h" else x
            cur_pts.append((cx, cy))
            prev_cmd = cmd
            last_c2 = None
            last_q1 = None
        elif cmd in ("V", "v"):
            y = next_float()
            cy = cy + y if cmd == "v" else y
            cur_pts.append((cx, cy))
            prev_cmd = cmd
            last_c2 = None
            last_q1 = None
        elif cmd in ("C", "c"):
            x1, y1 = next_float(), next_float()
            x2, y2 = next_float(), next_float()
            x, y = next_float(), next_float()
            if cmd == "c":
                x1, y1 = cx + x1, cy + y1
                x2, y2 = cx + x2, cy + y2
                x, y = cx + x, cy + y
            p0x, p0y = cx, cy
            for step in range(1, curve_steps + 1):
                t = step / curve_steps
                mt = 1.0 - t
                px = mt**3 * p0x + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x
                py = mt**3 * p0y + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y
                cur_pts.append((px, py))
            cx, cy = x, y
            last_c2 = (x2, y2)
            last_q1 = None
            prev_cmd = cmd
        elif cmd in ("S", "s"):
            x2, y2 = next_float(), next_float()
            x, y = next_float(), next_float()
            if cmd == "s":
                x2, y2 = cx + x2, cy + y2
                x, y = cx + x, cy + y
            if prev_cmd in ("C", "c", "S", "s") and last_c2 is not None:
                x1, y1 = 2.0 * cx - last_c2[0], 2.0 * cy - last_c2[1]
            else:
                x1, y1 = cx, cy
            p0x, p0y = cx, cy
            for step in range(1, curve_steps + 1):
                t = step / curve_steps
                mt = 1.0 - t
                px = mt**3 * p0x + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x
                py = mt**3 * p0y + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y
                cur_pts.append((px, py))
            cx, cy = x, y
            last_c2 = (x2, y2)
            last_q1 = None
            prev_cmd = cmd
        elif cmd in ("Q", "q"):
            x1, y1 = next_float(), next_float()
            x, y = next_float(), next_float()
            if cmd == "q":
                x1, y1 = cx + x1, cy + y1
                x, y = cx + x, cy + y
            p0x, p0y = cx, cy
            for step in range(1, curve_steps + 1):
                t = step / curve_steps
                mt = 1.0 - t
                px = mt * mt * p0x + 2 * mt * t * x1 + t * t * x
                py = mt * mt * p0y + 2 * mt * t * y1 + t * t * y
                cur_pts.append((px, py))
            cx, cy = x, y
            last_q1 = (x1, y1)
            last_c2 = None
            prev_cmd = cmd
        elif cmd in ("T", "t"):
            x, y = next_float(), next_float()
            if cmd == "t":
                x, y = cx + x, cy + y
            if prev_cmd in ("Q", "q", "T", "t") and last_q1 is not None:
                x1, y1 = 2.0 * cx - last_q1[0], 2.0 * cy - last_q1[1]
            else:
                x1, y1 = cx, cy
            p0x, p0y = cx, cy
            for step in range(1, curve_steps + 1):
                t = step / curve_steps
                mt = 1.0 - t
                px = mt * mt * p0x + 2 * mt * t * x1 + t * t * x
                py = mt * mt * p0y + 2 * mt * t * y1 + t * t * y
                cur_pts.append((px, py))
            cx, cy = x, y
            last_q1 = (x1, y1)
            last_c2 = None
            prev_cmd = cmd
        elif cmd in ("A", "a"):
            rx, ry = next_float(), next_float()
            rot = next_float()
            large_arc = int(round(next_float()))
            sweep = int(round(next_float()))
            x, y = next_float(), next_float()
            if cmd == "a":
                x, y = cx + x, cy + y
            cur_pts.extend(_sample_svg_arc(cx, cy, rx, ry, rot, large_arc, sweep, x, y, steps=curve_steps))
            cx, cy = x, y
            last_c2 = None
            last_q1 = None
            prev_cmd = cmd
        else:
            break

    if cur_pts:
        subpaths.append((cur_pts, False))
    return subpaths


def _hex_to_rgba(color_str: str | None, alpha_mult: float = 1.0) -> tuple[int, int, int, int] | None:
    if not color_str or color_str == "none":
        return None
    if HEX_COLOR_RE.match(color_str):
        r = int(color_str[1:3], 16)
        g = int(color_str[3:5], 16)
        b = int(color_str[5:7], 16)
        a = max(0, min(255, int(round(255.0 * alpha_mult))))
        return (r, g, b, a)
    return None


def _sample_ellipse_pts(cx: float, cy: float, rx: float, ry: float, steps: int = 48) -> list[tuple[float, float]]:
    pts = [
        (cx + rx * math.cos(2.0 * math.pi * i / steps), cy + ry * math.sin(2.0 * math.pi * i / steps))
        for i in range(steps)
    ]
    pts.append(pts[0])
    return pts


def _sample_rect_pts(x: float, y: float, w: float, h: float, rx: float, ry: float) -> list[tuple[float, float]]:
    rx = min(max(0.0, rx), w / 2.0)
    ry = min(max(0.0, ry), h / 2.0)
    if rx < 1e-4 or ry < 1e-4:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    pts: list[tuple[float, float]] = []
    corners = [
        (x + w - rx, y + ry, -math.pi / 2.0, 0.0),
        (x + w - rx, y + h - ry, 0.0, math.pi / 2.0),
        (x + rx, y + h - ry, math.pi / 2.0, math.pi),
        (x + rx, y + ry, math.pi, 1.5 * math.pi),
    ]
    for ccx, ccy, a0, a1 in corners:
        for i in range(9):
            ang = a0 + (a1 - a0) * (i / 8.0)
            pts.append((ccx + rx * math.cos(ang), ccy + ry * math.sin(ang)))
    pts.append(pts[0])
    return pts


def rasterize_blobster_svg(svg_text: str, out_size: int = 256, supersample: int = 4) -> Image.Image:
    """Rasterize a validated OpenClaw Blobster SVG to an RGBA Image using pure Pillow."""
    root = ET.fromstring(svg_text)
    vb_parts = [float(x) for x in root.attrib.get("viewBox", "-12 -18 144 144").split()]
    vb_x, vb_y, vb_w, vb_h = vb_parts if len(vb_parts) == 4 else (-12.0, -18.0, 144.0, 144.0)

    ss_px = max(64, out_size * supersample)
    sx = ss_px / vb_w
    sy = ss_px / vb_h
    root_mat: Matrix2D = (sx, 0.0, 0.0, sy, -vb_x * sx, -vb_y * sy)

    # Collect clipPath polygons in supersampled coordinates
    clip_masks: dict[str, Image.Image] = {}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "clipPath" and elem.attrib.get("id"):
            cid = elem.attrib["id"]
            mask = Image.new("L", (ss_px, ss_px), 0)
            mdraw = ImageDraw.Draw(mask)
            for child in elem:
                ctag = child.tag.split("}")[-1]
                if ctag == "path" and child.attrib.get("d"):
                    for pts, _ in _parse_svg_path_subpaths(child.attrib["d"]):
                        tpts = [_mat_apply(root_mat, px, py) for px, py in pts]
                        if len(tpts) >= 3:
                            mdraw.polygon(tpts, fill=255)
            clip_masks[cid] = mask

    def extract_subpaths(elem: ET.Element, tag: str) -> list[tuple[list[tuple[float, float]], bool]]:
        a = elem.attrib
        if tag == "path":
            return _parse_svg_path_subpaths(a.get("d", ""))
        if tag == "circle":
            cx, cy, r = float(a.get("cx", 0)), float(a.get("cy", 0)), float(a.get("r", 0))
            return [(_sample_ellipse_pts(cx, cy, r, r), True)] if r > 0 else []
        if tag == "ellipse":
            cx, cy = float(a.get("cx", 0)), float(a.get("cy", 0))
            rx, ry = float(a.get("rx", 0)), float(a.get("ry", 0))
            return [(_sample_ellipse_pts(cx, cy, rx, ry), True)] if rx > 0 and ry > 0 else []
        if tag == "rect":
            x, y = float(a.get("x", 0)), float(a.get("y", 0))
            w, h = float(a.get("width", 0)), float(a.get("height", 0))
            rx_raw, ry_raw = a.get("rx"), a.get("ry")
            rx = float(rx_raw) if rx_raw is not None else (float(ry_raw) if ry_raw is not None else 0.0)
            ry = float(ry_raw) if ry_raw is not None else rx
            return [(_sample_rect_pts(x, y, w, h, rx, ry), True)] if w > 0 and h > 0 else []
        if tag == "line":
            x1, y1 = float(a.get("x1", 0)), float(a.get("y1", 0))
            x2, y2 = float(a.get("x2", 0)), float(a.get("y2", 0))
            return [([(x1, y1), (x2, y2)], False)]
        if tag in ("polyline", "polygon"):
            nums = [float(n) for n in NUMBER_RE.findall(a.get("points", ""))]
            pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
            if tag == "polygon" and pts:
                pts.append(pts[0])
                return [(pts, True)]
            return [(pts, False)] if pts else []
        return []

    def draw_node(target: Image.Image, elem: ET.Element, mat: Matrix2D, inherited: dict[str, str]) -> None:
        tag = elem.tag.split("}")[-1]
        if tag in ("metadata", "title", "desc", "defs", "clipPath"):
            return

        style = dict(inherited)
        for k in ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"):
            if k in elem.attrib:
                style[k] = elem.attrib[k]

        cur_mat = _mat_mul(mat, _parse_transform(elem.attrib["transform"])) if "transform" in elem.attrib else mat
        node_opacity = float(elem.attrib.get("opacity", "1.0")) * float(inherited.get("_opacity", "1.0"))
        style["_opacity"] = str(node_opacity)

        clip_attr = elem.attrib.get("clip-path", "")
        clip_id = clip_attr[5:-1] if clip_attr.startswith("url(#") and clip_attr.endswith(")") else None

        dest_img = Image.new("RGBA", (ss_px, ss_px), (0, 0, 0, 0)) if clip_id in clip_masks else target

        if tag == "g":
            for child in elem:
                draw_node(dest_img, child, cur_mat, style)
        elif tag in SHAPE_TAGS:
            subpaths = extract_subpaths(elem, tag)
            default_fill = "none" if tag == "line" else "#000000"
            fill_str = style.get("fill", default_fill)
            stroke_str = style.get("stroke", "none")
            fill_op = float(elem.attrib.get("fill-opacity", "1.0")) * node_opacity
            stroke_op = float(elem.attrib.get("stroke-opacity", "1.0")) * node_opacity
            fill_rgba = _hex_to_rgba(fill_str, fill_op)
            stroke_rgba = _hex_to_rgba(stroke_str, stroke_op)
            sw_units = float(style.get("stroke-width", "1.0"))
            mat_scale = math.hypot(cur_mat[0], cur_mat[1])
            sw_px = max(1, int(round(sw_units * mat_scale)))
            linecap = style.get("stroke-linecap", "butt")

            if fill_rgba or stroke_rgba:
                layer = Image.new("RGBA", (ss_px, ss_px), (0, 0, 0, 0))
                ldraw = ImageDraw.Draw(layer)
                for pts, closed in subpaths:
                    tpts = [_mat_apply(cur_mat, px, py) for px, py in pts]
                    if fill_rgba and len(tpts) >= 3 and tag != "line":
                        ldraw.polygon(tpts, fill=fill_rgba)
                    if stroke_rgba and len(tpts) >= 2 and sw_units > 0:
                        ldraw.line(tpts, fill=stroke_rgba, width=sw_px, joint="curve")
                        if linecap == "round" or closed:
                            rad = sw_px / 2.0
                            cap_pts = tpts if closed else [tpts[0], tpts[-1]]
                            for cx_p, cy_p in cap_pts:
                                ldraw.ellipse((cx_p - rad, cy_p - rad, cx_p + rad, cy_p + rad), fill=stroke_rgba)
                dest_img.alpha_composite(layer)

        if clip_id in clip_masks:
            r_ch, g_ch, b_ch, a_ch = dest_img.split()
            clipped_a = Image.composite(a_ch, Image.new("L", (ss_px, ss_px), 0), clip_masks[clip_id])
            dest_img = Image.merge("RGBA", (r_ch, g_ch, b_ch, clipped_a))
            target.alpha_composite(dest_img)

    canvas = Image.new("RGBA", (ss_px, ss_px), (0, 0, 0, 0))
    for child in root:
        draw_node(canvas, child, root_mat, {"_opacity": "1.0"})

    if ss_px != out_size:
        return canvas.resize((out_size, out_size), Image.Resampling.LANCZOS)
    return canvas


# ---------------------------------------------------------------------------
# Tier 1 Chroma-Key Extraction & GIF Compilation
# ---------------------------------------------------------------------------


def despike_magenta_cell(cell_img: Image.Image) -> Image.Image:
    """Remove #FF00FF chroma-key background with edge despill."""
    rgba = cell_img.convert("RGBA")
    w, h = rgba.size
    pixels = rgba.load()

    border_samples: list[tuple[int, int, int]] = []
    for x in range(w):
        for y in (0, 1, h - 2, h - 1):
            r, g, b, _ = pixels[x, y]
            if r > 140 and b > 140 and g < 120:
                border_samples.append((r, g, b))
    for y in range(h):
        for x in (0, 1, w - 2, w - 1):
            r, g, b, _ = pixels[x, y]
            if r > 140 and b > 140 and g < 120:
                border_samples.append((r, g, b))

    if border_samples:
        kr = sum(p[0] for p in border_samples) / len(border_samples)
        kg = sum(p[1] for p in border_samples) / len(border_samples)
        kb = sum(p[2] for p in border_samples) / len(border_samples)
    else:
        kr, kg, kb = 255.0, 0.0, 255.0

    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            dist = math.sqrt((r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2)
            magenta_excess = min(r, b) - g
            if dist < 68 or (magenta_excess > 105 and b > 145 and abs(r - b) < 75):
                pixels[x, y] = (0, 0, 0, 0)
            elif dist < 115 or (magenta_excess > 70 and b > 120 and abs(r - b) < 85):
                factor = max(0.0, min(1.0, (dist - 68.0) / 47.0))
                new_a = int(a * factor)
                clamped_b = min(b, int((r + g) * 0.45)) if b > r * 0.7 else b
                pixels[x, y] = (r, g, clamped_b, new_a)

    return rgba


def normalize_cell_frame(cell_rgba: Image.Image, target_size: int = 256, pad_ratio: float = 0.08) -> Image.Image:
    """Center and scale extracted character bounding box onto a transparent square frame."""
    alpha = cell_rgba.split()[3]
    mask = alpha.point(lambda p: 255 if p > 24 else 0)
    bbox = mask.getbbox()
    canvas = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
    if not bbox:
        return canvas
    cropped = cell_rgba.crop(bbox)
    cw, ch = cropped.size
    max_dim = int(target_size * (1.0 - 2.0 * pad_ratio))
    scale = min(max_dim / max(cw, 1), max_dim / max(ch, 1))
    nw = max(1, int(round(cw * scale)))
    nh = max(1, int(round(ch * scale)))
    resized = cropped.resize((nw, nh), Image.Resampling.LANCZOS)
    ox = (target_size - nw) // 2
    oy = target_size - int(target_size * pad_ratio) - nh
    canvas.alpha_composite(resized, (ox, oy))
    return canvas


def save_transparent_gif(frames: list[Image.Image], out_path: Path, duration_ms: int = 220) -> None:
    """Save RGBA frames as a clean looping transparent GIF89a under 2 MiB."""
    pal_frames: list[Image.Image] = []
    for frame in frames:
        rgba = frame.convert("RGBA")
        alpha = rgba.split()[3]
        rgb = Image.new("RGB", rgba.size, (17, 22, 20))
        rgb.paste(rgba, mask=alpha)
        quant = rgb.quantize(colors=255, method=Image.Quantize.FASTOCTREE)
        mask = Image.eval(alpha, lambda a: 255 if a <= 64 else 0)
        quant.paste(255, mask)
        quant.info["transparency"] = 255
        quant.info["disposal"] = 2
        pal_frames.append(quant)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pal_frames[0].save(
        out_path,
        save_all=True,
        append_images=pal_frames[1:],
        loop=0,
        duration=duration_ms,
        transparency=255,
        disposal=2,
        optimize=True,
    )
    size = out_path.stat().st_size
    if size > OPENCLAW_AVATAR_MAX_BYTES:
        raise ValueError(f"Generated GIF {out_path} ({size} bytes) exceeds 2 MiB limit")


# ---------------------------------------------------------------------------
# Deterministic Pack QA & Contact Sheet Renderer
# ---------------------------------------------------------------------------


def analyze_frame_qa(frame: Image.Image) -> dict[str, Any]:
    """Measure outer 1px border clipping and residual #FF00FF magenta fringe spill on an RGBA frame."""
    rgba = frame.convert("RGBA")
    w, h = rgba.size
    pixels = rgba.load()

    border_clip_px = 0
    for x in range(w):
        if pixels[x, 0][3] > 24:
            border_clip_px += 1
        if h > 1 and pixels[x, h - 1][3] > 24:
            border_clip_px += 1
    for y in range(1, max(1, h - 1)):
        if pixels[0, y][3] > 24:
            border_clip_px += 1
        if w > 1 and pixels[w - 1, y][3] > 24:
            border_clip_px += 1

    opaque_px = 0
    spill_px = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a <= 24:
                continue
            opaque_px += 1
            magenta_excess = min(r, b) - g
            if magenta_excess > 70 and b > 120 and abs(r - b) < 85:
                spill_px += 1

    spill_pct = round((100.0 * spill_px / max(1, opaque_px)), 3)
    return {
        "width": w,
        "height": h,
        "opaquePixels": opaque_px,
        "borderClipPixels": border_clip_px,
        "magentaSpillPixels": spill_px,
        "magentaSpillPct": spill_pct,
    }


def _extract_gif_rgba_frames(gif_path: Path) -> list[Image.Image]:
    frames: list[Image.Image] = []
    with Image.open(gif_path) as gim:
        n_frames = getattr(gim, "n_frames", 1)
        for idx in range(n_frames):
            gim.seek(idx)
            frames.append(gim.convert("RGBA").copy())
    return frames


def analyze_pack_qa(avatars_dir: Path, max_spill_pct: float = 1.5) -> dict[str, Any]:
    """Run deterministic QA checks on an OpenClaw Blobster avatars/ directory."""
    errors: list[str] = []
    svg_path = avatars_dir / "blobster.svg"
    design_path = avatars_dir / "blobster-design.json"
    hero_path = avatars_dir / "hero-512.png"
    cutout_path = avatars_dir / "cutout-256.png"
    idle_path = avatars_dir / "blobster-idle.gif"
    wave_path = avatars_dir / "blobster-wave.gif"

    agent_id = avatars_dir.parent.parent.name if avatars_dir.name == "avatars" else avatars_dir.name
    agent_name = agent_id
    if design_path.is_file():
        try:
            d_obj = json.loads(design_path.read_text(encoding="utf-8"))
            agent_id = str(d_obj.get("id", agent_id))
            agent_name = str(d_obj.get("name", agent_name))
            if d_obj.get("layers", {}).get("back", "") != "":
                errors.append("blobster-design.json layer 'back' must be empty")
        except Exception as exc:
            errors.append(f"Invalid blobster-design.json: {exc}")

    total_svg_shapes = 0
    custom_svg_shapes = 0
    svg_bytes = 0
    if not svg_path.is_file():
        errors.append("Missing blobster.svg")
    else:
        svg_bytes = svg_path.stat().st_size
        if svg_bytes > OPENCLAW_AVATAR_MAX_BYTES:
            errors.append(f"blobster.svg ({svg_bytes}B) exceeds 2 MiB")
        try:
            root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
            if root.attrib.get("viewBox") != "-12 -18 144 144":
                errors.append("blobster.svg viewBox must be '-12 -18 144 144'")
            if root.attrib.get("width") != "256" or root.attrib.get("height") != "256":
                errors.append("blobster.svg dimensions must be 256x256")
            in_defs = False
            for elem in root.iter():
                tag = elem.tag.split("}")[-1]
                if tag == "defs":
                    in_defs = True
                    continue
                if not in_defs and tag in SHAPE_TAGS:
                    total_svg_shapes += 1
            # Re-count excluding <defs> accurately
            defs_shapes = sum(
                1
                for d in root.findall("{http://www.w3.org/2000/svg}defs") + root.findall("defs")
                for e in d.iter()
                if e.tag.split("}")[-1] in SHAPE_TAGS
            )
            all_shapes = sum(1 for e in root.iter() if e.tag.split("}")[-1] in SHAPE_TAGS)
            total_svg_shapes = max(0, all_shapes - defs_shapes)
            custom_svg_shapes = max(0, total_svg_shapes - BASE_TEMPLATE_SHAPE_COUNT)
            if custom_svg_shapes > MAX_CUSTOM_SVG_SHAPES:
                errors.append(
                    f"blobster.svg has {custom_svg_shapes} custom vector shapes (exceeds {MAX_CUSTOM_SVG_SHAPES} 24px legibility cap)"
                )
        except Exception as exc:
            errors.append(f"Invalid blobster.svg XML: {exc}")

    hero_bytes = 0
    if not hero_path.is_file():
        errors.append("Missing hero-512.png")
    else:
        hero_bytes = hero_path.stat().st_size
        if hero_bytes > OPENCLAW_AVATAR_MAX_BYTES:
            errors.append(f"hero-512.png ({hero_bytes}B) exceeds 2 MiB")
        with Image.open(hero_path) as him:
            if him.size != (512, 512):
                errors.append(f"hero-512.png size {him.size} != (512, 512)")

    frame_metrics: dict[str, Any] = {}
    max_border_clip = 0
    max_spill = 0.0

    if not cutout_path.is_file():
        errors.append("Missing cutout-256.png")
    else:
        with Image.open(cutout_path) as cim:
            m_cut = analyze_frame_qa(cim)
            frame_metrics["cutout-256.png"] = m_cut
            max_border_clip = max(max_border_clip, m_cut["borderClipPixels"])
            max_spill = max(max_spill, m_cut["magentaSpillPct"])

    gif_bytes: dict[str, int] = {}
    for gpath in (idle_path, wave_path):
        if not gpath.is_file():
            errors.append(f"Missing {gpath.name}")
            continue
        sz = gpath.stat().st_size
        gif_bytes[gpath.name] = sz
        if sz > OPENCLAW_AVATAR_MAX_BYTES:
            errors.append(f"{gpath.name} ({sz}B) exceeds 2 MiB")
        frames = _extract_gif_rgba_frames(gpath)
        if len(frames) < 2:
            errors.append(f"{gpath.name} must contain >= 2 animation frames")
        for f_idx, fr in enumerate(frames):
            fm = analyze_frame_qa(fr)
            frame_metrics[f"{gpath.name}#f{f_idx}"] = fm
            max_border_clip = max(max_border_clip, fm["borderClipPixels"])
            max_spill = max(max_spill, fm["magentaSpillPct"])

    if max_border_clip > 0:
        errors.append(f"Detected {max_border_clip} border-clipped foreground pixels on outer 1px frame boundary")
    if max_spill > max_spill_pct:
        errors.append(f"Max #FF00FF magenta fringe spill {max_spill:.2f}% exceeds {max_spill_pct:.2f}% threshold")

    return {
        "ok": len(errors) == 0,
        "id": agent_id,
        "name": agent_name,
        "avatarsDir": str(avatars_dir.resolve()),
        "maxMagentaSpillPct": round(max_spill, 3),
        "maxSpillThresholdPct": max_spill_pct,
        "maxBorderClipPixels": max_border_clip,
        "customSvgShapes": custom_svg_shapes,
        "totalSvgShapes": total_svg_shapes,
        "svgBytes": svg_bytes,
        "hero512Bytes": hero_bytes,
        "idleGifBytes": gif_bytes.get("blobster-idle.gif", 0),
        "waveGifBytes": gif_bytes.get("blobster-wave.gif", 0),
        "frameMetrics": frame_metrics,
        "errors": errors,
    }


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for c in candidates:
        if Path(c).is_file():
            try:
                return ImageFont.truetype(c, size=size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_qa_contact_sheet(avatars_dir: Path, out_path: Path, qa_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render a 1280x760 dark/light visual QA contact sheet for an OpenClaw Blobster pack."""
    qa = qa_report or analyze_pack_qa(avatars_dir)
    svg_text = (avatars_dir / "blobster.svg").read_text(encoding="utf-8")
    svg_256 = rasterize_blobster_svg(svg_text, out_size=256, supersample=4)
    svg_64 = rasterize_blobster_svg(svg_text, out_size=64, supersample=4)
    svg_24 = rasterize_blobster_svg(svg_text, out_size=24, supersample=8)
    svg_24_loupe = svg_24.resize((96, 96), Image.Resampling.NEAREST)

    cutout_256 = Image.open(avatars_dir / "cutout-256.png").convert("RGBA")
    cutout_64 = cutout_256.resize((64, 64), Image.Resampling.LANCZOS)
    cutout_24 = cutout_256.resize((24, 24), Image.Resampling.LANCZOS)
    hero_88 = Image.open(avatars_dir / "hero-512.png").convert("RGBA").resize((88, 88), Image.Resampling.LANCZOS)
    idle_frames = _extract_gif_rgba_frames(avatars_dir / "blobster-idle.gif")
    wave_frames = _extract_gif_rgba_frames(avatars_dir / "blobster-wave.gif")

    W, H = 1280, 760
    sheet = Image.new("RGBA", (W, H), (15, 19, 25, 255))
    draw = ImageDraw.Draw(sheet)

    f_title = _load_font(22, bold=True)
    f_sub = _load_font(13, bold=False)
    f_sec = _load_font(15, bold=True)
    f_lbl = _load_font(12, bold=False)
    f_pill = _load_font(13, bold=True)
    f_val = _load_font(20, bold=True)

    # Top header bar
    draw.rounded_rectangle((20, 16, W - 20, 88), radius=14, fill=(23, 29, 38, 255), outline=(45, 55, 72, 255), width=1)
    draw.text((40, 28), f"BLOBSTER QA CONTACT SHEET  ·  {qa['name']} ({qa['id']})", font=f_title, fill=(248, 250, 252, 255))
    draw.text(
        (40, 57),
        "24px SVG silhouette + 4x pixel loupe  ·  64px sidebar  ·  256px cutout safe-frame  ·  #FF00FF chroma-spill & GIF frame audit",
        font=f_sub,
        fill=(148, 163, 184, 255),
    )

    badge_ok = qa["ok"]
    badge_bg = (20, 83, 45, 255) if badge_ok else (127, 29, 29, 255)
    badge_fg = (134, 239, 172, 255) if badge_ok else (254, 202, 202, 255)
    badge_txt = "PASS · READY TO SHIP" if badge_ok else "FAIL · QA BLOCKED"
    draw.rounded_rectangle((W - 245, 32, W - 40, 72), radius=10, fill=badge_bg, outline=badge_fg, width=1)
    draw.text((W - 142, 52), badge_txt, font=f_pill, fill=badge_fg, anchor="mm")

    # Dark (#0D1117) and Light (#F8FAFC) surface panels
    panels = [
        ("Dark Surface (#0D1117)", 20, (13, 17, 23, 255), (30, 41, 59, 255), (241, 245, 249, 255), (148, 163, 184, 255), (22, 27, 34, 255)),
        ("Light Surface (#F8FAFC)", 648, (248, 250, 252, 255), (203, 213, 225, 255), (15, 23, 42, 255), (71, 85, 105, 255), (255, 255, 255, 255)),
    ]

    handle = f"@{qa['id'].replace('blobster-', '')}"
    cutout_192 = cutout_256.resize((192, 192), Image.Resampling.LANCZOS)
    idle_f1_88 = idle_frames[min(1, len(idle_frames) - 1)].resize((88, 88), Image.Resampling.LANCZOS)
    wave_f2_88 = wave_frames[min(2, len(wave_frames) - 1)].resize((88, 88), Image.Resampling.LANCZOS)

    for title, px, bg_col, border_col, fg_col, muted_col, card_col in panels:
        pw, py, ph = 612, 104, 492
        draw.rounded_rectangle((px, py, px + pw, py + ph), radius=16, fill=bg_col, outline=border_col, width=2)
        draw.text((px + 22, py + 18), title, font=f_sec, fill=fg_col)
        draw.text((px + pw - 210, py + 20), "24px · 64px · 256px · GIFs", font=f_lbl, fill=muted_col)

        # Row 1 Left: 24px chat pills (SVG + Cutout)
        pill1_x, pill1_y = px + 22, py + 58
        draw.rounded_rectangle((pill1_x, pill1_y, pill1_x + 150, pill1_y + 38), radius=19, fill=card_col, outline=border_col, width=1)
        sheet.alpha_composite(svg_24, (pill1_x + 10, pill1_y + 7))
        draw.text((pill1_x + 42, pill1_y + 11), handle, font=f_pill, fill=fg_col)
        draw.text((pill1_x + 4, pill1_y + 44), "24px SVG chat pill", font=f_lbl, fill=muted_col)

        pill2_y = pill1_y + 68
        draw.rounded_rectangle((pill1_x, pill2_y, pill1_x + 150, pill2_y + 38), radius=19, fill=card_col, outline=border_col, width=1)
        sheet.alpha_composite(cutout_24, (pill1_x + 10, pill2_y + 7))
        draw.text((pill1_x + 42, pill2_y + 11), handle, font=f_pill, fill=fg_col)
        draw.text((pill1_x + 4, pill2_y + 44), "24px 3D GIF/cutout pill", font=f_lbl, fill=muted_col)

        # Row 1 Middle: 4x pixel loupe of 24px SVG (96x96)
        lx, ly = px + 196, py + 56
        draw.rounded_rectangle((lx, ly, lx + 112, ly + 112), radius=12, fill=card_col, outline=border_col, width=1)
        sheet.alpha_composite(svg_24_loupe, (lx + 8, ly + 8))
        draw.text((lx + 4, ly + 118), "24px SVG (4x loupe)", font=f_lbl, fill=muted_col)

        # Row 1 Right: 64px SVG & 64px Cutout cards
        s64_x, s64_y = px + 332, py + 56
        draw.rounded_rectangle((s64_x, s64_y, s64_x + 112, s64_y + 112), radius=12, fill=card_col, outline=border_col, width=1)
        sheet.alpha_composite(svg_64, (s64_x + 24, s64_y + 24))
        draw.text((s64_x + 18, s64_y + 118), "64px SVG", font=f_lbl, fill=muted_col)

        c64_x = px + 466
        draw.rounded_rectangle((c64_x, s64_y, c64_x + 112, s64_y + 112), radius=12, fill=card_col, outline=border_col, width=1)
        sheet.alpha_composite(cutout_64, (c64_x + 24, s64_y + 24))
        draw.text((c64_x + 14, s64_y + 118), "64px Cutout", font=f_lbl, fill=muted_col)

        # Row 2 Left: Large Cutout Safe-Frame & Spill Box
        big_x, big_y = px + 22, py + 248
        draw.rounded_rectangle((big_x, big_y, big_x + 216, big_y + 212), radius=14, fill=card_col, outline=border_col, width=1)
        # Dashed/subtle safe border around 192x192 cutout
        draw.rectangle((big_x + 11, big_y + 9, big_x + 205, big_y + 203), outline=(56, 189, 248, 95), width=1)
        sheet.alpha_composite(cutout_192, (big_x + 12, big_y + 10))
        draw.text((big_x + 14, big_y + 217), "256px Cutout · Edge & #FF00FF Spill", font=f_lbl, fill=muted_col)

        # Row 2 Right: Idle GIF frame, Wave GIF frame, 3D Hero thumb + 256px SVG preview
        strip_items = [
            (idle_f1_88, "Idle GIF f1"),
            (wave_f2_88, "Wave GIF f2"),
            (hero_88, "512px 3D Hero"),
        ]
        for idx_s, (thumb, caption) in enumerate(strip_items):
            tx = px + 260 + idx_s * 112
            ty = py + 252
            draw.rounded_rectangle((tx, ty, tx + 102, ty + 102), radius=12, fill=card_col, outline=border_col, width=1)
            if caption == "512px 3D Hero":
                sheet.paste(thumb, (tx + 7, ty + 7))
            else:
                sheet.alpha_composite(thumb, (tx + 7, ty + 7))
            draw.text((tx + 8, ty + 108), caption, font=f_lbl, fill=muted_col)

        # Compact frame-check summary inside panel bottom-right
        note_y = py + 392
        draw.rounded_rectangle((px + 260, note_y, px + 586, note_y + 68), radius=10, fill=card_col, outline=border_col, width=1)
        svg_mini = svg_256.resize((52, 52), Image.Resampling.LANCZOS)
        sheet.alpha_composite(svg_mini, (px + 270, note_y + 8))
        draw.text((px + 332, note_y + 14), f"Vector + GIF Parity · {qa['id']}", font=f_lbl, fill=fg_col)
        draw.text(
            (px + 332, note_y + 37),
            f"Spill {qa['maxMagentaSpillPct']:.2f}%  ·  Clip {qa['maxBorderClipPixels']}px  ·  Shapes {qa['customSvgShapes']}",
            font=f_lbl,
            fill=muted_col,
        )

    # Bottom Telemetry Cards (4 cards across 1240px)
    idle_kb = qa["idleGifBytes"] // 1024
    wave_kb = qa["waveGifBytes"] // 1024
    hero_kb = qa["hero512Bytes"] // 1024
    cards = [
        (
            "#FF00FF Fringe Spill",
            f"{qa['maxMagentaSpillPct']:.2f}%",
            f"Threshold <= {qa['maxSpillThresholdPct']:.2f}% across all frames",
            qa["maxMagentaSpillPct"] <= qa["maxSpillThresholdPct"],
        ),
        (
            "Frame Border Clipping",
            f"{qa['maxBorderClipPixels']} border px",
            "0 outer-perimeter pixels clipped",
            qa["maxBorderClipPixels"] == 0,
        ),
        (
            "24px Custom SVG Shapes",
            f"{qa['customSvgShapes']} shapes",
            f"Target <= {MAX_CUSTOM_SVG_SHAPES} · viewBox -12 -18 144 144",
            qa["customSvgShapes"] <= MAX_CUSTOM_SVG_SHAPES,
        ),
        (
            "OpenClaw < 2 MiB Budgets",
            f"{idle_kb}KB · {wave_kb}KB · {hero_kb}KB",
            "idle.gif · wave.gif · hero-512.png (< 2048 KB)",
            max(qa["idleGifBytes"], qa["waveGifBytes"], qa["hero512Bytes"]) <= OPENCLAW_AVATAR_MAX_BYTES,
        ),
    ]
    cw_card = 298
    gap = 16
    for idx_c, (c_title, c_val, c_sub, c_ok) in enumerate(cards):
        cx0 = 20 + idx_c * (cw_card + gap)
        cy0 = 614
        accent = (74, 222, 128, 255) if c_ok else (248, 113, 113, 255)
        draw.rounded_rectangle((cx0, cy0, cx0 + cw_card, cy0 + 126), radius=14, fill=(23, 29, 38, 255), outline=(45, 55, 72, 255), width=1)
        draw.text((cx0 + 18, cy0 + 16), c_title, font=f_lbl, fill=(148, 163, 184, 255))
        draw.text((cx0 + 18, cy0 + 44), c_val, font=f_val, fill=accent)
        draw.text((cx0 + 18, cy0 + 86), c_sub, font=f_lbl, fill=(148, 163, 184, 255))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out_path, format="PNG", optimize=True)
    return {**qa, "contactSheet": str(out_path.resolve()), "contactSheetBytes": out_path.stat().st_size}


def compile_tier1_pack(
    design_json_path: Path,
    hero_source_path: Path,
    sheet_2x2_path: Path,
    output_dir: Path,
    gif_size: int = 256,
    qa_out_path: Path | None = None,
    max_spill_pct: float = 1.5,
) -> dict[str, Any]:
    design = json.loads(design_json_path.read_text(encoding="utf-8"))
    svg_text = render_blobster_svg(design)

    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / "blobster.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    hero_img = Image.open(hero_source_path).convert("RGBA")
    hw, hh = hero_img.size
    side = min(hw, hh)
    left = (hw - side) // 2
    top = (hh - side) // 2
    hero_512 = hero_img.crop((left, top, left + side, top + side)).resize(
        (512, 512), Image.Resampling.LANCZOS
    )
    hero_512_path = output_dir / "hero-512.png"
    hero_512.save(hero_512_path, format="PNG", optimize=True)

    sheet_img = Image.open(sheet_2x2_path).convert("RGBA")
    sw, sh = sheet_img.size
    cw, ch = sw // 2, sh // 2
    ix, iy = int(cw * 0.02), int(ch * 0.02)
    quadrants = [
        (0 + ix, 0 + iy, cw - ix, ch - iy),
        (cw + ix, 0 + iy, sw - ix, ch - iy),
        (0 + ix, ch + iy, cw - ix, sh - iy),
        (cw + ix, ch + iy, sw - ix, sh - iy),
    ]
    clean_frames = [
        normalize_cell_frame(despike_magenta_cell(sheet_img.crop(box)), target_size=gif_size)
        for box in quadrants
    ]

    idle_frames = [clean_frames[0], clean_frames[1], clean_frames[0], clean_frames[1]]
    wave_frames = [clean_frames[0], clean_frames[2], clean_frames[3], clean_frames[2]]

    idle_gif_path = output_dir / "blobster-idle.gif"
    wave_gif_path = output_dir / "blobster-wave.gif"
    save_transparent_gif(idle_frames, idle_gif_path, duration_ms=260)
    save_transparent_gif(wave_frames, wave_gif_path, duration_ms=200)

    cutout_path = output_dir / "cutout-256.png"
    clean_frames[0].save(cutout_path, format="PNG", optimize=True)

    # Copy blobster-design.json into output_dir if compiling into a fresh target directory
    dest_design = output_dir / "blobster-design.json"
    if design_json_path.resolve() != dest_design.resolve():
        dest_design.write_text(design_json_path.read_text(encoding="utf-8"), encoding="utf-8")

    qa_res = analyze_pack_qa(output_dir, max_spill_pct=max_spill_pct)
    if qa_out_path is not None:
        qa_res = render_qa_contact_sheet(output_dir, qa_out_path, qa_report=qa_res)

    return {
        "ok": qa_res["ok"],
        "id": design["id"],
        "name": design["name"],
        "svg": str(svg_path),
        "svgBytes": svg_path.stat().st_size,
        "hero512": str(hero_512_path),
        "hero512Bytes": hero_512_path.stat().st_size,
        "idleGif": str(idle_gif_path),
        "idleGifBytes": idle_gif_path.stat().st_size,
        "waveGif": str(wave_gif_path),
        "waveGifBytes": wave_gif_path.stat().st_size,
        "cutout256": str(cutout_path),
        "qa": {
            "ok": qa_res["ok"],
            "maxMagentaSpillPct": qa_res["maxMagentaSpillPct"],
            "maxBorderClipPixels": qa_res["maxBorderClipPixels"],
            "customSvgShapes": qa_res["customSvgShapes"],
            "contactSheet": qa_res.get("contactSheet"),
            "errors": qa_res["errors"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_svg = sub.add_parser("svg", help="Compile & validate an OpenClaw Blobster SVG from design JSON")
    p_svg.add_argument("--design", required=True, type=Path, help="Path to blobster-design.json")
    p_svg.add_argument("--out", required=True, type=Path, help="Output SVG path")

    p_tier1 = sub.add_parser("tier1", help="Compile full Tier 1 Fast Pack (SVG + 512 PNG + transparent GIFs + QA)")
    p_tier1.add_argument("--design", required=True, type=Path, help="Path to blobster-design.json")
    p_tier1.add_argument("--hero", required=True, type=Path, help="Path to 1:1 3D hero source image")
    p_tier1.add_argument("--sheet", required=True, type=Path, help="Path to 2x2 #FF00FF chroma-key sheet")
    p_tier1.add_argument("--out-dir", required=True, type=Path, help="Output avatars/ directory")
    p_tier1.add_argument("--gif-size", type=int, default=256, help="Square GIF pixel dimension (default: 256)")
    p_tier1.add_argument(
        "--qa-out",
        type=Path,
        default=None,
        help="Optional output PNG path for 1280x760 dark/light QA contact sheet (keep outside templates/<id>/).",
    )
    p_tier1.add_argument(
        "--max-spill-pct",
        type=float,
        default=1.5,
        help="Max allowed #FF00FF magenta fringe spill percentage per frame (default: 1.5).",
    )

    p_qa = sub.add_parser("qa", help="Audit an avatars/ pack and optionally emit a dark/light QA contact sheet PNG")
    p_qa.add_argument("--avatars-dir", required=True, type=Path, help="Path to workspace/avatars directory")
    p_qa.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output PNG path for 1280x760 dark/light QA contact sheet (keep outside templates/<id>/).",
    )
    p_qa.add_argument(
        "--max-spill-pct",
        type=float,
        default=1.5,
        help="Max allowed #FF00FF magenta fringe spill percentage per frame (default: 1.5).",
    )

    args = parser.parse_args(argv)
    if args.cmd == "svg":
        if not args.design.is_file():
            print(f"error: design JSON not found: {args.design}", file=sys.stderr)
            return 2
        design = json.loads(args.design.read_text(encoding="utf-8"))
        svg_text = render_blobster_svg(design)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(svg_text, encoding="utf-8")
        print(json.dumps({"ok": True, "svg": str(args.out), "bytes": args.out.stat().st_size}, indent=2))
        return 0

    if args.cmd == "tier1":
        for req_p, label in ((args.design, "design"), (args.hero, "hero"), (args.sheet, "sheet")):
            if not req_p.is_file():
                print(f"error: {label} file not found: {req_p}", file=sys.stderr)
                return 2
        res = compile_tier1_pack(
            design_json_path=args.design,
            hero_source_path=args.hero,
            sheet_2x2_path=args.sheet,
            output_dir=args.out_dir,
            gif_size=args.gif_size,
            qa_out_path=args.qa_out,
            max_spill_pct=args.max_spill_pct,
        )
        print(json.dumps(res, indent=2))
        if not res["ok"]:
            for err in res["qa"]["errors"]:
                print(f"qa error: {err}", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "qa":
        if not args.avatars_dir.is_dir():
            print(f"error: avatars directory not found: {args.avatars_dir}", file=sys.stderr)
            return 2
        qa_res = (
            render_qa_contact_sheet(args.avatars_dir, args.out, qa_report=analyze_pack_qa(args.avatars_dir, args.max_spill_pct))
            if args.out is not None
            else analyze_pack_qa(args.avatars_dir, max_spill_pct=args.max_spill_pct)
        )
        print(json.dumps(qa_res, indent=2))
        if not qa_res["ok"]:
            for err in qa_res["errors"]:
                print(f"qa error: {err}", file=sys.stderr)
            return 1
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
