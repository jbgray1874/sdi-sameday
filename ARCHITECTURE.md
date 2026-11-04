# SDI Same Day Intelligence: how it works

This guide covers the whole app: how a brief goes from the account manager's voice to a render, a GA drawing and two PDFs, where each file fits, and which AI does which job. It is written for whoever deploys and looks after the app (James). In the code the app lives in `brief_lite\` and is sometimes called Brief Lite.

Updated 4 November 2026.

## 1. The idea in one paragraph

An account manager (AM) is on a client call or has just finished one. The AM talks to Same Day, or types, the way they would talk to ChatGPT. The tool works through the brief like this:

1. **Choose a pack.** It asks once which pack is needed: a client pack, an internal brief, or both. If the AM doesn't answer and carries on about the job, it takes **both** (marked "assumed") so nothing is missed, and never asks again. The AM can change the pack at any point ("actually just the client pack").
2. **Render questions.** For the render it asks only what the picture can't be drawn without: the unit, its size, the products and the colours.
3. **Past work or new.** It asks whether to follow a past SDI job or file, or make something new. Any job or file the AM names, by number, name, fixture, file name or time ("the latest bunker"), is looked up on W:. The tool **always checks back** before following it ("Do you mean 12148 - Rollershutter Forecourt Bunker?").
4. **Render and changes.** It draws a concept render. Changes come back as new options (A, B, C…).
5. **Client pack.** For the chosen option it makes a GA drawing and a one-page client sheet.
6. **Internal brief.** It asks the job-specific questions and makes SDI's 8-page internal brief PDF for the studio.

That is the usual order, not a fixed one (section 4b): the AM can do the internal questions first, ask for the render before half the questions, change an option at any point, or build the brief PDF early.

## 2. The parts

```
 browser / phone (lite_page.html, PWA)
   │  typed chat, voice notes ─────► /api/chat, /api/voice ──► handle()  (lite_app.py)
   │  live call (WebRTC audio) ◄───► OpenAI gpt-realtime   ──► /api/rt/tool, /api/rt/log
   ▼                                                              │
 lite_app.py (Flask on 0.0.0.0:5020, served by waitress)          ▼
   ├─ convo_parts.py     flow: which stage, what's missing, size sanity checks
   ├─ realtime_parts.py  live-voice instructions, tools, transcription vocabulary
   ├─ lite_search.py     past SDI jobs: names, synonyms, "latest", file names, GA pages from W:
   ├─ moodboard.py / spaces.py   reference pictures and AM "spaces" (upload boards)
   ├─ ga_draw.py         GA drawn by code (fallback, and the size check)
   ├─ pdf_pack.py        client sheet + 8-page internal brief
   ├─ lite_store.py      lite.db (chats, briefs, projects, AI spend)
   └─ out\               renders, GAs, PDFs, voice files
```

| File | Role |
|---|---|
| `lite_app.py` | Web server and the brain. `handle()` takes every typed or voice-note message. `make_visual()` draws a render; `make_ga_ai()` draws the GA; `ref_lookup()` finds and confirms the past job the AM named. `/api/brand` serves the client's logo and colours. `log_cost()` writes every AI call's cost. |
| `convo_parts.py` | The flow, as a state machine: pack → render questions → past/mix/new → render → changes → finalise → internal questions → PDF. None of these is a gate (section 4b). `RENDER_KEYS` is the short list asked before a render. `brief_conflicts()` catches odd sizes (under 150 mm or over 4.5 m, deeper than wide, far from the usual size for that unit). |
| `realtime_parts.py` | Live call: the voice's instructions (`VOICE_RULES`: one structured brief, each rule once, fixed text first so OpenAI can cache it; `NOW_DO` adds only what each stage needs) ("the AM leads", short questions, confirm past jobs), its tools (`record_answers`, `make_concepts`, `show_past_work`, `set_pack`…), and the transcription vocabulary (client names and SDI words such as FSDU, gondola end, coal bunker, AdBlue). |
| `lite_search.py` | Past SDI work. It searches `knowledge.db` and `projects.db` by job number, by project name, by words in file names, and by time ("latest", "this month"). `heard_fix()` corrects common mishearings ("four court" → forecourt). `job_drawing_pages()` renders page 1 of a job's GA PDFs from W: to PNG (PyMuPDF, read-only). |
| `pdf_pack.py` | The client concept sheet and the internal brief PDF |
| `moodboard.py`, `spaces.py` | Reference pictures and the AM's own upload boards |
| `ga_draw.py` | A GA drawn by code from the sizes. Used when the AI GA's sizes are more than 2% off. |
| `lite_store.py` | SQLite access to `lite.db` |
| `lite_page.html` | The whole page: chat, live call stage, brand reveal and colours, voice notes, Stop button, past-work viewer, sidebar |
| `pwa\` | Phone install files (icons, manifest) |
| `build_projects.py`, `build_profiles.py`, `build_estimates.py` | Offline: build `projects.db`, `client_profiles.json` and estimate data from W:. These only read W:. They have already been run. |

## 3. Which AI does what

| Job | Model | Notes |
|---|---|---|
| Live call (voice) | OpenAI `gpt-realtime-2` (set by `LITE_RT_BIG_MODEL`; put `gpt-realtime` back there to roll back) | Same model for everyone. Turn-taking is `semantic_vad`; noisy mode uses `server_vad` (section 4). Its spend is counted at `gpt-realtime`'s price until its own is set in `.env` as `LITE_RT_PRICE` (audio in, audio out, text in, text out, cached, USD per million tokens). A model with no price is never counted at the cheap mini price. |
| Live transcription | OpenAI `gpt-live-transcribe` (since 4 November 2026; `LITE_RT_TRANSCRIBE_LIVE`). If OpenAI refuses it for a call, SameDay uses `gpt-4o-transcribe`, which is deprecated and shuts down on 26 February 2027. | It is told keyword hints (`keywords()`) plus a short prompt. Its vocabulary prompt (`heard_hint()`) holds SDI's words, this brief's own names (client, store, unit, products, people, past jobs) and SDI's usual clients. It is updated during the call as the brief names more. |
| Voice notes in | OpenAI `gpt-4o-transcribe` | Falls back to local Whisper if OpenAI fails |
| Voice notes out | OpenAI `gpt-4o-mini-tts`, voice "fable" (British) | Falls back to the free edge-tts voice |
| Chat turns, checks, GA size check | Claude Haiku | Cheap and fast |
| Design director (writes the render prompt) | Claude Opus | `LITE_DIRECTOR_MODEL` in `.env` |
| Moodboard | Claude Sonnet | |
| Render and GA pictures | OpenAI `gpt-image-2` | First render is "medium" quality (about 40 s); finalise is HD. Up to 6 reference pictures, converted to PNG. |

Keys: the real keys file is `SDI_Automation\.env` inside the K: deploy folder (Muhammad's keys; James uses these, no personal account). It is copied to `C:\SDI_Automation\.env` on the server with the code, and every API call reads its key from there. The `.env.example` next to the guides is only an empty template (Windows shows it as ".env", type "EXAMPLE File"). Never in Git.

## 4. What happens on a live call

1. The page asks `/api/rt/session` for a short-lived token, then talks to OpenAI directly over WebRTC.
2. Everything the AM says is sent to `/api/rt/log` and goes through the same `handle()` as typed chat. The brief is saved, past jobs are looked up, and the next question is chosen.
3. When the voice calls a tool, `/api/rt/tool` runs it.
   - `make_concepts` refuses until the AM has confirmed any past job they named.
   - `show_past_work` only runs if the AM actually asked to see past work.
4. While a render is being drawn, the mic is paused and a **Stop** button is on the stage. `/api/rt/done` returns `drawn: false` if no new picture was made, so the voice never says "ready" for nothing.
5. Lines the voice couldn't use are written to `brief_lite\rt_drops.log`. This is useful when someone says "it didn't hear me".
6. "Show me the GA" (or "the shelf drawing", "all of them", "the second one") runs as its own visible turn, `show_ref`, so the drawings reach the screen. The voice then asks "is that the one?" and waits for a clear yes.
7. The page waits about 1.2 seconds after the AM stops before the voice answers, so a pause to think isn't cut into. If the AM talks while the voice is speaking, it stops at once. Whispers, "mmm" and read-back noise are dropped and never shown. A read-back of the vocabulary prompt is recognised by comparing it with the prompt itself (`echo_of()` on the server, `hintEcho()` on the page).
8. **Noisy rooms.** After 3 lines of noise in a minute the call switches to "noisy": only a clear, close voice starts a turn, and the bar it must clear follows how loud the room is (`vadBar()`). If noise still gets through, a second, stricter level starts and the voice suggests holding the orb (push-to-talk). Each level steps back down after two quiet minutes. The voice is also told to ignore other voices, a TV or a phone call, and never to note something half-heard.

## 4b. Any order (4 November 2026)

Sales and account managers build a client solution their own way, so the flow is a guide, not a cage.

| The AM says, at any point | What happens |
|---|---|
| Nothing about the pack | It takes **both** (assumed) after asking once, and never asks again |
| "Actually just the client pack" / "I don't need the internal brief" | The pack changes (`convo.pack_change()`). Merely mentioning a pack changes nothing. |
| "Make the render" before the questions | It draws now. Gaps are assumed and marked; a past job they named is still checked first. |
| "Let's do the internal questions first" | `_focus = internal`: the internal-brief questions come now. The voice uses the `focus` tool. |
| "Back to the render", or any render request or change | `_focus` is cleared, and the client pack carries on where it was |
| "Change the header" / "go back to option A" | That option is changed into the next letter. The earlier options stay. |
| "Build the brief PDF now" | It is built straight away, even before the client pack (only on the AM's own words) |
| Dates, budget or sizes, early or late | Recorded when said. A newer answer replaces the older one. |

The brief is complete when every question has an answer, in whatever order. These checks stay: a past job is confirmed before it is followed, a size clash needs a clear answer (or "just draw it"), and the voice can never choose a pack the AM didn't say.

Tests: `tests/test_any_order_and_noise.py`. They run offline on a copy of the app, with no AI calls and no keys.

## 4a. Past SDI jobs: find, show, follow

- **Finding a job.** `lite_search.resolve_reference()` matches the AM's words against `projects.db`. Words in the job's **name** count most. Words inside drawing titles count less. The client's own name only filters. Backup and archive folders are never jobs. A weak match is offered as a choice, never picked on its own.
- **Showing a job.** `show_ref_files()` in `lite_app.py` copies the job's GA (page 1, as PNG) and pictures from W: into `out\jobref\` (read-only on W:), with the file name. Jobs newer than the index are read straight from their W: folder.
- **Following it.** Once the AM says yes, `_ref_job` is set. The render then uses only that job's pictures and GA, the design director is told to build that unit, and the GA copies that job's real GA. "Something completely new" overrides it.
- **Spoken job numbers.** The transcriber can mangle a number ("12148" → "1:148"). `spoken_job()` joins the digits and matches them, plus the job's name words, against the jobs on offer. If it still can't tell, it asks which one and never opens a different job.
- **GA from a chosen job.** The AI GA is told never to copy the old job's dimensions. If its numbers still come out wrong, it gets one retry with the error spelled out, and only then falls back to the code-drawn GA. Drawings of other jobs filed in the same W: folder are never shown as this job's GA.
- **Refreshing the index.** `python brief_lite\build_projects.py` takes about 10 seconds, needs no AI, and reads the scan files already on the server.
- **Earlier client files.** Files uploaded to an earlier brief for the same client are background only. They never lead a new render or GA.

## 4b2. Keeping track (4 November 2026)

The voice leads: after each answer it moves to the next most useful open question for this job. The account manager steers, and whatever they raise comes first. Every answer that replaces an earlier one is logged in `_changes`; the voice sees the last four as `recent_changes`.

A change of the unit itself (a gondola end becoming a wall bay, checked by `new_direction()`) is a new direction:

- What was only guessed for the old unit (its typical size, fixing, lighting and so on) is dropped, so it's worked out again for the new one.
- The past-work search starts again.
- The voice is told once (`direction_changed`) to say the change back. If options are already on screen, it offers a fresh design rather than changing the old picture.
- A reply that changes the brief is never taken as the answer to "past job or new?", so nothing is drawn before the change is taken in.

## 4c. On the phone (4 November 2026)

SDI Intelligence (port 8071, already published through App Proxy) carries SameDay at `/sameday/` on its own https address (`sameday_proxy.py` in ClaudeVision):

- **Who gets in.** From outside the office, only people signed in with their SDI Microsoft account. Writes must come from that same address.
- **What SameDay gets.** It gets `X-Forwarded-Prefix: /sameday`, from 127.0.0.1 only. That puts the prefix into the page, the manifest and the service worker, and a small script on the page puts it in front of every address the page asks for (`PREFIX_SHIM` in `lite_app.py`).
- **No team code.** The request comes from this machine, so the team code isn't asked; Microsoft sign-in has been asked instead.
- **Unchanged.** Opened directly at `:5020`, nothing changes.

## 5. Data, spend and safety

- **W:, S: and K: on the server.** The past-work indexes hold paths as `W:\...`, `S:\...` and `K:\...`. A Windows service has no mapped drives, so at start SameDay maps any missing letter for itself, by its network name (`map_drives()`; `LITE_DRIVES` in `.env` overrides). `/api/version` reports which drives it can read, and `Update-SameDay.ps1` prints that.
- **Read-only on W: and K:.** The app never writes to the shared drives; everything it makes goes to `brief_lite\out\`.
- **Spend.** Every AI call is logged in `lite.db` (table `ai_calls`). The daily cap is in `studio_data\ai_switch.json` → `brief_lite_daily_cap_usd`, currently **$10**. When the cap is reached the page says so clearly. To give a fresh $10 for the rest of a day, set `brief_lite_budget_reset_at` to the current time, for example `2026-11-03T15:06:36`. Spend then counts from that moment until midnight. The log itself is never changed. No restart is needed.
- **Chats.** Chats are never hard-deleted: deleting one sets `state='deleted'`.
- **What leaves the building.** Brief text, voice audio and reference pictures go to OpenAI and Anthropic to do the work. Nothing else does.

## 6. Where to look when something breaks

| Symptom | Look at |
|---|---|
| Page won't load | Is `lite_app.py` running? Check `brief_lite\lite_err.log`. |
| "Talk mode" or the call won't start | The OpenAI key has expired or the budget is used up. The page shows which. Check `.env`. |
| It didn't hear a word | `rt_drops.log`. Add the word to the vocabulary in `realtime_parts.py` (`session_config` prompt) and to `HEARD` in `lite_search.py`. |
| Wrong past job | `lite_search.resolve_reference()`. The AM can always say "no" and pick another one. |
| GA sizes wrong | `ga_sizes_wrong()` in `lite_app.py` swaps in the code GA when the AI's sizes are more than 2% off. |

Questions: Muhammad Yazir.
