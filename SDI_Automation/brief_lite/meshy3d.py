"""meshy3d.py - the chosen design as a real, textured 3D model, made from its render by Meshy (25 Nov 2026).

James: "use the 3D service for now". SDI Live's own 3D model (model3d.py) is a block model from the brief's sizes; it
can't show a curved arch or a bread-oven mouth. Meshy turns ONE picture into a textured 3D model (GLB) the page can turn.
It needs MESHY_API_KEY in the server's .env (never in Git); without it nothing here runs and the block model stays.

    start(image_path)  -> task id          POST /openapi/v1/image-to-3d   (the picture as a data URI)
    status(task_id)    -> {'status', 'progress', 'glb', 'thumb', 'error'}
    fetch(url, path)   -> path             the GLB is downloaded at once: Meshy's links expire

Every answer is read defensively (the task id as 'result' or 'id'; the GLB under model_urls.glb), and anything
unexpected is raised with Meshy's own words, so the log says plainly what went wrong.
"""
import base64
import os

API = os.environ.get("MESHY_API", "https://api.meshy.ai/openapi/v1/image-to-3d")
DONE, FAILED = {"SUCCEEDED"}, {"FAILED", "CANCELED", "CANCELLED", "EXPIRED"}


def key():
    return os.environ.get("MESHY_API_KEY", "").strip()


def _headers():
    return {"Authorization": f"Bearer {key()}"}


def _data_uri(path, longest=1536):
    """The picture as a PNG data URI, no bigger than Meshy needs."""
    try:
        from PIL import Image
        import io
        im = Image.open(path).convert("RGB")
        im.thumbnail((longest, longest))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        raw = buf.getvalue()
    except Exception:                                          # noqa: BLE001
        raw = open(path, "rb").read()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def start(image_path, texture=True, timeout=60):
    """Ask Meshy for a textured model of the unit in the picture -> its task id."""
    import requests
    body = {"image_url": _data_uri(image_path), "should_texture": bool(texture), "enable_pbr": False,
            "should_remesh": True, "topology": "triangle", "target_polycount": 60000, "symmetry_mode": "auto"}
    if os.environ.get("MESHY_AI_MODEL"):
        body["ai_model"] = os.environ["MESHY_AI_MODEL"]
    r = requests.post(API, headers=_headers(), json=body, timeout=timeout)
    if r.status_code >= 300:
        raise RuntimeError(f"Meshy refused the job ({r.status_code}): {r.text[:300]}")
    j = r.json()
    tid = j.get("result") or j.get("id")
    if not tid:
        raise RuntimeError(f"Meshy gave no task id: {str(j)[:300]}")
    return str(tid)


def status(task_id, timeout=30):
    import requests
    r = requests.get(f"{API}/{task_id}", headers=_headers(), timeout=timeout)
    if r.status_code >= 300:
        raise RuntimeError(f"Meshy status failed ({r.status_code}): {r.text[:300]}")
    j = r.json()
    urls = j.get("model_urls") or {}
    err = j.get("task_error") or {}
    return {"status": str(j.get("status") or "").upper(), "progress": j.get("progress"), "glb": urls.get("glb"),
            "thumb": j.get("thumbnail_url"), "error": (err.get("message") if isinstance(err, dict) else str(err or "")) or ""}


def fetch(url, path, timeout=120):
    import requests
    with requests.get(url, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in r.iter_content(1 << 16):
                fh.write(chunk)
    return path
