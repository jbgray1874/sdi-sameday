"""make_avatars.py - the four characters' portraits for SDI Live's "Talk to" panel (21 Nov 2026).

Run once on the server, from C:\\SDI_Automation\\brief_lite, with the OpenAI key in ..\\.env:
    python make_avatars.py            makes any portrait that isn't there yet (about 4p each)
    python make_avatars.py --again    makes all four again

Saved as brand\\avatars\\<sid|beth|ray|isla>.png and shown next to each name straight away - no restart. Until they
exist the page shows each character's initial on their colour. They are illustrations of made-up people, never photos
of anyone real.
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "brand", "avatars")

STYLE = ("A friendly, modern flat-illustration avatar portrait, head and shoulders, facing the viewer with a warm natural "
         "smile, simple shapes and soft shading, on a plain {bg} circle background. Clean, professional, the style of a "
         "design studio's team page. No text, no logo, no frame. An illustration of a made-up person, not a real one.")
PEOPLE = {
    "sid": ("a sharp, friendly British man in his thirties, short dark hair, light stubble, black crew-neck jumper",
            "SDI yellow (#F6D946)"),
    "beth": ("a polished, elegant English woman in her forties, neat shoulder-length fair hair, navy blazer, pearl "
             "earrings", "warm stone (#E1E1D5)"),
    "ray": ("a cheerful, down-to-earth man from Birmingham in his fifties, greying hair, check shirt under a work "
            "jacket", "charcoal (#282928)"),
    "isla": ("a calm, thoughtful Scottish woman in her thirties, auburn hair tied back, dark green knitted jumper",
             "warm grey (#71716B)"),
}


def main(again=False):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))
    from openai import OpenAI
    os.makedirs(OUT, exist_ok=True)
    client = OpenAI(timeout=120)
    for key, (who, bg) in PEOPLE.items():
        path = os.path.join(OUT, f"{key}.png")
        if os.path.exists(path) and not again:
            print(f"{key}: already there")
            continue
        r = client.images.generate(model=os.environ.get("LITE_IMAGE_MODEL", "gpt-image-2"), size="1024x1024",
                                   quality="medium", prompt=f"{STYLE.format(bg=bg)} The person: {who}.")
        with open(path, "wb") as f:
            f.write(base64.b64decode(r.data[0].b64_json))
        print(f"{key}: made {path}")


if __name__ == "__main__":
    main(again="--again" in sys.argv)
