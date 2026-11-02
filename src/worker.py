"""Reads lots queued by the relay and hands the replies back.

Runs where Meta Model API answers (this Mac, in India). Outgoing calls only:

    .venv/bin/python -u src/worker.py
"""
import base64
import json
import os
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from pipeline import build_reply

ROOT = Path(__file__).resolve().parent.parent
RELAY_URL = os.environ.get("RELAY_URL", "https://counter-production-b1b8.up.railway.app")
TOKEN = os.environ.get("VERIFY_TOKEN") or (ROOT / ".verify_token").read_text().strip()
WORK = Path(tempfile.gettempdir()) / "lots-worker"


def _post(result: dict) -> None:
    req = urllib.request.Request(f"{RELAY_URL}/jobs/result?token={TOKEN}", data=json.dumps(result).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=60).read()


def run_one(job: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.time() * 1000))
    photos = []
    for n, b64 in enumerate(job["photos"]):
        p = WORK / f"{stamp}-{n}.jpg"
        p.write_bytes(base64.b64decode(b64))
        photos.append(p)
    try:
        text, jpeg, caption = build_reply(photos, job["words"], WORK)
        _post({"sender": job["sender"], "text": text,
               "image": base64.b64encode(jpeg).decode() if jpeg else None, "caption": caption})
    except Exception:
        traceback.print_exc()
        _post({"sender": job["sender"], "text": "Something went wrong reading that lot. Please send it again."})
    finally:
        for p in WORK.glob(f"{stamp}-*"):
            p.unlink(missing_ok=True)


def main() -> None:
    print(f"worker polling {RELAY_URL}", flush=True)
    while True:
        try:
            with urllib.request.urlopen(f"{RELAY_URL}/jobs?token={TOKEN}", timeout=40) as r:
                if r.status == 200:
                    job = json.loads(r.read())
                    print(f"lot from {job['sender'][-4:]}: {len(job['photos'])} photo(s)", flush=True)
                    run_one(job)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print("poll:", str(e)[:120], flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
