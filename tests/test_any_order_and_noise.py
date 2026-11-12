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
import time
import unittest
import urllib.parse
from pathlib import Path

REPO =Path(__file__).resolve().parent.parent
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
REF_LOOKUP = L.ref_lookup                                   # the real one, for the past-job tests
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
            self.assertNotIn("didn't ask for the brief PDF", out["output"])  # they did ask - so the gaps are checked:
            self.assertIn("Are you sure that's everything", out["output"])   # 11 Nov 2026: asked once, naming them
            self.assertEqual(started, [])
            L.log_msg(self.s["id"], "in", "yes, that's everything I have")
            out = self.tool("finish_brief", {"now": True})
            self.assertNotIn("Not built yet", out["output"])
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
        os.environ["LITE_SIGNIN_URL"] = ""                                   # the redirect off (see below)
        try:
            elsewhere = self.c.get("/", environ_base={"REMOTE_ADDR": "10.0.0.20"}).get_data(as_text=True)
        finally:
            os.environ.pop("LITE_SIGNIN_URL", None)
        self.assertIn("Enter the team access code", elsewhere)              # anyone else still needs it

    def test_opened_from_another_computer_it_goes_to_microsoft_sign_in(self):
        """8 Nov 2026 (James, on the office address: "why does it think I'm Andy ... it needs to read the person who is
        logged in"). Nobody is signed in on the office address, so the page goes to the https address, where Microsoft
        365 says who it is. The laptop scripts' checks and this machine are as before."""
        r = self.c.get("/", environ_base={"REMOTE_ADDR": "10.0.0.20"})
        self.assertEqual((r.status_code, r.headers["Location"]), (302, L.SIGNIN_URL_DEFAULT))
        self.assertEqual(L.SIGNIN_URL_DEFAULT, "https://sdiintelligence-sdidisplays.msappproxy.net/sameday/")
        r = self.c.get("/?s=abc", environ_base={"REMOTE_ADDR": "10.0.0.20"})            # the chat it was opened at
        self.assertEqual(r.headers["Location"], L.SIGNIN_URL_DEFAULT + "?s=abc")
        self.assertEqual(self.c.get("/api/version", environ_base={"REMOTE_ADDR": "10.0.0.20"}).status_code, 200)
        self.assertEqual(self.c.get("/").status_code, 200)                         # on the server itself
        self.assertEqual(self.c.get("/", headers=self.P).status_code, 200)         # carried by SDI Intelligence

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
        js = r.get_json()
        self.assertEqual(set(js), {"version", "can_read", "past_work"})
        # no team code here, so only counts, yes / no and a short reason - no jobs, clients or paths
        self.assertEqual(set(js["past_work"]), {"jobs", "estimates", "pictures", "why"})
        self.assertIsInstance(js["past_work"]["jobs"], int)
        self.assertLessEqual(len(js["past_work"]["why"]), 200)
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


class EveryToolCallIsLoggedTests(unittest.TestCase):
    """4 Nov 2026: 'the render didn't appear' - the voice had been refused, and no log said so."""

    def test_a_refusal_is_in_the_log(self):
        import contextlib
        import io
        who = new_chat()
        _, s = say(who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        L.log_msg(s["id"], "out", "Which pack do you need - client, internal, or both?")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            L.app.test_client().post("/api/rt/tool", json={"session": s["id"], "name": "set_pack",
                                                            "arguments": {"pack": "client"}})
        self.assertIn(f"rt tool {s['id']} set_pack: The AM hasn't answered yet", buf.getvalue())


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


def _past_jobs_index(folder):
    """A small projects.db as the W: indexer makes it: three jobs, their pictures and drawings."""
    import sqlite3
    con = sqlite3.connect(folder / "projects.db")
    con.executescript("""
        CREATE TABLE projects(job_no TEXT, name TEXT, brand TEXT, folder TEXT, first_date TEXT, last_date TEXT, n_drawings INT,
            n_images INT, n_renders INT, drawn_by TEXT, titles TEXT, weight_kg REAL, design_days TEXT, designers TEXT);
        CREATE TABLE project_images(img_id INTEGER PRIMARY KEY, job_no TEXT, kind TEXT, name TEXT, src TEXT, thumb TEXT);""")
    con.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("12148", "12148 - Rollershutter Forecourt Bunker", "Tesco", r"W:\Tesco\12148", "2025-11-03", "2026-02-10", 14, 4, 2,
         None, '["GA1 Forecourt Bunker", "Shutter detail"]', None, None, None),
        ("10474", "10474 - Boots No7 Triple Mod", "Boots", r"W:\Boots\10474", "2023-03-01", "2023-06-01", 9, 2, 1,
         None, '["GA1 Triple Mod"]', None, None, None),
        ("11800", "11800 - Milwaukee M18 Gondola End", "TTI", r"W:\TTI\11800", "2024-05-01", "2024-07-01", 6, 2, 1,
         None, '["GA1 Gondola End"]', None, None, None)])
    con.executemany("INSERT INTO project_images VALUES (?,?,?,?,?,?)", [
        (0, "12148", "drawing", "12148-00 GA", r"W:\Tesco\12148\GA.pdf", "t0.jpg"),
        (1, "12148", "render", "bunker front", r"W:\Tesco\12148\front.png", "t1.jpg"),
        (2, "12148", "render", "bunker side", r"W:\Tesco\12148\side.png", "t2.jpg"),
        (3, "10474", "render", "triple mod", r"W:\Boots\10474\r.png", "t3.jpg"),
        (4, "11800", "creative", "gondola visual", r"W:\TTI\11800\v.jpg", "t4.jpg"),
        (5, "11800", "drawing", "11800 GA", r"W:\TTI\11800\GA.pdf", "t5.jpg")])
    con.commit()
    con.close()


class PastJobsWithoutThePictureIndexTests(unittest.TestCase):
    """4 November 2026 (James): "can it see the W:/ ? It keeps saying it can't see past jobs". The service could read
    W: and K:, but the past-work search opened the picture index (all_img_index.npz) first, the server has none, and
    so every look-up failed - a job's own number too. Now the job index is enough; pictures only add look-alikes."""

    def setUp(self):
        import lite_search
        self.S = lite_search
        self.keep = {k: getattr(lite_search, k) for k in ("JOBS_DB", "ESTIMATES_DB", "PICTURES", "clip_model")}
        self.dir = Path(tempfile.mkdtemp(prefix="pastjobs-"))
        _past_jobs_index(self.dir)
        self._fresh(JOBS_DB=str(self.dir / "projects.db"), ESTIMATES_DB=str(self.dir / "knowledge.db"),
                    PICTURES=str(self.dir / "all_img_index.npz"))

    def _fresh(self, **attrs):
        if self.S._state.get("con"):
            self.S._state["con"].close()
        for d in (self.S._state, self.S._pic, self.S._clip):
            d.clear()
        for k, v in attrs.items():
            setattr(self.S, k, v)

    def tearDown(self):
        self._fresh(**self.keep)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_job_named_by_its_number_or_its_name_is_found(self):
        self.assertEqual(self.S.named_jobs("refer to job 12148"), ["12148"])
        rr = self.S.resolve_reference("the coal bunker we did", "Tesco")
        self.assertEqual(rr["options"][0][0], "12148")
        self.assertEqual(self.S.project_rows(["12148"])["12148"]["name"], "12148 - Rollershutter Forecourt Bunker")

    def test_the_brief_finds_its_past_jobs_by_words_with_their_renders(self):
        res = self.S.search("coal bunker with a roller shutter", client="Tesco")
        self.assertEqual(res[0]["job_no"], "12148")
        self.assertEqual([im["kind"] for im in res[0]["images"]], ["render", "render"])    # renders, not the GA
        res = self.S.search("Milwaukee M18 gondola end")                                   # no client said yet
        self.assertIn("11800", [r["job_no"] for r in res])
        self.assertNotIn("10474", [r["job_no"] for r in res])

    def test_what_it_can_find_is_reported_and_why_pictures_are_off(self):
        st = self.S.status()
        self.assertEqual(st["jobs"], 3)
        self.assertFalse(st["pictures"])
        self.assertFalse(st["estimates"])
        self.assertIn("all_img_index.npz", st["why"])
        self.assertIsNone(self.S.pictures())
        self.assertFalse((self.dir / "knowledge.db").exists())

    def test_no_job_index_is_said_and_never_made_empty(self):
        self._fresh(JOBS_DB=str(self.dir / "missing" / "projects.db"))
        st = self.S.status()
        self.assertEqual((st["jobs"], st["why"]), (0, "no job index (projects.db)"))
        with self.assertRaises(FileNotFoundError):
            self.S.named_jobs("job 12148")
        self.assertFalse((self.dir / "missing" / "projects.db").exists())

    def test_a_picture_index_newer_than_the_job_index_is_not_used(self):
        import numpy as np
        np.savez(self.dir / "all_img_index.npz", emb=np.zeros((9, 4), dtype=np.float32))    # 9 pictures, 6 in projects.db
        self._fresh(clip_model=lambda: object())
        self.assertIsNone(self.S.pictures())                 # picture 7 would be labelled as some other job
        self.assertIn("newer than the job index", self.S.status()["why"])
        self.assertEqual(self.S.search("coal bunker", client="Tesco")[0]["job_no"], "12148")

    def test_sdi_made_this_before_needs_only_the_job_index(self):
        here = WORK / "brief_lite"
        shutil.copy(self.dir / "projects.db", here / "projects.db")
        try:
            said = convo.same_before({"brief": {"client": "Tesco", "unit_type": "coal bunker"}})
        finally:
            (here / "projects.db").unlink()
        self.assertTrue(said.startswith("12148 Rollershutter Forecourt Bunker (2026"), said)
        self.assertFalse((here / "knowledge.db").exists())          # no K: estimates index: no quote, nothing made
        self.assertEqual(convo.same_before({"brief": {"client": "Tesco", "unit_type": "coal bunker"}}), "")
        self.assertFalse((here / "projects.db").exists())

    def test_the_update_check_hears_about_past_work(self):
        js = L.app.test_client().get("/api/version").get_json()
        self.assertEqual(js["past_work"]["jobs"], 3)
        self.assertIn("pictures", js["past_work"])

    def test_web_pictures_are_not_used_unchecked_without_clip(self):
        keep = L.moodboard.G.get("clip")
        L.moodboard.G["clip"] = lambda: None
        try:
            self.assertEqual(L.moodboard._rank([str(self.dir / "projects.db")], "a gondola end", 2), [])
        finally:
            L.moodboard.G["clip"] = keep


BUNKER = "12148 - Rollershutter Forecourt Bunker (2026-02)"
OTHER = "11800 - Milwaukee M18 Gondola End (2024-07)"


class LettingGoOfAPastJobTests(unittest.TestCase):
    """4 November 2026 (Andy, after testing): "it was suggesting a past job and it was being quite forceful around that -
    I was trying to move it away from that but it was still insisting. Then it froze." On a call nothing let a suggested
    job go: "something new" was read only after a call's lines had returned, "no" led to the other matches and then a
    job number, and the render stayed refused."""

    def setUp(self):
        import lite_search
        self.S = lite_search
        self.keep = {k: getattr(lite_search, k) for k in ("JOBS_DB", "ESTIMATES_DB", "PICTURES", "WALK_SECONDS")}
        self.dir = Path(tempfile.mkdtemp(prefix="letgo-"))
        _past_jobs_index(self.dir)
        self._fresh(JOBS_DB=str(self.dir / "projects.db"), ESTIMATES_DB=str(self.dir / "knowledge.db"),
                    PICTURES=str(self.dir / "all_img_index.npz"))
        self.client = L.app.test_client()
        self.who = new_chat()
        _, self.s = say(self.who, "Tesco want a coal bunker", {"client": "Tesco", "unit_type": "coal bunker"})
        self.stub, L.ref_lookup = L.ref_lookup, REF_LOOKUP          # the real look-up, on the small job index

    def _fresh(self, **attrs):
        if self.S._state.get("con"):
            self.S._state["con"].close()
        for d in (self.S._state, self.S._pic, self.S._clip):
            d.clear()
        for k, v in attrs.items():
            setattr(self.S, k, v)

    def tearDown(self):
        L.ref_lookup = self.stub
        self._fresh(**self.keep)
        shutil.rmtree(self.dir, ignore_errors=True)

    def brief(self, **state):
        s = L._session_by_id(self.s["id"])
        s["brief"].update(state)
        L.save_session(s)
        return s

    def on_the_call(self, text):
        """What the AM says on a live call, the way the call sends it (record_only - where it used to be lost)."""
        L.handle(self.who, "Test", text, voice=True, record_only=True, sid=self.s["id"])
        return L._session_by_id(self.s["id"])["brief"]

    def test_something_new_on_a_call_lets_the_suggested_job_go(self):
        self.brief(_ref_confirm={"label": BUNKER, "hint": "", "others": [OTHER]})
        b = self.on_the_call("No, let's do something new")
        for k in ("_ref_confirm", "_ref_ask", "_ref_more"):
            self.assertNotIn(k, b)
        self.assertEqual(b.get("design_route"), "new")
        self.assertIn("12148", b.get("_ref_declined"))
        self.assertIn("dropped", json.loads(rt.tool_result(L._session_by_id(self.s["id"]), []))["which_past_job"])

    def test_other_ways_of_moving_away_work_too(self):
        for said in ("forget that, start again", "I don't want a past job", "none of those", "never mind that one",
                     "something different please", "we'll do it from scratch"):
            with self.subTest(said=said):
                self.brief(_ref_ask=[BUNKER, OTHER], _ref_off=None, design_route=None)
                b = self.on_the_call(said)
                self.assertNotIn("_ref_ask", b)
                self.assertTrue(b.get("_ref_off"))

    def test_no_offers_the_others_once_then_no_is_no(self):
        self.brief(_ref_confirm={"label": BUNKER, "hint": "", "others": [OTHER]})
        b = self.on_the_call("No")
        self.assertEqual(b.get("_ref_ask"), [OTHER])
        b = self.on_the_call("No")
        self.assertNotIn("_ref_ask", b)
        self.assertNotIn("_ref_more", b)            # it used to go on to ask for a job number
        self.assertTrue(b.get("_ref_off"))

    def test_no_with_nothing_else_never_asks_for_a_number(self):
        self.brief(_ref_confirm={"label": BUNKER, "hint": "", "others": []})
        b = self.on_the_call("nope")
        self.assertNotIn("_ref_more", b)
        self.assertTrue(b.get("_ref_off"))

    def test_yes_with_a_design_change_still_follows_the_job(self):
        self.brief(_ref_confirm={"label": BUNKER, "hint": "", "others": []})
        b = self.on_the_call("Yes, that one, but make the shutter something different")
        self.assertEqual(b.get("_ref_job"), "12148")
        self.assertFalse(b.get("_ref_off"))

    def test_describing_another_job_is_not_taken_as_a_no(self):
        self.brief(_ref_more=1)
        b = self.on_the_call("not sure of the number, it was the one with the roller shutter")
        self.assertFalse(b.get("_ref_off"))

    def test_letting_go_also_answers_is_it_a_repeat(self):
        self.brief(_ref_confirm={"label": BUNKER, "hint": "", "others": []})
        b = self.on_the_call("forget it, something new")
        self.assertEqual(b.get("repeat_of"), "New design")

    def test_asked_once_for_a_number_dont_know_ends_it(self):
        self.brief(_ref_more=1)
        b = self.on_the_call("I don't know it")
        self.assertNotIn("_ref_more", b)
        self.assertTrue(b.get("_ref_off"))

    def test_a_chosen_job_stays_for_a_design_change_and_goes_when_they_say_so(self):
        self.brief(_ref_job="12148", design_route="past", liked_job=BUNKER + " - the AM asked to follow it closely",
                   size="1500 x 2000 x 900 mm (from 12148)", _size_from_ref="12148")
        b = self.on_the_call("make the shutter something different, maybe grey")
        self.assertEqual(b.get("_ref_job"), "12148")
        b = self.on_the_call("actually forget the past job, start again")
        self.assertNotIn("_ref_job", b)
        self.assertEqual(b.get("design_route"), "new")
        self.assertNotIn("size", b)                 # the old job's size, never said by the AM
        self.assertNotIn("liked_job", b)

    def test_a_new_design_is_never_held_up_by_a_past_job_being_checked(self):
        self.brief(_ref_confirm={"label": BUNKER, "hint": "", "others": []})
        refused = json.loads(self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": "make_concepts",
                             "arguments": {"output": "3D render", "design_route": "past"}}).get_json()["output"])
        self.assertIn("Not drawing yet", refused["error"])
        self.assertIn("design_route 'new'", refused["error"])        # the way out is always given
        keep = (L._start_turn, L._busy_until_done)
        started = []

        def fake_turn(*a, **k):
            started.append(a)
            L.JOBS["fake"] = {"ch": L.Channel("pending"), "done": True, "session": self.s["id"], "brief": {}, "error": None}
            return "fake"
        L._start_turn, L._busy_until_done = fake_turn, (lambda *a: None)
        try:
            out = json.loads(self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": "make_concepts",
                             "arguments": {"output": "3D render", "design_route": "new"}}).get_json()["output"])
        finally:
            L._start_turn, L._busy_until_done = keep
        self.assertTrue(out.get("started"), out)
        self.assertEqual(len(started), 1)
        self.assertNotIn("_ref_confirm", L._session_by_id(self.s["id"])["brief"])

    def test_one_list_of_past_jobs_per_brief_never_round_and_round(self):
        """10 Nov 2026 (Muhammad: "it was still pushing down the particular job reference"). After the first render a
        liked job was saved and three past jobs read out (8928, 6548, 5988); his answer was saved as a new liked job and
        a different three read out (12271, 4970, ...) - round and round, never drawn."""
        def draw():
            keep = (L._start_turn, L._busy_until_done)
            started = []

            def fake_turn(*a, **k):
                started.append(a)
                L.JOBS["fake"] = {"ch": L.Channel("pending"), "done": True, "session": self.s["id"], "brief": {},
                                  "error": None}
                return "fake"
            L._start_turn, L._busy_until_done = fake_turn, (lambda *a: None)
            try:
                out = json.loads(self.client.post("/api/rt/tool", json={
                    "session": self.s["id"], "name": "make_concepts",
                    "arguments": {"output": "3D render", "design_route": "past"}}).get_json()["output"])
            finally:
                L._start_turn, L._busy_until_done = keep
            return out, started
        self.brief(_ref_ask=["8928 - Gift Card Gondola End (2021-09)", "6548 - Tesco Transformation Gondola End (2016-09)"])
        out, started = draw()
        self.assertIn("more than one past job fits", out["error"])      # the first list is read out
        self.assertEqual(started, [])
        self.brief(_ref_ask=["12271 - Stationary Branded Double Mod Refresh (2026-01)", "4970 - Tesco Bank Queue Barrier"])
        out, started = draw()                                            # a second list: never read out
        self.assertTrue(out.get("started"), out)
        self.assertEqual(len(started), 1)
        self.assertIn("couldn't be pinned down", out["note"])
        self.assertIn("Never read out another list", out["note"])
        b = L._session_by_id(self.s["id"])["brief"]
        self.assertNotIn("_ref_ask", b)
        self.assertEqual(b.get("design_route"), "new")
        self.brief(_ref_ask=["8928 - Gift Card Gondola End (2021-09)"])  # and none after that, in this brief
        out, _ = draw()
        self.assertTrue(out.get("started"), out)

    def test_something_new_saved_as_the_liked_job_is_not_looked_up(self):
        self.brief(liked_job="something new, not the old one")
        keep = L.ref_lookup
        looked = []
        # only a lookup of THIS liked job counts: a background turn left running by an earlier test can call ref_lookup
        # while it is swapped out here (5 Nov 2026: one run in three failed on another test's call)
        L.ref_lookup = lambda b, text: looked.append(text) if "something new" in (text or "") else None
        try:
            self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": "make_concepts",
                             "arguments": {"output": "3D render", "design_route": "mix"}})
        finally:
            L.ref_lookup = keep
        self.assertEqual(looked, [])

    def test_wanting_something_is_not_pointing_at_a_past_job(self):
        b = {"client": "Tesco", "unit_type": "coal bunker"}
        for said in ("I'd like the header lit", "they'd like the shelves in oak", "we like the blue"):
            with self.subTest(said=said):
                L.ref_lookup(b, said)
                self.assertFalse(L.ref_pending(b), b)
        L.ref_lookup(b, "make it like the bunker we did")
        self.assertTrue(L.ref_pending(b))

    def test_a_job_turned_down_is_not_offered_again_unless_named(self):
        b = {"client": "Tesco", "unit_type": "coal bunker", "_ref_declined": ["12148"], "_ref_off": 1}
        L.ref_lookup(b, "make it like the bunker we did")
        self.assertNotIn("12148", json.dumps({k: b.get(k) for k in ("_ref_confirm", "_ref_ask")}))
        L.ref_lookup(b, "actually, refer to job 12148")
        self.assertTrue(b.get("_ref_confirm", {}).get("label", "").startswith("12148"))

    def test_the_voice_is_told_to_let_it_go(self):
        self.assertIn("Suggest a past job at most once", rt.VOICE_RULES)
        self.assertIn("offer the other matches once", rt.VOICE_RULES)

    def test_a_big_job_folder_on_w_never_holds_the_call_up(self):
        import sqlite3
        root = self.dir / "W" / "12148"
        (root / "deep" / "deeper").mkdir(parents=True)
        (root / "GA.pdf").write_bytes(b"%PDF")
        (root / "deep" / "deeper" / "late.pdf").write_bytes(b"%PDF")
        con = sqlite3.connect(self.dir / "projects.db")
        con.execute("UPDATE projects SET folder=? WHERE job_no='12148'", (str(root),))
        con.commit()
        con.close()
        self._fresh(WALK_SECONDS=0)
        self.assertEqual([n for n, _ in self.S.live_files("12148")], ["GA"])      # stopped after the first folder
        self._fresh(WALK_SECONDS=8)
        self.assertEqual(sorted(n for n, _ in self.S.live_files("12148")), ["GA", "late"])

    def test_the_page_never_waits_for_ever(self):
        page = (WORK / "brief_lite" / "lite_page.html").read_text(encoding="utf-8")
        self.assertIn("async function pollQuiet(turn,wait,maxMs)", page)
        self.assertEqual(page.count("pollQuiet(j.turn,w,"), 2)              # both waits have a limit
        self.assertEqual(page.count("if(w.dataset.late)"), 2)               # and both carry on, honestly
        self.assertNotIn("pollQuiet(j.turn,w)", page)


GONDOLA_JOBS = [("5988", "5988 - Tesco Gondola End", "2016-01-20"), ("8928", "8928 - Gift Card Gondola End", "2021-09-01"),
                ("6548", "6548 - Tesco Transformation Gondola End", "2016-09-01"),
                ("12271", "12271 - Stationary Branded Double Mod Refresh", "2026-01-10"),
                ("4970", "4970 - Tesco Bank Queue Barrier Gift Card Unit", "2015-05-01")]
FIRST_LIST = ["8928 - Gift Card Gondola End (2021-09)", "6548 - Tesco Transformation Gondola End (2016-09)",
              "5988 - Tesco Gondola End (2016-01)"]


class ASaidJobNumberIsTheJobTests(unittest.TestCase):
    """10 November 2026, Muhammad's call (chat 9de922ce52), and James: "That's still wrong, because he'd clearly asked
    for 5988 - this is to be the basis for the new one. The look and feel, but of course he can ask for a different
    colour, dimensions etc." He said "five nine double eight" five times and "yes" to "5988 - Tesco Gondola End, is that
    the one?", and was offered 8928, 6548, then 12271, 4970, then "do you mean 12271?" ("double" matched "Double Mod").
    "One two four zero eight" wasn't on file and was never said to be missing. And "a new render referencing 5988" was
    sent as design_route 'new', which let 5988 go."""

    def setUp(self):
        import lite_search, sqlite3
        self.S = lite_search
        self.keep = {k: getattr(lite_search, k) for k in ("JOBS_DB", "ESTIMATES_DB", "PICTURES", "WALK_SECONDS")}
        self.dir = Path(tempfile.mkdtemp(prefix="saidjob-"))
        _past_jobs_index(self.dir)
        con = sqlite3.connect(self.dir / "projects.db")
        con.executemany("INSERT INTO projects (job_no, name, brand, folder, first_date, last_date, n_drawings, n_images, "
                        "n_renders) VALUES (?,?,?,?,?,?,0,0,0)",
                        [(j, nm, "Tesco", rf"W:\Tesco\{j}", d, d) for j, nm, d in GONDOLA_JOBS])
        con.commit()
        con.close()
        self._fresh(JOBS_DB=str(self.dir / "projects.db"), ESTIMATES_DB=str(self.dir / "knowledge.db"),
                    PICTURES=str(self.dir / "all_img_index.npz"))
        self.client = L.app.test_client()
        self.who = new_chat()
        _, self.s = say(self.who, "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        self.stub, L.ref_lookup = L.ref_lookup, REF_LOOKUP          # the real look-up, on the small job index

    def _fresh(self, **attrs):
        if self.S._state.get("con"):
            self.S._state["con"].close()
        for d in (self.S._state, self.S._pic, self.S._clip):
            d.clear()
        for k, v in attrs.items():
            setattr(self.S, k, v)

    def tearDown(self):
        L.ref_lookup = self.stub
        self._fresh(**self.keep)
        shutil.rmtree(self.dir, ignore_errors=True)

    def brief(self, **state):
        s = L._session_by_id(self.s["id"])
        s["brief"].update(state)
        L.save_session(s)
        return s

    def on_the_call(self, text):
        """A line the AM says on the call: logged (as /api/rt/log does) and read the way the call reads it."""
        L.log_msg(self.s["id"], "in", text)
        L.handle(self.who, "Test", text, voice=True, record_only=True, sid=self.s["id"])
        return L._session_by_id(self.s["id"])["brief"]

    def draw(self, route="past"):
        keep = (L._start_turn, L._busy_until_done)
        started = []

        def fake_turn(*a, **k):
            started.append(k.get("t_override"))
            L.JOBS["fake"] = {"ch": L.Channel("pending"), "done": True, "session": self.s["id"], "brief": {}, "error": None}
            return "fake"
        L._start_turn, L._busy_until_done = fake_turn, (lambda *a: None)
        try:
            out = json.loads(self.client.post("/api/rt/tool", json={
                "session": self.s["id"], "name": "make_concepts",
                "arguments": {"output": "3D render", "design_route": route}}).get_json()["output"])
        finally:
            L._start_turn, L._busy_until_done = keep
        return out, started

    def test_job_numbers_read_out_in_words(self):
        for said, digits in (("five nine double eight", "5988"), ("one two four zero eight", "12408"),
                             ("fifty nine eighty eight", "5988"), ("twelve four oh eight", "12408"),
                             ("twelve thousand four hundred and eight", "12408"), ("one, two, one, four, eight", "12148"),
                             ("5 9 double 8", "5988"), ("ten five one nine", "10519")):
            with self.subTest(said=said):
                self.assertEqual(L.spoken_digits(said), digits)
        for said in ("one or two shelves", "a double sided unit", "the one with two shelves", "Oh, the one we did",
                     "make it double", "two or three"):
            with self.subTest(said=said):
                self.assertNotRegex(L.spoken_digits(said), r"\d{3}")

    def test_a_size_a_quantity_money_or_a_year_is_not_a_job(self):
        for said in ("1800 high, 600 wide and 400 deep", "1800 x 600 x 400", "eighteen hundred high", "budget of £5000",
                     "about 3000 units", "the 2016 one", "for 200 stores", "store 4567", "two thousand units",
                     "order number 45678"):
            with self.subTest(said=said):
                self.assertEqual(L.said_jobs(said), [])
        self.assertEqual([x["n"] for x in L.said_jobs("Do you know about the job number one two four zero eight?")],
                         ["12408"])
        self.assertTrue(L.said_jobs("job number 12408")[0]["strong"])

    def test_a_bare_number_answering_another_question_is_not_a_job(self):
        import sqlite3
        con = sqlite3.connect(self.dir / "projects.db")
        con.execute("INSERT INTO projects (job_no, name, brand, last_date) VALUES ('1800', '1800 - Old Plinth', 'Boots', "
                    "'2009-01-01')")
        con.commit()
        con.close()
        self._fresh()
        for said in ("1800, 600, 400", "eighteen hundred", "1800"):
            with self.subTest(said=said):
                b = self.on_the_call(said)
                self.assertNotIn("_ref_confirm", b)
        self.brief(_ref_job="5988", design_route="past")
        b = self.on_the_call("make it 1800")
        self.assertEqual(b.get("_ref_job"), "5988")
        self.assertNotIn("_ref_confirm", b)

    def test_muhammads_call_follows_5988(self):
        self.brief(_ref_ask=list(FIRST_LIST), _ref_ask_read=list(FIRST_LIST), liked_job="our past jobs")
        b = self.on_the_call("Do you know about the job number one two four zero eight?")
        self.assertEqual(b.get("_ref_missing"), "12408")             # said to be missing, never swapped for a list
        self.assertNotIn("_ref_ask", b)
        told = json.loads(rt.tool_result(L._session_by_id(self.s["id"]), []))["which_past_job"]
        self.assertIn("12408", told["not_on_file"])
        self.assertIn("Never offer other jobs", told["not_on_file"])
        b = self.on_the_call("Could you make me a new render from five nine double eight?")
        self.assertTrue(b["_ref_confirm"]["label"].startswith("5988 - Tesco Gondola End (2016-01)"), b.get("_ref_confirm"))
        self.assertNotIn("_ref_missing", b)
        b = self.on_the_call("Yes.")
        self.assertEqual(b.get("_ref_job"), "5988")
        self.assertEqual(b.get("design_route"), "past")
        out, started = self.draw("new")                             # the voice sent "a new render" as 'new'
        self.assertTrue(out.get("started"), out)
        b = L._session_by_id(self.s["id"])["brief"]
        self.assertEqual(b.get("_ref_job"), "5988")                  # still the basis
        self.assertEqual(started[0]["updates"].get("design_route"), "past")
        self.assertIn("basis", json.loads(rt.tool_result(L._session_by_id(self.s["id"]), []))["following_past_job"])

    def test_the_basis_stays_through_colour_and_size_changes(self):
        self.brief(_ref_job="5988", design_route="past", liked_job="5988 - Tesco Gondola End (2016-01) - the AM asked "
                                                                   "to follow it closely")
        for said in ("make it a completely different colour, blue", "brand new graphics on the header",
                     "make it 1800 high and 900 wide", "a new render in black please", "no, not that colour"):
            with self.subTest(said=said):
                b = self.on_the_call(said)
                self.assertEqual(b.get("_ref_job"), "5988")
        b = self.on_the_call("actually forget the past job, start again")
        self.assertNotIn("_ref_job", b)                             # only their own words let it go

    def test_saying_it_again_after_the_read_back_is_a_yes(self):
        b = self.on_the_call("refer to five nine double eight")
        self.assertTrue(b["_ref_confirm"]["label"].startswith("5988"))
        self.assertNotIn("_ref_job", b)                             # read back first
        b = self.on_the_call("One to follow five nine double eight")
        self.assertEqual(b.get("_ref_job"), "5988")

    def test_a_number_beats_the_words_in_a_list(self):
        self.brief(_ref_ask=["12271 - Stationary Branded Double Mod Refresh (2026-01)",
                             "4970 - Tesco Bank Queue Barrier Gift Card Unit (2015-05)"])
        b = self.on_the_call("Five nine double eight.")
        self.assertTrue(b["_ref_confirm"]["label"].startswith("5988"), b.get("_ref_confirm"))
        self.assertNotIn("_ref_ask", b)

    def test_a_number_is_never_a_word_search(self):
        b = self.on_the_call("Just make a render, new render referencing 5988")
        self.assertTrue(b["_ref_confirm"]["label"].startswith("5988"), b)
        self.assertNotIn("_ref_ask", b)

    def test_a_render_asked_for_from_a_number_is_checked_once_then_drawn(self):
        L.log_msg(self.s["id"], "in", "new render referencing five nine double eight")
        out, started = self.draw("new")
        self.assertIn("Do you mean 5988 - Tesco Gondola End", out["error"])
        self.assertEqual(started, [])
        self.on_the_call("yes")
        out, started = self.draw("new")
        self.assertTrue(out.get("started"), out)
        self.assertEqual(L._session_by_id(self.s["id"])["brief"].get("_ref_job"), "5988")

    def test_a_number_not_on_file_is_said_once_then_it_is_a_new_design(self):
        b = self.on_the_call("refer to job one two four zero eight")
        self.assertEqual(b.get("_ref_missing"), "12408")
        out, started = self.draw()
        self.assertIn("12408 isn't in SDI's past jobs", out["error"])
        self.assertIn("1 2 4 0 8", out["error"])
        b = self.on_the_call("yes, one two four zero eight")
        self.assertNotIn("_ref_missing", b)
        self.assertEqual(b.get("_ref_not_on_file"), "12408")
        self.assertEqual(b.get("design_route"), "new")
        self.assertIn("12408 isn't on file", json.loads(rt.tool_result(L._session_by_id(self.s["id"]), []))
                      ["which_past_job"]["dropped"])
        out, started = self.draw()
        self.assertTrue(out.get("started"), out)                    # no list, no second ask

    def test_drawn_anyway_after_missing_is_told_once(self):
        self.on_the_call("refer to job 12408")
        out, _ = self.draw()
        self.assertIn("12408", out["error"])
        out, started = self.draw()
        self.assertTrue(out.get("started"), out)
        self.assertIn("12408 isn't in SDI's past jobs", out["note"])

    def test_misheard_and_corrected(self):
        self.on_the_call("refer to job 12408")
        b = self.on_the_call("no, it's one two one four eight")
        self.assertNotIn("_ref_missing", b)
        self.assertTrue(b["_ref_confirm"]["label"].startswith("12148"))

    def test_turning_it_down_by_number(self):
        self.brief(_ref_job="5988", design_route="past", liked_job="5988 - Tesco Gondola End - the AM asked to follow it "
                                                                   "closely")
        b = self.on_the_call("I don't want 5988, let's do something new")
        self.assertNotIn("_ref_job", b)
        self.assertEqual(b.get("design_route"), "new")

    def test_a_new_design_said_plainly_still_lets_a_pending_job_go(self):
        self.brief(_ref_confirm={"label": "5988 - Tesco Gondola End (2016-01)", "hint": "", "others": []})
        L.log_msg(self.s["id"], "in", "no, let's do something completely new")
        out, started = self.draw("new")
        self.assertTrue(out.get("started"), out)
        self.assertNotIn("_ref_confirm", L._session_by_id(self.s["id"])["brief"])


class TheBaseQuestionsAreAChecklistTests(unittest.TestCase):
    """11 November 2026, Andy: "it pushed ahead and generated the brief without ensuring that all the questions were
    answered". James: the base questions are gone through, each answer saved and ticked off like a checklist; the AM
    can add more or change the flow; and if they say that's all they have, SDI Live asks once "are you sure that's
    everything?" and then builds it, with what is still open listed as open points."""

    def setUp(self):
        self.built = []
        self.keep = convo.finish_pack
        convo.finish_pack = lambda s, ch, quiet=False: self.built.append(s["id"])
        self.who = new_chat()
        _, self.s = say(self.who, "Tesco want a gondola end by the tills, 1800 x 1330 x 450, steel",
                        {"client": "Tesco", "unit_type": "gondola end", "placement": "by the tills",
                         "size": "1800 x 1330 x 450 mm", "materials": "Powder-coated steel"})

    def tearDown(self):
        convo.finish_pack = self.keep

    def brief(self, **state):
        s = L._session_by_id(self.s["id"])
        s["brief"].update(state)
        L.save_session(s)
        return s["brief"]

    def test_thats_all_i_have_is_asked_once_then_built(self):
        out, s = say(self.who, "that's all the information I have, build the brief", {}, "finish")
        q = asked(out)
        self.assertIn("Are you sure that's everything", q)
        self.assertIn("still open", q)
        self.assertEqual(self.built, [])                                  # nothing built past open questions unasked
        out, s = say(self.who, "Yes - build it now")
        self.assertEqual(self.built, [s["id"]])                           # their yes builds it
        self.assertNotIn("Are you sure", asked(out))

    def test_build_it_now_is_asked_too_and_never_skips_the_check(self):
        # ("skip the rest" alone only stops the questions - nothing is built - so it needs no check)
        for said in ("just build the brief now as it is", "build the brief anyway, that's all I've got"):
            with self.subTest(said=said):
                self.brief(_gaps_ok=None, _asking=[None])
                out, _ = say(self.who, said, {}, "finish")
                self.assertIn("Are you sure that's everything", asked(out))
                self.assertEqual(self.built, [])

    def test_lets_answer_them_carries_on_with_the_questions(self):
        say(self.who, "that's all I have", {}, "finish")
        self.brief(_deferred=["lighting"], _askn={"lighting": 2})
        out, s = say(self.who, "No, let's answer them")
        self.assertEqual(self.built, [])
        self.assertNotIn("Are you sure", asked(out))
        self.assertNotIn("_deferred", s["brief"])                         # the skipped ones are asked again
        self.assertTrue(asked(out))                                       # and the next question is asked

    def test_a_question_left_unanswered_stays_open_not_not_known(self):
        for _ in range(2):
            self.brief(_asking=["lighting"])
            say(self.who, "it's for their spring range")                  # not an answer to lighting
        b = L._session_by_id(self.s["id"])["brief"]
        self.assertFalse(b.get("lighting"))                               # never written as "not known"
        self.assertIn("lighting", b.get("_deferred") or [])
        self.assertNotIn("lighting", [k for k, _, _ in convo.plan(b)])     # not asked again in turn...
        row = next(c for c in convo.checklist(b) if c["key"] == "lighting")
        self.assertEqual((row["status"], row["skipped"]), ("open", True))  # ...but still open on the checklist
        self.assertIn(row["label"], convo.sure_question(b))                # and named before anything is built

    def test_a_live_call_line_never_marks_a_question_skipped(self):
        for _ in range(3):
            self.brief(_asking=["lighting"])
            L.handle(self.who, "Test", "it's for their spring range", voice=True, record_only=True, sid=self.s["id"])
        self.assertNotIn("lighting", L._session_by_id(self.s["id"])["brief"].get("_deferred") or [])

    def test_the_checklist_ticks_what_was_answered(self):
        self.brief(lighting="not known", colours_graphics="Black and red (assumed)")
        c = {r["key"]: r["status"] for r in convo.checklist(L._session_by_id(self.s["id"])["brief"])}
        self.assertEqual(c["client"], "answered")
        self.assertEqual(c["lighting"], "not known")                      # asked, and that was the answer
        self.assertEqual(c["colours_graphics"], "assumed")                # filled in for them - to confirm
        self.assertIn("open", c.values())
        page = L.app.test_client().get(f"/api/session/{self.s['id']}").get_json()["session"]["brief"]
        self.assertEqual({r["key"]: r["status"] for r in page["_checklist"]}, c)   # the page draws it
        self.assertNotIn("_checklist", L._session_by_id(self.s["id"])["brief"])    # and it is never stored

    def test_assumed_answers_are_open_points_on_the_brief(self):
        b = self.brief(colours_graphics="Black and red (assumed)")
        self.assertTrue(any("assumed: Black and red" in q and "confirm" in q for _, _, q in convo.missing_list(b)))

    def test_on_a_call_the_line_that_asked_is_never_the_yes(self):
        client = L.app.test_client()
        tool = lambda: json.loads(client.post("/api/rt/tool", json={"session": self.s["id"], "name": "finish_brief",
                                                                    "arguments": {"now": True}}).get_json()["output"])
        L.log_msg(self.s["id"], "in", "that's all I have, build the brief PDF")
        self.assertIn("Are you sure that's everything", tool()["error"])
        self.assertIn("Not built yet", tool()["error"])                   # called again, nobody answered: still not
        self.assertTrue(tool().get("still_open"))

    def test_the_page_shows_it_and_a_call_is_not_ended_by_thats_all_i_have(self):
        page = (WORK / "brief_lite" / "lite_page.html").read_text(encoding="utf-8")
        self.assertIn('id="chk"', page)
        self.assertIn("brief._checklist", page)
        self.assertIn("!/\\b(info|information|details|have|got|know|brief|pack|pdf|build|make|generate|render|document|"
                      "questions?)\\b/i.test(tx)", page)


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


class LookAlikeWithoutThePictureIndexTests(unittest.TestCase):
    """5 November 2026 (James): "can we synthesise this somehow? we can do the search and mock up the matching". The
    server has no picture index, so the words find the likely jobs and Claude looks at one render of each, side by
    side on one numbered sheet, and scores how much each looks like the unit being briefed."""

    def setUp(self):
        import lite_search
        self.S = lite_search
        self.keep = {k: getattr(lite_search, k) for k in ("JOBS_DB", "ESTIMATES_DB", "PICTURES")}
        self.dir = Path(tempfile.mkdtemp(prefix="look-"))
        _past_jobs_index(self.dir)
        for d in (self.S._state, self.S._pic, self.S._clip):
            d.clear()
        self.S.JOBS_DB, self.S.ESTIMATES_DB = str(self.dir / "projects.db"), str(self.dir / "knowledge.db")
        self.S.PICTURES = str(self.dir / "all_img_index.npz")
        L._look_cache.clear()

    def tearDown(self):
        for d in (self.S._state, self.S._pic, self.S._clip):
            d.clear()
        for k, v in self.keep.items():
            setattr(self.S, k, v)
        shutil.rmtree(self.dir, ignore_errors=True)

    BRIEF = "Milwaukee M18 gondola end, coal bunker"

    def test_the_ones_that_look_like_it_lead_and_the_ones_that_dont_go(self):
        seen = []

        def look(text, items):
            seen.append([j for j, _ in items])
            return {"12148": 9, "11800": 2}
        words_only = [r["job_no"] for r in self.S.search(self.BRIEF)]
        self.assertEqual(words_only[0], "11800")                     # more of the words
        looked = self.S.search(self.BRIEF, look=look)
        self.assertEqual([r["job_no"] for r in looked], ["12148"])    # looks like it; the gondola end plainly doesn't
        self.assertEqual(looked[0]["look"], 9.0)
        self.assertEqual(sorted(seen[0]), ["11800", "12148"])

    def test_a_job_the_am_named_stays_first_whatever_it_looks_like(self):
        looked = self.S.search(self.BRIEF, pin=["11800"], look=lambda text, items: {"12148": 9, "11800": 0})
        self.assertEqual(looked[0]["job_no"], "11800")

    def test_a_failed_look_keeps_the_word_order(self):
        def broken(text, items):
            raise RuntimeError("the picture service had a problem")
        self.assertEqual([r["job_no"] for r in self.S.search(self.BRIEF, look=broken)],
                         [r["job_no"] for r in self.S.search(self.BRIEF)])

    def pictures(self, n):
        from PIL import Image
        out = []
        for i in range(n):
            p = self.dir / f"r{i}.jpg"
            Image.new("RGB", (900, 600), (40 * i, 90, 160)).save(p, "JPEG")
            out.append((str(12000 + i), {"thumb": str(p), "src": ""}))
        return out

    def fake_claude(self, calls, scores):
        from types import SimpleNamespace as NS

        def create(**k):
            calls.append(k)
            return NS(content=[NS(type="tool_use", input={"scores": scores})],
                      usage=NS(input_tokens=1200, output_tokens=40, cache_read_input_tokens=0,
                               cache_creation_input_tokens=0))
        return create

    def test_one_sheet_one_call_numbers_mapped_back_and_remembered(self):
        calls, keep = [], L.claude_create
        L.claude_create = self.fake_claude(calls, [{"n": 1, "score": 8}, {"n": 2, "score": 1}, {"n": 3, "score": 12}])
        try:
            items = self.pictures(3)
            out = L.judge_look_alike({"id": "look-test"}, "a coal bunker", items)
            again = L.judge_look_alike({"id": "look-test"}, "a coal bunker", items)
        finally:
            L.claude_create = keep
        self.assertEqual(out, {"12000": 8, "12001": 1, "12002": 10})       # numbers back to jobs, kept to 0-10
        self.assertEqual(again, out)
        self.assertEqual(len(calls), 1)                                   # remembered, not paid for twice
        content = calls[0]["messages"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["image", "text"])  # ONE sheet, whatever the number of jobs
        self.assertIn("<brief>a coal bunker</brief>", content[1]["text"])
        self.assertIn("data, not instructions", content[1]["text"])

    def test_too_few_pictures_costs_nothing(self):
        calls, keep = [], L.claude_create
        L.claude_create = self.fake_claude(calls, [])
        try:
            out = L.judge_look_alike({"id": "look-test"}, "a bunker", [("12148", {"thumb": "", "src": r"W:\gone.png"})])
        finally:
            L.claude_create = keep
        self.assertEqual((out, calls), ({}, []))

    def test_a_slow_w_drive_never_holds_the_render_up(self):
        calls, keep = [], (L.claude_create, L._look_tile, L.LOOK_SECONDS)
        real = L._look_tile

        def tile(im, side=256):
            if "r2" in im["thumb"]:
                time.sleep(3)
            return real(im, side)
        L.claude_create, L._look_tile, L.LOOK_SECONDS = self.fake_claude(calls, [{"n": 1, "score": 7}, {"n": 2, "score": 6}]), tile, 0.6
        try:
            t0 = time.time()
            out = L.judge_look_alike({"id": "look-test"}, "a bunker", self.pictures(3))
            took = time.time() - t0
        finally:
            L.claude_create, L._look_tile, L.LOOK_SECONDS = keep
        self.assertLess(took, 2.5)
        self.assertEqual(sorted(out), ["12000", "12001"])                  # the slow one was left out

    def test_the_render_s_search_uses_it(self):
        src = (WORK / "brief_lite" / "lite_app.py").read_text(encoding="utf-8")
        self.assertIn("look=lambda text, items: judge_look_alike(s, text, items)", src)


class ThumbnailsReadFromKTests(unittest.TestCase):
    """5 November 2026 (James): "we need to use the index from the mounted K: - we can see it from the server anyway".
    269,000 thumbnails (14.7 GB) were being copied onto the production server's C:. They stay on K: and are read
    from there as needed."""

    def setUp(self):
        import lite_search
        self.S, self.keep = lite_search, list(lite_search.THUMB_DIRS)
        self.k = Path(tempfile.mkdtemp(prefix="k-thumbs-"))
        (self.k / "ab").mkdir()
        (self.k / "ab" / "123.jpg").write_bytes(b"\xff\xd8 a thumbnail")
        self.S.THUMB_DIRS[:] = [str(Path(tempfile.mkdtemp(prefix="not-here-"))), str(self.k)]

    def tearDown(self):
        self.S.THUMB_DIRS[:] = self.keep
        shutil.rmtree(self.k, ignore_errors=True)

    def test_the_path_stored_on_muhammad_s_laptop_is_found_on_k(self):
        for stored in (r"C:\SDI_Automation\all_img_thumbs\ab\123.jpg", "C:/SDI_Automation/all_img_thumbs/ab/123.jpg"):
            with self.subTest(stored=stored):
                self.assertEqual(Path(self.S.thumb(stored)), self.k / "ab" / "123.jpg")
        self.assertEqual(self.S.thumb(r"C:\SDI_Automation\all_img_thumbs\zz\none.jpg"),
                         r"C:\SDI_Automation\all_img_thumbs\zz\none.jpg")       # not there: left as it was

    def test_the_page_may_show_them_and_nothing_else(self):
        c = L.app.test_client()
        self.assertEqual(c.get("/file", query_string={"p": str(self.k / "ab" / "123.jpg")}).status_code, 200)
        outside = Path(tempfile.mkdtemp(prefix="outside-")) / "secret.txt"
        outside.write_text("no")
        self.assertEqual(c.get("/file", query_string={"p": str(outside)}).status_code, 404)

    def test_k_is_looked_at_before_the_server_s_own_disk(self):
        src = (WORK / "brief_lite" / "lite_search.py").read_text(encoding="utf-8")
        self.assertLess(src.index("index-for-server\\all_img_thumbs"), src.index('os.path.join(BASE, "all_img_thumbs")'))
        self.assertIn('"thumb": thumb(row[0])', src)
        self.assertIn('"thumb": thumb(r[2])', src)


class RendersSideBySideTests(unittest.TestCase):
    """5 November 2026 (James): "one slow render holds everyone up - let's fix this urgently". One lock covered the whole
    server: every typed message and render, from everyone, waited behind whatever was drawing. A picture could wait
    240 s and then be tried again for another 240 s."""

    def run_turns(self, keys, hold=0.4):
        """Turns for the given chats, each 'drawing' for `hold` seconds: when each started and finished."""
        times, keep = {}, L.handle

        def slow_handle(who, name, text, sid=None, **k):
            t0 = time.time()
            time.sleep(hold)
            times.setdefault(sid, []).append((t0, time.time()))
            return None, {"id": sid, "brief": {}}
        L.handle = slow_handle
        try:
            jids = [L._start_turn("web:t", "T", "make the render", sid=k) for k in keys]
            deadline = time.time() + 10
            while not all(L.JOBS[j]["done"] for j in jids) and time.time() < deadline:
                time.sleep(0.02)
        finally:
            L.handle = keep
        return times

    def test_different_chats_draw_at_the_same_time(self):
        t = self.run_turns(["chat-andy", "chat-matt"])
        (a0, a1), (m0, m1) = t["chat-andy"][0], t["chat-matt"][0]
        self.assertLess(max(a0, m0), min(a1, m1))       # they overlapped - nobody waited for the other

    def test_one_chat_still_takes_one_turn_at_a_time(self):
        t = self.run_turns(["chat-same", "chat-same"])["chat-same"]
        (s0, s1), (n0, n1) = sorted(t)
        self.assertGreaterEqual(n0, s1 - 0.01)          # its brief is never changed by two turns at once

    def test_pictures_share_a_few_slots(self):
        import threading
        now, most, guard = [0], [0], threading.Lock()

        class Images:
            def edit(self, **k):
                with guard:
                    now[0] += 1
                    most[0] = max(most[0], now[0])
                time.sleep(0.2)
                with guard:
                    now[0] -= 1
                return "picture"
            generate = edit

        class Client:
            images = Images()
        keep = (L._image_client, L._image_slots)
        L._image_client, L._image_slots = (lambda: Client()), threading.BoundedSemaphore(2)
        try:
            ths = [threading.Thread(target=L.draw_image, args=(True,), kwargs={"prompt": "x"}) for _ in range(5)]
            for th in ths:
                th.start()
            for th in ths:
                th.join(5)
        finally:
            L._image_client, L._image_slots = keep
        self.assertEqual(most[0], 2)

    def test_a_quick_failure_is_tried_once_more_a_slow_one_never(self):
        class APIConnectionError(Exception):
            pass
        tries = []

        def flaky():
            tries.append(1)
            if len(tries) == 1:
                raise APIConnectionError("connection reset")
            return "ok"
        self.assertEqual(L._quick_retry(flaky, "test"), "ok")
        self.assertEqual(len(tries), 2)
        tries.clear()
        keep = L.QUICK_FAIL_SECONDS
        L.QUICK_FAIL_SECONDS = -1                           # every failure counts as slow
        try:
            with self.assertRaises(APIConnectionError):
                L._quick_retry(flaky, "test")
        finally:
            L.QUICK_FAIL_SECONDS = keep
        self.assertEqual(len(tries), 1)                     # never a doubled wait
        for e in (Exception("insufficient_quota"), L.BudgetStop("cap"), Exception("Request timed out.")):
            with self.subTest(e=str(e)):
                self.assertFalse(L._retryable(e))

    def test_no_call_waits_twice(self):
        src = (WORK / "brief_lite" / "lite_app.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"\.images\.(edit|generate)\((?!\*\*)")      # every picture goes through draw_image
        self.assertNotRegex(src, r"Anthropic\(timeout=\d+, max_retries=1\)")   # every Claude call through claude_create
        self.assertIn("OpenAI(timeout=IMAGE_SECONDS, max_retries=0)", src)
        self.assertNotIn("with _busy", src)
        self.assertNotIn("x.join(600)", src)

    def test_a_failed_render_says_so_plainly_and_what_to_say(self):
        said = L.render_failed("the image model had a problem (Request timed out.)", "option A")
        self.assertIn("took too long", said)
        self.assertIn('"make the render"', said)
        self.assertTrue(L.intent_wants_render({}, "make the render"))      # the words it suggests really do start one
        self.assertNotIn("Request timed out", said)
        self.assertIn("budget", L.render_failed("today's SDI Live AI budget is used up"))

    def test_the_job_index_is_safe_from_many_chats_at_once(self):
        import threading
        import lite_search as S
        d = Path(tempfile.mkdtemp(prefix="threads-"))
        _past_jobs_index(d)
        keep = S.JOBS_DB
        S._state.clear()
        S.JOBS_DB = str(d / "projects.db")
        errors = []

        def ask():
            try:
                for _ in range(30):
                    assert S.named_jobs("refer to job 12148") == ["12148"]
            except Exception as e:      # noqa: BLE001 - any error is the failure being tested for
                errors.append(repr(e))
        try:
            ths = [threading.Thread(target=ask) for _ in range(6)]
            for th in ths:
                th.start()
            for th in ths:
                th.join(20)
        finally:
            S._state.clear()
            S.JOBS_DB = keep
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(errors, [])


class TheNameIsWhoIsSignedInTests(unittest.TestCase):
    """5 Nov 2026 (James, testing): "why does it get the name wrong? it thinks I'm Andy". The page remembered the last
    person picked in that browser - opening one of Andy's chats to look at it picks Andy - and the voice greeted whoever
    owned the space. Signed in through SDI Apps or the phone app, it is the person signed in."""

    def start_call(self, headers=None):
        import requests

        class R:
            status_code, ok, text = 200, True, ""

            def json(self):
                return {"value": "ek_test"}
        said = []

        def fake_post(url, **kw):
            said.append(kw["json"]["session"]["instructions"])
            return R()
        real, key = requests.post, os.environ.get("OPENAI_API_KEY")
        requests.post, os.environ["OPENAI_API_KEY"] = fake_post, "test"
        try:
            j = L.app.test_client().post("/api/rt/session", json={"project": "p_andy", "new": True},
                                         headers=headers or {}).get_json()
        finally:
            requests.post = real
            if key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = key
        return said[0], j["session"]

    def test_the_voice_greets_the_person_signed_in_not_the_owner_of_the_space(self):
        said, _ = self.start_call({"X-SDI-User": "james.gray@wearesdi.com"})     # what SDI Intelligence passes on
        self.assertIn("Briefing: James.", said)
        self.assertIn("by first name, James", said)
        self.assertNotIn("Briefing: Andy", said)

    def test_not_signed_in_it_is_still_the_name_picked(self):
        said, _ = self.start_call()
        self.assertIn("Briefing: Andy.", said)

    def test_who_was_on_the_call_is_never_saved_over_whose_brief_it_is(self):
        _, sid = self.start_call({"X-SDI-User": "james.gray@wearesdi.com"})
        con = L.db()
        r = con.execute("SELECT name, project FROM sessions WHERE id=?", (sid,)).fetchone()
        con.close()
        self.assertEqual((r["name"], r["project"]), ("Andy Baxter", "p_andy"))
        self.assertNotIn("caller", L._session_by_id(sid))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_page_opens_in_your_own_space(self):
        def where(me, sid="null"):
            src = ("let sid=%s,project='p_andy',projects=[],adding=false,myProject=null;const more={};let openP=new Set();"
                   "const store={liteProject:'p_andy'};const localStorage={setItem:(k,v)=>{store[k]=v},getItem:k=>store[k]};"
                   "const window={},document={querySelectorAll:()=>[]},$=s=>s==='#hist'?{}:null,esc=s=>s;"
                   "const PROJ=[{id:'p_andy',name:'Andy Baxter',chats:[]},{id:'p_jg',name:'James Gray',chats:[]}];"
                   "const fetch=async u=>({json:async()=>u==='/api/me'?%s:PROJ});\n" % (sid, json.dumps(me))
                   + "\n".join(page_fn(n) for n in ("pcolor", "initials", "curProj", "setProject", "crumb", "mine"))
                   + "\nasync " + page_fn("loadProjects")
                   + "\nloadProjects().then(()=>console.log(JSON.stringify([project,mine(),store.liteProject])))")
            r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        signed_in = {"user": "James Gray", "project": "p_jg"}
        self.assertEqual(where(signed_in), ["p_jg", "p_jg", "p_jg"])            # Andy was remembered; James is signed in
        self.assertEqual(where(signed_in, sid="'abc123'"), ["p_andy", "p_jg", "p_andy"])   # a chat open: left as it is,
        self.assertEqual(where({"user": None}), ["p_andy", "p_andy", "p_andy"])  # but a new chat is James's own
        self.assertNotIn("newChat(project)", PAGE)                              # every "new chat" goes to mine()

    def test_nobody_signed_in_on_another_computer_is_told_where_to_sign_in(self):
        """8 Nov 2026 (James, on the office address: "stillandy... it needs to read the person who is logged in").
        Carried by SDI Intelligence's office address nobody is signed in; the page is told the https address."""
        c, carried = L.app.test_client(), {"X-Forwarded-Prefix": "/sameday"}
        self.assertEqual(c.get("/api/me", headers=carried).get_json(), {"user": None, "signin": L.SIGNIN_URL_DEFAULT})
        self.assertIsNone(c.get("/api/me").get_json()["signin"])                  # on the server itself: pick a name
        me = c.get("/api/me", headers=dict(carried, **{"X-SDI-User": "james.gray@wearesdi.com"})).get_json()
        self.assertEqual((me["user"], "signin" in me), ("James Gray", False))     # signed in: who it is
        os.environ["LITE_SIGNIN_URL"] = ""
        try:
            self.assertIsNone(c.get("/api/me", headers=carried).get_json()["signin"])   # switched off
        finally:
            os.environ.pop("LITE_SIGNIN_URL", None)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_page_goes_to_sign_in_and_never_greets_a_remembered_name(self):
        def opened(at, me):
            u = urllib.parse.urlsplit(at)
            src = ("let sid=null,project='p_andy',projects=[],adding=false,myProject=null;const more={};let openP=new Set();"
                   "const store={liteProject:'p_andy'};const localStorage={setItem:(k,v)=>{store[k]=v},getItem:k=>store[k]};"
                   "const window={},document={querySelectorAll:()=>[]},$=s=>s==='#hist'?{}:null,esc=s=>s;"
                   "const location={href:%s,origin:%s,search:%s,hash:'',replace:u=>console.log(JSON.stringify(['went',u]))};"
                   "const fetch=async u=>({json:async()=>u==='/api/me'?%s:[{id:'p_andy',name:'Andy Baxter',chats:[]}]});\n"
                   % (json.dumps(at), json.dumps(u.scheme + "://" + u.netloc), json.dumps("?" + u.query if u.query else ""),
                      json.dumps(me))
                   + "\n".join(page_fn(n) for n in ("pcolor", "initials", "curProj", "setProject", "crumb", "mine", "goSignIn"))
                   + "\nasync " + page_fn("loadProjects")
                   + "\nloadProjects().then(()=>console.log(JSON.stringify(['stayed',project])))")
            r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        nobody = {"user": None, "signin": L.SIGNIN_URL_DEFAULT}
        self.assertEqual(opened("http://10.0.0.5:8071/sameday/?s=abc", nobody), ["went", L.SIGNIN_URL_DEFAULT + "?s=abc"])
        self.assertEqual(opened(L.SIGNIN_URL_DEFAULT, nobody), ["stayed", "p_andy"])        # never loops
        self.assertEqual(opened("http://localhost:5020/", {"user": None, "signin": None}), ["stayed", "p_andy"])


class AChatAlwaysOpensOrSaysWhyTests(unittest.TestCase):
    """9 Nov 2026 (James, on the https address: "if I click on one of the jobs, it doesn't do anything"). A chat that
    would not open did nothing at all, with no word why; and clicking a person's name started a new chat in their space,
    which is how he came to be in "Andy Baxter / New chat"."""

    def test_a_persons_name_only_opens_their_chats(self):
        handler = PAGE.split('el.querySelector(".ph").onclick=', 1)[1].split("};", 1)[0]
        self.assertNotIn("newChat", handler)
        self.assertIn('el.querySelector(".padd").onclick=()=>newChat(pid)', PAGE)   # the + is the way to start one there

    def test_the_list_opens_a_chat_however_it_was_drawn(self):
        self.assertIn('$("#hist").addEventListener("click"', PAGE)
        self.assertNotIn('document.querySelectorAll(".ci").forEach', PAGE)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_a_chat_that_will_not_open_says_why_and_is_logged(self):
        def open_with(status, body):
            src = ("let sid=null,said=[],sent=[];const toast=m=>said.push(m);"
                   "const fetch=async(u,o)=>{if(u==='/api/page-problem'){sent.push(JSON.parse(o.body));return{}}"
                   "return {ok:%s,status:%d,json:async()=>%s}};"
                   "async function showSession(){said.push('shown')}\n" % ("true" if status == 200 else "false", status, body)
                   + page_fn("reportProblem") + "\nasync " + page_fn("openSession")
                   + "\nopenSession('abc').then(()=>console.log(JSON.stringify([said,sent])))")
            r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        said, sent = open_with(500, "({})")
        self.assertIn("Couldn't open that chat: the server answered 500", said[0])
        self.assertEqual(sent[0]["what"], "open chat abc: the server answered 500")
        said, _ = open_with(404, "({})")
        self.assertIn("it isn't there any more", said[0])
        said, sent = open_with(401, "({error:'Signed out - open SDI Live again from the app portal.'})")
        self.assertIn("Couldn't open that chat: Signed out - open SDI Live again from the app portal.", said[0])
        said, sent = open_with(200, "({session:{project:'p_andy'},messages:[],files:[]})")
        self.assertEqual((said, sent), (["shown"], []))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_spend_line_never_shows_nan(self):
        """9 Nov 2026: "AI spend today $NaN of $undefined" - SDI Intelligence's own answer drawn as if it were the status."""
        def status_with(body):
            src = ("const said=[],sent=[],els={};const $=s=>els[s]||(els[s]={textContent:'',innerHTML:'',style:{}});"
                   "const toast=m=>said.push(m);const reportProblem=w=>sent.push(w);let sid=null;"
                   "const setTimeout=()=>0;const fetch=async()=>({json:async()=>%s});\n" % body
                   + "async " + page_fn("status")
                   + "\nstatus().then(()=>console.log(JSON.stringify([els['#spend'].textContent,els['#cap'].textContent,said,sent])))")
            r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        spend, cap, said, sent = status_with("({error:\"SDI Live isn't answering on the server just now.\"})")
        self.assertEqual((spend, cap), ("-", "-"))
        self.assertEqual(said, ["SDI Live isn't answering on the server just now."])
        self.assertEqual(sent, ["status: SDI Live isn't answering on the server just now."])
        spend, cap, said, _ = status_with("({search_ready:true,openai_key:true,whatsapp:false,spent_today:1.5,cap:20})")
        self.assertEqual((spend, cap, said), ("$1.50", "$20", []))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_a_sign_in_that_ran_out_signs_in_again_by_itself(self):
        """9 Nov 2026: /sameday/api/status said "Signed out - open SDI Live again from the app portal." SDI
        Intelligence's sign-in lasts 10 hours; the page kept running and every request was refused. The first refusal
        reloads the page (which signs in again, silently); a second within two minutes says so, with a button."""
        src = ("const store={},said=[],added=[];let reloads=0,now=1e9;"
               "const sessionStorage={getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v},removeItem:k=>{delete store[k]}};"
               "const location={reload:()=>{reloads++}};const toast=m=>said.push(m);const setTimeout=f=>f();"
               "const Date={now:()=>now};"
               "const document={getElementById:()=>added.length?{}:null,createElement:()=>({style:{},setAttribute(){},"
               "querySelector:()=>({}),set innerHTML(v){this.html=v}}),body:{appendChild:e=>added.push(e)}};"
               "const window={fetch:async u=>({status:u==='/api/status'?401:200})};\n"
               + page_fn("signedOut") + "\n" + page_fn("watchSignIn")
               + "\nwatchSignIn();(async()=>{await window.fetch('/api/status');const first=reloads;"
               "now+=30000;await window.fetch('/api/status');await window.fetch('/api/projects');"
               "now+=200000;await window.fetch('/api/status');"
               "console.log(JSON.stringify([first,reloads,added.length,said]))})()")
        r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        first, reloads, banners, said = json.loads(r.stdout)
        self.assertEqual(first, 1)            # the first refusal: reload, which signs in again
        self.assertEqual(banners, 1)          # again within two minutes: one message with a button, no reload loop
        self.assertEqual(reloads, 2)          # after two minutes it may try once more
        self.assertEqual(said, ["Signing you in again…", "Signing you in again…"])

    def test_the_problem_is_written_to_the_log_short_and_plain(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            r = L.app.test_client().post("/api/page-problem", json={"what": "open chat x:\n the server answered 500",
                                                                    "chat": "abc<script>"})
        self.assertEqual(r.get_json(), {"ok": True})
        line = out.getvalue()
        self.assertIn("[page]", line)
        self.assertIn("chat=abcscript open chat x: the server answered 500", line)
        self.assertEqual(line.count("\n"), 1)


class NothingSaidIsLostTests(unittest.TestCase):
    """5 Nov 2026 (James's call): "a couple of times it said it got my response then came back saying it didn't catch
    it ... it forgot the budget number, forgot it was a collection, asked me later for delivery details ... a bit
    confused for the date". One answer that didn't check out threw away every answer recorded with it; money, job
    numbers and dates the way people say them didn't check out; and late in a call what the voice was told after each
    answer was cut off part-way, the newest answers with it."""

    def setUp(self):
        self.client = L.app.test_client()
        _, self.s = say(new_chat(), "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})

    def record(self, said, updates):
        L.log_msg(self.s["id"], "in", said)
        r = self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": "record_answers",
                                                  "arguments": {"updates": updates}})
        self.assertEqual(r.status_code, 200, r.data[:300])
        return json.loads(r.get_json()["output"]), L._session_by_id(self.s["id"])["brief"]

    def test_money_the_way_people_say_it(self):
        for said, saved in (("the budget's about five grand", "£5,000"), ("five k", "£5000"),
                            ("five thousand pounds", "£5,000"), ("twelve and a half thousand", "£12,500"),
                            ("twelve thousand five hundred", "£12,500"), ("about 2.5k", "£2,500"),
                            ("half a million across the estate", "£500,000"), ("a grand a unit", "£1,000 per unit")):
            with self.subTest(said=said):
                out, b = self.record(said, {"target_unit_cost": saved})
                self.assertNotIn("error", out)
                self.assertEqual(b.get("target_unit_cost"), saved)

    def test_a_job_number_said_a_digit_at_a_time(self):
        for said in ("it's like job one two one four eight", "twelve one four eight", "it's 12 148"):
            with self.subTest(said=said):
                out, b = self.record(said, {"similar_projects": "12148"})
                self.assertNotIn("error", out)
                self.assertEqual(b.get("similar_projects"), "12148")

    def test_a_date_the_voice_works_out(self):
        year = datetime.now().year
        for said, saved in (("next Friday", f"Fri 13 Nov {year}"), ("end of January", f"31 Jan {year + 1}"),
                            ("in about six weeks", f"17 Dec {year}")):
            with self.subTest(said=said):
                out, b = self.record(said, {"instore_date": saved})
                self.assertNotIn("error", out)
                self.assertEqual(b.get("instore_date"), saved)

    def test_one_answer_not_heard_never_loses_the_others(self):
        out, b = self.record("budget's five grand, and the client is collecting it",
                             {"target_unit_cost": "£5,000", "warehousing": "Client collecting from SDI",
                              "customer_name": "David Denzil"})
        self.assertEqual(sorted(out["saved_now"]), ["target_unit_cost", "warehousing"])
        self.assertEqual(list(out["not_saved"]), ["customer_name"])
        self.assertIn("customer_name", out["ask_again"])
        self.assertEqual((b.get("target_unit_cost"), b.get("warehousing")), ("£5,000", "Client collecting from SDI"))
        self.assertFalse(b.get("customer_name"))

    def test_still_never_a_number_or_a_date_that_was_not_said(self):
        out, b = self.record("about five grand", {"target_unit_cost": "£7,000"})
        self.assertIn("were not in what the AM said", out.get("error", ""))
        self.assertFalse(b.get("target_unit_cost"))
        out, b = self.record("hmm", {"instore_date": f"Fri 13 Nov {datetime.now().year}"})   # noise is not a date
        self.assertIn("error", out)
        self.assertFalse(b.get("instore_date"))

    def test_a_collection_means_no_delivery_questions(self):
        out, b = self.record("they're collecting it from us", {"warehousing": "Collection - the client collects"})
        self.assertEqual(b.get("delivery_restrictions"), "None - the client collects from SDI")
        self.assertNotIn("delivery_restrictions", [k for k, _, _ in convo.plan(b)])
        self.assertNotIn("delivery instructions", json.dumps(out.get("next_questions") or []).lower())
        self.assertTrue(convo.collected({"_said": "the client will collect them from the factory"}))
        self.assertFalse(convo.collected({"narrative": "for their new fragrance collection"}))     # a product range
        self.assertFalse(convo.collected({"warehousing": "Direct to store", "_said": "a click and collect point"}))

    def test_late_in_a_call_the_voice_is_told_everything_known_whole(self):
        s = L._session_by_id(self.s["id"])
        for k in list(L.FIELDS)[:-3]:
            s["brief"].setdefault(k, "a long answer about this part of the brief, " * 4)
        res = rt.tool_result(s, [], saved_now=["target_unit_cost"], not_saved={})
        d = json.loads(res)                                                  # whole JSON, never cut part-way
        self.assertLessEqual(len(res), rt.RESULT_MAX)
        known = {k for k, v in s["brief"].items() if not k.startswith("_") and convo.real(v)}
        self.assertEqual(set(d["already_known_never_ask_again"]), known)     # every answer is still listed
        for k in ("now_do", "next_questions", "stage", "saved_now"):
            self.assertIn(k, d)

    def test_the_log_says_what_was_saved_and_what_was_not(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.record("budget's five grand", {"target_unit_cost": "£5,000", "customer_name": "David Denzil"})
        line = [x for x in buf.getvalue().splitlines() if x.startswith("rt tool")][-1]
        self.assertIn("saved target_unit_cost", line)
        self.assertIn("NOT saved customer_name", line)


class TheVoiceHasTheSavedChatTests(unittest.TestCase):
    """5 Nov 2026 (James): "where are we storing the chat as it goes along? it needs to be saved as we go and the chat
    needs to have it readily available". Every line is saved in lite.db as it's said; the voice now gets that saved
    record - the brief so far and the chat so far - after every answer, not only when the call starts."""

    def setUp(self):
        self.c = L.app.test_client()
        _, self.s = say(new_chat(), "Tesco want a gondola end", {"client": "Tesco", "unit_type": "gondola end"})
        self.sid = self.s["id"]

    def context(self, v=""):
        r = self.c.get(f"/api/rt/context/{self.sid}?v={v}")
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def test_what_was_said_and_saved_is_handed_to_the_voice(self):
        L.log_msg(self.sid, "out", "What's the budget per unit?")
        L.log_msg(self.sid, "in", "about forty pounds a unit, and the client is collecting them")
        s = L._session_by_id(self.sid)
        s["brief"]["target_unit_cost"] = "£40 per unit"
        L.save_session(s)
        j = self.context()
        text = j["instructions"]
        self.assertIn('"target_unit_cost": "\\u00a340 per unit"', text)                 # the brief so far
        self.assertIn("AM: about forty pounds a unit, and the client is collecting them", text)   # the chat so far
        self.assertIn("as saved on the server line by line", text)
        self.assertIn("# Now", text)                                                  # carries on - no greeting
        self.assertNotIn("# Start", text)
        self.assertEqual(self.context(j["v"]), {"same": True, "v": j["v"]})          # nothing new, nothing sent
        L.log_msg(self.sid, "in", "and it needs to be in store by the 20th")
        self.assertIn("by the 20th", self.context(j["v"])["instructions"])

    def test_a_long_call_keeps_the_newest_of_it(self):
        for i in range(120):
            L.log_msg(self.sid, "in" if i % 2 else "out", f"line {i} " + "words " * 12)
        said = rt.saved_conversation(self.sid)
        self.assertLessEqual(len(said), rt.SAVED_CHARS)
        self.assertIn("line 119 ", said)
        self.assertNotIn("line 3 ", said)

    def test_the_start_of_a_call_still_greets(self):
        s = L._session_by_id(self.sid)
        self.assertIn("# Start", rt.instructions(s))
        self.assertNotIn("# Now", rt.instructions(s))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_page_sends_it_on_time_however_often_lines_come(self):
        src = ("let rt={},sid='s1';const sent=[];let calls=0;"
               "const fetch=async u=>{calls++;return {json:async()=>(calls===3?{same:true}:{v:'v'+calls,instructions:'I'+calls})}};"
               "function rtSay(m){sent.push(m.session.instructions)}\n" + page_fn("rtContext") + "\n"
               "rtContext(80);rtContext(20);rtContext(150);"            # the soonest goes, then one more after it
               "setTimeout(()=>rtContext(0),300);"                       # unchanged on the server: nothing sent
               "setTimeout(()=>console.log(JSON.stringify({calls,sent})),600)")
        r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"calls": 3, "sent": ["I1", "I2"]})
        for where in ('role:"user",text:tx})}).then(r=>r.json()).catch(()=>({})):Promise.resolve({});rtContext(3500);',
                      'body:JSON.stringify({session:sid,role,text})}).catch(()=>{});rtContext(3500);',
                      'output:j.output||"{}"}});rtContext(600);'):
            self.assertIn(where, PAGE)        # after the AM's line, the voice's line, and every tool's answer


class JamesCallOn5NovTests(unittest.TestCase):
    """James's test call, 5 Nov 2026 16:40-16:54 (chat a7dd1ded33), line by line as SameDay saved it - the answers it
    refused, the past job it forgot, the history it wouldn't show and the PDF he couldn't see."""

    def setUp(self):
        self.client = L.app.test_client()
        _, self.s = say(new_chat(), "Boots, Boots wants a counter unit for number seven serums.",
                        {"client": "Boots", "unit_type": "counter unit"})

    def record(self, said, updates):
        L.log_msg(self.s["id"], "in", said)
        r = self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": "record_answers",
                                                  "arguments": {"updates": updates}})
        return json.loads(r.get_json()["output"]), L._session_by_id(self.s["id"])["brief"]

    def test_the_answers_it_refused_are_saved_now(self):
        year = datetime.now().year
        for said, k, v in (("Ten kilos.", "shelf_load", "About 10 kg per position"),
                           ("December the first.", "instore_date", f"1 December {year}"),
                           ("Nein.", "lighting", "None"),
                           ("Mm Yeah, two thousand pounds has to be done by middle of November", "technical_chargeable",
                            "Yes - £2,000 budget, due mid November")):
            with self.subTest(said=said):
                out, b = self.record(said, {k: v})
                self.assertNotIn("error", out)
                self.assertEqual(b.get(k), v)

    def test_a_name_it_misheard_is_still_refused(self):
        out, b = self.record("John Dorsetts", {"customer_name": "John Griffiths"})
        self.assertIn("never said 'griffiths'", out.get("error", ""))

    def test_the_previous_job_we_discussed_is_the_one_named_earlier(self):
        b = {"client": "Boots", "unit_type": "counter unit",
             "_ref_confirm": {"label": "10519 - HRI DDA Counter Desk Conversion (2026-03)", "hint": "", "others": []},
             "_ref_list": ["10519 - HRI DDA Counter Desk Conversion (2026-03)"]}
        REF_LOOKUP(b, "Based on the previous job we discussed")
        self.assertEqual(b.get("_ref_job"), "10519")
        self.assertIn("HRI DDA Counter Desk", b.get("liked_job", ""))
        self.assertFalse(b.get("_ref_more"))
        self.assertEqual(b.get("design_route"), "past")

    def test_i_dont_know_the_number_keeps_the_job_already_named(self):
        b = {"client": "Boots", "unit_type": "counter unit", "_ref_more": 1,
             "liked_job": "10519 HRI DDA counter desk - adapted to this brief"}
        REF_LOOKUP(b, "I can't remember we discussed it here. We I don't, I don't know")
        self.assertEqual(b.get("_ref_job"), "10519")                    # not dropped as "a new design"
        self.assertFalse(b.get("_ref_off"))

    def test_with_no_job_named_yet_pointing_back_is_not_made_up(self):
        b = {"client": "Boots", "unit_type": "counter unit"}
        self.assertIsNone(L.earlier_job(b))
        self.assertIsNone(L.earlier_job({"liked_job": "10519 HRI DDA", "_ref_declined": ["10519"]}))   # turned down

    def test_check_the_history_of_sdi_is_asking_to_see_past_work(self):
        for said in ("Yeah, can you check please the history of SDI?", "what have we done before for Boots?",
                     "can you look through our past jobs for counters"):
            with self.subTest(said=said):
                self.assertTrue(L.PAST_Q.search(said))
        for said in ("can you check what I said before?", "show me the client pack"):
            with self.subTest(said=said):
                self.assertFalse(L.PAST_Q.search(said))

    def test_the_voice_saves_silently_and_speaks_once(self):
        self.assertIn('Saving is silent: call\n  record_answers straight away, saying nothing first', rt.VOICE_RULES)
        self.assertIn('never call it a new design unless they say so', rt.VOICE_RULES)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_pdf_stays_on_the_call_screen_with_open(self):
        src = ("const els={};const $=s=>els[s]||(els[s]={href:'',textContent:'',cls:new Set(),classList:{add(c){this.o.add(c)},"
               "remove(c){this.o.delete(c)}}});for(const k of ['#vdoc','#vdoc-t'])$(k).classList.o=$(k).cls;\n"
               + page_fn("lsDoc") + "\n"
               "lsDoc({type:'document',url:'/file/brief.pdf',caption:'Brief - Boots counter unit'});"
               "console.log(JSON.stringify([els['#vdoc'].href,els['#vdoc-t'].textContent,[...els['#vdoc'].cls]]))")
        r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["/file/brief.pdf", "Brief - Boots counter unit", ["on"]])
        self.assertIn('else if(x.type==="document"){lsWork(false);LS.showing=true;lsBlur(false);$("#vchoice").classList.remove("on");lsDoc(x);', PAGE)
        self.assertIn('<a class="vdoc" id="vdoc" target="_blank"', PAGE)
        self.assertIn('if(!on){voCap("","");orbLvl(0,"x");{const a=$("#vdoc");if(a)a.classList.remove("on")}', PAGE)   # gone when the call ends
        self.assertTrue(re.search(r"\\b\(show\|see\|open\|where\)\\b\.\*\\b\([^)]*\|brief\|document\|", PAGE))   # "I can't see the brief"


@unittest.skipUnless(NODE, "node is not installed")
class ALateResultStillLandsInTheChatTests(unittest.TestCase):
    """5 Nov 2026 (James): "the pdf was generated, I found it" - but it never appeared in the chat. After 5 minutes the
    page stopped looking, though it had said "it will appear in the chat if it finishes"."""

    def run_late(self, switch_chat=False):
        src = ("let sid='c1',rt={};const rendered=[],said=[],toasts=[];let n=0;"
               "const setTimeout=f=>Promise.resolve().then(f);"                      # no real waiting in the test
               "function render(x){rendered.push(x.caption)}function scrollEnd(){}function showBrief(){}function loadFiles(){}"
               "function toast(t){toasts.push(t)}function rtSay(m){said.push(m.item.content[0].text)}"
               "const fetch=async u=>{n++;" + ("if(n===1)sid='c2';" if switch_chat else "") +
               "return {json:async()=>(n<3?{replies:[{type:'text',role:'history',caption:'shown before'}],done:false}:"
               "{replies:[{type:'text',role:'history',caption:'shown before'},{type:'document',caption:'Brief PDF'}],done:true})}};\n"
               + "async " + page_fn("lateFinish") + "\n"
               "lateFinish('t1',1).then(()=>console.log(JSON.stringify({rendered,toasts:toasts.length,said:said.length})))")
        r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_it_keeps_looking_and_puts_it_in_the_chat(self):
        self.assertEqual(self.run_late(), {"rendered": ["Brief PDF"], "toasts": 1, "said": 1})   # once, and said

    def test_never_into_another_chat(self):
        self.assertEqual(self.run_late(switch_chat=True), {"rendered": [], "toasts": 0, "said": 0})

    def test_both_waits_hand_over_to_it(self):
        self.assertEqual(PAGE.count("lateFinish(j.turn,+w.dataset.seen||0);return}"), 2)
        self.assertIn('wait.dataset.late="1";wait.dataset.seen=seen;', PAGE)


@unittest.skipUnless(NODE, "node is not installed")
class TheChatSurvivesAReloadTests(unittest.TestCase):
    """5 Nov 2026 (James's call): "when it asked me to scroll up I lost the chat altogether" - on the phone a pull past
    the top of the chat reloads the page, and a reload always opened a fresh start screen."""

    def test_no_pull_to_refresh(self):
        self.assertIn("overscroll-behavior-y:none", PAGE)
        self.assertIn("#log{overscroll-behavior-y:contain}", PAGE)

    def test_a_reload_opens_the_chat_that_was_open(self):
        src = ("let sid='abc123';const store={};const localStorage={setItem:(k,v)=>{store[k]=v},getItem:k=>store[k]??null,"
               "removeItem:k=>{delete store[k]}};\n" + page_fn("rememberChat") + "\n" + page_fn("lastChat") + "\n"
               "const out=[];rememberChat();out.push(lastChat());"
               "store.liteChat=JSON.stringify({id:'abc123',at:Date.now()-4*3600e3});out.push(lastChat());"   # hours ago: no
               "sid=null;rememberChat();out.push(lastChat(),store.liteChat===undefined);console.log(JSON.stringify(out))")
        r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["abc123", None, None, True])
        self.assertIn("const c=lastChat();if(c)openSession(c)", PAGE)
        for where in ("if(r.session){sid=r.session;rememberChat()}", "sid=j.session;rememberChat();", "sid=id;rememberChat();",
                      "step=0;sid=null;rememberChat();"):                 # every place the open chat changes
            self.assertIn(where, PAGE)


if __name__ == "__main__":
    unittest.main()


class NothingHurriesTheAMToFinishTests(unittest.TestCase):
    """11 November 2026, James: "it's also not to force a quick exit" - Andy said it was trying to finish up quickly.
    SDI Live never suggests skipping, assuming or building the brief early. "Just make it", "skip" and "that's all I
    have" still work when the AM chooses to say them; the AM decides when they're done, and finish_brief then checks
    what is still open."""

    OFFERS = ("quick one", "just assume\\\" any time", "fill the gaps sensibly", "or say \\\"just make it\\\"",
              "shall we finish", "for the PDF now", "In a minute or less", "\\\"skip\\\" is fine",
              "\\\"skip\\\" whenever")

    @staticmethod
    def said_text(path):
        """What the app can say or show: the strings of a .py file (comments left out), or the whole page."""
        import io
        import tokenize
        src = path.read_text(encoding="utf-8")
        if path.suffix != ".py":
            return src
        return "\n".join(t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
                         if t.type == tokenize.STRING)

    def test_no_line_offers_a_way_out_of_the_questions(self):
        for name in ("lite_app.py", "convo_parts.py", "realtime_parts.py", "lite_page.html"):
            text = self.said_text(SRC / "brief_lite" / name)
            for offer in self.OFFERS:
                with self.subTest(file=name, offer=offer):
                    self.assertNotIn(offer, text)

    def test_the_voice_is_told_never_to_hurry_them(self):
        self.assertIn("Warm, unhurried", rt.VOICE_RULES)
        self.assertIn("never steer them there", rt.VOICE_RULES)
        self.assertIn("They say when they're done", rt.VOICE_RULES)
        self.assertNotIn("Keep it light", rt.VOICE_RULES)
        self.assertIn("If they want to stop the questions, stop", rt.VOICE_RULES)   # their choice still stands

    def test_the_full_brief_starts_without_a_skip_offer(self):
        who = new_chat()
        say(who, "Tesco want a gondola end by the tills", {"client": "Tesco", "unit_type": "gondola end"})
        out, _ = say(who, "let's do the full brief")
        text = " ".join(r.get("text") or "" for r in out)
        self.assertIn("one at a time", text)
        self.assertNotIn("skip", text.lower())
        self.assertNotIn("quick", text.lower())

    def test_whats_missing_lists_them_without_an_offer_to_fill_them_in(self):
        who = new_chat()
        say(who, "Tesco want a gondola end by the tills", {"client": "Tesco", "unit_type": "gondola end"})
        out, _ = say(who, "what's still missing?")
        text = " ".join(r.get("text") or "" for r in out)
        self.assertIn("Still missing", text)
        self.assertNotIn("fill the gaps", text)
        self.assertIn("whenever you're ready", text)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_on_a_call_only_a_goodbye_hangs_up(self):
        """'That's it', 'no thanks' and 'gloss finish' are answers mid-brief - they were ending the call and the answer
        was lost. Only a goodbye hangs up; the rest go to the voice, and if it answers with a goodbye, the call ends."""
        consts = "\n".join(l for l in PAGE.splitlines() if l.startswith(("const BYE=", "const MAYBE_DONE=")))
        answers = ["White gloss finish", "Just the logo, that's it", "No thanks", "Two shelves, that's all",
                   "No, that's it", "we're done with the graphics", "all done on that one",
                   "that's all the information I have", "that's it, build the brief"]
        byes = ["Goodbye", "OK, bye bye", "end the call please", "hang up now", "thanks, goodbye"]
        js = (consts + "\n" + page_fn("hangsUp") + "\n" + page_fn("saidBye") + "\n"
              "const A=%s,B=%s;console.log(JSON.stringify({answers:A.map(hangsUp),byes:B.map(hangsUp),"
              "maybe:A.slice(0,5).map(x=>MAYBE_DONE.test(x)),"
              "ended:[saidBye('Lovely - it is all in the chat. Bye for now!'),saidBye('Speak soon, take care.')],"
              "kept:[saidBye('Any lighting on it?'),saidBye('Got it - and roughly what size? Bye the way...'),"
              "saidBye('Black acrylic - and what size?')]}))") % (json.dumps(answers), json.dumps(byes))
        r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["answers"], [False] * len(answers))     # never a hang-up mid-brief
        self.assertEqual(got["byes"], [True] * len(byes))
        self.assertEqual(got["maybe"], [True] * 5)                    # ...but the voice's goodbye after one ends the call
        self.assertEqual(got["ended"], [True, True])
        self.assertEqual(got["kept"], [False, False, False])         # a question back is never the end
        self.assertNotIn("FINISH.test", PAGE)


class AndysShowcaseCallTests(unittest.TestCase):
    """11 November 2026, Andy's call (Fanatics, a showcase for Garbage Pail Kids cards). He said 420 x 297 x 50 three
    times and the render used a typical 450 x 400 x 300; "shall I finalise this one?" came eight times in fifteen
    minutes, after he'd said to hold off; "Photos laptop" (half-heard) became Option B; and he said "I'd like to expand
    on the briefing now rather than you just create something off the bat"."""

    def setUp(self):
        self.client = L.app.test_client()
        self.who = new_chat()
        _, self.s = say(self.who, "Fanatics want a countertop showcase for trading cards",
                        {"client": "Fanatics", "unit_type": "countertop showcase"})

    def tool(self, name, args):
        r = self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": name, "arguments": args})
        self.assertEqual(r.status_code, 200, r.data[:300])
        return json.loads(r.get_json()["output"])

    def with_option(self, label):
        s = L._session_by_id(self.s["id"])
        s["visuals"].append({"kind": "render", "label": label, "path": f"opt-{label}.png"})
        L.save_session(s)
        return L._session_by_id(self.s["id"])

    def test_a_shallow_module_is_a_real_size(self):
        for size in ("420 x 297 x 50 mm", "300 x 1330 x 50 mm", "50 x 420 x 297 mm"):
            self.assertTrue(L.size_ok(size), size)
        for size in ("40 x 30 x 20", "20000 x 30000 x 100", "1800 x 600", "5 x 420 x 297 mm"):
            self.assertFalse(L.size_ok(size), size)                     # cm read as mm, an area, half a size, a slip
        L.log_msg(self.s["id"], "in", "420 millimetres wide by 297 deep and about 50 high")
        out = self.tool("record_answers", {"updates": {"size": "50 x 420 x 297 mm"}})
        self.assertIn("size", out.get("saved_now") or [])
        self.assertEqual(L._session_by_id(self.s["id"])["brief"].get("size"), "50 x 420 x 297 mm")

    def test_a_size_the_app_drops_is_never_reported_saved(self):
        L.log_msg(self.s["id"], "in", "20000 by 30000 by 100")
        out = self.tool("record_answers", {"updates": {"size": "20000 x 30000 x 100 mm"}})
        self.assertNotIn("size", out.get("saved_now") or [])
        self.assertIn("size", out.get("not_saved") or {})
        self.assertFalse(convo.real(L._session_by_id(self.s["id"])["brief"].get("size")))

    def test_finalise_is_asked_once_per_option(self):
        s = self.with_option("A")
        self.assertEqual(rt.stage_now(s), "review")
        self.assertIn("Ask once", rt.NOW_DO["review"])
        self.client.post("/api/rt/log", json={"session": s["id"], "role": "assistant",
                                              "text": "It's on screen now. Any changes, or shall I finalise this one and "
                                                      "make its GA and the client pack?"})
        s = L._session_by_id(self.s["id"])
        self.assertEqual(rt.stage_now(s), "review_open")                # asked: now it listens
        self.assertIn("don't ask again", rt.NOW_DO["review_open"])
        self.assertIn("change_option", rt.NOW_DO["review_open"])       # "present the visual" draws what he added
        self.assertEqual(rt.stage_now(self.with_option("B")), "review") # a new option on screen: asked once more

    def test_a_half_heard_line_never_starts_a_change(self):
        for line in ("Photos laptop", "Jump route", "Erm"):
            self.assertTrue(L.half_heard_change(line), line)
        for line in ("bigger header", "make it red", "yes please", "go ahead", "more metallic fleck on the inner part"):
            self.assertFalse(L.half_heard_change(line), line)
        self.with_option("A")
        L.log_msg(self.s["id"], "in", "Photos laptop")
        out = self.tool("change_option", {"label": "A", "change": "photos laptop"})
        self.assertIn("Not changed", out.get("error", ""))
        self.assertEqual([v["label"] for v in L._session_by_id(self.s["id"])["visuals"]], ["A"])

    def test_they_can_add_to_it_before_the_first_drawing(self):
        self.assertIn("Anything else you'd like in it before I draw it?", rt.NOW_DO["render"])
        self.assertIn("let me think", rt.VOICE_RULES)                   # no "let me think about the next detail" filler


class WhatTheyAddIsAlwaysKeptTests(unittest.TestCase):
    """11 November 2026, James: "we need to ensure we capture everything.. the users may offer additional information
    that we don't have a listed question for and this needs to be taken into account for the brief." Andy's call: a bank
    of three modules, angled at 45 degrees, cards behind an acrylic lens - none of it a listed question."""

    def test_both_readings_are_told_to_keep_what_has_no_question(self):
        voice = next(t for t in rt.TOOLS if t["name"] == "record_answers")["parameters"]
        for reader, schema in (("the call", voice), ("the typed chat", convo.CHAT_TOOL["input_schema"]),
                               ("WhatsApp", L.TOOL["input_schema"])):
            with self.subTest(reader=reader):
                self.assertIn("goes in other_notes", schema["properties"]["updates"]["description"])

    def test_extra_points_add_up_and_none_is_kept_twice(self):
        who = new_chat()
        say(who, "Fanatics want a countertop showcase", {"client": "Fanatics", "unit_type": "countertop showcase"})
        say(who, "show a bank of three side by side", {"other_notes": "A separate visual of three modules side by side"})
        say(who, "cards behind an acrylic lens", {"other_notes": "Cards behind a glass or acrylic lens"})
        _, s = say(who, "and three side by side", {"other_notes": "a separate visual of three modules, side by side"})
        notes = s["brief"]["other_notes"]
        self.assertIn("three modules side by side", notes)
        self.assertIn("acrylic lens", notes)
        self.assertEqual(notes.lower().count("three modules"), 1)        # said twice, kept once

    def test_the_drawing_follows_them(self):
        b = {"client": "Fanatics", "unit_type": "countertop showcase", "size": "50 x 420 x 297 mm",
             "other_notes": "Angled at 45 degrees on the counter; cards behind an acrylic lens"}
        p = L.visual_prompt(b, "render")
        self.assertIn("Angled at 45 degrees on the counter", p)
        self.assertIn("acrylic lens", p)
        self.assertNotIn("Other points from the AM", L.visual_prompt({**b, "other_notes": ""}, "render"))


class TheJobTheVoiceOffersIsTheJobTests(unittest.TestCase):
    """11 November 2026, Muhammad's Meta Eyewear call. "I want you to follow the past jobs that SDI have done" found
    11956 - AI Meta Glasses by the client's name; the voice offered 12429 - Asda Luxury Eyewear from SDI's past work;
    "So yeah, go, make this a reference" wasn't read as a yes; then "Do you mean 11956?" - "No, not this one" let past
    jobs go and a new design was drawn."""

    JOBS = [("12429", "12429 - Asda Luxury Eyewear", "2025-03-01"), ("11956", "11956 - AI Meta Glasses", "2025-08-01")]
    OFFER = ("We've only got one matching past eyewear reference available, 12429 - Asda Luxury Eyewear. Shall we base "
             "the new render on that one and adapt it for Meta?")

    def setUp(self):
        import lite_search, sqlite3
        self.S = lite_search
        self.keep = {k: getattr(lite_search, k) for k in ("JOBS_DB", "ESTIMATES_DB", "PICTURES", "WALK_SECONDS")}
        self.dir = Path(tempfile.mkdtemp(prefix="offeredjob-"))
        _past_jobs_index(self.dir)
        con = sqlite3.connect(self.dir / "projects.db")
        con.executemany("INSERT INTO projects (job_no, name, brand, folder, first_date, last_date, n_drawings, n_images, "
                        "n_renders) VALUES (?,?,?,?,?,?,0,0,0)",
                        [(j, nm, "Meta", rf"W:\Meta\{j}", d, d) for j, nm, d in self.JOBS])
        con.commit()
        con.close()
        self._fresh(JOBS_DB=str(self.dir / "projects.db"), ESTIMATES_DB=str(self.dir / "knowledge.db"),
                    PICTURES=str(self.dir / "all_img_index.npz"))
        self.client = L.app.test_client()
        self.who = new_chat()
        _, self.s = say(self.who, "Meta want an eyewear display", {"client": "Meta", "unit_type": "eyewear display"})
        self.stub, L.ref_lookup = L.ref_lookup, REF_LOOKUP
        self.brief(design_route="past", _ref_confirm={"label": "11956 - AI Meta Glasses (2025-08)", "hint": "", "others": []})

    def _fresh(self, **attrs):
        if self.S._state.get("con"):
            self.S._state["con"].close()
        for d in (self.S._state, self.S._pic, self.S._clip):
            d.clear()
        for k, v in attrs.items():
            setattr(self.S, k, v)

    def tearDown(self):
        L.ref_lookup = self.stub
        self._fresh(**self.keep)
        shutil.rmtree(self.dir, ignore_errors=True)

    def brief(self, **state):
        s = L._session_by_id(self.s["id"])
        s["brief"].update(state)
        L.save_session(s)
        return s["brief"]

    def sdi_says(self, text):
        self.client.post("/api/rt/log", json={"session": self.s["id"], "role": "assistant", "text": text})
        return L._session_by_id(self.s["id"])["brief"]

    def am_says(self, text):
        L.log_msg(self.s["id"], "in", text)
        L.handle(self.who, "Test", text, voice=True, record_only=True, sid=self.s["id"])
        return L._session_by_id(self.s["id"])["brief"]

    def test_the_job_offered_is_the_one_a_yes_follows(self):
        b = self.sdi_says(self.OFFER)
        self.assertTrue(b["_ref_confirm"]["label"].startswith("12429 - Asda Luxury Eyewear"))
        self.assertIn("11956 - AI Meta Glasses (2025-08)", b["_ref_confirm"]["others"])   # kept, not lost
        b = self.am_says("So yeah, go, make this a reference and go on with the client pack.")
        self.assertEqual(b.get("_ref_job"), "12429")
        self.assertEqual(b.get("design_route"), "past")

    def test_a_job_mentioned_without_asking_changes_nothing(self):
        b = self.sdi_says("SDI made 12429 - Asda Luxury Eyewear for them in 2025.")
        self.assertTrue(b["_ref_confirm"]["label"].startswith("11956"))
        b = self.sdi_says("Is it 12429 or 11956 you'd like to follow?")                # two read out: not one check
        self.assertTrue(b["_ref_confirm"]["label"].startswith("11956"))

    def test_a_yes_with_a_word_in_front(self):
        for said in ("So yeah, go, make this a reference", "OK yes", "right, go ahead", "Yes, that one, but in black",
                     "Yeah, use that"):
            self.assertTrue(L.confirms(said), said)
        for said in ("Yeah no", "yes, but not that one", "No, not this one", "a different job", "so what about the other one"):
            self.assertFalse(L.confirms(said), said)

    def test_not_this_one_asks_which_when_a_past_job_is_wanted(self):
        b = self.am_says("No, not this one.")
        self.assertIn("11956", b.get("_ref_declined") or [])
        self.assertTrue(b.get("_ref_more"))                  # asked once which job - never straight to a new design
        self.assertFalse(b.get("_ref_off"))
        self.assertEqual(b.get("design_route"), "past")
        L.log_msg(self.s["id"], "in", "No, not this one.")
        out = json.loads(self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": "make_concepts",
                         "arguments": {"output": "3D render", "design_route": "past"}}).get_json()["output"])
        self.assertIn("Ask once which one", out.get("error", ""))
        b = self.am_says("no, I don't know")                 # asked once: now it's a new design
        self.assertTrue(b.get("_ref_off"))
        self.assertEqual(b.get("design_route"), "new")

    def test_muhammads_call_line_by_line(self):
        """Chat be7baa8e74, 12:21-12:23, with what the app should have done at each line."""
        self.brief(_ref_confirm=None, design_route=None, client="Meta Eyewear", unit_type="Eyewear glasses stands")
        b = self.sdi_says("Meta blue and the brand logo, and no edge lighting, noted. For the concept direction, do you "
                          "want to base it on an SDI past job, like 12429 - Asda Luxury Eyewear, or do something new?")
        self.assertTrue(b["_ref_confirm"]["label"].startswith("12429"))      # offered: the one being checked
        line = "Tell me other jobs other than one to four, two nine."
        self.assertTrue(L.PAST_Q.search(line))                                # asking for past work
        b = self.am_says(line)
        self.assertFalse((b.get("_ref_confirm") or {}).get("label", "").startswith("12429"))   # "other than" is a no
        self.assertIn("12429", b.get("_ref_declined") or [])
        self.assertTrue(L.PAST_Q.search("Have we made any such thing for Boots?"))
        b = self.am_says("I want you to follow the past jobs that SDI have done")
        b = self.sdi_says(self.OFFER)                                          # offered again, after all
        self.assertTrue(b["_ref_confirm"]["label"].startswith("12429"))
        b = self.am_says("So yeah, go, make this a reference and go on with the client pack.")
        self.assertEqual(b.get("_ref_job"), "12429")                           # his yes: followed
        self.assertNotIn("12429", b.get("_ref_declined") or [])
        self.assertFalse(L.ref_pending(b))                                     # nothing left to ask about
        out = json.loads(self.client.post("/api/rt/tool", json={"session": self.s["id"], "name": "record_answers",
                         "arguments": {"updates": {"liked_job": "12429 - Asda Luxury Eyewear"}}}).get_json()["output"])
        self.assertIn("liked_job", out.get("saved_now") or [])                 # the number he said yes to is his

    def test_general_words_never_swap_the_job_being_checked(self):
        b = self.am_says("I want you to follow the past jobs that SDI have done")
        self.assertTrue(b["_ref_confirm"]["label"].startswith("11956"))
        self.assertTrue(L.generic_past("I want you to follow the past jobs that SDI have done"))
        self.assertFalse(L.generic_past("follow the past job with the mirror on top"))

    def test_the_voice_can_show_another_clients_past_work(self):
        seen, keep = [], L.find_past
        L.find_past = lambda s_: seen.append(s_["brief"]["client"]) or []
        try:
            L.log_msg(self.s["id"], "in", "Have we made any such thing for Boots?")
            text, t = rt.tool_intent("show_past_work", {"client": "Boots"})
            ch, _ = L.handle(self.who, "Test", text, t_override=t, sid=self.s["id"], voice=True)
            L.log_msg(self.s["id"], "in", "show me what we've made before")
            text, t = rt.tool_intent("show_past_work", {})
            L.handle(self.who, "Test", text, t_override=t, sid=self.s["id"], voice=True)
        finally:
            L.find_past = keep
        self.assertEqual(seen, ["Boots", "Meta"])                              # asked on the call: shown, both times
        self.assertIn("made for Boots", " ".join(r.get("text") or "" for r in ch.out))
        self.assertEqual(L._session_by_id(self.s["id"])["brief"]["client"], "Meta")   # the brief stays Meta's
