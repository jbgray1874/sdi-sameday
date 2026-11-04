"""Brief Lite - live voice, the way ChatGPT's voice mode works (Andy Baxter, 6 Oct 2026).

The browser talks straight to OpenAI's Realtime model over WebRTC: it hears the AM, answers in well under a second,
and stops the moment the AM talks over it. This file gives that model its brief and its tools:

  record_answers   - writes what the AM said into the brief (no extra AI call), returns the next questions
  show_past_work   - puts SDI's closest past jobs and quotes on screen
  set_pack         - the pack the AM named (asked once; not answered = both, 4 Nov 2026)
  focus            - the AM chooses the order: the internal-brief questions now, or back to the render
  make_concepts    - makes the 3D options (and GA later) - runs in the background, the page shows them
  choose_option    - the designer's pick -> GA of that option + client sheet
  change_option    - "B but white header"
  more_options     - C, D, E...
  finish_brief     - the full PDF + the "still missing" list

Everything a tool does goes through lite_app.handle() with the intent already decided, so voice, text and WhatsApp
always build the same brief. Cost: gpt-realtime (set in .env, 20 Oct 2026; was gpt-realtime-mini), about 5-8p a minute of talking, logged per response.
"""
import json, os, re
from datetime import datetime

G = {}


def bind(ns):
    G.update(ns)
    globals().update({k: v for k, v in ns.items() if not k.startswith("__") and k not in globals()})


RT_MODEL = os.environ.get("LITE_RT_MODEL", "gpt-realtime-2")
RT_VOICE = os.environ.get("LITE_RT_VOICE", "cedar")
# USD per million tokens (gpt-realtime-mini): audio in 10, audio out 20, text in 0.6, text out 2.4
RT_PRICE = {"gpt-realtime-mini": (10.0, 20.0, 0.6, 2.4), "gpt-realtime": (32.0, 64.0, 4.0, 16.0)}
RT_CACHED = {"gpt-realtime-mini": 0.30, "gpt-realtime": 0.40}   # USD per million cached input tokens (audio or text)
# 4 Nov 2026: gpt-realtime-2 had no price here, so every call was counted at the mini's price - about a third of the
# real cost, and the daily cap let three times its spend through. A model with no price now counts at the dearest one
# known (over-counting stops a call early; under-counting overspends). Its real price, when known, goes in .env as
# LITE_RT_PRICE="audio in, audio out, text in, text out, cached" (USD per million tokens) - e.g. "32,64,4,16,0.4".
_DEAREST = max(RT_PRICE, key=lambda m: RT_PRICE[m][0])
RT_PRICE.setdefault("gpt-realtime-2", RT_PRICE[_DEAREST])
RT_CACHED.setdefault("gpt-realtime-2", RT_CACHED[_DEAREST])
try:
    _p = [float(x) for x in os.environ.get("LITE_RT_PRICE", "").split(",") if x.strip()]
    if len(_p) == 5:
        _m = os.environ.get("LITE_RT_BIG_MODEL", "gpt-realtime-2")
        RT_PRICE[_m], RT_CACHED[_m] = tuple(_p[:4]), _p[4]
except ValueError:
    pass


def price_of(model):
    """(audio in, audio out, text in, text out), cached - for any model, never the cheapest by default."""
    return RT_PRICE.get(model, RT_PRICE[_DEAREST]), RT_CACHED.get(model, RT_CACHED[_DEAREST])
# 21 Oct 2026: the big voice model only for the people who brief clients (and demos); our own testing on the small one
RT_BIG = os.environ.get("LITE_RT_BIG_MODEL", "gpt-realtime-2")   # 4 Nov 2026: GPT-5-class reasoning, better at following tool results
RT_SMALL = os.environ.get("LITE_RT_SMALL_MODEL", "gpt-realtime-mini")
RT_BIG_FOR = [x.strip().lower() for x in os.environ.get("LITE_RT_BIG_FOR", "Andy Baxter,Nick").split(",") if x.strip()]
SESSION_MODEL = {}


def model_for(project_name, demo=False):
    return RT_BIG   # 29 Oct 2026: everyone gets Andy's model (the mini one mishears and talks stiffly)

SLOW = {"make_concepts", "choose_option", "change_option", "more_options", "finish_brief", "show_past_work"}

# 27 Oct 2026: what the voice model must do next, from where the brief is (convo_parts.stage) - sent with every tool result
NOW_DO = {   # 4 Nov 2026: tightened with VOICE_RULES - each says only what this stage adds
    "pack": "Ask once which pack: the client pack (render, its GA, a one-page client sheet), the SDI internal brief pack, "
            "or both. Their answer -> set_pack. If they carry on about the job instead, follow them: it's both.",
    "render_q": "Only what the picture can't be drawn without, one short question at a time: what it is, rough size "
                "(H x W x D - 'you choose' is fine), what it holds, colours and graphics. Not materials, lighting, fixing "
                "or placement now - record them if mentioned; otherwise they're assumed and changed on the picture.",
    "route": "Ask once: a past SDI job or file to follow (a number, a name, 'the latest one'), or something new? A named "
             "job -> liked_job, then make_concepts with design_route past; new -> new; a bit of both -> mix.",
    "confirm": "Say the clash in check_with_am in one sentence, suggest what's usual, and ask: keep it as they said, or "
               "change it? Wait for a clear answer, record any change, then make_concepts.",
    "render": "Call make_concepts now with the design_route they gave.",
    "rendering": "It's being drawn. Say nothing more until it's on screen; if they speak, answer in a few words.",
    "finalising": "The GA and client pack are being made. Say once that they're on the way, then nothing until they're "
                  "on screen - never that they're done before then.",
    "review": "Ask: any changes, or finalise this one and make its GA and the client pack? A change -> change_option, "
              "exactly what they said. Not happy -> ask 'changes, or a completely new design?'; a new design -> "
              "more_options n=1, never the same one redone. Finalise, 'that's the one', 'make its GA' -> choose_option. "
              "Ask again whenever a new option is on screen.",
    "internal_q": "If the client pack has just been made, say in one line that it's done and the internal brief starts. "
                  "Then next_questions[0], worded for this job. If focus is internal, the render is waiting: when these "
                  "run out or they ask for it, call focus render.",
    "extra": "Ask if there's anything else for the brief; record it (other_notes), then finish_brief with now=true.",
    "done": "Everything they asked for is done. Ask if there's anything else; if not, a warm goodbye.",
}


def stage_now(s):
    st = convo.stage(s)
    busy = G.get("RT_BUSY", {}).get(s["id"])
    if st in ("render", "review") and busy in ("make_concepts", "change_option", "more_options"):
        return "rendering"
    if busy == "choose_option":
        return "finalising"      # 27 Oct 2026: the voice told the AM it was done and moved on while the pack was still being made
    return st

TOOLS = [
    {"type": "function", "name": "record_answers",
     "description": "Save what the AM just told you into the brief. Call it after EVERY answer that contains brief information, "
                    "before you ask the next question. Returns what is still needed and the next template questions.",
     "parameters": {"type": "object", "properties": {
         "updates": {"type": "object", "description": "Field id -> value, only what the AM actually said. Several at once is fine. "
                     "size is ALWAYS 'HEIGHT x WIDTH x DEPTH mm', height first: '1800 wide, 1200 high, 700 deep' -> '1200 x 1800 x 700 mm'."},
         "not_known": {"type": "array", "items": {"type": "string"}, "description": "Field ids the AM doesn't know (after you offered options)."}},
         "required": ["updates"]}},
    {"type": "function", "name": "set_pack",
     "description": "The pack the AM chose: 'client' (a 3D render, its GA and a one-page client sheet), 'internal' (the full SDI "
                    "brief - Andy's template) or 'both'. Call it as soon as they answer the pack question.",
     "parameters": {"type": "object", "properties": {"pack": {"type": "string", "enum": ["client", "internal", "both"]}},
                    "required": ["pack"]}},
    {"type": "function", "name": "focus",
     "description": "The AM chooses the order. 'internal': they want the SDI internal-brief questions now - before the "
                    "render, or between renders ('let's do the brief questions first', 'the studio bits now'). 'render': "
                    "back to the render / client pack ('back to the render', 'let's see it'). Whatever is already made "
                    "or answered stays.",
     "parameters": {"type": "object", "properties": {"on": {"type": "string", "enum": ["internal", "render"]}},
                    "required": ["on"]}},
    {"type": "function", "name": "show_past_work",
     "description": "Show on screen what SDI has made before for this client/unit, with quotes. ONLY when they ask for past or previous work. Never for 'show me the client pack / render / GA / PDF' - those are already in the chat.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "make_concepts",
     "description": "Make the 3D concept render - only after the render questions and past / mix / new are answered (or the AM "
                    "says just make it). Takes 1-2 minutes; it appears on screen. While it's drawn, ask NOTHING - wait for it.",
     "parameters": {"type": "object", "properties": {
         "output": {"type": "string", "enum": ["3D render", "3D render and technical GA", "GA only"]},
         "n": {"type": "integer", "description": "How many renders the AM asked for (default 1)."},
         "design_route": {"type": "string", "enum": ["past", "new", "mix", "own"],
                          "description": "What the AM said: build on SDI's past work, a brand-new concept, or a mix."}},
         "required": ["output", "design_route"]}},
    {"type": "function", "name": "choose_option",
     "description": "The AM picks a concept (A, B, C...). Draws its GA if wanted and makes the one-page client sheet.",
     "parameters": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}},
    {"type": "function", "name": "change_option",
     "description": "Change a concept: e.g. label B, change 'white header, 4 shelves'.",
     "parameters": {"type": "object", "properties": {"label": {"type": "string"}, "change": {"type": "string"}}, "required": ["label", "change"]}},
    {"type": "function", "name": "more_options",
     "description": "Make more concept directions (max 5).",
     "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}},
    {"type": "function", "name": "finish_brief",
     "description": "Build the full internal brief PDF. If the AM asks for the full / internal brief, do NOT call this first - go through NEXT QUESTIONS with them one at a time (call focus(internal) if the render isn't finished), then call it. Call it with now=true only when they say build the brief / PDF now as it is, skip the questions, or every question is done - at any point, even before the client pack.",
     "parameters": {"type": "object", "properties": {"now": {"type": "boolean", "description": "true only if they said build it now / skip the rest, or nothing is left to ask."}}}},
]


def first_name(s):
    """Who's on the call - the project they picked (4 Nov 2026: 'greet Andy by name')."""
    try:
        who = G["who_of"](s) if "who_of" in G else (s.get("name") or "")
    except Exception:
        who = s.get("name") or ""
    w = (who or "").strip().split()
    return w[0] if w and w[0].lower() not in ("web", "someone", "test", "guest") else ""


# 4 Nov 2026 (James: "tighten the voice instructions"): one structured brief, each rule once, instead of ~70 rules added
# one incident at a time. Every rule from before is kept - the incidents behind them are in this file's history and the
# code comments, not in what the voice reads. The fixed part comes first and this call's details last, so OpenAI can
# serve the unchanged part from its cache.
VOICE_RULES = """# Role and goal
You are a senior designer at SDI Displays, on a call with an account manager (AM) who is with a client or has just left
one. SDI designs and makes retail displays and store fixtures - FSDUs, gondola ends, wall bays, counter units, signage -
for Boots, M&S, Tesco, Milwaukee and others.
Your goal: a complete, accurate brief for THIS job and, when they want them, the render, its GA and client sheet, and
the SDI internal brief PDF - in a call that feels like talking to a sharp colleague, never like filling in a form.

# Tone
- Warm, quick, British English. One or two short sentences, then listen. Finish every sentence.
- Contractions, and a brief reaction to what they said ("Got it, four shelves." "Ah, their new layout?"), never the
  same one twice in a row. Shorter when they sound rushed. A light comment is fine; waffle is not.
- Picture the unit as they talk. If it isn't a classic display (a jacket, a sign, a wrap, a whole space), go with
  that - never force shelves or a stand - and if it's ambiguous ask the one question a designer would.

# You lead, they steer
- After each answer, move the brief on yourself: the next most useful open question for this job (next_questions[0]
  in the tool result), in your own words. One question at a time; two only when they belong together.
- Whatever the AM raises comes first. Answer their question properly and briefly - materials, finishes, retail, their
  brand, how it's made, anything sensible - then carry on. "What are the options?" gets 2-4 real options.
- They can go in any order, jump ahead, go back or change their mind; their newest word wins. When the direction
  changes - a different unit, size, look or past job - say it back in one line ("So a wall bay now, not the gondola
  end"), record it, and treat what depended on the old direction as open again (direction_changed says what).
- Never re-ask anything in already_known_never_ask_again or the conversation, and never bring back an answer they
  replaced (recent_changes).
- Skip what doesn't fit this job: a card FSDU needs no power question; a lit unit does. "Don't know", "skip" or
  "don't ask me that" means move on. If they want to stop the questions, stop.
- If something looks wrong - a size that doesn't suit the unit, a past job that doesn't match, a date in the past -
  say so plainly, suggest what you'd do, and let them decide.

# Listening
- Only the AM talking to you counts. Other voices, a TV, a phone call or a stray word is not an answer: ignore it, or
  ask once "Sorry - was that for me?". If it keeps happening, suggest once: "It's noisy there - hold the orb while you
  talk and I'll only hear you."
- Unclear, half-heard, or not an answer to what you asked: never guess and never move on - say you didn't quite catch
  it and ask again, briefly. "Change it" without saying to what: ask what it should be.
- "Mmm", "erm": they're thinking. Wait quietly.
- Two pieces with a pause between: answer all of it together. If you were cut off, respond to what they just said.
- Names exactly as heard: never add a first name or surname, never "correct" a spelling ("Denzel" stays "Denzel");
  if unsure, ask them to spell it. A client name that sounds odd but close to an SDI client ("boards", Boots): confirm
  once.
- Straight after you ask which pack, "Boots" or "booth" on its own means both.

# Recording the brief
- Call record_answers whenever they tell you anything for the brief - several fields at once is fine - in their own
  words, before your next question. If it comes back "Not saved", ask that question again.
- Size is the whole unit, height x width x depth. Never invent sizes, colours, materials, quantities or dates.
- "Not powder coat" or "as last time" isn't a material or a colour: ask what it should be, with 2-3 choices (for
  colours, the brand's own).

# The usual order - a guide, not a cage (each tool result's stage and now_do say where things are)
1. Pack. Once you know roughly what the client is after, ask once: the client pack (a 3D render, its GA and a one-page
   client sheet), the SDI internal brief pack, or both. Call set_pack only with what THEY said. If they carry on about
   the job instead, it's both, and you never ask again. They can change it any time ("just the client pack"). The
   internal brief has many names - the job sheet, the 8-page brief, the brief for the studio, the full or design brief,
   Andy's template - and any of them, at any point, means they want it: set_pack internal, or both if they still want
   the client pack.
2. Render. Keep it light: what it is and roughly its size ("you choose" is fine), then one question - a past SDI job or
   file to follow, or something new? Then make_concepts. Everything else is assumed, marked, and changed on the picture.
3. Review. When it's on screen: "Any changes, or shall I finalise this one and make its GA and the client pack?"
4. Internal brief. next_questions one at a time, then "Is there anything else you'd like to add to the brief?", then
   finish_brief with now=true.

# At any point
- "Make the render", "just draw it": ask only what you truly can't draw without, in one short question, check any past
  job they named, then make_concepts.
- A change to an option on screen: change_option on the one they mean (the latest if they don't say). It comes back
  as the next letter and the others stay. "Go back to A" means A. "Something completely different": more_options n=1.
- "That's the one", "finalise", "make its GA": choose_option. You may then ask once, briefly, what made it the one.
- "Let's do the brief questions first": focus internal. "Back to the render": focus render.
- "Build the brief PDF now": finish_brief with now=true.
- "Stop", "cancel that": what is being made stops; ask what they'd like next.

# Past SDI jobs
- A past job they name ("12148", "the forecourt bunker we did last year", "the latest GA") is their answer to past or
  new: record it as liked_job in their words and don't ask that question again.
- Before anything is drawn from it, say its full number and name back ("12148 - Rollershutter Forecourt Bunker, from
  February - is that the one?") and wait for a clear yes; after it, the render, GA and client pack follow that job.
  Offer only the jobs in which_past_job, never your own list, and for "the latest" or "this year" go by their dates.
  Never say a job is chosen unless which_past_job says so. A garbled number: ask which one.
- Its GA or pictures open in the chat beside the call as you check it, so "show me" means it's already opening: "It's
  on screen now - is that the one?" Seeing it is not a yes. If no, offer the other matches, and never draw in between.
  No GA on file: say so and suggest following its renders.
- A question about past work ("what did we last make for them?") is answered in words from sdi_made_before - number,
  what, when. Call show_past_work only when they ask to see it.

# While something is being made
- A render, the client pack or the PDF takes about a minute and the mic is off meanwhile: one short line that it's
  coming, then say nothing and ask nothing until it's on screen.
- Never say a render is coming, being made or ready unless make_concepts or change_option has just returned started,
  or a result says it's on screen. If they ask where it is and nothing is being made, call make_concepts.
- A "[Showroom: ...]" note is the app telling you what it has just done: tell them in one line and carry on.

# Never
- Never promise a price to the client, and never help with anything harmful.
- SDI's drives (W:, K:) are read-only to you: you find and show past work, never change it.
"""


def instructions(s):
    b = s["brief"]
    st0 = convo.stage(s)
    p = convo.render_plan(b) if st0 == "render_q" else convo.plan(b) if st0 == "internal_q" else []
    known = {k: v for k, v in b.items() if not k.startswith("_") and v}
    sb = b.get("_same_before") or ""
    now = datetime.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    convo_text = history(s["id"], 24)
    name = first_name(s)
    st = stage_now(s)
    return (
        VOICE_RULES
        + "\n# This call\n"
        + f"Today is {G['date'].today():%A %d %B %Y}; it's {now:%H:%M}, the {part}. Greet only with the right part of "
          "the day, or just 'Hi'.\n"
        + (f"Briefing: {name}.\n" if name else "")
        + "FIELDS (id: meaning):\n" + "\n".join(f"- {k}: {v[0]}" for k, v in FIELDS.items()) + "\n"
        + f"BRIEF SO FAR: {json.dumps(known)[:2500]}\n"
        + f"PACK: {convo.pack_label(b)}. FOCUS: {b.get('_focus') or 'the usual order'}. STAGE NOW: {st} - {NOW_DO[st]}\n"
        + f"NEXT QUESTIONS: {[q for _, q, _ in p[:6]]}\n"
        + (f"SDI MADE THIS BEFORE: {sb}\n" if sb else "")
        + (f"THEIR FILES: {convo.files_context(s, 1500)}\n" if convo.all_files(s) else "")
        + (f"CONVERSATION SO FAR in this chat (typed and earlier calls) - continue it, never start again:\n{convo_text}\n"
           if convo_text else "")
        + "\n# Start\n"
        + (f"A short, warm greeting{(' by first name, ' + name) if name else ''}, right for the time of day, then ask what "
           f"the client is after - like a colleague who's glad to hear from them ('Hi {name or 'there'}, good to hear from "
           "you - what's the client after?')." if not known.get("client") and not convo_text else
           "This is the same brief you were already working on: don't greet them as new, and don't ask again for "
           "anything in BRIEF SO FAR or the conversation. Say in one short line where you got to, then ask the next "
           "question."))


# 4 Nov 2026: gpt-4o-transcribe has a successor for live audio, gpt-live-transcribe (OpenAI, 29 July 2026): fewer errors on
# short phrases, numbers, specialist words and speech over loud background noise, and keyword hints. gpt-4o-transcribe
# is deprecated (OpenAI: shut down 26 Feb 2027). The live one is asked for first; if OpenAI won't take it in a voice
# session, /api/rt/session falls back to gpt-4o-transcribe, so a call always starts.
TRANSCRIBE_LIVE = os.environ.get("LITE_RT_TRANSCRIBE_LIVE", "gpt-live-transcribe")
TRANSCRIBE = os.environ.get("LITE_RT_TRANSCRIBE", "gpt-4o-transcribe")
SDI_WORDS = ("client pack, internal pack, both, FSDU, gondola end, wall bay, counter unit, plinth, header, shelf-edge strip, "
             "dump bin, totem, slatwall, powder coat, acrylic, MDF, Dibond, foamex, LED, GA, render, forecourt, coal bunker, AdBlue")
_CLIENTS = []


def _top_clients(n=20):
    """SDI's most frequent clients, from projects.db (read once; plain SQL, no AI)."""
    if not _CLIENTS:
        try:
            import sqlite3
            con = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects.db"))
            _CLIENTS.extend(b for (b,) in con.execute("SELECT brand FROM projects WHERE brand != '' GROUP BY brand "
                                                      "ORDER BY count(*) DESC LIMIT 40") if b and len(b) < 30)
            con.close()
        except Exception:
            pass
        if not _CLIENTS:
            _CLIENTS.extend(["Tesco", "Boots", "M&S", "Milwaukee", "TTI", "Sainsbury's", "Superdrug", "Halfords"])
    return _CLIENTS[:n]


def heard_hint(s):
    """What the transcriber is told it will hear (4 Nov 2026: in a noisy room the words it already expects are the ones it
    still gets right). SDI's words, then THIS brief's own names - the client, the store, the unit, the products, the
    people and the past jobs being talked about - then SDI's usual clients. It opens with 'UK retail display brief', so
    a read-back in silence is caught by the page's junkHeard() and the server's hint_echo() (and by matching this
    exact text - the page is given it)."""
    b = (s or {}).get("brief") or {}
    mine = []
    for k in ("client", "retailer", "unit_type", "products_held", "hero_products", "project_name", "account_manager",
              "customer_name", "liked_job"):
        v = str(b.get(k) or "").strip()
        if v and "(assumed)" not in v and v.lower() not in ("not known", "unknown"):
            mine.append(v[:60])
    for x in str(b.get("_same_before") or "").split("; ")[:3]:
        x = x.split(" (")[0].strip()
        if x:
            mine.append(x[:60])
    mine = list(dict.fromkeys(mine))
    others = [c for c in _top_clients() if c.lower() not in " ".join(mine).lower()]
    out = ("UK retail display brief for SDI Displays. Short answers like yes, no, both. Words: " + SDI_WORDS + "."
           + (" This job: " + ", ".join(mine) + "." if mine else "")
           + (" Clients: " + ", ".join(others) + "." if others else ""))
    return out[:900]


def keywords(s, n=40):
    """The words the live transcriber should expect, as a list (gpt-live-transcribe's keyword hints): this brief's own
    names first, then SDI's words and clients. Only letters, digits, spaces, apostrophes and hyphens - OpenAI refuses
    a session whose keywords hold other characters ("M&S" is sent as "M and S")."""
    b = (s or {}).get("brief") or {}
    words = []
    for k in ("client", "retailer", "unit_type", "products_held", "hero_products", "project_name", "account_manager",
              "customer_name", "liked_job"):
        v = str(b.get(k) or "")
        if v and "(assumed)" not in v and v.lower() not in ("not known", "unknown"):
            words += [v]
    for x in str(b.get("_same_before") or "").split("; ")[:3]:
        words.append(x.split(" (")[0])
    words += [w.strip() for w in SDI_WORDS.split(",")] + _top_clients(25)
    out = []
    for w in words:
        w = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9' -]+", " ", w.replace("&", " and "))).strip()[:40]
        if len(w) >= 2 and w.lower() not in (x.lower() for x in out):
            out.append(w)
    return out[:n]


def transcription(s, live=True):
    """The transcriber's settings for a call. live: gpt-live-transcribe (keyword hints, plural languages, low delay);
    otherwise the previous gpt-4o-transcribe settings."""
    if live and TRANSCRIBE_LIVE:
        return {"model": TRANSCRIBE_LIVE, "prompt": heard_hint(s)[:500], "keywords": keywords(s), "languages": ["en"],
                "delay": "low"}
    return {"model": TRANSCRIBE, "language": "en", "prompt": heard_hint(s)}


def hint_text(tr):
    """Everything the transcriber was told, as one text - what a read-back in silence would look like."""
    return (tr.get("prompt") or "") + " " + ", ".join(tr.get("keywords") or [])


def session_config(s, far=True, model=None, live=True):
    return {"type": "realtime", "model": model or RT_MODEL, "instructions": instructions(s),
            # 27 Oct 2026: "Boots" was heard as "boards" - the transcriber is told the names it will hear (heard_hint).
            # If it ever reads them back, the page's junkHeard() and the server's hint_echo() drop the line.
            "audio": {"input": {"transcription": transcription(s, live),
                                "turn_detection": {"type": "semantic_vad", "eagerness": "low", "interrupt_response": False,
                                                   "create_response": False},
                                "noise_reduction": {"type": "far_field" if far else "near_field"}},
                      "output": {"voice": RT_VOICE, "speed": 1.08}},
            "tools": TOOLS, "tool_choice": "auto"}


def tool_intent(name, a):
    """A tool call -> the same 'what did they mean' dict the text chat gets from Haiku, so handle() does the rest."""
    a = a or {}
    if name == "record_answers":
        return "", {"updates": a.get("updates") or {}, "not_known": a.get("not_known") or [], "intent": "answer", "reply": "", "no_auto": True}
    if name == "set_pack":
        return "", {"updates": {}, "intent": "answer", "pack": a.get("pack"), "reply": "", "no_auto": True}
    if name == "focus":
        on = "internal" if str(a.get("on") or "").lower().startswith("int") else "render"
        return "", {"updates": {}, "intent": "answer", "focus": on, "reply": "", "no_auto": True}
    if name == "show_past_work":
        return "", {"updates": {}, "intent": "show_past", "reply": ""}
    if name == "make_concepts":
        out = a.get("output") or "3D render"
        upd = {"output": out} if out == "GA only" else {}      # the client pack always carries the GA (set_pack)
        if a.get("design_route") in ("past", "new", "mix", "own"):
            upd["design_route"] = a["design_route"]
        # go: the voice model asked the questions and past / mix / new - draw it now, nothing more asked first (26 Oct 2026:
        # make_concepts asked "what products?" instead of drawing, while the AM was told the render was on its way)
        return "", {"updates": upd, "intent": "want_ga_only" if out == "GA only" else "want_visuals",
                    "n_renders": a.get("n"), "reply": "", "assume": True, "go": out != "GA only"}   # none said: A and B
    if name == "choose_option":
        L = str(a.get("label") or "A").strip().upper()[:1]
        return f"Option {L} is the one", {"updates": {}, "intent": "approve_visual", "change_request": f"option {L}", "reply": ""}
    if name == "change_option":
        L = str(a.get("label") or "A").strip().upper()[:1]
        return f"Option {L}: {a.get('change', '')}", {"updates": {}, "intent": "change_visual",
                                                      "change_request": f"option {L}: {a.get('change', '')}", "reply": ""}
    if name == "more_options":
        return "more options", {"updates": {}, "intent": "more_options", "n_options": int(a.get("n") or 3), "reply": ""}
    if name == "finish_brief":
        return ("build it now" if a.get("now") else "finish the brief"), {"updates": {}, "intent": "finish", "reply": "",
                                                                          "pdf": True}   # the brief PDF - never 'finalise the render'
    return "", {"updates": {}, "intent": "answer", "reply": ""}


def tool_result(s, replies):
    """What the voice model hears back: where the brief is and what to ask next - short, so it answers fast."""
    b = s["brief"]
    st = stage_now(s)
    p = convo.render_plan(b) if st == "render_q" else convo.plan(b)
    total, done = convo.plan_total(b)
    need = [k for k in need_for(b) if not convo.real(b.get(k))]
    shown = [r.get("text") or r.get("caption") for r in replies if r.get("role") not in ("ask", "choose_output")]
    asked = [r.get("text") for r in replies if r.get("role") in ("ask", "choose_output")]
    return json.dumps({
        "saved": True, "answered": f"{done} of {total}",
        "pack": convo.pack_label(b), "focus": b.get("_focus") or "", "stage": st, "now_do": NOW_DO[st],
        "render_in_progress": st == "rendering",
        "check_with_am": convo.brief_conflicts(b),
        "which_past_job": (
            {"confirm_with_am": f"Check it's the right job before using it - ask: 'Do you mean {b['_ref_confirm']['label']}?' "
                                "(yes -> it's followed; no -> the others are offered)"} if b.get("_ref_confirm") else
            {"ask_the_am": "More than one past SDI job fits - read these out briefly and ask which one they mean (a number, "
                           "a word from the name, or 'the first one' is enough):", "options": b["_ref_ask"]} if b.get("_ref_ask") else
            {"ask_the_am": "No past SDI job matched what they said - ask for the job number, or a few more words from its "
                           "name or the fixture."} if b.get("_ref_more") and not b.get("_ref_job") else ""),
        "following_past_job": b.get("liked_job") if b.get("_ref_job") else "",
        # 4 Nov 2026 (James: "keep track - every job might be slightly different")
        "direction_changed": (
            {"now": b["_direction"]["to"], "was": b["_direction"]["from"],
             "say_back": f"Say it back in one line ('So a {b['_direction']['to']} now, not the {b['_direction']['from']}').",
             "open_again": b["_direction"].get("reopened") or [],
             "then": ("Options already on screen are of the old unit: offer a fresh design of the new one (more_options n=1) "
                      "- never change the old picture into it." if b["_direction"].get("drawn") else
                      "Carry on with what's still open for the new unit.")
                     + (f" They were following past job {b['_direction']['following']} - check it still fits."
                        if b["_direction"].get("following") else "")}
            if b.get("_direction_new") and b.get("_direction") else ""),
        "recent_changes": [f"{c['field']}: {c['from']} -> {c['to']}" for c in (b.get("_changes") or [])[-4:]],
        "already_known_never_ask_again": {k: v for k, v in b.items() if not k.startswith("_") and convo.real(v)},
        "essentials_missing": need,
        "output_wanted": b.get("output") or "not chosen yet - see now_do",
        "concepts_on_screen": sorted({v.get("label") for v in s["visuals"] if v.get("kind") == "render" and v.get("label")}),
        # only while questions are what's next - not during a render, a review or the finalising (the voice jumped to
        # Andy's template while Option B was still waiting to be finalised)
        "next_questions": [q for _, q, _ in p[:4]] if st in ("render_q", "internal_q") else [],
        "sdi_made_before": b.get("_same_before") or "",
        "new_client": bool(b.get("_new_client")),   # true: never say SDI made anything for them; ask for photos/logo/guidelines
        "shown_on_screen": [x[:300] for x in shown if x][:6],
        "suggested_next": ("" if any(w in (asked[-1] if asked else "").lower() for w in ("which client", "who's the client", "who is the client")) and b.get("client")
                           else (asked[-1] if asked else ""))[:300],
    })[:3500]


def log_usage(sid, u):
    """response.done usage from the browser -> Brief Lite's daily spend (the same $ cap as everything else)."""
    m = SESSION_MODEL.get(sid, RT_MODEL)
    (ai, ao, ti, to), cr = price_of(m)
    inp, out = u.get("input_token_details") or {}, u.get("output_token_details") or {}
    # every reply re-reads the call so far; that part is served from OpenAI's cache at a fraction of the price -
    # counting it at full price made the cap stop calls early (21 Oct 2026: 5 minutes logged as $0.58)
    cd = inp.get("cached_tokens_details") or {}
    ca, ct = cd.get("audio_tokens", 0) or 0, cd.get("text_tokens", 0) or 0
    cost = ((max(0, inp.get("audio_tokens", 0) - ca) * ai + max(0, inp.get("text_tokens", 0) - ct) * ti + (ca + ct) * cr
             + out.get("audio_tokens", 0) * ao + out.get("text_tokens", 0) * to) / 1e6)
    if cost > 0:
        log_cost(sid, "voice-live", round(cost, 5))
    # 29 Oct 2026: the AM's words are also written out by gpt-4o-transcribe (~$6 per million audio tokens) - billed
    # separately by OpenAI and never counted before
    tr = max(0, inp.get("audio_tokens", 0) - ca) * 6.0 / 1e6
    if tr > 0:
        log_cost(sid, "voice-transcribe", round(tr, 5))
    return cost + tr
