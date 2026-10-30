"""One lot, start to finish: photos and staff words in, the reply out."""
import os
import time
from pathlib import Path

from quote import load_pricelist, read_photo, read_staff, reconcile, staff_message
from receipt import counted_photo

BRAND = os.environ.get("BRAND", "prezr")


def build_reply(photos: list[Path], words: str, work: Path) -> tuple[str, bytes, str]:
    """Returns the text for staff, the counted photo, and its caption."""
    items = load_pricelist(BRAND)
    started = time.time()
    photo = read_photo(photos)
    staff = read_staff(words, items)
    draft = reconcile(staff.get("lines", []), photo, items)
    secs = time.time() - started
    customer = staff.get("customer_phone")
    head = f"Customer {customer}\n" if customer else "No customer number heard.\n"
    text = head + staff_message(draft) + f"\n({secs:.0f} s)"

    garments = [c.garment for c in draft.checks if c.seen] or ["garment"]
    out = work / f"{photos[0].stem}-counted.jpg"
    counts = counted_photo(photos[0], garments, out)
    caption = "Counted at the counter: " + ", ".join(f"{n} {g}" for g, n in counts.items())
    return text, out.read_bytes(), caption
