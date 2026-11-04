# SDI SameDay: using it, testing it, updating it

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

- **Past SDI jobs from W:.** The server runs SameDay as a Windows service, and a service can't see mapped drives. The `W:` and `S:` paths in `lite_app.py` need their full `\\server\share` names, so until Muhammad changes them, past-job look-ups come back empty.
- **The picture index.** `all_img_index.npz` was not in the K: folder, so the picture search is off on the server.

Both are listed for Muhammad in `SAMEDAY_GO_LIVE.html` part D.

## 2. Using it

1. **Open it** and type the team access code once. The browser remembers it for 90 days.
2. **Pick your name** (or add it). Your briefs stay under your name, and you can go back to any of them later.
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

### Put the branch on the server

On the laptop, with the VPN on:

```
cd C:\ClaudeVision
git pull jbg claude/app-portal-main-2026
Copy-Item C:\ClaudeVision\sdi-intelligence-backend\deploy\Update-SameDay.ps1 \\10.0.0.5\c$\Tools\
```

On the server, in PowerShell opened as administrator. The first time, a GitHub sign-in opens: sign in as jbgray1874.

```
powershell -ExecutionPolicy Bypass -File C:\Tools\Update-SameDay.ps1 -Branch claude/inspiring-planck-8juriz
```

It ends with "SameDay is running the new code".

### Let the voice work on the http address (the test PC only)

In Chrome on the PC you test from:

1. Open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`.
2. Add `http://10.0.0.5:5020` and set it to Enabled.
3. Relaunch Chrome.

This changes only that browser. It isn't needed on the portal's https address, where the microphone already works.

### What to try

Typed:

- [ ] "Tesco want a gondola end for Milwaukee drills, make a render". It should draw, with no pack question first.
- [ ] Start a brief and answer the pack question with something about the job instead. It should not ask the pack again.
- [ ] Mid-brief: "let's do the internal questions first", answer two, then "back to the render".
- [ ] With a render on screen: "change the header to navy", then "go back to option A and make the shelves oak".
- [ ] Before finalising: "build the brief PDF now".
- [ ] "Actually just the client pack".

Voice (Talk live):

- [ ] The same as above, out loud, in any order.
- [ ] Somewhere noisy, or with a radio or a colleague talking nearby. Look for "Noisy room" on screen. It should not answer the other voices.
- [ ] Very noisy: it should suggest holding the orb. Hold it, talk, let go.
- [ ] Say the client and a job number. It should read them back correctly.

On the phone:

- [ ] Open the app portal on the phone (outside the office, on mobile data), then SameDay. It should open signed in, with no team code.
- [ ] Talk live on the phone, then Add to Home Screen and open it from the icon.

Note anything wrong with the time and what was said. The chat keeps everything, and `rt_drops.log` shows what the call threw away.

### After testing

If it is good, the branch is merged into main, and from then on the update runs without `-Branch`. If it is not, put the old code back. The update keeps it in `C:\SDI_Automation\backups\before-update-...`, and its last lines give the exact command.

## 6. Updating the server

Always use `Update-SameDay.ps1` on the server (section 5, without `-Branch` for main).

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
| No past jobs found | The W: change (section 1), not yet made |
| Spend looks wrong | `ai_calls` in `lite.db`. The live voice is counted at `gpt-realtime`'s price until its own is set in `.env` as `LITE_RT_PRICE`. |

Tests for the 4 November changes run offline, with no keys and no drives:

```
python -m pytest tests -q
```

They need flask, numpy and reportlab, plus node for the page checks.
