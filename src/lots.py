"""What came in, kept per customer, so what goes out can be checked against it.

A JSON file per customer number under data/lots/ (git-ignored): each intake's
billed pieces by garment, what the photo saw, the damage recorded, and a copy
of the intake photo.
"""
import json
import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOTS = ROOT / "data" / "lots"

HANDOVER = re.compile(r"\b(hand\s*over|handover|deliver(y|ed|ing)?|return(ing)?|out\s*going|kodukk\w*)\b", re.I)


PHONE = re.compile(r"(?<![\d-])(?:\+?91[\s-]?)?([6-9]\d{4})[\s-]?(\d{5})(?![\d-])")


def phone_in(words: str) -> str | None:
    """A mobile number exactly as written: ten digits, or five and five. Never repaired:
    "989542235 810 shirts" is nine digits and a count, so no number."""
    m = PHONE.search(words)
    return m.group(1) + m.group(2) if m else None


def is_handover(words: str) -> bool:
    return bool(HANDOVER.search(words))


def record_intake(phone: str, billed: dict[str, int], seen: dict[str, int], damage: list[dict], photo: Path) -> None:
    LOTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    kept = LOTS / f"{phone}-{stamp}.jpg"
    shutil.copy(photo, kept)
    path = LOTS / f"{phone}.json"
    history = json.loads(path.read_text()) if path.exists() else []
    history.append({"at": time.strftime("%d %b %Y, %H:%M"), "billed": billed, "seen": seen,
                    "damage": damage, "photo": kept.name})
    path.write_text(json.dumps(history, indent=1))


def last_intake(phone: str) -> dict | None:
    path = LOTS / f"{phone}.json"
    if not path.exists():
        return None
    history = json.loads(path.read_text())
    return history[-1] if history else None
