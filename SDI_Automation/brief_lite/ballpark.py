"""ballpark.py - an internal guide price per unit, worked out in the open from SDI's own past quotes (21 Nov 2026).

Matt (18 Nov): "Can you bring some budget pricing into this, or do you not have that capability yet?" - Sid said no,
yet SDI Live already had SDI's past quotes for the closest jobs and the design director had written a band from them.
This makes that figure something the AM can ask for and see the workings of. It is NEVER a quote: internal only,
labelled so everywhere, and the client sheet never carries it. Estimate Lite (the estimating engine, priced part by
part) is the next step up when they need a real number.

HOW IT'S WORKED OUT
  1. The past jobs SDI Live matched to this brief (same client / kind of unit / look), with a whole-unit quote in the
     estimates on K: (knowledge.db) - never a part's quote (a header, a shelf).
  2. Each quote brought to today's money at INFLATION a year from its date.
  3. If the AM asked for a different quantity, each moved along a volume curve: unit cost x (quoted qty / new qty)^VOLUME
     - the setup shared over more units (0.12: ten times the quantity is ~24% cheaper a unit).
  4. The band: the middle of those (the median), +/- SPREAD, wider when there's only one quote or they disagree.
  5. If the design director wrote a band for the option on screen (it reasons from the same quotes and the design's
     extras - lighting, joinery, bigger size), that band is shown too, as the director's reading.
Confidence: high = 3+ quotes that agree within 25%; medium = 2, or 3+ that spread; low = 1.
"""
import re
import statistics
from datetime import date

INFLATION = 0.04      # a year, from the quote's date to today
VOLUME = 0.12         # unit cost ~ qty ** -VOLUME
SPREAD = 0.15         # either side of the middle


def _year(d):
    m = re.match(r"\s*(\d{4})", str(d or ""))
    return int(m.group(1)) if m else None


def _qty(v):
    m = re.search(r"\d[\d,]*", str(v or ""))
    return int(m.group(0).replace(",", "")) if m else None


def work_out(quotes, brief_qty=None, director_band="", today=None):
    """quotes: [{'job', 'name', 'unit_cost', 'qty', 'date'}] (whole-unit quotes). -> the ballpark, or None with none."""
    today = today or date.today()
    used = []
    for q in quotes:
        cost = float(q.get("unit_cost") or 0)
        if cost <= 0:
            continue
        yr = _year(q.get("date"))
        years = max(0, today.year - yr) if yr else 0
        now = cost * (1 + INFLATION) ** years
        qq = _qty(q.get("qty"))
        if brief_qty and qq and brief_qty != qq:
            now *= (qq / brief_qty) ** VOLUME
        used.append({**q, "today": round(now, 2), "years": years, "qty": qq})
    if not used:
        return None
    vals = [u["today"] for u in used]
    mid = statistics.median(vals)
    spread_ = SPREAD
    agree = (max(vals) - min(vals)) / mid <= 0.25 if len(vals) > 1 else False
    if len(vals) == 1:
        spread_, conf = 0.25, "low - one past quote to go on"
    elif len(vals) >= 3 and agree:
        conf = f"high - {len(vals)} past quotes that agree"
    else:
        spread_, conf = 0.20, f"medium - {len(vals)} past quote{'s' if len(vals) != 1 else ''}" + ("" if agree else " that differ")
    lo, hi = mid * (1 - spread_), mid * (1 + spread_)
    rnd = (lambda v: int(round(v / 10.0)) * 10) if mid >= 100 else (lambda v: int(round(v)))
    return {"low": rnd(lo), "high": rnd(hi), "middle": rnd(mid), "qty": brief_qty, "confidence": conf,
            "basis": used, "director": (director_band or "").strip(),
            "method": (f"{len(used)} past SDI quote{'s' if len(used) != 1 else ''}, brought to today at "
                       f"{int(INFLATION * 100)}% a year" + (f", moved to {brief_qty} units" if brief_qty else "")
                       + f"; middle +/- {int(spread_ * 100)}%.")}


def say(bp):
    """One line for Sid / the chat."""
    q = f" at {bp['qty']} units" if bp.get("qty") else ""
    first = bp["basis"][0]
    return (f"As an internal guide only - not for the client - about £{bp['low']:,}-£{bp['high']:,} a unit{q}, from "
            f"{len(bp['basis'])} past SDI quote{'s' if len(bp['basis']) != 1 else ''} (closest: {first['job']} at "
            f"£{float(first['unit_cost']):,.0f} a unit{(' for ' + str(first['qty'])) if first.get('qty') else ''}). "
            f"Confidence: {bp['confidence'].split(' - ')[0]}.")


# ── the quick estimate: the closest past job's estimate, adjusted to suit (21 Nov 2026) ─────────────────────────────
# James: "two options - one ... for a more accurate estimate [Estimate Lite, 5-15 minutes]. The second one is the look
# up to old jobs which are similar in the K: / W: and modifies to suit." Here a model only SAYS what differs and by
# how much (each adjustment with its reason); the sums are done in this file, from the past job's own figures:
#     per unit now  = the base job's quote brought to today (as above) + the adjustments, at the base job's quantity
#     at each qty   = that x (base qty / qty) ** VOLUME
# Adjustments that would take it below 40% or above 250% of the base are not believed: confidence drops to low and it
# says so.

ADJUST = """You are an SDI Displays estimator. A new display has been briefed; the closest past SDI jobs and their
estimates are below. Pick the ONE past job closest to the new unit as the base, then list what's different about the
new unit and what each difference adds to or takes off the PER-UNIT cost at the base job's quantity, in GBP - size,
materials, finish, lighting, shelves, header, graphics, assembly, anything in the brief. Only real differences; no
padding. Say each one plainly ("LED shelf lighting, 4 shelves: +£85 - LED strip, driver and wiring per shelf").

THE NEW UNIT:
{brief}

PAST SDI JOBS (each quote per unit at its quantity, already brought to today's money; material / labour split and
what the estimate lists where known):
{quotes}

Answer with JSON only:
{{"base_job": "<job number from the list>", "adjustments": [{{"what": "...", "gbp": <number, + or ->, "why": "..."}}],
 "assumptions": ["..."]}}"""


def _brief_lines(brief):
    keys = ("client", "unit_type", "size", "materials", "finish", "colours_graphics", "lighting", "products_held",
            "shelf_load", "placement", "fixing", "assembled", "volume_qty", "other_notes")
    return "\n".join(f"- {k}: {' '.join(str(brief[k]).split())}" for k in keys if brief.get(k))


def quick(brief, quotes, ask, brief_qty=None, today=None):
    """-> the quick estimate {base, adjustments, unit_gbp, prices, confidence, assumptions, band}, or None (no quotes)."""
    band = work_out(quotes, None, "", today)
    if not band:
        return None
    by_job = {str(u["job"]): u for u in band["basis"]}
    lines = []
    for u in band["basis"]:
        extra = []
        if u.get("material_cost") or u.get("labour_cost"):
            extra.append(f"materials £{float(u.get('material_cost') or 0):,.0f} / labour £{float(u.get('labour_cost') or 0):,.0f}")
        for k in ("materials", "processes"):
            if u.get(k):
                extra.append(f"{k}: {' '.join(str(u[k]).split())[:300]}")
        lines.append(f"- {u['job']} {u.get('name', '')}: £{u['today']:,.0f} a unit today at qty {u.get('qty') or 1}"
                     + (f" ({'; '.join(extra)})" if extra else ""))
    try:
        import json as _json
        raw = ask(ADJUST.format(brief=_brief_lines(brief), quotes="\n".join(lines)))
        m = re.search(r"\{.*\}", raw or "", re.S)
        got = _json.loads(m.group(0)) if m else {}
    except Exception:                                                     # noqa: BLE001
        got = {}
    base = by_job.get(str(got.get("base_job") or "")) or band["basis"][0]
    adj = []
    for a in got.get("adjustments") or []:
        try:
            g = round(float(a.get("gbp")), 2)
        except (TypeError, ValueError):
            continue
        if a.get("what"):
            adj.append({"what": str(a["what"])[:120], "gbp": g, "why": str(a.get("why") or "")[:200]})
    base_q = base.get("qty") or 1
    unit = round(base["today"] + sum(a["gbp"] for a in adj), 2)
    conf = "medium - one past job adjusted" if adj else "low - the past job as it was, nothing adjusted"
    if unit < 0.4 * base["today"] or unit > 2.5 * base["today"]:
        conf = "low - the adjustments move it a long way from the past job; check it"
    if not got:
        conf = "low - the adjustment couldn't be worked out; this is the closest past job brought to today"
    qtys = sorted({1, 10} | ({brief_qty} if brief_qty else set()) | {base_q})
    prices = [{"qty": q, "unit_gbp": round(max(0.0, unit) * (base_q / q) ** VOLUME, 2)} for q in qtys]
    return {"base": {"job": base["job"], "name": base.get("name", ""), "quoted": float(base["unit_cost"]), "qty": base_q,
                     "date": base.get("date"), "today": base["today"]},
            "adjustments": adj, "unit_gbp": unit, "prices": prices, "confidence": conf,
            "assumptions": [str(x)[:160] for x in (got.get("assumptions") or [])][:5],
            "band": {"low": band["low"], "high": band["high"], "n": len(band["basis"])}}


def say_quick(q):
    at = next((p for p in q["prices"] if p["qty"] == q["base"]["qty"]), q["prices"][0])
    return (f"Quick estimate - internal, not for the client: about £{at['unit_gbp']:,.0f} a unit at {at['qty']}, from SDI's "
            f"{q['base']['job']} (£{q['base']['quoted']:,.0f} a unit) adjusted for {len(q['adjustments'])} difference"
            f"{'s' if len(q['adjustments']) != 1 else ''}. Confidence: {q['confidence'].split(' - ')[0]}. For the engine's "
            "priced estimate, ask for Estimate Lite (5-15 minutes).")
