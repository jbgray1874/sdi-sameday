"""SameDay: the brief in any order, and a live call that copes with a noisy room.

"Pls let's make changes so the Voice AI is as strong as possible at handling background noise and handling a dynamic,
changing conversation. Gathers all the information it needs for the brief but allows the user to change the flow."
- James Gray, 4 November 2026.

These run offline: no AI, no keys, no W: or K:. Each run works on a throwaway copy of brief_lite, so no lite.db or
craft.db is ever written into the repository. The conversation model is replaced by a stand-in that returns what the
AM's words would give, so what is tested is the app's own flow - the part that used to force the order.

    python -m pytest tests -q          (needs flask and numpy; node for the page checks)
"""
import importlib
import json
from datetime import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "SDI_Automation"
WORK = Path(tempfile.mkdtemp(prefix="sameday-test-"))
shutil.copytree(SRC / "brief_lite", WORK / "brief_lite",
                ignore=shutil.ignore_patterns("*.db", "out", "client_files", "__pycache__", ".env"))
shutil.copytree(SRC / "craft", WORK / "craft", ignore=shutil.ignore_patterns("*.db", "__pycache__"))
os.environ["LITE_ACCESS_CODE"] = "test-code-not-real"
sys.path.insert(0, str(WORK / "brief_lite"))
L = importlib.import_module("lite_app")
convo, rt = L.convo, L.rt

# offline: no AI, no drives, no web
L.ref_lookup = lambda b, text: None
L.moodboard.start = lambda s: None
L.guess_client = convo.guess_client = lambda text: None     # reads the picture index on C:
SAID = {}     # text -> what the conversation model would have pulled from it


def fake_converse(s, text, fast=False):
    upd, intent = SAID.get(text, ({}, "answer"))
    return {"updates": dict(upd), "intent": intent, "reply": "", "ask_field": "", "ask": "", "options": []}


convo.converse = fake_converse
_n = [0]


def new_chat():
    _n[0] += 1
    return f"web:test-{_n[0]}"


def say(who, text, upd=None, intent="answer"):
    SAID[text] = (upd or {}, intent)
    ch, s = L.handle(who, "Test", text)
    return ch.out, L._session_by_id(s["id"])


def asked(out):
    return " ".join(r.get("text") or "" for r in out if r.get("role") in ("ask", "choose_pack", "choose_output"))


class PackIsAskedOnceNeverAGateTests(unittest.TestCase):
    def test_the_pack_is_asked_once_and_carrying_on_means_both(self):
        who = new_chat()
        out, s = say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        self.assertIn("Which pack", asked(out))
        out, s = say(who, "about 1800 high, 1200 wide and 600 deep, for Milwaukee drills",
                     {"size": "1800 x 1200 x 600 mm", "products_held": "Milwaukee drills"})
        b = s["brief"]
        self.assertEqual(b.get("_pack"), "both")
        self.assertTrue(b.get("_pack_assumed"))
        self.assertNotIn("Which pack", asked(out))
        self.assertEqual(b.get("size"), "1800 x 1200 x 600 mm")

    def test_a_render_asked_for_first_never_waits_for_the_pack(self):
        who = new_chat()
        out, s = say(who, "make me a render of a Boots FSDU", {"client": "Boots", "unit_type": "FSDU"}, "want_visuals")
        b = s["brief"]
        self.assertEqual(b.get("_pack"), "both")
        self.assertTrue(b.get("_pack_assumed"))
        self.assertNotIn("Which pack", asked(out))
        self.assertTrue(b.get("_render_q_done"))

    def test_a_named_pack_is_still_the_ams_choice(self):
        who = new_chat()
        say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        _, s = say(who, "just the client pack")
        self.assertEqual(s["brief"].get("_pack"), "client")
        self.assertFalse(s["brief"].get("_pack_assumed"))

    def test_naming_the_pack_after_it_was_taken_as_both(self):
        who = new_chat()
        say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        say(who, "it's for the tills", {"placement": "tills"})
        _, s = say(who, "add the deadline to the internal brief")
        self.assertEqual(s["brief"].get("_pack"), "both")          # a mention, not a choice
        _, s = say(who, "client pack please")
        self.assertEqual(s["brief"].get("_pack"), "client")
        self.assertFalse(s["brief"].get("_pack_assumed"))

    def test_a_change_of_mind_is_heard_at_any_point(self):
        who = new_chat()
        say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        say(who, "both please")
        _, s = say(who, "actually I don't need the internal brief, just the client pack")
        self.assertEqual(s["brief"].get("_pack"), "client")


class PackWordsTests(unittest.TestCase):
    def test_a_sentence_about_the_client_is_not_the_client_pack(self):
        self.assertIsNone(convo.pack_from("the client wants a gondola end for Tesco in the spring", asked=True))
        self.assertEqual(convo.pack_from("the client one", asked=True), "client")
        self.assertEqual(convo.pack_from("both please", asked=True), "both")

    def test_changes_of_pack(self):
        self.assertEqual(convo.pack_change("actually just the internal brief"), "internal")
        self.assertEqual(convo.pack_change("I don't need the internal brief, just the client pack"), "client")
        self.assertEqual(convo.pack_change("I don't need the client pack"), "internal")
        self.assertEqual(convo.pack_change("actually make it both packs"), "both")

    def test_a_mention_is_not_a_change(self):
        for text in ("can you just add that to the client sheet", "it's not for the client yet",
                     "the client pack needs their logo on it", "put the deadline in the brief"):
            with self.subTest(text=text):
                self.assertIsNone(convo.pack_change(text))


class TheAmChoosesTheOrderTests(unittest.TestCase):
    def _started(self):
        who = new_chat()
        say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        say(who, "both please")
        return who

    def test_the_internal_questions_can_come_before_the_render(self):
        who = self._started()
        out, s = say(who, "let's do the internal brief questions first")
        self.assertEqual(s["brief"].get("_focus"), "internal")
        self.assertEqual(convo.stage(s), "internal_q")
        self.assertNotIn("comes straight after the client pack", " ".join(r.get("text") or "" for r in out))

    def test_back_to_the_render_carries_on_where_it_was(self):
        who = self._started()
        say(who, "let's do the internal brief questions first")
        _, s = say(who, "ok back to the render")
        self.assertFalse(s["brief"].get("_focus"))
        self.assertIn(convo.stage(s), ("render_q", "route", "confirm"))

    def test_when_the_internal_questions_run_out_the_render_is_next(self):
        s = {"id": "x", "visuals": [], "brief": {"_flow": 2, "_pack": "both", "_focus": "internal", "client": "Tesco",
                                                  "unit_type": "gondola end"}}
        self.assertEqual(convo.stage(s), "internal_q")
        real_plan = convo.plan
        try:
            convo.plan = lambda b: []
            self.assertNotEqual(convo.stage(s), "internal_q")
        finally:
            convo.plan = real_plan

    def test_the_focus_never_outlives_the_client_pack(self):
        s = {"id": "x", "visuals": [], "brief": {"_flow": 2, "_pack": "client", "_focus": "internal", "client": "Tesco",
                                                  "unit_type": "gondola end"}}
        self.assertNotEqual(convo.stage(s), "internal_q")

    def test_finishing_the_brief_pdf_on_a_render_is_not_finalising_the_render(self):
        src = (WORK / "brief_lite" / "lite_app.py").read_text(encoding="utf-8")
        line = next(x for x in src.splitlines() if 'intent == "finish" and convo.stage(s) == "review"' in x)
        self.assertIn('not t.get("pdf")', line)
        self.assertTrue(rt.tool_intent("finish_brief", {"now": True})[1].get("pdf"))


class LiveCallToolsTests(unittest.TestCase):
    def setUp(self):
        self.client = L.app.test_client()
        self.who = new_chat()
        _, self.s = say(self.who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})

    def tool(self, name, args):
        r = self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": name, "arguments": args})
        self.assertEqual(r.status_code, 200, r.data[:300])
        return r.get_json()

    def test_a_pack_the_am_never_named_is_taken_as_both_not_asked_again(self):
        L.log_msg(self.s["id"], "out", "Which pack do you need - the client pack, the internal pack, or both?")
        L.log_msg(self.s["id"], "in", "it's for their new spring layout, by the tills")
        out = json.loads(self.tool("set_pack", {"pack": "client"})["output"])
        self.assertIn("Don't ask the pack question again", out.get("note", ""))
        b = L._session_by_id(self.s["id"])["brief"]
        self.assertEqual(b.get("_pack"), "both")
        self.assertTrue(b.get("_pack_assumed"))

    def test_the_voice_still_cannot_choose_before_the_am_answers(self):
        L.log_msg(self.s["id"], "out", "Which pack do you need - the client pack, the internal pack, or both?")
        out = json.loads(self.tool("set_pack", {"pack": "client"})["output"])
        self.assertIn("hasn't answered yet", out.get("error", ""))

    def test_the_focus_tool(self):
        L.log_msg(self.s["id"], "in", "let's do the studio questions first")
        res = self.tool("focus", {"on": "internal"})
        out = json.loads(res["output"])
        self.assertEqual(out.get("focus"), "internal")
        self.assertEqual(out.get("stage"), "internal_q")
        self.assertEqual(L._session_by_id(self.s["id"])["brief"].get("_focus"), "internal")

    def test_the_brief_pdf_can_be_asked_for_before_the_client_pack(self):
        started = []
        real = L._start_turn
        try:
            L._start_turn = lambda *a, **k: (started.append(k.get("t_override")), real(*a, **k))[1]
            L.log_msg(self.s["id"], "in", "Tesco gondola end")
            out = self.tool("finish_brief", {"now": True})
            self.assertIn("didn't ask for the brief PDF", out["output"])      # the voice alone can't
            self.assertEqual(started, [])
            L.log_msg(self.s["id"], "in", "build the internal brief PDF now as it is")
            out = self.tool("finish_brief", {"now": True})
            self.assertNotIn("Not yet", out["output"])
            self.assertTrue(started and started[0].get("pdf"))
        finally:
            L._start_turn = real

    def test_a_fresher_listening_hint_comes_back_when_the_brief_names_more(self):
        L.RT_HINT[self.s["id"]] = ["UK retail display brief for SDI Displays. (an older hint)"]
        L.log_msg(self.s["id"], "in", "it holds Milwaukee M18 drills")
        res = self.tool("record_answers", {"updates": {"products_held": "Milwaukee M18 drills"}})
        self.assertIn("Milwaukee M18 drills", (res.get("transcription") or {}).get("prompt", ""))


class ListeningInANoisyRoomTests(unittest.TestCase):
    def brief(self, **kw):
        return {"id": "h", "visuals": [], "brief": dict({"_flow": 2}, **kw)}

    def test_the_transcriber_is_told_this_briefs_own_names(self):
        h = rt.heard_hint(self.brief(client="Lindt", unit_type="counter unit", products_held="Lindor tubes",
                                     account_manager="Denzel", _same_before="12148 Rollershutter Forecourt Bunker (2026)"))
        for word in ("Lindt", "counter unit", "Lindor tubes", "Denzel", "12148 Rollershutter Forecourt Bunker", "FSDU"):
            self.assertIn(word, h)
        self.assertTrue(h.startswith("UK retail display brief"))      # caught by the existing read-back checks too
        self.assertLessEqual(len(h), 900)
        self.assertNotIn("(assumed)", rt.heard_hint(self.brief(client="Lindt", size="900 x 400 x 300 mm (assumed)")))

    def test_the_call_is_told_it_can_go_in_any_order_and_to_ignore_other_voices(self):
        who = new_chat()
        _, s = say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        text = rt.instructions(s)
        for part in ("# At any point", "focus internal", "Only the AM talking to you counts", "hold the orb", "ask once"):
            self.assertIn(part, text)
        self.assertNotIn("Then STOP and wait", text)
        self.assertIn("focus", [x["name"] for x in rt.TOOLS])

    def test_the_session_uses_it(self):
        cfg = rt.session_config(self.brief(client="Lindt"))
        self.assertIn("Lindt", cfg["audio"]["input"]["transcription"]["prompt"])
        self.assertEqual(cfg["audio"]["input"]["turn_detection"]["type"], "semantic_vad")

    def test_a_read_back_of_the_hint_is_dropped_and_a_real_answer_is_kept(self):
        h = rt.heard_hint(self.brief(client="Lindt", unit_type="counter unit"))
        self.assertTrue(L.echo_of("FSDU, gondola end, wall bay, counter unit, plinth, header", h))
        self.assertTrue(L.echo_of("This job: Lindt, counter unit. Clients: Tesco, Boots", h + " Clients: Tesco, Boots."))
        for real in ("the client pack and the internal pack", "it's a counter unit for Lindt, about 400 high",
                     "both please", "a gondola end with four shelves and a lit header"):
            with self.subTest(real=real):
                self.assertFalse(L.echo_of(real, h))
        L.RT_HINT["call"] = [h]
        self.assertTrue(L.hint_echo("FSDU, gondola end, wall bay, counter unit, plinth, header", "call"))
        self.assertFalse(L.hint_echo("a gondola end with four shelves and a lit header", "call"))


class VoiceSpendTests(unittest.TestCase):
    def test_the_live_model_is_never_counted_at_the_mini_price(self):
        self.assertEqual(rt.price_of("gpt-realtime-2")[0], rt.RT_PRICE["gpt-realtime"])
        self.assertEqual(rt.price_of("some-new-realtime-model")[0], rt.RT_PRICE["gpt-realtime"])
        self.assertGreater(rt.price_of("gpt-realtime-2")[0][0], rt.RT_PRICE["gpt-realtime-mini"][0])


class TeamCodeOverHttpTests(unittest.TestCase):
    def test_the_cookie_is_kept_on_the_office_http_address(self):
        r = L.app.test_client().post("/unlock", data={"code": "test-code-not-real"},
                                     environ_base={"REMOTE_ADDR": "10.0.0.20"})
        cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("lite_access=", cookie)
        self.assertNotIn("Secure", cookie)

    def test_and_secure_on_https(self):
        r = L.app.test_client().post("/unlock", data={"code": "test-code-not-real"}, base_url="https://sameday.example",
                                     environ_base={"REMOTE_ADDR": "10.0.0.20"})
        self.assertIn("Secure", r.headers.get("Set-Cookie", ""))


NODE = shutil.which("node")
PAGE = (WORK / "brief_lite" / "lite_page.html").read_text(encoding="utf-8")


def page_fn(name):
    """One function from the page, cut out by its braces."""
    i = PAGE.index("function " + name + "(")
    j, depth = PAGE.index("{", i), 0
    for k in range(j, len(PAGE)):
        depth += {"{": 1, "}": -1}.get(PAGE[k], 0)
        if depth == 0:
            return PAGE[i:k + 1]


@unittest.skipUnless(NODE, "node is not installed")
class ThePageTests(unittest.TestCase):
    def run_js(self, body):
        src = "\n".join(page_fn(n) for n in ("hintEcho", "junkHeard", "vadBar", "autoTD")) + "\n" + body
        r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_the_page_drops_the_hint_read_back_and_keeps_real_answers(self):
        h = rt.heard_hint({"brief": {"client": "Lindt", "unit_type": "counter unit"}})
        got = self.run_js("let rt={hints:[%s]};console.log(JSON.stringify([" % json.dumps(h) +
                          "junkHeard('FSDU, gondola end, wall bay, counter unit, plinth, header'),"
                          "junkHeard('a counter unit for Lindt, about four hundred high'),"
                          "junkHeard('the client pack and the internal pack'),junkHeard('both please')]))")
        self.assertEqual(got, [True, False, False, False])

    def test_the_bar_follows_the_room(self):
        got = self.run_js("let rt={noisy:1,floor:0.002};const a=autoTD().threshold;rt.floor=0.03;const b=autoTD().threshold;"
                          "rt.noisy=2;const c=autoTD();rt.floor=0.5;const d=autoTD().threshold;rt.noisy=false;"
                          "console.log(JSON.stringify([a,b,c.threshold,c.silence_duration_ms,d,autoTD().type]))")
        self.assertEqual(got[:4], [0.6, 0.7, 0.8, 800])
        self.assertEqual(got[4], 0.85)
        self.assertEqual(got[5], "semantic_vad")

    def test_it_never_starts_speaking_while_the_am_is_talking(self):
        """4 Nov 2026 (James: "doesn't talk over"): a render finishing, a tool's answer or a queued follow-up could
        start the voice mid-sentence. Now it is held back and said once their turn is over - unless their own reply
        covers it."""
        js = (page_fn("rtSay") + "\n" + page_fn("owedLater") + "\n"
              "const sent=[];let rt={paused:false,inTurn:true,held:false,inResp:false,replyPending:false,"
              "dc:{readyState:'open',send:x=>sent.push(JSON.parse(x).type)}};"
              "rtSay({type:'conversation.item.create'});rtSay({type:'response.create'});"   # a render finished mid-sentence
              "const held=[...sent],owed=rt.owed;"
              "rt.inTurn=false;owedLater();"                                                   # their turn ends, nothing to reply to
              "setTimeout(()=>{const after=[...sent];"
              "rt.inTurn=true;rtSay({type:'response.create'});rt.inTurn=false;rt.replyPending=true;owedLater();"
              "setTimeout(()=>{console.log(JSON.stringify([held,owed,after,sent.length,rt.owed]))},2700)},2700)")
        r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        held, owed, after, total, still_owed = json.loads(r.stdout)
        self.assertEqual(held, ["conversation.item.create"])           # the note goes in; the voice stays quiet
        self.assertTrue(owed)
        self.assertEqual(after[-1], "response.create")                  # ...and speaks once they've finished
        self.assertEqual(total, len(after))                             # their own reply was coming: not said twice
        self.assertTrue(still_owed)                                     # (their reply clears it when it is sent)

    def test_the_phone_stays_awake_and_a_dropped_call_reloads_the_chat(self):
        """4 Nov 2026: "the render didn't appear on the phone app" - a minute or two of drawing with the mic paused, the
        phone locked itself, and a locked phone pauses the page and drops the call."""
        self.assertIn("keepAwake(true);dc.send", PAGE)                       # on as the call opens
        self.assertIn("function rtStop(){if(!rt)return;keepAwake(false);", PAGE)
        self.assertIn('navigator.wakeLock.request("screen")', PAGE)
        self.assertIn('document.addEventListener("visibilitychange"', PAGE)  # taken again when the page is back
        stop = page_fn("rtStop")
        self.assertIn("loadHist()", stop)                                     # a stopped call reloads the chat
        self.assertIn('pc.onconnectionstatechange=()=>{if(rt&&rt.pc===pc&&["failed","closed"]', PAGE)

    def test_a_fresher_hint_is_sent_to_the_transcriber_mid_call(self):
        self.assertIn('session:{type:"realtime",audio:{input:{transcription:j.transcription}}}', PAGE)
        self.assertIn("const tr0=j.transcription||null;", PAGE)


class CarriedToThePhoneTests(unittest.TestCase):
    """4 Nov 2026 (James: "the app needs to work on the phone"): SDI Intelligence carries SameDay at /sameday/ on its
    https address (its sameday_proxy.py). Asked from this machine with X-Forwarded-Prefix, the page, the manifest and the
    service worker take the prefix; opened directly, nothing changes."""
    P = {"X-Forwarded-Prefix": "/sameday"}

    def setUp(self):
        self.c = L.app.test_client()

    def test_the_page_is_unchanged_when_opened_directly(self):
        plain = self.c.get("/").get_data(as_text=True)
        self.assertEqual(plain, (WORK / "brief_lite" / "lite_page.html").read_text(encoding="utf-8"))
        self.assertNotIn("SD_BASE", plain)

    def test_carried_the_page_asks_for_sameday_addresses(self):
        h = self.c.get("/", headers=self.P).get_data(as_text=True)
        self.assertIn('window.SD_BASE="/sameday"', h)
        self.assertLess(h.index("SD_BASE"), h.index('rel="manifest"'))      # before anything else loads
        self.assertIn('href="/sameday/pwa/manifest.webmanifest"', h)
        self.assertEqual(h.count('"/pwa/'), 0)

    def test_only_this_machine_may_give_the_prefix(self):
        h = self.c.get("/", headers=self.P, environ_base={"REMOTE_ADDR": "10.0.0.20"}).get_data(as_text=True)
        self.assertNotIn("SD_BASE", h)
        h = self.c.get("/", headers={"X-Forwarded-Prefix": "/x\"><script>"}).get_data(as_text=True)
        self.assertNotIn("SD_BASE", h)

    def test_installed_on_the_phone_it_opens_at_sameday(self):
        m = json.loads(self.c.get("/pwa/manifest.webmanifest", headers=self.P).get_data(as_text=True))
        self.assertEqual((m["start_url"], m["scope"]), ("/sameday/", "/sameday/"))
        self.assertTrue(all(i["src"].startswith("/sameday/pwa/") for i in m["icons"]))
        r = self.c.get("/sw.js", headers=self.P)
        self.assertEqual(r.headers["Service-Worker-Allowed"], "/sameday/")
        js = r.get_data(as_text=True)
        self.assertIn('startsWith("/sameday/api")', js)
        self.assertNotIn('"/pwa/', js)

    def test_carried_there_is_no_team_code_because_microsoft_sign_in_was_asked(self):
        carried = self.c.get("/", headers=self.P).get_data(as_text=True)       # from this machine: SDI Intelligence
        self.assertNotIn("Enter the team access code", carried)
        elsewhere = self.c.get("/", environ_base={"REMOTE_ADDR": "10.0.0.20"}).get_data(as_text=True)
        self.assertIn("Enter the team access code", elsewhere)              # anyone else still needs it

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_page_script_puts_the_prefix_in_front_of_every_address(self):
        h = self.c.get("/", headers=self.P).get_data(as_text=True)
        shim = h.split("<script>", 1)[1].split("</script>", 1)[0]
        js = ("const calls=[];global.window=global;window.fetch=(u)=>calls.push(u);"
              "global.XMLHttpRequest=function(){};XMLHttpRequest.prototype.open=function(m,u){calls.push(u)};"
              "global.navigator={};global.MutationObserver=function(){this.observe=()=>{}};"
              "global.document={documentElement:{},addEventListener(){}};"
              + shim + ";fetch('/api/chat');fetch('/sameday/api/x');fetch('https://api.openai.com/v1/x');"
              "fetch('//cdn.example/x');new XMLHttpRequest().open('GET','/file?p=1');"
              "console.log(JSON.stringify([calls,window.SD_FIX('/out/a.png')]))")
        r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls, fixed = json.loads(r.stdout)
        self.assertEqual(calls, ["/sameday/api/chat", "/sameday/api/x", "https://api.openai.com/v1/x", "//cdn.example/x",
                                 "/sameday/file?p=1"])
        self.assertEqual(fixed, "/sameday/out/a.png")


class UpdateCheckTests(unittest.TestCase):
    def test_the_laptop_can_read_the_version_without_the_team_code(self):
        """Update-SameDay.ps1 runs on the laptop and checks the restarted server from there."""
        c = L.app.test_client()
        r = c.get("/api/version", environ_base={"REMOTE_ADDR": "10.0.0.20"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.get_json()), {"version", "can_read"})
        self.assertEqual(c.get("/api/status", environ_base={"REMOTE_ADDR": "10.0.0.20"}).status_code, 401)


class KeepingTrackTests(unittest.TestCase):
    """James, 4 Nov 2026: "we lead but the user might change direction and we need to keep track, as every job might be
    slightly different"."""

    def test_a_new_unit_is_a_new_direction_and_a_refinement_is_not(self):
        self.assertTrue(L.new_direction("gondola end", "wall bay"))
        self.assertTrue(L.new_direction("FSDU", "counter unit"))
        for old, new in (("gondola end", "double-sided gondola end"), ("FSDU", "floor standing display unit"),
                         ("counter unit", "CDU"), ("wall bays", "wall bay"), ("", "wall bay")):
            with self.subTest(old=old, new=new):
                self.assertFalse(L.new_direction(old, new))

    def test_a_change_of_unit_reopens_what_depended_on_it(self):
        who = new_chat()
        say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        _, s = say(who, "you choose the size", {}, "answer")          # pencilled in, nothing drawn
        self.assertIn("(assumed)", s["brief"].get("size", ""))
        out, s = say(who, "actually make it a wall bay instead", {"unit_type": "wall bay"})
        b = s["brief"]
        self.assertEqual(b["unit_type"], "wall bay")
        self.assertEqual(b["_direction"]["from"], "gondola end")
        self.assertIn("size", b["_direction"]["reopened"])
        self.assertNotIn("1800", b.get("size") or "")          # the gondola end's typical size is not kept for a wall bay
        self.assertIn({"field": "unit_type", "from": "gondola end", "to": "wall bay"},
                      [{k: c[k] for k in ("field", "from", "to")} for c in b["_changes"]])
        self.assertIn("a wall bay now, not the gondola end", " ".join(r.get("text") or "" for r in out))
        # it was asked "past job or new?" just before: the change is the AM steering, not the answer - nothing drawn
        self.assertFalse(b.get("design_route"))
        self.assertFalse(s["visuals"])

    def test_an_answer_replaced_is_logged_and_an_assumption_filled_is_not(self):
        b = {"size": "1800 x 1000 x 450 mm (assumed)", "colours_graphics": "red"}
        L.keep_track(b, [], voice=False)
        self.assertNotIn("_changes", b)
        self.assertFalse(L.said_before(b["size"]))
        self.assertTrue(L.said_before(b["colours_graphics"]))

    def test_the_voice_is_told_once(self):
        c = L.app.test_client()
        who = new_chat()
        _, s = say(who, "Boots want a gondola end", {"client": "Boots", "unit_type": "gondola end"})
        L.log_msg(s["id"], "in", "actually it's a wall bay now")
        args = {"updates": {"unit_type": "wall bay"}}
        first = json.loads(c.post("/api/rt/tool", json={"session": s["id"], "name": "record_answers", "arguments": args}
                                  ).get_json()["output"])
        self.assertEqual(first["direction_changed"]["now"], "wall bay")
        self.assertIn("unit_type: gondola end -> wall bay", first["recent_changes"])
        L.log_msg(s["id"], "in", "it holds No7 serums")
        again = json.loads(c.post("/api/rt/tool", json={"session": s["id"], "name": "record_answers",
                                                        "arguments": {"updates": {"products_held": "No7 serums"}}}
                                  ).get_json()["output"])
        self.assertEqual(again["direction_changed"], "")

    def test_the_call_is_told_to_lead_and_to_follow_a_change(self):
        who = new_chat()
        _, s = say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        text = rt.instructions(s)
        self.assertIn("# You lead, they steer", text)
        self.assertIn("never bring back an answer they\n  replaced", text)


class TheLiveTranscriberTests(unittest.TestCase):
    def brief(self, **kw):
        return {"id": "t", "visuals": [], "brief": dict({"_flow": 2}, **kw)}

    def test_the_newer_live_transcriber_with_keyword_hints(self):
        tr = rt.transcription(self.brief(client="M&S", unit_type="wine bay", liked_job="12148 Rollershutter Bunker"))
        self.assertEqual(tr["model"], "gpt-live-transcribe")
        self.assertEqual(tr["languages"], ["en"])
        self.assertNotIn("language", tr)
        self.assertEqual(tr["delay"], "low")
        self.assertIn("M and S", tr["keywords"])
        self.assertIn("12148 Rollershutter Bunker", tr["keywords"])
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9' -]{2,40}", k) for k in tr["keywords"]))
        self.assertLessEqual(len(tr["keywords"]), 40)
        self.assertLessEqual(len(tr["prompt"]), 500)

    def test_the_previous_one_when_asked(self):
        tr = rt.transcription(self.brief(client="Lindt"), live=False)
        self.assertEqual((tr["model"], tr["language"]), ("gpt-4o-transcribe", "en"))
        self.assertNotIn("keywords", tr)

    def test_a_call_still_starts_if_openai_refuses_the_new_one(self):
        import requests

        class R:
            def __init__(self, code, body):
                self.status_code, self.ok, self._b, self.text = code, code < 400, body, json.dumps(body)

            def json(self):
                return self._b
        sent = []

        def fake_post(url, **kw):
            tr = kw["json"]["session"]["audio"]["input"]["transcription"]
            sent.append(tr["model"])
            return R(400, {"error": "unknown parameter"}) if tr["model"] == "gpt-live-transcribe" else R(200, {"value": "ek_test"})
        real, key = requests.post, os.environ.get("OPENAI_API_KEY")
        requests.post, os.environ["OPENAI_API_KEY"] = fake_post, "test"
        try:
            j = L.app.test_client().post("/api/rt/session", json={"who": "t", "new": True}).get_json()
        finally:
            requests.post = real
            if key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = key
        self.assertEqual(sent, ["gpt-live-transcribe", "gpt-4o-transcribe"])
        self.assertEqual(j["key"], "ek_test")
        self.assertEqual(j["transcription"]["model"], "gpt-4o-transcribe")
        self.assertFalse(L.RT_LIVE[j["session"]])

    def test_a_read_back_of_the_keywords_is_dropped(self):
        tr = rt.transcription(self.brief(client="Lindt", unit_type="counter unit"))
        listed = ", ".join(tr["keywords"][2:10])
        self.assertTrue(L.echo_of(listed, rt.hint_text(tr)))


class TheDrivesTests(unittest.TestCase):
    def test_the_laptop_hears_whether_the_service_can_read_the_drives(self):
        j = L.app.test_client().get("/api/version", environ_base={"REMOTE_ADDR": "10.0.0.20"}).get_json()
        self.assertEqual(set(j["can_read"]), {"W", "S", "K"})

    def test_each_drive_has_its_network_name(self):
        self.assertEqual(L.DRIVES["K"], r"\\sdi-dc01\shareddata$\Shared")       # the one Publish reads every day
        self.assertTrue(all(v.startswith("\\\\") for v in L.DRIVES.values()))
        src = (WORK / "brief_lite" / "lite_app.py").read_text(encoding="utf-8")
        self.assertLess(src.index("    map_drives()"), src.index("threading.Thread(target=warm"))


class TheTightenedInstructionsTests(unittest.TestCase):
    """4 Nov 2026 (James: "tighten the voice instructions now"): one structured brief, every earlier rule kept once."""
    KEPT = {
        "names exactly as heard": "Names exactly as heard",
        "no extra first name or surname": "never add a first name or surname",
        "never guess a half-heard answer": "never guess and never move on",
        "a past job is said back first": "say its full number and name back",
        "seeing a GA is not a yes": "Seeing it is not a yes",
        "only the jobs offered by the app": "Offer only the jobs in which_past_job",
        "latest by date": "go by their dates",
        "past work answered in words": "answered in words from sdi_made_before",
        "show_past_work only when asked": "Call show_past_work only when they ask to see it",
        "never claim a render": "Never say a render is coming, being made or ready",
        "quiet while drawing": "then say nothing and ask nothing until it's on screen",
        "pack asked once": "ask once: the client pack",
        "set_pack only on their word": "Call set_pack only with what THEY said",
        "internal brief by any name": "any of them, at any point, means they want it",
        "Boots means both": '"Boots" or "booth" on its own means both',
        "never invent figures": "Never invent sizes, colours, materials, quantities or dates",
        "record before the next question": "before your next question",
        "Not saved means ask again": '"Not saved", ask that question again',
        "a 'not' answer is not a material": "isn't a material or a colour",
        "whole-unit size": "Size is the whole unit",
        "changes become new options": "next letter and the others stay",
        "stop means stop": '"Stop", "cancel that"',
        "Showroom notes": '"[Showroom: ...]" note',
        "no price promises": "Never promise a price",
        "drives read-only": "read-only to you",
        "noise and other voices": "Sorry - was that for me?",
        "thinking pauses": "they're thinking. Wait quietly",
        "answer their question first": "Whatever the AM raises comes first",
        "flag what looks wrong": "If something looks wrong",
        "right part of the day": "Greet only with the right part of",
    }

    def setUp(self):
        who = new_chat()
        _, self.s = say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        self.text = rt.instructions(self.s)

    def test_every_earlier_rule_is_still_there(self):
        for rule, words in self.KEPT.items():
            with self.subTest(rule=rule):
                self.assertIn(words, self.text)

    def test_it_is_shorter_and_has_no_incident_diary(self):
        self.assertLess(len(rt.VOICE_RULES), 8500)
        self.assertIsNone(re.search(r"\b\d{1,2} (Oct|Nov) 2026\b", rt.VOICE_RULES))     # dates live in the code comments
        self.assertLess(len(re.findall(r"\b[A-Z]{4,}\b", rt.VOICE_RULES)), 6)           # no wall of capitals

    def test_the_fixed_part_comes_first_for_the_cache(self):
        self.assertTrue(self.text.startswith(rt.VOICE_RULES))
        self.assertNotIn(datetime.now().strftime("%H:%M"), rt.VOICE_RULES)
        self.assertIn("# This call", self.text)
        self.assertIn("BRIEF SO FAR", self.text)

    def test_every_stage_has_its_hint(self):
        src = (WORK / "brief_lite" / "convo_parts.py").read_text(encoding="utf-8")
        stages = set(re.findall(r'return "([a-z_]+)"', src.split("def stage(s):", 1)[1].split("\ndef ", 1)[0]))
        self.assertTrue(stages)
        self.assertLessEqual(stages | {"rendering", "finalising"}, set(rt.NOW_DO))

    def test_a_ga_only_call_gets_its_hint(self):
        """It had none: NOW_DO["ga"] raised KeyError, so every tool result of a GA-only voice call failed."""
        s = {"id": "g", "visuals": [], "brief": {"_flow": 2, "_pack": "client", "client": "Tesco", "unit_type": "gondola end",
                                                  "size": "1800 x 1200 x 600 mm", "output": "GA only", "_render_q_done": 1,
                                                  "products_held": "drills", "colours_graphics": "red"}}
        self.assertEqual(convo.stage(s), "ga")
        self.assertIn("GA only", json.loads(rt.tool_result(s, []))["now_do"])

    def test_each_tool_named_in_the_rules_exists(self):
        names = {t["name"] for t in rt.TOOLS}
        for tool in re.findall(r"\b(record_answers|set_pack|focus|show_past_work|make_concepts|choose_option|"
                               r"change_option|more_options|finish_brief)\b", rt.VOICE_RULES):
            self.assertIn(tool, names)


class StillTrueTests(unittest.TestCase):
    """What Muhammad's earlier fixes guard, unchanged by any of this."""

    def test_a_past_job_is_still_confirmed_before_drawing(self):
        src = (WORK / "brief_lite" / "lite_app.py").read_text(encoding="utf-8")
        self.assertIn("Not drawing yet - check the past job first", src)

    def test_the_clash_check_still_needs_a_clear_answer(self):
        src = (WORK / "brief_lite" / "lite_app.py").read_text(encoding="utf-8")
        self.assertIn("Not drawn: the clash isn't settled", src)

    def test_no_secret_in_the_code(self):
        for p in (SRC / "brief_lite").glob("*.py"):
            with self.subTest(file=p.name):
                self.assertIsNone(re.search(r"sk-(ant-|proj-)?[A-Za-z0-9_\-]{24,}", p.read_text(encoding="utf-8", errors="ignore")))


if __name__ == "__main__":
    unittest.main()
