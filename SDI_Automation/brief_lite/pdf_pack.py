"""SDI's eight-page internal brief and one-page client concept sheet.

No network writes or AI calls. Historical costs retain their source and scope;
planning scenarios are distinguished from quoted prices and booked dates.
Public build()/client_sheet() signatures are retained for the existing app.
"""
import itertools
import json
import math
import os
import re
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing, Line, Polygon
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepInFrame, Paragraph, Spacer, Table, TableStyle

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(os.path.dirname(HERE), "logo.png")
RED, INK, MUTE, LINE, SOFT = (colors.HexColor(x) for x in
                            ("#c8102e", "#202733", "#626b78", "#dce0e5", "#f4f5f7"))
RATE_GBP = 75
# Equipment dimensions are planning examples, not carrier guarantees. The one
# historical freight figure in the supplied brief is GBP1,170 for 33 pallets.
LOADS = [
    ("Artic trailer (UK)", 13600, 2480, 2700, 1170,
     "Historical SDI benchmark: GBP1,170 per artic / 33 pallets; route and date need reconfirming"),
    ("20ft container", 5898, 2352, 2393, None, "Freight quotation required"),
    ("40ft container", 12032, 2352, 2393, None, "Freight quotation required"),
    ("40ft high cube", 12032, 2352, 2698, None, "Freight quotation required"),
]
# Existing app planning assumptions, in working weeks. These are never called
# historical lead times. China manufacture is 6 weeks plus 42 calendar sea days.
# The gaps only the client can fill, worded as a question the account manager can paste into an email.
CLIENT_ASKS = {
    "instore_date": "What date do the units need to be in store?",
    "size": "What are the approximate height, width and depth the unit must fit into?",
    "placement": "Where in the store will it sit (front of store, aisle end, counter, window)?",
    "materials": "Are there any material or finish requirements (e.g. FSC board, powder-coat colour, wood finish)?",
    "colours_graphics": "Can you send the brand colours, logo and any graphics or artwork for the header and shelf edges?",
    "products_held": "What products will it display, and can you send sizes or a sample so we can fit the shelves?",
    "volume_qty": "How many units do you expect to need, and is it a single store or a roll-out?",
    "target_unit_cost": "Is there a target budget per unit?",
    "shelf_life": "How long will the unit stay in store (weeks, months, years)?",
    "assembled": "Should it arrive fully assembled or flat-packed to build in store?",
    "delivery_restrictions": "Is delivery direct to store or to a warehouse, and are there any access or delivery restrictions?",
    "references": "Do you have any reference images, sketches or a similar unit you like?",
    "repeat": "Is this likely to repeat, and how often?",
}
STAGES = {"creative": 2, "client sign-off": 1, "technical GA": 1,
          "full technical (after GA)": 0.6, "prototype": 3,
          "manufacture UK": 5, "manufacture Europe": 7,
          "manufacture China": 6, "sea freight (China)": 6, "installation": 1}
st = getSampleStyleSheet()
H1 = ParagraphStyle("sdi_h1", parent=st["Heading1"], fontSize=19, leading=23, textColor=RED, spaceAfter=12)
H2 = ParagraphStyle("sdi_h2", parent=st["Heading2"], fontSize=11, leading=14, textColor=INK, spaceBefore=10, spaceAfter=5)
P = ParagraphStyle("sdi_p", parent=st["BodyText"], fontSize=9, leading=12, textColor=INK, spaceAfter=4)
SMALL = ParagraphStyle("sdi_small", parent=P, fontSize=7.5, leading=10, textColor=MUTE)
BIG = ParagraphStyle("sdi_big", parent=P, fontSize=18, leading=23)


def today():
    """Use the business timezone even when the server is moved elsewhere."""
    return datetime.now(ZoneInfo("Europe/London")).date()


def _text(value, limit=1200):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    value = str(value if value is not None else "").replace("\x00", "")
    value = value.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    if limit and len(value) > limit:
        value = value[:limit] + "... [full response in companion JSON]"
    return escape(value)


def _p(value, style=P, limit=1200):
    return Paragraph(_text(value, limit), style)


def _missing(value):
    return value is None or str(value).strip().lower() in {
        "", "unknown", "not known", "don't know", "dont know", "not sure", "skip", "tbc", "tbd"}


def parse_size(text):
    """Parse only complete H/W/D values; bare values use the template's mm unit.

    Supports labelled dimensions in any order and an H x W x D sequence with
    shared trailing units. Never infer metres from a small bare number.
    """
    if not text:
        return None
    t = str(text).lower().replace("\u00d7", "x").replace(",", " ")
    t = re.sub(r"\bmillimet(?:er|re)s?\b", "mm", t)
    t = re.sub(r"\bcentimet(?:er|re)s?\b", "cm", t)
    t = re.sub(r"\bmet(?:er|re)s?\b", "m", t)
    scale = {"mm": 1, "cm": 10, "m": 1000, "": 1}
    num = r"(\d+(?:\.\d+)?)"
    unit = r"\s*(mm|cm|m)?"
    labels = r"(height|high|tall|width|wide|depth|deep|h|w|d)\b"
    values = {}
    # "1800 high 600 wide 400 deep" (number first) and "height 1800 width 600 depth 400" (label first) are two different
    # layouts. Read each on its own and keep the one that gives all three - mixing them pairs a label with the NEXT number.
    for pattern, first in ((num + unit + r"\s*" + labels, False),
                           (r"\b(height|high|tall|width|wide|depth|deep|h|w|d)(?=[\s:=\d])\s*[:=]?\s*" + num + unit, True)):
        found = {}
        for hit in re.finditer(pattern, t):
            label, number, units = hit.groups() if first else (hit[3], hit[1], hit[2])
            key = "h" if label == "tall" else label[0]
            value = float(number) * scale[units or ""]
            if key in found and found[key] != value:
                found = {}
                break
            found[key] = value
        if len(found) == 3:
            values = found
            break
        if len(found) > len(values):
            values = found
    if len(values) == 3:
        result = tuple(values[k] for k in "hwd")
    elif values:
        return None
    else:
        match = re.search(num + unit + r"\s*x\s*" + num + unit + r"\s*x\s*" + num + unit, t)
        if not match:
            return None
        numbers = [match[1], match[3], match[5]]
        units = [match[2], match[4], match[6]]
        common = units[-1] if not any(units[:-1]) else None
        result = tuple(float(n) * scale[u or common or ""] for n, u in zip(numbers, units))
    return result if all(math.isfinite(v) and 0 < v <= 100000 for v in result) else None


def money(text):
    """Read a supplied number (also used by legacy code for quantities)."""
    if isinstance(text, bool) or _missing(text):
        return None
    match = re.search(r"(?<![\w.-])(?:GBP|£|\$|€)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", str(text), re.I)
    if not match:
        return None
    value = float(match[1].replace(",", "")) * (1000 if match[2] else 1)
    return value if math.isfinite(value) else None


def when(text):
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    t = str(text or "")
    for pattern, fmt in ((r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
                         (r"\d{1,2}/\d{1,2}/\d{4}", "%d/%m/%Y"),
                         (r"\d{1,2}/\d{1,2}/\d{2}\b", "%d/%m/%y")):
        match = re.search(pattern, t)
        if match:
            try:
                return datetime.strptime(match[0], fmt).date()
            except ValueError:
                pass
    match = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(\d{4})", t)
    if match:
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(" ".join(match.groups()), fmt).date()
            except ValueError:
                pass
    return None


def requirement_from(brief):
    """What the client wants, in a few lines, when no narrative was written - from the answers already in the brief
    (3 Nov 2026: 'Customer requirement: Not given' after the AM had described the whole unit)."""
    unit = " ".join(w if (w.isupper() or re.search(r"\d", w)) else w.lower() for w in str(brief.get("unit_type") or "").split())
    art = "an" if re.match(r"(?i)[aeio]|fsdu|lsdu|led", unit) else "a"        # 'an FSDU', 'a gondola end'
    parts = [f"{brief.get('client')} need {art} {unit}" if brief.get("client") and unit else unit]
    for key, label in (("placement", "for"), ("size", "at"), ("products_held", "holding"), ("colours_graphics", "finished in"),
                       ("materials", "made in"), ("liked_job", "following")):
        v = str(brief.get(key) or "").strip()
        names = {w.lower() for w in re.findall(r"[A-Za-z&]+", f"{brief.get('client') or ''} {brief.get('retailer') or ''}")}
        if v[:1].isupper() and v.split()[0].lower() not in names and not v.split()[0].isupper() and not re.search(r"\d", v.split()[0]):
            v = v[0].lower() + v[1:]          # mid-sentence: 'holding bagged coal', but 'finished in Tesco blue'
        if v and not re.match(r"(not known|not given|none|n/?a)\b", v, re.I):
            parts.append(f"{label} {re.sub(r' - the AM asked to follow it closely$', '', v)}")
    text = ", ".join(p for p in parts if p).strip()
    return (text[0].upper() + text[1:] + ".") if text else "Not given"


def short_name(r):
    job = str(r.get("job_no") or "")
    name = re.sub(r"^" + re.escape(job) + r"[\s-]*", "", str(r.get("name") or ""))
    return f"{job} {name[:75]}".strip()


def yes(text):
    return text is True or bool(re.match(r"\s*(yes|y|yeah|yep|required|needed|true|chargeable)\b", str(text or ""), re.I))


def packed_size(hwd, assembled_text):
    h, w, d = hwd
    if re.search(r"flat|kit|knock", str(assembled_text or ""), re.I):
        thick = max(80.0, round(d * 0.25 / 10) * 10)
        box = (w + 100, h + 100, thick)
        return box, "ASSUMED flat-pack carton: %.0f x %.0f x %.0f mm; 25%% of unit depth, minimum 80 mm; confirm carton" % box
    box = (h + 100, w + 100, d + 100)
    mode = "Assembled" if re.search(r"assembl|built", str(assembled_text or ""), re.I) else "ASSUMED assembled (packing not confirmed)"
    return box, mode + ": unit plus 50 mm each side = %.0f x %.0f x %.0f mm" % box


def fit(load, box):
    """Geometric ceiling only; unrestricted rotation/stacking must be approved."""
    if not load or not box or any(not math.isfinite(v) or v <= 0 for v in (*load, *box)):
        return 0, None
    best = (0, None)
    for orient in sorted(set(itertools.permutations(box))):
        number = math.prod(int(a // b) for a, b in zip(load, orient))
        if number > best[0]:
            best = number, orient
    return best


def _scope(estimate):
    explicit = str(estimate.get("scope") or estimate.get("cost_scope") or "").lower()
    description = str(estimate.get("description") or "").lower()
    if explicit in {"whole_unit", "whole unit", "complete unit", "finished unit"}:
        return "whole unit"
    if re.search(r"\b(component|replacement|spare|header|shelf|shelves|bracket|panel|graphic|decal|lens|base only|logo|block|strip|"
                 r"hook|hooks|label|sticker|lid|tray insert|price holder|ticket|clip|uprights?|toppers?|plinths?|rails?|"
                 r"trims?|kits?|wobblers?|shrouds?|panels|brackets|headers|graphics)\b", description):
        return "component / scope unconfirmed"
    if re.search(r"\b(complete|assembled|finished)\s+(unit|display|stand)\b", description):
        return "whole unit"
    # an estimate named after a whole fixture ("1m HDC Wall Bay", "Battery wall bay + security", "Garden FSDU") is the unit
    if re.search(r"\b(bay|bays|fsdu|gondola|unit|stand|display|pod|pods|kiosk|counter|plinth|totem|table|cabinet|wall|end)\b", description):
        return "whole unit"
    return "scope unconfirmed"


def comparable_estimates(brief, refs, limit=8):
    """Use only retrieved closest jobs. Never silently substitute all client jobs."""
    rows, seen = [], set()
    database = Path(HERE, "knowledge.db")
    con = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=3) if database.exists() else None
    try:
        if con:
            con.row_factory = sqlite3.Row
        for ref in refs or []:
            job = str(ref.get("job_no") or "")
            if not job or job in seen or len(rows) >= limit:
                continue
            estimate = dict(ref.get("estimate") or {})
            if not estimate and con:
                try:
                    hit = con.execute("SELECT * FROM estimates WHERE job_no=? AND status='ok' AND unit_cost>0 ORDER BY est_date DESC, mtime DESC LIMIT 1", (job,)).fetchone()
                    estimate = dict(hit) if hit else {}
                except sqlite3.Error:
                    estimate = {}
            unit = money(estimate.get("unit_cost"))
            if unit is None or unit <= 0:
                continue
            seen.add(job)
            rows.append({"job": job, "what": estimate.get("description") or ref.get("name") or "Description unavailable",
                         "qty": money(estimate.get("qty")), "unit": unit,
                         "date": estimate.get("est_date") or estimate.get("date") or "Not recorded",
                         "why": "retrieved similar job", "scope": _scope(estimate),
                         "source": estimate.get("path"), "sell_price": money(estimate.get("sell_price"))})
    finally:
        if con:
            con.close()
    return rows


def _workdays(start, amount):
    step = 1 if amount >= 0 else -1
    remaining = abs(int(amount))
    while remaining:
        start += timedelta(days=step)
        if start.weekday() < 5:
            remaining -= 1
    return start


def timeline(brief):
    """Schedule backwards from the in-store date; timings are labelled assumptions."""
    due, current = when(brief.get("instore_date")), today()
    region = str(brief.get("region") or "").lower()
    plan, issues = [], []
    for field, stages in (("creative_required", ["creative", "client sign-off"]),
                          ("technical_required", ["technical GA", "full technical (after GA)"]),
                          ("prototype_required", ["prototype", "client sign-off"])):
        if yes(brief.get(field)) or (field != "prototype_required" and _missing(brief.get(field))):
            plan.extend(stages)
            if _missing(brief.get(field)):
                issues.append(field.replace("_", " ").capitalize() + " is unconfirmed; included in this planning scenario.")
    if not str(brief.get("volume_required") or "").lower().startswith("no"):
        if "china" in region:
            plan.extend(["manufacture China", "sea freight (China)"])
        else:
            plan.append("manufacture Europe" if "europe" in region else "manufacture UK")
            if not region:
                issues.append("Manufacture region is unknown; the UK scenario is used for planning only.")
    if yes(brief.get("installation")):
        plan.append("installation")
    rows = []
    anchor = due or current
    for stage in (reversed(plan) if due else plan):
        days = round(STAGES[stage] * (7 if stage.startswith("sea freight") else 5))
        offset = -days if due else days
        other = anchor + timedelta(days=offset) if stage.startswith("sea freight") else _workdays(anchor, offset)
        rows.append((stage, other, anchor) if due else (stage, anchor, other))
        anchor = other
    if due:
        rows.reverse()
        if rows and rows[0][1] < current:
            shortfall = (current - rows[0][1]).days
            issues.append(f"Required start {rows[0][1]:%d %b %Y} is {shortfall} calendar days before today. Review supplier capacity, overlapping approved stages, transport options or a revised in-store date.")
    else:
        issues.append("No valid in-store date: indicative forward scenario only; confirm the required date.")
    for field, stage in (("creative_due", "creative"), ("technical_due", "full technical (after GA)"), ("prototype_due", "prototype")):
        wanted = when(brief.get(field))
        scheduled = next((r[2] for r in rows if r[0] == stage), None)
        if wanted and scheduled and scheduled > wanted:
            issues.append(f"{stage.capitalize()} scenario ends {scheduled:%d %b %Y}, after requested {wanted:%d %b %Y}.")
    weeks = (rows[-1][2] - rows[0][1]).days / 7 if rows else 0
    return rows, issues, weeks, due


def iso_loading(load, box_o, n, max_draw=400):
    """Bounded illustrative geometry, not a palletisation or restraint design."""
    L, W, H = load
    a, b, c = box_o
    dw, dh = 170 * mm, 82 * mm
    cosine, sine = math.cos(math.pi / 6), math.sin(math.pi / 6)
    scale = min((dw - 10 * mm) / ((L + W) * cosine), (dh - 10 * mm) / ((L + W) * sine + H))
    drawing = Drawing(dw, dh)
    def point(x, y, z):
        return 5 * mm + (W + x - y) * cosine * scale, 5 * mm + ((x + y) * sine + z) * scale
    nx, ny, nz = [int(v // b) for v, b in zip(load, box_o)]
    # Cap dimensions before constructing cells so tiny cartons cannot allocate
    # millions of tuples just to draw a few hundred illustrative boxes.
    cells = list(itertools.islice(itertools.product(range(nx), range(ny), range(nz)), min(n, max_draw)))
    for ix, iy, iz in sorted(cells, key=lambda t: (-(t[0] + t[1]), t[2])):
        x, y, z = ix * a, iy * b, iz * c
        for corners, fill in (([(x,y,z+c),(x+a,y,z+c),(x+a,y+b,z+c),(x,y+b,z+c)], "#f4c6cd"),
                              ([(x,y,z),(x+a,y,z),(x+a,y,z+c),(x,y,z+c)], "#df7f8d"),
                              ([(x,y,z),(x,y+b,z),(x,y+b,z+c),(x,y,z+c)], "#c8102e")):
            drawing.add(Polygon([q for corner in corners for q in point(*corner)], fillColor=colors.HexColor(fill), strokeColor=RED, strokeWidth=0.2))
    vertices = list(itertools.product((0,L), (0,W), (0,H)))
    for p, q in itertools.combinations(vertices, 2):
        if sum(a != b for a, b in zip(p,q)) == 1:
            drawing.add(Line(*point(*p), *point(*q), strokeColor=INK, strokeWidth=0.6))
    return drawing


def kv_table(rows, w1=62):
    cells = [[_p(k, SMALL, 180), _p(v)] for k, v in rows] or [[_p("Information"), _p("Not given")]]
    return Table(cells, colWidths=[w1 * mm, (174 - w1) * mm], style=TableStyle([
        ("GRID", (0,0), (-1,-1), 0.3, LINE), ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BACKGROUND", (0,0), (0,-1), SOFT), ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))


def val(brief, key):
    return "Not given / needs confirming" if _missing(brief.get(key)) else str(brief[key])


def _safe_output(out_dir, name):
    destination = Path(out_dir).resolve()
    if destination.drive.upper() != "C:" or str(destination).startswith("\\\\"):
        raise ValueError("SDI Same Day Intelligence exports must be saved locally on C:.")
    destination.mkdir(parents=True, exist_ok=True)
    return str(destination / name)


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "brief"))[:70]


def header_footer(c, doc, title):
    c.saveState()
    if os.path.isfile(LOGO):
        try:
            c.drawImage(LOGO, 18*mm, A4[1]-15*mm, width=26*mm, height=9*mm, preserveAspectRatio=True, mask="auto")
        except (OSError, ValueError):
            pass
    c.setFillColor(MUTE)
    c.setFont("Helvetica", 7)
    c.drawRightString(A4[0]-18*mm, A4[1]-11*mm, str(title)[:88])
    c.setStrokeColor(RED)
    c.line(18*mm, A4[1]-19*mm, A4[0]-18*mm, A4[1]-19*mm)
    c.drawString(18*mm, 10*mm, "SDI Displays | INTERNAL | Concept and planning information - not a quotation")
    c.drawRightString(A4[0]-18*mm, 10*mm, f"{doc.page} / 8")
    c.restoreState()


def _flow(c, story, x, top, width, height):
    # A fixed frame guarantees the contractual page count. Long narrative
    # values are bounded for print and retained in full in the JSON export.
    frame = KeepInFrame(width, height, story, mode="shrink", hAlign="LEFT", vAlign="TOP")
    _, used = frame.wrapOn(c, width, height)
    frame.drawOn(c, x, top-used)


def _photo(c, visual, x, y, width, height, empty):
    c.setFillColor(SOFT)
    c.roundRect(x, y, width, height, 5, fill=1, stroke=0)
    if visual and os.path.isfile(str(visual.get("path") or "")):
        try:
            c.drawImage(visual["path"], x+3*mm, y+3*mm, width=width-6*mm, height=height-6*mm,
                        preserveAspectRatio=True, anchor="c", mask="auto")
            return True
        except (OSError, ValueError):
            pass
    _flow(c, [_p(empty, SMALL)], x+7*mm, y+height/2, width-14*mm, height/2)
    return False


def _reference_paths(session):
    paths = set()
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"path", "thumb", "src", "img", "image"} and isinstance(item, str):
                    paths.add(os.path.normcase(os.path.abspath(item)))
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(session.get("refs") or [])
    return paths


def _client_text(value, session):
    """External spec allow-list plus removal of accidental internal identifiers."""
    text = str(value or "")
    for ref in session.get("refs") or []:
        job = str(ref.get("job_no") or "")
        if job:
            text = re.sub(r"(?<!\w)" + re.escape(job) + r"(?!\w)", "", text)
    text = re.sub(r"(?:GBP|£|USD|\$|EUR|€)\s*[\d,.]+\s*[kK]?", "", text, flags=re.I)
    text = re.sub(r"\b(?:job|estimate|quote)\s*(?:no\.?|number|#|:)?\s*\d[\w/-]*", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -;,|")[:500]


def _client_logo(session):
    """The client's own logo for the sheet (27 Oct 2026, Muhammad): SDI's brand-logo library first
    (studio_data/brand_logos/<client>.png), then a file the AM uploaded that is a logo."""
    brief = session.get("brief") or {}
    name = re.sub(r"[^a-z0-9]+", "-", str(brief.get("client") or "").lower()).strip("-")
    lib = os.path.join(os.path.dirname(HERE), "studio_data", "brand_logos")
    for cand in (name, name.split("-")[0] if name else ""):
        for ext in (".png", ".jpg", ".jpeg"):
            p = os.path.join(lib, cand + ext)
            if cand and os.path.isfile(p):
                return p
    for f in brief.get("_files") or []:
        if f.get("kind") == "image" and re.search(r"\blogo", f"{f.get('name', '')} {f.get('what', '')}", re.I) \
                and os.path.isfile(f.get("path", "")):
            return f["path"]
    return None


def client_sheet(session, visuals, out_dir):
    """Exactly one landscape A4 page: up to two generated render options (A, B) plus the dimensioned concept GA,
    so the client sees what it looks like AND what size it is. Never past SDI work for other clients."""
    brief = session.get("brief") or {}
    forbidden = _reference_paths(session)
    known = {os.path.normcase(os.path.abspath(v.get("path", ""))) for v in session.get("visuals", [])
             if v.get("kind") in ("render", "technical")}
    selected = {}
    for visual in visuals or []:
        path = os.path.normcase(os.path.abspath(str((visual or {}).get("path") or "")))
        kind = (visual or {}).get("kind")
        if kind not in ("render", "technical") or path in forbidden or path not in known or not os.path.isfile(path):
            continue
        if kind == "technical":
            selected["GA"] = visual
            continue
        label = str(visual.get("label") or "A").upper()
        if label not in {"A", "B"}:
            label = "A" if "A" not in selected else "B"
        selected[label] = visual
    if not selected:
        raise ValueError("A concept render or GA is required before making a client sheet.")
    options = sorted((k, v) for k, v in selected.items() if k != "GA")[:2] + ([("GA", selected["GA"])] if "GA" in selected else [])
    client = _client_text(brief.get("client") or "Client concept", session)
    unit = _client_text(brief.get("unit_type") or "Display concept", session)
    title = f"{client} | {unit}"
    path = _safe_output(out_dir, f"Concept_{_slug(client)}_{_slug(session.get('id'))}_{len(options)}.pdf")
    width, height = landscape(A4)
    c = canvas.Canvas(path, pagesize=(width,height))
    c.setTitle(title)
    c.setAuthor("SDI Displays")
    c.setStrokeColor(RED)
    c.setLineWidth(2)
    c.line(14*mm, height-18*mm, width-14*mm, height-18*mm)
    if os.path.isfile(LOGO):
        c.drawImage(LOGO, width-42*mm, height-15*mm, width=28*mm, height=10*mm, preserveAspectRatio=True, mask="auto")
    clogo = _client_logo(session)
    tx = 14*mm
    if clogo:      # the client's own logo, top left - it's their pack
        try:
            c.drawImage(clogo, 14*mm, height-41*mm, width=34*mm, height=18*mm, preserveAspectRatio=True, mask="auto")
            tx = 52*mm
        except Exception:
            pass
    _flow(c, [_p(title, H1, 250)], tx, height-24*mm, width-tx-14*mm, 17*mm)
    spec = [re.sub(r"\s*\((assumed|as assumed)[^)]*\)", "", _client_text(brief.get(key), session), flags=re.I)   # internal notes stay internal
            for key in ("size", "materials", "colours_graphics", "placement") if not _missing(brief.get(key))]
    _flow(c, [_p(" | ".join(spec), SMALL, 900)], 14*mm, height-43*mm, width-28*mm, 15*mm)
    gap = 6*mm
    card_width = (width-28*mm-gap*(len(options)-1))/len(options)
    for index, (label, visual) in enumerate(options):
        x = 14*mm + index*(card_width+gap)
        one = sum(1 for k, _ in options if k != "GA") == 1     # one finalised design: "Your concept", not "Option B"
        _flow(c, [_p("CONCEPT GA - SIZES" if label == "GA" else "YOUR CONCEPT" if one else f"OPTION {label}", H2)],
              x, height-61*mm, card_width, 9*mm)
        _photo(c, visual, x, 33*mm, card_width, 103*mm, "Concept unavailable")
    _flow(c, [_p("Concept visual for discussion - final design confirmed by SDI's design team after approval.", SMALL)],
          14*mm, 25*mm, width-28*mm, 10*mm)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTE)
    c.drawString(14*mm, 9*mm, f"SDI Displays | wearesdi.com | {today():%d %B %Y}")
    c.showPage()
    c.save()
    return path


def _section(brief, fields, sections, numbers):
    story = []
    for section in sections:
        if section[:1] in numbers:
            story.extend([_p(section, H2), kv_table([(info[0], val(brief,key)) for key,info in fields.items() if info[1] == section])])
    return story


def _table(headers, rows, widths):
    return Table([[_p(h, SMALL) for h in headers]] + [[_p(v, SMALL, 350) for v in row] for row in rows],
                 colWidths=[v*mm for v in widths], style=TableStyle([
                     ("BACKGROUND",(0,0),(-1,0),SOFT),("GRID",(0,0),(-1,-1),0.3,LINE),
                     ("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),5),
                     ("BOTTOMPADDING",(0,0),(-1,-1),5)]))


def build(session, fields, sections, out_dir):
    brief, refs, visuals = session.get("brief") or {}, session.get("refs") or [], session.get("visuals") or []
    title = f"{brief.get('project_name') or brief.get('unit_type') or 'Project brief'} | {brief.get('client') or 'Client to confirm'}"
    path = _safe_output(out_dir, f"Brief_{_slug(brief.get('client'))}_{_slug(session.get('id'))}.pdf")
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(title)
    c.setAuthor("SDI Displays")
    page_width, page_height = A4
    top, body_height = page_height-26*mm, 250*mm
    assumptions = ["Concept images and GA are for discussion only; SDI's studio must validate the design before manufacture.",
                   "Planning durations are configurable assumptions, not booked studio, factory or transport capacity."]
    actions = ["Confirm outstanding answers with the account manager and client; arrange studio and estimating review."]
    def page(number, heading, story):
        header_footer(c, type("Page", (), {"page":number})(), title)
        _flow(c, [_p(heading, H1)]+story, 18*mm, top, 174*mm, body_height)
        c.showPage()
    # Sections are deliberately placed on fixed pages rather than allowing the
    # flowing tables to move the cost/loading pages beyond the promised 8 pages.
    glance = [("Client", val(brief,"client")), ("Unit", val(brief,"unit_type")),
              ("H x W x D", val(brief,"size")), ("In store", val(brief,"instore_date")),
              ("Volume / region", f"{val(brief,'volume_qty')} / {val(brief,'region')}")]
    page(1, "Project brief", [_p(title, H2), _p("Briefing date: " + str(brief.get("briefing_date") or "Not recorded"), SMALL),
          _p("At a glance", H2),kv_table(glance,45)] + _section(brief,fields,sections,{"1"}) +
         [_p("Customer requirement",H2),_p(brief.get("narrative") or requirement_from(brief),limit=2200)])
    project_story = _section(brief,fields,sections,{"2"})
    hours = []
    for key,label in (("creative_chargeable","Creative"),("technical_chargeable","Technical")):
        budget = money(brief.get(key))
        hours.append((label+" hours allocated", f"{math.ceil(budget/RATE_GBP)} hours (GBP{budget:,.2f} / GBP75, rounded up)" if budget is not None else "Budget not given; hours not allocated"))
    project_story.extend([_p("Design allocation",H2),kv_table(hours)])
    # 3 Nov 2026 (demo check): a Tesco coal bunker brief listed Lindt and a goalpost as 'similar', each '? to ?'. Only the
    # job the AM chose and past jobs whose name shares a word with this unit; years written plainly.
    want = set(re.findall(r"[a-z]{4,}", f"{brief.get('unit_type') or ''} {brief.get('liked_job') or ''}".lower())) - {
        "unit", "units", "display", "free", "standing", "freestanding", "closely", "asked", "follow"}
    chosen = str(brief.get("_ref_job") or "")
    refs = [r for r in refs if str(r.get("job_no")) == chosen] + [
        r for r in refs if str(r.get("job_no")) != chosen and want & set(re.findall(r"[a-z]{4,}", (r.get("name") or "").lower()))]
    def years(ref):
        a, b = str(ref.get("first") or ref.get("first_date") or "")[:4], str(ref.get("last") or ref.get("last_date") or "")[:4]
        return f"{a}-{b}" if a and b and a != b else (b or a or "date not recorded")
    project_story.extend([_p("Similar SDI work",H2)] + [_p(short_name(ref)+f" | {ref.get('n_drawings') or 'Unknown'} drawings | {years(ref)}"
                                                        + (" | the one this brief follows" if str(ref.get("job_no")) == chosen else ""), SMALL)
                                                     for ref in refs[:4]])
    if not refs:
        project_story.append(_p("No past projects selected yet.",SMALL))
    page(2,"Project scope & design allocation",project_story)
    page(3,"Main brief & estimating",_section(brief,fields,sections,{"3","4","5"}))
    hwd = parse_size(brief.get("size"))
    box, packing_rule = packed_size(hwd,brief.get("assembled")) if hwd else (None,"Complete height, width and depth not supplied; loading cannot be calculated.")
    header_footer(c,type("Page",(),{"page":4})(),title)
    _flow(c,[_p("Initial design & technical response",H1)],18*mm,top,174*mm,15*mm)
    for kind,y,label in (("render",151,"3D concept visual"),("technical",59,"Technical concept GA - NOT FOR MANUFACTURE")):
        # the option the AM finalised (and its GA) - not just whatever was drawn last (27 Oct 2026: Option D was the
        # chosen one but the internal pack showed an older render and GA)
        pick = brief.get("chosen_option")
        visual = (next((v for v in reversed(visuals) if v.get("kind")==kind and pick and
                        (v.get("label")==pick if kind=="render" else v.get("from_option")==pick)),None)
                  or next((v for v in reversed(visuals) if v.get("kind")==kind),None))
        _flow(c,[_p(label,H2)],18*mm,(y+83)*mm,174*mm,10*mm)
        _photo(c,visual,18*mm,y*mm,174*mm,74*mm,"Not generated yet - request this view in the chat.")
    method = brief.get("method_of_manufacture") or "Not confirmed; studio to establish joinery / fabrication method"
    _flow(c,[_p(f"Overall: {val(brief,'size')} | Materials: {val(brief,'materials')}",SMALL),
             _p(f"Method: {method}",SMALL),_p(packing_rule,SMALL)],18*mm,53*mm,174*mm,31*mm)
    c.showPage()
    comparisons = comparable_estimates(brief,refs)
    eligible = [row["unit"] for row in comparisons if row["scope"]=="whole unit"]
    cost_story = [_p("Indicative, from history - not a quote",H2),
                  _p("Figures below are historical internal unit costs, not client selling prices. Component and unconfirmed scopes are excluded from the whole-unit range.",SMALL)]
    if eligible:
        cost_story.append(_p(f"GBP{min(eligible):,.2f} / GBP{statistics.median(eligible):,.2f} / GBP{max(eligible):,.2f}",BIG))
        cost_story.append(_p("Minimum / median / maximum confirmed whole-unit cost",SMALL))
    else:
        cost_story.append(_p("Whole-unit range unavailable: no comparable estimate is confirmed as a complete unit.",P))
        actions.append("Estimating must confirm which historical rows cover whole units before giving a cost range.")
    if comparisons:
        cost_story.append(_table(["Job / date","Historical description / scope","Qty","Unit cost"],
             [[f"{r['job']} / {r['date']}",f"{r['what']} / {r['scope']}",r['qty'] if r['qty'] is not None else "?",f"GBP{r['unit']:,.2f}"] for r in comparisons],[31,91,16,36]))
    else:
        cost_story.append(_p("No usable estimates attached to the retrieved closest jobs."))
    # How long similar jobs took the studio: design days Jono booked per team, drawings produced, who did them
    names = {"design_2d": "2D creative", "3d": "3D", "design_3d": "3D", "technical": "technical"}
    rows = []
    for r in refs[:6]:
        days = r.get("design_days") or {}
        dtxt = ", ".join(f"{names.get(k, k)} {v}d" for k, v in days.items()) if isinstance(days, dict) else ""
        who = ", ".join((r.get("designers") or [])[:3])
        rows.append([f"{r['job_no']} {re.sub(r'^' + re.escape(str(r['job_no'])) + r'[ -]*', '', str(r['name']))[:34]}", (r.get("last") or r.get("first") or "")[:4] or "-",
                     str(r.get("n_drawings") or "-"), dtxt or "no booking found", who or "-"])
    if rows:
        cost_story += [_p("How long similar jobs took",H2),
                       _p("Studio days are what Jono booked in his calendar for that job (one booking = the days it spans); drawings are SolidWorks sheets on W:.",SMALL),
                       _table(["Past job","Year","Dwgs","Studio time booked","People"],rows,[56,12,12,52,42])]
    target = money(brief.get("target_unit_cost"))
    cost_story += [_p("Client target",H2),_p(f"GBP{target:,.2f} per unit. Target selling price and historical internal cost are different bases; estimating must assess margin and scope." if target is not None else "Not given.")]
    load_rows = []
    for name,L,W,H,freight,note in LOADS:
        count,orient = fit((L,W,H),box) if box else (0,None)
        load_rows.append({"name":name,"inside":(L,W,H),"units":count,"orient":orient,"freight":freight,"note":note})
    cost_story += [_p("Delivery per unit by region",H2),
        _p("UK historical benchmark: GBP1,170 per 33-pallet artic (GBP35.45 per pallet). Units per pallet, route, restrictions and current rate need confirmation; no per-unit delivery quote is inferred.",SMALL),
        _p("Europe / China: current freight quotations required. No invented container freight price is used.",SMALL)]
    page(5,"Historical cost comparison",cost_story)
    loading = [_p(packing_rule),_p("Geometric ceiling only: all rotations and stacking are allowed in this calculation. Real capacity must allow pallets, doors, weight limits, access, load restraint and fragility.",SMALL)]
    if box:
        loading.append(_table(["Equipment","Inside L x W x H (mm)","Max. boxes","Freight / unit"],
                      [[r['name']," x ".join(str(v) for v in r['inside']),r['units'],"Not confirmed"] for r in load_rows],[40,65,27,42]))
        preferred = max(load_rows[1:] if "china" in str(brief.get("region") or "").lower() else load_rows[:1],key=lambda r:r['units'])
        if preferred['units']:
            loading += [_p(f"Illustrative loading - {preferred['name']} ({preferred['units']} boxes)",H2),iso_loading(preferred['inside'],preferred['orient'],preferred['units']),
                        _p("Drawing shows up to 400 boxes. This is a spatial illustration, not a transport loading instruction.",SMALL)]
        assumptions.append(packing_rule)
        assumptions.append("Equipment internal dimensions are planning examples; capacity permits unrestricted rotation and stacking. Palletisation and weight are not included.")
        actions.append("Confirm packed carton, upright-only constraints, stackability, unit weight and carrier dimensions before booking transport.")
    else:
        actions.append("Obtain complete H x W x D and packed dimensions for loading calculations.")
    page(6,"Container & wagon loading",loading)
    stages,issues,weeks,due = timeline(brief)
    timing = [_p((f"Planned backwards from {due:%d %B %Y}" if due else "Indicative forward planning scenario") + f" | approximately {weeks:.1f} calendar weeks",H2),
              _p("Durations are planning assumptions. Working stages use Monday-Friday, excluding public-holiday allowances; full technical is 3 working days after GA. China sea freight uses 42 calendar days.",SMALL),
              _table(["Stage","Start","Finish"],[[name,f"{start:%d %b %Y}",f"{end:%d %b %Y}"] for name,start,end in stages],[84,45,45]),
              _p("Delivery challenges",H2)] + [_p(issue,SMALL) for issue in issues]
    if not issues:
        timing.append(_p("No conflict detected against this assumed route; confirm live capacity before committing.",SMALL))
    page(7,"Project delivery challenges",timing)
    assumptions.append("Default stage durations (working weeks, except sea): "+", ".join(f"{key} {value:g}" for key,value in STAGES.items())+".")
    missing = [info[0] for key,info in fields.items() if _missing(brief.get(key))]
    ending = [_p("Assumptions to validate",H2)] + [_p("- "+item,SMALL) for item in assumptions]
    ending += [_p("Actions",H2)] + [_p("- "+item,SMALL) for item in actions]
    ask_client = [info[0] for key,info in fields.items() if _missing(brief.get(key)) and key in CLIENT_ASKS]
    if ask_client:
        ending += [_p("Still to confirm (AM / PM)",H2),
                   _p("Gaps that hold up design and estimating. Check your meeting notes first; ask the client only for what you can't answer:",SMALL)]
        ending += [_p(f"{n}. {CLIENT_ASKS[key]}",SMALL) for n,key in enumerate([k for k in CLIENT_ASKS if _missing(brief.get(k))],1)]
    ending += [_p("Every unanswered question",H2),_p(" | ".join(missing) if missing else "All template questions have recorded answers.",SMALL,0),
               _p("All full-length answers and export metadata are preserved in the companion JSON.",SMALL)]
    page(8,"Assumptions & actions",ending)
    c.save()
    payload = {"schema_version":"sdi.brief-opportunity.v1","title":title,
       "briefed":brief.get("briefing_date"),"exported_at":datetime.now(ZoneInfo("Europe/London")).isoformat(),
       "fields":{**{key:brief.get(key) for key in fields},**brief},
       "opportunity":{"external_id":str(session.get("id")),"name":brief.get("project_name") or brief.get("unit_type"),
           "client":brief.get("client"),"account_manager":brief.get("account_manager") or session.get("name"),
           "briefing_date":brief.get("briefing_date"),"target_instore_date":brief.get("instore_date"),
           "status":session.get("status") or "open","converted_to_job":session.get("converted_to_job"),
           "job_number":session.get("job_no"),"value_estimate":session.get("value_estimate"),"currency":"GBP"},
       "sage_mapping_status":"Field mapping requires confirmation against the target Sage CRM schema; this file has not been imported.",
       "similar_jobs":[ref.get("job_no") for ref in refs],"historical_estimates":comparisons,
       "visuals":[v.get("path") for v in visuals],"unanswered_questions":missing,
       "assumptions":assumptions,"actions":actions}
    with open(path[:-4]+".json","w",encoding="utf-8") as output:
        json.dump(payload,output,indent=2,ensure_ascii=False,default=str)
    return path
