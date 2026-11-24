"""ai_estimate.py - the AI estimate: a frontier model costs the design on screen line by line (21 Nov 2026).

James: "can we do a third option - an LLM lookup ... through this frontier llm model?" The three, fastest first:
    quick estimate   seconds   SDI's closest past job's own estimate, adjusted to suit           (ballpark.py)
    AI estimate      ~30-60 s  a frontier model costs the render and brief part by part          (this file)
    Estimate Lite    5-15 min  SDI's estimating engine prices it                                 (estimate_lite.py)

The model (SDI Live's best, the design director's) sees the render and the brief, with SDI's past quotes for the
closest jobs as a yardstick, and lists:
    per-unit lines   materials (part, material, how much), labour (process, minutes), bought-in (LEDs, castors...)
    one-off setup    design-for-manufacture, programming, jigs, tooling, first-off - paid once whatever the quantity
The sums are done here, not by the model:
    unit cost at q = sum(per-unit lines) + sum(setup) / q
A total that lands below 40% or above 250% of the closest past quote is flagged low confidence. Internal only - never
for the client, never a quote.

24 Nov 2026 (James: "get the estimating right"): SDI's own figures, once checked, live in
studio_data\estimate_norms.json (estimate_check.py proposes them from the estimate sheets on K: and a test on past
jobs). When it's there: the model is given SDI's hourly rates and SDI's usual setup for this kind of unit; a setup far
above SDI's usual is brought back to it; and the total is corrected by what the check measured for this kind of unit.
Without the file nothing changes.
"""
import base64
import json
import os
import re

PROMPT = """You are a senior estimator at SDI Displays, a UK designer and manufacturer of retail display units (metal,
timber, acrylic, print, LED). Cost the unit in the picture, as briefed below, the way an SDI estimator would: every part
and its material, every process and its time, every bought-in item - at UK 2026 costs (materials at trade prices; shop
labour about £{shop} an hour, assembly about £{assembly}, design / CAD about £{design}). Cost, not a selling price.{setup_note}

THE BRIEF:
{brief}

SDI'S PAST QUOTES FOR THE CLOSEST JOBS (per unit, today's money) - a yardstick, not a copy:
{quotes}

List PER-UNIT lines (each unit needs them every time) and ONE-OFF SETUP (paid once for the order: drawings for
manufacture, CNC / laser programming, jigs, tooling, first-off sample). Be specific ("1.2 mm mild steel, laser cut and
folded, 2 sides 1500 x 500", not "metalwork"). Say what you assumed.

Answer with JSON only:
{{"per_unit": [{{"group": "materials|labour|bought-in|finish|packing", "what": "...", "gbp": <number>}}],
 "setup": [{{"what": "...", "gbp": <number>}}],
 "assumptions": ["..."], "biggest_risk": "..."}}"""

GROUPS = ("materials", "labour", "bought-in", "finish", "packing")
RATES = {"shop": 45, "assembly": 35, "design": 75}          # until SDI's own are in estimate_norms.json
NORMS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "studio_data", "estimate_norms.json")
KINDS = [("fsdu", r"\bfsdu|floor ?stand|free ?standing"), ("gondola", r"gondola"), ("wall bay", r"\bwall|\bbays?\b"),
         ("counter", r"counter|ctu|cdu|countertop"), ("plinth", r"plinth"), ("totem", r"totem"),
         ("kiosk / pod", r"kiosk|\bpods?\b"), ("cabinet", r"cabinet"), ("dump bin", r"\bbin\b|dump"),
         ("table", r"\btable"), ("end", r"\bend\b|end ?cap")]


def kind_of(text):
    """The kind of unit, as estimate_check.py groups SDI's past estimates: fsdu, gondola, wall bay, counter... or other."""
    d = (text or "").lower()
    return next((k for k, pat in KINDS if re.search(pat, d)), "other")


def load_norms(path=NORMS):
    """SDI's checked figures (rates, usual setup by kind, measured correction) or {} - read each time, so a new file
    takes effect without a restart."""
    try:
        with open(path, encoding="utf-8") as fh:
            j = json.load(fh)
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def _setup_norm(norms, kind):
    v = ((norms or {}).get("setup_by_kind") or {}).get(kind) or {}
    return v if v.get("median_gbp") and v.get("high_gbp") and (v.get("n") or 0) >= 3 else None


def _correction(norms, kind):
    c = ((norms or {}).get("ai_correction_by_kind") or {}).get(kind) or (norms or {}).get("ai_correction_all")
    try:
        c = float(c)
    except (TypeError, ValueError):
        return None
    return c if 0.4 <= c <= 2.5 and abs(c - 1) >= 0.05 else None


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def brief_text(brief):
    keys = ("client", "unit_type", "size", "materials", "finish", "colours_graphics", "lighting", "products_held",
            "shelf_load", "placement", "fixing", "assembled", "delivery_packing", "volume_qty", "other_notes")
    return "\n".join(f"- {k}: {' '.join(str(brief[k]).split())}" for k in keys if brief.get(k)) or "- (little given)"


def work_out(got, brief_qty=None, yardstick=None, norms=None, kind="other"):
    """The model's lines -> the estimate, summed here. None when it gave no lines. norms: SDI's checked figures
    (load_norms) - a setup far above SDI's usual for this kind is brought back to it, and the measured correction for
    this kind is applied to the totals, both said in the assumptions."""
    per = []
    for x in (got or {}).get("per_unit") or []:
        g = _num((x or {}).get("gbp"))
        if g is not None and g >= 0 and x.get("what"):
            grp = str(x.get("group") or "materials").lower()
            per.append({"group": grp if grp in GROUPS else "materials", "what": str(x["what"])[:140], "gbp": g})
    setup = []
    for x in (got or {}).get("setup") or []:
        g = _num((x or {}).get("gbp"))
        if g is not None and g >= 0 and x.get("what"):
            setup.append({"what": str(x["what"])[:140], "gbp": g})
    if not per:
        return None
    notes = []
    sn = _setup_norm(norms, kind)
    raw_setup = sum(x["gbp"] for x in setup)
    if sn and raw_setup > 1.5 * sn["high_gbp"]:                # 24 Nov 2026: the AI's setup jumped about (£5.7k-£8.8k)
        k = sn["high_gbp"] / raw_setup
        setup = [dict(x, gbp=round(x["gbp"] * k, 2)) for x in setup]
        notes.append(f"setup brought down from £{raw_setup:,.0f} to £{sn['high_gbp']:,.0f}, the top of SDI's usual for a "
                     f"{kind} ({sn['n']} past jobs)")
    corr = _correction(norms, kind)
    if corr:
        per = [dict(x, gbp=round(x["gbp"] * corr, 2)) for x in per]
        setup = [dict(x, gbp=round(x["gbp"] * corr, 2)) for x in setup]
        notes.append(f"adjusted x{corr:.2f}: on past SDI jobs the AI estimate ran "
                     f"{'high' if corr < 1 else 'low'} by about {abs(1 / corr - 1) * 100:.0f}%")
    unit_var = round(sum(x["gbp"] for x in per), 2)
    one_off = round(sum(x["gbp"] for x in setup), 2)
    qtys = sorted({1, 10} | ({brief_qty} if brief_qty else set()))
    prices = [{"qty": q, "unit_gbp": round(unit_var + one_off / q, 2)} for q in qtys]
    split = {g: round(sum(x["gbp"] for x in per if x["group"] == g), 2) for g in GROUPS}
    conf = "medium - costed line by line by the model, checked against SDI's past quotes" if yardstick else \
        "low - costed line by line by the model; no past SDI quote to check it against"
    if yardstick:
        at = next((p["unit_gbp"] for p in prices if p["qty"] == (yardstick.get("qty") or 1)), prices[0]["unit_gbp"])
        if at < 0.4 * yardstick["today"] or at > 2.5 * yardstick["today"]:
            conf = (f"low - a long way from SDI's {yardstick['job']} (£{yardstick['today']:,.0f} a unit today); check "
                    "which is nearer")
    return {"per_unit": per, "setup": setup, "unit_variable": unit_var, "setup_total": one_off, "prices": prices,
            "split": {k: v for k, v in split.items() if v}, "confidence": conf,
            "assumptions": notes + [str(a)[:160] for a in (got.get("assumptions") or [])][:6], "kind": kind,
            "calibrated": bool(notes),
            "risk": str(got.get("biggest_risk") or "")[:200], "yardstick": yardstick}


def estimate(brief, image_path, quotes_today, ask, brief_qty=None, norms=None):
    """quotes_today: [{'job', 'name', 'today', 'qty'}]. ask(prompt, image_b64) -> the model's text.
    norms: SDI's checked figures; None reads studio_data\\estimate_norms.json, {} uses none."""
    norms = load_norms() if norms is None else norms
    kind = kind_of(" ".join(str(brief.get(k) or "") for k in ("unit_type", "other_notes")))
    rates = dict(RATES, **{k: v for k, v in ((norms.get("rates") or {}).items()) if k in RATES and isinstance(v, (int, float))})
    sn = _setup_norm(norms, kind)
    setup_note = (f"\nSDI's own one-off setup for a {kind} is usually about £{sn['median_gbp']:,.0f} for the whole order "
                  f"(rarely over £{sn['high_gbp']:,.0f}) - only go above that for something really new to make.") if sn else ""
    qs = "\n".join(f"- {q['job']} {q.get('name', '')}: £{q['today']:,.0f} a unit at qty {q.get('qty') or 1}"
                   for q in quotes_today[:5]) or "- none close enough"
    img = None
    if image_path:
        try:
            with open(image_path, "rb") as fh:
                img = base64.b64encode(fh.read()).decode("ascii")
        except OSError:
            img = None
    raw = ask(PROMPT.format(brief=brief_text(brief), quotes=qs, setup_note=setup_note,
                            shop=f"{rates['shop']:g}", assembly=f"{rates['assembly']:g}", design=f"{rates['design']:g}"), img)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
    except ValueError:
        got = {}
    return work_out(got, brief_qty, quotes_today[0] if quotes_today else None, norms, kind)


def steady(runs, qty=None):
    """24 Nov 2026 (James: "fast and accurate"): the same design costed three times at once often comes back quite
    differently, mostly in the setup. Keep the middle one by its unit price at the order quantity (its lines still add
    up), and say how far apart the three were. None when no run gave lines."""
    runs = [r for r in runs if r and r.get("prices")]
    if not runs:
        return None
    q = int(qty or 10)

    def unit(r):
        ps = sorted(r["prices"], key=lambda p: p["qty"])
        return float(next((p["unit_gbp"] for p in ps if p["qty"] == q), ps[-1]["unit_gbp"]))
    runs.sort(key=unit)
    mid = dict(runs[len(runs) // 2])
    vals = [unit(r) for r in runs]
    mid["runs"] = [round(v, 2) for v in vals]
    mid["spread_pct"] = round((max(vals) - min(vals)) / min(vals) * 100) if len(vals) > 1 and min(vals) > 0 else 0
    if len(vals) > 1:
        mid["confidence"] = mid["confidence"] + f"; {len(vals)} runs within {mid['spread_pct']}% of each other"
    return mid


def say(e):
    at = next((p for p in e["prices"] if p["qty"] == 10), e["prices"][0])
    return (f"AI estimate - internal, not for the client: a cost to make of about £{at['unit_gbp']:,.0f} a unit at {at['qty']} "
            f"(£{e['unit_variable']:,.0f} a unit to make, plus £{e['setup_total']:,.0f} one-off setup shared over the "
            f"order) - cost before margin, not a selling price. Confidence: {e['confidence'].split(' - ')[0]}.")
