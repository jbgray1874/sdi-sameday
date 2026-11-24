"""agreed.py - ONE figure from SDI Live's two estimates, for the client pack (24 Nov 2026).

James: "can we produce a rounded / what we deem accurate number for the client, and the internal workings / details on
the documents only internal see?" SDI Live works out two estimates for the chosen design, side by side:
    AI estimate        line by line from the render and brief (run three times, the middle one kept - ai_estimate.steady)
    past jobs estimate  SDI's closest past job's own estimate, adjusted for what's different (ballpark.quick)
The agreed figure is the two weighed together - by how close each has been to SDI's real estimate sheets when
estimate_check.py measured them (studio_data/estimate_norms.json "accuracy"), else 60 / 40 to the line-by-line one -
and less weight on either when it's shaky (the AI's three runs far apart; a past job with nothing adjusted).
    within 20% of each other   good   - the client figure stands
    20-50% apart               fair   - fine to show, worth a glance
    more than 50% apart        check  - the AM is told to look at both before it goes to the client
The client sees the agreed figure only, rounded (client_price). Everything else - both estimates, the weights, the
gap, the lines - is on the internal pricing sheet and the screen, never the client pack.
"""

DEFAULT_WEIGHTS = {"ai": 0.6, "quick": 0.4}


def at_qty(prices, q):
    """The unit price at quantity q from [{'qty', 'unit_gbp'}]: exact, else the nearest quantity below, else the first."""
    ps = sorted((p for p in prices or [] if p.get("unit_gbp")), key=lambda p: p["qty"])
    if not ps:
        return None
    exact = next((p for p in ps if p["qty"] == q), None)
    if exact:
        return float(exact["unit_gbp"])
    below = [p for p in ps if p["qty"] <= q]
    return float((below[-1] if below else ps[0])["unit_gbp"])


def weights(norms, ai, quick):
    acc = (norms or {}).get("accuracy") or {}
    try:
        w = {"ai": 1.0 / max(5.0, float(acc["ai"])), "quick": 1.0 / max(5.0, float(acc["quick"]))}
    except (KeyError, TypeError, ValueError):
        w = dict(DEFAULT_WEIGHTS)
    if (ai or {}).get("spread_pct", 0) > 30:                 # the AI's three runs didn't agree with each other
        w["ai"] *= 0.7
    if str((quick or {}).get("confidence", "")).startswith("low"):
        w["quick"] *= 0.7
    t = w["ai"] + w["quick"]
    return {k: round(v / t, 2) for k, v in w.items()}


def agree(ai, quick, qty=None, norms=None):
    """-> {'unit', 'qty', 'prices', 'ai', 'quick', 'gap_pct', 'weights', 'confidence', 'check', 'how', 'split',
    'setup_total'} or None when neither estimate was done. Prices at every quantity follow the AI's own curve (its
    setup shared over the order), moved to the agreed figure; without the AI, the past-jobs prices."""
    q = int(qty or 10)
    a = at_qty((ai or {}).get("prices"), q)
    b = at_qty((quick or {}).get("prices"), q)
    if a is None and b is None:
        return None
    if a is None or b is None:
        only = "ai" if a is not None else "quick"
        src = ai if a is not None else quick
        return {"unit": round(a if a is not None else b, 2), "qty": q, "prices": src["prices"], "ai": a, "quick": b,
                "gap_pct": None, "weights": {only: 1.0}, "check": False,
                "confidence": "fair - one estimate only" if only == "ai" else "fair - from past jobs only",
                "how": f"Only the {'AI' if only == 'ai' else 'past jobs'} estimate could be done for this design.",
                "split": (ai or {}).get("split"), "setup_total": (ai or {}).get("setup_total")}
    w = weights(norms, ai, quick)
    unit = w["ai"] * a + w["quick"] * b
    gap = abs(a - b) / min(a, b) * 100
    f = unit / a
    prices = [{"qty": p["qty"], "unit_gbp": round(float(p["unit_gbp"]) * f, 2)} for p in ai["prices"]]
    if not any(p["qty"] == q for p in prices):
        prices.append({"qty": q, "unit_gbp": round(unit, 2)})
        prices.sort(key=lambda p: p["qty"])
    if gap <= 20:
        conf, check = f"good - the two estimates agree within {gap:.0f}%", False
    elif gap <= 50:
        conf, check = f"fair - the two estimates are {gap:.0f}% apart", False
    else:
        conf, check = f"check - the two estimates are {gap:.0f}% apart; look at both before this goes to the client", True
    split = {k: round(v * f, 2) for k, v in ((ai.get("split") or {}).items())}
    return {"unit": round(unit, 2), "qty": q, "prices": prices, "ai": round(a, 2), "quick": round(b, 2),
            "gap_pct": round(gap), "weights": w, "confidence": conf, "check": check,
            "how": (f"AI estimate £{a:,.0f} and past jobs £{b:,.0f} a unit at {q:,}, weighed "
                    f"{round(w['ai'] * 100)} / {round(w['quick'] * 100)}"
                    + (" by how close each has been to SDI's own estimates" if (norms or {}).get("accuracy") else "")
                    + f" = £{unit:,.0f}."),
            "split": split, "setup_total": round(float(ai.get("setup_total") or 0) * f, 2)}


def client_price(v):
    """A price as the client sees it: rounded to what the estimate can honestly claim - £1 under £50, £5 under £200,
    £10 under £1,000, £25 above."""
    v = float(v)
    step = 1 if v < 50 else 5 if v < 200 else 10 if v < 1000 else 25
    return int(round(v / step) * step)


def say(g):
    if not g:
        return ""
    line = (f"Estimate for the pack - internal, not for the client: about £{g['unit']:,.0f} a unit to make at "
            f"{g['qty']:,} - cost before margin. ")
    if g.get("gap_pct") is None:
        return line + g["how"]
    line += f"AI £{g['ai']:,.0f}, past jobs £{g['quick']:,.0f}: {g['confidence'].split(' - ', 1)[1]}."
    if g["check"]:
        line += " Worth checking both before quoting."
    return line
