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

    def test_something_new_saved_as_the_liked_job_is_not_looked_up(self):
        self.brief(liked_job="something new, not the old one")
        keep = L.ref_lookup
        looked = []
        L.ref_lookup = lambda b, text: looked.append(text)
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
        self.assertIn("budget", L.render_failed("today's SDI Same Day Intelligence AI budget is used up"))

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


if __name__ == "__main__":
    unittest.main()
