import sqlite3, json
c = sqlite3.connect(r"C:\SDI_Automation\brief_lite\lite.db")
r = c.execute("SELECT refs FROM sessions WHERE number='web:tester' ORDER BY updated DESC LIMIT 1").fetchone()
for x in json.loads(r[0])[:4]:
    print(x["job_no"], x["name"], "|", [i["name"] for i in x["images"][:2]])
    print("   ", [i["thumb"] for i in x["images"][:2]])
