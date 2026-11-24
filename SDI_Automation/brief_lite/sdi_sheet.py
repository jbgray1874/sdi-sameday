"""sdi_sheet.py - cost a unit SDI's way: SDI's own estimate sheet, its rates and its sums (24 Nov 2026).

James: "I can pass in the estimating sheet - it has all labour rates on there ... base one of your internal estimate
views on that." SDI's blank estimate workbook holds every work centre's rate per hour and set-up minutes, the steel
and wire price per tonne, laser cutting speeds by gauge, the wire gauge table and the powder price. This module:

  1. reads those from SDI's blank workbook on the server (studio_data/estimate_template.xlsx - NEVER in git: the
     repository is public and these are SDI's commercial rates);
  2. costs a bill of materials and manufacturing route (from the AI, ai_estimate.SHEET_PROMPT) with the SAME sums the
     workbook's own formulas do - so the AI only says what is in the unit and how it is made; every pound comes from
     SDI's rates and prices:
        sheet steel   parts nested on the 2500 x 1250 sheet (80 mm edge, 10 / 20 mm gaps), sheet weight at 7.85,
                      steel GBP/tonne, cost per part rounded up to the penny, 4% scrap
        laser         seconds per part = 60 / parts per sheet (load) + perimeter / speed for the gauge + internal cut
                      / speed + 1 s a hole -> parts an hour on the Laser (Metal) line
        wire          kg = length / metres per tonne; GBP per metre = wire GBP/tonne / metres per tonne; 4% scrap
        other sheet   acrylic, MDF...: sheet cost / parts per sheet, 4% scrap
        powder        both faces' area, 6 m2 a kilo, at the powder GBP/kg (the sheet adds it itself)
        labour        per unit = GBP/hour / parts an hour x quantity per unit, plus set-up minutes at GBP/hour spread
                      over the order quantity
        unit cost     (materials + labour) / (1 - rebate) / 0.93 - read off the template's own unit-cost cell
  3. writes the lines into a copy of the blank workbook (fill_workbook) - a DRAFT the estimators open, check and
     correct like one of their own; the workbook's own formulas do the sums again when it's opened.
"""
import math
import os
import re
import shutil
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), "studio_data", "estimate_template.xlsx")
SHEET_L, SHEET_W, SCRAP, DENSITY, DOWNTIME, POWDER_M2_PER_KG = 2500.0, 1250.0, 0.04, 7.85, 0.93, 6.0
ROWS = {"bom": (11, 80), "wire": (83, 90), "steel": (93, 136), "other": (139, 146), "labour": (151, 222)}


def _f(v, default=None):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def load_rates(path=TEMPLATE):
    """SDI's rates off the blank workbook -> {'ops': {name: {dept, rate, setup}}, 'steel_t', 'wire_t', 'laser': [(gauge,
    mm/s)], 'wire': [(gauge, m per tonne)], 'powder_kg'} or None when the workbook isn't there."""
    if not os.path.exists(path):
        return None
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    ws = wb["Estimate"]
    ops = {}
    for r in range(235, 267):
        name, rate, dept, setup = (ws.cell(r, c).value for c in (8, 9, 10, 11))
        if name and _f(rate):
            ops[str(name).strip()] = {"dept": str(dept or "").strip(), "rate": float(rate), "setup": _f(setup, 0.0)}
    laser = sorted((float(ws.cell(r, 25).value), float(ws.cell(r, 26).value)) for r in range(93, 135)
                   if _f(ws.cell(r, 25).value) and _f(ws.cell(r, 26).value))
    wire = sorted((float(ws.cell(r, 8).value), float(ws.cell(r, 9).value)) for r in range(271, 290)
                  if _f(ws.cell(r, 8).value) and _f(ws.cell(r, 9).value))
    rebate = _f(ws["M227"].value, 0.0) or 0.0
    wb.close()
    downtime = DOWNTIME            # the unit cost cell's own divisor: =((materials + labour)/(100%-rebate))/0.93
    try:
        wf = openpyxl.load_workbook(path, data_only=False)
        m = re.search(r"\)\s*/\s*(0?\.\d+)\s*$", str(wf["Estimate"]["M225"].value or ""))
        if m and 0.5 < float(m.group(1)) <= 1:
            downtime = float(m.group(1))
        wf.close()
    except Exception:                                          # noqa: BLE001
        pass
    out = {"ops": ops, "steel_t": _f(ws["L5"].value, 0.0), "wire_t": _f(ws["L3"].value, 0.0), "laser": laser,
           "wire": wire, "powder_kg": _f(ws["AF137"].value, 0.0), "template": path, "downtime": downtime,
           "rebate": rebate if 0 <= rebate < 0.5 else 0.0}
    return out if ops and out["steel_t"] else None


def _lookup(table, x):
    """Excel LOOKUP on a sorted table: the row with the largest key <= x (the first row when x is below them all)."""
    best = table[0][1] if table else None
    for k, v in table:
        if k <= x:
            best = v
    return best


def op_name(rates, said):
    """The SDI operation the AI meant: exact, else the closest by words ('laser metal' -> 'Laser (Metal)')."""
    ops = rates["ops"]
    if said in ops:
        return said
    low = {k.lower(): k for k in ops}
    s = str(said or "").lower().strip()
    if s in low:
        return low[s]
    sw = set(re.findall(r"[a-z0-9]+", s))
    best = max(ops, key=lambda k: len(sw & set(re.findall(r"[a-z0-9]+", k.lower()))) / max(1, len(set(re.findall(r"[a-z0-9]+", k.lower())))))
    return best if sw & set(re.findall(r"[a-z0-9]+", best.lower())) else None


def nest(length, width, sheet_l=SHEET_L, sheet_w=SHEET_W):
    """Parts per sheet as SDI's sheet nests them: INT((sheet width - 80) / (width + 10)) x INT(sheet length /
    (length + 20)) - the way the sheet does it, not turned round; only turned when it won't fit at all. 0 = too big."""
    def n(l_, w_):
        if l_ <= 0 or w_ <= 0 or w_ > sheet_w or l_ > sheet_l:
            return 0
        return int((sheet_w - 80) / (w_ + 10)) * int(sheet_l / (l_ + 20))
    return n(length, width) or n(width, length)


def steel_part(rates, p):
    """One sheet-steel part -> its cost per unit, laser parts an hour, powder kg per unit (the sheet's own sums)."""
    L, W, g, q = _f(p.get("length_mm"), 0), _f(p.get("width_mm"), 0), _f(p.get("gauge_mm"), 1.2), _f(p.get("qty"), 1)
    per_sheet = nest(L, W)
    note = ""
    sl, sw = SHEET_L, SHEET_W
    if not per_sheet:                    # bigger than a standard sheet: a 3000 x 1500, said so
        sl, sw, note = 3000.0, 1500.0, "needs a 3000 x 1500 sheet"
        per_sheet = nest(L, W, sl, sw) or 1
    sheet_kg = sl / 1000 * sw / 1000 * g * DENSITY
    per_part = math.ceil(rates["steel_t"] * sheet_kg / 1000 / per_sheet * 100) / 100
    cost = per_part * q * (1 + SCRAP)
    speed = _lookup(rates["laser"], g) or 50.0
    secs = 60.0 / per_sheet + (L + W) * 2 / speed + _f(p.get("internal_cut_mm"), 0) / speed + _f(p.get("holes"), 0)
    area = L / 1000 * W / 1000 * 2
    powder = q * area / POWDER_M2_PER_KG if p.get("powder_coat", True) else 0.0
    return {"cost": cost, "per_sheet": per_sheet, "laser_per_hour": 3600.0 / secs, "powder_kg": powder, "note": note,
            "sheet": (sl, sw)}


def wire_part(rates, p):
    g, length, q = _f(p.get("gauge_mm"), 4), _f(p.get("length_mm"), 0), _f(p.get("qty"), 1)
    m_per_t = _lookup(rates["wire"], g) or 10000.0
    price_m = rates["wire_t"] / m_per_t
    return {"cost": price_m / 1000 * length * q * (1 + SCRAP), "kg": 1 / m_per_t * length * q, "m_per_t": m_per_t,
            "price_m": price_m}


def other_part(p):
    L, W, q = _f(p.get("length_mm"), 0), _f(p.get("width_mm"), 0), _f(p.get("qty"), 1)
    sl, sw = _f(p.get("sheet_length_mm"), 2440), _f(p.get("sheet_width_mm"), 1220)

    def n(l_, w_):
        if l_ <= 0 or w_ <= 0 or l_ > sl or w_ > sw:
            return 0
        return int((sw - 5) / (w_ + 20)) * int(sl / (l_ + 20))
    per_sheet = n(L, W) or n(W, L) or 1
    return {"cost": _f(p.get("cost_per_sheet"), 0) / per_sheet * (1 + SCRAP) * q, "per_sheet": per_sheet}


def labour_line(rates, op, order_qty):
    """{operation, qty, per_hour} -> per-unit run cost, set-up cost per unit at this order quantity, hours."""
    name = op_name(rates, op.get("operation"))
    if not name:
        return None
    r = rates["ops"][name]
    q, ph = _f(op.get("qty"), 1), _f(op.get("per_hour"), 0)
    if not ph or ph <= 0:
        return None
    run = r["rate"] / ph * q
    setup_total = r["rate"] / 60 * r["setup"]
    return {"operation": name, "dept": r["dept"], "rate": r["rate"], "setup_mins": r["setup"], "run": run,
            "setup_total": setup_total, "per_unit": run + setup_total / max(1, order_qty), "qty": q, "per_hour": ph,
            "part": str(op.get("part") or "")[:60]}


def cost(rates, plan, order_qty=10):
    """The AI's bill of materials and route, costed by SDI's sums -> {material, labour, unit, lines, setup_total, ...}.
    Laser (Metal) and powder for every steel part are added here from the part's own sizes, as the sheet does."""
    order_qty = max(1, int(order_qty or 1))
    lines, mats, ops = [], 0.0, []
    powder_kg = 0.0
    for p in plan.get("sheet_parts") or []:
        c = steel_part(rates, p)
        mats += c["cost"]
        powder_kg += c["powder_kg"]
        lines.append({"group": "materials", "what": f"{p.get('description', 'part')} - {_f(p.get('gauge_mm'), 1.2):g} mm steel "
                      f"{_f(p.get('length_mm'), 0):.0f} x {_f(p.get('width_mm'), 0):.0f}, x{_f(p.get('qty'), 1):g}"
                      + (f" ({c['note']})" if c["note"] else ""), "gbp": round(c["cost"], 2), "src": p, "calc": c})
        ops.append({"operation": "Laser (Metal)", "qty": _f(p.get("qty"), 1), "per_hour": c["laser_per_hour"],
                    "part": p.get("description"), "auto": True})
    for p in plan.get("wire_parts") or []:
        c = wire_part(rates, p)
        mats += c["cost"]
        lines.append({"group": "materials", "what": f"{p.get('description', 'wire')} - {_f(p.get('gauge_mm'), 4):g} mm wire x "
                      f"{_f(p.get('length_mm'), 0):.0f} mm, x{_f(p.get('qty'), 1):g}", "gbp": round(c["cost"], 2), "src": p, "calc": c})
    for p in plan.get("other_sheet") or []:
        c = other_part(p)
        mats += c["cost"]
        lines.append({"group": "materials", "what": f"{p.get('description', 'panel')} - {p.get('material', '')} "
                      f"{_f(p.get('length_mm'), 0):.0f} x {_f(p.get('width_mm'), 0):.0f}, x{_f(p.get('qty'), 1):g} "
                      "(sheet price indicative)", "gbp": round(c["cost"], 2), "src": p, "calc": c})
    for p in plan.get("bought_in") or []:
        v = _f(p.get("price_gbp"), 0) * _f(p.get("qty"), 1) * (1 + SCRAP)
        mats += v
        lines.append({"group": "bought-in", "what": f"{p.get('description', 'item')} x{_f(p.get('qty'), 1):g} (price indicative)",
                      "gbp": round(v, 2), "src": p})
    if powder_kg and rates.get("powder_kg"):
        v = powder_kg * rates["powder_kg"]          # as the sheet's AF138: kg x GBP/kg, no scrap
        mats += v
        lines.append({"group": "finish", "what": f"Powder - {powder_kg:.2f} kg from the coated area", "gbp": round(v, 2),
                      "src": {"description": "POWDER", "qty": powder_kg, "price_gbp": rates["powder_kg"]}})
    lab, setup_total, done = 0.0, 0.0, []
    for op in ops + list(plan.get("operations") or []):
        if not op.get("auto") and op_name(rates, op.get("operation")) == "Laser (Metal)":
            continue                     # the laser is worked out from the parts themselves
        ln = labour_line(rates, op, order_qty)
        if not ln:
            continue
        lab += ln["per_unit"]
        setup_total += ln["setup_total"]
        done.append(ln)
        grp = "finish" if ln["dept"] in ("P/C", "SPRY", "DPOL") else "packing" if ln["dept"].startswith("PAC") else "labour"
        lines.append({"group": grp, "what": f"{ln['operation']} - {ln['part'] or 'unit'}: x{ln['qty']:g} at "
                      f"{ln['per_hour']:.0f} an hour", "gbp": round(ln["run"], 2), "labour": ln})
    dt, rb = rates.get("downtime") or DOWNTIME, rates.get("rebate") or 0.0
    unit = (mats + lab) / (1 - rb) / dt
    return {"material": round(mats, 2), "labour": round(lab, 2), "unit": round(unit, 2), "order_qty": order_qty,
            "lines": lines, "labour_lines": done, "setup_total": round(setup_total, 2),
            "run_per_unit": round((mats + lab - setup_total / order_qty) / (1 - rb) / dt, 2), "powder_kg": round(powder_kg, 3)}


def prices(rates, plan, qtys):
    """Unit cost at each quantity - recosted at each, so the set-up minutes are spread over that order."""
    return [{"qty": int(q), "unit_gbp": cost(rates, plan, q)["unit"]} for q in sorted(set(int(x) for x in qtys if x))]


def fill_workbook(rates, plan, out_path, header):
    """A copy of SDI's blank workbook with this unit's bill of materials and route written in - a DRAFT for the
    estimators. header: {customer, description, quantity, note}. The workbook's formulas do the sums when opened."""
    import openpyxl
    shutil.copyfile(rates["template"], out_path)
    wb = openpyxl.load_workbook(out_path)
    ws = wb["Estimate"]
    ws["D3"], ws["D4"] = str(header.get("customer") or ""), str(header.get("description") or "")[:80]
    ws["D6"], ws["D7"] = int(header.get("quantity") or 1), date.today().strftime("%d/%m/%Y")
    ws["H6"] = str(header.get("note") or "DRAFT from a concept render - SDI Live. Check every line.")
    ws["F7"] = "SDI Live (AI) - DRAFT"
    r0, r1 = ROWS["bom"]
    r = r0
    for p in (plan.get("bought_in") or [])[: r1 - r0 + 1]:
        ws.cell(r, 3, str(p.get("description") or "")[:80])
        ws.cell(r, 8, str(p.get("part_code") or "")[:30])
        ws.cell(r, 9, "SDI Live AI - INDICATIVE")
        ws.cell(r, 10, _f(p.get("price_gbp"), 0))
        ws.cell(r, 11, _f(p.get("qty"), 1))
        ws.cell(r, 12, SCRAP)
        r += 1
    done = cost(rates, plan, header.get("quantity") or 1)     # powder: the sheet adds it itself (AF138 = kg x GBP/kg)
    r0, r1 = ROWS["wire"]
    for i, p in enumerate((plan.get("wire_parts") or [])[: r1 - r0 + 1]):
        c = wire_part(rates, p)
        row = r0 + i
        ws.cell(row, 3, str(p.get("description") or "")[:80])
        ws.cell(row, 5, _f(p.get("qty"), 1))
        ws.cell(row, 6, _f(p.get("gauge_mm"), 4))
        ws.cell(row, 7, _f(p.get("length_mm"), 0))
        ws.cell(row, 9, c["m_per_t"])
    r0, r1 = ROWS["steel"]
    for i, p in enumerate((plan.get("sheet_parts") or [])[: r1 - r0 + 1]):
        row = r0 + i
        ws.cell(row, 3, str(p.get("description") or "")[:80])
        ws.cell(row, 5, _f(p.get("qty"), 1))
        ws.cell(row, 6, _f(p.get("length_mm"), 0))
        ws.cell(row, 7, _f(p.get("width_mm"), 0))
        ws.cell(row, 8, _f(p.get("gauge_mm"), 1.2))
        sl, sw = steel_part(rates, p)["sheet"]       # every row: the blank leaves some rows' sheet length empty
        ws.cell(row, 9, sl)
        ws.cell(row, 10, sw)
        ws.cell(row, 19, _f(p.get("holes"), 0))
        ws.cell(row, 20, _f(p.get("internal_cut_mm"), 0))
    r0, r1 = ROWS["other"]
    for i, p in enumerate((plan.get("other_sheet") or [])[: r1 - r0 + 1]):
        row = r0 + i
        ws.cell(row, 3, f"{p.get('description') or ''} - {p.get('material') or ''}"[:80])
        ws.cell(row, 4, _f(p.get("qty"), 1))
        ws.cell(row, 5, _f(p.get("length_mm"), 0))
        ws.cell(row, 6, _f(p.get("width_mm"), 0))
        ws.cell(row, 7, _f(p.get("thickness_mm"), 0))
        ws.cell(row, 8, _f(p.get("sheet_length_mm"), 2440))
        ws.cell(row, 9, _f(p.get("sheet_width_mm"), 1220))
        ws.cell(row, 12, _f(p.get("cost_per_sheet"), 0))
    r0, r1 = ROWS["labour"]
    for i, ln in enumerate(done["labour_lines"][: r1 - r0 + 1]):
        row = r0 + i
        ws.cell(row, 3, ln["operation"])
        ws.cell(row, 4, ln["part"])
        ws.cell(row, 8, ln["qty"])
        ws.cell(row, 9, round(ln["per_hour"], 4))
    wb.save(out_path)
    return out_path
