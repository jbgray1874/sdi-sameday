"""Replay a pretend AM briefing through the web chat and print what Brief Lite says back."""
import json, sys, time, requests
msgs = sys.argv[1:] or [
    "New brief - Boots want a No7 shelf unit for the front of store, 1800 high 600 wide 400 deep, white gloss with oak shelves and a navy No7 header",
    "Finish - give me the full brief PDF",
    "Project is No7 Front of Store, I'm Test AM, contact is Sarah at Boots, in store 20 Nov. Creative yes, chargeable, budget 1500, due 16 Oct",
    "skip",
]
sid = None
for i, m in enumerate(msgs):
    turn = requests.post("http://127.0.0.1:5020/api/chat", json={"text": m, "new": i == 0, "who": "tester2"}, timeout=60).json()["turn"]
    while True:
        r = requests.get(f"http://127.0.0.1:5020/api/turn/{turn}", timeout=60).json()
        if r["done"]:
            break
        time.sleep(1.5)
    print(f"\n>>> AM: {m[:110]}")
    for x in r["replies"]:
        print("   BOT:", (x.get("text") or f"[{x['type']}/{x.get('role')}] {x.get('caption', '')[:170]}"))
print("\nBRIEF keys:", sorted(r["brief"]))
