"""Make one concept for a test brief with a chosen image model, using SDI's own past renders as references.
python _try_visual.py <model> [quality]"""
import base64, os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_app, lite_search
from openai import OpenAI

model = sys.argv[1] if len(sys.argv) > 1 else "gpt-image-2"
quality = sys.argv[2] if len(sys.argv) > 2 else "medium"
brief = {"client": "Boots", "unit_type": "No7 skincare floor-standing shelf unit", "placement": "front of store",
         "size": "1800 high x 600 wide x 400 deep", "materials": "white gloss with oak shelves",
         "colours_graphics": "navy No7 header", "products_held": "No7 skincare"}
s = {"id": "try", "brief": brief, "refs": [], "visuals": [], "client_images": []}
t = time.time()
lite_app.find_past(s)
print(f"search {time.time() - t:.1f}s:", [r["job_no"] + " " + r["name"][:30] for r in s["refs"][:4]])
opts = lite_app.option_refs(s)
label, refs = opts[0]
files = []
for r in refs:
    for im in r["images"][:2 if r is refs[0] else 1]:
        b = lite_app.load_ref_image(im)
        if b:
            files.append(b)
print("references:", [f.name for f in files])
prompt = lite_app.visual_prompt(brief, "render", refs=refs)
t = time.time()
r = OpenAI().images.edit(model=model, image=files, prompt=prompt, size="1536x1024", quality=quality)
out = os.path.join(lite_app.OUT, f"try_{model}_{quality}.png")
open(out, "wb").write(base64.b64decode(r.data[0].b64_json))
print(f"{model} {quality}: {time.time() - t:.0f}s ->", out)
print("usage:", getattr(r, "usage", None))
