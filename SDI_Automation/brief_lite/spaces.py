"""
spaces.py - Spaces: the AM's own inspiration libraries (Andy, 13 Oct 2026: "I photographed every one of the ~350
permanent trays in Boots and put them in a ChatGPT Space - the difference it makes to the output is unbelievable").

A Space is a named collection of photos (and notes) - "Boots Permanent Trays", "Consumer Electronics", "Andy's style".
Every photo is, once, on this PC:
  - shrunk to a 1600px copy (renders) and a 480px thumb (the page) - the original is not kept
  - described by Claude Haiku vision as tags a designer would use (unit, retailer, materials, header, tester, shelves)
  - fingerprinted with CLIP, the same model that searches SDI's 269k past-work images
Then every concept render looks across the Spaces for the photos closest to the brief and uses them as inspiration,
so a fragrance gondola end for Boots is drawn in the language of the 350 trays Andy photographed - not just SDI's own.

Spaces are shared: one AM's library helps the whole sales team (a ChatGPT Space is personal).
Everything stays in brief_lite/out/spaces/ on C:. W: and K: are never written.
"""
import base64, io, json, os, re, sqlite3, threading, time, uuid
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "out", "spaces")
DB = os.path.join(HERE, "lite.db")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
DOC_EXT = (".pdf", ".docx", ".txt", ".md")
VISION_MODEL = "claude-haiku-5-5"   # 21 Oct 2026: was claude-haiku-4-5
_lock = threading.RLock()
_queue = []                      # (space_id, item_id) still to tag + fingerprint
_worker = {"t": None}
_cache = {}                      # space_id -> (mtime, items, emb)
G = {}                           # spent_today / daily_cap / log_cost / clip, bound by lite_app


def bind(**kw):
    G.update(kw)


def db():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS spaces (id TEXT PRIMARY KEY, name TEXT, about TEXT, created TEXT, owner TEXT, "
                "state TEXT DEFAULT 'live')")
    return con


def _dir(sid):
    d = os.path.join(ROOT, re.sub(r"[^\w-]", "", sid))
    os.makedirs(os.path.join(d, "img"), exist_ok=True)
    return d


def _index_p(sid):
    return os.path.join(_dir(sid), "index.json")


def items(sid):
    try:
        return json.load(open(_index_p(sid), encoding="utf-8"))
    except Exception:
        return []


def _save_items(sid, its):
    p = _index_p(sid)
    tmp = p + ".tmp"
    json.dump(its, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, p)
    _cache.pop(sid, None)


# ---------------------------------------------------------------- spaces

def create(name, about="", owner=""):
    name = re.sub(r"\s+", " ", name or "").strip()[:60]
    if not name:
        raise ValueError("give the Space a name")
    con = db()
    r = con.execute("SELECT id FROM spaces WHERE lower(name)=lower(?) AND state='live'", (name,)).fetchone()
    if r:
        con.close()
        return r["id"]
    sid = "s_" + uuid.uuid4().hex[:8]
    con.execute("INSERT INTO spaces (id, name, about, created, owner, state) VALUES (?,?,?,?,?, 'live')",
                (sid, name, (about or "").strip()[:2000], datetime.now().isoformat(timespec="seconds"), owner[:60]))
    con.commit(); con.close()
    _dir(sid)
    return sid


def update(sid, name=None, about=None):
    con = db()
    if name is not None and name.strip():
        con.execute("UPDATE spaces SET name=? WHERE id=?", (name.strip()[:60], sid))
    if about is not None:
        con.execute("UPDATE spaces SET about=? WHERE id=?", (about.strip()[:2000], sid))
    con.commit(); con.close()


def remove(sid):
    """Archived, not destroyed: the photos stay on C: and the Space can be brought back."""
    con = db()
    con.execute("UPDATE spaces SET state='archived' WHERE id=?", (sid,))
    con.commit(); con.close()


def get(sid):
    con = db()
    r = con.execute("SELECT * FROM spaces WHERE id=? AND state='live'", (sid,)).fetchone()
    con.close()
    return dict(r) if r else None


def all_spaces():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM spaces WHERE state='live' ORDER BY created")]
    con.close()
    for r in rows:
        its = items(r["id"])
        r["n"] = len(its)
        r["pending"] = sum(1 for i in its if i.get("status") == "new")
        r["covers"] = [i["thumb"] for i in its if i.get("thumb")][-4:]
    return rows


# ---------------------------------------------------------------- adding photos

def add(sid, paths, added_by=""):
    """Copy photos in (shrunk), queue them for tagging + fingerprinting. Returns how many were added."""
    from PIL import Image, ImageOps
    d = _dir(sid)
    with _lock:
        its = items(sid)
        have = {i.get("src_name") for i in its}
        n = 0
        for p in paths:
            name = os.path.basename(p)
            ext = os.path.splitext(name)[1].lower()
            if name in have:
                continue
            iid = uuid.uuid4().hex[:10]
            rec = {"id": iid, "src_name": name, "added_by": added_by[:60], "at": datetime.now().isoformat(timespec="seconds")}
            try:
                if ext in IMG_EXT:
                    im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
                    big = os.path.join(d, "img", iid + ".jpg")
                    small = os.path.join(d, "img", iid + "_t.jpg")
                    im2 = im.copy(); im2.thumbnail((1600, 1600)); im2.save(big, "JPEG", quality=88)
                    im3 = im.copy(); im3.thumbnail((480, 480)); im3.save(small, "JPEG", quality=80)
                    rec.update(kind="image", path=big, thumb=small, w=im.width, h=im.height, status="new")
                elif ext in DOC_EXT:
                    dst = os.path.join(d, "img", iid + ext)
                    import shutil
                    shutil.copy2(p, dst)
                    rec.update(kind="doc", path=dst, status="new")
                else:
                    continue
            except Exception as e:
                rec.update(kind="bad", status="bad", why=str(e)[:120])
                continue
            its.append(rec)
            _queue.append((sid, iid))
            n += 1
        _save_items(sid, its)
    _kick()
    return n


def drop(sid, iid):
    with _lock:
        its = [i for i in items(sid) if i["id"] != iid]
        _save_items(sid, its)
        emb_p = os.path.join(_dir(sid), "emb.npz")
        if os.path.exists(emb_p):
            z = dict(np.load(emb_p))
            ids = list(z["ids"])
            if iid in ids:
                k = ids.index(iid)
                np.savez(emb_p, ids=np.array(ids[:k] + ids[k + 1:]), emb=np.delete(z["emb"], k, axis=0))


def _kick():
    if _worker["t"] and _worker["t"].is_alive():
        return
    t = threading.Thread(target=_work, daemon=True)
    _worker["t"] = t
    t.start()


def requeue_unfinished():
    """On start-up: anything added but not yet tagged (the PC restarted) goes back in the queue."""
    for s in all_spaces():
        for i in items(s["id"]):
            if i.get("status") == "new":
                _queue.append((s["id"], i["id"]))
    if _queue:
        _kick()


TAG_PROMPT = ("You are tagging a photo for a retail display designer's inspiration library. Reply with JSON only:\n"
              '{"what": "one line - what this is (a unit in store, product packshot, artwork, sketch, material sample)",'
              ' "unit": "unit type (gondola end, permanent tray, FSDU, counter unit, wall bay, plinth, totem, shelf strip...) or none",'
              ' "retailer": "store if you can tell (Boots, Superdrug, Selfridges...) or unknown",'
              ' "brands": ["brands visible"], "category": "fragrance / skincare / cosmetics / electronics / food / ...",'
              ' "materials": ["acrylic", "MDF", "steel", "glass", "wood", ...], "colours": ["main colours"],'
              ' "header": "header / graphic treatment (lightbox, fabric, printed panel, none)",'
              ' "testers": "how testers are shown, or none", "shelves": "shelf count and profile (stepped, flat, angled, lipped)",'
              ' "lighting": "lit shelves / backlit / none", "idea": "the one design idea worth stealing, in 12 words"}')


def _tag(path, sid):
    """Haiku vision on a 768px copy: ~0.1p a photo."""
    try:
        if G.get("spent_today") and G["spent_today"]() >= G["daily_cap"]():
            return None
        import anthropic
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im.thumbnail((768, 768))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=80)
        r = anthropic.Anthropic().messages.create(model=VISION_MODEL, max_tokens=1024, output_config={"effort": "low"}, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": TAG_PROMPT}]}])
        if G.get("log_cost"):
            G["log_cost"]("space:" + sid, "space-tag", r.usage.input_tokens / 1e6 * 0.10 + r.usage.output_tokens / 1e6 * 0.50)
        txt = "".join(x.text for x in r.content if x.type == "text")
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else {"what": txt[:200]}
    except Exception:
        return None


# Free tagging (13 Oct 2026: 532 photos at ~0.15p each would have used the day's whole budget). CLIP - already on this
# PC for the fingerprints - picks the closest words from fixed lists. Not as rich as a vision model, but it costs nothing.
LISTS = {
    "unit": ["gondola end", "permanent tray on a shelf", "counter top display unit", "floor standing display unit",
             "wall bay of shelves", "shelf edge strip", "totem", "plinth with products", "pegboard wall with hooks",
             "glass cabinet", "shop window display", "store interior", "product packshot on white", "hand sketch drawing",
             "logo or artwork graphic"],
    "category": ["fragrance and perfume", "skincare", "make-up and cosmetics", "haircare", "power tools", "consumer electronics",
                 "food and drink", "chocolate and confectionery", "fashion and accessories", "toys", "pharmacy and health"],
    "materials": ["clear acrylic", "white gloss acrylic", "coloured acrylic", "natural wood", "painted MDF", "black metal",
                  "white powder coated steel", "chrome and mirror", "glass", "cardboard", "marble or stone", "fabric"],
    "header": ["backlit lightbox header", "printed header panel", "digital screen", "no header"],
    "lighting": ["LED lit shelves", "backlit graphics", "no lighting"],
    "testers": ["tester bottles at the front", "products boxed only"],
}
_vecs = {}


def _clip_tags(v):
    m = _clip()
    if m is None or v is None:
        return {"what": "photo"}
    out = {}
    for k, words in LISTS.items():
        if k not in _vecs:
            _vecs[k] = m.encode([f"a photo of {w}" for w in words], convert_to_numpy=True, normalize_embeddings=True)
        sims = _vecs[k] @ v
        order = list(np.argsort(-sims))
        if k == "materials":
            out[k] = [words[j] for j in order[:2]]
        else:
            out[k] = words[order[0]]
    out["what"] = f"{out['unit']} - {out['category']}"
    out["shelves"] = ""
    return out


def _doc_text(path):
    try:
        if path.lower().endswith((".txt", ".md")):
            return open(path, encoding="utf-8", errors="ignore").read()[:6000]
        if path.lower().endswith(".pdf"):
            from pypdf import PdfReader
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages[:15])[:6000]
        if path.lower().endswith(".docx"):
            import docx
            return "\n".join(p.text for p in docx.Document(path).paragraphs)[:6000]
    except Exception:
        pass
    return ""


def _work():
    while _queue:
        sid, iid = _queue.pop(0)
        with _lock:
            its = items(sid)
            rec = next((i for i in its if i["id"] == iid), None)
        if not rec or rec.get("status") != "new":
            continue
        if rec["kind"] == "doc":
            rec["text"] = _doc_text(rec["path"])
            rec["tags"] = {"what": (rec["text"][:120] or "document").replace("\n", " ")}
            rec["status"] = "ready"
        else:
            emb = _embed_image(rec["path"])
            tags = _tag(rec["path"], sid) if os.environ.get("SPACE_TAG_AI") == "1" else _clip_tags(emb)
            if emb is not None:
                _store_emb(sid, iid, emb)
            rec["tags"] = tags or rec.get("tags") or {"what": "photo"}
            rec["status"] = "ready" if emb is not None else "new"
            if emb is None:            # CLIP not up yet: try again later
                time.sleep(5)
                _queue.append((sid, iid))
        with _lock:
            its = items(sid)
            for k, i in enumerate(its):
                if i["id"] == iid:
                    its[k] = rec
            _save_items(sid, its)


def _clip():
    try:
        return G["clip"]()
    except Exception:
        return None


def _embed_image(path):
    m = _clip()
    if m is None:
        return None
    try:
        from PIL import Image
        v = m.encode([Image.open(path).convert("RGB")], convert_to_numpy=True, normalize_embeddings=True)[0]
        return v.astype(np.float32)
    except Exception:
        return None


def _store_emb(sid, iid, v):
    p = os.path.join(_dir(sid), "emb.npz")
    with _lock:
        if os.path.exists(p):
            z = dict(np.load(p))
            ids, emb = list(z["ids"]), z["emb"]
            if iid in ids:
                emb[ids.index(iid)] = v
            else:
                ids.append(iid); emb = np.vstack([emb, v[None, :]])
        else:
            ids, emb = [iid], v[None, :]
        np.savez(p, ids=np.array(ids), emb=emb)
        _cache.pop(sid, None)


def _load_emb(sid):
    p = os.path.join(_dir(sid), "emb.npz")
    if not os.path.exists(p):
        return [], None
    mt = os.path.getmtime(p)
    c = _cache.get(sid)
    if c and c[0] == mt:
        return c[1], c[2]
    z = np.load(p)
    ids, emb = list(z["ids"]), z["emb"].astype(np.float32)
    _cache[sid] = (mt, ids, emb)
    return ids, emb


# ---------------------------------------------------------------- using them

def tag_line(rec):
    t = rec.get("tags") or {}
    bits = [t.get("what"), t.get("unit") if t.get("unit") not in (None, "none") else None,
            ("materials: " + ", ".join(t["materials"])) if t.get("materials") else None,
            ("header: " + t["header"]) if t.get("header") and t["header"] != "none" else None,
            ("testers: " + t["testers"]) if t.get("testers") and t["testers"] != "none" else None,
            ("shelves: " + t["shelves"]) if t.get("shelves") else None,
            ("idea: " + t["idea"]) if t.get("idea") else None]
    return "; ".join(b for b in bits if b)[:260]


def search(query, linked=(), k=4, skip=(), min_sim=0.21, at_least=0):
    """The Space photos closest to the brief, across every Space (a Space linked to this chat counts a little more).
    Returns [{space, name, path, thumb, sim, line}]. Below min_sim nothing is used - better no inspiration than wrong -
    except at_least: the AM chose this Space for the brief, so its closest photos are used even when none score high
    (27 Oct 2026, Muhammad: "a Space or a file the AM gives must always be a reference")."""
    m = _clip()
    if m is None or not (query or "").strip() or not linked:      # only the Spaces this chat uses (Muhammad, 13 Oct)
        return []
    q = m.encode([query[:300]], convert_to_numpy=True, normalize_embeddings=True)[0].astype(np.float32)
    out = []
    for sp in all_spaces():
        if sp["id"] not in linked:
            continue
        ids, emb = _load_emb(sp["id"])
        if emb is None or not len(ids):
            continue
        sims = emb @ q
        bonus = 0.03 if sp["id"] in linked else 0.0
        recs = {i["id"]: i for i in items(sp["id"])}
        for j in np.argsort(-sims)[:k * 3]:
            iid = ids[j]
            r = recs.get(iid)
            if not r or iid in skip or not os.path.exists(r.get("path", "")):
                continue
            out.append({"space": sp["name"], "space_id": sp["id"], "id": iid, "path": r["path"], "thumb": r.get("thumb"),
                        "sim": float(sims[j]) + bonus, "line": tag_line(r)})
    out.sort(key=lambda x: -x["sim"])
    return [o for o in out if o["sim"] >= min_sim][:k] or out[:min(k, at_least)]


def notes_for(linked):
    """The 'about' text of the Spaces linked to a chat - the AM's standing instructions ('I want it to feel premium, never MDF')."""
    out = []
    for sid in linked or []:
        sp = get(sid)
        if sp and (sp.get("about") or "").strip():
            out.append(f"{sp['name']}: {sp['about'].strip()[:600]}")
        for i in items(sid):
            if i.get("kind") == "doc" and i.get("text"):
                out.append(f"{sp['name'] if sp else sid} note {i['src_name']}: {i['text'][:500]}")
    return "\n".join(out)[:2500]
