"""Build Andy's PDF from the last test session (adds a few made-up answers so every page has something)."""
import json, sqlite3, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_app, pdf_pack
con = sqlite3.connect(lite_app.DB)
con.row_factory = sqlite3.Row
r = dict(con.execute("SELECT * FROM sessions WHERE number='web:tester' ORDER BY updated DESC LIMIT 1").fetchone())
for k in ("brief", "refs", "visuals", "client_images"):
    r[k] = json.loads(r[k] or "[]")
r["brief"].update({"project_name": "No7 Front of Store FSDU (TEST)", "account_manager": "Test AM", "instore_date": "Fri 20 Nov 2026",
                   "volume_qty": "250", "region": "UK", "assembled": "flat-packed", "creative_required": "yes",
                   "creative_chargeable": "yes, budget £1,500", "target_unit_cost": "£180"})
print(pdf_pack.build(r, lite_app.FIELDS, lite_app.SECTIONS, lite_app.OUT))
