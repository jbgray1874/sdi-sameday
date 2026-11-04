"""Technical GA drawn BY THE IMAGE MODEL FROM THE CHOSEN 3D CONCEPT, so every feature of that unit appears. python _try_ga.py <render.png> [quality]"""
import base64, glob, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(r"C:\SDI_Automation\.env")
from openai import OpenAI

src = sys.argv[1]
quality = sys.argv[2] if len(sys.argv) > 2 else "medium"
H, W, D = 1800, 600, 400
prompt = f"""Draw the GENERAL ARRANGEMENT (GA) technical drawing of the display unit shown in this image - the same unit, with every feature it has:
its exact shape, header, shelves (count them), plinth/base, side panels, curves, lighting and graphics panels.
Style: a clean black line drawing on a white A3 landscape sheet, like a SolidWorks drawing sheet, no photo, no colour fill except thin hatching for glass or acrylic.
Views: FRONT ELEVATION, SIDE ELEVATION, PLAN (top view), and a small ISOMETRIC view.
Dimensions - use EXACTLY these overall figures and do not invent any other number:
  overall height {H} mm, width {W} mm, depth {D} mm.
Show dimension lines with arrows and the figures H {H}, W {W}, D {D} on the views. Add leader-line callouts naming the parts and materials
visible in the image (e.g. header panel, shelf, plinth, side panel, LED strip) without adding any measurement you were not given.
Title block bottom right: "SDI DISPLAYS - CONCEPT GA - NOT FOR MANUFACTURE", with H x W x D = {H} x {W} x {D} mm and the date.
All text must be spelled correctly and legible."""
t = time.time()
r = OpenAI().images.edit(model="gpt-image-2", image=[open(src, "rb")], prompt=prompt, size="1536x1024", quality=quality)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", f"try_ga_{quality}.png")
open(out, "wb").write(base64.b64decode(r.data[0].b64_json))
u = r.usage
d = u.input_tokens_details
print(f"{quality}: {time.time() - t:.0f}s, ~${(d.text_tokens * 5 + d.image_tokens * 10 + u.output_tokens * 40) / 1e6:.3f} ->", out)
