"""
studio_voice.py - turning what someone said into something the brief can read.

Stuart, describing the moment a brief actually happens:

    "If you're Nick Garish or Andy Moran and you come out of a client meeting,
     you're on the train, you're in the car and it's a screamer... if Andy could
     verbalise that and it dictates."

Nobody is filling in a form in the car. They will send a voice note. So a voice
note has to be a first-class way in, alongside an email - WhatsApp .opus, a
phone memo .m4a, a recorded Teams call .mp3, all of it.

Runs entirely on this machine. faster-whisper (CTranslate2) needs no torch and
no internet, so a client call never leaves the building to be transcribed -
which is the same line this project has held on email and on the LLM itself.

The model downloads once on first use, into the usual HuggingFace cache.
"""
import os
import re
import threading

# Voice notes are short and the studio wants them turned round quickly, so
# "small" is the sweet spot: noticeably better than "base" on UK accents and
# retail jargon, still seconds rather than minutes on CPU.
MODEL_SIZE = os.environ.get("SDI_WHISPER_MODEL", "small")

AUDIO_EXTS = {
    ".opus", ".ogg", ".oga",   # WhatsApp voice notes
    ".m4a", ".mp4", ".aac",    # phone memos, iOS
    ".mp3", ".wav", ".wma",    # recordings, Teams exports
    ".flac", ".webm",
}

_model = None
_lock = threading.Lock()


def is_audio(filename):
    return os.path.splitext(filename or "")[1].lower() in AUDIO_EXTS


def is_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _load():
    """One model, loaded once, shared across requests. First call pays the
    download; every call after that is just inference."""
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            # int8 on CPU: about 4x faster than float32 with no meaningful
            # accuracy loss at this model size, and it avoids the CUDA version
            # mismatch on this machine's GPU entirely.
            _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


_big = None


def _load_big():
    """WhatsApp voice notes: the small model misheard accents and invented 'Mb Mb Mb' in silence.
    large-v3-turbo is far better and still a few seconds on CPU for a short note."""
    global _big
    if _big is None:
        with _lock:
            if _big is None:
                from faster_whisper import WhisperModel
                _big = WhisperModel(os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices", "whisper-large-v3-turbo"), device="cpu", compute_type="int8", cpu_threads=12)
    return _big


def _junk(text):
    """Whisper's hallucinations: the same short word over and over, or nothing but filler."""
    w = re.findall(r"[a-z']+", text.lower())
    if not w:
        return True
    return len(w) >= 4 and len(set(w)) <= max(2, len(w) // 4)


def transcribe(path, fast=False, prompt=None, accurate=False):
    """
    Returns {"ok": True, "text": ..., "language": ..., "seconds": ...}
    or {"ok": False, "error": ...}. Never raises - a voice note that will not
    transcribe must not take the rest of the brief down with it.
    fast=True is for short spoken questions: English only, one pass - about
    twice as quick, and a question is a few words, not a client call.
    """
    if not is_available():
        return {"ok": False, "error": "faster-whisper is not installed - run: pip install faster-whisper"}
    if not os.path.exists(path):
        return {"ok": False, "error": f"File not found: {path}"}
    try:
        model = _load_big() if accurate else _load()
        segments, info = model.transcribe(
            path,
            # Questions are English - pinning it stops an accent being heard as another
            # language. Full search kept: accuracy matters more than a second.
            beam_size=2 if accurate else 5,     # turbo is accurate enough with a short search, and twice as quick
            language="en" if fast else None,
            # The job's own words (names, people, numbers) so Whisper hears "Lindberg",
            # "InVue" or "Rem" instead of guessing at them.
            initial_prompt=prompt,
            # Voice notes are full of pauses and car noise; VAD keeps the model
            # from inventing words in the silence between sentences.
            # Not for short questions: on a low-quality browser recording (Edge sent ~2 kbps)
            # the filter judged real speech to be silence every time.
            vad_filter=accurate or not fast,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if not text:
            # A quiet microphone can look like silence to the voice filter, which then throws
            # the whole recording away. Try once more without it before giving up.
            segments, info = model.transcribe(path, beam_size=5, language="en" if fast else None,
                                              initial_prompt=prompt, vad_filter=False)
            text = " ".join(s.text.strip() for s in segments).strip()
        if accurate and _junk(text):    # without the filter Whisper can invent "Mb Mb Mb" from silence
            text = ""
        return {
            "ok": True,
            "text": text,
            "language": getattr(info, "language", ""),
            "seconds": round(getattr(info, "duration", 0) or 0, 1),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def transcribe_as_source(path, filename=None):
    """Transcript wrapped the way the rest of the pipeline expects a source:
    labelled, so the model reading the brief knows this was spoken, not written,
    and can treat a half-finished sentence accordingly."""
    res = transcribe(path)
    if not res.get("ok"):
        return ""
    name = filename or os.path.basename(path)
    if not res["text"]:
        return ""
    return (f"--- Source: {name} (voice note, {res['seconds']}s, transcribed locally) ---\n"
            f"{res['text']}")
