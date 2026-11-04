"""The Craft Memory page and its API, added to a Flask app with one line: craft_web.add(app, "showroom", "SDI Same Day Intelligence", "/pwa/mark.png")."""
import csv, io, json, os

from flask import Response, jsonify, request

import craft

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "craft_page.html")


def add(app, tool, tool_name, mark_url, who_of=lambda js: js.get("who") or "", extra=None):
    """extra: optional callable returning a dict merged into the summary (a tool's own section, e.g. SDI Recall's
    "what the library is missing"). The page shows that section only when it is there."""
    @app.route("/craft")
    def craft_page():
        """The learning lives on its own site now - SDI Craft, port 5030 - not on the tools' pages."""
        from flask import redirect
        host = (request.host or "localhost").split(":")[0]
        return redirect(f"http://{host}:5030/t/{tool}/")

    @app.route("/api/craft/summary")
    def craft_summary():
        d = craft.stats()
        if extra:
            try:
                d.update(extra() or {})
            except Exception as e:
                print("craft_web extra:", e)
        return jsonify(d)

    @app.route("/api/craft/reason", methods=["POST"])
    def craft_reason():
        js = request.get_json(silent=True) or {}
        eid = craft.reason(js.get("ref") or "", chips=js.get("chips") or [], text=js.get("text") or "", kind=js.get("kind"),
                           by=who_of(js))
        return jsonify({"ok": bool(eid)})

    @app.route("/api/craft/event", methods=["POST"])
    def craft_event():
        """Signals only the page sees (a reference struck out, a chip tapped). Same rules: never breaks anything."""
        js = request.get_json(silent=True) or {}
        kind = str(js.get("kind") or "")[:40]
        if kind not in ("reference_rejected", "said_reason", "viewed", "question_feedback", "question_missing", "fact_wrong", "render_feedback"):
            return jsonify({"ok": False}), 400
        craft.log(tool, kind, who_of(js), js.get("ref") or "", js.get("context") or {}, js.get("data") or {})
        return jsonify({"ok": True})

    @app.route("/api/craft/note", methods=["POST"])
    def craft_note():
        """A designer's craft note on a job: what changed from the brief and why (one line and/or chips)."""
        js = request.get_json(silent=True) or {}
        text, chips = (js.get("text") or "").strip()[:600], [c for c in (js.get("chips") or []) if isinstance(c, str)][:8]
        if not (text or chips) or not (js.get("ref") or "").strip():
            return jsonify({"ok": False}), 400
        ctx = js.get("context") or {}
        eid = craft.log(tool, "designer_note", who_of(js), js["ref"], ctx,
                        {"team": js.get("team") or "", "summary": (text or ", ".join(chips))[:160]})
        if eid:
            con = craft.db()
            con.execute("UPDATE events SET chips=?, reason=?, reason_by=? WHERE id=?", (json.dumps(chips), text, who_of(js)[:60], eid))
            con.commit(); con.close()
        return jsonify({"ok": bool(eid)})

    @app.route("/api/craft/optout", methods=["POST"])
    def craft_optout():
        js = request.get_json(silent=True) or {}
        if (js.get("who") or "").strip():
            craft.set_optout(js["who"].strip(), bool(js.get("out", True)))
        return jsonify({"ok": True})

    @app.route("/api/craft/export.csv")
    def craft_export():
        rows = craft.export_rows()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["at", "tool", "kind", "who", "context", "chips", "reason", "data"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=sdi_craft_memory_anonymised.csv"})
