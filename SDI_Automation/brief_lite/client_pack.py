"""client_pack.py - the client concept pack: a few landscape pages in we.are.sdi's look (21 Nov 2026).

James: "It is for clients so it has to be brilliant ... all the details captured from the account person / designer fed
into the pack ... a few pages ... the estimate on there also, with as much detail as we can provide, depending on which
of the three was selected."

    1  Cover            the hero render full-page, client, project, contact, date, reference
    2  The concept      the render large, and the design story (the idea, how it's built, the products, the header, why)
    3  Specification    everything the AM and designer captured that a client should see, grouped
    4  Every angle      the views of this design; without them, the unit's own 3D model from three sides
    5  Sizes            the concept GA, a page to itself so every dimension can be read
    6  Indicative budget  only when SDI has set its markup (client_pack_markup_pct): SDI's estimate is a COST to make,
                       before margin, so the client sees cost + markup, labelled indicative, subject to quotation
    7  Next steps       what happens after approval, who to talk to, and a sign-off box

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
YELLOW = colors.HexColor("#F6D946")
BLACK = colors.HexColor("#111111")
INK = colors.HexColor("#2B2B2B")
MUTE = colors.HexColor("#6E6C66")
STONE = colors.HexColor("#E1E1D5")
SOFT = colors.HexColor("#F4F3EE")
LINE = colors.HexColor("#DEDCD3")
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


EYEBROW = _style("eyebrow", SEMI, 8, 10, MUTE)
TITLE = _style("title", BOLD, 30, 34, BLACK)
SUB = _style("sub", REG, 15, 19, INK)
H1 = _style("h1", BOLD, 22, 26, BLACK)
H3 = _style("h3", SEMI, 9.5, 12, BLACK, spaceBefore=7, spaceAfter=2)
BODY = _style("body", REG, 9.5, 13.2, INK)
BIG = _style("big", REG, 12, 16.5, INK)
SMALL = _style("small", REG, 7.5, 10, MUTE)
CELL_K = _style("cellk", SEMI, 8, 10.5, MUTE)
CELL_V = _style("cellv", REG, 9, 12, INK)

FOOTER = "we.are.sdi  |  Experiences. Designed & Made.  |  wearesdi.com  |  hello@wearesdi.com  |  +44 (0) 116 274 7040"


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


def image(c, path, x, y, w, h, cover=False, pad=0):
    """The picture in the box: whole (contain) or filling it, cropped (cover)."""
    if not path or not os.path.isfile(path):
        return False
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
        c.drawImage(path, x + (w - dw) / 2, y + (h - dh) / 2, width=dw, height=dh, mask="auto")
    except Exception:                                        # noqa: BLE001
        c.restoreState()
        return False
    c.restoreState()
    return True


def card(c, x, y, w, h, fill=SOFT):
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=0)


def chrome(c, n, title, logo):
    """Every page but the cover: the wordmark, the yellow rule, the page's place in the pack, the footer."""
    if logo and os.path.isfile(logo):
        c.drawImage(logo, W - M - 40 * mm, H - 15 * mm, width=40 * mm, height=7 * mm, preserveAspectRatio=True,
                    mask="auto", anchor="e")
    c.setFillColor(MUTE)
    c.setFont(SEMI, 7.5)
    c.drawString(M, H - 12.5 * mm, title.upper())
    c.setStrokeColor(YELLOW)
    c.setLineWidth(2.2)
    c.line(M, H - 18 * mm, W - M, H - 18 * mm)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(M, 13 * mm, W - M, 13 * mm)
    c.setFont(REG, 7)
    c.setFillColor(MUTE)
    c.drawString(M, 8.5 * mm, FOOTER)
    c.drawRightString(W - M, 8.5 * mm, f"{n}")


def heading(c, text, sub=""):
    _flow(c, [_p(text, H1)] + ([_p(sub, BODY)] if sub else []), M, H - 25 * mm, W - 2 * M, 20 * mm)


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
        faces = []
        for p in parts:
            x, y, z, w_, h_, d_ = (float(p[k]) for k in ("x", "y", "z", "w", "h", "d"))
            v = [(x + dx * w_, y + dy * h_, z + dz * d_) for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
            col = tuple(int(p["colour"][i:i + 2], 16) for i in (1, 3, 5))
            for idx, shade in (((1, 3, 7, 5), 1.0), ((0, 2, 6, 4), 0.62), ((4, 5, 7, 6), 0.82), ((0, 1, 3, 2), 0.82),
                               ((2, 3, 7, 6), 1.08), ((0, 1, 5, 4), 0.5)):
                pts = [proj(*v[i]) for i in idx]
                faces.append((sum(q[2] for q in pts) / 4, [(q[0], q[1]) for q in pts],
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
        for _d, pts, col in sorted(faces, key=lambda f: f[0]):          # far faces first
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
}


def budget(est, markup_pct):
    """SDI's estimate (cost per unit at each quantity) -> the client's indicative price, rounded. None without both."""
    if not est or markup_pct is None or not est.get("prices"):
        return None
    k = 1 + float(markup_pct) / 100.0
    rnd = lambda v: int(round(v / 5.0)) * 5 if v >= 100 else int(round(v))
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
def build(path, session, render, ga=None, views=None, model=None, story=None, est=None, markup_pct=None,
          client_logo=None, sdi_logo=None, today=None):
    """Write the pack to `path`. render/ga/views: image paths (views: [(path, caption)]). story: the design director's
    direction for this option ({name, idea, build, products, header, why}). est: the estimate chosen for this option."""
    today = today or date.today()
    b = session.get("brief") or {}
    client = clean(b.get("client")) or "Your concept"
    unit = clean(b.get("unit_type")) or "Display concept"
    project = clean(b.get("project_name"), session, keep_numbers=True)
    title = f"{client} | {unit}"
    c = canvas.Canvas(path, pagesize=(W, H))
    c.setTitle(title)
    c.setAuthor("SDI Displays")
    c.setSubject("Concept presentation")
    n = 1

    # 1 cover
    image(c, render, 0, 0, W, H, cover=True)
    c.setFillColor(colors.white)
    c.rect(0, 0, W * 0.5, 64 * mm, fill=1, stroke=0)
    c.setFillColor(YELLOW)
    c.rect(0, 64 * mm, W * 0.5, 2.2 * mm, fill=1, stroke=0)
    meta = " · ".join(x for x in (
        f"For {clean(b.get('customer_name'), session)}" if clean(b.get("customer_name"), session) else "",
        f"{today:%d %B %Y}",
        f"Ref {clean(b.get('job_number'), session, True)}" if clean(b.get("job_number"), session, True) else "") if x)
    _flow(c, [_p("CONCEPT PRESENTATION", EYEBROW), _p(client, TITLE), _p(project or unit, SUB), _p(" ", SMALL),
              _p(meta, BODY)], M, 56 * mm, W * 0.5 - 2 * M, 46 * mm)
    if sdi_logo and os.path.isfile(sdi_logo):
        card(c, W - M - 52 * mm, H - M - 14 * mm, 52 * mm, 14 * mm, colors.white)
        c.drawImage(sdi_logo, W - M - 48 * mm, H - M - 11 * mm, width=44 * mm, height=8 * mm, preserveAspectRatio=True,
                    mask="auto", anchor="c")
    if client_logo and os.path.isfile(client_logo):
        card(c, M, H - M - 24 * mm, 46 * mm, 24 * mm, colors.white)
        image(c, client_logo, M, H - M - 24 * mm, 46 * mm, 24 * mm, pad=3 * mm)
    c.showPage()

    # 2 the concept
    n += 1
    chrome(c, n, title, sdi_logo)
    heading(c, "The concept", (story or {}).get("name") or "")
    lw = (W - 2 * M) * 0.58
    card(c, M, 20 * mm, lw, H - 62 * mm)
    image(c, render, M, 20 * mm, lw, H - 62 * mm, pad=4 * mm)
    rx, rw = M + lw + 9 * mm, W - 2 * M - lw - 9 * mm
    items = []
    st = story or {}
    for key, lab in (("idea", "The idea"), ("build", "How it's built"), ("products", "Showing the products"),
                     ("header", "Header and graphics"), ("why", "Why it works")):
        v = clean(st.get(key), session)
        if v:
            items += [_p(lab, H3), _p(v, BODY)]
    need = clean(b.get("narrative"), session)
    if need:
        items += [_p("What you asked for", H3), _p(need, BODY)]
    if not items:
        items = [_p("Your brief", H3)] + [_p(f"{lab}: {v}", BODY) for _g, rows in spec_groups(b, session)[:2]
                                           for lab, v in rows[:5]]
    _flow(c, items, rx, H - 44 * mm, rw, H - 64 * mm)
    c.showPage()

    # 3 specification
    groups = spec_groups(b, session)
    if groups:
        n += 1
        chrome(c, n, title, sdi_logo)
        heading(c, "The specification", "Everything captured for this unit at briefing.")
        cols = 3
        gw = (W - 2 * M - (cols - 1) * 8 * mm) / cols
        col_items = [[] for _ in range(cols)]
        load = [0] * cols
        for group, rows in groups:                                         # fill the lightest column
            i = load.index(min(load))
            t = Table([[_p(lab, CELL_K), _p(v, CELL_V)] for lab, v in rows], colWidths=[gw * 0.36, gw * 0.64])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
            col_items[i] += [_p(group, H3), t]
            load[i] += 1.4 + sum(1 + len(v) / 42 for _l, v in rows)
        for i in range(cols):
            if col_items[i]:
                _flow(c, col_items[i], M + i * (gw + 8 * mm), H - 45 * mm, gw, H - 62 * mm)
        c.showPage()

    # 4 every angle
    pics = [(p, cap) for p, cap in (views or []) if p and os.path.isfile(p)][:4]
    if len(pics) < 2 and model:
        pics = model_pictures(model, os.path.dirname(path), os.path.splitext(os.path.basename(path))[0])
    if pics:
        n += 1
        chrome(c, n, title, sdi_logo)
        heading(c, "From every angle", "" if views else "The unit at its briefed size, from three sides.")
        k = len(pics)
        cols = 2 if k == 4 else k
        rows_ = 2 if k == 4 else 1
        gap = 6 * mm
        cw = (W - 2 * M - (cols - 1) * gap) / cols
        top, bottom = H - 45 * mm, 20 * mm
        chh = (top - bottom - (rows_ - 1) * gap) / rows_
        for i, (p, cap) in enumerate(pics):
            x = M + (i % cols) * (cw + gap)
            y = top - (i // cols + 1) * chh - (i // cols) * gap
            card(c, x, y, cw, chh)
            image(c, p, x, y + 6 * mm, cw, chh - 6 * mm, pad=3 * mm)
            c.setFont(SEMI, 7.5)
            c.setFillColor(MUTE)
            c.drawString(x + 4 * mm, y + 3 * mm, str(cap).upper())
        c.showPage()

    # 5 sizes
    if ga and os.path.isfile(ga):
        n += 1
        chrome(c, n, title, sdi_logo)
        size = clean(b.get("size"), session, True)
        heading(c, "Sizes", (f"Concept general arrangement at {size}. " if size else "") +
                "Dimensions in mm; final dimensions are confirmed in technical design.")
        card(c, M, 18 * mm, W - 2 * M, H - 60 * mm, colors.white)
        image(c, ga, M, 18 * mm, W - 2 * M, H - 60 * mm, pad=2 * mm)
        c.showPage()

    # 6 indicative budget
    bud = budget(est, markup_pct)
    if bud and bud["rows"]:
        n += 1
        chrome(c, n, title, sdi_logo)
        heading(c, "Indicative budget", "For this concept, per unit, at the quantities below.")
        q_brief = re.search(r"\d[\d,]*", str(b.get("volume_qty") or ""))
        q_brief = int(q_brief.group(0).replace(",", "")) if q_brief else None
        lead = next((r for r in bud["rows"] if r["qty"] == q_brief), bud["rows"][-1])
        card(c, M, H - 98 * mm, 92 * mm, 46 * mm, STONE)
        c.setFillColor(BLACK)
        c.setFont(BOLD, 34)
        c.drawString(M + 7 * mm, H - 74 * mm, f"£{lead['unit']:,}")
        c.setFont(REG, 10.5)
        c.setFillColor(INK)
        c.drawString(M + 7 * mm, H - 83 * mm, f"per unit at {lead['qty']:,} units")
        c.setFont(SEMI, 9)
        c.drawString(M + 7 * mm, H - 91 * mm, f"£{lead['total']:,} for {lead['qty']:,} units, excluding VAT")
        rows = [[_p("Quantity", CELL_K), _p("Per unit", CELL_K), _p("Total", CELL_K)]] + \
               [[_p(f"{r['qty']:,}", CELL_V), _p(f"£{r['unit']:,}", CELL_V), _p(f"£{r['total']:,}", CELL_V)]
                for r in bud["rows"]]
        t = Table(rows, colWidths=[30 * mm, 30 * mm, 32 * mm])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        _flow(c, [_p("At other quantities", H3), t], M, H - 104 * mm, 92 * mm, 60 * mm)
        rx = M + 104 * mm
        right = [_p("What's in it", H3)]
        if bud["parts"]:
            right += [_p(f"{name} - about {pct}%", BODY) for name, pct in bud["parts"]]
        else:
            right += [_p("Materials, manufacture, finishing and packing for each unit.", BODY)]
        if bud["setup"]:
            right += [_p("One-off, once per order", H3),
                      _p(f"Design for manufacture, programming and tooling: about £{bud['setup']:,}, shared across the "
                         "order and included in the prices shown.", BODY)]
        right += [_p("How it was worked out", H3), _p(bud["basis"], BODY),
                  _p("Please note", H3),
                  _p("An indicative budget from the concept, to help you plan - not a quotation. The quotation follows "
                     "technical design. Excludes VAT, delivery and installation unless stated. Valid for 30 days.", BODY)]
        _flow(c, right, rx, H - 50 * mm, W - M - rx, H - 70 * mm)
        c.showPage()

    # 7 next steps
    n += 1
    chrome(c, n, title, sdi_logo)
    heading(c, "Next steps")
    yes = lambda k: bool(re.match(r"\s*(yes|y|needed|required|true)", str(b.get(k) or ""), re.I))
    steps = [("Approve the concept", "Sign below, or tell your account manager what you'd like changed.")]
    steps.append(("Technical design", "Detailed drawings and specification for manufacture."))
    if yes("prototype_required"):
        steps.append(("Prototype", "A sample unit to see, test and sign off" +
                      (f" - by {clean(b.get('prototype_due'), session, True)}." if clean(b.get("prototype_due"), session, True) else ".")))
    qty = clean(b.get("volume_qty"), session, True)
    lt = clean(b.get("leadtime"), session, True)
    steps.append(("Production", (f"{qty} units" if qty else "Manufacture") + (f", {lt} lead time." if lt else ".")))
    ins = clean(b.get("instore_date"), session, True)
    steps.append(("In store", (f"In store by {ins}." if ins else "Delivered") + (" Installed by SDI." if yes("installation") else "")))
    sw = (W - 2 * M - (len(steps) - 1) * 5 * mm) / len(steps)
    for i, (head, txt) in enumerate(steps):
        x = M + i * (sw + 5 * mm)
        card(c, x, H - 86 * mm, sw, 40 * mm)
        c.setFillColor(YELLOW)
        c.circle(x + 9 * mm, H - 55 * mm, 4.2 * mm, fill=1, stroke=0)
        c.setFillColor(BLACK)
        c.setFont(BOLD, 10)
        c.drawCentredString(x + 9 * mm, H - 56.6 * mm, str(i + 1))
        _flow(c, [_p(head, H3), _p(txt, BODY)], x + 5 * mm, H - 61 * mm, sw - 10 * mm, 24 * mm)
    am = clean(b.get("account_manager"), session)
    contact = [_p("Your SDI contact", H3), _p(am or "Your SDI account manager", BIG),
               _p("hello@wearesdi.com  ·  +44 (0) 116 274 7040", BODY)]
    _flow(c, contact, M, H - 96 * mm, 100 * mm, 30 * mm)
    bx, bw, by, bh = M + 116 * mm, W - 2 * M - 116 * mm, 20 * mm, 62 * mm
    card(c, bx, by, bw, bh, colors.white)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.8)
    c.roundRect(bx, by, bw, bh, 6, fill=0, stroke=1)
    c.setFont(SEMI, 10)
    c.setFillColor(BLACK)
    c.drawString(bx + 7 * mm, by + bh - 10 * mm, "Concept approved")
    for j, lab in enumerate(("Name", "Signature", "Date")):
        yy = by + bh - 24 * mm - j * 13 * mm
        c.setFont(REG, 8)
        c.setFillColor(MUTE)
        c.drawString(bx + 7 * mm, yy, lab)
        c.setStrokeColor(LINE)
        c.line(bx + 30 * mm, yy - 1 * mm, bx + bw - 7 * mm, yy - 1 * mm)
    c.showPage()
    c.save()
    return path, n
