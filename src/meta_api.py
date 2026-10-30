"""Thin client for the Meta Model API, standard library only.

Standard tier models only. The `-contributor` models let Meta train on what we
send (Terms of Service 6.1), and our test photos are a laundry's customers'
clothes, so they are refused here rather than left to whoever edits a model name.
"""
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://api.meta.ai/v1"
ROOT = Path(__file__).resolve().parent.parent


def api_key() -> str:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        key_file = ROOT / ".meta_key"
        if key_file.exists():
            key = key_file.read_text().strip()
    if not key:
        raise SystemExit("No API key: set MODEL_API_KEY or put it in .meta_key")
    return key


def image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def post(path: str, body: dict, timeout: int = 120) -> tuple[dict, float]:
    """POST JSON, retrying 429 and 5xx with backoff. Returns (json, seconds)."""
    if "contributor" in str(body.get("model", "")):
        raise ValueError("contributor models train on our data; use the standard model")
    # The Responses API stores every request unless told not to.
    body = {"store": False, **body}
    data = json.dumps(body).encode()
    for attempt in range(5):
        req = urllib.request.Request(
            BASE_URL + path,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key()}",
                "Content-Type": "application/json",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read()), time.monotonic() - started
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = float(e.headers.get("Retry-After") or 0.5 * 2**attempt)
                time.sleep(wait)
                continue
            raise RuntimeError(f"{e.code} {e.read().decode()[:500]}") from None
    raise RuntimeError(f"gave up after retries on {path}")


def response_text(resp: dict) -> str:
    """Collect output_text from a Responses API result."""
    parts = []
    for item in resp.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                parts.append(c.get("text", ""))
    return "".join(parts) or resp.get("output_text", "")
