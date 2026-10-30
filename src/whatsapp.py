"""WhatsApp Cloud API: read an incoming photo, send text and images back."""
import json
import os
import urllib.request
import uuid

GRAPH = "https://graph.facebook.com/v25.0"


def _token() -> str:
    return os.environ["WA_TOKEN"].strip()


def _phone_id() -> str:
    return os.environ["WA_PHONE_ID"].strip()


def _call(method: str, url: str, body: bytes | None = None, ctype: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def download_media(media_id: str) -> bytes:
    meta = _call("GET", f"{GRAPH}/{media_id}")
    req = urllib.request.Request(meta["url"], headers={"Authorization": f"Bearer {_token()}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def send_text(to: str, text: str) -> None:
    _call("POST", f"{GRAPH}/{_phone_id()}/messages", json.dumps({
        "messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]},
    }).encode(), "application/json")


def send_image(to: str, jpeg: bytes, caption: str = "") -> None:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\nimage/jpeg\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="lot.jpg"\r\n'
        f'Content-Type: image/jpeg\r\n\r\n'.encode() + jpeg + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    media = _call("POST", f"{GRAPH}/{_phone_id()}/media", b"".join(parts), f"multipart/form-data; boundary={boundary}")
    _call("POST", f"{GRAPH}/{_phone_id()}/messages", json.dumps({
        "messaging_product": "whatsapp", "to": to, "type": "image",
        "image": {"id": media["id"], "caption": caption[:1024]},
    }).encode(), "application/json")
