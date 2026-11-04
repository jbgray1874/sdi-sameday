"""
build_projects.py - one row per past SDI job, from what is already indexed on this PC.

Sources (all read only, all already on C: - nothing touches W: or K:):
  all_img_meta.json        renders / visuals per job (269k images from W:)
  pdf_fields_index.jsonl   drawing title blocks: dates, who drew it, weight, client
  master_index.json        every job folder on W: with its brand
  newsys/studio.db         Jono's calendar: design days booked per job and team
  knowledge.db/estimates   what it was quoted at (build_estimates.py)

Writes C:\\SDI_Automation\\brief_lite\\knowledge.db tables `projects` and `project_images`.
"""
import json, os, re, sqlite3, collections
from datetime import date

BASE = r"C:\SDI_Automation"
HERE = os.path.join(BASE, "brief_lite")
DB = os.path.join(HERE, "projects.db")    # estimates live in knowledge.db, written by build_estimates.py
JOB = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")
RENDER = re.compile(r"render|visual|\bav\d|concept|mock.?up|cgi|3d", re.I)
BAD_NAME = re.compile(r"archive|^old\b|backup|supplied|^temp|^new folder", re.I)
NOT_RENDER = re.compile(r"decal|map|texture|logo|artwork|supplied|reference|ref\b|screenshot|_mask|alpha", re.I)


def job_of(*texts):
    for t in texts:
        m = JOB.search(t or "")
        if m:
            return m.group(1)
    return None


def main():
    P = collections.defaultdict(lambda: {"names": collections.Counter(), "brands": collections.Counter(), "folders": set(),
                                         "dates": [], "folder_dates": [], "img_names": collections.Counter(), "drawn_by": collections.Counter(), "titles": collections.Counter(),
                                         "weights": [], "n_drawings": 0, "n_images": 0, "n_renders": 0})
    # 1. job folders on W:
    items = json.load(open(os.path.join(BASE, "master_index.json"), encoding="utf-8"))["items"]
    # 3 Nov 2026: a day when hundreds of folders were 'modified' at once is a bulk copy / permission change on W:, not
    # work (6,242 folders on 2 Nov) - those dates made 30-year-old jobs look like 'this month'
    per_day = collections.Counter(i.get("date") for i in items if i.get("kind") == "folder")
    bulk = {d for d, n in per_day.items() if n > 400}
    for it in items:
        if it.get("kind") != "folder":
            continue
        j = job_of(it.get("name"))
        if not j:
            continue
        p = P[j]
        if not BAD_NAME.search(it["name"]):
            p["names"][it["name"]] += 3
        p["brands"][it.get("brand") or ""] += 1
        if len(p["folders"]) < 3:
            p["folders"].add(it.get("folder"))
        if it.get("date") and it["date"] not in bulk:
            p["folder_dates"].append(it["date"])   # when the folder was last touched - only a fallback
    # 2. drawings
    for line in open(os.path.join(BASE, "pdf_fields_index.jsonl"), encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("status") != "ok":
            continue
        j = job_of(r.get("job"), r.get("file"))
        if not j:
            continue
        p, f = P[j], r.get("fields") or {}
        p["n_drawings"] += 1
        if not BAD_NAME.search(r.get("job") or ""):
            p["names"][r.get("job") or ""] += 1
        p["brands"][r.get("brand") or ""] += 1
        dd = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(f.get("date") or ""))   # the date in the title block
        if dd:
            a, b_, y = int(dd.group(1)), int(dd.group(2)), dd.group(3)
            d_, m_ = (a, b_) if b_ <= 12 else (b_, a)          # UK dd/mm, but some title blocks are US mm/dd
            if 1 <= m_ <= 12 and 1 <= d_ <= 31:
                p["dates"].append(f"{y}-{m_:02d}-{d_:02d}")
        elif r.get("date"):
            p["dates"].append(r["date"])
        for k in ("drawn_by", "modified_by"):
            if f.get(k):
                p["drawn_by"][str(f[k]).upper().replace(".", " ")[:30]] += 1
        if f.get("title"):
            p["titles"][str(f["title"])[:60]] += 1
        w = re.match(r"([\d.]+)\s*(k?g)", str(f.get("weight") or ""), re.I)
        if w:
            p["weights"].append(float(w.group(1)) * (1 if w.group(2).lower() == "kg" else 0.001))
    # 3. images: keep the best renders per job
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS project_images")
    con.execute("CREATE TABLE project_images (img_id INTEGER PRIMARY KEY, job_no TEXT, kind TEXT, name TEXT, thumb TEXT, src TEXT)")
    meta = json.load(open(os.path.join(BASE, "all_img_meta.json"), encoding="utf-8"))
    rows = []
    for row, m in enumerate(meta):   # img_id = row in all_img_index.npz (meta "id" is not unique)
        j = job_of(str(m.get("project") or ""), m.get("brand"), m.get("folder"))
        src = m.get("src") or ""
        kind = "other"
        if RENDER.search(src) and not NOT_RENDER.search(src):
            kind = "render"
        elif "creative" in src.lower():
            kind = "creative"
        if j:
            P[j]["n_images"] += 1
            P[j]["n_renders"] += kind == "render"
            if kind == "render":   # "11637 - Boots - No7 Pro Artist BRI - Animation 0300" -> a name when the folder is "Archive"
                stem = re.sub(r"[\s_-]*(v\d+|view \d+|\d{3,})?\s*$", "", m.get("name") or "", flags=re.I)
                if len(stem) > 8:
                    P[j]["img_names"][stem[:70]] += 1
            P[j]["brands"][(m.get("brand") or "").split(" - ", 1)[-1]] += 0
        rows.append((row, j, kind, (m.get("name") or "")[:120], m.get("img"), src))
    con.executemany("INSERT INTO project_images VALUES (?,?,?,?,?,?)", rows)
    # 4. design time from Jono's calendar
    cal = collections.defaultdict(lambda: collections.Counter())
    people = collections.defaultdict(collections.Counter)
    try:
        sc = sqlite3.connect(os.path.join(BASE, "newsys", "studio.db"))
        for start, end, team, job, job_no, ppl, subj in sc.execute(
                "SELECT start, end, team, job, job_no, people, subject FROM calendar_entries WHERE kind='booking'"):
            j = job_no or job_of(job, subj)
            if not j:
                continue
            try:
                days = max(1, (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days)
            except ValueError:
                days = 1
            cal[j][team or "?"] += days
            for n in json.loads(ppl or "[]"):
                people[j][n] += days
    except sqlite3.Error:
        pass
    # 5. write projects
    con.execute("DROP TABLE IF EXISTS projects")
    con.execute("""CREATE TABLE projects (job_no TEXT PRIMARY KEY, name TEXT, brand TEXT, folder TEXT, first_date TEXT,
                   last_date TEXT, n_drawings INT, n_images INT, n_renders INT, drawn_by TEXT, titles TEXT,
                   weight_kg REAL, design_days TEXT, designers TEXT, text TEXT)""")
    out = []
    for j, p in P.items():
        name = (p["names"].most_common(1) or [("", 0)])[0][0]
        if not name or name.strip() == j:
            name = (p["img_names"].most_common(1) or [(name or j, 0)])[0][0]
        brand = next((b for b, _ in p["brands"].most_common() if b and not b.isdigit()), "")
        ds = sorted(d for d in p["dates"] if d and d[:2] in ("19", "20")) or \
             sorted(d for d in p["folder_dates"] if d and d[:2] in ("19", "20"))
        titles = [t for t, _ in p["titles"].most_common(6)]
        text = " ".join([name, brand] + titles).lower()
        out.append((j, name, brand, sorted(p["folders"])[0] if p["folders"] else "", ds[0] if ds else None,
                    ds[-1] if ds else None, p["n_drawings"], p["n_images"], p["n_renders"],
                    json.dumps([d for d, _ in p["drawn_by"].most_common(4)]), json.dumps(titles),
                    round(max(p["weights"]), 2) if p["weights"] else None, json.dumps(dict(cal.get(j, {}))),
                    json.dumps([n for n, _ in people[j].most_common(4)]), text))
    con.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    con.execute("CREATE INDEX IF NOT EXISTS pi_job ON project_images(job_no)")
    con.commit()
    print(f"{len(out)} projects, {len(rows)} images ({sum(1 for r in rows if r[2] == 'render')} renders), "
          f"{sum(1 for j in cal)} jobs with calendar time")


if __name__ == "__main__":
    main()
