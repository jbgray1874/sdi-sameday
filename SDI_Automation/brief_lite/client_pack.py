"""client_pack.py - the client concept pack: a few landscape pages in we.are.sdi's look (21 Nov 2026).

James: "It is for clients so it has to be brilliant ... all the details captured from the account person / designer fed
into the pack ... a few pages ... the estimate on there also, with as much detail as we can provide, depending on which
of the three was selected."

    1  Cover            the unit in its store (or the render) full-page, the dark band: project, client, contact,
                        SDI contact, reference, size - in the quote portal's look (badge, lockup, yellow rule)
    2  The concept      the render large, and the design story (the idea, how it's built, the products, the header, why)
    3  How we designed it   the portal's dark panel: what you told us, what we produced, four steps
    4  Specification    everything the AM and designer captured that a client should see, grouped
    5  Every angle      the views of this design; without them, the unit's own 3D model from three sides
    6  Sizes            the concept GA, a page to itself so every dimension can be read
    7  Indicative budget  only when SDI has set its markup (client_pack_markup_pct): SDI's estimate is a COST to make,
                       before margin, so the client sees cost + markup, labelled indicative, subject to quotation
    8  Next steps       what happens after approval, who to talk to, and a sign-off box

Never on it: SDI's cost, margin, other clients' jobs, internal notes, budgets for design time, assumptions.
"""
import math
import os
import re
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, KeepInFrame, Paragraph, Table, TableStyle

W, H = landscape(A4)
YELLOW = colors.HexColor("#F5D947")          # the portal's SDI yellow - on dark, or as a fill
GOLD = colors.HexColor("#B8860B")            # the accent on white (yellow on white is barely a colour)
BLACK = colors.HexColor("#1F2321")
DARK = colors.HexColor("#282928")            # the portal's dark band
INK = colors.HexColor("#2B2E2C")
MUTE = colors.HexColor("#6B6F6C")
STONE = colors.HexColor("#E1E1D5")
SOFT = colors.HexColor("#F5F5F1")
LINE = colors.HexColor("#E6E7E4")
M = 16 * mm                                   # page margin

# ── type: Segoe UI on the server (Windows), Liberation Sans elsewhere, Helvetica if neither ──────────────────────────
_FONT_SETS = [
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
REG, SEMI, BOLD = "Helvetica", "Helvetica-Bold", "Helvetica-Bold"
for _r, _s, _b in _FONT_SETS:
    if all(os.path.isfile(p) for p in (_r, _s, _b)):
        try:
            pdfmetrics.registerFont(TTFont("SDI", _r))
            pdfmetrics.registerFont(TTFont("SDI-Semi", _s))
            pdfmetrics.registerFont(TTFont("SDI-Bold", _b))
            REG, SEMI, BOLD = "SDI", "SDI-Semi", "SDI-Bold"
            break
        except Exception:                                   # noqa: BLE001
            continue


def _style(name, font, size, lead=None, colour=INK, **kw):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=lead or size * 1.3, textColor=colour,
                          alignment=TA_LEFT, **kw)


EYEBROW = _style("eyebrow", SEMI, 7.5, 10, GOLD, spaceAfter=1)
EYEBROW_D = _style("eyebrow_d", SEMI, 8, 10, YELLOW)
TITLE = _style("title", BOLD, 32, 36, colors.white)
SUB = _style("sub", REG, 14, 18, colors.HexColor("#D9DAD6"))
H1 = _style("h1", BOLD, 22, 26, BLACK)
H1_D = _style("h1_d", BOLD, 21, 25, colors.white)
META_D = _style("meta_d", REG, 9, 12, colors.HexColor("#C9CAC6"))
H3 = _style("h3", SEMI, 9.5, 12, BLACK, spaceBefore=8, spaceAfter=2)
BODY = _style("body", REG, 9.5, 13.4, INK)
BODY_D = _style("body_d", REG, 8.6, 12, colors.HexColor("#D9DAD6"))
TILE_H = _style("tile_h", BOLD, 10.5, 13, colors.white)
BIG = _style("big", REG, 12, 16.5, INK)
SMALL = _style("small", REG, 7.5, 10, MUTE)
CELL_K = _style("cellk", SEMI, 8, 10.5, MUTE)
CELL_V = _style("cellv", REG, 9, 12, INK)

FOOTER = "we.are.sdi  ·  Design-led manufacturer  ·  Loughborough, UK  ·  wearesdi.com  ·  hello@wearesdi.com  ·  +44 (0) 116 274 7040"


def _esc(t):
    return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _flow(c, items, x, y_top, w, h):
    f = Frame(x, y_top - h, w, h, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, showBoundary=0)
    f.addFromList([KeepInFrame(w, h, items, mode="shrink")], c)


def _p(text, style):
    return Paragraph(_esc(text).replace("\n", "<br/>"), style)


# ── what may be shown to a client ──────────────────────────────────────────────────────────────────────────────────
UNKNOWN = re.compile(r"^\s*(unknown|not known|n/?a|none|tbc|not given.*|needs confirming|-)\s*$", re.I)


def clean(value, session=None, keep_numbers=False):
    """Client-safe text: no money, no other clients' job numbers, no internal '(assumed ...)' notes."""
    t = " ".join(str(value or "").split())
    if not t or UNKNOWN.match(t):
        return ""
    t = re.sub(r"\s*\((assumed|as assumed|internal)[^)]*\)", "", t, flags=re.I)
    if not keep_numbers:
        for ref in (session or {}).get("refs") or []:
            job = str(ref.get("job_no") or "")
            if job:
                t = re.sub(r"(?<!\w)" + re.escape(job) + r"(?!\w)", "", t)
        t = re.sub(r"(?:GBP|£|USD|\$|EUR|€)\s*[\d,.]+\s*[kK]?", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -;,|")[:420]


SPEC = [
    ("The project", [("project_name", "Project"), ("client", "Client"), ("retailer", "Retailer"),
                     ("customer_name", "Your contact"), ("account_manager", "SDI account manager"),
                     ("job_number", "Our reference"), ("instore_date", "In store by"), ("shelf_life", "Life in store"),
                     ("repeat", "Repeat orders")]),
    ("The unit", [("unit_type", "Unit"), ("size", "Size (H x W x D)"), ("volume_qty", "Quantity"),
                  ("placement", "Where in store"), ("fixing", "Fixing"), ("fixture_system", "Retailer fixture"),
                  ("stability", "Stability"), ("security", "Security"), ("power", "Power"), ("food_safe", "Food safe")]),
    ("Build and finish", [("materials", "Materials"), ("finish_instructions", "Finish"),
                          ("colours_graphics", "Colours and graphics"), ("lighting", "Lighting"),
                          ("assembled", "Supplied"), ("brand_assets", "Brand assets")]),
    ("Products", [("products_held", "Products"), ("hero_products", "Hero products"), ("shelf_load", "Shelf load")]),
    ("Delivery", [("warehousing", "Storage and delivery"), ("delivery_packing", "Packing"),
                  ("delivery_restrictions", "Delivery notes"), ("installation", "Installation"),
                  ("leadtime", "Lead time")]),
    ("Notes", [("references", "Your references"), ("other_notes", "Other points")]),
]
NUMBERS_OK = {"job_number", "size", "volume_qty", "instore_date", "shelf_load", "leadtime"}


def _tidy(key, v):
    """'yes' / 'no' read as a sentence; every value starts with a capital."""
    if re.match(r"^\s*(yes|y|yeah|required|needed)\b\.?\s*$", v, re.I):
        v = {"installation": "Yes, by SDI", "food_safe": "Yes"}.get(key, "Yes")
    elif re.match(r"^\s*(no|n|nope|not needed|none)\b\.?\s*$", v, re.I):
        v = {"installation": "No - installed by others", "lighting": "None"}.get(key, "No")
    return v[:1].upper() + v[1:]


def spec_groups(brief, session=None):
    """[(group, [(label, text)])] - only what's known, client-safe."""
    out = []
    for group, keys in SPEC:
        vals = [(k, label, clean(brief.get(k), session, keep_numbers=k in NUMBERS_OK)) for k, label in keys]
        rows = [(label, _tidy(k, v)) for k, label, v in vals if v]
        if rows:
            out.append((group, rows))
    return out


# ── drawing helpers ────────────────────────────────────────────────────────────────────────────────────────────────
def _img_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:                                        # noqa: BLE001
        return None


def _svg(c, path, x, y, w, h, align):
    """An SVG logo (the quote portal keeps some only as SVG), drawn as vectors - needs svglib."""
    try:
        from reportlab.graphics import renderPDF
        import tempfile
        from svglib.svglib import svg2rlg
        # a logo saved from a web page carries CSS sizes on its <svg> ("width:auto") that svglib can't read: the
        # root's own sizes are taken from its viewBox instead
        txt = open(path, encoding="utf-8", errors="ignore").read()
        m = re.search(r"<svg\b[^>]*>", txt)
        if m:
            root = re.sub(r'\s(width|height|style)="[^"]*"', "", m.group(0))
            vb = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', root)
            if vb:
                root = root[:-1].rstrip("/ ") + f' width="{vb.group(1)}" height="{vb.group(2)}">'
            txt = txt[:m.start()] + root + txt[m.end():]
        with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8") as fh:
            fh.write(txt)
        try:
            d = svg2rlg(fh.name)
        finally:
            os.unlink(fh.name)
        if not d or not d.width or not d.height:
            return False
        s_ = min(w / d.width, h / d.height)
        d.width, d.height = d.width * s_, d.height * s_
        d.scale(s_, s_)
        ix = x + (w - d.width) if align == "right" else x if align == "left" else x + (w - d.width) / 2
        renderPDF.draw(d, c, ix, y + (h - d.height) / 2)
        return True
    except Exception:                                        # noqa: BLE001
        return False


def image(c, path, x, y, w, h, cover=False, pad=0, align="centre"):
    """The picture in the box: whole (contain) or filling it, cropped (cover); a logo can sit to the right."""
    if not path or not os.path.isfile(path):
        return False
    if path.lower().endswith(".svg"):
        return _svg(c, path, x + pad, y + pad, w - 2 * pad, h - 2 * pad, align)
    sz = _img_size(path)
    if not sz:
        return False
    iw, ih = sz
    x, y, w, h = x + pad, y + pad, w - 2 * pad, h - 2 * pad
    s = (max if cover else min)(w / iw, h / ih)
    dw, dh = iw * s, ih * s
    c.saveState()
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)
    try:
        ix = x + (w - dw) if align == "right" else x if align == "left" else x + (w - dw) / 2
        c.drawImage(path, ix, y + (h - dh) / 2, width=dw, height=dh, mask="auto")
    except Exception:                                        # noqa: BLE001
        c.restoreState()
        return False
    c.restoreState()
    return True


def card(c, x, y, w, h, fill=SOFT):
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=0)


def eyebrow(c, x, y, text, colour=GOLD, size=7.5):
    c.setFont(SEMI, size)
    c.setFillColor(colour)
    c.drawString(x, y, " ".join(text.upper()))      # tracked out, like the portal's eyebrows


def chrome(c, n, total, client, badge, client_logo):
    """Every page but the cover, as the quote portal: SDI's badge, the lockup between, the client's logo, the yellow
    rule; and the footer with the page's place in the pack."""
    top = H - 9 * mm
    if badge and os.path.isfile(badge):
        c.drawImage(badge, M, top - 14 * mm, width=14 * mm, height=14 * mm, mask="auto")
    c.setFont(REG, 6.8)
    c.setFillColor(MUTE)
    c.drawCentredString(W / 2, top - 5 * mm, " ".join("SDI INTELLIGENCE"))
    c.setFont(SEMI, 11)
    c.setFillColor(DARK)
    lock = f"Concept presentation · {client}"
    c.drawCentredString(W / 2, top - 10.5 * mm, lock)
    if client_logo and os.path.isfile(client_logo):
        image(c, client_logo, W - M - 40 * mm, top - 15 * mm, 40 * mm, 16 * mm, align="right")
    c.setFillColor(YELLOW)
    c.rect(0, top - 19 * mm, W, 1.4 * mm, fill=1, stroke=0)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(M, 12 * mm, W - M, 12 * mm)
    c.setFont(SEMI, 7)
    c.setFillColor(DARK)
    c.drawString(M, 7.5 * mm, "we.are.sdi")
    c.setFont(REG, 7)
    c.setFillColor(MUTE)
    c.drawString(M + c.stringWidth("we.are.sdi  ", SEMI, 7), 7.5 * mm, FOOTER.split("  ·  ", 1)[1])
    c.drawRightString(W - M, 7.5 * mm, f"{n:02d} / {total:02d}")


TOP = H - 37 * mm                                  # where a page's own content starts, under the header


def heading(c, label, text, sub=""):
    eyebrow(c, M, TOP, label)
    _flow(c, [_p(text, H1)] + ([_p(sub, BODY)] if sub else []), M, TOP - 3 * mm, W - 2 * M, 18 * mm)


def dark_band(c, y, h, label, text, meta=""):
    """The portal's dark title band, full width, with a yellow eyebrow."""
    c.setFillColor(DARK)
    c.rect(0, y, W, h, fill=1, stroke=0)
    eyebrow(c, M, y + h - 8 * mm, label, YELLOW, 8)
    _flow(c, [_p(text, H1_D)] + ([_p(meta, META_D)] if meta else []), M, y + h - 10 * mm, W - 2 * M, h - 12 * mm)


# ── the unit's 3D model, drawn from three sides (when there are no rendered views) ────────────────────────────────
def model_pictures(model, out_dir, stem):
    """Three PNGs of the model3d boxes, shaded, from front-left, front-right and straight on. [] without PIL."""
    try:
        from PIL import Image, ImageDraw
    except Exception:                                        # noqa: BLE001
        return []
    parts = (model or {}).get("parts") or []
    if not parts:
        return []
    out = []
    for name, yaw, pitch in (("left", -35, 22), ("right", 35, 22), ("front", 0, 8)):
        a, e = math.radians(yaw), math.radians(pitch)
        hgt, wid, dep = model["size"]

        def proj(px, py, pz):
            x0, z0 = px - wid / 2, pz - dep / 2
            xr = x0 * math.cos(a) + z0 * math.sin(a)
            zr = -x0 * math.sin(a) + z0 * math.cos(a)
            yr = py * math.cos(e) - zr * math.sin(e)
            depth = zr * math.cos(e) + py * math.sin(e)
            return xr, -yr, depth
        import model3d
        rank = {i: r for r, i in enumerate(model3d.draw_order(parts, (-math.sin(a) * math.cos(e), math.sin(e),
                                                                     math.cos(a) * math.cos(e))))}
        faces = []
        for pi, p in enumerate(parts):
            x, y, z, w_, h_, d_ = (float(p[k]) for k in ("x", "y", "z", "w", "h", "d"))
            v = [(x + dx * w_, y + dy * h_, z + dz * d_) for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
            col = tuple(int(p["colour"][i:i + 2], 16) for i in (1, 3, 5))
            for idx, shade in (((1, 3, 7, 5), 1.0), ((0, 2, 6, 4), 0.62), ((4, 5, 7, 6), 0.82), ((0, 1, 3, 2), 0.82),
                               ((2, 3, 7, 6), 1.08), ((0, 1, 5, 4), 0.5)):
                pts = [proj(*v[i]) for i in idx]
                faces.append(((rank[pi], sum(q[2] for q in pts) / 4), [(q[0], q[1]) for q in pts],
                              tuple(max(0, min(255, int(ch * shade))) for ch in col)))
        xs = [q[0] for f in faces for q in f[1]]
        ys = [q[1] for f in faces for q in f[1]]
        size, padpx = 1200, 90
        sc = (size - 2 * padpx) / max(max(xs) - min(xs), max(ys) - min(ys), 1)
        im = Image.new("RGB", (size, size), (244, 243, 238))
        dr = ImageDraw.Draw(im)
        ox = (size - (max(xs) - min(xs)) * sc) / 2 - min(xs) * sc
        oy = (size - (max(ys) - min(ys)) * sc) / 2 - min(ys) * sc
        base_y = oy + max(ys) * sc
        dr.ellipse((size * 0.18, base_y - 16, size * 0.82, base_y + 24), fill=(226, 224, 216))      # its shadow
        for _d, pts, col in sorted(faces, key=lambda f: f[0]):          # far parts first (model3d.draw_order)
            dr.polygon([(ox + px * sc, oy + py * sc) for px, py in pts], fill=col, outline=(60, 60, 58))
        path = os.path.join(out_dir, f"{stem}_model_{name}.png")
        im.save(path)
        out.append((path, {"left": "From the front left", "right": "From the front right", "front": "Straight on"}[name]))
    return out


# ── the budget, from SDI's estimate plus SDI's markup ─────────────────────────────────────────────────────────────
BASIS = {
    "lite": "Priced by SDI's estimating system part by part, from this concept and brief.",
    "ai": "Costed line by line - materials, manufacture, finish and packing - from this concept and brief, and checked "
          "against comparable SDI projects.",
    "quick": "Based on comparable SDI projects, adjusted for this design.",
    "agreed": "Costed line by line - materials, manufacture, finish and packing - from this concept and brief, and "
              "weighed against what comparable SDI projects cost.",
}


def budget(est, markup_pct):
    """SDI's estimate (cost per unit at each quantity) -> the client's indicative price, rounded. None without both."""
    if not est or markup_pct is None or not est.get("prices"):
        return None
    k = 1 + float(markup_pct) / 100.0
    import agreed
    rnd = agreed.client_price            # 24 Nov 2026: rounded to what an estimate from a concept can honestly claim
    rows = [{"qty": int(p["qty"]), "unit": rnd(float(p["unit_gbp"]) * k)} for p in est["prices"] if p.get("unit_gbp")]
    rows = sorted({r["qty"]: r for r in rows}.values(), key=lambda r: r["qty"])
    for r in rows:
        r["total"] = r["unit"] * r["qty"]
    parts = []
    split = est.get("split") or {}
    names = {"materials": "Materials and components", "labour": "Manufacture and assembly", "bought-in": "Bought-in parts",
             "finish": "Finishing", "packing": "Packing"}
    tot = sum(split.values()) or 0
    if tot:
        parts = [(names.get(g, g.title()), round(100 * v / tot)) for g, v in split.items() if v]
    setup = est.get("setup_total")
    return {"rows": rows, "parts": parts, "setup": rnd(float(setup) * k) if setup else None,
            "basis": BASIS.get(est.get("kind"), BASIS["quick"]), "kind": est.get("kind")}


# ── the pack ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _yes(b, k):
    return bool(re.match(r"\s*(yes|y|needed|required|true)", str(b.get(k) or ""), re.I))


def build(path, session, render, ga=None, views=None, model=None, story=None, est=None, markup_pct=None,
          client_logo=None, sdi_logo=None, today=None, badge=None):
    """Write the pack to `path` -> (path, pages). render/ga: image paths; views: [(path, caption)] - one captioned
    'In store' becomes the cover; story: the design director's direction for this option ({name, idea, build, products,
    header, why}); est: the estimate chosen for this option (budget() turns it into the client's indicative price)."""
    today = today or date.today()
    badge = badge or os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand", "wearesdi_badge.png")
    b = session.get("brief") or {}
    client = clean(b.get("client")) or "Your concept"
    unit = clean(b.get("unit_type")) or "Display concept"
    project = clean(b.get("project_name"), session, keep_numbers=True)
    contact = clean(b.get("customer_name"), session)
    am = clean(b.get("account_manager"), session)
    ref = clean(b.get("job_number"), session, True)
    size = clean(b.get("size"), session, True)
    qty = clean(b.get("volume_qty"), session, True)
    st = story or {}
    views = [(p, cap) for p, cap in (views or []) if p and os.path.isfile(p)]
    instore = next((p for p, cap in views if re.search(r"store", str(cap), re.I)), None)
    hero = instore or render
    angles = views[:4]
    if len(angles) < 2 and model:
        angles = model_pictures(model, os.path.dirname(path), os.path.splitext(os.path.basename(path))[0])
    groups = spec_groups(b, session)
    bud = budget(est, markup_pct)
    meta = "  ·  ".join(x for x in (f"{today:%d %B %Y}", f"for {contact}" if contact else "",
                                    f"ref {ref}" if ref else "", size) if x)

    pages = []

    def cover(c, n, total):
        image(c, hero, 0, 0, W, H, cover=True)
        c.setFillColor(DARK)
        c.rect(0, 0, W, 58 * mm, fill=1, stroke=0)
        c.setFillColor(YELLOW)
        c.rect(0, 58 * mm, W, 1.6 * mm, fill=1, stroke=0)
        eyebrow(c, M, 47 * mm, f"Concept presentation  ·  {today:%B %Y}", YELLOW, 8.5)
        _flow(c, [_p(project or unit, TITLE), _p(f"{unit} for {client}" if project else f"for {client}", SUB)],
              M, 43 * mm, W * 0.62, 30 * mm)
        rows = [(k, v) for k, v in (("Prepared for", contact), ("Your SDI contact", am), ("Our reference", ref),
                                    ("Size", size), ("Quantity", qty)) if v]
        yy = 47 * mm
        for k, v in rows[:4]:
            c.setFont(REG, 7.5)
            c.setFillColor(colors.HexColor("#A9AAA6"))
            c.drawString(W * 0.68, yy, k.upper())
            c.setFont(SEMI, 10)
            c.setFillColor(colors.white)
            c.drawString(W * 0.68, yy - 4.6 * mm, v[:44])
            yy -= 10.5 * mm
        if badge and os.path.isfile(badge):
            c.drawImage(badge, M, H - M - 24 * mm, width=24 * mm, height=24 * mm, mask="auto")
        if client_logo and os.path.isfile(client_logo):
            card(c, W - M - 50 * mm, H - M - 22 * mm, 50 * mm, 22 * mm, colors.white)
            image(c, client_logo, W - M - 50 * mm, H - M - 22 * mm, 50 * mm, 22 * mm, pad=3.5 * mm)
    pages.append(cover)

    def concept(c, n, total):
        chrome(c, n, total, client, badge, client_logo)
        band_h = 30 * mm
        dark_band(c, H - 28 * mm - band_h, band_h, f"{client}  ·  {unit}  ·  the concept",
                  st.get("name") or project or unit, meta)
        y0 = 18 * mm
        hgt = H - 28 * mm - band_h - 6 * mm - y0
        lw = (W - 2 * M) * 0.58
        card(c, M, y0, lw, hgt)
        image(c, render, M, y0, lw, hgt, pad=3 * mm)
        rx, rw = M + lw + 9 * mm, W - 2 * M - lw - 9 * mm
        items = []
        for key, lab in (("idea", "The idea"), ("build", "How it's built"), ("products", "Showing the products"),
                         ("header", "Header and graphics"), ("why", "Why it works")):
            v = clean(st.get(key), session)
            if v:
                items += [_p(lab.upper(), EYEBROW), _p(v, BODY), _p(" ", SMALL)]
        need = clean(b.get("narrative"), session)
        if need:
            items += [_p("WHAT YOU ASKED FOR".upper(), EYEBROW), _p(need, BODY)]
        if not items:
            items = [_p(f"{lab}: {v}", BODY) for _g, rows in groups[:2] for lab, v in rows[:6]]
        _flow(c, items, rx, y0 + hgt, rw, hgt)
    pages.append(concept)

    # how we got here - the portal's dark "how we read your enquiry" panel, from what this chat actually did
    told = sum(len(rows) for _g, rows in groups)
    files = len([f for f in (b.get("_files") or []) if f.get("kind") == "image"])
    options = len({v.get("label") for v in session.get("visuals") or [] if v.get("kind") == "render" and v.get("label")})
    if told:
        def how(c, n, total):
            chrome(c, n, total, client, badge, client_logo)
            c.setFillColor(DARK)
            c.rect(0, 12 * mm + 2, W, H - 28 * mm - 12 * mm - 2, fill=1, stroke=0)
            eyebrow(c, M, TOP - 2 * mm, f"{client}  ·  {unit}  ·  how we designed it", YELLOW, 8)
            _flow(c, [_p("We listened to your brief the way a designer would.", H1_D),
                      _p("Every detail from the briefing went into the design, the drawings and the budget - "
                         "and nothing was guessed that you told us.", BODY_D)], M, TOP - 5 * mm, W - 2 * M, 22 * mm)
            ty, th = TOP - 66 * mm, 36 * mm
            tw = (W - 2 * M - 6 * mm) / 2

            def tile(x, label, nums, fill, ink):
                c.setFillColor(fill)
                c.roundRect(x, ty, tw, th, 4, fill=1, stroke=0)
                eyebrow(c, x + 5 * mm, ty + th - 7 * mm, label, ink if fill == YELLOW else YELLOW, 7)
                cw = (tw - 10 * mm) / max(1, len(nums))
                for i, (num, lab) in enumerate(nums):
                    c.setFont(BOLD, 28)
                    c.setFillColor(DARK if fill == YELLOW else colors.white)
                    c.drawString(x + 5 * mm + i * cw, ty + 12 * mm, str(num))
                    c.setFont(REG, 7.5)
                    c.setFillColor(DARK if fill == YELLOW else colors.HexColor("#C9CAC6"))
                    c.drawString(x + 5 * mm + i * cw, ty + 5.5 * mm, lab)
            tile(M, "What you told us", [(told, "details captured"), (len(groups), "areas covered")]
                 + ([(files, "pictures shared")] if files else []), colors.HexColor("#33352F"), colors.white)
            tile(M + tw + 6 * mm, "What we produced",
                 [(max(options, 1), "concepts explored"), (len(views) or len(angles), "views"),
                  (1 if ga else 0, "drawing at size")] + ([("£", "budget")] if bud else []), YELLOW, DARK)
            steps = [("01 · Listened", "Your brief, in your words",
                      f"{told} details - the unit, its size, materials, products, placement and dates."),
                     ("02 · Designed", st.get("name") or "One clear idea",
                      clean(st.get("idea"), session) or "A design built around what the unit has to do."),
                     ("03 · Drawn", f"At {size}" if size else "To size",
                      "Rendered from every angle and drawn as a general arrangement with its dimensions."),
                     ("04 · " + ("Costed" if bud else "Ready"), "An indicative budget" if bud else "Ready to develop",
                      (bud["basis"] if bud else "Ready for technical design as soon as you approve it."))]
            sw = (W - 2 * M - 3 * 5 * mm) / 4
            sh = min(58 * mm, ty - 8 * mm - 20 * mm)
            sy = ty - 8 * mm - sh
            for i, (no, head, txt) in enumerate(steps):
                x = M + i * (sw + 5 * mm)
                c.setFillColor(colors.HexColor("#33352F"))
                c.roundRect(x, sy, sw, sh, 4, fill=1, stroke=0)
                c.setFillColor(YELLOW)
                c.rect(x, sy + sh - 1.2 * mm, sw, 1.2 * mm, fill=1, stroke=0)
                eyebrow(c, x + 4 * mm, sy + sh - 8 * mm, no, YELLOW, 7)
                _flow(c, [_p(head, TILE_H), _p(" ", SMALL), _p(txt, BODY_D)], x + 4 * mm, sy + sh - 11 * mm,
                      sw - 8 * mm, sh - 14 * mm)
        pages.append(how)

    if groups:
        def spec(c, n, total):
            chrome(c, n, total, client, badge, client_logo)
            heading(c, "Specification", "Everything captured at briefing")
            cols = 3
            gw = (W - 2 * M - (cols - 1) * 9 * mm) / cols
            col_items = [[] for _ in range(cols)]
            load = [0] * cols
            for group, rows in groups:
                i = load.index(min(load))
                t = Table([[_p(lab, CELL_K), _p(v, CELL_V)] for lab, v in rows], colWidths=[gw * 0.36, gw * 0.64])
                t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                                       ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
                col_items[i] += [_p(group.upper(), EYEBROW), _p(" ", SMALL), t, _p(" ", BODY)]
                load[i] += 1.6 + sum(1 + len(v) / 42 for _l, v in rows)
            for i in range(cols):
                if col_items[i]:
                    _flow(c, col_items[i], M + i * (gw + 9 * mm), TOP - 22 * mm, gw, TOP - 22 * mm - 18 * mm)
        pages.append(spec)

    if angles:
        def every_angle(c, n, total):
            chrome(c, n, total, client, badge, client_logo)
            heading(c, "Every angle", "The design from every side" if views else
                    "The unit at its briefed size, from three sides")
            k = len(angles)
            cols, rows_ = (2, 2) if k == 4 else (k, 1)
            gap = 5 * mm
            cw = (W - 2 * M - (cols - 1) * gap) / cols
            top, bottom = TOP - 22 * mm, 17 * mm
            chh = (top - bottom - (rows_ - 1) * gap) / rows_
            for i, (p, cap) in enumerate(angles):
                x = M + (i % cols) * (cw + gap)
                y = top - (i // cols + 1) * chh - (i // cols) * gap
                card(c, x, y, cw, chh)
                image(c, p, x, y + 6 * mm, cw, chh - 6 * mm, pad=2.5 * mm, cover=bool(views))
                eyebrow(c, x + 4 * mm, y + 2.4 * mm, str(cap), MUTE, 6.8)
        pages.append(every_angle)

    if ga and os.path.isfile(ga):
        def sizes(c, n, total):
            chrome(c, n, total, client, badge, client_logo)
            heading(c, "Sizes", (f"General arrangement at {size}" if size else "General arrangement"),
                    "Dimensions in mm. Final dimensions are confirmed in technical design.")
            card(c, M, 16 * mm, W - 2 * M, TOP - 26 * mm - 16 * mm, colors.white)
            c.setStrokeColor(LINE)
            c.roundRect(M, 16 * mm, W - 2 * M, TOP - 26 * mm - 16 * mm, 6, fill=0, stroke=1)
            image(c, ga, M, 16 * mm, W - 2 * M, TOP - 26 * mm - 16 * mm, pad=2 * mm)
        pages.append(sizes)

    if bud and bud["rows"]:
        def budget_page(c, n, total):
            chrome(c, n, total, client, badge, client_logo)
            heading(c, "Indicative budget", "For this concept, per unit")
            q_brief = re.search(r"\d[\d,]*", str(b.get("volume_qty") or ""))
            q_brief = int(q_brief.group(0).replace(",", "")) if q_brief else None
            lead = next((r for r in bud["rows"] if r["qty"] == q_brief), bud["rows"][-1])
            # the portal's price card: unit price left, order value right
            cy, chh = TOP - 52 * mm, 28 * mm
            card(c, M, cy, W - 2 * M, chh)
            eyebrow(c, M + 7 * mm, cy + chh - 7 * mm, "Unit price", MUTE, 7)
            c.setFont(BOLD, 28)
            c.setFillColor(BLACK)
            c.drawString(M + 7 * mm, cy + 9 * mm, f"£{lead['unit']:,}")
            c.setFont(REG, 8.5)
            c.setFillColor(MUTE)
            c.drawString(M + 7 * mm, cy + 4 * mm, f"per unit, ex VAT  ·  indicative  ·  at {lead['qty']:,} units")
            c.drawRightString(W - M - 7 * mm, cy + chh - 7 * mm, " ".join("ORDER VALUE"))
            c.setFont(BOLD, 18)
            c.setFillColor(BLACK)
            c.drawRightString(W - M - 7 * mm, cy + 10 * mm, f"£{lead['total']:,}")
            c.setFont(REG, 8.5)
            c.setFillColor(MUTE)
            c.drawRightString(W - M - 7 * mm, cy + 4 * mm, "ex VAT  ·  indicative")
            colw = (W - 2 * M - 12 * mm) / 3
            yb = cy - 8 * mm
            rows = [[_p("Quantity", CELL_K), _p("Per unit", CELL_K), _p("Total", CELL_K)]] + \
                   [[_p(f"{r['qty']:,}", CELL_V), _p(f"£{r['unit']:,}", CELL_V), _p(f"£{r['total']:,}", CELL_V)]
                    for r in bud["rows"]]
            t = Table(rows, colWidths=[colw * 0.3, colw * 0.33, colw * 0.37])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            _flow(c, [_p("AT OTHER QUANTITIES", EYEBROW), _p(" ", SMALL), t], M, yb, colw, yb - 16 * mm)
            inc = [name for name, _pct in bud["parts"]] or ["Materials and components", "Manufacture and assembly",
                                                              "Finishing", "Packing for transport"]
            x2 = M + colw + 6 * mm
            c.setFont(SEMI, 7.5)
            eyebrow(c, x2, yb - 3 * mm, "What's included")
            yy = yb - 11 * mm
            for name in inc + (["One-off design for manufacture, programming and tooling"] if bud["setup"] else []):
                c.setFillColor(YELLOW)
                c.rect(x2, yy, 2.6 * mm, 2.6 * mm, fill=1, stroke=0)
                _flow(c, [_p(name, BODY)], x2 + 5.5 * mm, yy + 3.4 * mm, colw - 6 * mm, 10 * mm)
                yy -= 8.5 * mm
            x3 = x2 + colw + 6 * mm
            _flow(c, [_p("HOW IT WAS WORKED OUT", EYEBROW), _p(bud["basis"], BODY), _p(" ", BODY),
                      _p("PLEASE NOTE", EYEBROW),
                      _p("An indicative budget from the concept, to help you plan - not a quotation. The quotation "
                         "follows technical design. Prices exclude VAT, delivery and installation unless stated, and "
                         "are valid for 30 days.", BODY)], x3, yb, colw, yb - 16 * mm)
        pages.append(budget_page)

    def next_steps(c, n, total):
        chrome(c, n, total, client, badge, client_logo)
        heading(c, "Next steps", "From this concept to your stores")
        steps = [("Approve the concept", "Sign below, or tell us what you'd like changed.")]
        steps.append(("Technical design", "Detailed drawings and specification for manufacture."))
        if _yes(b, "prototype_required"):
            due = clean(b.get("prototype_due"), session, True)
            steps.append(("Prototype", "A sample to see, test and sign off" + (f", by {due}." if due else ".")))
        lt = clean(b.get("leadtime"), session, True)
        steps.append(("Production", (f"{qty} units" if qty else "Manufacture") + (f", {lt} lead time." if lt else ".")))
        ins = clean(b.get("instore_date"), session, True)
        steps.append(("In store", (f"By {ins}." if ins else "Delivered to you.") + (" Installed by SDI." if _yes(b, "installation") else "")))
        sw = (W - 2 * M - (len(steps) - 1) * 5 * mm) / len(steps)
        sy, sh = TOP - 66 * mm, 40 * mm
        for i, (head, txt) in enumerate(steps):
            x = M + i * (sw + 5 * mm)
            card(c, x, sy, sw, sh)
            c.setFillColor(YELLOW)
            c.rect(x, sy + sh - 1.2 * mm, sw, 1.2 * mm, fill=1, stroke=0)
            eyebrow(c, x + 5 * mm, sy + sh - 8 * mm, f"{i + 1:02d}")
            _flow(c, [_p(head, H3), _p(txt, BODY)], x + 5 * mm, sy + sh - 10 * mm, sw - 10 * mm, sh - 12 * mm)
        bh = min(52 * mm, sy - 10 * mm - 18 * mm)
        by = sy - 10 * mm - bh
        card(c, M, by, (W - 2 * M) * 0.42, bh, DARK)
        _flow(c, [_p("YOUR SDI CONTACT", EYEBROW_D), _p(" ", SMALL), _p(am or "Your SDI account manager", H1_D),
                  _p("hello@wearesdi.com  ·  +44 (0) 116 274 7040  ·  wearesdi.com", META_D)],
              M + 7 * mm, by + bh - 7 * mm, (W - 2 * M) * 0.42 - 14 * mm, bh - 10 * mm)
        bx, bw = M + (W - 2 * M) * 0.42 + 6 * mm, (W - 2 * M) * 0.58 - 6 * mm
        c.setStrokeColor(LINE)
        c.setLineWidth(0.8)
        c.setFillColor(colors.white)
        c.roundRect(bx, by, bw, bh, 6, fill=1, stroke=1)
        eyebrow(c, bx + 7 * mm, by + bh - 9 * mm, "Concept approved")
        for j, lab in enumerate(("Name", "Signature", "Date")):
            yy = by + bh - 21 * mm - j * 11 * mm
            c.setFont(REG, 8)
            c.setFillColor(MUTE)
            c.drawString(bx + 7 * mm, yy, lab)
            c.setStrokeColor(LINE)
            c.line(bx + 28 * mm, yy - 1 * mm, bx + bw - 7 * mm, yy - 1 * mm)
    pages.append(next_steps)

    c = canvas.Canvas(path, pagesize=(W, H))
    c.setTitle(f"{client} | {project or unit} - concept presentation")
    c.setAuthor("SDI Displays")
    c.setSubject("Concept presentation")
    total = len(pages)
    for n, draw in enumerate(pages, 1):
        draw(c, n, total)
        c.showPage()
    c.save()
    return path, total
