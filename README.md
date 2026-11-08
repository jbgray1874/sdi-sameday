# SDI Live (internally: SameDay)

> **SDI Live** (8 November 2026): this tool is now called SDI Live wherever people see it - the page, the phone app and its icon, the app portal tile and the emails. *SameDay* stays its internal name: the `SDISameDay` service, `C:\SDI_Automation`, this repository, the `/sameday/` address the phone app and App Proxy use, and K:'s `SDI Same Day Intelligence` folder where the picture index lands.


Same Day is SDI's tool for the account manager (AM). During or straight after a client call, the AM talks or types the brief. The tool:

- asks the missing questions;
- draws a concept render;
- takes changes as new options (A, B, C…);
- makes a GA drawing and a client sheet from the chosen option;
- makes an internal brief PDF for the studio.

## Run it

| | |
|---|---|
| Entry point | `brief_lite/lite_app.py` (Flask, served by waitress) |
| Port | **5020** (`LITE_PORT`) |
| Python | 3.11+, `pip install -r requirements_full.txt` |
| Start | `python brief_lite/lite_app.py` |
| Keep-alive | `Studio_Brief_Autostart.bat` checks every 5 minutes and restarts it if it is down |

It serves a single page (`lite_page.html`) at `/`. Everything else is under `/api/...`.

## Configuration (`.env` in the repo root, never committed)

| Variable | What it does |
|---|---|
| `OPENAI_API_KEY` | Renders (gpt-image), voice (Realtime), GA images |
| `ANTHROPIC_API_KEY` | Chat, brief checks, render checks, moodboard (Claude) |
| `LITE_ACCESS_CODE` | Team code a user types if they are not signed in |
| `LITE_TRUST_FROM` | Comma-separated IPs of the App Proxy connector. Sign-in headers are trusted only from these IPs. |
| `LITE_USER_HEADERS` | Optional. Header names that carry the signed-in user. The default covers the Entra App Proxy header-SSO names. |
| `LITE_CHAT_MODEL`, `LITE_IMAGE_MODEL`, `LITE_IMAGE_QUALITY`, `LITE_RT_*` | Optional model overrides. The defaults are in `lite_config.py` and `realtime_parts.py`. |

`.env.example` in the deploy folder lists every variable without its value.

## Publishing on SDI Apps (Entra App Proxy)

- **Internal URL:** `http://LC-328802:5020/`, the laptop for now. Use a server once one is available.
- **Pre-authentication:** Microsoft Entra ID. Assign Andy Baxter and Muhammad Yazir to start with.
- **Backend timeout: Long.** A render or GA takes 60–150 s, and the default timeout cuts it off.
- **Single sign-on:** header-based, optional. If the connector sends the user's UPN or name in a header, set `LITE_TRUST_FROM` to the connector IP. The app then skips the team code and shows the user's name at `/api/me`.
- **Browser features:**
  - Voice uses the microphone, so the page must be served over HTTPS. App Proxy already provides HTTPS.
  - Voice uses WebRTC straight to OpenAI, so the browser needs outbound access to `api.openai.com`.

## Files

| File | Role |
|---|---|
| `lite_app.py` | Web server, routes, flow dispatch, render, GA |
| `convo_parts.py` | Flow state machine: pack → render questions → confirm → past/mix/new → render → review → internal questions → done |
| `realtime_parts.py` | Voice tools and instructions for OpenAI Realtime |
| `pdf_pack.py` | Client sheet and internal brief PDF |
| `moodboard.py`, `spaces.py`, `lite_search.py` | Find references (past SDI units, space photos, products) |
| `lite_store.py` / `lite.db` | SQLite store of chats and briefs |
| `knowledge.db`, `client_profiles.json` | Read-only knowledge: past jobs and client profiles |
| `out/` | Generated renders, GAs and PDFs |

The full picture of the app (flow, models, live call, troubleshooting) is in `ARCHITECTURE.md` in the K: folder.

## Data and security

- **No secrets in the repo.** Keys live only in `.env` on the host.
- **Data stays on the host:** chats, renders and PDFs are kept in `lite.db` and `out/`.
- **What goes to the AI providers:** the brief text and the reference images are sent to OpenAI and Anthropic to make each render or answer.
- **Spend cap:** daily AI spend is capped in `studio_data/ai_switch.json`. The current cap is $10 a day.

## Known limits

- It runs on a laptop, so it is offline whenever that laptop is off or off the office network. It needs a server or VM for real use.
- One render runs at a time per chat (`_busy` lock). Each AI call has a timeout of up to 240 s.
