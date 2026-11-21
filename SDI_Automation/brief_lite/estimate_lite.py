"""estimate_lite.py - Estimate Lite: the design on screen priced by SDI's estimating engine (21 Nov 2026).

James: "let's wire it in. we can test it. it's not a live system". The estimating service already has the door for
this - POST /api/estimate/llm, "one call for a concept estimate: a prompt and an image in, a queued LLM run out" - so
nothing is priced here. SDI Live sends:
    prompt      the brief written out: client, unit, H x W x D, materials, finish, lighting, products, quantity, notes
    image       the chosen render (its HD copy when there is one)
    quantities  1, 10 and the brief's quantity
    reference   SDILive-<chat>-<option>, so the run is found on Grid Control and in the estimating folders
and the engine reads the picture and brief, builds the parts list, prices materials, labour and bought-in items, and
files a DRAFT workbook. SDI Live checks the run every POLL_S seconds and, when it's done, reads the unit cost at each
quantity and the summary, and shows them. The service's own words stand: an LLM-only read is a measurement of the
model, not a quotation; the customer quote stays behind the estimating team's release.

Settings (SDI Live's .env):
    ESTIMATE_LITE_URL   the estimating service (default http://127.0.0.1:8071 - SDI Intelligence on this server)
    SDI_API_KEY         its service key; if not set here, read from SDI Intelligence's own .env on this server.
                        Never printed, logged or shown.
State is kept in its own table (estimate_lite in lite.db), never in the brief, so a turn saving the brief can't lose it.
"""
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime

POLL_S = 20
GIVE_UP_S = 45 * 60
SDI_ENV = r"C:\ClaudeVision\sdi-intelligence-backend\.env"


def url():
    return (os.environ.get("ESTIMATE_LITE_URL") or "http://127.0.0.1:8071").rstrip("/")


def key():
    k = (os.environ.get("SDI_API_KEY") or "").strip()
    if k:
        return k
    try:
        for line in open(SDI_ENV, encoding="utf-8", errors="ignore"):
            m = re.match(r"\s*SDI_API_KEY\s*=\s*(.+)$", line)
            if m and not line.lstrip().startswith("#"):
                return m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _headers():
    k = key()
    return {"X-SDI-Key": k} if k else {}


# ── what is sent ──────────────────────────────────────────────────────────────────────────

FIELDS = [("client", "Client"), ("unit_type", "Unit"), ("size", "Overall size (H x W x D)"), ("materials", "Materials"),
          ("finish", "Finish"), ("colours_graphics", "Colours and graphics"), ("lighting", "Lighting"),
          ("products_held", "Products it holds"), ("hero_products", "Hero products"), ("shelf_load", "Shelf load"),
          ("placement", "Where in store"), ("fixing", "Fixing / free-standing"), ("assembly", "Assembly"),
          ("volume_qty", "Quantity"), ("packaging", "Packaging"), ("other_notes", "Other notes")]


def prompt_for(brief, label="A", director=""):
    """The enquiry brief, as the estimating page's LLM run takes it: stated facts, one per line."""
    lines = [f"Concept from SDI Live (option {label}) - priced from the concept render and this brief, not drawings."]
    for k, name in FIELDS:
        v = brief.get(k)
        if v and str(v).strip() and str(v).strip().lower() not in ("unknown", "not known", "n/a"):
            lines.append(name + ": " + " ".join(str(v).split()))
    if director:
        lines.append("Design intent: " + " ".join(str(director).split())[:600])
    return "\n".join(lines)


def quantities_for(brief):
    m = re.search(r"\d[\d,]*", str(brief.get("volume_qty") or ""))
    q = int(m.group(0).replace(",", "")) if m else None
    out = sorted({1, 10} | ({q} if q and 1 <= q <= 100000 else set()))
    return ",".join(str(x) for x in out)


# ── its own record ────────────────────────────────────────────────────────────────────────

def _con(db_path):
    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS estimate_lite (sid TEXT, run_id TEXT, label TEXT, started TEXT, "
                "status TEXT, result TEXT, error TEXT)")
    return con


def latest(db_path, sid):
    con = _con(db_path)
    r = con.execute("SELECT * FROM estimate_lite WHERE sid=? ORDER BY started DESC LIMIT 1", (sid,)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    return d


def _save(db_path, sid, run_id, **kw):
    con = _con(db_path)
    if kw.get("new"):
        con.execute("INSERT INTO estimate_lite VALUES (?,?,?,?,?,?,?)",
                    (sid, run_id, kw.get("label") or "A", datetime.now().isoformat(timespec="seconds"), "queued", None, None))
    else:
        sets, vals = [], []
        for k in ("status", "result", "error"):
            if k in kw:
                sets.append(f"{k}=?")
                vals.append(json.dumps(kw[k]) if k == "result" and kw[k] is not None else kw[k])
        con.execute(f"UPDATE estimate_lite SET {', '.join(sets)} WHERE sid=? AND run_id=?", (*vals, sid, run_id))
    con.commit()
    con.close()


# ── the estimating service ────────────────────────────────────────────────────────────────

def runners_online(get):
    """How many estimating runners can take the job now; None when the service can't be asked."""
    try:
        r = get(url() + "/api/estimate/runners", headers=_headers(), timeout=15)
        if r.status_code != 200:
            return None
        j = r.json()
        rows = j.get("runners") if isinstance(j, dict) else j
        return sum(1 for x in (rows or []) if (x or {}).get("online", True))
    except Exception:                                                     # noqa: BLE001
        return None


def start(brief, image_path, label, sid, post, get, director=""):
    """Queue the run. -> (run_id, '') or ('', why)."""
    n = runners_online(get)
    if n is None:
        return "", (f"the estimating service at {url()} didn't answer - it may be stopped, or this server can't reach it")
    if n == 0:
        return "", "no estimating runner is online to take it just now"
    try:
        with open(image_path, "rb") as fh:
            r = post(url() + "/api/estimate/llm", headers=_headers(), timeout=60,
                     files={"image": (os.path.basename(image_path), fh, "image/png")},
                     data={"prompt": prompt_for(brief, label, director), "client": str(brief.get("client") or "SDI"),
                           "reference": f"SDILive-{sid}-{label}", "quantities": quantities_for(brief)})
    except Exception as e:                                                # noqa: BLE001
        return "", f"the estimating service didn't take it ({type(e).__name__})"
    if r.status_code in (401, 403):
        return "", "the estimating service refused SDI Live's key (SDI_API_KEY)"
    if r.status_code != 200:
        try:
            why = r.json().get("detail") or r.text
        except ValueError:
            why = r.text
        return "", f"the estimating service said no ({r.status_code}: {str(why)[:160]})"
    rid = str((r.json() or {}).get("run_id") or "")
    return (rid, "") if rid else ("", "the estimating service gave no run number")


def result_of(status, summary):
    """What the card shows: the unit cost at each quantity, provisional or not, and where the workbook is."""
    qp = []
    for q in (status or {}).get("quantity_prices") or []:
        try:
            if q.get("unit_gbp") is not None:
                qp.append({"qty": int(q["quantity"]), "unit_gbp": round(float(q["unit_gbp"]), 2)})
        except (TypeError, ValueError, KeyError):
            continue
    unit = (summary or {}).get("unit_cost_gbp") or (status or {}).get("engine_price_gbp")
    if not qp and unit is not None:
        qp = [{"qty": int((summary or {}).get("units") or 1), "unit_gbp": round(float(unit), 2)}]
    return {"prices": sorted(qp, key=lambda x: x["qty"]), "provisional": bool((summary or {}).get("provisional", True)),
            "workbook": (summary or {}).get("workbook_xlsx") or "", "caution": (summary or {}).get("caution") or "",
            "run_id": (summary or {}).get("run_id") or (status or {}).get("run_id")}


def watch(db_path, sid, run_id, get, done=None, sleep=time.sleep, give_up_s=GIVE_UP_S, poll_s=POLL_S):
    """Follow the run until it ends; the result goes into the record and `done(record)` is told."""
    t0 = time.time()
    while time.time() - t0 < give_up_s:
        try:
            r = get(f"{url()}/api/estimate/{run_id}", headers=_headers(), timeout=30)
            st = r.json() if r.status_code == 200 else {}
        except Exception:                                                 # noqa: BLE001
            st = {}
        s_ = str(st.get("status") or "")
        if s_ and s_ != (latest(db_path, sid) or {}).get("status"):
            _save(db_path, sid, run_id, status=s_)
        if s_ == "done":
            try:
                summ = get(f"{url()}/api/estimate/{run_id}/summary", headers=_headers(), timeout=30).json()
            except Exception:                                             # noqa: BLE001
                summ = {}
            res = result_of(st, summ)
            _save(db_path, sid, run_id, status="done", result=res)
            break
        if s_ in ("error", "failed", "cancelled", "abandoned", "timeout"):
            _save(db_path, sid, run_id, status=s_, error=str(st.get("error") or s_)[:300])
            break
        sleep(poll_s)
    else:
        _save(db_path, sid, run_id, status="timeout", error=f"not finished after {give_up_s // 60} minutes")
    rec = latest(db_path, sid)
    if done:
        done(rec)
    return rec


def say(rec):
    """One line for Sid / the chat."""
    if not rec:
        return ""
    if rec.get("status") != "done":
        return f"Estimate Lite didn't finish: {rec.get('error') or rec.get('status')}."
    ps = (rec.get("result") or {}).get("prices") or []
    if not ps:
        return "Estimate Lite finished but gave no unit price - the workbook says why."
    bits = "; ".join(f"£{p['unit_gbp']:,.0f} a unit at {p['qty']}" for p in ps)
    return f"Estimate Lite (provisional, from the concept - not a quote): {bits}."
