import os
"""
lite_search.py - "what have we made before that looks like this?"

A brief ("Boots No7 shelf unit, oak, 1200 wide, floor standing") is matched
against SDI's own past work, two ways at once:
  - by picture: the brief's words against 269k images from W: (CLIP text->image,
    on this PC's GPU, free). Renders and visuals count, logos/maps/artwork don't.
  - by words: client and product words against job names, drawing titles and
    estimate descriptions.
Results are grouped per past JOB, so the answer is "we did 10474 Boots BRI
Triple Mod in 2023 - here are its renders, 14 drawings, quoted at GBP1,023 a unit".
"""
import datetime, json, os, re, sqlite3, threading
import numpy as np

BASE = r"C:\SDI_Automation"
HERE = os.path.join(BASE, "brief_lite")
_lock = threading.Lock()
_state = {}

STOP = set("""a an the and or of for to in on at by with from is are be it this that we they need needs want wants
like about around approx approximately roughly mm cm m metre metres meter meters unit units display displays
new client brief please would could should can will make made some one two three x by""".split())


def _load():
    with _lock:
        if _state:
            return _state
        z = np.load(os.path.join(BASE, "all_img_index.npz"))
        emb = z["emb"].astype(np.float32)
        con = sqlite3.connect(os.path.join(HERE, "projects.db"), check_same_thread=False)
        kinds = np.array([k for (k,) in con.execute("SELECT kind FROM project_images ORDER BY img_id")])
        jobs = [j for (j,) in con.execute("SELECT job_no FROM project_images ORDER BY img_id")]
        import torch
        from sentence_transformers import SentenceTransformer
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = SentenceTransformer("clip-ViT-B-32", device=dev)
        t = torch.from_numpy(emb).to(dev)
        if dev == "cuda":
            t = t.half()
        from collections import Counter
        df = Counter()
        for (txt,) in con.execute("SELECT name || ' ' || COALESCE(titles,'') FROM projects"):
            df.update(set(re.findall(r"[a-z0-9&]{2,}", norm(txt))))
        _state.update(df=df, n_jobs=sum(1 for _ in con.execute("SELECT 1 FROM projects")))
        _state.update(emb=t, kinds=kinds, jobs=jobs, model=model, dev=dev, con=con,
                      weight=np.where(kinds == "render", 1.0, np.where(kinds == "creative", 0.93, 0.80)).astype(np.float32))
        return _state


# Colour, finish and size words describe every job, so they say nothing about WHICH job. Words for the kind of unit
# (wall bay, gondola, pod, counter, FSDU, plinth) are the opposite - they are kept, and weighted by how rare they are.
GENERIC = set("""high wide deep tall height width depth mm cm metre metres white black grey gray silver gloss matt matte
oak wood wooden metal steel acrylic mdf finish colour color colours front back store shop with and the for of about
powder coated coat painted red blue green gold navy""".split())
TYPE_WORDS = set("""wall bay bays gondola end pod pods fsdu counter countertop plinth totem header shelf shelving tray kiosk
table cabinet cube column pegboard hooks till checkout window entrance gantry mezzanine""".split())


def norm(text):
    """'No 7' and 'No7', 'gondola-end' and 'gondola end' should match: glue letter+number pairs, drop punctuation."""
    t = re.sub(r"\b([a-z]{1,4})\s+(\d{1,3})\b", r"\1\2", (text or "").lower())
    return re.sub(r"[^a-z0-9&]+", " ", t)


def words(text):
    return [w for w in re.findall(r"[a-z0-9&]{2,}", norm(text)) if w not in STOP]


def rarity(w):
    """A word in few job names ('no7', 'liz', 'serum') says much more than one in thousands ('shelf', 'end')."""
    df = _state.get("df", {}).get(w, 0)
    n = max(_state.get("n_jobs", 1), 1)
    return 0.07 if df and df / n < 0.005 else 0.04 if df / n < 0.03 else 0.015


def image_hits(query, k=400):
    s = _load()
    import torch
    q = s["model"].encode([query], convert_to_tensor=True, normalize_embeddings=True).to(s["dev"])
    q = q.half() if s["dev"] == "cuda" else q
    sims = (s["emb"] @ q.T).squeeze(1).float().cpu().numpy() * s["weight"]
    top = np.argpartition(-sims, k)[:k]
    return sorted(((int(i), float(sims[i])) for i in top), key=lambda x: -x[1])


UNIT_PROMPTS = ["a freestanding retail display unit", "a shelf unit with products in a store", "a counter display stand",
                "a 3D render of a point of sale display fixture", "a gondola end display with shelves"]
NOT_UNIT_PROMPTS = ["abstract artwork or a graphic design", "a brand logo", "the inside of a store or an empty room",
                    "a photo of people", "a technical drawing sheet or floor plan", "a close up of a texture or material"]


def unit_probs(ids):
    """For each image: how likely it is a picture of a display unit (not artwork, a logo, a room or a drawing). Zero-shot CLIP."""
    s = _load()
    if "T" not in s:
        import torch
        t = s["model"].encode(UNIT_PROMPTS + NOT_UNIT_PROMPTS, convert_to_tensor=True, normalize_embeddings=True).to(s["dev"])
        s["T"] = t.half() if s["dev"] == "cuda" else t
    import torch
    logits = 100.0 * (s["emb"][ids] @ s["T"].T).float()
    return torch.softmax(logits, dim=1)[:, :len(UNIT_PROMPTS)].sum(dim=1).cpu().numpy()


def best_unit_images(job, query_vec, k=4, min_unit=0.45):
    """The k pictures of this job that are most (a) a real display unit and (b) like the brief. Empty if the job has none."""
    s = _load()
    ids = [i for (i,) in s["con"].execute(
        "SELECT img_id FROM project_images WHERE job_no=? AND kind IN ('render','creative') LIMIT 400", (job,))]
    if not ids:
        return []
    sims = (s["emb"][ids] @ query_vec.T).squeeze(1).float().cpu().numpy()
    top = np.argsort(-sims)[:120]
    ids, sims = [ids[i] for i in top], sims[top]
    up = unit_probs(ids)
    keep = [(i, float(sm), float(u)) for i, sm, u in zip(ids, sims, up) if u >= min_unit]
    keep.sort(key=lambda x: -(0.6 * x[2] + 4.0 * x[1]))
    out, seen = [], set()
    for i, sm, u in keep:                       # skip near-duplicate frames of the same view (animation sequences)
        v = s["emb"][i]
        if any(float((v @ s["emb"][j]).float()) > 0.965 for j in seen):
            continue
        seen.add(i)
        out.append((i, sm))
        if len(out) >= k:
            break
    return out


def project_rows(job_nos):
    s = _load()
    if not job_nos:
        return {}
    q = ",".join("?" * len(job_nos))
    cols = ["job_no", "name", "brand", "folder", "first_date", "last_date", "n_drawings", "n_images", "n_renders",
            "drawn_by", "titles", "weight_kg", "design_days", "designers"]
    rows = s["con"].execute(f"SELECT {','.join(cols)} FROM projects WHERE job_no IN ({q})", job_nos).fetchall()
    return {r[0]: dict(zip(cols, r)) for r in rows}


def estimate_text(job_nos):
    """What each job was quoted as on K: ('1m HDC Wall Bay', 'Battery wall bay + security'), lower-case, for word matching."""
    path = os.path.join(HERE, "knowledge.db")
    if not job_nos or not os.path.exists(path):
        return {}
    con = sqlite3.connect(path, timeout=5)
    out = {}
    try:
        for i in range(0, len(job_nos), 500):
            part = job_nos[i:i + 500]
            for j, d in con.execute(f"SELECT job_no, group_concat(description, ' ') FROM estimates WHERE job_no IN "
                                    f"({','.join('?' * len(part))}) GROUP BY job_no", part):
                out[j] = norm(d or "")
    except sqlite3.Error:
        pass
    con.close()
    return out


def estimates_for(job_nos):
    path = os.path.join(HERE, "knowledge.db")
    if not job_nos or not os.path.exists(path):
        return {}
    con = sqlite3.connect(path, timeout=5)
    q = ",".join("?" * len(job_nos))
    out = {}
    try:
        for r in con.execute(f"""SELECT job_no, description, qty, unit_cost, material_cost, labour_cost, est_date,
                                 prepared_by, materials, processes FROM estimates
                                 WHERE status='ok' AND unit_cost > 0 AND job_no IN ({q}) ORDER BY est_date DESC""", job_nos):
            out.setdefault(r[0], []).append(dict(zip(["job_no", "description", "qty", "unit_cost", "material_cost",
                                                      "labour_cost", "date", "prepared_by", "materials", "processes"], r)))
    except sqlite3.Error:
        pass
    con.close()
    # A job has many estimate sheets (header, shelf, the whole bay...). Put the WHOLE-unit one first: named after a fixture,
    # not a part, and the most expensive of those - so "quoted £964 a unit" means the bay, not a £2 logo block.
    part = re.compile(r"\b(headers?|shel(?:f|ves)|brackets?|panels?|graphics?|decals?|lens(?:es)?|logos?|blocks?|strips?|hooks?|"
                      r"labels?|stickers?|tickets?|clips?|spares?|kickers?|caps?|covers?|inserts?|castors?|knobs?|mirrors?|"
                      r"uprights?|toppers?|plinths?|rails?|trims?|kits?|wobblers?|shrouds?)\b", re.I)
    whole = re.compile(r"\b(bay|bays|fsdu|gondola|unit|stand|display|pod|kiosk|counter|plinth|totem|table|cabinet|wall|end)\b", re.I)
    for j, rows in out.items():
        rows.sort(key=lambda e: (not (whole.search(e["description"] or "") and not part.search(e["description"] or "")),
                                 -(e["unit_cost"] or 0)))
    return out


# 2 Nov 2026 (Andy's test): what the transcriber writes for SDI's own words
HEARD = [(r"\bfour[- ]?(courts?|cores?)\b", "forecourt"), (r"\b(cold|coal) ?(monkey|buncle|bunk|bunkle)s?\b|\bcolbunks?\b", "coal bunker"),
         (r"\bad ?blue\b", "adblue"), (r"\btamb(ador|or|our)\b", "tambour"), (r"\bfstu\b", "fsdu"),
         (r"\bgondala\b", "gondola"), (r"\broller ?shutter\b", "rollershutter")]


def heard_fix(t):
    for a, b in HEARD:
        t = re.sub(a, b, t, flags=re.I)
    return t


NAME_STOP = {"the", "and", "for", "unit", "units", "display", "stand", "new", "old", "version", "v1", "v2", "a", "of", "to", "in",
             "we", "our", "that", "this", "one", "refer", "previous", "previously", "please", "similar", "like", "made", "did",
             "base", "based", "use", "using", "follow", "make", "want", "thing", "kit", "the", "from", "with", "same",
             # 3 Nov 2026: time and filler words ('the latest gondola we made this month, I want it like that')
             "latest", "newest", "recent", "recently", "last", "month", "week", "year", "just", "made", "drew", "done",
             "drawing", "drawings", "need", "something", "those", "these", "they", "them", "did", "for", "was", "were",
             "job", "jobs", "what", "which", "have", "had", "could", "would", "show", "see", "can", "you", "about",
             "think", "there", "any", "all", "time", "ago", "client", "customer", "manufactured", "created", "produced",
             "variant", "existing", "previous", "within", "units", "please", "past", "earlier", "old", "sdi"}
# 3 Nov 2026: what AMs call a client vs how W: files it - TTi is Milwaukee, Ryobi and AEG
BRAND_ALIAS = {"tti": {"tti", "milwaukee", "ryobi", "aeg"}, "milwaukee": {"milwaukee", "tti"}, "ryobi": {"ryobi", "tti"},
               "aeg": {"aeg", "tti"}}
JUNK_JOB = re.compile(r"back-?ups?\b|\barchive|^\s*temp\b|old files|do not use|\bcopy of\b", re.I)
UNIT_WORDS = {"gondola", "bunker", "fsdu", "bay", "plinth", "totem", "counter", "kiosk", "cabinet", "dump", "bin", "header",
              "pod", "table", "shipper", "wall", "end", "stand"}


def named_jobs(text, client=""):
    """2 Nov 2026 (Andy): 'refer to drawing 12148' / 'the Forecourt Bunker Shell we did' - the past jobs the AM names, by job
    number or by name, so they lead the references instead of whatever the picture search finds."""
    s = _load()
    t = heard_fix((text or "").lower())
    out = []
    for m in re.finditer(r"\b(?:job|drawing|drawings|dwg|ga|project|ref|reference|number|no\.?|#)\s*(?:number\s*)?#?(\d{3,6})\b", t):
        j = m.group(1)
        if s["con"].execute("SELECT 1 FROM projects WHERE job_no=?", (j,)).fetchone() and j not in out:
            out.append(j)
    tw = {w for w in words(t) if len(w) > 2 and w not in NAME_STOP and not w.isdigit()}
    if tw:
        cw = set(words(client))
        best = []
        for j, nm, br in s["con"].execute("SELECT job_no, name, brand FROM projects"):
            nw = {w for w in words(f"{nm}") if len(w) > 2 and w not in NAME_STOP and not w.isdigit()}
            hit = nw & tw
            if len(hit) >= 2 and (not cw or cw & set(words(f"{br} {nm}"))):
                best.append((len(hit) / max(1, len(nw)) + 0.1 * len(hit), j))
        for _, j in sorted(best, reverse=True)[:2]:
            if j not in out:
                out.append(j)
    return out[:3]


SYN = {"bunker": {"coal", "fuel", "kindling", "forecourt", "pfs", "rollershutter", "logs", "firewood"},
       "coal": {"bunker", "fuel", "kindling"}, "forecourt": {"pfs", "petrol", "bunker"}, "pfs": {"forecourt", "petrol"},
       "shutter": {"rollershutter"}, "shutters": {"rollershutter"}, "roller": {"rollershutter"},
       "gondola": {"gondola", "end", "bay"}, "fsdu": {"floor", "standing", "stand"}, "wall": {"bay"}}
RECENT = re.compile(r"\b(latest|newest|most recent|recent(ly)?|last one|this (month|week|year)|last (month|week|year)|"
                    r"just (made|did|done)|we just (made|did|drew))\b", re.I)   # 'the bay we did' is not 'the latest'


def resolve_reference(text, client="", context=""):
    """2 Nov 2026 (Muhammad): the past job the AM means, however they put it - its number ('drawing 12148'), part of its
    name ('the coal bunker' when the job is '12148 - Rollershutter Forecourt Bunker'), its drawings' titles, or when it
    was made ('the latest one', 'the GA we did this month'). Returns {"pick": job or None, "options": [(job, name, date)],
    "ask": True when two or more fit about equally and the AM should choose}."""
    s = _load()
    t = heard_fix((text or "").lower())
    nums = named_jobs(t, client)
    if nums and re.search(r"\d{3,6}", t):
        rows = project_rows(nums)
        return {"pick": nums[0], "options": [(j, rows[j]["name"], rows[j]["last_date"]) for j in nums if j in rows], "ask": False}
    # 3 Nov 2026 (sweep over every big client): the words that say WHICH job ('wine', 'golf', 'No7') count far more than
    # the unit word, the client's own name counts for nothing (it's the filter), backup / archive folders are never
    # jobs, and a weak match is offered as a choice - never picked on its own.
    tw = {w for w in words(t) if len(w) > 2 and w not in NAME_STOP and not w.isdigit()}
    cw = set(words(client))
    for w in list(tw):              # a client named in the sentence ('for TTI') narrows it like the brief's client does
        if w in BRAND_ALIAS:
            cw |= BRAND_ALIAS[w]
    for w in list(cw):
        cw |= BRAND_ALIAS.get(w, set())
    said_client = tw & cw           # a client / sub-brand they SAID ('the Milwaukee dump bin'), not one from the brief
    tw -= cw
    if not tw and context:          # 'the last job we did for them' - the unit being briefed
        tw = {w for w in words(heard_fix(context.lower())) if len(w) > 2 and w not in NAME_STOP and not w.isdigit()} - cw
    if not tw:
        return {"pick": None, "options": [], "ask": False}     # nothing to match on - never guess a random job
    unit = tw & UNIT_WORDS - {"end", "wall", "stand"}   # 'a gondola' must be a gondola (or the thing they described)
    ctx_w = {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words(heard_fix((context or "").lower()))
             if len(w) > 3 and w not in NAME_STOP} - cw - {"unit", "display"}
    desc = tw - UNIT_WORDS
    want = set(tw)
    for w in tw:
        want |= SYN.get(w, set())
    recent = bool(RECENT.search(t))
    this_month = re.search(r"\bthis month\b", t) and datetime.date.today().strftime("%Y-%m")
    cand = []
    jobs = {}
    for j, nm, br, titles, last in s["con"].execute("SELECT job_no, name, brand, titles, last_date FROM projects"):
        if cw and not (cw & set(words(f"{br} {nm}"))):
            continue
        if JUNK_JOB.search(nm or "") or (nm or "").strip() == j:
            continue
        if not last and len([w for w in words(nm or "") if w.isalpha()]) < 2:
            continue                      # 'Entrance-0.' - a stray folder, not a job
        jobs[j] = (nm, last)
        nw = {w for w in words(nm or "") if len(w) > 2}
        nw |= {w[:-1] for w in nw if w.endswith("s") and len(w) > 4}    # 'Gondolas and Wall Bays' is a gondola
        tl = {w for w in words(titles or "") if len(w) > 2}
        tl |= {w[:-1] for w in tl if w.endswith("s") and len(w) > 4}
        # the job's NAME says what it is; a drawing title deep inside it ('wine' on one part of a Cheese Zone) much less
        score, strong_, unit_seen = 0.0, 0, False
        for w in tw:
            sy = SYN.get(w, set()) - {w}
            pts = 3 if w in nw else 1 if w in tl else 1.5 if sy & nw else 0.5 if sy & tl else 0
            score += pts * (2 if w in desc else 1)
            if pts and w in unit:
                unit_seen = True
            if pts >= 1.5 and (w in desc or not desc):
                strong_ = 1
        if unit and not unit_seen and not strong_:
            continue
        if score >= 1 and ctx_w:
            score += 1.5 * len(ctx_w & nw)     # 4 Nov 2026: the unit being briefed, as a tie-breaker
        if score >= 1 and said_client & set(words(nm or "")):
            score += 2                    # 'the Milwaukee dump bin' - the one with Milwaukee in its name first
        if score >= 1:
            cand.append([score, last or "", j, nm, strong_])
    # 2 Nov 2026: a fixture or file name inside a job ('the spit shelving', 'divider wall kit', 'parasite unit') counts too
    if tw and jobs and len(jobs) < 3000:
        have = {c[2]: c for c in cand}
        q = ",".join("?" * len(jobs))
        best = {}
        for j, fn in s["con"].execute(f"SELECT job_no, name FROM project_images WHERE job_no IN ({q})", list(jobs)):
            fw = {w for w in words((fn or "").lower()) if len(w) > 2 and not w.isdigit()}
            hit = len(tw & fw)
            if hit >= 2 or (hit == 1 and len(tw) == 1 and not (tw & UNIT_WORDS)):   # 'gondola' in a file name says little
                best[j] = max(best.get(j, (0, 0)), (hit, len(desc & fw)))
        for j, (hit, dh) in best.items():
            # a file named with their OWN describing words is a strong sign; one that only repeats the unit ('dump bin')
            # says little more than the job name already did
            if j in have:
                have[j][0] += 1.2 * dh + 0.3 * (hit - dh)
                have[j][4] = have[j][4] or int(dh > 0)
            elif dh:
                cand.append([1.2 * hit, jobs[j][1] or "", j, jobs[j][0], 1])
    if not cand:      # nothing like it: ask for the number - never offer the client's newest jobs that have nothing to do with it
        return {"pick": None, "options": [], "ask": False}
    strong = [c for c in cand if c[4] > 0]     # what they described is in the job's own name
    pool = strong or cand
    if recent:      # 'the latest bunker' - newest of the ones that fit
        top = max(c[0] for c in pool)
        pool = [c for c in pool if c[0] >= top - 0.5]
        if this_month and any(c[1][:7] == this_month for c in pool):
            pool = [c for c in pool if c[1][:7] == this_month]
        pool.sort(key=lambda c: c[1], reverse=True)
        return {"pick": pool[0][2] if strong else None, "options": [(c[2], c[3], c[1]) for c in pool[:3]],
                "ask": not strong, "weak": not strong}
    pool.sort(key=lambda c: (c[0], c[1]), reverse=True)
    opts = [(c[2], c[3], c[1]) for c in pool[:3]]
    ask = not strong or (len(pool) > 1 and pool[1][0] >= pool[0][0] - 0.25)   # weak, or two fit equally - AM chooses
    return {"pick": None if ask else pool[0][2], "options": opts, "ask": ask, "weak": not strong}


def live_pdfs(job, cap=400):
    return [r for r in live_files(job, cap * 4) if r[1].lower().endswith(".pdf")][:cap]


def live_files(job, cap=1600):
    """3 Nov 2026: a job newer than the last index (12738, Oct) has no PDFs in it yet - list its W: folder directly,
    read-only, so 'the gondola we did this month' still brings its real GA."""
    s = _load()
    r = s["con"].execute("SELECT folder FROM projects WHERE job_no=?", (job,)).fetchone()
    out = []
    if not r or not r[0] or not os.path.isdir(r[0]):
        return out
    for root, _, files in os.walk(r[0]):
        for f in files:
            if f.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
                out.append((os.path.splitext(f)[0], os.path.join(root, f)))
                if len(out) >= cap:
                    return out
    return out


def job_drawing_pages(job, n=2, hint=""):
    """The job's own GA drawing(s) from W:, page 1 as PNG - the real SDI drawing the new GA and render follow. hint: what the
    AM said, so 'the spit shelving GA' or 'the packaging spec' picks that very file."""
    import fitz
    s = _load()
    rows = s["con"].execute("SELECT name, src FROM project_images WHERE job_no=? AND lower(src) LIKE '%.pdf'", (job,)).fetchall()
    if not rows:
        rows = live_pdfs(job)
    hw = {w for w in words(heard_fix(hint.lower())) if len(w) > 2 and w not in NAME_STOP and not w.isdigit()}
    jr = s["con"].execute("SELECT name FROM projects WHERE job_no=?", (job,)).fetchone()
    hw -= set(words((jr[0] if jr else "") or "")) | {"show", "open", "see", "view", "drawing", "drawings", "one"}  # the job's own name picks no file
    def rank(r):
        nm = (r[0] or "").lower()
        asked = 4 * len(hw & {w for w in words(nm) if len(w) > 2})          # the file they named wins
        # 3 Nov 2026: SDI's top drawing is often '<job>-00 ...' or a 'design intent' / 'assembly' sheet, not called GA
        return (asked + ("ga1" in nm or "general assembl" in nm) * 3 + ("[ga]" in nm or "-ga" in nm or " ga" in nm) * 2
                + bool(re.search(rf"\b{re.escape(str(job))}-0?0\b", nm)) * 2 + ("design intent" in nm or "assembly" in nm) * 2
                # 3 Nov 2026: '2697 PFS Coal Bunker Headers' sat in 12148's folder - another job's drawing is not this job's GA
                - bool(re.match(r"\s*(\d{3,6})\b", nm) and re.match(r"\s*(\d{3,6})\b", nm).group(1) != str(job)) * 8
                - (not asked) * ("packag" in nm or "boxed" in nm or "o&m" in nm or "register" in nm or "instruction" in nm
                                 or "header" in nm or "decal" in nm or "artwork" in nm) * 5, nm)
    out = []
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "jobref")
    os.makedirs(d, exist_ok=True)
    seen = set()
    for nm, src in sorted(rows, key=rank, reverse=True):
        if rank((nm, src))[0] <= 0 or len(out) >= n:
            continue
        other = re.match(r"\s*(\d{3,6})(?!\d)", nm or "")      # '2697_PFS...' - an underscore is a word character
        if other and other.group(1) != str(job):
            continue                      # another job's drawing filed in this folder - never shown as this job's GA
        key = re.sub(r"(ga)?$", "", re.sub(r"[^a-z0-9]+", "", (nm or "").lower()))   # 'revJ', 'revJ ' and 'revA GA' are one drawing
        if key in seen:
            continue
        seen.add(key)
        png = os.path.join(d, re.sub(r"[^\w-]+", "_", f"{job}_{nm}")[:120] + ".png")
        try:
            if not os.path.exists(png):
                doc = fitz.open(src)
                doc[0].get_pixmap(dpi=110).save(png)
                doc.close()
            out.append(png)
        except Exception:
            continue
    return out


def job_pictures(job, n=3, hint=""):
    """The job's best pictures - any PNG / JPG on W: (renders first, or the one whose name the AM said) - as local paths."""
    s = _load()
    hw = {w for w in words(heard_fix(hint.lower())) if len(w) > 2 and w not in NAME_STOP and not w.isdigit()}
    rows = [r for r in s["con"].execute("SELECT src, name, kind FROM project_images WHERE job_no=? LIMIT 400", (job,))
            if r[0] and r[0].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    if not rows:        # 3 Nov 2026: a job newer than the index - its Renders folder on W:, read-only
        rows = [(src, nm, "render" if "render" in src.lower() else "other") for nm, src in live_files(job)
                if src.lower().endswith((".png", ".jpg", ".jpeg")) and not re.search(r"decal|maps|supplied|artwork|logo", src, re.I)]
    rows.sort(key=lambda r: (-4 * len(hw & set(words((r[1] or "").lower()))), {"render": 0, "creative": 1}.get(r[2], 2)))
    out = []
    for src, _, _ in rows:
        if os.path.exists(src):
            out.append(src)
        if len(out) >= n:
            break
    return out


def search(brief_text, client="", n=6, pin=()):
    """Best past jobs for a brief, each with its best-matching renders and what it cost. pin: jobs the AM named - always first."""
    s = _load()
    hits = image_hits(f"a retail display: {brief_text}")
    cw = set(words(client))
    # words that name the thing: no bare numbers (sizes), no size/colour/finish words that every job shares
    bw = {w for w in words(brief_text) if not w.isdigit() and w not in GENERIC} - cw
    per_job = {}
    for i, sim in hits:
        j = s["jobs"][i]
        if not j:
            continue
        d = per_job.setdefault(j, {"score": 0.0, "imgs": [], "best": 0.0})
        if len(d["imgs"]) < 4:
            d["imgs"].append((i, sim))
        d["best"] = max(d["best"], sim)
        # best picture, plus a little for up to 4 good ones - NOT per hit, or jobs with hundreds of images win by volume
        d["score"] = d["best"] + 0.004 * min(len(d["imgs"]), 4)
    # same client's own past jobs are always in the running, even if the picture match is weaker
    if cw:
        like = " OR ".join(["lower(brand) LIKE ? OR lower(name) LIKE ?"] * len(cw))
        args = [a for w in cw for a in (f"%{w}%", f"%{w}%")]
        for (j,) in s["con"].execute(f"SELECT job_no FROM projects WHERE n_renders>0 AND ({like})", args):
            per_job.setdefault(j, {"score": 0.0, "imgs": []})
    # jobs whose name or estimate says the same kind of unit for this client always get a look-in, even if no picture matched
    tws = [w for w in bw if w in TYPE_WORDS]
    if cw and tws:
        like = " OR ".join(["lower(name) LIKE ?"] * len(tws))
        cl = " OR ".join(["lower(brand) LIKE ? OR lower(name) LIKE ?"] * len(cw))
        for (j,) in s["con"].execute(f"SELECT job_no FROM projects WHERE n_renders>0 AND ({cl}) AND ({like})",
                                     [a for w in cw for a in (f"%{w}%", f"%{w}%")] + [f"%{w}%" for w in tws]):
            per_job.setdefault(j, {"score": 0.25, "imgs": []})
    for j in pin:
        per_job.setdefault(j, {"imgs": []})["score"] = 10.0
    est_text = estimate_text(list(per_job))
    info = project_rows(list(per_job))
    for j, d in per_job.items():
        p = info.get(j)
        if not p:
            continue
        txt = norm(f"{p['name']} {p['brand']} {p['titles']}")
        tw = set(txt.split())
        d["client"] = any(w in tw for w in cw)
        d["score"] += 0.15 * d["client"]                              # the client's own past work first
        d["score"] += min(0.14, sum(rarity(w) for w in bw if w in tw))   # same product line (No7) counts more than 'shelf'
        d["score"] += min(0.10, 0.05 * sum(1 for w in bw & TYPE_WORDS if w in tw))   # same KIND of unit (wall bay, pod)
        et = est_text.get(j, "")
        d["score"] += min(0.08, 0.04 * sum(1 for w in bw & TYPE_WORDS if w in et))   # ...or quoted as one on K:
    def named(j):   # '4704' or 'Entrance-0' tell the AM nothing: skip jobs that have no real name
        nm = (info[j]["name"] or "").strip()
        rest = re.sub(r"^\d+[\s-]*", "", nm).strip(" .-")
        # a real job is called "<job number> - <name>", or has drawings behind it; "Entrance-0." is a stray render folder
        real = nm.startswith(str(j)) or (info[j]["n_drawings"] or 0) > 0
        junk = re.search(r"back-?ups?|archive|^old\b|supplied", rest, re.I)
        return real and not junk and not str(j).startswith("00") and len(rest) >= 5 and not re.fullmatch(r"[\w -]{1,12}-\d+", rest)
    order = sorted((j for j in per_job if j in info and (j in pin or named(j))), key=lambda j: -per_job[j]["score"])
    # mostly the client's own jobs, but always a couple of the best look-alikes from anyone
    # A Boots brief shows Boots work. Other clients only fill in when this client has fewer than 3 matching jobs.
    mine = [j for j in order if per_job[j].get("client") or j in pin] if cw else []
    ranked_all = (mine if len(mine) >= 3 else mine + [j for j in order if j not in mine])[:n * 4]   # extra, some get dropped below
    # Pictures: for every job, the ones that are really a display unit and look like THIS brief. A job whose pictures are only
    # artwork, a logo or a shop interior ("Entrance-0") is dropped - it tells the AM nothing about the unit.
    q = s["model"].encode([f"a retail display: {brief_text}"], convert_to_tensor=True, normalize_embeddings=True).to(s["dev"])
    q = q.half() if s["dev"] == "cuda" else q
    kept = []
    for j in ranked_all:
        imgs = best_unit_images(j, q)
        if not imgs and j in pin:   # a named job with only drawings/photos (12148): still shown, with its first pictures
            imgs = [(i, 0.0) for (i,) in s["con"].execute("SELECT img_id FROM project_images WHERE job_no=? ORDER BY "
                                                          "CASE kind WHEN 'render' THEN 0 WHEN 'creative' THEN 1 ELSE 2 END, img_id LIMIT 4", (j,))]
        if imgs:
            per_job[j]["imgs"] = imgs
            kept.append(j)
        if len(kept) >= n:
            break
    ranked = kept
    est = estimates_for(ranked)
    out = []
    for j in ranked:
        p = dict(info[j])
        for k in ("drawn_by", "titles", "design_days", "designers"):
            p[k] = json.loads(p[k] or "null")
        imgs = []
        for i, sim in per_job[j]["imgs"]:
            row = s["con"].execute("SELECT thumb, src, name, kind FROM project_images WHERE img_id=?", (i,)).fetchone()
            if row:
                imgs.append({"id": i, "thumb": row[0], "src": row[1], "name": row[2], "kind": row[3], "sim": round(sim, 3)})
        p.update(score=round(per_job[j]["score"], 3), images=imgs, estimates=est.get(j, [])[:3])
        out.append(p)
    return out


if __name__ == "__main__":
    import sys, time
    t = time.time()
    res = search(" ".join(sys.argv[2:]) or "floor standing shelf unit oak", client=sys.argv[1] if len(sys.argv) > 1 else "")
    print(f"{time.time() - t:.1f}s")
    for r in res:
        e = r["estimates"][0] if r["estimates"] else {}
        print(f"{r['job_no']:>7} {r['score']:.3f} {r['brand'][:18]:18} {r['name'][:50]:50} {r['first_date']}..{r['last_date']} "
              f"dwg={r['n_drawings']} renders={r['n_renders']} est={e.get('unit_cost')}")
        for im in r["images"][:2]:
            print("          ", im["kind"], im["sim"], im["name"][:60])
