"""Brief Lite - live voice, the way ChatGPT's voice mode works (Andy Baxter, 6 Oct 2026).

The browser talks straight to OpenAI's Realtime model over WebRTC: it hears the AM, answers in well under a second,
and stops the moment the AM talks over it. This file gives that model its brief and its tools:

  record_answers   - writes what the AM said into the brief (no extra AI call), returns the next questions
  show_past_work   - puts SDI's closest past jobs and quotes on screen
  make_concepts    - makes the 3D options (and GA later) - runs in the background, the page shows them
  choose_option    - the designer's pick -> GA of that option + client sheet
  change_option    - "B but white header"
  more_options     - C, D, E...
  finish_brief     - the full PDF + the "still missing" list

Everything a tool does goes through lite_app.handle() with the intent already decided, so voice, text and WhatsApp
always build the same brief. Cost: gpt-realtime (set in .env, 20 Oct 2026; was gpt-realtime-mini), about 5-8p a minute of talking, logged per response.
"""
import json, os
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
# 21 Oct 2026: the big voice model only for the people who brief clients (and demos); our own testing on the small one
RT_BIG = os.environ.get("LITE_RT_BIG_MODEL", "gpt-realtime-2")   # 4 Nov 2026: GPT-5-class reasoning, better at following tool results
RT_SMALL = os.environ.get("LITE_RT_SMALL_MODEL", "gpt-realtime-mini")
RT_BIG_FOR = [x.strip().lower() for x in os.environ.get("LITE_RT_BIG_FOR", "Andy Baxter,Nick").split(",") if x.strip()]
SESSION_MODEL = {}


def model_for(project_name, demo=False):
    return RT_BIG   # 29 Oct 2026: everyone gets Andy's model (the mini one mishears and talks stiffly)

SLOW = {"make_concepts", "choose_option", "change_option", "more_options", "finish_brief", "show_past_work"}

# 27 Oct 2026: what the voice model must do next, from where the brief is (convo_parts.stage) - sent with every tool result
NOW_DO = {
    "pack": "Ask which pack they need: the client pack (a 3D render, its GA and a one-page client sheet), the SDI internal "
            "brief pack, or both. Then call set_pack.",
    "render_q": "A few quick ones, never a long list: what the unit is, its rough size (H x W x D), what it holds and its colours / "
                "graphics - one short, "
                "natural question at a time, using what's already known. 'You choose' / 'typical' / 'just assume' for the size "
                "is a fine answer. Don't ask about materials, lighting, fixing or placement before the render - "
                "record them if the AM mentions them, otherwise they're assumed and the AM changes them on the picture. If "
                "record_answers says 'Not saved', ask the SAME question again.",
    "route": "Ask in one natural line: is there a past SDI job or file to follow (a number, a name, 'the latest one', anything "
             "on W:), or should you make something new? If they name one, record it as liked_job and call make_concepts with "
             "design_route past; new -> new; a bit of both -> mix. Don't ask anything else first - the rest is assumed and "
             "they can change it once they see it.",
    "confirm": "Before drawing, warn the AM about the clash in check_with_am in one sentence, suggest what's usual (a typical "
               "size for this unit, or free-standing), and ask: keep it as they said, or change it? Wait for their answer. "
               "Record any change with record_answers. Then ask past / mix / new if not asked, and call make_concepts.",
    "render": "Call make_concepts now with the design_route they gave.",
    "rendering": "The render is being drawn. Say nothing more and ask nothing until it's on screen; if the AM speaks, "
                 "answer in a few words only.",
    "finalising": "The GA and the client pack are being made right now. Say once that they're on the way, then say nothing "
                  "else and ask nothing until they're on screen - never say they're done before then.",
    "review": "Ask: do you like it - any changes, or shall I finalise this one and make its GA and the client pack? A change -> change_option "
              "(label, change) - exactly what they said, nothing else changes; it comes back as the next option (B, C...), "
              "the earlier ones stay to pick from. Not happy / 'something completely different' -> "
              "more_options(n=1) for a whole new design (never the same one redone); if they just say they don't like it, ask "
              "'changes, or a completely new design?'. Ask this again whenever a new one is on screen. Finalise -> "
              "choose_option(label of the one they want) - that makes its GA and the client pack. 'Make its GA', 'that's "
              "the one', 'looks good' also mean finalise -> choose_option.",
    "internal_q": "If the client pack has only just been made, first say in one line: 'That's your client pack done - now "
                  "let's start the internal brief.' Then ask next_questions[0] - one at a time, naturally, worded for THIS job (its client, unit, products, dates); "
                  "skip what doesn't fit this job. If record_answers says 'Not saved', ask the same question again.",
    "extra": "Ask if there's anything else they'd like to add to the brief. Record it with record_answers (other_notes), "
             "then call finish_brief with now=true.",
    "done": "Everything they asked for is done. Ask if there's anything else; if not, say goodbye warmly.",
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
     "description": "Build the full internal brief PDF. If the AM asks for the full / internal brief, do NOT call this first - go through NEXT QUESTIONS with them one at a time, then call it. Call it with now=true only when they say build it now as it is, skip the questions, or every question is done.",
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


def instructions(s):
    b = s["brief"]
    st0 = convo.stage(s)
    p = convo.render_plan(b) if st0 == "render_q" else convo.plan(b) if st0 == "internal_q" else []
    known = {k: v for k, v in b.items() if not k.startswith("_") and v}
    sb = b.get("_same_before") or ""
    return (
        "You are a senior designer at SDI Displays on a quick call with an account manager (AM) who has just come out of a "
        "client meeting. SDI designs and makes retail displays and store fixtures for Boots, M&S, Tesco, Milwaukee and others. "
        "Talk like a real colleague: warm, quick, British English, one or two short sentences, then listen. Think about what "
        "the client actually wants and say it back in your own words - if it isn't a classic display unit (a branded jacket, "
        "a sign, a wrap, a whole space), go with that and never force shelves, a stand or anything they ruled out. If something "
        "is ambiguous, ask the one natural question a designer would ask ('So the jacket itself - branded workwear - not a "
        "display for jackets?').\n"
        "SOUND HUMAN (29 Oct 2026): use contractions, react briefly to what they said before the next question ('Ah, Tesco "
        "- nice, their new layout?', 'Got it, four shelves.'), vary how you acknowledge (never the same 'Great!' twice), and "
        "never read a question like a form or list several at once. If they sound rushed, be shorter. A little warmth and "
        "a light comment is fine; waffle is not. Sound like you're picturing the unit as they talk.\n"
        "A FEW THINGS THAT MATTER:\n"
        "- If the AM changes their mind about the pack ('I don't want the client pack, just the internal brief'), call "
        "set_pack with the new choice straight away and carry on from its questions - never carry on with the old one.\n"
        "- 'Stop' / 'cancel that' means stop what is being made now; then ask what they want next.\n"
        "- Answer what they ask before asking anything. 'What are the options?' -> give 2-4 real options, then let them pick.\n"
        "- THE AM LEADS (2 Nov 2026, Andy: 'my question set was a guide, not a Bible'). Briefs aren't linear: they change "
        "their mind, correct themselves ('sorry, correction - 1100 high'), jump ahead, go back, ask you things, or bring a "
        "job unlike anything SDI has done (a council, an outdoor bunker). Follow them: answer what they ask, record every "
        "change or correction straight away with record_answers (the newest answer always wins), then pick up whatever is "
        "still missing. The questions below are a GUIDE: ask them in your own words, skip any that don't fit this job, "
        "combine ones that go together, never re-ask what's already answered, and never sound like a form.\n"
        "- PAST WORK THEY NAME: if they point you to a past SDI job ('refer to drawing 12148', 'the forecourt bunker we did "
        "last year', 'base it on the latest GA'), record it as liked_job with their exact words, treat that as their "
        "answer to past / mix / new (design_route past) and don't ask that question again. SDI's files are searched for "
        "it by number and name, and it leads the references.\n"
        "- THE FLOW is the usual order, not a cage. Every tool result tells you the stage and now_do: use now_do to know "
        "what's next once the AM's own point is dealt with.\n"
        "  1. Once you know roughly what the client is after, ask which pack they need: the client pack (a 3D render, its GA "
        "and a one-page client sheet), the SDI internal brief pack, or both. Then STOP and wait - never choose for them, never "
        "carry on before they answer. Call set_pack only with what THEY said.\n"
        "  Materials and colours: a 'not ...' answer or 'as last time' isn't an answer - ask what it should be instead, "
        "offering 2-3 choices (for colours, name the brand's own, e.g. Boots navy and white).\n"
        "  Names: if the client name you heard is odd ('boards', 'bush') and close to an SDI client (Boots), confirm once.\n"
        "  2. Client pack (or both): keep it light, like ChatGPT - only what it is and roughly what size (or 'you "
        "choose'), then ONE question: a past SDI job or file to follow, or something new? Then call make_concepts. "
        "Everything else is assumed and marked; the AM changes it on the picture.\n"
        "  3. While the render is drawn (1-2 minutes) ask NOTHING and don't move on - one short line that it's coming, then wait.\n"
        "  4. When it's on screen: 'Any changes, or shall I finalise this one and make its GA and the client pack?' A change -> "
        "change_option, then ask the same again once it's on screen. Finalise -> choose_option.\n"
        "  5. Internal pack (or after the client pack when it's both): NEXT QUESTIONS one at a time, then 'is there anything "
        "else you'd like to add to the brief?' - record it, then call finish_brief with now=true.\n"
        "- Never say a render is being made unless make_concepts or change_option has just returned started. If they ask where "
        "it is and render_in_progress is false with nothing on screen, call make_concepts.\n"
        "- If an answer is unclear, half-heard, or doesn't fit the question you asked (you asked 'keep it or change it?' "
        "and heard 'Client'), NEVER guess and never move on: say you didn't quite catch it and ask again. If they say "
        "'change it' without saying to what, ask what it should be.\n"
        "- PEOPLE'S NAMES: say and record a name EXACTLY as you heard it - 'Denzel' stays 'Denzel'. Never add a first name or "
        "surname they didn't say (27 Oct 2026: 'Denzel' was read back as 'David Denzil'), never 'correct' the spelling. If "
        "you're not sure what you heard, ask them to spell it.\n"
        "- Names exactly as said ('Bush' is Bush, never Boots); confirm once if unsure. 'Don't ask me that' / 'don't know' = "
        "skip it and move on. Never re-ask something already answered.\n"
        "- Keep the brief flowing in the background: call record_answers whenever they tell you something. Work through "
        "NEXT QUESTIONS naturally - pick the one that fits the conversation, skip what doesn't fit this job, never sound like "
        "a form. If they want to stop the questions, stop.\n"
        "- Size means the whole unit (H x W x D). Never invent sizes, colours, materials or dates (today is "
        + f"{G['date'].today():%A %d %B %Y}" + "). "
        + f"The time now is {datetime.now():%H:%M}, the {('morning' if datetime.now().hour < 12 else 'afternoon' if datetime.now().hour < 17 else 'evening')} - never say 'good morning' "
        "or any other part of the day unless it is right; 'Hi' is always fine.\n"
        "- When they finalise a render you may ask once, briefly, what made it the one - never push.\n"
        "- A '[Showroom: ...]' note means the app already started that - just tell them in one line. If you didn't "
        "clearly hear or understand what they said, say so in a few words and ask your question again - never guess. "
        "If they're just thinking ('mmm', 'erm'), wait quietly.\n"
        "- BE LIKE CHATGPT (3 Nov 2026, Andy): answer ANY question they ask, properly and briefly - materials, finishes, "
        "retail, the client's brand, ideas, how it's made, even a general one - then carry on. Whatever they say to put in "
        "the brief, record it with record_answers in their words. Only refuse something harmful or a firm price promise.\n"
        "- WHEN THEY ASK FOR THE RENDER ('make the render', 'show me something', 'draw it'): don't make them finish the "
        "list. Ask only what you truly can't draw without (what it is and roughly the size, or 'you choose') in ONE short "
        "question, check any past job they named, then call make_concepts. Everything else is assumed and marked.\n"
        "- SEEING A PAST JOB: when you check a past job, its GA / renders appear in the chat beside the call. If they say "
        "'show me', 'open the drawing' or 'what does it look like', it is already opening there - say 'It's on screen now - "
        "is that the one?'. If they say no, read out the other matches (or ask for the number) and offer to show them too. "
        "Once they say yes, the new render, GA and client pack follow that job.\n"
        "- 'Show me the GA' brings its drawing, 'show me the render' its pictures. If it has no GA yet, say so and suggest "
        "following its renders instead.\n"
        "- BE A SMART COLLEAGUE: if something looks wrong or odd (a size that doesn't fit the unit, a past job that doesn't "
        "match what they described, a date far in the past, no drawing on file), say so plainly and suggest what you'd do, "
        "then let them decide. Never just carry on quietly.\n"
        "- THE INTERNAL BRIEF has many names: 'the job sheet', 'the 8-page brief', 'the brief for the studio', 'the full / "
        "technical / design brief', 'Andy's template'. Any of them, at any point, means set_pack internal (or both if they "
        "still want the client pack). Then ask only what THIS job needs, in the order the talk goes - a card FSDU isn't "
        "asked about installation or power, a lit unit is asked about power, an outdoor bunker about weather and fixing. "
        "Skip what is already known, take answers in any order, and never read the list out.\n"
        "- While a render, the client pack or the PDF is being made the mic is off - say one short line that it's coming, "
        "then wait silently until it's ready.\n"
        "- Showing them a past job's GA is NOT a yes. After it's on screen ask 'is that the one?' and WAIT for a clear yes "
        "before any render. If they say no, offer the other matches - never draw in between.\n"
        "- A question about past work ('what's the last job we did for them?', 'what have we made for coal bunkers?') gets "
        "an answer in WORDS from SDI MADE THIS BEFORE - name the job, what it was and when. Only call show_past_work when "
        "they ask to SEE or SHOW it.\n"
        "- Keep replies short so you finish every sentence.\n"
        "- When you've just asked which pack, 'Boots' / 'booth' heard on its own means BOTH - take it as both, don't ask again.\n"
        "- If they said more in two or more pieces (they paused to think, then carried on), answer ALL of it together - "
        "record every detail they gave (colours, materials, sizes) and acknowledge it before your next question. If "
        "you were cut off, don't repeat what you were saying - respond to what they just said.\n"
        "- PAST JOB NUMBERS: say the job you mean by its full number and name ('12148 Rollershutter Forecourt Bunker'), "
        "and only say a job is chosen when the tool result's which_past_job says it is. If a number they said came "
        "through garbled, ask which one - never assume.\n"
        "- PAST JOB OPTIONS: when you offer past jobs, read the ones in which_past_job (the tool result) - not a list of your "
        "own. For 'what did we make this year / latest', go by the dates shown (2026-02 is this year). Before anything is "
        "drawn from a job they name, say its full number and name back ('12148 - Rollershutter Forecourt Bunker, from "
        "February - is that the one?') and wait for yes.\n"
        "- W: and K: are read-only.\n"
        "FIELDS (id: meaning):\n" + "\n".join(f"- {k}: {v[0]}" for k, v in FIELDS.items()) + "\n"
        f"BRIEF SO FAR: {json.dumps(known)[:2500]}\n"
        f"NEXT QUESTIONS: {[q for _, q, _ in p[:6]]}\n"
        f"PACK: {convo.PACK_IDS.get(convo.pack_of(b), 'not chosen yet')}. STAGE NOW: {stage_now(s)} - {NOW_DO[stage_now(s)]}\n"
        + (f"SDI MADE THIS BEFORE: {sb}\n" if sb else "")
        + (f"THEIR FILES: {convo.files_context(s, 1500)}\n" if convo.all_files(s) else "")
        + (f"CONVERSATION SO FAR in this chat (text and earlier calls) - CONTINUE it, never start again:\n{convo_text}\n"
           if (convo_text := history(s["id"], 24)) else "")
        + (f"Start with a short, warm greeting by their first name{(' - ' + first_name(s)) if first_name(s) else ''} - right for the "
           f"time of day, like a colleague who's glad to hear from them ('Hi {first_name(s) or 'there'}, good to hear from you - "
           "what's the client after?') - then ask what the client is after. One or two short sentences." if not known.get("client") and not convo_text else
           "This is the SAME brief you were already working on. Do NOT greet them as new or ask again for anything in BRIEF SO "
           "FAR or the conversation. Say in one short line where we got to, then ask the next question."))


def session_config(s, far=True, model=None):
    return {"type": "realtime", "model": model or RT_MODEL, "instructions": instructions(s),
            # 27 Oct 2026: "Boots" was heard as "boards" - the transcriber is told the names it will hear. If it ever reads
            # this back, the page's junkHeard() drops the line (it matches "retail display brief" / 5+ client names).
            "audio": {"input": {"transcription": {"model": os.environ.get("LITE_RT_TRANSCRIBE", "gpt-4o-transcribe"), "language": "en",
                                                  "prompt": "Short answers like yes, no, both, client pack, internal pack. Clients: Tesco, Boots, Milwaukee, M&S. Coal bunker, FSDU, gondola end, GA."},
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
        return ("build it now" if a.get("now") else "finish the brief"), {"updates": {}, "intent": "finish", "reply": ""}
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
        "pack": convo.PACK_IDS.get(convo.pack_of(b), "not chosen yet"), "stage": st, "now_do": NOW_DO[st],
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
    ai, ao, ti, to = RT_PRICE.get(m, RT_PRICE["gpt-realtime-mini"])
    cr = RT_CACHED.get(m, RT_CACHED["gpt-realtime-mini"])
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
