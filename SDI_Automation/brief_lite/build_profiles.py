"""
build_profiles.py - what SDI already knows about each big client, before a brief arrives.

For Boots, M&S, Tesco, TTI (Milwaukee/Ryobi/AEG), Lindt, Superdrug, Harrods... from the indexes on C:
  - how many jobs, and the kinds of unit SDI makes for them most (wall bays, FSDUs, gondola ends...)
  - the materials and processes on their estimates (Black Tex MDF, powder coat colours, acrylic...)
  - what whole units were quoted at, by kind (median and range)
  - the most recent jobs
Brief Lite reads client_profiles.json so it can talk like someone who has done this client's work for years.
Read only on W:/K: data - this only reads projects.db and knowledge.db. Re-run any time (seconds).
"""
import json, os, re, sqlite3, statistics
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "client_profiles.json")
TYPES = {
    "wall bay": r"wall ?bay|bays?\b|pod wall|wall pod|wall unit|wall display",
    "gondola end": r"gondola|\bend\b|aisle end|end cap",
    "FSDU / floor stand": r"fsdu|floor ?stand|free ?standing|totem|plinth|column",
    "counter / CDU": r"counter|cdu|countertop|till|checkout",
    "shelf / tray system": r"shelf|shelves|tray|strip|shelf edge",
    "header / signage": r"header|sign|signage|graphic|lightbox|light box",
    "table / promo": r"table|promo|feature|island",
    "store fit / concept": r"store|concept|fit ?out|refit|layout|launch",
}
PART = re.compile(r"\b(headers?|shel(?:f|ves)|brackets?|panels?|graphics?|decals?|lens(?:es)?|logos?|blocks?|strips?|hooks?|"
                  r"labels?|stickers?|tickets?|clips?|spares?|kickers?|caps?|covers?|inserts?|dividers?|risers?|castors?|foot|feet|"
                  r"knobs?|mirrors?|lightbox(?:es)?|proto(?:type)?|frame assembly|uprights?|toppers?|plinths?|rails?|trims?|"
                  r"edges?|bars?|kits?|wobblers?|shrouds?|fixings?)\b", re.I)


def mat_key(m):
    """'Powder - Red RAL 3020 Semi Gloss' and 'Powder RAL 3020 Red' are one material; 'mm MDF' alone says nothing."""
    ral = re.search(r"ral\s*(\d{4})", m, re.I)
    if ral:
        return "ral" + ral.group(1)
    return re.sub(r"[^a-z]+", " ", m.lower()).strip()
WHOLE = re.compile(r"\b(bay|bays|fsdu|gondola|unit|stand|display|pod|kiosk|counter|plinth|totem|table|cabinet|wall|end)\b", re.I)
MAT = re.compile(r"(\d+\s*mm\s+)?([A-Za-z][A-Za-z /&-]*?(mdf|ply|acrylic|petg|perspex|steel|ral \d{4}|powder[^,;]*|oak|laminate|"
                 r"glass|aluminium|wire|melamine|foamex|dibond|led)[A-Za-z0-9 /&-]{0,25})", re.I)
CLIENTS = {   # profile name -> words that pick its jobs (brand field or job name) and its estimates (customer)
    "Boots": ["boots", "no7", "liz earle"], "M&S": ["m&s", "marks"], "Tesco": ["tesco"], "TTI": ["tti", "milwaukee", "ryobi", "aeg"],
    "Lindt": ["lindt"], "Superdrug": ["superdrug"], "Harrods": ["harrods"], "AS Watson": ["as watson", "tps", "perfume shop"],
    "Unilever": ["unilever"], "Perfetti Van Melle": ["perfetti", "chupa", "mentos"], "Jewells": ["jewells", "essity"],
}


def kind_of(text):
    t = (text or "").lower()
    return next((k for k, p in TYPES.items() if re.search(p, t)), None)


def main():
    pc = sqlite3.connect(os.path.join(HERE, "projects.db"))
    kc = sqlite3.connect(os.path.join(HERE, "knowledge.db"))
    out = {}
    for name, words in CLIENTS.items():
        like = " OR ".join(["lower(brand) LIKE ? OR lower(name) LIKE ?"] * len(words))
        args = [a for w in words for a in (f"%{w}%", f"%{w}%")]
        jobs = pc.execute(f"SELECT job_no, name, last_date, n_drawings, n_renders FROM projects WHERE ({like})", args).fetchall()
        kinds = Counter(k for _, n, *_ in jobs if (k := kind_of(n)))
        recent = sorted((j for j in jobs if j[2] and j[3]), key=lambda j: j[2], reverse=True)[:6]
        el = " OR ".join(["lower(customer) LIKE ? OR lower(client_folder) LIKE ?"] * len(words))
        ests = kc.execute(f"SELECT job_no, description, qty, unit_cost, materials, processes, est_date FROM estimates "
                          f"WHERE status='ok' AND unit_cost>0 AND ({el})", args).fetchall()
        by_kind, mats, procs, names = defaultdict(list), Counter(), Counter(), {}
        for j, desc, qty, uc, m, p, dt in ests:
            if WHOLE.search(desc or "") and not PART.search(desc or "") and uc >= 40:   # under GBP40 is a part
                by_kind[kind_of(desc) or "other unit"].append((uc, qty, desc, j, dt))
            for line in json.loads(m or "[]"):
                hit = MAT.search(line or "")
                if hit:
                    m = re.sub(r"\s+", " ", hit.group(0)).strip()[:60]
                    m = re.sub(r"(?i)^used\s+", "", m)          # 3 Nov 2026: 'Used White RAL 9003' reached a brief PDF
                    m = m.rstrip(")").strip() if m.count(")") > m.count("(") else m
                    if len(re.sub(r"(?i)\b\d+\s*mm\b|\bmdf\b", "", m).strip()) >= 4 and not re.search(r"(?i)knob|screw|bolt|castor", m):
                        mats[mat_key(m)] += 1
                        names.setdefault(mat_key(m), m)
            procs.update(json.loads(p or "[]"))
        quotes = {}
        for k, rows in by_kind.items():
            costs = [r[0] for r in rows]
            ex = sorted(sorted(rows, key=lambda r: r[4] or "", reverse=True)[:12], key=lambda r: -r[0])[:3]   # recent, biggest first
            quotes[k] = {"n": len(rows), "median": round(statistics.median(costs)), "low": round(min(costs)), "high": round(max(costs)),
                         "examples": [f"{r[3]} {r[2][:45]} - £{r[0]:,.0f}" + (f" x{int(r[1])}" if r[1] else "") + (f" ({r[4][:7]})" if r[4] else "")
                                      for r in ex]}
        out[name] = {"words": words, "jobs": len(jobs), "renders": sum(j[4] or 0 for j in jobs),
                     "kinds": kinds.most_common(5), "materials": [names[m] for m, _ in mats.most_common(8)],
                     "processes": [p for p, _ in procs.most_common(6)], "quotes": quotes,
                     "recent": [f"{j[0]} {re.sub(r'^' + re.escape(str(j[0])) + r'[ -]*', '', j[1])[:50]} ({j[2][:4]})" for j in recent]}
        print(f"{name:20} {len(jobs):5} jobs  {len(ests):5} estimates  kinds={kinds.most_common(3)}")
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("->", OUT)


if __name__ == "__main__":
    main()
