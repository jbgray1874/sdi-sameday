# SDI Live (SameDay): using it, testing it, updating it

> **SDI Live** (8 November 2026): this tool is now called SDI Live wherever people see it - the page, the phone app and its icon, the app portal tile and the emails. *SameDay* stays its internal name: the `SDISameDay` service, `C:\SDI_Automation`, this repository, the `/sameday/` address the phone app and App Proxy use, and K:'s `SDI Same Day Intelligence` folder where the picture index lands.


This guide is for whoever uses, tests or looks after SameDay. `ARCHITECTURE.md` explains how the code works.

Written 4 November 2026. It describes the changes on branch `claude/inspiring-planck-8juriz`: the brief in any order, and the live voice in noisy rooms.

## 1. One app, opened four ways

There is one SameDay. It runs on the server (10.0.0.5, port 5020), and every way in opens the same page:

| Way in | Address | Works from |
|---|---|---|
| Phone (app portal tile, or the home-screen icon) | SDI Intelligence's own https address, at `/sameday/` | Anywhere, signed in with your SDI account |
| App portal tile or intranet menu on a laptop | The same `/sameday/` on whichever portal address you're using | The same |
| Directly | `http://10.0.0.5:5020` | The office network, or the VPN (team code) |

**On the phone (4 November 2026).** SDI Intelligence is already published through App Proxy, so it reaches phones over https with Microsoft sign-in. It carries SameDay at `/sameday/` on that same address (`sameday_proxy.py` in ClaudeVision). That needs no new Entra app, and over https the microphone works. Signed in with Microsoft, you aren't asked for the team code. The live voice goes from the phone straight to OpenAI, the same as in the office.

All the work happens on the server, so every way in has the same functions: the brief, the renders, the GA, the PDFs, the web look-ups, the past-job look-ups and the AI spend cap. The voice uses the same model everywhere.

These are the only differences:

| | https (the portal's address, on a phone or a laptop) | http (`10.0.0.5`) |
|---|---|---|
| Typed brief, files, renders, GA, PDFs | Yes | Yes |
| Live voice | Yes | No: browsers only allow the microphone on https |
| Add to the home screen as an app | Yes. Safari: Share, then Add to Home Screen. Chrome: menu, then Install app. | No |
| Listening | Phone: tuned for a phone held close (`near_field`). Laptop: tuned for a laptop mic (`far_field`). | |

### Not working on the server yet (the same on every way in)

- **The picture index.** `all_img_index.npz` was not in the K: folder, so the picture-by-picture matching Muhammad's laptop does is off on the server. Since 5 November the server does it another way: the brief's words find the likely past jobs, and Claude looks at one render of each, side by side on one numbered sheet, and scores how much each looks like the unit being briefed. The ones that look like it lead, and ones that plainly don't are left out of the render's references. It costs a fraction of a penny per render and adds a few seconds. Copy it from Muhammad's laptop (`C:\SDI_Automation\`) to the server's `C:\SDI_Automation\`, with `brief_lite\projects.db` from the same day, then restart SDISameDay.

W:, S: and K: themselves are fine: SameDay maps them for itself at start, and `Update-SameDay.ps1` says whether it can read each one. It does not search the drives file by file during a call. It searches index files made from them: `projects.db` (the jobs on W:), `knowledge.db` (the estimates on K:) and the picture index. `Update-SameDay.ps1` and `Check-SameDay-Call.ps1` both say how many past jobs it can find, whether the estimates are there, and whether picture matching is on.

## 2. Using it

1. **Open it** and type the team access code once. The browser remembers it for 90 days.
2. **Pick your name** (or add it). Your briefs stay under your name, and you can go back to any of them later.
   Signed in through the app portal or the phone, it opens in your own name without asking. **+ New chat** always starts in
   your own space, and the voice greets whoever is signed in, even inside someone else's chat. Opened on the office
   `http://` address, where nobody is signed in, it goes to the same page on the https address, so Microsoft 365 says
   who you are. Only on the server itself does it ask you to pick a name.
3. **Type or talk:**
   - **Typing:** describe the brief in the box and press the **red arrow** (Send). Each message gets one short reply and one question. Tap a suggested answer, or type your own.
   - **Talking:** press **Talk live** (the grey button with the sound bars) and just talk, as you would on a call.
     - You can talk over it, and it stops at once.
     - **Pause** lets you speak to someone else, then carry on.
     - **End** finishes the call. Everything stays in the chat.
     - While a render is being drawn, the mic is off until the picture is on screen. **Stop** cancels it.
   - **Files:** the **paperclip** adds photos, sketches, PDFs or drawings. SameDay reads them and uses them.
4. **New chat** starts a new brief. A different client also starts a new brief by itself.

You don't have to start with the red arrow. Start whichever way suits you: type and press the red arrow, press Talk live, or drop in a file.

## 3. The brief in any order

The questions follow the usual order, but nothing forces it. Everything you say is recorded when you say it, and SameDay only asks for what is still missing.

| Say this, at any point | What happens |
|---|---|
| Nothing about which pack | It asks once. If you carry on about the job, it does **both** packs (marked "assumed") and doesn't ask again. |
| "Actually just the client pack" / "I don't need the internal brief" | The pack changes. Only mentioning a pack ("add that to the client sheet") changes nothing. |
| "Make a render" (before the questions are done) | It draws now. Anything it has to guess is marked "assumed", and you change it on the picture. |
| "Let's do the internal questions first" | The SDI internal-brief questions come now. The render waits. |
| "Back to the render" | It carries on with the render where it left off |
| "Change the header to navy" | A new option (B, C…) is made from the one on screen. The earlier ones stay. |
| "Go back to option A and make the shelves oak" | The new option is made from A |
| "Something completely different" | A whole new design |
| "Something new" / "forget that one" / "none of those", while it is checking a past job | It drops the past job at once, and doesn't suggest it again unless you name one. "No" to a suggested job offers the other matches once, then lets it go. |
| "Build the brief PDF now" | The 8-page PDF is made from what is known, with a list of what is still missing |
| A date, budget, quantity or new size, early or late | Recorded straight away. The newest answer wins. |

Some checks stay, because they stop wrong pictures:

- A past job you name is read back to you ("Do you mean 12148, Rollershutter Forecourt Bunker?") before it is followed.
- A size that doesn't look right for the unit is said back once. Answer it, or say "just draw it".
- The voice can never choose a pack you didn't say.

## 4. In a noisy room

- **Hearing names.** The transcriber is told this brief's own names: the client, the store, the unit, the products, the people and past job numbers. It is updated during the call as more are given.
- **Noisy mode.** After three bits of noise in a minute, the call switches to "Noisy room": only a clear, close voice counts. The louder the room, the higher the bar.
- **Very noisy.** If noise still gets through, it goes stricter and suggests once that you **hold the orb** while you talk. Then only what you say while holding it is heard.
- **Quiet again.** Each level steps back down after two quiet minutes.
- **Other voices.** It is told to ignore other voices, a TV or a phone call, and to ask again rather than note something it half-heard.

When someone says "it didn't hear me", look in `brief_lite\rt_drops.log` on the server. It lists every line the call threw away, and why.

## 5. Testing the 4 November changes

### Put it on the server (from the laptop, VPN on)

The server has no git, so this runs on the laptop, as Ship-It does. SameDay goes first, then Ship-It:

```
cd C:\ClaudeVision
git pull jbg claude/app-portal-main-2026
.\sdi-intelligence-backend\deploy\Update-SameDay.ps1 -Branch claude/inspiring-planck-8juriz
.\sdi-intelligence-backend\deploy\Ship-It.ps1
```

Update-SameDay ends with "SameDay is running the new code". Ship-It ends green at 4b. The first time, a GitHub sign-in may open: sign in as jbgray1874.

### Script A: talking, on the web app (a laptop, about 15 minutes)

Use the app portal's **https** address, the same one the phone uses. On the office `http://` address the browser won't give it the microphone. Open SameDay, pick your name, press **+ New chat**, then press **Talk** and allow the microphone.

| # | Say | It should |
|---|---|---|
| 1 | "Hi, it's Tesco. They want a gondola end for Milwaukee M18 drills." | Say it back, and ask one question |
| 2 | "Both packs, please." | Take both and move on. It never asks the pack again. |
| 3 | "Let's do the brief questions first." | Switch to the internal questions |
| 4 | "Deadline's Friday the 20th of November, budget five thousand pounds, fifty units." | Take all three, and ask something it doesn't have yet |
| 5 | "Back to the render. 1800 high, 1200 wide, 600 deep, black and red, with a lit header." | Read the size back in that order, then ask: past job, or something new? |
| 6 | "Did we do anything like this for Milwaukee before?" | Answer in words: job number, what it was, when. (If it finds nothing, check `can_read` W: in section 7.) |
| 7 | "Something new. Draw it." | Say it's drawing. The mic pauses and the render appears in about a minute. |
| 8 | "Make the header bigger." | Make Option B. A stays on screen. |
| 9 | "Go back to A and make the shelves oak." | Make Option C from A, not from B |
| 10 | "C's the one. Finalise it." | Make C's GA and the client sheet |
| 11 | "Build the brief PDF now." | Make the 8-page PDF, with a list of what's still missing |
| 12 | "That's all, thanks." | Say goodbye. Everything stays in the chat. |

**Passes if:** it never asked the pack twice, never re-asked anything you'd said, read the size back right, and never spoke while you were mid-sentence.

### Script B: talking, on a phone (about 10 minutes)

Do this outside the office, on mobile data. Open the app portal on the phone, tap SameDay, then **Open**.

- It should open signed in, with no team code.
- Pick your name, press **+ New chat**, then press **Talk** (yellow) and allow the microphone.

| # | Say | It should |
|---|---|---|
| 1 | "Hi, it's Boots. They want a counter unit for No7 serums." | Say it back, and ask one question (the pack, once) |
| 2 | Ignore that: "About 400 high, 300 wide, 250 deep, navy and white." | Not ask the pack again. Read the size back right. |
| 3 | "Let's do the studio questions first." | Switch to the internal questions |
| 4 | "Deadline's the 20th of November, 200 units." | Take both, and ask the next one |
| 5 | "OK, back to the render. Just draw it." | Say it's drawing. The mic pauses and the render appears. |
| 6 | "Make the header lit." | Make Option B |
| 6b | Change direction: "Actually, make it a wall bay, not a counter unit." | Say it back ("So a wall bay now, not the counter unit"), work out the size again, and offer a fresh design rather than changing B |
| 7 | Put a radio or TV on, or get someone to talk nearby. Keep going: "and add a tester tray at the front." | Answer you, not them. "Noisy room" appears. |
| 8 | If it's very noisy: hold the orb, say "add a tester tray", and let go | Only hear you while you hold it |
| 8b | Talk over it while it's speaking. Then give a long answer with a pause in the middle ("It needs... a lit header and, um, four shelves"). | Stop at once when you talk. Never start speaking while you're mid-sentence, and wait out the pause. |
| 9 | "That's the one. Finalise B." | Make B's GA and the client sheet |
| 10 | "That's all, thanks." | Say goodbye. Everything stays in the chat. |

Then add it to your home screen (Safari: Share, then Add to Home Screen) and open it from the icon. It should open SameDay.

**Passes if:** it opened without the team code, never answered the radio or the other person, never asked anything twice, and everything you said shows in the Brief panel.

**If something's wrong:** note the time and what you said. The chat keeps every line, and on the server `C:\SDI_Automation\brief_lite\rt_drops.log` shows what the call threw away, and why.

### After testing

If it is good, the branch is merged into main, and from then on the update runs without `-Branch`. If it is not, put the old code back. The update keeps it in `C:\SDI_Automation\backups\before-update-...`, and its last lines give the exact command.

## 6. Updating the server

Always update the server with `Update-SameDay.ps1`, run from the laptop (section 5; without `-Branch` it takes main).

- **What it does.** It keeps the code it replaces, never touches the keys, chats, uploads or spend log, restarts only SameDay and SDI Craft, and checks that SameDay reports the new version.
- **Not `UPDATE_SAME_DAY.bat`.** That is Muhammad's laptop update, and it must not be used on the server. It copies K: (older code) over the server's own files, and whatever K: holds of Craft's log (`craft\craft.db`) and the budget settings (`studio_data\`) goes over the server's too. It also starts a second SameDay outside the Windows service, which fights the service for port 5020.
- **Muhammad's changes on K:** reach this repository through `Publish-SameDay-Code.ps1` (in ClaudeVision, run from the laptop). Each copy of K: goes on the `from-k` branch, and only what changed on K: is merged into main. So a copy of K: never undoes work made here. If both changed the same lines, it stops and names the files.

## 7. When something breaks

| Symptom | Look at |
|---|---|
| The page won't load | On the server: `Get-Service SDISameDay`, and the end of `C:\SDI_Automation\logs\SDISameDay.log` |
| The team code is refused | Check it's the current code. The cookie fix of 4 November is in this branch. |
| Talk live won't start | Is the page `https://` (the portal's address), or the Chrome switch on? Is the OpenAI key in date, and is the day's budget left? The page says which. |
| On the phone it says "SameDay isn't answering" | SameDay is down on the server. SDI Intelligence is up, but `SDISameDay` isn't. |
| On the phone the page opens but nothing works | The server's SameDay is older than this branch, so it doesn't know `/sameday/`. Run `Update-SameDay.ps1`. |
| It didn't hear something | `C:\SDI_Automation\brief_lite\rt_drops.log` |
| A render is slow when others are drawing too | Up to 4 pictures are drawn at once across the server (`LITE_IMAGE_SLOTS` in `.env`); each has a firm limit of 170 seconds (`LITE_IMAGE_SECONDS`). Different people's chats never wait for each other. |
| It seemed to freeze on a call | After 5 minutes waiting for a render the call carries on by itself and says so. `Check-SameDay-Call.ps1` shows any turn that took too long ("took …s") or waited behind another render. |
| No past jobs found | Run `Check-SameDay-Call.ps1`. Section 1 says how many past jobs SameDay can find and lists the index files on the server. "NONE" means `projects.db` is missing from `C:\SDI_Automation\brief_lite`. Before 4 November the missing picture index stopped every look-up; `Update-SameDay.ps1` fixes that. |
| Spend looks wrong | `ai_calls` in `lite.db`. The live voice is counted at `gpt-realtime`'s price until its own is set in `.env` as `LITE_RT_PRICE`. |

Tests for the 4 November changes run offline, with no keys and no drives:

```
python -m pytest tests -q
```

They need flask, numpy and reportlab, plus node for the page checks.
