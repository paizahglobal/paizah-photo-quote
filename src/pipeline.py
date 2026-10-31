"""One lot, start to finish: photos and staff words in, the reply out."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from quote import load_pricelist, read_damage, read_photo, read_staff, reconcile, staff_message
from receipt import counted_photo

BRAND = os.environ.get("BRAND", "prezr")


def damage_note(damage: dict) -> str:
    issues = damage.get("issues", [])
    if not issues:
        return "\nNo stains or damage seen. Folded pieces were checked on the side that shows."
    rows = [f"- {i.get('piece')}: {i.get('issue')}, {i.get('where')}" for i in issues]
    return ("\nNoted before washing (please check, and tell the customer):\n" + "\n".join(rows)
            + "\nFolded pieces were checked on the side that shows.")


def build_reply(photos: list[Path], words: str, work: Path) -> tuple[str, bytes, str]:
    """Returns the text for staff, the counted photo, and its caption."""
    items = load_pricelist(BRAND)
    started = time.time()
    # The count and the damage check read the same photos; neither waits for the other.
    with ThreadPoolExecutor(max_workers=2) as pool:
        photo_job = pool.submit(read_photo, photos)
        damage_job = pool.submit(read_damage, photos)
        photo = photo_job.result()
        staff = read_staff(words, items, photo)
        damage = damage_job.result()
    draft = reconcile(staff.get("lines", []), photo, items)
    secs = time.time() - started
    customer = staff.get("customer_phone")
    head = f"Customer {customer}\n" if customer else "No customer number heard. Send it as a reply.\n"
    text = head + staff_message(draft) + "\n" + damage_note(damage) + f"\n({secs:.0f} s)"

    # The picture shows what the photo reading counted, no more, plus where the stains are.
    expected = {c.garment: c.seen for c in draft.checks if c.seen}
    marks = 1 if any(i.get("issue") in ("stain", "discolouration") for i in damage.get("issues", [])) else 0
    out = work / f"{photos[0].stem}-counted.jpg"
    counts = counted_photo(photos[0], expected, out, stains=marks)
    caption = "Counted at the counter: " + ", ".join(f"{n} {g}" for g, n in counts.items() if g != "stain")
    if counts.get("stain"):
        caption += f". Stains marked in red: {counts['stain']}"
    return text, out.read_bytes(), caption
