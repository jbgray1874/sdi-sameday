"""Contact sheet of what a brief pulls, so the pictures can be judged by eye: python _contact.py Client "brief words" out.png"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_search
from PIL import Image, ImageDraw
res = lite_search.search(sys.argv[3] if len(sys.argv) > 4 else sys.argv[2], client=sys.argv[1], n=6)
out = sys.argv[-1]
tw, th = 220, 160
sheet = Image.new("RGB", (4 * tw, len(res) * (th + 18)), "white")
d = ImageDraw.Draw(sheet)
for r, row in enumerate(res):
    y = r * (th + 18)
    d.text((4, y + 2), f"{row['job_no']} {row['name'][:60]} ({row['brand']})", fill=(0, 0, 0))
    for c, im in enumerate(row["images"][:4]):
        try:
            t = Image.open(im["thumb"]).convert("RGB")
            t.thumbnail((tw - 4, th - 2))
            sheet.paste(t, (c * tw + 2, y + 16))
        except Exception:
            pass
sheet.save(out)
print(len(res), "jobs ->", out)
