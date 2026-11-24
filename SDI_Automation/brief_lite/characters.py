"""characters.py - who the AM talks to in SDI Live: Sid, Beth, Ray or Isla (21 Nov 2026).

James: "Can we also have a few different voices and characters. So English posh lady polite persuasive voice Beth.
Sid. English sounding sharp. Do we have or can we find a Birmingham and a Scottish accent. Let's find an avatar also to
put next to their name and be able to switch between the four."

Every character runs the same brief, with the same rules and tools: only the name, the voice, the accent and the
manner change. One character for the whole chat - the live call (OpenAI Realtime voice + accent in its instructions),
Talk mode (OpenAI text-to-speech voice + accent instructions) and the typed chat (name and manner).

Accents are asked of the voice models in words: Received Pronunciation and Scottish come out well; Birmingham is the
hardest for them. Listen before relying on it - if Ray's accent drifts, the voice or wording here is the one place to
change it.
"""
import re

CHARACTERS = {
    "sid": {
        "name": "Sid", "he": "he", "tagline": "Sharp, quick, UK designer",
        "rt_voice": "cedar", "tts_voice": "fable",
        "manner": "Warm, unhurried, British English.",
        "accent": "",            # Sid is as he was: no change to the voice that is already live
        "tts_style": ("A warm, natural British designer chatting to a colleague. Relaxed but brisk pace, "
                      "light and friendly, contractions, no announcer voice, no robotic pauses."),
        "colour": "#F6D946",
    },
    "beth": {
        "name": "Beth", "he": "she", "tagline": "Polished, polite and persuasive",
        "rt_voice": "marin", "tts_voice": "shimmer",
        "manner": "Polished, polite and quietly persuasive - a well-spoken English account director. Warm, gracious, "
                  "never pushy.",
        "accent": "a refined, well-spoken English accent (Received Pronunciation)",
        "tts_style": ("A refined, well-spoken English woman with a Received Pronunciation accent - polished, polite and "
                      "gently persuasive, warm and gracious, unhurried, like a senior account director."),
        "colour": "#E1E1D5",
    },
    "ray": {
        "name": "Ray", "he": "he", "tagline": "Friendly, down-to-earth Brummie",
        "rt_voice": "ash", "tts_voice": "ash",
        "manner": "Friendly, down-to-earth and practical - a Birmingham workshop-floor designer who knows how things "
                  "get made. Chatty but to the point.",
        # 24 Nov 2026 (Matt: "you don't sound like a Brummie"): spelt out, so the voice commits to it
        "accent": "a strong, broad Brummie accent (sing-song Birmingham tune, 'oi' for 'I', 'yow' for 'you'), never neutral",
        "tts_style": ("A friendly man from Birmingham with a clear Brummie accent - down-to-earth, warm and practical, "
                      "chatty but to the point, natural pace."),
        "colour": "#282928",
    },
    "isla": {
        "name": "Isla", "he": "she", "tagline": "Calm, clear and Scottish",
        "rt_voice": "coral", "tts_voice": "coral",
        "manner": "Calm, clear and encouraging - an Edinburgh designer with a dry sense of humour. Thoughtful and "
                  "precise.",
        "accent": "a soft Scottish accent (Edinburgh)",
        "tts_style": ("A calm, clear Scottish woman from Edinburgh with a soft Scottish accent - thoughtful, precise and "
                      "encouraging, a touch of dry humour, natural pace."),
        "colour": "#71716B",
    },
}
DEFAULT = "sid"


def key(value):
    """A character's key from anything the page or the brief carries; Sid when it isn't one of the four."""
    k = re.sub(r"[^a-z]", "", str(value or "").lower())
    return k if k in CHARACTERS else DEFAULT


def of(s):
    """The character for this chat."""
    return CHARACTERS[key(((s or {}).get("brief") or {}).get("_character"))]


def voice_rules(rules, c):
    """Sid's rules, spoken by another character: their name, and their manner and accent for the whole call."""
    if c["name"] == "Sid":
        return rules
    out = rules.replace("You are Sid,", f"You are {c['name']},").replace("- You are Sid.", f"- You are {c['name']}.")
    out = out.replace('("Hi James, Sid here")', f'("Hi James, {c["name"]} here")')
    out = out.replace('"Sid, SDI\'s design assistant."', f'"{c["name"]}, SDI\'s design assistant."')
    line = f"- {c['manner']}" + (f" Speak in {c['accent']} - every word, the whole call." if c["accent"] else "")
    return out.replace("- Warm, unhurried, British English.", line, 1)


def say_name(text, c):
    """'Sid' in a line written for Sid, for whoever the AM is talking to."""
    return text if c["name"] == "Sid" else re.sub(r"\bSid\b", c["name"], text)


def public():
    """What the page shows for each: name, one line, pronoun and colour (never the voice settings)."""
    return [{"key": k, "name": c["name"], "tagline": c["tagline"], "he": c["he"], "colour": c["colour"]}
            for k, c in CHARACTERS.items()]
