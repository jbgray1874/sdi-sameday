# Build "SDI Brief Lite" — WhatsApp/voice briefing → SDI-grounded concept visuals for clients

You are a senior full-stack + applied-AI engineer. Build a production-quality web app (plus a WhatsApp
channel) for **SDI Displays Ltd** (UK retail display / POS manufacturer, ~200 staff, own design studio
and factory in Loughborough). Read this whole brief before writing code. Ask me questions only if
something here is contradictory — otherwise make sensible decisions and say what you decided.

---

## 1. The problem in one paragraph

Account managers (AMs) and project managers (PMs) come out of a client meeting ("Boots want a No7 shelf
unit for the front of store, about 1800 high, white gloss with oak shelves and a navy header") and the
first thing they need is **a visual to show the client for approval**. Today that means waiting days
for the design studio, or using ChatGPT, which produces a random generic shelf with a logo stuck on it
that looks nothing like what SDI actually builds. SDI has **20 years of its own renders, drawings and
estimates** on its network drives — already indexed on my PC (details in §5). I want an app where the
AM briefs by **voice or text, on WhatsApp or the web**, and gets back, within a couple of minutes:

1. the **closest things SDI has built before** (the client's own past jobs first), with what they
   were, when, how many drawings, and what they were quoted at;
2. **two brand-new concept visuals** that clearly look like *SDI-built units* — same construction,
   materials, proportions, header/shelf style as SDI's past work for that client — not generic AI art;
3. a **one-page client sheet (PDF)** with those concepts, SDI branded, nothing internal on it, ready
   to forward to the client;
4. later, the **full internal brief** in the Sales Director's 8-page format (§8).

**Visuals first.** Questions that are not needed to draw the unit come *after* the pictures.

---

## 2. Users and how they talk to it

| User | Channel | What they want |
|---|---|---|
| Account managers / PMs (main users, many resist new processes) | WhatsApp voice notes & text on their phone; sometimes the web page | Visual for the client fast, with as few questions as possible |
| Sales Director (Andy Baxter) | Web / PDF | Every brief complete, consistent, re-usable, transferable to Sage (no re-keying) |
| Studio manager (Jonathan "Jono") / designers | Web | See approved concepts and the brief when the job comes to the studio |
| Finance / ops (Charlotte, James Gray – AI & Systems Controller) | Web | Every enquiry recorded as an *opportunity* with converted yes/no → conversion rate per client |

The conversation must feel like talking to a helpful colleague — short, British English, warm, never
a form. It must handle "don't know", "skip", rambling one-minute narratives, voice-transcription
mistakes ("Boards" for "Boots", "Lint" for "Lindt"), and corrections ("no, 2 metres high").

---

## 3. Core flow (must work end to end)

```
AM (WhatsApp voice/text or web)  ─►  1. UNDERSTAND
                                       extract every field it can from the message (LLM, one call per turn)
                                       if a field needed for the picture is missing → ask (max 2 things per reply)
                                       needed for a picture: client, what the unit is, where in store, approx size, materials/finish
                                       (colours/graphics and products held: use if given, don't block on them)
                                            │
                                            ▼
                                     2. FIND SDI'S PAST WORK  (local, free, already indexed – §5)
                                       client's own past jobs first, then best look-alikes from any client
                                       group by job; per job: best 2–4 renders + facts + estimate
                                       send the top 3 past jobs back as images with captions
                                            │
                                            ▼
                                     3. MAKE TWO NEW CONCEPTS  (image model, with SDI renders as references)
                                       Option A = grounded on the client's own past renders
                                       Option B = grounded on the closest look-alike from any client
                                       prompt includes the brief + "how SDI built these" (materials & processes
                                       pulled from the reference jobs' estimates, §5.3)
                                            │
                                            ▼
                                     4. CLIENT SHEET  (1-page landscape PDF, SDI branded, both options,
                                       short spec line, "concept for discussion" note — NO costs, NO job numbers,
                                       NO other clients' work)
                                            │
                                            ▼
                                     5. ITERATE  "B but oak shelves", "taller header on A", "A is the one",
                                       "technical drawing please" → edit that option (use the previous concept
                                       as the base image, change only what was asked) / produce a GA-style
                                       line drawing / re-issue the client sheet
                                            │
                                            ▼
                                     6. FINISH  remaining template questions (§8) asked conversationally,
                                       then the 8-page internal PDF + a JSON of all fields for Sage
```

Also:
- The AM can **send a photo/sketch/AI render from the client** at any time → it becomes the first
  reference image for the concepts and is stored with the brief.
- A brief "session" stays open for ~3 hours per phone number; "new brief" starts another; "cancel" closes.
- The briefing date is filled in automatically and read back ("New brief started Friday 2 October").
- Relative dates ("next Wednesday") are converted to real dates from today.

---

## 4. Visual quality — the most important requirement

The whole point is that visuals look like **something SDI would actually design and manufacture**:

- Always pass **real SDI renders** of the closest past jobs as reference images (image-edit /
  multi-reference mode), not just a text prompt. Client-supplied images go first.
- The prompt must tell the model to follow the references' construction, proportions, materials,
  joinery/metalwork, shelf and header style; not to copy any single reference; to show the brand name
  as clean simple lettering on the header (no invented slogans, prices or extra text).
- Add "house notes" from SDI's estimates for those reference jobs (e.g. *"SDI built these from 12mm
  Black Tex MDF, 40x10 ERW tube, powder coat RAL 9005, 2mm PETG header lens; processes: laser, fold,
  CNC joinery, powder coat"*) so materials are realistic.
- 3D render style: photoreal 3ds Max / V-Ray retail visual, unit in a bright realistic store, ¾ front
  view, products on shelves, person for scale if floor-standing. Landscape 1536×1024.
- Technical style (on request): black-on-white SolidWorks-style GA — front/side/plan + small iso,
  overall H/W/D dimension lines from the brief, title block "SDI DISPLAYS – CONCEPT GA – NOT FOR
  MANUFACTURE". Clearly labelled concept only.
- Edits must keep everything else the same (use the last concept as the base image).
- Image model: **OpenAI `gpt-image-1`** (or newer) via `images.edit` with multiple reference images;
  key in `OPENAI_API_KEY`. Quality "medium" by default (~$0.06/image), configurable.
- Make the image provider swappable (an interface), so a local GPU model can be plugged in later.

**Data protection:** reference renders are SDI/client IP. Send only the few reference images needed
per request, never bulk-upload the library, and keep a log of which files were sent.

---

## 5. Data that ALREADY EXISTS — do not re-index, reuse it

All of this is on my Windows PC (`C:\SDI_Automation`). The network drives are **read-only for this
project — never write anything to W: or K:**. Everything new goes under `C:\SDI_Automation\brief_lite\`.

Network drives (read-only):
- **W:** = `\\sdi-dc01\CAD` — design work: `W:\Design\Customers April 08 Onwards\<Client>\<JobNo - Name>\<JobNo>-Creative\<JobNo>-Renders\…`,
  SolidWorks PDFs, artwork, 3ds Max files.
- **K:** = `\\sdi-dc01\shareddata$\Shared` — `K:\Estimating\Completed\Manual Estimates\<Year>\<Client>\<Job>\*.xls(x)` (estimate sheets), `K:\Customers\<Client>\…`.

### 5.1 Image index (W: renders, visuals, photos) — 269,278 images
- `C:\SDI_Automation\all_img_meta.json` — list, one record per image, **row order = embedding row**:
  `{"id", "name", "brand", "project", "img": "C:\\SDI_Automation\\all_img_thumbs\\00000.jpg" (local 432×600 thumb), "src": "\\\\sdi-dc01\\CAD\\...\\render.png" (full size on W:), "folder"}`.
  (Note: the `id` field is NOT unique — use the row position.)
- `C:\SDI_Automation\all_img_index.npz` → `emb` float32 **(269278, 512)**, L2-normalised,
  **CLIP `clip-ViT-B-32`** (sentence-transformers) → use for **text → image** search.
- `C:\SDI_Automation\all_img_dino_index.npz` → `dino_emb` **(269278, 768)**, **DINOv2-base** →
  use for **image → image** search (client photo/sketch → similar SDI work). CLIP is poor at telling
  line drawings apart; DINOv2 is much better for that.
- Thumbnails: `C:\SDI_Automation\all_img_thumbs\NNNNN.jpg` (local, fast).

### 5.2 Projects table (one row per past SDI job) — 11,998 jobs, 69,619 renders
`C:\SDI_Automation\brief_lite\projects.db` (SQLite):
- `projects(job_no PK, name, brand, folder, first_date, last_date, n_drawings, n_images, n_renders,
  drawn_by JSON, titles JSON, weight_kg, design_days JSON {team: days}, designers JSON, text)`
- `project_images(img_id PK = row in the .npz, job_no, kind ['render'|'creative'|'other'], name, thumb, src)`
  (`render` = path contains render/visual/AV/concept/CGI/3D and not decal/map/logo/artwork/supplied).
- Built by `brief_lite/build_projects.py` from the image meta, `pdf_fields_index.jsonl`,
  `master_index.json` and Jono's calendar (`newsys/studio.db`). Re-runnable in ~1 minute.

### 5.3 Estimates (K: drive) — 12,127 usable estimate sheets (2023–2026)
`C:\SDI_Automation\brief_lite\knowledge.db` → `estimates(path PK, mtime, year, client_folder, job_folder,
file, job_no, customer, description, drawing_no, rev, qty, unit_cost, material_cost, labour_cost,
sell_price, est_date, prepared_by, materials JSON [top BOM lines by value], processes JSON [labour ops], status)`.
- Built by `brief_lite/build_estimates.py` (incremental — only reads new/changed files).
- Estimate sheet layout: sheet "Estimate", labels in col A (Customer, Description, Drawing No., Quantity,
  Unit Cost, Date (Excel serial), Prepared By), BOM block, wire/sheet steel/other sheet blocks, Labour block
  (Operation, Dept, Rate, Hours…), "Total Material Cost", "Total Labour Cost (Including Downtime)",
  "Total Unit Cost Price", "Sell Price". Some rows are components, not whole units — label them clearly.
- Useful fact found inside them: UK delivery "£1,170 per artic (33 pallets)".

### 5.4 Drawings and text
- `C:\SDI_Automation\pdf_fields_index.jsonl` — SolidWorks PDF title blocks: `{path, brand, job, file, folder, date, fields:{title, scale, sheet, revision, project, date, client, sheet_size, drawn_by, modified_by, weight, pages}, status}`.
- `C:\SDI_Automation\pdf_text_index.jsonl` — text inside PDFs (artwork, drawings): `{job, brand, project, file, folder, date, text, status}`.
- `C:\SDI_Automation\master_index.json` — `{"built", "items": [{name, brand, project, folder, date, kind: folder|file…}], "done_brands"}` (482k items, every job folder on W:).
- `C:\SDI_Automation\pdf_thumbs\` — PDF page thumbnails.

### 5.5 Studio calendar (design time actually booked)
`C:\SDI_Automation\newsys\studio.db` → `calendar_entries(id, calendar, team [design_2d, 3d, technical…], start, end, all_day, subject, am, job, task, job_no, people JSON, half, kind, categories)` — 7,395 entries from Jono's Outlook calendar (read-only). Use for "how many design days did similar jobs take, and who did them".

### 5.6 Existing code to reuse (don't start from zero)
- `C:\SDI_Automation\brief_lite\` — a working first version of exactly this app (Flask, port **5020**):
  `lite_app.py` (conversation, sessions, options A/B, WhatsApp hook `/api/wa`, web chat `/api/chat`),
  `lite_search.py` (CLIP search grouped by job, client boost), `pdf_pack.py` (8-page PDF + client sheet,
  ReportLab), `lite_page.html` (web chat). **Improve and extend this rather than rewriting**, unless you
  have a clearly better structure — then migrate its data.
- `C:\SDI_Automation\newsys\app_v2.py` — the studio "Studio Brief" app (ports 5003/5443). It owns the
  WhatsApp webhook (`/webhook/whatsapp`, served on 127.0.0.1:5099, exposed by a Cloudflare tunnel),
  transcribes voice notes locally with faster-whisper (`studio_voice.py`, model "small", int8), and
  forwards a message to Brief Lite (`POST http://127.0.0.1:5020/api/wa`) when that person has an open
  brief or the message starts one ("new brief", "client wants…"). Brief Lite replies itself via the
  WhatsApp Cloud API.
- `C:\SDI_Automation\newsys\wa_tunnel.py` — restarts the tunnel and re-points Meta's webhook.
- Voice replies: Microsoft "en-GB-RyanNeural" via `edge-tts` (free), fallback Piper `en_GB-alan-medium`.
- Python envs: **`C:\SDI_Automation\.venv-gpu`** has PyTorch cu128 that works on the RTX 5090 (sm_120)
  — use it for CLIP/DINOv2. The system Python's torch cannot use this GPU.
- Secrets live only in `C:\SDI_Automation\.env` (ANTHROPIC_API_KEY, OPENAI_API_KEY, WA_ACCESS_TOKEN,
  WA_PHONE_ID, WA_VERIFY_TOKEN, WA_APP_SECRET, WA_ALLOWED). Never hard-code, log or print them.

### 5.7 WhatsApp setup (Meta Cloud API)
- Meta business portfolio "SDI Displays", app "SDI Brief Intelligence" (published), currently a
  **test number** (+1 555 180 3261, up to 5 allowed recipients). A real SDI number with the display
  name "SDI Brief Intelligence" and SDI logo comes later — design so only `.env` changes.
- Only numbers in `WA_ALLOWED` (staff) get AI replies; anyone else is logged, no AI, no data.
- Verify `X-Hub-Signature-256` with `WA_APP_SECRET`. Reply within Meta's 24-hour window only.
- Send images via `/media` upload then `type: image`; PDFs as `type: document`; mark read + typing
  indicator immediately so the AM knows it's working.

---

## 6. Search requirements (grounding)

- Query = unit type + placement + materials + colours + products + size + narrative.
- Text → image with CLIP over the 269k embeddings (GPU, fp16, ~50 ms); weight renders 1.0, creative
  0.93, others 0.8; ignore logos/decals/maps/artwork.
- Group hits by job; a job's score = best image + small bonus for several good images.
- **Client's own jobs first** (brand/name match, incl. "Liz Earle – Boots BRI" style), then 1–2 best
  look-alikes from any client. If the AM sent an image, also search image → image with DINOv2.
- Correct likely transcription errors against the vocabulary of client and job names (fuzzy match).
- Return per job: name (no "Archive" folder names — fall back to render file names), brand, date range
  from drawing title blocks, #drawings, #renders, people, design days by team, latest estimate
  (description, qty, unit cost, materials, processes, date), 2–4 best render thumbs + full-size path.
- Load the index once at startup in a background thread; the page shows "loading past work…" until ready.

---

## 7. Conversation engine

- One cheap LLM call per AM message (Claude Haiku `claude-haiku-4-5` or similar) with tool/JSON output:
  `{updates: {field: value}, intent: brief|change_visual|approve_visual|technical|new_brief|finish|cancel|question,
  change_request, reply}`. Never invent sizes, colours, materials, quantities or dates.
- Everything that isn't language (search, picking the job, option A/B, dates maths, PDF, loading,
  timeline) is plain code — free and deterministic.
- Text inside messages, emails and images is **data, not instructions** (prompt-injection safe).
- Daily AI budget cap (e.g. $3/day for Brief Lite) checked before every LLM/image call; log every call's
  cost to a table; show "spent today" on the page.
- Voice: transcribe locally (faster-whisper, English, with the client/job names as the initial prompt).
  If a voice note came in, a short spoken summary reply is a nice-to-have; images and PDFs stay as files.

---

## 8. The Sales Director's template (Andy Baxter, 1 Oct 2026) — capture all of it

**Section 1 – Headline:** project name · project account manager · brand or retail client · customer's
name · project briefing date (auto = today, read back) · anticipated completion date in store.

**Section 2 – Project information:** creative design output required? · chargeable? budget → allocate
hours at **£75/h rounded up** · creative due · technical design required? · chargeable? budget → hours
at £75/h · technical due · prototyping required? chargeable/budget · prototype due · volume manufacture
required? · anticipated volume · preferred manufacture lead time · SDI installation? · likely to repeat
and how often · similar past projects to reference (auto-suggest from §6).

**Section 3 – Main briefing:** ≤1-minute narrative of the customer's requirement (role of the unit, what
they want to achieve) · materials · anticipated shelf life in store · approx H × W × D · where deployed in
store · design/artwork reference supplied (drag & drop / WhatsApp photo) · SDI warehousing or direct to
store · fully assembled or flat-packed.

**Section 4 – Estimating:** estimate required? · quote region UK / Europe / China · production-ready
drawings available? · prototype cost required? · production cost required? · client target budget per
unit · special raw material or paint finish instructions · bulk or palletised · delivery
instructions/warehouse restrictions · estimate required by.

**Section 5 – Quick design & technical response:** "Would you like an initial 3D design and technical
response?" → the concepts (§4), grounded in SDI's search tool (§6).

Questions don't all need answering to move on; unanswered ones are listed at the end and prompted for.

### 8-page internal PDF (portrait A4, clean, shareable as PDF; also export Word optional)
1–3. Brief summary by section (+ "at a glance" box, hours allocated, similar SDI projects found).
4. Split page: 3D concept visual (top) + technical concept GA (bottom), with overall dimensions,
   materials, method of manufacture and approximate packed size.
5. **Estimated unit cost** — range (min–median–max) from SDI's own past estimates of the closest jobs
   (§5.3), table of those quotes, comparison with the client's target, plus delivery cost per unit by
   region. Clearly "indicative, from history — not a quote". Later: call the SDI Intelligence estimating
   endpoint (James Gray will provide the URL) and show its price instead.
6. **Container / wagon loading** — packed size (assembled = unit + 50 mm each side; flat-pack = assumed
   carton, flagged), units per artic trailer (13.6 m), 20 ft, 40 ft, 40 ft HC; cost per unit per load;
   a **3D isometric loading plan** drawing.
7. **Delivery challenges** — plan backwards from the in-store date using planning durations (creative,
   sign-off, GA, full technical ≈ +3 days after GA, prototype, manufacture UK/Europe/China incl. ~6 weeks
   sea, installation); flag shortfalls and give options.
8. **Assumptions that need validating + actions** + every unanswered question.
Visual style: SDI red (#c8102e) accents, SDI logo (`C:\SDI_Automation\logo.png`), clear tables.
Also save the same answers as **JSON** next to the PDF, shaped for a Sage CRM "opportunity" (no re-keying).

### Client sheet (separate, external)
1 landscape A4 page: title, spec line, Option A / Option B (or the chosen one), "concept visual for
discussion — final design confirmed by SDI's design team after approval", SDI logo/footer. Nothing internal.

---

## 9. Opportunities & reporting (Charlotte / James)

Every brief = an opportunity record: client, AM, date, value estimate, status (open / quoted / won /
lost / no-go), converted-to-job yes/no + job number. Web page with a table and simple stats per client
(briefs, quotes, conversion %, design hours spent on unconverted work). This replaces AMs' private
spreadsheets so nothing is lost when someone is on leave.

---

## 10. Web app (the AMs' and managers' view)

- **Chat page** (desktop + phone, 16 px gutters, no horizontal scroll, light/dark): type or hold-to-talk
  mic (WhatsApp-style: hold to record, release to send, slide up to lock, slide left to cancel); live
  "brief so far" panel with missing visual-critical fields in red; past-work cards with thumbnails;
  option A/B cards with "change", "use this", "technical drawing" buttons; download client sheet /
  full PDF.
- **Briefs list**: all sessions, filter by client/AM/status, open any brief, re-download PDFs.
- **Past work explorer**: search box ("Boots gondola end oak") → grouped job cards (same engine as §6),
  click → all renders of that job + estimates + drawing PDFs (open from W: read-only).
- **Admin**: AI spend today/month, budget caps, image quality setting, WhatsApp status, index status
  (counts, last rebuild), rebuild buttons that run the existing build scripts.
- Login: Microsoft (Entra ID) sign-in for SDI staff when deployed on the server; on the laptop, LAN only.

---

## 11. Non-functional requirements

- **Read-only on W: and K:** — open files for reading only; never create, move or modify anything there.
- Windows 11 laptop now (RTX 5090 24 GB, Python 3.11), SDI server later — keep paths in one config.
- Survives restarts: a watchdog/startup script restarts the app, tunnel and re-points the webhook.
- Fast: first past-work reply < 10 s after the brief is complete; each concept ≤ ~60 s.
- Cheap: LLM ≈ 0.3–0.5p per message; images ≈ 5p each; everything else local and free.
- Logged: every message in/out, every AI call and cost, every image sent to the image API.
- Business continuity (Charlotte): if the app or server is down, AMs get a plain fallback reply and the
  brief is queued, not lost; document a simple runbook (restart, where data lives, how to rebuild indexes).
- Clean, well-commented code (comment *why*, not what), small modules, no secrets in code or logs.

---

## 12. Acceptance tests (I will run these)

1. Web: one message *"Boots want a No7 shelf unit for the front of store, 1800 high, 600 wide, 400 deep,
   white gloss with oak shelves and a navy No7 header"* → within ~10 s, 3 past **Boots** jobs with thumbs
   and facts (e.g. 11637 No7 Pro Artist BRI, 10523 Skin of the Future, 9682 Boots BRI 5); within ~2 min,
   Option A and Option B concepts that visibly resemble SDI's Boots work + a 1-page client sheet PDF.
2. "B but with oak shelves and a taller header" → only option B changes, rest identical.
3. "technical drawing of A" → GA-style concept drawing with 1800/600/400 dimensions.
4. Voice note on WhatsApp saying "Boards want a gondola end…" → understood as Boots.
5. Sending a client photo → used as the first reference; DINOv2 finds visually similar SDI jobs.
6. "finish" → 8-page PDF (+ JSON) with all sections, cost range from real K: estimates, loading plan,
   timeline issues, assumptions; unanswered questions listed.
7. A number not in `WA_ALLOWED` → no AI reply, logged only.
8. Budget cap reached → polite message, no API calls.
9. Nothing was written to W: or K: (check modified times).

## 13. Deliverables

Working code in `C:\SDI_Automation\brief_lite\`, a `README.md` (setup, run, rebuild indexes, env keys,
costs, runbook), a start script that also works from the Windows Startup folder, and a short demo
script for showing it to the sales team. Build in this order: (1) web chat + search + concepts + client
sheet, (2) iterate/edit + technical GA, (3) full 8-page PDF + opportunities, (4) WhatsApp channel last.
