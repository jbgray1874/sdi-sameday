"""A phone link for Brief Lite that never changes - even when this laptop restarts.

How it works:
  Andy's phone -> https://sdi-brief.<account>.workers.dev  (fixed; a tiny Cloudflare Worker, free plan)
               -> today's Cloudflare quick tunnel to this laptop (changes on every restart)
               -> Brief Lite on port 5020
The Worker passes every request through to whatever tunnel address is stored in Cloudflare KV. When the laptop
restarts, lite_tunnel.py starts a new tunnel and calls update() with its address, so the fixed link keeps working.

Needs one thing in C:\\SDI_Automation\\.env:  CF_API_TOKEN=<token made from the "Edit Cloudflare Workers" template>
    python fixed_link.py deploy     - once: makes the Worker and its KV store, prints the fixed link
    python fixed_link.py update     - points the fixed link at the tunnel in PHONE_LINK.txt (lite_tunnel.py does this)
Nothing about a client passes through Cloudflare's storage: KV holds only the tunnel address. The team access
code (LITE_ACCESS_CODE) still guards Brief Lite itself.
"""
import json, os, re, sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(os.path.dirname(HERE), ".env")
STATE = os.path.join(HERE, "fixed_link.json")
API = "https://api.cloudflare.com/client/v4"
SCRIPT = "sdi-brief"

WORKER_JS = r"""
// SDI Same Day Intelligence - fixed link. Passes every request to the laptop's current tunnel (stored in KV as "target").
export default {
  async fetch(req, env) {
    const target = await env.LINK.get("target");
    if (!target) return offline();
    const u = new URL(req.url);
    const headers = new Headers(req.headers);
    headers.delete("host");
    const init = { method: req.method, headers, redirect: "manual" };
    if (!["GET", "HEAD"].includes(req.method)) init.body = await req.arrayBuffer();
    let r;
    try { r = await fetch(target + u.pathname + u.search, init); } catch (e) { return offline(); }
    if ([502, 503, 504, 530].includes(r.status) && !(r.headers.get("content-type") || "").includes("json")) return offline();
    const h = new Headers(r.headers);
    const loc = h.get("location");
    if (loc && loc.startsWith(target)) h.set("location", u.origin + loc.slice(target.length));
    return new Response(r.body, { status: r.status, headers: h });
  }
};
function offline() {
  return new Response(`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDI Same Day Intelligence</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#F5F3EF;font:16px system-ui;color:#17181B">
<div style="background:#fff;border-radius:20px;padding:28px;max-width:320px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.08)">
<div style="font-size:40px">🔌</div><h2 style="margin:8px 0">SDI Same Day Intelligence is starting up</h2>
<p style="color:#6E6A64">The SDI laptop that runs it is restarting or offline. Try again in a couple of minutes.</p>
<button onclick="location.reload()" style="height:44px;border:0;border-radius:12px;background:#C8102E;color:#fff;font-weight:700;padding:0 22px">Try again</button></div>`,
    { status: 503, headers: { "content-type": "text/html; charset=utf-8", "retry-after": "60" } });
}
"""


def token():
    t = os.environ.get("CF_API_TOKEN", "")
    if not t and os.path.exists(ENV):
        for line in open(ENV, encoding="utf-8"):
            if line.startswith("CF_API_TOKEN="):
                t = line.split("=", 1)[1].strip()
    return t


def cf(method, path, **kw):
    r = requests.request(method, API + path, headers={"Authorization": f"Bearer {token()}"}, timeout=30, **kw)
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"{method} {path}: HTTP {r.status_code}")
    if not j.get("success"):
        raise RuntimeError(f"{method} {path}: {j.get('errors')}")
    return j.get("result")


def state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def deploy():
    if not token():
        sys.exit("Put CF_API_TOKEN=... in C:\\SDI_Automation\\.env first.")
    acct = cf("GET", "/accounts")[0]["id"]
    # the KV store that holds only the tunnel address
    ns = next((n["id"] for n in cf("GET", f"/accounts/{acct}/storage/kv/namespaces") if n["title"] == "brief-lite"), None)
    ns = ns or cf("POST", f"/accounts/{acct}/storage/kv/namespaces", json={"title": "brief-lite"})["id"]
    meta = {"main_module": "worker.js", "compatibility_date": "2024-09-01",
            "bindings": [{"type": "kv_namespace", "name": "LINK", "namespace_id": ns}]}
    cf("PUT", f"/accounts/{acct}/workers/scripts/{SCRIPT}",
       files={"metadata": (None, json.dumps(meta), "application/json"),
              "worker.js": ("worker.js", WORKER_JS, "application/javascript+module")})
    # the account's workers.dev name (made once if the account is new), then switch this Worker on there
    try:
        sub = cf("GET", f"/accounts/{acct}/workers/subdomain")["subdomain"]
    except RuntimeError:
        sub = cf("PUT", f"/accounts/{acct}/workers/subdomain", json={"subdomain": "sdi-brief-lite"})["subdomain"]
    cf("POST", f"/accounts/{acct}/workers/scripts/{SCRIPT}/subdomain", json={"enabled": True})
    url = f"https://{SCRIPT}.{sub}.workers.dev"
    json.dump({"account": acct, "namespace": ns, "url": url, "target": ""}, open(STATE, "w", encoding="utf-8"), indent=1)
    update()
    print(url)
    return url


def update(target=None):
    """Point the fixed link at the laptop's current tunnel. Cheap: one KV write, only when it changed."""
    st = state()
    if not (token() and st.get("namespace")):
        return None
    if not target:
        try:
            target = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", open(os.path.join(HERE, "PHONE_LINK.txt"), encoding="utf-8").read()).group(0)
        except (OSError, AttributeError):
            return None
    if st.get("target") == target:
        return st["url"]
    requests.put(f"{API}/accounts/{st['account']}/storage/kv/namespaces/{st['namespace']}/values/target",
                 headers={"Authorization": f"Bearer {token()}"}, data=target.encode(), timeout=30).raise_for_status()
    st["target"] = target
    json.dump(st, open(STATE, "w", encoding="utf-8"), indent=1)
    return st["url"]


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["update"])[0]
    print(deploy() if cmd == "deploy" else update() or "fixed link not set up yet (run: python fixed_link.py deploy)")
