"""The counter on WhatsApp.

Staff send the photo(s) of a lot, then say what is in it, as the photo's
caption or the next text. The reply is the priced draft, or a question when the
words and the photo disagree, followed by the counted photo.

Two ways to run:
- direct (RELAY unset): this process reads the lot itself.
- relay (RELAY=1): this process only talks to WhatsApp and queues each lot; a
  worker (src/worker.py) somewhere Meta Model API answers takes the lot from
  GET /jobs and hands the reply back to POST /jobs/result. The worker only
  makes outgoing calls, so it needs no public address. Meta Model API answers
  "model_not_found" to calls from Railway's servers (30 Oct 2026), which is
  why this mode exists.

Only numbers in ALLOWED_NUMBERS are answered: every reading costs money.
"""
import base64
import hashlib
import hmac
import json
import os
import queue
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import whatsapp

HOLD_SECONDS = 15 * 60
MAX_PHOTOS = 5
RELAY = os.environ.get("RELAY") == "1"
ALLOWED = {n.strip() for n in os.environ.get("ALLOWED_NUMBERS", "").split(",") if n.strip()}
WORK = Path(tempfile.gettempdir()) / "lots"

held: dict[str, list[tuple[float, Path]]] = {}   # sender -> photos waiting for their words
last: dict[str, tuple[float, list[Path], str]] = {}  # sender -> the lot just quoted, for follow-ups
seen_ids: set[str] = set()
jobs: "queue.Queue[dict]" = queue.Queue()
lock = threading.Lock()


def take_photos(sender: str) -> list[Path]:
    with lock:
        return [p for t, p in held.pop(sender, []) if time.time() - t < HOLD_SECONDS]


def quote_lot(sender: str, photos: list[Path], words: str) -> None:
    with lock:
        last[sender] = (time.time(), photos, words)
    if RELAY:
        jobs.put({"sender": sender, "words": words,
                  "photos": [base64.b64encode(p.read_bytes()).decode() for p in photos]})
        return
    from pipeline import build_reply
    text, jpeg, caption = build_reply(photos, words, WORK)
    whatsapp.send_text(sender, text)
    whatsapp.send_image(sender, jpeg, caption)


def handle(msg: dict) -> None:
    sender = msg.get("from", "")
    if msg.get("id") in seen_ids:
        return
    seen_ids.add(msg.get("id"))
    if ALLOWED and sender not in ALLOWED:
        return
    kind = msg.get("type")
    if kind == "image":
        WORK.mkdir(parents=True, exist_ok=True)
        path = WORK / (msg["id"][-24:].replace("=", "") + ".jpg")
        path.write_bytes(whatsapp.download_media(msg["image"]["id"]))
        caption = (msg["image"].get("caption") or "").strip()
        with lock:
            lot = held.setdefault(sender, [])
            if len(lot) < MAX_PHOTOS:
                lot.append((time.time(), path))
            first = len(lot) == 1
        if caption:
            quote_lot(sender, take_photos(sender), caption)
        elif first:
            whatsapp.send_text(sender, "Photo received. Now say what is in it, with the customer's number.")
    elif kind == "text":
        photos = take_photos(sender)
        if photos:
            quote_lot(sender, photos, msg["text"]["body"])
            return
        # No new photo: a follow-up (the number, a correction) to the lot just quoted.
        with lock:
            prev = last.get(sender)
        if prev and time.time() - prev[0] < HOLD_SECONDS:
            quote_lot(sender, prev[1], prev[2] + "\nThen staff added: " + msg["text"]["body"])
            return
        whatsapp.send_text(sender, "Send the photo of the lot first, then what is in it.")
    elif kind == "audio":
        whatsapp.send_text(sender, "Voice notes are coming next. For now, type what is in the lot.")


def process(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []) or []:
                try:
                    handle(msg)
                except Exception:
                    traceback.print_exc()
                    try:
                        whatsapp.send_text(msg.get("from", ""), "Something went wrong reading that lot. Please send it again.")
                    except Exception:
                        traceback.print_exc()


def _authorised(q: dict) -> bool:
    token = os.environ.get("VERIFY_TOKEN", "")
    return bool(token) and hmac.compare_digest(q.get("token", [""])[0], token)


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: bytes = b"", ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/health":
            return self._reply(200, b"ok")
        if url.path == "/webhook":
            if q.get("hub.mode") == ["subscribe"] and q.get("hub.verify_token") == [os.environ.get("VERIFY_TOKEN")]:
                return self._reply(200, q.get("hub.challenge", [""])[0].encode())
            return self._reply(403, b"forbidden")
        if url.path == "/jobs" and _authorised(q):
            # Long poll: the worker waits here up to 25 s for the next lot.
            try:
                job = jobs.get(timeout=25)
            except queue.Empty:
                return self._reply(204)
            return self._reply(200, json.dumps(job).encode(), "application/json")
        return self._reply(403, b"forbidden")

    def do_POST(self):
        url = urlparse(self.path)
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if url.path == "/jobs/result":
            if not _authorised(parse_qs(url.query)):
                return self._reply(403)
            r = json.loads(raw)
            if r.get("sender") not in ALLOWED:
                return self._reply(400)
            self._reply(200)
            try:
                whatsapp.send_text(r["sender"], r["text"])
                if r.get("image"):
                    whatsapp.send_image(r["sender"], base64.b64decode(r["image"]), r.get("caption", ""))
            except Exception:
                traceback.print_exc()
            return
        if url.path != "/webhook":
            return self._reply(404)
        secret = os.environ.get("APP_SECRET", "")
        if secret:
            want = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, self.headers.get("X-Hub-Signature-256", "")):
                return self._reply(403)
        self._reply(200)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return
        threading.Thread(target=process, args=(payload,), daemon=True).start()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"listening on {port}, {'relay' if RELAY else 'direct'}, {len(ALLOWED)} numbers allowed", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
