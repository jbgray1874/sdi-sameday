"""
ga_draw.py - a dimensioned concept GA for the brief, drawn by code (free, instant, and the sizes are exact).

An image model can draw something that *looks* like a SolidWorks GA but writes the numbers
wrong. Here the numbers come straight from the brief: overall H x W x D, plus a sensible
make-up of the unit (plinth, shelves, header) that the AM can see and the designer will
replace with the real design. Front, side and plan views, a small isometric, dimension
lines and an SDI title block - "CONCEPT GA - NOT FOR MANUFACTURE".
"""
import math
import os
import re
from datetime import date

from PIL import Image, ImageDraw, ImageFont

W_PX, H_PX = 2000, 1414            # A-series landscape ratio
INK, MUTE, RED, FILL = (25, 25, 28), (120, 120, 128), (200, 16, 46), (238, 238, 240)


def _font(size, bold=False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"), ("segoeuib.ttf" if bold else "segoeui.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_up(brief, h, w, d):
    """What the unit is made of, from the brief's words. Defaults are typical SDI proportions, labelled as such."""
    text = " ".join(str(brief.get(k) or "") for k in ("unit_type", "materials", "colours_graphics", "narrative", "placement")).lower()
    floor = h >= 1200 or "floor" in text or "fsdu" in text
    header = 0 if re.search(r"no header|without header", text) else (min(350, max(180, round(h * 0.16 / 10) * 10)) if ("header" in text or floor) else 0)
    plinth = (min(120, max(60, round(h * 0.055 / 10) * 10))) if floor else 0
    # "4 shelves" / "five tiers" - but not "No7 shelf" (a product line, not a count)
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    text = re.sub(r"\b(two|three|four|five|six)\s+(shelves|tiers)", lambda x: f"{words[x.group(1)]} {x.group(2)}", text)
    m = re.search(r"(?<![a-z\d])(\d{1,2})\s+(shelves|tiers)\b", text)
    shelves = int(m.group(1)) if m else max(2, min(6, round((h - header - plinth) / 380))) if floor else max(1, round((h - header) / 300))
    return {"floor": floor, "header": header, "plinth": plinth, "shelves": shelves, "side_t": 18 if d < 600 else 25}


class Sheet:
    def __init__(self):
        self.im = Image.new("RGB", (W_PX, H_PX), "white")
        self.d = ImageDraw.Draw(self.im)

    def rect(self, x0, y0, x1, y1, fill=None, w=3, col=INK):
        self.d.rectangle([x0, y0, x1, y1], outline=col, width=w, fill=fill)

    def line(self, pts, w=2, col=INK):
        self.d.line(pts, fill=col, width=w)

    def text(self, xy, s, size=26, col=INK, bold=False, anchor="la"):
        self.d.text(xy, s, fill=col, font=_font(size, bold), anchor=anchor)

    def dim_h(self, x0, x1, y, label, off=40):
        """Horizontal dimension line below/above a view."""
        yy = y + off
        self.line([(x0, y + 8), (x0, yy + 10)], 1, MUTE)
        self.line([(x1, y + 8), (x1, yy + 10)], 1, MUTE)
        self.line([(x0, yy), (x1, yy)], 2, RED)
        for x, s in ((x0, 1), (x1, -1)):
            self.d.polygon([(x, yy), (x + 14 * s, yy - 6), (x + 14 * s, yy + 6)], fill=RED)
        self.text(((x0 + x1) / 2, yy - 8), label, 26, RED, True, "ms")

    def dim_v(self, x, y0, y1, label, off=-40):
        xx = x + off
        self.line([(x - 8 if off < 0 else x + 8, y0), (xx - 10 if off < 0 else xx + 10, y0)], 1, MUTE)
        self.line([(x - 8 if off < 0 else x + 8, y1), (xx - 10 if off < 0 else xx + 10, y1)], 1, MUTE)
        self.line([(xx, y0), (xx, y1)], 2, RED)
        for y, s in ((y0, 1), (y1, -1)):
            self.d.polygon([(xx, y), (xx - 6, y + 14 * s), (xx + 6, y + 14 * s)], fill=RED)
        lab = Image.new("RGBA", (260, 40), (255, 255, 255, 0))
        ImageDraw.Draw(lab).text((130, 20), label, fill=RED, font=_font(26, True), anchor="mm")
        lab = lab.rotate(90, expand=True)
        self.im.paste(lab, (int(xx - 20 - (6 if off < 0 else -6) - 20), int((y0 + y1) / 2 - 130)), lab)


def draw(brief, hwd, out_path, client_name=""):
    h, w, d = hwd
    mk = make_up(brief, h, w, d)
    S = Sheet()
    # drawing area: front (left), side (middle), plan (under front), iso (right)
    area_h = 860
    scale = min(area_h / h, 520 / max(w, 1), 330 / max(d, 1)) * 0.92
    fx, base_y = 170, 140 + area_h                         # front view bottom-left
    sx = fx + w * scale + 200                              # side view left
    H, Wd, D = h * scale, w * scale, d * scale
    t = max(3, mk["side_t"] * scale)

    # --- front elevation
    top = base_y - H
    S.rect(fx, top, fx + Wd, base_y, w=4)
    if mk["plinth"]:
        S.rect(fx, base_y - mk["plinth"] * scale, fx + Wd, base_y, fill=FILL, w=3)
    if mk["header"]:
        S.rect(fx, top, fx + Wd, top + mk["header"] * scale, fill=(250, 232, 236), w=3)
        S.text((fx + Wd / 2, top + mk["header"] * scale / 2), (client_name or brief.get("client") or "HEADER").upper()[:22],
               max(18, int(min(46, mk["header"] * scale * 0.42))), RED, True, "mm")
    S.rect(fx, top, fx + t, base_y, fill=FILL, w=2)
    S.rect(fx + Wd - t, top, fx + Wd, base_y, fill=FILL, w=2)
    lo = base_y - mk["plinth"] * scale
    hi = top + mk["header"] * scale
    for i in range(1, mk["shelves"] + 1):           # shelves evenly spaced in the open bay
        y = lo - (lo - hi) * (i - 1) / mk["shelves"] - 2
        S.rect(fx + t, y - 18 * scale - 3, fx + Wd - t, y, fill=(214, 186, 150) if "oak" in str(brief.get("materials", "")).lower() else FILL, w=2)
    S.text((fx, top - 60), "FRONT ELEVATION", 28, INK, True)
    S.dim_h(fx, fx + Wd, base_y, f"{w:.0f}")
    S.dim_v(fx, top, base_y, f"{h:.0f}", off=-55)
    if mk["header"]:
        S.dim_v(fx + Wd, top, top + mk["header"] * scale, f"{mk['header']}", off=50)

    # --- side elevation
    S.rect(sx, top, sx + D, base_y, w=4)
    if mk["plinth"]:
        S.rect(sx, base_y - mk["plinth"] * scale, sx + D, base_y, fill=FILL, w=3)
    if mk["header"]:
        S.rect(sx, top, sx + D * 0.35, top + mk["header"] * scale, fill=(250, 232, 236), w=3)
    for i in range(1, mk["shelves"] + 1):
        y = lo - (lo - hi) * (i - 1) / mk["shelves"] - 2
        S.line([(sx, y), (sx + D, y)], 4)
    S.text((sx, top - 60), "SIDE ELEVATION", 28, INK, True)
    S.dim_h(sx, sx + D, base_y, f"{d:.0f}")

    # --- plan (under the title block area, right of side)
    px, py = sx + D + 160, base_y - D
    S.rect(px, py, px + Wd, py + D, w=4)
    S.rect(px, py, px + t, py + D, fill=FILL, w=2)
    S.rect(px + Wd - t, py, px + Wd, py + D, fill=FILL, w=2)
    S.text((px, py - 60), "PLAN", 28, INK, True)
    S.dim_h(px, px + Wd, py + D, f"{w:.0f}")

    # --- isometric (top right): fit the projected box into its own area, whatever the proportions
    c, s_ = math.cos(math.radians(30)), math.sin(math.radians(30))

    def raw(x, y, z):            # x across the front, y back into the unit, z up; seen from front-left, above
        return ((x - y) * c, -(x + y) * s_ - z)
    corners = [raw(x, y, z) for x in (0, w) for y in (0, d) for z in (0, h)]
    minx, maxx = min(p[0] for p in corners), max(p[0] for p in corners)
    miny, maxy = min(p[1] for p in corners), max(p[1] for p in corners)
    ax0, ay0, ax1, ay1 = px + Wd + 140, 150, W_PX - 80, 700           # area to the right of the plan, top
    if ax1 - ax0 < 300:
        ax0, ax1 = px, W_PX - 80
    iso_s = min((ax1 - ax0) / (maxx - minx), (ay1 - ay0) / (maxy - miny)) * 0.9

    def P(x, y, z):
        rx, ry = raw(x, y, z)
        return (ax0 + (rx - minx) * iso_s, ay0 + (ry - miny) * iso_s)
    # an open-fronted unit, painted back to front: back panel, far (right) side, shelves, plinth, near (left) side, top, header
    def face(pts, col, out=INK, wd=2):
        S.d.polygon([P(*p) for p in pts], fill=col, outline=out, width=wd)
    shelf_col = (214, 186, 150) if "oak" in str(brief.get("materials", "")).lower() else (205, 205, 211)
    face(((0, d, 0), (w, d, 0), (w, d, h), (0, d, h)), (236, 236, 240))                     # back panel
    face(((w, 0, 0), (w, d, 0), (w, d, h), (w, 0, h)), (222, 222, 227))                     # far side
    pl, hd = mk["plinth"], mk["header"]
    for i in range(1, mk["shelves"] + 1):
        z = pl + (h - hd - pl) * (i - 1) / mk["shelves"]
        face(((0, 0, z), (w, 0, z), (w, d, z), (0, d, z)), shelf_col)
        face(((0, 0, z - 18), (w, 0, z - 18), (w, 0, z), (0, 0, z)), shelf_col)              # shelf front edge
    if pl:
        face(((0, 0, 0), (w, 0, 0), (w, 0, pl), (0, 0, pl)), (215, 215, 220))                # plinth front
    face(((0, 0, 0), (0, d, 0), (0, d, h), (0, 0, h)), (246, 246, 248), INK, 3)               # near side
    face(((0, 0, h), (w, 0, h), (w, d, h), (0, d, h)), (240, 240, 244), INK, 3)               # top
    if hd:
        face(((0, 0, h - hd), (w, 0, h - hd), (w, 0, h), (0, 0, h)), (250, 232, 236), RED, 3) # header
        cx, cy = P(w / 2, 0, h - hd / 2)
        S.text((cx, cy), (client_name or brief.get("client") or "")[:14].upper(), max(14, int(hd * iso_s * 0.35)), RED, True, "mm")
    tx = min(P(x, y, h)[0] for x in (0, w) for y in (0, d))
    ty = min(P(x, y, h)[1] for x in (0, w) for y in (0, d))
    S.text((tx, ty - 50), "ISOMETRIC", 28, INK, True)

    # --- title block
    tb_y = H_PX - 170
    S.rect(30, 30, W_PX - 30, H_PX - 30, w=3)
    S.rect(30, tb_y, W_PX - 30, H_PX - 30, w=3)
    S.text((60, tb_y + 30), "SDI DISPLAYS", 40, RED, True)
    S.text((60, tb_y + 82), "CONCEPT GA - NOT FOR MANUFACTURE", 26, INK, True)
    info = [("CLIENT", brief.get("client") or "-"), ("UNIT", (brief.get("unit_type") or "-")[:40]),
            ("OVERALL", f"{h:.0f} H x {w:.0f} W x {d:.0f} D mm"), ("DATE", f"{date.today():%d/%m/%Y}")]
    x = 640
    for k, v in info:
        S.text((x, tb_y + 30), k, 20, MUTE, True)
        S.text((x, tb_y + 62), str(v), 26, INK)
        x += 340
    S.text((640, tb_y + 108), "Materials: " + str(brief.get("materials") or "TBC")[:90], 22, MUTE)
    note = (f"Make-up assumed for the concept: {mk['shelves']} shelves" + (f", {mk['header']} mm header" if mk["header"] else "")
            + (f", {mk['plinth']} mm plinth" if mk["plinth"] else "") + ". All dimensions in mm. Overall sizes from the brief; "
            "internal layout is indicative until designed.")
    S.text((60, tb_y - 34), note, 21, MUTE)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    S.im.save(out_path, "PNG")
    return out_path, mk


if __name__ == "__main__":
    b = {"client": "Boots", "unit_type": "No7 shelf unit", "materials": "white gloss with oak shelves",
         "colours_graphics": "navy No7 header", "placement": "front of store"}
    print(draw(b, (1800, 600, 400), os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "ga_test.png"), "No7"))
