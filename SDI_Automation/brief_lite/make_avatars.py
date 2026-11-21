"""make_avatars.py - the four characters' portraits for SDI Live's "Talk to" row (21 Nov 2026).

James: "we need cool wearesdi avatars / digital looking people for the four characters ... to give it character."
Stylised digital people in we.are.sdi's look - SDI yellow (#F6D946), black and warm stone, with the yellow halftone dots
the website uses - one per character, each recognisably themselves. Illustrations of made-up people, never anyone real.

Run on the server, from C:\\SDI_Automation\\brief_lite (the OpenAI key is read from ..\\.env; about 4p a picture):
    python make_avatars.py                  one portrait each, for any that isn't there yet
    python make_avatars.py --options 3      three to choose from for each, in brand\\avatars\\options (about 50p)
    python make_avatars.py --use sid=2 beth=1 ray=3 isla=2
                                            the ones chosen become the portraits
    python make_avatars.py --again          all four made again
Saved as brand\\avatars\\<sid|beth|ray|isla>.png and shown next to each name straight away - no restart.
"""
import base64
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "brand", "avatars")
OPTS = os.path.join(OUT, "options")

STYLE = ("A stylised digital character portrait for a design studio's AI assistant: head and shoulders, centred, facing "
         "the viewer with a warm, confident expression. A modern semi-realistic 3D look - smooth stylised skin and hair, "
         "soft studio lighting with a gentle rim light, crisp and premium, like a high-end brand's digital mascot. The "
         "studio's brand look: a warm stone (#E1E1D5) background with a large SDI yellow (#F6D946) circle behind the head "
         "and a soft field of small black halftone dots fading across one side; clothing in black or charcoal with a "
         "single SDI yellow accent. Square, plenty of space around the head so it crops cleanly into a circle. No text, "
         "no logo, no frame, no hands. A made-up person, not a real one. The character: {who}")
PEOPLE = {
    "sid": "Sid - a sharp, quick-witted London designer in his thirties: short dark hair with a neat fade, light stubble, "
           "a black crew-neck jumper, a yellow pencil tucked behind one ear, a knowing half-smile.",
    "beth": "Beth - a polished, elegant English account director in her forties: sleek shoulder-length fair hair, a "
            "tailored black blazer over a cream top, a small yellow enamel pin, pearl earrings, a gracious, persuasive smile.",
    "ray": "Ray - a cheerful, down-to-earth Birmingham workshop designer in his fifties: short greying hair, a trimmed "
           "salt-and-pepper beard, a charcoal work jacket over a yellow t-shirt, safety glasses pushed up on his head, a "
           "big friendly grin.",
    "isla": "Isla - a calm, thoughtful Edinburgh designer in her thirties: auburn hair in a loose low bun, freckles, round "
            "black-framed glasses, a dark knitted jumper with a yellow collar, a quiet, dry-humoured smile.",
}


def _client():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))
    from openai import OpenAI
    return OpenAI(timeout=180)


def _make(client, key, path):
    r = client.images.generate(model=os.environ.get("LITE_IMAGE_MODEL", "gpt-image-2"), size="1024x1024",
                               quality="high", prompt=STYLE.format(who=PEOPLE[key]))
    with open(path, "wb") as f:
        f.write(base64.b64decode(r.data[0].b64_json))
    print(f"{key}: made {path}", flush=True)


def main(argv):
    os.makedirs(OUT, exist_ok=True)
    uses = [a for a in argv if "=" in a and a.split("=", 1)[0] in PEOPLE]
    if "--use" in argv:
        for a in uses:
            k, n = a.split("=", 1)
            src = os.path.join(OPTS, f"{k}_{n}.png")
            if not os.path.exists(src):
                print(f"{k}: there's no option {n} ({src})")
                continue
            shutil.copyfile(src, os.path.join(OUT, f"{k}.png"))
            print(f"{k}: option {n} is now the portrait")
        return 0
    client = _client()
    if "--options" in argv:
        i = argv.index("--options")
        n = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else 3
        os.makedirs(OPTS, exist_ok=True)
        for k in PEOPLE:
            for j in range(1, n + 1):
                _make(client, k, os.path.join(OPTS, f"{k}_{j}.png"))
        print(f"Look in {OPTS}, then: python make_avatars.py --use sid=<n> beth=<n> ray=<n> isla=<n>")
        return 0
    for k in PEOPLE:
        path = os.path.join(OUT, f"{k}.png")
        if os.path.exists(path) and "--again" not in argv:
            print(f"{k}: already there")
            continue
        _make(client, k, path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
