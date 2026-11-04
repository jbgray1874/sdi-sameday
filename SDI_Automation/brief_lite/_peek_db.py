import sqlite3, sys
c = sqlite3.connect(r"C:\SDI_Automation\brief_lite\knowledge.db")
for r in c.execute("SELECT status, count(*) FROM estimates GROUP BY 1"):
    print(r)
q = ("SELECT job_no, customer, description, qty, round(unit_cost,2), round(material_cost,2), round(labour_cost,2), "
     "est_date, prepared_by, substr(materials,1,160), substr(processes,1,120) FROM estimates WHERE status='ok' LIMIT ?")
for r in c.execute(q, (int(sys.argv[1]) if len(sys.argv) > 1 else 6,)):
    print(r)
for r in c.execute("SELECT file, status FROM estimates WHERE status!='ok' LIMIT 5"):
    print(r)
