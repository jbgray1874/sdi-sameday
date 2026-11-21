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
