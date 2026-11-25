"""make_icons.py - SDI Live's app icon and splash screens for iPhone and Android, drawn from the brand itself.

The icon: SDI yellow, the we.are.sdi wordmark (the same SVG as SDI Live's page) and 'Live' in a serif - the home-screen
icon the web app already had, drawn at full size so it stays sharp on a phone. Run it again after changing the design:
    python3 make_icons.py
"""
import io
import os
import re

import cairosvg
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "..", "SDI_Automation", "brief_lite", "lite_page.html")
YELLOW, INK, PAPER = (245, 217, 71), (31, 35, 33), (247, 246, 241)
SERIF = ["/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", "C:/Windows/Fonts/georgia.ttf",
         "/System/Library/Fonts/Supplemental/Georgia.ttf"]


def wordmark(width):
    """The we.are.sdi wordmark as a transparent PNG, `width` pixels wide, in SDI's ink colour."""
    svg = re.search(r'<svg class="sdiwm".*?</svg>', open(PAGE, encoding="utf-8").read(), re.S).group(0)
    svg = svg.replace('class="sdiwm" role="img" aria-label="we.are.sdi" ', 'xmlns:x="x" ').replace("currentColor", "#1F2321")
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=width)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def serif(size):
    for f in SERIF:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def icon(size=1024, background=YELLOW, scale=1.0):
    """The square icon. scale < 1 shrinks the artwork into the middle (Android's adaptive-icon safe zone)."""
    im = Image.new("RGBA", (size, size), background + (255,) if background else (0, 0, 0, 0))
    art = int(size * 0.62 * scale)
    wm = wordmark(art)
    live = serif(int(size * 0.36 * scale))
    d = ImageDraw.Draw(im)
    box = d.textbbox((0, 0), "Live", font=live)
    lw, lh = box[2] - box[0], box[3] - box[1]
    gap = int(size * 0.035 * scale)
    total = wm.height + gap + lh
    y0 = (size - total) // 2 - int(size * 0.02 * scale)
    im.alpha_composite(wm, ((size - wm.width) // 2, y0))
    d.text(((size - lw) // 2 - box[0], y0 + wm.height + gap - box[1]), "Live", font=live, fill=INK)
    return im


def splash(w, h):
    """A calm splash: SDI's paper colour with the icon in the middle."""
    im = Image.new("RGB", (w, h), PAPER)
    s = int(min(w, h) * 0.32)
    ic = icon(s).resize((s, s), Image.LANCZOS)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=255)
    im.paste(ic.convert("RGB"), ((w - s) // 2, (h - s) // 2), mask)
    return im


def main():
    big = icon(1024)
    # iPhone: one 1024 icon, no transparency (Apple refuses an icon with an alpha channel)
    big.convert("RGB").save(os.path.join(HERE, "ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png"))
    # Android: launcher icons, and the adaptive icon's foreground on a yellow background
    res = os.path.join(HERE, "android/app/src/main/res")
    for dpi, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        d = os.path.join(res, f"mipmap-{dpi}")
        os.makedirs(d, exist_ok=True)
        sq = big.resize((px, px), Image.LANCZOS).convert("RGB")
        sq.save(os.path.join(d, "ic_launcher.png"))
        rnd = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        mask = Image.new("L", (px, px), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, px - 1, px - 1), fill=255)
        rnd.paste(icon(px * 4, scale=0.86).resize((px, px), Image.LANCZOS), (0, 0), mask)
        rnd.save(os.path.join(d, "ic_launcher_round.png"))
        fg = int(px * 108 / 48)
        icon(fg * 4, background=None, scale=0.62).resize((fg, fg), Image.LANCZOS).save(
            os.path.join(d, "ic_launcher_foreground.png"))
    bg = os.path.join(res, "values", "ic_launcher_background.xml")
    with open(bg, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#F5D947</color>\n</resources>\n')
    # splash screens: every one Capacitor made, redrawn at its own size
    for root, _, files in os.walk(os.path.join(HERE, "android/app/src/main/res")):
        for f in files:
            if f == "splash.png":
                p = os.path.join(root, f)
                w, h = Image.open(p).size
                splash(w, h).save(p)
    ios_splash = os.path.join(HERE, "ios/App/App/Assets.xcassets/Splash.imageset")
    for f in os.listdir(ios_splash) if os.path.isdir(ios_splash) else []:
        if f.endswith(".png"):
            p = os.path.join(ios_splash, f)
            w, h = Image.open(p).size
            splash(w, h).save(p)
    print("icons and splash screens drawn")


if __name__ == "__main__":
    main()
