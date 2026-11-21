"""model3d.py - the unit as a simple 3D model the AM can spin on screen (21 Nov 2026).

James: "3 d visuals that can rotate". Built from the brief alone - its exact height x width x depth and the same make-up
as the concept GA (ga_draw.make_up: plinth, sides, back, shelves, header) - so the sizes are right and it costs nothing.
It is a clean massing model in the brief's colours, not a photo: the renders show the look, this shows the shape and
proportions from every side. The page draws it itself (no library to download).
"""
import re

import ga_draw
import pdf_pack


def _hex(v, default):
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else default


def body_colour(brief):
    """The unit's main finish from the materials named: black, white, oak/wood, metal, acrylic."""
    t = " ".join(str(brief.get(k) or "") for k in ("materials", "colours_graphics")).lower()
    for pat, col in ((r"\bblack\b|anthracite|charcoal", "#2B2B2B"), (r"\boak\b|wood|walnut|timber|joinery|ply", "#C49A6C"),
                     (r"\bgrey\b|\bgray\b|metal|steel|chrome|aluminium", "#A9ADB2"), (r"\bwhite\b|9003|9010|9016", "#F4F4F2")):
        if re.search(pat, t):
            return col
    return "#F1F0EC"


def model(brief, accent="#F6D946"):
    """{'size': [h, w, d], 'parts': [{'name', 'x', 'y', 'z', 'w', 'h', 'd', 'colour'}]} in mm, or None without a size.
    x across the width (0 = left), y up from the floor, z from the back (0) to the front (d)."""
    hwd = pdf_pack.parse_size(str(brief.get("size") or ""))
    if not hwd or len(hwd) < 3 or not all(hwd[:3]):
        return None
    h, w, d = (float(v) for v in hwd[:3])
    m = ga_draw.make_up(brief, h, w, d)
    t, sh = float(m["side_t"]), 18.0
    body, acc = body_colour(brief), _hex(accent, "#F6D946")
    parts = []

    def box(name, x, y, z, bw, bh, bd, colour):
        if bw > 0 and bh > 0 and bd > 0:
            parts.append({"name": name, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1), "w": round(bw, 1),
                          "h": round(bh, 1), "d": round(bd, 1), "colour": colour})

    base = float(m["plinth"])
    top = h - float(m["header"])
    if base:
        box("plinth", 0, 0, 0, w, base, d, "#3A3A38")
    box("left side", 0, base, 0, t, top - base, d, body)
    box("right side", w - t, base, 0, t, top - base, d, body)
    box("back", t, base, 0, w - 2 * t, top - base, sh, body)
    n = max(1, int(m["shelves"]))
    gap = (top - base) / (n + (0 if m["floor"] else 0.0))
    for i in range(n):
        y = base + (i * gap if m["floor"] else i * gap)
        box(f"shelf {i + 1}", t, y, sh, w - 2 * t, sh, d - sh, body)
        box(f"shelf edge {i + 1}", t, y + sh, d - 4, w - 2 * t, 30, 4, acc)
    box("top", 0, top - sh, 0, w, sh, d, body)
    if m["header"]:
        box("header", 0, top, max(0.0, d - 60), w, float(m["header"]), 25, acc)
    return {"size": [h, w, d], "parts": parts, "floor": bool(m["floor"])}
