"""
craft.py - SDI Craft Memory: the studio's design know-how, captured while people work.

Why (Tracy, KTP review, 14 Oct 2026): "All you're capturing is the outputs of the craft process. What's the craft
thinking that's going on?" Tools that only store renders and drawings lose the reasons - why this option and not that
one, why the header grew, why the tester sits front-left. That knowledge leaves the building when a designer does.

The theory it follows:
  - Polanyi (1966): "we know more than we can tell" - craft knowledge is tacit; you get it by watching decisions, not by
    asking people to write rules.
  - Nonaka & Takeuchi (1995), the SECI spiral - knowledge moves tacit -> explicit -> combined -> learned again:
      Socialisation   people working side by side             (design reviews, the weekly sit-downs)
      Externalisation the tacit becomes explicit             (a decision + its "why", captured here)
      Combination     explicit pieces joined into patterns   (rules(), taste(), stats())
      Internalisation the patterns go back into people's work (the Design Director's STUDIO MEMORY, the Craft page)
  - Schon (1983), reflection-in-action: designers reason in the moment ("make the header bigger"), so capture happens
    at the moment of the decision, never in a form filled in later.
  - Design rationale (MacLean et al., QOC 1991): Questions, Options, Criteria - every decision is stored with the options
    that were on the table and the criteria that decided it.

No extra work for anyone: almost everything is captured from what people already do (which option they pick, what they
ask to change, which reference they strike out, who gets booked on what). The only ask is an optional one-tap "why".
Free: SQLite + CLIP on this PC. No AI credit is spent here. Everything stays on C:.
"""
import json, os, re, sqlite3, threading, time, uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "craft.db")
VEC = os.path.join(HERE, "vecs")
_lock = threading.Lock()

# The reasons a retail display designer gives, worded the way they say them - the one-tap chips
CHIPS = ["Brand fit", "Products show well", "Looks premium", "Cost / budget", "Easy to make", "Easy to ship & build",
         "Client asked", "Fits the store / space", "Stands out in the aisle", "Testers easy to reach", "Sturdy / safe",
         "Sustainable"]
# Chips a tool adds for its own kind of decision (SDI Recall: "Right shape", "Same client"...). Kept apart from CHIPS
# so the Showroom's chip row does not change; reason() accepts both.
EXTRA_CHIPS = set()

BECAUSE = re.compile(r"\b(because|cos|'cause|as it|since|so that|so it|otherwise|too (?:big|small|busy|plain|tall|short|wide|"
                     r"narrow|dark|light|expensive|cheap|heavy|much|little)|not (?:enough|visible|premium|sturdy)|looks? "
                     r"(?:better|cleaner|cheap|premium|busy)|feels? (?:more|less|cheap|premium)|cheaper|stronger|easier|"
                     r"brand (?:guide|rule)s?|client (?:wants|likes|asked|said))\b", re.I)


def db():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, at TEXT, tool TEXT, kind TEXT, who TEXT, ref TEXT,
        context TEXT, data TEXT, chips TEXT, reason TEXT, reason_by TEXT);
    CREATE INDEX IF NOT EXISTS ev_ref ON events(ref, kind, at);
    CREATE INDEX IF NOT EXISTS ev_kind ON events(kind, at);
    CREATE TABLE IF NOT EXISTS predictions (id TEXT PRIMARY KEY, at TEXT, tool TEXT, ref TEXT, who TEXT, client TEXT,
        options TEXT, predicted TEXT, scores TEXT, actual TEXT, hit INTEGER, decided_at TEXT);
    CREATE TABLE IF NOT EXISTS optout (who TEXT PRIMARY KEY, at TEXT);
    """)
    return con


def opted_out(who):
    if not who:
        return False
    con = db()
    r = con.execute("SELECT 1 FROM optout WHERE lower(who)=lower(?)", (who,)).fetchone()
    con.close()
    return bool(r)


def set_optout(who, out=True):
    con = db()
    if out:
        con.execute("INSERT OR REPLACE INTO optout VALUES (?,?)", (who, datetime.now().isoformat(timespec="seconds")))
    else:
        con.execute("DELETE FROM optout WHERE lower(who)=lower(?)", (who,))
    con.commit(); con.close()


# ---------------------------------------------------------------- capture

def context_of(b):
    """The features a decision depends on, from a brief - what makes two decisions comparable."""
    b = b or {}
    txt = " ".join(str(b.get(k) or "") for k in ("unit_type", "products_held", "hero_products", "narrative", "colours_graphics")).lower()
    cat = next((c for c, w in (("fragrance", r"fragrance|perfume|parfum|eau de"), ("skincare", r"skin ?care|serum|moistur|no7"),
                               ("cosmetics", r"make-?up|cosmetic|lipstick|mascara"), ("power tools", r"drill|tool|milwaukee|ryobi|tti"),
                               ("food & drink", r"chocolate|lindt|food|drink|coffee|capsule|confection"),
                               ("electronics", r"electronic|phone|headphone|tech|gaming")) if re.search(w, txt)), "")
    unit = str(b.get("unit_type") or "").lower()
    unit = next((u for u, w in (("gondola end", r"gondola"), ("counter unit", r"counter|cdu|till"), ("FSDU", r"fsdu|floor"),
                                ("wall bay", r"wall ?bay|bay"), ("permanent tray", r"tray"), ("plinth", r"plinth|podium"),
                                ("totem", r"totem")) if re.search(w, unit)), unit[:30])
    q = re.findall(r"\d+", str(b.get("volume_qty") or ""))
    return {k: v for k, v in {"client": (b.get("client") or "").strip()[:40], "retailer": (b.get("retailer") or "").strip()[:40],
                              "category": cat, "unit": unit, "materials": str(b.get("materials") or "")[:60],
                              "placement": str(b.get("placement") or "")[:40],
                              "qty": ("1-10" if int(q[0]) <= 10 else "11-100" if int(q[0]) <= 100 else "100+") if q else ""}.items() if v}


def log(tool, kind, who="", ref="", context=None, data=None):
    """One decision or signal. Never raises - capture must never break the tool."""
    try:
        if opted_out(who):
            return None
        eid = uuid.uuid4().hex[:12]
        with _lock:
            con = db()
            con.execute("INSERT INTO events (id, at, tool, kind, who, ref, context, data, chips, reason, reason_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (eid, datetime.now().isoformat(timespec="seconds"), tool, kind, (who or "")[:60], (ref or "")[:60],
                         json.dumps(context or {}), json.dumps(data or {}, default=str)[:20000], "[]", "", ""))
            con.commit(); con.close()
        return eid
    except Exception as e:
        print("craft.log:", e)
        return None


DECISIONS = ("option_chosen", "change_requested", "reference_rejected", "assumption_corrected", "booked", "email_filed", "job_closed",
             "studio_review", "designer_note")
SHOWN = DECISIONS + ("meeting_insight", "said_reason", "question_feedback", "question_missing", "fact_wrong", "render_feedback")


def reason(ref, chips=None, text="", kind=None, by=""):
    """Attach a 'why' to the latest decision on this brief/job (the one-tap chips, or words they said anyway)."""
    try:
        con = db()
        q = "SELECT id, chips, reason FROM events WHERE ref=? AND kind IN (%s) ORDER BY at DESC LIMIT 1" % \
            ",".join("?" * len((kind,) if kind else DECISIONS))
        r = con.execute(q, (ref, *((kind,) if kind else DECISIONS))).fetchone()
        if not r:
            con.close()
            return None
        cs = sorted(set(json.loads(r["chips"] or "[]")) | {c for c in (chips or []) if c in CHIPS or c in EXTRA_CHIPS})
        rs = "; ".join(x for x in [r["reason"], (text or "").strip()[:400]] if x)
        con.execute("UPDATE events SET chips=?, reason=?, reason_by=? WHERE id=?", (json.dumps(cs), rs, (by or "")[:60], r["id"]))
        con.commit(); con.close()
        return r["id"]
    except Exception as e:
        print("craft.reason:", e)
        return None


def because(text):
    """The reason inside something they said anyway - 'make the header bigger, it isn't visible from the aisle'."""
    t = (text or "").strip()
    if not t or not BECAUSE.search(t):
        return ""
    parts = re.split(r"(?<=[.!?])\s+", t)
    hit = [p for p in parts if BECAUSE.search(p)]
    return " ".join(hit)[:300]


def heard(tool, who, ref, text, window_min=4):
    """A sentence from the chat or a live call: if it carries a reason and a decision happened in the last few minutes,
    that reason belongs to the decision (reflection-in-action - said in the moment, captured in the moment)."""
    why = because(text)
    if not why:
        return None
    try:
        con = db()
        since = (datetime.now() - timedelta(minutes=window_min)).isoformat(timespec="seconds")
        r = con.execute("SELECT id FROM events WHERE ref=? AND at>=? AND kind IN (%s) ORDER BY at DESC LIMIT 1" % ",".join("?" * len(DECISIONS)),
                        (ref, since, *DECISIONS)).fetchone()
        con.close()
        if r:
            return reason(ref, text=why, by=who)
        return log(tool, "said_reason", who, ref, data={"text": why})
    except Exception:
        return None


# ---------------------------------------------------------------- learn (free, on this PC)

def _vec_path(key):
    os.makedirs(VEC, exist_ok=True)
    return os.path.join(VEC, re.sub(r"[^\w-]", "_", key)[:80] + ".npy")


def remember_look(key, image_path, clip):
    """CLIP fingerprint of a picture someone chose or passed over - what their taste is learnt from."""
    try:
        import numpy as np
        from PIL import Image
        p = _vec_path(key)
        if os.path.exists(p):
            return np.load(p)
        v = clip().encode([Image.open(image_path).convert("RGB")], convert_to_numpy=True, normalize_embeddings=True)[0]
        np.save(p, v.astype("float32"))
        return v
    except Exception:
        return None


def taste(who="", client="", min_n=2):
    """Taste direction = what was chosen minus what was passed over (for this person and/or client). None until there's
    enough to go on. It's how the tool learns 'Andy goes for the lit, minimal one' without anyone saying so."""
    import numpy as np
    con = db()
    rows = con.execute("SELECT who, context, data FROM events WHERE kind='option_chosen'").fetchall()
    con.close()
    good, bad = [], []
    for r in rows:
        ctx, d = json.loads(r["context"] or "{}"), json.loads(r["data"] or "{}")
        if who and (r["who"] or "").lower() != who.lower() and not (client and ctx.get("client", "").lower() == client.lower()):
            continue
        if not who and client and ctx.get("client", "").lower() != client.lower():
            continue
        for key, lst in ((d.get("chosen_key"), good), *((k, bad) for k in d.get("rejected_keys") or [])):
            if key and os.path.exists(_vec_path(key)):
                lst.append(np.load(_vec_path(key)))
    if len(good) < min_n:
        return None
    t = np.mean(good, 0) - (np.mean(bad, 0) if bad else 0)
    n = np.linalg.norm(t)
    return t / n if n else None


def predict(tool, ref, options, who, client, clip):
    """Before they pick: which option will they choose? Logged, then marked right or wrong when they do - the learning
    curve that shows the tool is picking up the studio's taste (the number for the KTP report and the paper)."""
    try:
        keys = []
        for o in options:
            v = remember_look(f"{ref}_{o['label']}_{os.path.basename(o['path'])}", o["path"], clip)
            keys.append((o["label"], v))
        t = taste(who, client)
        if t is None or not keys:
            scores, pred = {}, ""
        else:
            scores = {L: float(v @ t) for L, v in keys if v is not None}
            pred = max(scores, key=scores.get) if scores else ""
        con = db()
        con.execute("INSERT INTO predictions (id, at, tool, ref, who, client, options, predicted, scores, actual, hit, decided_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex[:12], datetime.now().isoformat(timespec="seconds"), tool, ref,
                                                         who or "", client or "", json.dumps([L for L, _ in keys]), pred,
                                                         json.dumps(scores), "", None, ""))
        con.commit(); con.close()
        return pred
    except Exception as e:
        print("craft.predict:", e)
        return ""


def outcome(ref, chosen):
    try:
        con = db()
        r = con.execute("SELECT id, predicted FROM predictions WHERE ref=? AND actual='' ORDER BY at DESC LIMIT 1", (ref,)).fetchone()
        if r:
            con.execute("UPDATE predictions SET actual=?, hit=?, decided_at=? WHERE id=?",
                        (chosen, (1 if r["predicted"] == chosen else 0) if r["predicted"] else None,
                         datetime.now().isoformat(timespec="seconds"), r["id"]))
            con.commit()
        con.close()
    except Exception as e:
        print("craft.outcome:", e)


def rules(context=None, k=6, tool=None):
    """Combination: the reasons given for decisions in a similar context, grouped and counted, with who gave them.
    'Boots fragrance gondola ends: testers easy to reach x5 (Andy, Reese)'."""
    context = context or {}
    con = db()
    rows = con.execute("SELECT kind, who, context, chips, reason, data, ref FROM events WHERE (chips!='[]' OR reason!='') "
                       + ("AND tool=? " if tool else "") + "ORDER BY at DESC LIMIT 3000", (tool,) if tool else ()).fetchall()
    con.close()
    keys = [x for x in ("client", "category", "unit") if context.get(x)]
    agg = defaultdict(lambda: {"n": 0, "who": Counter(), "refs": [], "match": 0, "examples": []})
    for r in rows:
        ctx = json.loads(r["context"] or "{}")
        match = sum(1 for x in keys if str(ctx.get(x, "")).lower() == str(context[x]).lower())
        if keys and not match:
            continue
        where = " ".join(v for v in (ctx.get("client"), ctx.get("category"), ctx.get("unit")) if v)
        for c in json.loads(r["chips"] or "[]"):
            a = agg[(c, where)]
            a["n"] += 1; a["match"] = max(a["match"], match); a["refs"].append(r["ref"])
            if r["who"]:
                a["who"][r["who"]] += 1
        if r["reason"]:
            a = agg[("“" + r["reason"][:320] + "”", where)]
            a["n"] += 1; a["match"] = max(a["match"], match); a["refs"].append(r["ref"])
            if r["who"]:
                a["who"][r["who"]] += 1
    out = [{"rule": key[0], "where": key[1], "n": v["n"], "who": [w for w, _ in v["who"].most_common(3)], "refs": v["refs"][:5],
            "match": v["match"]} for key, v in agg.items()]
    out.sort(key=lambda x: (-x["match"], -x["n"]))
    return out[:k]


def memory_for_prompt(context, who=""):
    """Internalisation: the studio's own rules, handed to the Design Director before it draws (cited, so it can say so)."""
    rs = rules(context, 6)
    if not rs:
        return ""
    lines = [f"- {r['rule']} ({r['n']}x{', ' + ', '.join(r['who']) if r['who'] else ''}{', ' + r['where'] if r['where'] else ''})" for r in rs]
    return "STUDIO MEMORY - what SDI's own people chose before in briefs like this, and why (cite it when you use it):\n" + "\n".join(lines)


# ---------------------------------------------------------------- the Craft Memory page

def stats(tool=None):
    """tool: one tool's own learning (SDI Craft's tabs); None = everything together."""
    con = db()
    w, args = ("WHERE tool=?", (tool,)) if tool else ("", ())
    ev = [dict(r) for r in con.execute(f"SELECT * FROM events {w} ORDER BY at DESC LIMIT 5000", args)]
    pr = [dict(r) for r in con.execute(f"SELECT * FROM predictions {w} ORDER BY at", args)]
    outs = [r["who"] for r in con.execute("SELECT who FROM optout")]
    con.close()
    dec = [e for e in ev if e["kind"] in DECISIONS]
    why = [e for e in dec if e["chips"] != "[]" or e["reason"]]
    chips = Counter(c for e in ev for c in json.loads(e["chips"] or "[]"))
    gaps = Counter(json.loads(e["data"] or "{}").get("field", "") for e in ev if e["kind"] == "knowledge_gap")
    expert = defaultdict(Counter)
    for e in ev:
        if e["kind"] in ("booked", "option_chosen") and e["who"]:
            ctx = json.loads(e["context"] or "{}")
            person = json.loads(e["data"] or "{}").get("person") or e["who"]
            expert[person][ctx.get("category") or ctx.get("unit") or ctx.get("client") or "general"] += 1
    scored = [p for p in pr if p["hit"] is not None]
    weeks = defaultdict(lambda: [0, 0])
    for p in scored:
        wk = (p["decided_at"] or p["at"])[:10]
        wk = (datetime.fromisoformat(wk) - timedelta(days=datetime.fromisoformat(wk).weekday())).date().isoformat()
        weeks[wk][0] += p["hit"]; weeks[wk][1] += 1
    recent = []
    for e in [e for e in ev if e["kind"] in SHOWN][:30]:
        d = json.loads(e["data"] or "{}")
        recent.append({"at": e["at"], "tool": e["tool"], "kind": e["kind"], "who": e["who"], "ref": e["ref"],
                       "context": json.loads(e["context"] or "{}"), "chips": json.loads(e["chips"] or "[]"), "reason": e["reason"],
                       "summary": d.get("summary") or d.get("change") or d.get("label") or d.get("field") or d.get("person") or ""})
    by_tool = Counter(e["tool"] for e in ev)
    return {"events": len(ev), "decisions": len(dec), "with_why": len(why), "by_tool": dict(by_tool),
            "top_reasons": chips.most_common(10), "gaps": [g for g in gaps.most_common(8) if g[0]],
            "accuracy": {"scored": len(scored), "hits": sum(p["hit"] for p in scored),
                         "weeks": [{"week": w, "hits": h, "n": n} for w, (h, n) in sorted(weeks.items())]},
            "expertise": {p: c.most_common(4) for p, c in sorted(expert.items(), key=lambda x: -sum(x[1].values()))[:12]},
            "rules": rules({}, 12, tool), "recent": recent, "chips": CHIPS, "opted_out": outs}


def export_rows():
    """Everything, anonymised (people become P1, P2...) - for the KTP report and a paper."""
    con = db()
    rows = [dict(r) for r in con.execute("SELECT at, tool, kind, who, context, chips, reason, data FROM events ORDER BY at")]
    con.close()
    names = {}
    for r in rows:
        r["who"] = names.setdefault(r["who"] or "-", f"P{len(names) + 1}") if r["who"] else ""
        r["data"] = (r["data"] or "")[:500]
    return rows


# ---------------------------------------------------------------- meeting notes (Socialisation -> Externalisation)

DECIDE = re.compile(r"\b(we (?:decided|agreed|chose|went with|should|need to|always|never|tend to)|client (?:wants|wanted|likes|liked|"
                    r"asked|said|prefers|hates)|they (?:want|wanted|like|prefer|asked)|i (?:like|prefer|always|never|would)|"
                    r"the trick is|rule of thumb|in my experience|what works|doesn'?t work|works better|the best way|"
                    r"value engineer|too (?:expensive|busy|plain|heavy)|cheaper|stronger|premium|tester|header|shelf|acrylic|mdf|"
                    r"powder ?coat|lightbox|flat ?pack)\b", re.I)


def add_notes(text, source="meeting", who="", context=None):
    """Meeting transcripts and notes: the sentences that carry a decision or a reason become insights, with the speaker
    when the transcript names one ("Andy Baxter 0:21 ..."). Free and rule-based - nothing leaves this PC."""
    text = re.sub(r"\s+", " ", text or "")
    speaker = ""
    found, seen = [], set()
    # a Teams export often names only whoever started the recording - trust names only when several people are tagged
    trust = len(set(re.findall(r"([A-Z][a-z]+ [A-Z][a-z]+)\s+\d{1,2}:\d{2}", text))) >= 2
    for part in re.split(r"(?<=[.!?])\s+|(?=\b[A-Z][a-z]+ [A-Z][a-z]+\s+\d{1,2}:\d{2})", text):
        m = re.match(r"([A-Z][a-z]+ [A-Z][a-z]+)\s+\d{1,2}:\d{2}\s*(.*)", part)
        if m:
            speaker, part = m.group(1), m.group(2)
        p = part.strip()
        if len(p) < 40 or len(p) > 400 or not (BECAUSE.search(p) and DECIDE.search(p) or re.search(r"\b(we (?:decided|agreed)|rule of thumb|"
                                                                                                    r"in my experience|the trick is|client (?:wants|asked))\b", p, re.I)):
            continue
        k = p.lower()[:80]
        if k in seen:
            continue
        seen.add(k)
        found.append(((speaker if trust else "") or who, p))
    n = 0
    for spk, p in found[:60]:
        cl = re.search(r"\b(Boots|No7|Superdrug|Tesco|Sainsbury'?s|M&S|Lindt|Milwaukee|TTI|Ryobi|Selfridges|John Lewis|L'?Or[eé]al|"
                       r"Viktor|Flowerbomb|Nespresso|Jo Malone)\b", p, re.I)
        ctx = dict(context or {}, **({"client": cl.group(1)} if cl else {}))
        eid = log("meeting", "meeting_insight", spk, source[:60], ctx, {"summary": p[:160], "source": source})
        if eid:
            con = db()
            con.execute("UPDATE events SET reason=?, reason_by=? WHERE id=?", (p[:400], spk[:60], eid))
            con.commit(); con.close()
            n += 1
    return n


def notes_text(path):
    """Text from a .docx / .txt / .md / .pdf of meeting notes."""
    p = path.lower()
    try:
        if p.endswith(".docx"):
            import zipfile, html as H
            x = zipfile.ZipFile(path).read("word/document.xml").decode("utf8")
            return H.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"</w:p>", "\n", x)))
        if p.endswith(".pdf"):
            from pypdf import PdfReader
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages[:40])
        return open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


def add_insight(text, who, source, context=None):
    """One insight picked from meeting notes by a person (or by Claude reading the notes in chat) - with who said it."""
    eid = log("meeting", "meeting_insight", who, source[:60], context or {}, {"summary": text[:160], "source": source})
    if eid:
        con = db()
        con.execute("UPDATE events SET reason=?, reason_by=? WHERE id=?", (text[:400], (who or "")[:60], eid))
        con.commit(); con.close()
    return eid
