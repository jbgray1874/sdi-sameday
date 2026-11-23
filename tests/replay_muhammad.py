"""Replay of Muhammad's call of 23 Nov 2026 (chat f51945ab68) through the server: his words, in order, and the tool calls
the voice made (from the server log). Pictures and AI calls are stood in. Run: python3 tests/replay_muhammad.py"""
import json, os, sys, time
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(__file__))
from test_any_order_and_noise import L, new_chat, WORK, _past_jobs_index   # noqa: E402
import lite_search                                          # noqa: E402
if not (WORK / "brief_lite" / "projects.db").exists():
    _past_jobs_index(WORK / "brief_lite")
lite_search.JOBS_DB = str(WORK / "brief_lite" / "projects.db")
lite_search._state.clear()
from PIL import Image                                      # noqa: E402

def fake_visual(s, kind, refs=None, label="A", **k):
    p = os.path.join(L.OUT, f"replay_{s['id']}_{label}.png"); Image.new("RGB", (64, 48), (200, 120, 0)).save(p)
    s["visuals"].append({"path": p, "kind": "render", "label": label, "check": {"ok": True}}); return p, ""
L.make_visual = fake_visual
L.design_directions = lambda s, labels: {}
def offline(*a, **k): raise RuntimeError("offline replay")
L.claude_create = offline
L.auto_estimate_start = lambda s, label: {"label": label, "status": "done"}

c = L.app.test_client()
s = L.get_session(new_chat(), "Muhammad Yazir", new=True); sid = s["id"]
def bot(t): c.post("/api/rt/log", json={"session": sid, "role": "assistant", "text": t})
def am(t):
    r = c.post("/api/rt/log", json={"session": sid, "role": "user", "text": t}).get_json() or {}
    return r
def tool(name, args):
    r = c.post("/api/rt/tool", json={"session": sid, "name": name, "arguments": args}).get_json() or {}
    out = json.loads(r.get("output") or "{}")
    if r.get("turn") and name in ("make_concepts", "more_options"):
        for _ in range(300):
            d = c.get(f"/api/rt/done/{r['turn']}").get_json()
            if d.get("done"): break
            time.sleep(0.05)
        return ("DRAWN" if d.get("drawn") else "NOTHING DRAWN: " + json.loads(d["output"]).get("error", "")[:90])
    if r.get("turn"):
        for _ in range(300):
            if (L.JOBS.get(r["turn"]) or {}).get("done"): break
            time.sleep(0.05)
    return out.get("error") or out.get("note") or out.get("read_back") or ("saved " + ", ".join(out.get("saved_now") or []) if "saved_now" in out else "ok")
def renders(): return [v["label"] for v in L._session_by_id(sid)["visuals"] if v.get("kind") == "render"]

steps = [
 ("Hi Muhammad, Sid here - good to hear from you. Is this one for the client pack, the internal brief, or both?", None, []),
 (None, "So the client is looking for freestanding units.", [("record_answers", {"updates": {"unit_type": "freestanding unit"}})]),
 ("Got it, a free-standing unit. Which client is it for?", "It is for Sainsbury's", [("record_answers", {"updates": {"client": "Sainsbury's"}})]),
 ("What materials and finish are you thinking?", "Powder coated", [("record_answers", {"updates": {"materials": "Powder coated"}})]),
 ("Roughly what size are you aiming for?", "Just just assume on your own.", []),
 ("Even a rough range is fine, like about 1.5 metres tall and 600 wide.", "Yeah, take that site that you have just told.",
  [("record_answers", {"updates": {"size": "1500 x 600 x 600 mm"}})]),
 ("Sorry, I need the numbers.", "Twelve hundred by nine hundred by seven hundred", [("record_answers", {"updates": {"size": "1200 x 900 x 700 mm"}})]),
 ("Where will it sit in store?", "At the end of the aisle.", [("record_answers", {"updates": {"placement": "aisle end"}})]),
 ("What products will it hold?", "It will, it will hold few chocolates and I don't know how many it will hold on a single shelf.",
  [("record_answers", {"updates": {"products_held": "chocolates"}})]),
 ("Colours and graphics?", "Just use the brand colors.", [("record_answers", {"updates": {"colours_graphics": "brand colours"}})]),
 ("Does it need lighting?", "No.", [("record_answers", {"updates": {"lighting": "None"}})]),
 ("Free-standing, or fixed?", "It is free standing.", [("record_answers", {"updates": {"fixing": "free-standing"}})]),
 ("Have they mentioned a unit they like?", "No, but you can tell me what, what we have done for them before, something similar like this",
  [("show_past_work", {})]),
 (None, "No, just carry on with the questions and generate me renders and internal brief pack, client pack.", [("record_answers", {"updates": {}})]),
 ("Before I draw it, should this build on a past SDI job or be brand-new?", "Yes, it should be built on the past SDI jobs.",
  [("record_answers", {"updates": {"design_route": "past"}})]),
 ("Which one is it, the job number?", "So it will refer to eight four one double two.", [("record_answers", {"updates": {"liked_job": "84122"}})]),
 ("I heard 8 4 1 2 2. Is that right?", "Yes,", [("record_answers", {"updates": {}})]),
 ("If 8 4 1 2 2 is right, it's not on file, so this will be a new design. How heavy is the stock on each shelf?", "I told them. I don't know",
  [("record_answers", {"updates": {}, "not_known": ["shelf_load"]})]),
 ("No worries. What's the project name?", "Just render just give me a render first and then ask all these questions for internal pack.",
  [("make_concepts", {"output": "3D render"})]),
]
for b_, a_, tools in steps:
    if b_: bot(b_); print(f"BOT  {b_[:100]}")
    if a_:
        r = am(a_); print(f"AM   {a_[:100]}" + (f"   [listener started: {r.get('kind')}]" if r.get("kind") else ""))
        if r.get("turn"):
            for _ in range(300):
                d = c.get(f"/api/rt/done/{r['turn']}").get_json()
                if d.get("done"): break
                time.sleep(0.05)
            j = L.JOBS.get(r["turn"]) or {}
            said = " | ".join((x.get("text") or x.get("caption") or "")[:110] for x in j["ch"].out) if j.get("ch") else ""
            c.get(f"/api/rt/done/{r['turn']}")          # as the page does: the turn is over
            time.sleep(1.2)                                   # the busy marker clears a second after
            print("     -> listener turn said:", said[:400] or "(nothing)", "| error:", j.get("error"))
    for n, args in tools:
        print(f"     voice calls {n}: {str(tool(n, args))[:150]}")
    if renders():
        print(f"\n==> RENDERS ON SCREEN: {renders()}  stage: {L.convo.stage(L._session_by_id(sid))}"); break
b = L._session_by_id(sid)["brief"]
print("\nbrief:", {k: v for k, v in b.items() if not k.startswith("_")})
print("pack:", L.convo.pack_of(b), "| render asked:", b.get("_render_asked"), "| route:", b.get("design_route"))
print("busy:", L.RT_BUSY.get(sid), "| unfinished turns:", [(k, (v.get("tool"), v.get("error"))) for k, v in L.JOBS.items() if not v.get("done")])
