"""
build_estimates.py - Brief Lite's memory of what SDI has quoted before.

Reads every estimate sheet under K:\\Estimating\\Completed\\Manual Estimates
(Year\\Client\\Job\\*.xls / *.xlsx) and keeps the facts a salesperson needs:
customer, what it was, drawing number, quantity, unit cost, material and
labour cost, sell price, date, who priced it and the main materials.

READ ONLY on K: - files are opened for reading and nothing is ever written
there. Everything lands in C:\\SDI_Automation\\brief_lite\\knowledge.db.
Re-running only reads files that are new or changed since last time.
"""
import os, re, sqlite3, sys, time, json
from datetime import datetime, timedelta

ROOT = r"K:\Estimating\Completed\Manual Estimates"
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "knowledge.db")

LABELS = {  # label on the sheet -> field
    "customer": "customer", "description": "description", "drawing no.": "drawing_no", "drawing no": "drawing_no",
    "rev": "rev", "quantity": "qty", "unit cost": "unit_cost", "date": "est_date", "prepared by": "prepared_by",
    "total material cost": "material_cost", "total labour cost (including  downtime)": "labour_cost",
    "total labour cost (including downtime)": "labour_cost", "total labour cost": "labour_cost",
    "total unit cost price": "unit_cost_total", "sell price": "sell_price",
}
SECTION_END = re.compile(r"^(wire|sheet steel|other sheet material|labour|total material cost)$", re.I)


def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS estimates (
        path TEXT PRIMARY KEY, mtime REAL, year TEXT, client_folder TEXT, job_folder TEXT, file TEXT,
        job_no TEXT, customer TEXT, description TEXT, drawing_no TEXT, rev TEXT, qty REAL, unit_cost REAL,
        material_cost REAL, labour_cost REAL, sell_price REAL, est_date TEXT, prepared_by TEXT,
        materials TEXT, processes TEXT, status TEXT)""")
    return con


def rows_xls(path):
    import xlrd
    wb = xlrd.open_workbook(path, on_demand=True)
    names = wb.sheet_names()
    sn = next((n for n in names if n.strip().lower() == "estimate"), None)
    if not sn:
        return None, wb.datemode
    sh = wb.sheet_by_name(sn)
    out = [[sh.cell_value(r, c) for c in range(min(sh.ncols, 30))] for r in range(min(sh.nrows, 260))]
    return out, wb.datemode


def rows_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sn = next((n for n in wb.sheetnames if n.strip().lower() == "estimate"), None)
    if not sn:
        return None, 0
    out = []
    for i, row in enumerate(wb[sn].iter_rows(max_row=260, max_col=30, values_only=True)):
        out.append(["" if v is None else v for v in row])
    wb.close()
    return out, 0


def num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def to_date(v, datemode):
    f = num(v)
    if f and 30000 < f < 60000:     # Excel serial date
        return (datetime(1899, 12, 30) + timedelta(days=f)).date().isoformat()
    if isinstance(v, datetime):
        return v.date().isoformat()
    return None


def parse(rows, datemode):
    rec, mats, procs = {}, [], set()
    in_bom = in_labour = False
    for r in rows:
        cells = [c for c in r]
        texts = [str(c).strip() for c in cells]
        low = [t.lower() for t in texts]
        # label -> next non-empty value to the right
        for i, t in enumerate(low):
            f = LABELS.get(t)
            if f and f not in rec:
                for v in cells[i + 1:]:
                    s = str(v).strip()
                    if s.endswith("=") or s.lower() in LABELS:   # the next label, not a value: field left blank
                        break
                    if s not in ("", "None"):
                        rec[f] = v
                        break
        first = next((t for t in texts if t), "")
        if first.lower().startswith("bill of materials"):
            in_bom = True
            continue
        if first.lower() == "operation":
            in_labour = True
            continue
        if in_bom:
            if SECTION_END.match(first):
                in_bom = False
            elif first and not num(first):
                vals = [num(c) for c in cells[1:] if num(c) is not None]
                if vals and vals[-1] and vals[-1] > 0:
                    mats.append((round(vals[-1], 2), first[:80]))
        if in_labour:
            if first.lower().startswith("total labour"):
                in_labour = False
            elif first and len(texts) > 2 and texts[2]:
                procs.add(first[:30])
    if "est_date" in rec:
        rec["est_date"] = to_date(rec["est_date"], datemode)
    for k in ("qty", "unit_cost", "material_cost", "labour_cost", "sell_price", "unit_cost_total"):
        if k in rec:
            rec[k] = num(rec[k])
    if not rec.get("unit_cost") and rec.get("unit_cost_total"):
        rec["unit_cost"] = rec["unit_cost_total"]
    mats.sort(reverse=True)
    rec["materials"] = json.dumps([m for _, m in mats[:8]])
    rec["processes"] = json.dumps(sorted(procs))
    return rec


JOB = re.compile(r"^\D{0,4}(\d{4,6})(?!\d)")   # SDI job numbers lead the drawing no / folder name: "10474-04-GA1 ..."


def main(limit=None):
    con = db()
    known = {p: m for p, m in con.execute("SELECT path, mtime FROM estimates")}
    n = done = bad = 0
    t0 = time.time()
    for year in sorted(os.listdir(ROOT)):
        ydir = os.path.join(ROOT, year)
        if not os.path.isdir(ydir):
            continue
        for dirpath, dirnames, files in os.walk(ydir):
            dirnames[:] = [d for d in dirnames if d.lower() not in ("archive", "old")]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in (".xls", ".xlsx", ".xlsm") or fn.startswith("~$"):
                    continue
                if "blank" in fn.lower() and "estimate" in fn.lower() and dirpath == ydir:
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    mt = os.path.getmtime(path)
                except OSError:
                    continue
                n += 1
                if known.get(path) == mt:
                    continue
                rel = os.path.relpath(path, ydir).split(os.sep)
                client = rel[0] if len(rel) > 1 else ""
                jobf = rel[1] if len(rel) > 2 else ""
                try:
                    rows, dm = (rows_xls if ext == ".xls" else rows_xlsx)(path)
                    rec = parse(rows, dm) if rows else {}
                    status = "ok" if rec.get("unit_cost") or rec.get("description") else ("no-estimate-sheet" if rows is None else "empty")
                except Exception as e:
                    rec, status = {}, f"error: {str(e)[:80]}"
                    bad += 1
                m = next((x for x in (JOB.search(s) for s in (str(rec.get("drawing_no") or ""), jobf, fn)) if x), None)
                con.execute("INSERT OR REPLACE INTO estimates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    path, mt, year, client, jobf, fn, m.group(1) if m else None,
                    str(rec.get("customer") or "")[:80], str(rec.get("description") or "")[:200],
                    str(rec.get("drawing_no") or "")[:80], str(rec.get("rev") or "")[:10], rec.get("qty"),
                    rec.get("unit_cost"), rec.get("material_cost"), rec.get("labour_cost"), rec.get("sell_price"),
                    rec.get("est_date"), str(rec.get("prepared_by") or "")[:40], rec.get("materials"),
                    rec.get("processes"), status))
                done += 1
                if done % 200 == 0:
                    con.commit()
                    print(f"{done} read ({n} seen, {bad} errors) {time.time() - t0:.0f}s", flush=True)
                if limit and done >= limit:
                    con.commit()
                    print("limit reached")
                    return
    con.commit()
    print(f"finished: {done} read, {n} seen, {bad} errors, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
