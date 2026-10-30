"""Counter intake: staff say what the customer handed in, the photo checks them.

    staff words  ──► lines (garment, service, count)  ─┐
                                                      ├─► reconcile ─► priced draft, or a question to staff
    photo(s)     ──► pieces (garment, count, confidence)┘

The models read; code compares and does the arithmetic. A model never writes a
price, and a disagreement is never settled by a model: it goes back to staff.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from garments import GARMENTS, garment_of
from meta_api import image_data_url, post, response_text

ROOT = Path(__file__).resolve().parent.parent
MODEL = "muse-spark-1.3"

PHOTO_PROMPT = f"""You are the intake desk of a laundry in Kerala, India. The photo(s) show ONE customer's lot, laid out at the counter.
Count every piece. A pair of shoes is one piece. Folded or stacked pieces count separately; look at edges and collars to separate a stack.
Use only these garment names: {", ".join(GARMENTS)}, other.
A dhoti or mundu is a white or cream unstitched cloth, often with a gold or coloured border. A kurta is a long tunic, longer than a shirt.
If some pieces are hidden (inside a bag, under others), say so.
Reply with JSON only, no prose:
{{"items": [{{"garment": "<name>", "count": <int>, "confidence": <0..1>}}], "total": <int>, "all_visible": <true|false>}}"""

SERVICES = {"SP": "steam press", "DC": "dry clean", "W&SP": "wash and steam press", "W&F": "wash and fold",
            "SC": "shoe or bag cleaning", "STR": "starch", "KG": "laundry by weight", "DLV": "pickup and delivery"}


def staff_prompt(items: list[dict]) -> str:
    catalogue = "\n".join(f"{i['item_id']} | {i['name']}" for i in items)
    return f"""A member of staff at a laundry counter has said what a customer handed in. It may be English, Malayalam, Hindi or a mix, and may be a transcribed voice note.
Reply with JSON only: {{"customer_phone": string|null, "lines": [{{"item_id": string|null, "quantity": number, "said": string}}]}}
- One line per garment and service. Service codes in the item names: SP steam press, DC or SW dry clean, W & SP wash and steam press, W & F wash and fold.
- item_id: the ONE item below matching garment AND service; if the fabric is not said, the plainest. null if nothing fits.
- customer_phone: a 10-digit Indian mobile exactly as said, digits only; never repair a number.
- Add nothing that was not said.
ITEMS (id | name):
{catalogue}"""


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def read_photo(photos: list[Path], effort: str = "low") -> dict:
    content = [{"type": "input_text", "text": PHOTO_PROMPT}]
    content += [{"type": "input_image", "image_url": image_data_url(p)} for p in photos]
    resp, secs = post("/responses", {"model": MODEL, "reasoning": {"effort": effort}, "max_output_tokens": 8000,
                                     "input": [{"type": "message", "role": "user", "content": content}]})
    out = _json(response_text(resp))
    out["secs"] = round(secs, 1)
    return out


def read_staff(text: str, items: list[dict]) -> dict:
    resp, _ = post("/responses", {"model": MODEL, "reasoning": {"effort": "low"}, "max_output_tokens": 4000,
                                  "input": [{"type": "message", "role": "user", "content": [
                                      {"type": "input_text", "text": staff_prompt(items)},
                                      {"type": "input_text", "text": "STAFF SAID: " + text}]}]})
    return _json(response_text(resp))


@dataclass
class Check:
    garment: str
    said: int
    seen: int
    confidence: float | None = None

    @property
    def ok(self) -> bool:
        return self.said == self.seen


@dataclass
class Draft:
    lines: list[dict]                 # item_id, name, quantity, rate, total
    total: float
    checks: list[Check]
    unpriced: list[str] = field(default_factory=list)
    partial_photo: bool = False

    @property
    def mismatches(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def needs_staff(self) -> bool:
        return bool(self.mismatches or self.unpriced)


def reconcile(staff_lines: list[dict], photo: dict, items: list[dict]) -> Draft:
    """Price what staff said; compare it, garment by garment, with what the photo shows."""
    by_id = {i["item_id"]: i for i in items}
    lines, unpriced, said = [], [], {}
    for l in staff_lines:
        item = by_id.get(l.get("item_id"))
        qty = float(l.get("quantity") or 0)
        if not item or qty <= 0:
            unpriced.append(l.get("said") or l.get("name") or "an item")
            continue
        lines.append({"item_id": item["item_id"], "name": item["name"], "quantity": qty,
                      "rate": item["rate"], "total": round(qty * item["rate"], 2)})
        g = item["garment"]
        if g:  # charges, starch and by-weight lines are not pieces in the photo
            said[g] = said.get(g, 0) + int(round(qty))

    seen, conf = {}, {}
    for it in photo.get("items", []):
        g = str(it.get("garment", "other")).lower()
        seen[g] = seen.get(g, 0) + int(it.get("count") or 0)
        conf[g] = min(conf.get(g, 1.0), float(it.get("confidence") or 0))
    checks = [Check(g, said.get(g, 0), seen.get(g, 0), conf.get(g)) for g in sorted(set(said) | set(seen))]
    return Draft(lines, round(sum(l["total"] for l in lines), 2), checks, unpriced,
                 partial_photo=photo.get("all_visible") is False)


def staff_message(d: Draft) -> str:
    """What the counter is told. Plain English; the counter staff read English."""
    said_total = sum(c.said for c in d.checks)
    seen_total = sum(c.seen for c in d.checks)
    rows = [f"{l['quantity']:g} x {l['name']} @ Rs {l['rate']:g} = Rs {l['total']:g}" for l in d.lines]
    if not d.needs_staff:
        return f"Photo agrees: {seen_total} pieces.\n" + "\n".join(rows) + f"\nTotal Rs {d.total:g}. Sending to the customer."
    out = []
    if seen_total < said_total:
        out.append(f"You said {said_total} pieces, the photo shows {seen_total}. Send a photo of the rest, or correct the count.")
    elif seen_total > said_total:
        out.append(f"You said {said_total} pieces, the photo shows {seen_total}. Which pieces are missing from your message?")
    for c in d.mismatches:
        out.append(f"- {c.garment}: you said {c.said}, photo shows {c.seen}")
    for u in d.unpriced:
        out.append(f"- not on the price list: {u}")
    return "Check before this goes to the customer.\n" + "\n".join(out) + "\nDraft so far:\n" + "\n".join(rows) + f"\nTotal Rs {d.total:g}"


def load_pricelist(brand: str) -> list[dict]:
    items = json.loads((ROOT / "data" / "pricelist.json").read_text())
    return [i for i in items if i["brand"] == brand]


__all__ = ["read_photo", "read_staff", "reconcile", "staff_message", "load_pricelist", "garment_of", "SERVICES"]
