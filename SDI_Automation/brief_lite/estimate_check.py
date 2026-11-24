"""estimate_check.py - how close are SDI Live's two estimates to what SDI's estimators actually said? (24 Nov 2026)

James: "we get the estimating right to start with". This runs both of SDI Live's estimates - the AI estimate
(ai_estimate.py) and the past-jobs estimate (ballpark.quick) - on past SDI jobs whose real estimate sheet is on K:, and
compares. Each job is estimated the way SDI Live would see it: its own render from W:, its size read off its own GA,
its client, what it was and its quantity - and, as the yardstick, only OTHER jobs' quotes from BEFORE it (never its own).

It also reads SDI's own figures off the estimate sheets, at no AI cost:
  - setup: when one job was estimated at two or more quantities, unit cost = cost to make + setup / quantity, so the
    one-off setup falls out of the two prices. Grouped by kind of unit.
  - the labour section's columns and rates, and any one-off lines (tooling, jigs, programming, first-off, design).
Those are written as a PROPOSAL (estimate_norms.proposed.json) - SDI Live only uses them once copied to
studio_data\\estimate_norms.json, after they've been looked at.

Read-only on K: and W:. It does NOT use SDI Live's daily AI budget or its spend log; it has its own cap (--max-usd).
Results go to brief_lite\\out\\estimate_check\\<date-time>\\ (summary.txt to read, results.csv for the detail).

    .venv-gpu\\Scripts\\python.exe brief_lite\\estimate_check.py --jobs 40
    ... --dry       only the free part (setup and rates from the sheets), no AI calls
"""
import argparse
import base64
import csv
import io
import json
import os
import random
import re
import sqlite3
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except ImportError:
    pass

import agreed            # noqa: E402
import ai_estimate        # noqa: E402
import ballpark           # noqa: E402

CHEAP_MODEL = "claude-haiku-5-5"
CHAT_MODEL = os.environ.get("LITE_CHAT_MODEL", "claude-sonnet-5-5")             # the past-jobs estimate, as SDI Live
DIRECTOR_MODEL = os.environ.get("LITE_DIRECTOR_MODEL", "claude-opus-5-5")       # the AI estimate, as SDI Live
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}

SETUP_WORDS = re.compile(r"set ?up|tooling|\btool\b|jig|fixture|programm|first[- ]off|sample|prototype|design|drawing|"
                         r"cad|artwork|proof|cutter|die\b|mould|mold", re.I)


kind_of = ai_estimate.kind_of
RUNS = 3
OUT_DIR = None            # this run's folder: the AI's sheet for each job goes in its 'sheets' folder
SHEET_RATES = None        # SDI's rates from its blank estimate workbook - the AI estimate is then costed SDI's way


def year_of(d):
    m = re.match(r"\s*(\d{4})", str(d or ""))
    return int(m.group(1)) if m else None


def to_today(gbp, d):
    y = year_of(d)
    return gbp * (1 + ballpark.INFLATION) ** max(0, date.today().year - y) if (gbp and y) else gbp


def words(t):
    return {w for w in re.findall(r"[a-z]{3,}", (t or "").lower())} - {"the", "and", "for", "with", "unit", "display"}


# ── the estimate sheets ─────────────────────────────────────────────────────────────────────────────────────────────
def load_estimates(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    cols = ["path", "job_no", "customer", "description", "drawing_no", "qty", "unit_cost", "material_cost", "labour_cost",
            "sell_price", "est_date", "materials", "processes"]
    rows = [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {','.join(cols)} FROM estimates WHERE status='ok' AND unit_cost > 0")]
    con.close()
    return rows


def setup_from_quantities(rows):
    """Jobs estimated at 2+ quantities: unit = make + setup / qty, fitted -> [{job, kind, make, setup, qtys}]."""
    groups = {}
    for r in rows:
        q = r.get("qty") or 0
        if q >= 1 and r.get("unit_cost"):
            key = (r["job_no"], " ".join(sorted(words(r["description"]))), r.get("drawing_no") or "")
            groups.setdefault(key, {})[int(q)] = to_today(float(r["unit_cost"]), r.get("est_date"))
    out = []
    for (job, desc, _), by_q in groups.items():
        if len(by_q) < 2:
            continue
        xs = [1.0 / q for q in by_q]
        ys = list(by_q.values())
        mx, my = statistics.mean(xs), statistics.mean(ys)
        var = sum((x - mx) ** 2 for x in xs)
        if var <= 0:
            continue
        setup = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
        make = my - setup * mx
        if setup > 0 and make > 0:
            out.append({"job": job, "kind": kind_of(desc), "make": round(make, 2), "setup": round(setup, 2),
                        "qtys": sorted(by_q)})
    return out


def sheet_rows(path):
    import build_estimates as be
    try:
        rows, _ = (be.rows_xlsx(path) if path.lower().endswith(("xlsx", "xlsm")) else be.rows_xls(path))
    except Exception:                                          # noqa: BLE001
        return None
    return rows


def num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def read_sheet_figures(path):
    """From one estimate sheet: the labour columns, each operation's rate (when a column says rate / per hour), and any
    one-off lines (setup, tooling, jigs, programming, first-off, design). Nothing about the client."""
    rows = sheet_rows(path)
    if not rows:
        return None
    header, rate_col, ops, one_offs = None, None, [], []
    in_labour = False
    for r in rows:
        texts = [str(c).strip() for c in r]
        first = next((t for t in texts if t), "")
        if first.lower() == "operation":
            header = [t for t in texts]
            rate_col = next((i for i, t in enumerate(texts) if re.search(r"rate|per ?h(ou)?r|£ ?/ ?h", t, re.I)), None)
            in_labour = True
            continue
        if in_labour:
            if first.lower().startswith("total labour"):
                in_labour = False
            elif first and rate_col is not None and rate_col < len(r):
                rate = num(r[rate_col])
                if rate and 5 <= rate <= 250:
                    ops.append((first[:30].lower(), rate))
        if first and SETUP_WORDS.search(first):
            vals = [num(c) for c in r[1:] if num(c) is not None and num(c) > 0]
            if vals:
                one_offs.append((first[:50].lower(), round(vals[-1], 2)))
    return {"header": [h for h in (header or []) if h][:14], "rates": ops, "one_offs": one_offs[:12]}


# ── the AI calls (own client, own spend tally - never SDI Live's budget) ────────────────────────────────────────────
class Spend:
    def __init__(self, cap):
        self.cap, self.usd, self.lock = cap, 0.0, threading.Lock()

    def add(self, model, usage):
        i, o = PRICE.get(model, (4.0, 20.0))
        with self.lock:
            self.usd += usage.input_tokens / 1e6 * i + usage.output_tokens / 1e6 * o

    def over(self):
        return self.usd >= self.cap


def client():
    import anthropic
    return anthropic.Anthropic(timeout=150, max_retries=2)


def image_b64(path, longest=1568):
    """The picture as a JPEG no bigger than the model uses anyway - (b64, media type) or (None, None)."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im.thumbnail((longest, longest))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
    except Exception:                                          # noqa: BLE001
        return None, None


def read_size(path, spend):
    """Overall H x W x D off the job's own GA (the cheap model, as SDI Live's GA check) -> 'H x W x D mm' or ''."""
    b64, mt = image_b64(path, 1400)
    if not b64:
        return ""
    tool = {"name": "ga_sizes", "description": "The overall dimensions written on this technical drawing, in mm.",
            "input_schema": {"type": "object", "properties": {"height": {"type": "number"}, "width": {"type": "number"},
                                                              "depth": {"type": "number"}},
                             "required": ["height", "width", "depth"]}}
    try:
        r = client().messages.create(model=CHEAP_MODEL, max_tokens=300, tools=[tool],
                                     tool_choice={"type": "tool", "name": "ga_sizes"},
                                     messages=[{"role": "user", "content": [
                                         {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}},
                                         {"type": "text", "text": "Read the OVERALL height, width and depth of the whole unit "
                                                                  "from the dimension lines. Use 0 for any you can't find."}]}])
        spend.add(CHEAP_MODEL, r.usage)
        got = next(x.input for x in r.content if x.type == "tool_use")
        h, w, d = (float(got.get(k) or 0) for k in ("height", "width", "depth"))
        return f"{h:.0f} x {w:.0f} x {d:.0f} mm" if h > 50 and w > 50 and d > 20 else ""
    except Exception:                                          # noqa: BLE001
        return ""


def ask_ai(spend):
    def ask(prompt, img_b64):
        content = ([{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}}]
                   if img_b64 else []) + [{"type": "text", "text": prompt}]
        r = client().messages.create(model=DIRECTOR_MODEL, max_tokens=6000, output_config={"effort": "low"},
                                     messages=[{"role": "user", "content": content}])
        spend.add(DIRECTOR_MODEL, r.usage)
        return "".join(getattr(x, "text", "") for x in r.content)
    return ask


def ask_quick(spend):
    def ask(prompt):
        r = client().messages.create(model=CHAT_MODEL, max_tokens=1200, messages=[{"role": "user", "content": prompt}])
        spend.add(CHAT_MODEL, r.usage)
        return "".join(getattr(x, "text", "") for x in r.content)
    return ask


# ── one past job, estimated as SDI Live would ───────────────────────────────────────────────────────────────────────
def yardstick(job, whole, k=5):
    """Other jobs' whole-unit quotes from before this one, most alike first (same kind, same client, shared words)."""
    jy, jk, jw = year_of(job["est_date"]), kind_of(job["description"]), words(job["description"])
    scored = []
    for o in whole:
        if o["job_no"] == job["job_no"] or (o.get("drawing_no") and o.get("drawing_no") == job.get("drawing_no")):
            continue
        oy = year_of(o["est_date"])
        if jy and oy and (oy > jy or (oy == jy and str(o["est_date"]) >= str(job["est_date"]))):
            continue
        sc = (2.0 if kind_of(o["description"]) == jk and jk != "other" else 0) + \
             (1.0 if (o.get("customer") or "").lower() == (job.get("customer") or "").lower() else 0) + \
             len(jw & words(o["description"])) / max(1, len(jw | words(o["description"])))
        if sc >= 1.0:
            scored.append((sc, o))
    scored.sort(key=lambda t: -t[0])
    return [{"job": o["job_no"], "name": (o["description"] or "")[:60], "unit_cost": o["unit_cost"], "qty": o["qty"],
             "date": o["est_date"], "material_cost": o.get("material_cost"), "labour_cost": o.get("labour_cost"),
             "materials": o.get("materials"), "processes": o.get("processes")} for _, o in scored[:k]]


def at_qty(prices, q):
    return next((p["unit_gbp"] for p in prices or [] if p["qty"] == q), None)


def check_one(job, whole, spend, ls, norms_in):
    q = int(job["qty"]) or 1
    pics = ls.job_pictures(job["job_no"], 1)
    pages = []
    try:
        pages = ls.job_drawing_pages(job["job_no"], 1, job["description"] or "")
    except Exception:                                          # noqa: BLE001
        pages = []
    img = pics[0] if pics else (pages[0] if pages else None)
    if not img:
        return None
    size = read_size(pages[0], spend) if pages else ""
    try:
        mats = ", ".join(json.loads(job.get("materials") or "[]")[:4])
    except ValueError:
        mats = ""
    brief = {"client": job.get("customer") or "", "unit_type": job.get("description") or "", "size": size,
             "materials": mats, "volume_qty": str(q)}
    quotes = yardstick(job, whole)
    bp = ballpark.work_out(quotes, q) if quotes else None
    basis = (bp or {}).get("basis") or []
    b64, _ = image_b64(img)
    row = {"job": job["job_no"], "kind": kind_of(job["description"]), "what": (job["description"] or "")[:60],
           "year": year_of(job["est_date"]), "qty": q, "picture": "render" if pics else "drawing", "size_read": size,
           "past_quotes_used": len(basis),
           "sdi_unit": round(to_today(float(job["unit_cost"]), job["est_date"]), 2),
           "sdi_material": round(to_today(float(job["material_cost"]), job["est_date"]), 2) if job.get("material_cost") else None,
           "sdi_labour": round(to_today(float(job["labour_cost"]), job["est_date"]), 2) if job.get("labour_cost") else None}
    def one_run(_):                           # as SDI Live: costed RUNS times at once, the middle one kept
        try:
            return ai_estimate.estimate_best(brief, None, basis, lambda p, _i: ask_ai(spend)(p, b64), q, norms=norms_in,
                                             rates=SHEET_RATES)
        except Exception as ex:                                # noqa: BLE001
            row["ai_error"] = type(ex).__name__
            return None
    with ThreadPoolExecutor(max_workers=RUNS) as ex_:
        runs = list(ex_.map(one_run, range(RUNS)))
    e = ai_estimate.steady(runs, q)
    if e and e.get("method") == "sdi" and OUT_DIR:      # the AI's sheet for this job, to open beside SDI's real one
        try:
            import sdi_sheet
            wb_path = os.path.join(OUT_DIR, "sheets", f"{job['job_no']}_AI_estimate.xlsx")
            os.makedirs(os.path.dirname(wb_path), exist_ok=True)
            sdi_sheet.fill_workbook(SHEET_RATES, e["plan"], wb_path, {
                "customer": job.get("customer"), "description": job.get("description"), "quantity": q,
                "note": f"SDI Live estimate check - the AI's sheet for job {job['job_no']}; SDI's own sheet: "
                        f"{os.path.basename(job.get('path') or '')}"})
            row["ai_sheet"] = os.path.basename(wb_path)
        except Exception as ex:                        # noqa: BLE001
            row["ai_sheet"] = f"not written ({type(ex).__name__})"
        row["sdi_sheet"] = job.get("path") or ""
        row["ai_parts"] = len(e["plan"].get("sheet_parts") or []) + len(e["plan"].get("wire_parts") or []) \
            + len(e["plan"].get("other_sheet") or [])
        row["ai_operations"] = len(e["plan"].get("operations") or [])
        row["ai_material_sdi"], row["ai_labour_sdi"] = e["sdi"]["material"], e["sdi"]["labour"]
    if e:
        row["ai_runs"] = " / ".join(f"{v:,.0f}" for v in e.get("runs") or [])
        row["ai_spread_pct"] = e.get("spread_pct")
    if e:
        sp = e.get("split") or {}
        row.update(ai_unit=at_qty(e["prices"], q), ai_make=e["unit_variable"], ai_setup=e["setup_total"],
                   ai_material=round(sp.get("materials", 0) + sp.get("bought-in", 0), 2),
                   ai_labour=round(sp.get("labour", 0) + sp.get("finish", 0) + sp.get("packing", 0), 2),
                   ai_setup_lines="; ".join(f"{x['what'][:40]} £{x['gbp']:,.0f}" for x in e.get("setup") or [])[:300])
    qk = None
    if basis:
        try:
            qk = ballpark.quick(brief, quotes, ask_quick(spend), q)
        except Exception as ex:                                # noqa: BLE001
            qk, row["quick_error"] = None, type(ex).__name__
        if qk:
            row.update(quick_unit=at_qty(qk["prices"], q), quick_base=qk["base"]["job"])
    g = agreed.agree(e, qk, q, norms_in) if (e or qk) else None
    if g:
        row["agreed_unit"] = g["unit"]
    for k in ("ai_unit", "ai_make", "quick_unit", "agreed_unit"):
        if row.get(k) and row["sdi_unit"]:
            row[k.replace("_unit", "") + "_err_pct"] = round(100 * (row[k] / row["sdi_unit"] - 1), 1)
    for k in ("material", "labour"):
        if row.get(f"ai_{k}") and row.get(f"sdi_{k}"):
            row[f"ai_{k}_err_pct"] = round(100 * (row[f"ai_{k}"] / row[f"sdi_{k}"] - 1), 1)
    return row


# ── the summary ─────────────────────────────────────────────────────────────────────────────────────────────────────
def how_close(errs):
    errs = [e for e in errs if e is not None]
    if not errs:
        return None
    a = [abs(e) for e in errs]
    return {"n": len(errs), "typical_miss_pct": round(statistics.median(a)), "bias_pct": round(statistics.median(errs)),
            "within_20_pct": round(100 * sum(x <= 20 for x in a) / len(a)),
            "within_35_pct": round(100 * sum(x <= 35 for x in a) / len(a)),
            "correction": round(statistics.median([100 / (100 + e) for e in errs if e > -100]), 2)}


def pct_line(name, s):
    if not s:
        return f"  {name}: no results"
    side = "high" if s["bias_pct"] > 0 else "low"
    return (f"  {name} ({s['n']} jobs): typically {s['typical_miss_pct']}% out; tends to be {abs(s['bias_pct'])}% {side}; "
            f"{s['within_20_pct']}% of jobs within 20%, {s['within_35_pct']}% within 35%. "
            f"Multiplying by {s['correction']} would centre it.")


def norms(setups, sheets, results):
    by_kind = {}
    for s_ in setups:
        by_kind.setdefault(s_["kind"], []).append(s_)
    setup = {}
    for k, xs in by_kind.items():
        v = sorted(x["setup"] for x in xs)
        setup[k] = {"n": len(v), "median_gbp": round(statistics.median(v)), "high_gbp": round(v[int(0.8 * (len(v) - 1))]),
                    "median_make_gbp": round(statistics.median(x["make"] for x in xs))}
    rates = {}
    for sh in sheets:
        for op, r in (sh or {}).get("rates", []):
            rates.setdefault(op, []).append(r)
    rates = {op: {"n": len(v), "median_gbp_per_hour": round(statistics.median(v), 2)}
             for op, v in sorted(rates.items(), key=lambda t: -len(t[1])) if len(v) >= 2}
    one = {}
    for sh in sheets:
        for what, g in (sh or {}).get("one_offs", []):
            key = re.sub(r"[^a-z ]", "", what).strip()[:30]
            one.setdefault(key, []).append(g)
    one = {k: {"n": len(v), "median_gbp": round(statistics.median(v))} for k, v in
           sorted(one.items(), key=lambda t: -len(t[1])) if len(v) >= 2}
    corr = {}
    for k in sorted({r["kind"] for r in results}):
        s = how_close([r.get("ai_err_pct") for r in results if r["kind"] == k])
        if s and s["n"] >= 3:
            corr[k] = s["correction"]
    allk = how_close([r.get("ai_err_pct") for r in results])
    acc = {k: (how_close([r.get(f"{k}_err_pct") for r in results]) or {}).get("typical_miss_pct") for k in ("ai", "quick")}
    return {"accuracy": acc if all(acc.values()) else {},"made": datetime.now().isoformat(timespec="seconds"), "setup_by_kind": setup, "rates_by_operation": rates,
            "one_off_lines": one, "ai_correction_by_kind": corr, "ai_correction_all": (allk or {}).get("correction")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=40, help="past jobs to estimate (default 40)")
    ap.add_argument("--since", type=int, default=2022, help="only estimate sheets from this year on (default 2022)")
    ap.add_argument("--workers", type=int, default=3, help="jobs at once (default 3)")
    ap.add_argument("--max-usd", type=float, default=15.0, help="stop starting new jobs past this AI spend (default $15)")
    ap.add_argument("--runs", type=int, default=3, help="AI estimate runs per job, the middle kept, as SDI Live (default 3)")
    ap.add_argument("--sheets", type=int, default=150, help="estimate sheets to read for rates and one-off lines")
    ap.add_argument("--dry", action="store_true", help="only the free part: setup and rates from the sheets")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--old-ai", action="store_true", help="test the AI's own line-by-line pricing, not SDI's sheet")
    ap.add_argument("--use-norms", action="store_true", help="test the AI estimate WITH studio_data\\estimate_norms.json "
                                                             "(after calibrating, to see it got closer)")
    a = ap.parse_args()
    global RUNS, SHEET_RATES, OUT_DIR
    RUNS = max(1, a.runs)
    if not a.old_ai:
        import sdi_sheet
        SHEET_RATES = sdi_sheet.load_rates()
        print("AI estimate costed SDI's way, from " + sdi_sheet.TEMPLATE if SHEET_RATES else
              ("SDI's estimate template is at " + sdi_sheet.TEMPLATE + " but no rates could be read from it"
               if os.path.exists(sdi_sheet.TEMPLATE) else "No SDI estimate template at " + sdi_sheet.TEMPLATE)
              + ("" if SHEET_RATES else " - testing the AI's own pricing"), flush=True)

    import lite_search as ls
    out = os.path.join(HERE, "out", "estimate_check", datetime.now().strftime("%Y-%m-%d_%H%M"))
    os.makedirs(out, exist_ok=True)
    OUT_DIR = out
    rows = load_estimates(ls.ESTIMATES_DB)
    print(f"{len(rows)} estimate sheets with a unit cost", flush=True)

    setups = setup_from_quantities(rows)
    print(f"{len(setups)} jobs estimated at 2+ quantities (setup worked out from those)", flush=True)
    for r in rows:                                   # K:\ as stored, or its UNC share when K: isn't mapped here
        r["path"] = ls.real_path(r.get("path"))
    recent = [r for r in rows if (year_of(r["est_date"]) or 0) >= a.since and r.get("path") and os.path.exists(r["path"])]
    random.Random(a.seed).shuffle(recent)
    sheets = [read_sheet_figures(r["path"]) for r in recent[:a.sheets]]
    header = next((s_["header"] for s_ in sheets if s_ and s_["header"]), [])
    print(f"read {sum(1 for s_ in sheets if s_)} sheets for rates and one-off lines"
          + ("" if recent else f" - none of the estimate files could be opened (e.g. {rows[0].get('path') if rows else '-'})"),
          flush=True)

    best = {}
    for r in rows:
        if ls.is_whole_unit(r["description"]) and (r.get("qty") or 0) >= 1 and 20 <= r["unit_cost"] <= 20000:
            if r["job_no"] not in best or ls.whole_unit_key(r) < ls.whole_unit_key(best[r["job_no"]]):
                best[r["job_no"]] = r
    whole = list(best.values())
    pool = [r for r in whole if (year_of(r["est_date"]) or 0) >= a.since]
    random.Random(a.seed).shuffle(pool)
    by_kind = {}
    for r in pool:                                   # a spread of kinds, not forty of the commonest
        by_kind.setdefault(kind_of(r["description"]), []).append(r)
    order = []
    while any(by_kind.values()):
        for k in list(by_kind):
            if by_kind[k]:
                order.append(by_kind[k].pop())
    print(f"{len(whole)} jobs with a whole-unit estimate; {len(pool)} since {a.since}", flush=True)

    spend, results = Spend(a.max_usd), []
    norms_in = ai_estimate.load_norms() if a.use_norms else {}
    if a.use_norms:
        print("testing WITH SDI's figures from " + ai_estimate.NORMS + (" (none found)" if not norms_in else ""), flush=True)
    if not a.dry:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            todo, running = iter(order), {}

            def more():
                while len(running) < a.workers and len(results) + len(running) < a.jobs and not spend.over():
                    j = next(todo, None)
                    if j is None:
                        return
                    running[ex.submit(check_one, j, whole, spend, ls, norms_in)] = j
            more()
            while running:
                for f in as_completed(list(running)):
                    j = running.pop(f)
                    try:
                        r = f.result()
                    except Exception as e:                     # noqa: BLE001
                        r = None
                        print(f"  {j['job_no']}: failed ({type(e).__name__})", flush=True)
                    if r:
                        results.append(r)
                        print(f"  {len(results):>3} {r['job']} {r['kind']:<11} SDI £{r['sdi_unit']:,.0f} | AI "
                              f"{('£%s' % format(r['ai_unit'], ',.0f')) if r.get('ai_unit') else '-'} | past jobs "
                              f"{('£%s' % format(r['quick_unit'], ',.0f')) if r.get('quick_unit') else '-'}"
                              f"   (${spend.usd:.2f}, {time.time() - t0:.0f}s)", flush=True)
                    more()
                    break

    if results:
        keys = sorted({k for r in results for k in r}, key=lambda k: (k not in ("job", "kind", "what", "year", "qty"), k))
        with open(os.path.join(out, "results.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(results)
    nm = norms(setups, sheets, results)
    nm["labour_columns_on_the_sheet"] = header
    nm["rates"] = {"shop": None, "assembly": None, "design": None}   # SDI's hourly rates - filled in by hand when checked
    with open(os.path.join(out, "estimate_norms.proposed.json"), "w", encoding="utf-8") as fh:
        json.dump(nm, fh, indent=2)

    L = [f"SDI Live estimate check - {datetime.now():%d %b %Y %H:%M}" + (" - WITH SDI's figures" if a.use_norms else "")
         + (" - AI estimate costed on SDI's sheet" if SHEET_RATES else " - AI estimate priced by the AI itself"), ""]
    if results:
        L += [f"{len(results)} past SDI jobs estimated by both of SDI Live's estimates and compared with SDI's own estimate "
              f"sheet (all in today's money). AI spend ${spend.usd:.2f}.", "",
              "HOW CLOSE (unit cost at the job's own quantity):",
              pct_line("AI estimate", how_close([r.get("ai_err_pct") for r in results])),
              pct_line("AI estimate without the setup", how_close([r.get("ai_make_err_pct") for r in results])),
              pct_line("Past jobs estimate", how_close([r.get("quick_err_pct") for r in results])),
              pct_line("Agreed figure (the two weighed together - what the client pack uses)",
                       how_close([r.get("agreed_err_pct") for r in results])),
              pct_line("AI materials vs the sheet's materials", how_close([r.get("ai_material_err_pct") for r in results])),
              pct_line("AI labour vs the sheet's labour", how_close([r.get("ai_labour_err_pct") for r in results])), "",
              "BY KIND OF UNIT (AI estimate / past jobs):"]
        for k in sorted({r["kind"] for r in results}):
            mine = [r for r in results if r["kind"] == k]
            sa, sq = how_close([r.get("ai_err_pct") for r in mine]), how_close([r.get("quick_err_pct") for r in mine])
            L.append(f"  {k:<12} {len(mine):>2} jobs   AI typically {sa['typical_miss_pct'] if sa else '-'}% out "
                     f"(bias {sa['bias_pct'] if sa else '-'}%)   past jobs {sq['typical_miss_pct'] if sq else '-'}% out "
                     f"(bias {sq['bias_pct'] if sq else '-'}%)")
        spreads = [r["ai_spread_pct"] for r in results if r.get("ai_spread_pct") is not None]
        if spreads:
            L += ["", f"AI's {RUNS} runs per job: typically {statistics.median(spreads):.0f}% apart (the middle one is kept)."]
        ai_setups = [r["ai_setup"] for r in results if r.get("ai_setup") is not None]
        if ai_setups:
            L += ["", f"AI setup: median £{statistics.median(ai_setups):,.0f}, from £{min(ai_setups):,.0f} to "
                      f"£{max(ai_setups):,.0f}."]
    L += ["", "SETUP FROM SDI'S OWN SHEETS (jobs priced at 2+ quantities; unit = make + setup / qty):"]
    for k, v in sorted(nm["setup_by_kind"].items(), key=lambda t: -t[1]["n"]):
        L.append(f"  {k:<12} {v['n']:>3} jobs   setup typically £{v['median_gbp']:,} (80% under £{v['high_gbp']:,})   "
                 f"make £{v['median_make_gbp']:,} a unit")
    L += ["", "LABOUR COLUMNS ON THE SHEETS: " + (" | ".join(header) if header else "(no 'Operation' section found)"),
          "RATES (where a column gives one):"]
    L += [f"  {op:<30} £{v['median_gbp_per_hour']:.2f} an hour ({v['n']} sheets)" for op, v in
          list(nm["rates_by_operation"].items())[:20]] or ["  none found"]
    L += ["ONE-OFF LINES ON THE SHEETS:"]
    L += [f"  {k:<30} typically £{v['median_gbp']:,} ({v['n']} sheets)" for k, v in list(nm["one_off_lines"].items())[:20]] \
        or ["  none found"]
    L += ["", f"Detail: {os.path.join(out, 'results.csv')}",
          f"Proposed figures for SDI Live: {os.path.join(out, 'estimate_norms.proposed.json')}"]
    with open(os.path.join(out, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n" + "\n".join(L), flush=True)


if __name__ == "__main__":
    main()
