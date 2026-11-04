"""
moodboard.py - "it found the best things on the internet" (Andy, 13 Oct 2026, on why ChatGPT's Flowerbomb concept beat ours).

Before the first concept, Brief Lite looks outside SDI too:
  1. Claude (with web search) finds the pages that show the brief's REAL products (the actual Flowerbomb bottle and box)
     and strong examples of this kind of unit in this kind of store.
  2. The pictures on those pages are fetched (only pictures; each one re-saved as a plain JPEG on C:), and CLIP keeps
     the ones that really are that product / that kind of display - no logos, banners or wrong products.
  3. The AM sees them as a moodboard, can strike any out, and the concepts use them: products as the exact packs to put
     on the shelves, the displays as the standard to beat.
Cost: ~3-6p (a few web searches + one small model call). Pictures are for internal concept reference only.
"""
import io, json, os, re, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "out", "mood")
MODEL = "claude-sonnet-5-5"   # 21 Oct 2026: was claude-haiku-4-5 - better at finding the real products
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9", "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,*/*;q=0.8"}
G = {}
SKIP_HOST = ("pinterest.", "instagram.", "facebook.", "tiktok.", "youtube.", "x.com", "twitter.")


def bind(**kw):
    G.update(kw)


def wants_moodboard(b):
    """Worth a look online when the brief names real products/brands, or a unit type for a known retailer."""
    words = " ".join(str(b.get(k) or "") for k in ("hero_products", "products_held", "colours_graphics", "narrative", "brand_assets"))
    return bool(re.search(r"[A-Z][a-z]+|[A-Z]{2,}|&", words)) or bool(b.get("unit_type") and (b.get("client") or b.get("retailer")))


PLAN = """You are researching references for a retail display designer at SDI Displays (UK). The brief:
{brief}

Use web search to find:
1. PRODUCTS: the real products this unit will hold, if the brief names any brand or product (e.g. "Viktor&Rolf Flowerbomb").
   For each (max 2), up to 5 product-page URLs that show a clear packshot - prefer big UK retailers (johnlewis.com,
   lookfantastic.com, selfridges.com, harveynichols.com, feelunique, notino.co.uk, superdrug.com, amazon.co.uk) and the brand
   site.
2. INSPIRATION: up to 6 page URLs showing excellent real examples of this kind of display in this kind of store/category
   (retail design press like retail-focus.co.uk, retaildesignblog.net, vmsd.com, design agency case studies, award entries).
   Pages whose main picture IS the display.
Reply with JSON only:
{{"products": [{{"name": "...", "pages": ["url", ...]}}], "inspiration": [{{"what": "...", "pages": ["url", ...]}}]}}"""


def _plan(b, sid):
    import anthropic
    brief = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in b.items()
                      if not k.startswith("_") and v and k in ("client", "retailer", "unit_type", "placement", "hero_products",
                                                               "products_held", "materials", "colours_graphics", "lighting",
                                                               "narrative", "size"))[:1500]
    msgs = [{"role": "user", "content": PLAN.format(brief=brief)}]
    content = []
    for _ in range(3):   # a long search can come back as pause_turn: send it back as it is and let it carry on
        r = anthropic.Anthropic(timeout=200, max_retries=1).messages.create(
            model=MODEL, max_tokens=8000, output_config={"effort": "medium"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}], messages=msgs)
        try:
            u = r.usage
            searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
            G["log_cost"](sid, "moodboard-search", u.input_tokens / 1e6 * 2.0 + u.output_tokens / 1e6 * 10.0 + searches * 0.01)
        except Exception:
            pass
        content += list(r.content)
        if r.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": r.content}]
    txt = "".join(getattr(x, "text", "") for x in content if getattr(x, "type", "") == "text")
    os.makedirs(os.path.join(ROOT, sid), exist_ok=True)
    open(os.path.join(ROOT, sid, "plan.txt"), "w", encoding="utf-8").write(txt)
    for m in reversed(list(re.finditer(r"\{.*\}", txt, re.S))):
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    # no clean JSON: the URLs it found still help - the first ones are usually the product pages
    urls = re.findall(r"https?://[^\s\"'<>)\]]+", txt)
    return {"products": [{"name": str(b.get("hero_products") or b.get("client") or ""), "pages": urls[:5]}],
            "inspiration": [{"what": str(b.get("unit_type") or "display"), "pages": urls[5:10]}]} if urls else {}


def _bigger(url):
    """Retailer CDNs serve thumbnails by default - ask for the large one."""
    url = re.sub(r"\$rsp-pdp-port-\d+\$", "$rsp-pdp-port-1080$", url)
    url = re.sub(r"([?&](?:w|width|wid|sw)=)\d{2,3}\b", r"\g<1>1200", url)
    return url


def _page_images(url):
    import requests
    if any(h in url for h in SKIP_HOST):
        return []
    try:
        r = requests.get(url, headers=UA, timeout=12)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return []
        h = r.text[:900000]
    except Exception:
        return []
    found = []
    for pat in (r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image)["\'][^>]*content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)["\']',
                r'"image"\s*:\s*"(https?:[^"]+)"', r'"image"\s*:\s*\[\s*"(https?:[^"]+)"'):
        found += re.findall(pat, h, re.I)
    found += re.findall(r'<img[^>]+(?:data-src|src)=["\']([^"\']+\.(?:jpe?g|png|webp)[^"\']*)["\']', h, re.I)[:12]
    out, seen = [], set()
    for f in found:
        f = _bigger(urljoin(url, f.replace("&amp;", "&").replace("\\/", "/")))
        if f.startswith("http") and f not in seen and not re.search(r"logo|icon|sprite|favicon|placeholder|blank|pixel", f, re.I):
            seen.add(f); out.append(f)
    return out[:8]


def _fetch(url, d):
    import requests
    from PIL import Image
    try:
        r = requests.get(url, headers=UA, timeout=12, stream=True)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
            return None
        data = r.raw.read(8_000_001, decode_content=True)
        if len(data) > 8_000_000 or len(data) < 8000:
            return None
        im = Image.open(io.BytesIO(data))
        im.load()
        if min(im.size) < 300:
            return None
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255)); bg.paste(im, mask=im.split()[-1]); im = bg
        im = im.convert("RGB")
        im.thumbnail((1400, 1400))
        p = os.path.join(d, uuid.uuid4().hex[:10] + ".jpg")
        im.save(p, "JPEG", quality=88)
        return p
    except Exception:
        return None


def _rank(paths, text, keep, min_sim=0.2):
    """CLIP: keep the pictures that really show `text`, most like it first, no near-duplicates."""
    from PIL import Image
    m = G["clip"]()
    ims, ok = [], []
    for p in paths:
        try:
            ims.append(Image.open(p).convert("RGB")); ok.append(p)
        except Exception:
            pass
    if not ok:
        return []
    e = m.encode(ims, convert_to_numpy=True, normalize_embeddings=True)
    q = m.encode([text[:200]], convert_to_numpy=True, normalize_embeddings=True)[0]
    sims = e @ q
    out, kept = [], []
    for j in np.argsort(-sims):
        if sims[j] < min_sim:
            break
        if any(float(e[j] @ e[k]) > 0.95 for k in kept):
            continue
        kept.append(j); out.append((ok[j], float(sims[j])))
        if len(out) >= keep:
            break
    return out


def build(s):
    """Research + fetch + rank. Returns {"products": [...], "inspo": [...]} with local paths, or {} if nothing useful."""
    b = s["brief"]
    if G.get("spent_today") and G["spent_today"]() >= G["daily_cap"]():
        return {}
    plan = _plan(b, s["id"])
    d = os.path.join(ROOT, s["id"])
    os.makedirs(d, exist_ok=True)
    res = {"products": [], "inspo": []}

    def gather(pages, cap):
        imgs = []
        with ThreadPoolExecutor(6) as ex:
            for lst in ex.map(_page_images, [p for p in pages if isinstance(p, str)][:6]):
                imgs += lst[:3]
        with ThreadPoolExecutor(6) as ex:
            got = [p for p in ex.map(lambda u: _fetch(u, d), imgs[:cap]) if p]
        return got

    for prod in (plan.get("products") or [])[:2]:
        got = gather(prod.get("pages") or [], 14)
        for p, sim in _rank(got, f"a product photo of {prod.get('name', '')} bottle and box packshot", 2, 0.22):
            res["products"].append({"path": p, "name": prod.get("name", ""), "sim": sim})
    for ins in (plan.get("inspiration") or [])[:6]:
        got = gather(ins.get("pages") or [], 6)
        what = ins.get("what") or f"{b.get('unit_type', 'display')} retail display in a store"
        prods = str(b.get("hero_products") or b.get("products_held") or b.get("category") or "")[:60]
        for p, sim in _rank(got, f"a photo of a {b.get('unit_type', 'display')} retail display of {prods} in a store", 1, 0.23):
            res["inspo"].append({"path": p, "name": what, "sim": sim})
        if len(res["inspo"]) >= 4:
            break
    if not res["products"] and not res["inspo"]:
        return {}
    return res


def _mp(sid):
    return os.path.join(ROOT, sid, "mood.json")


def load(sid):
    try:
        return json.load(open(_mp(sid), encoding="utf-8"))
    except Exception:
        return {}


def save(sid, m):
    os.makedirs(os.path.join(ROOT, sid), exist_ok=True)
    json.dump(m, open(_mp(sid), "w", encoding="utf-8"), indent=1)


def start(s):
    """Once per brief, in the background, as soon as there's enough to search on. Kept beside the brief (not in it),
    so a slow search can never overwrite the conversation."""
    sid = s["id"]
    m = load(sid)
    if m.get("state") in ("running", "ready", "empty"):
        return m
    save(sid, {"state": "running"})

    def done(res):
        save(sid, {"state": "ready" if res else "empty", **(res or {}), "shown": False, "dropped": []})
    run_async(s, done)
    return {"state": "running"}


def picks(sid):
    """What the concepts should use: products (exact packs) and inspiration (the standard to beat), minus any struck out."""
    m = load(sid)
    if m.get("state") != "ready":
        return [], []
    drop = set(m.get("dropped") or [])
    ok = lambda r: r["path"] not in drop and os.path.exists(r["path"])
    return [r for r in m.get("products") or [] if ok(r)][:2], [r for r in m.get("inspo") or [] if ok(r)][:3]


def run_async(s, done):
    """Research in the background (it takes ~20-40s); done(result) is called when it's ready."""
    def go():
        try:
            done(build(s))
        except Exception:
            import traceback
            os.makedirs(os.path.join(ROOT, s["id"]), exist_ok=True)
            open(os.path.join(ROOT, s["id"], "error.txt"), "w", encoding="utf-8").write(traceback.format_exc())
            done({})
    threading.Thread(target=go, daemon=True).start()
