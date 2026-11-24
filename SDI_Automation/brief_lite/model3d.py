"""model3d.py - the unit as a simple 3D model the AM can spin on screen (21 Nov 2026).

James: "3 d visuals that can rotate". Built from the brief's exact height x width x depth and the make-up of the GA on
screen (24 Nov 2026, Matt: the 3D must match the GA): when the GA was drawn by the image model, its shelves, header and
plinth are read off that drawing (lite_app.ga_make_up); otherwise the code GA's own make-up (ga_draw.make_up). It is laid
out exactly as the GA draws it: sides full height, plinth at the foot, header panel across the top of the front, shelves
where the GA puts them. A clean massing model in the brief's colours, not a photo: the renders show the look, this shows
the shape and proportions from every side. The page draws it itself (no library to download).
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


def shelf_heights(m, h):
    """Where each shelf's top sits, mm from the floor - the GA's own when it was read, else spaced as ga_draw spaces
    them (the first on the base of the open bay, the rest evenly up to the header)."""
    if m.get("shelf_heights"):
        return [float(v) for v in m["shelf_heights"]]
    n = max(1, int(m["shelves"]))
    lo, hi = float(m["plinth"]), h - float(m["header"])
    return [lo + (hi - lo) * i / n + 18.0 for i in range(n)]


def model(brief, accent="#F6D946", make_up=None):
    """{'size': [h, w, d], 'parts': [{'name', 'x', 'y', 'z', 'w', 'h', 'd', 'colour'}]} in mm, or None without a size.
    x across the width (0 = left), y up from the floor, z from the back (0) to the front (d). make_up: the GA's
    (lite_app.ga_make_up / ga_draw.make_up); without it the brief's words decide, as the code GA does."""
    hwd = pdf_pack.parse_size(str(brief.get("size") or ""))
    if not hwd or len(hwd) < 3 or not all(hwd[:3]):
        return None
    h, w, d = (float(v) for v in hwd[:3])
    m = dict(make_up or ga_draw.make_up(brief, h, w, d))
    t, sh = float(m.get("side_t") or 18), 18.0
    body, acc = body_colour(brief), _hex(accent, "#F6D946")
    parts = []

    def box(name, x, y, z, bw, bh, bd, colour):
        if bw > 0 and bh > 0 and bd > 0:
            parts.append({"name": name, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1), "w": round(bw, 1),
                          "h": round(bh, 1), "d": round(bd, 1), "colour": colour})

    base, hd = float(m.get("plinth") or 0), float(m.get("header") or 0)
    inner = w - 2 * t
    if base:                                                       # plinth between the sides, as the GA's front view
        box("plinth", t, 0, sh, inner, base, d - sh, "#3A3A38")
    box("left side", 0, 0, 0, t, h, d, body)                       # sides the full height, floor to top
    box("right side", w - t, 0, 0, t, h, d, body)
    box("back", t, base, 0, inner, h - base, sh, body)
    box("top", t, h - sh, sh, inner, sh, d - sh, body)
    for i, y in enumerate(shelf_heights(m, h)):                    # shelf top at y (the lowest sits on the base)
        y = min(y, h - hd - sh)
        box(f"shelf {i + 1}", t, max(base, y - sh), sh, inner, sh, d - sh, body)
    if hd:                                                         # the header panel across the front, top of the unit
        box("header", t, h - hd, max(sh, d - 25), inner, hd, min(25.0, d - sh), acc)
    return {"size": [h, w, d], "parts": parts, "floor": bool(m.get("floor")),
            "from_ga": bool(m.get("from_ga")), "shelves": len(shelf_heights(m, h)),
            "header": int(hd), "plinth": int(base)}


def draw_order(parts, view):
    """Indices of the parts, farthest first, for painting them seen from direction `view` (x, y, z towards the viewer).
    Two boxes that don't touch have a gap between them along some axis; the one on the far side of that gap can never
    hide the near one, so it is painted first - sorting by centre alone gets tall sides and shelves wrong."""
    n = len(parts)
    lo = [[float(p[k]) for k in ("x", "y", "z")] for p in parts]
    hi = [[float(p["x"]) + float(p["w"]), float(p["y"]) + float(p["h"]), float(p["z"]) + float(p["d"])] for p in parts]
    mid = [sum(((lo[i][k] + hi[i][k]) / 2) * view[k] for k in range(3)) for i in range(n)]
    before = [set() for _ in range(n)]          # before[j]: parts that must be painted before j
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(3):
                if abs(view[k]) < 1e-6:
                    continue
                if hi[i][k] <= lo[j][k] + 0.5:      # i on the low side of the gap
                    far, near = (i, j) if view[k] > 0 else (j, i)
                elif hi[j][k] <= lo[i][k] + 0.5:
                    far, near = (j, i) if view[k] > 0 else (i, j)
                else:
                    continue
                before[near].add(far)
                break
    out, left = [], set(range(n))
    while left:
        ready = [i for i in left if not (before[i] & left)] or list(left)     # a loop (rare): fall back to the centre
        i = min(ready, key=lambda q: mid[q])
        out.append(i)
        left.discard(i)
    return out
