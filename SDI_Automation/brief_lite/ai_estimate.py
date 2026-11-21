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
"""
import base64
import json
import re

PROMPT = """You are a senior estimator at SDI Displays, a UK designer and manufacturer of retail display units (metal,
timber, acrylic, print, LED). Cost the unit in the picture, as briefed below, the way an SDI estimator would: every part
and its material, every process and its time, every bought-in item - at UK 2026 costs (materials at trade prices; shop
labour about £45 an hour, assembly about £35, design / CAD about £75). Cost, not a selling price.

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


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def brief_text(brief):
    keys = ("client", "unit_type", "size", "materials", "finish", "colours_graphics", "lighting", "products_held",
            "shelf_load", "placement", "fixing", "assembled", "delivery_packing", "volume_qty", "other_notes")
    return "\n".join(f"- {k}: {' '.join(str(brief[k]).split())}" for k in keys if brief.get(k)) or "- (little given)"


def work_out(got, brief_qty=None, yardstick=None):
    """The model's lines -> the estimate, summed here. None when it gave no lines."""
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
            "assumptions": [str(a)[:160] for a in (got.get("assumptions") or [])][:6],
            "risk": str(got.get("biggest_risk") or "")[:200], "yardstick": yardstick}


def estimate(brief, image_path, quotes_today, ask, brief_qty=None):
    """quotes_today: [{'job', 'name', 'today', 'qty'}]. ask(prompt, image_b64) -> the model's text."""
    qs = "\n".join(f"- {q['job']} {q.get('name', '')}: £{q['today']:,.0f} a unit at qty {q.get('qty') or 1}"
                   for q in quotes_today[:5]) or "- none close enough"
    img = None
    if image_path:
        try:
            with open(image_path, "rb") as fh:
                img = base64.b64encode(fh.read()).decode("ascii")
        except OSError:
            img = None
    raw = ask(PROMPT.format(brief=brief_text(brief), quotes=qs), img)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
    except ValueError:
        got = {}
    return work_out(got, brief_qty, quotes_today[0] if quotes_today else None)


def say(e):
    at = next((p for p in e["prices"] if p["qty"] == 10), e["prices"][0])
    return (f"AI estimate - internal, not for the client: a cost to make of about £{at['unit_gbp']:,.0f} a unit at {at['qty']} "
            f"(£{e['unit_variable']:,.0f} a unit to make, plus £{e['setup_total']:,.0f} one-off setup shared over the "
            f"order) - cost before margin, not a selling price. Confidence: {e['confidence'].split(' - ')[0]}.")
