"""The counter on WhatsApp.

Staff send the photo(s) of a lot, then say what is in it, as the photo's
caption or the next text. The reply is the priced draft, or a question when the
words and the photo disagree, followed by the counted photo.

Only numbers in ALLOWED_NUMBERS are answered: every reading costs money.
"""
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from quote import load_pricelist, read_photo, read_staff, reconcile, staff_message
from receipt import counted_photo
import whatsapp

HOLD_SECONDS = 15 * 60
MAX_PHOTOS = 5
BRAND = os.environ.get("BRAND", "prezr")
ALLOWED = {n.strip() for n in os.environ.get("ALLOWED_NUMBERS", "").split(",") if n.strip()}
WORK = Path(tempfile.gettempdir()) / "lots"

held: dict[str, list[tuple[float, Path]]] = {}   # sender -> photos waiting for their words
seen_ids: set[str] = set()
lock = threading.Lock()


def take_photos(sender: str) -> list[Path]:
    with lock:
        fresh = [p for t, p in held.pop(sender, []) if time.time() - t < HOLD_SECONDS]
    return fresh


def quote_lot(sender: str, photos: list[Path], words: str) -> None:
    items = load_pricelist(BRAND)
    started = time.time()
    photo = read_photo(photos)
    staff = read_staff(words, items)
    draft = reconcile(staff.get("lines", []), photo, items)
    secs = time.time() - started
    customer = staff.get("customer_phone")
    head = f"Customer {customer}\n" if customer else "No customer number heard.\n"
    whatsapp.send_text(sender, head + staff_message(draft) + f"\n({secs:.0f} s)")

    garments = [c.garment for c in draft.checks if c.seen] or ["garment"]
    out = WORK / f"{photos[0].stem}-counted.jpg"
    counts = counted_photo(photos[0], garments, out)
    whatsapp.send_image(sender, out.read_bytes(),
                        "Counted at the counter: " + ", ".join(f"{n} {g}" for g, n in counts.items()))


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
        path = WORK / f"{msg['id'][-24:]}.jpg".replace("=", "")
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
        if not photos:
            whatsapp.send_text(sender, "Send the photo of the lot first, then what is in it.")
            return
        quote_lot(sender, photos, msg["text"]["body"])
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        if q.get("hub.mode") == ["subscribe"] and q.get("hub.verify_token") == [os.environ.get("VERIFY_TOKEN")]:
            body = q.get("hub.challenge", [""])[0].encode()
            self.send_response(200)
        else:
            body = b"ok" if self.path == "/health" else b"forbidden"
            self.send_response(200 if self.path == "/health" else 403)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        secret = os.environ.get("APP_SECRET", "")
        if secret:
            want = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, self.headers.get("X-Hub-Signature-256", "")):
                self.send_response(403)
                self.end_headers()
                return
        self.send_response(200)
        self.end_headers()
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return
        threading.Thread(target=process, args=(payload,), daemon=True).start()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"listening on {port}, brand {BRAND}, {len(ALLOWED)} numbers allowed", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
