"""
craft_site.py - SDI Craft: the studio's know-how, learnt from the tools, on its own site (port 5030).

Muhammad, 14 Oct 2026: the feedback and learning shouldn't sit on the tools' own pages. Each tool (SDI Same Day Intelligence, SDI Debrief Intelligence,
SDI Recall) only CAPTURES - quietly, as people work - into craft\\craft.db. This site is where it's read: one tab per tool,
plus what's come out of meetings, and the exports that later train the tools to be better.

    http://localhost:5030          (office: http://LC-328802:5030)

Read-only over the same SQLite file the tools write to. No AI credit, nothing leaves C:, nothing is written to W: or K:.
"""
import csv, io, json, os, sys

from flask import Flask, Response, abort, jsonify, redirect, request, send_file

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BASE)
import craft  # noqa: E402

PORT = int(os.environ.get("CRAFT_PORT", "5030"))
TOOLS = {   # id -> (name, mark, where the tool itself lives, what it's for)
    "all":      ("All tools", "/m/sdi.png", None, "everything the tools have learnt, together"),
    "showroom": ("SDI Same Day Intelligence", "/m/showroom.png", "http://{host}:5020", "AMs: which concept is picked, what's changed, and why"),
    "flow":     ("SDI Debrief Intelligence", "/m/flow.svg", "https://{host}:5443", "the studio: who's booked on what, what people ask, craft notes"),
    "library":  ("SDI Recall", "/m/sdi.png", "http://{host}:5000", "designers: what they search for, open and reuse - and what's missing"),
    "meeting":  ("Meetings", "/m/sdi.png", None, "insights from meeting notes - read by Claude, with who said them"),
}
MARKS = {"showroom.png": os.path.join(BASE, "brief_lite", "pwa", "mark.png"), "flow.svg": os.path.join(BASE, "newsys", "flow_mark.svg"),
         "sdi.png": os.path.join(BASE, "logo.png")}
app = Flask(__name__)


def tabs_html(cur):
    return '<nav class="tooltabs">' + "".join(
        f'<a href="/t/{t}/" class="{"on" if t == cur else ""}"><img src="{v[1]}" alt=""><span>{v[0]}</span></a>' for t, v in TOOLS.items()) + "</nav>"


TAB_CSS = """<style>
.tooltabs{max-width:1180px;margin:0 auto 14px;padding:0 clamp(16px,4vw,40px);display:flex;gap:8px;flex-wrap:wrap}
.tooltabs a{display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 14px 0 8px;border:1px solid var(--line);border-radius:20px;background:var(--card);color:var(--ink);text-decoration:none;font-weight:700;font-size:13.5px}
.tooltabs a img{width:26px;height:26px;border-radius:50%}.tooltabs a.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.toolnote{max-width:1180px;margin:-4px auto 10px;padding:0 clamp(16px,4vw,40px);color:var(--muted);font-size:13.5px}
</style>"""


@app.route("/")
def home():
    return redirect("/t/all/")


@app.route("/t/<tool>/")
def tool_page(tool):
    if tool not in TOOLS:
        abort(404)
    name, mark, url, what = TOOLS[tool]
    html = open(os.path.join(HERE, "craft_page.html"), encoding="utf-8").read()
    html = html.replace("__MARK__", mark).replace("__TOOL__", name).replace("<title>Craft Memory</title>", f"<title>SDI Craft · {name}</title>")
    host = (request.host or "localhost").split(":")[0]
    back = f'<a href="{url.format(host=host)}" target="_blank">Open {name} ↗</a>' if url else ""
    # the page's own header link pointed back to the tool it lived in - here it opens the tool instead
    import re
    html = re.sub(r'<a href="/">← Back to [^<]*</a>', back, html, count=1)
    html = html.replace("<b>Craft Memory</b>", "<b>SDI Craft</b>", 1)
    html = html.replace("</header>", "</header>" + tabs_html(tool) + f'<p class="toolnote"><b>{name}</b> - {what}.</p>', 1)
    html = html.replace("</head>", TAB_CSS + "</head>", 1)
    return Response(html, mimetype="text/html")


@app.route("/t/<tool>/api/craft/summary")
def summary(tool):
    if tool not in TOOLS:
        abort(404)
    d = craft.stats(None if tool == "all" else tool)
    if tool in ("library", "all"):
        try:
            import craft_library
            lib = craft_library.summary() or {}
            if lib:
                d.update(lib)
        except Exception as e:
            print("library summary:", e)
    return jsonify(d)


@app.route("/t/<tool>/api/craft/optout", methods=["POST"])
def optout(tool):
    js = request.get_json(silent=True) or {}
    if (js.get("who") or "").strip():
        craft.set_optout(js["who"].strip(), bool(js.get("out", True)))
    return jsonify({"ok": True})


@app.route("/t/<tool>/api/craft/export.csv")
def export(tool):
    """Anonymised rows (P1, P2...) for the KTP report, a paper, and training the tools later."""
    rows = [r for r in craft.export_rows() if tool == "all" or r.get("tool") == tool]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["at", "tool", "kind", "who", "context", "chips", "reason", "data"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=sdi_craft_{tool}_anonymised.csv"})


@app.route("/m/<name>")
def mark(name):
    p = MARKS.get(name)
    if not p or not os.path.exists(p):
        abort(404)
    return send_file(p, max_age=86400)


if __name__ == "__main__":
    import socket
    probe = socket.socket()
    try:
        probe.bind(("0.0.0.0", PORT)); probe.close()
    except OSError:
        print(f"Port {PORT} already in use - SDI Craft is already running.")
        sys.exit(0)
    from waitress import serve
    print(f"SDI Craft on http://localhost:{PORT}  (office: http://LC-328802:{PORT})")
    serve(app, host="0.0.0.0", port=PORT, threads=4)
