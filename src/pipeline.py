"""One lot, start to finish: photos and staff words in, the reply out.

Two kinds of lot:
- intake (the default): count, price, damage check; recorded per customer.
- handover ("handover 98470 00000"): the photo of what is going back, counted
  and compared with what was billed at intake.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from garments import garment_of
from lots import is_handover, last_intake, phone_in, record_intake
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


def _seen(photo: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in photo.get("items", []):
        g = str(it.get("garment", "other")).lower()
        out[g] = out.get(g, 0) + int(it.get("count") or 0)
    return out


def counted_caption(prefix: str, expected: dict[str, int], boxed: dict[str, int]) -> str:
    """The caption carries the reading's count; the boxes may be fewer when pieces are stacked."""
    plural = lambda n, g: f"{n} {g}" + ("" if n == 1 or g.endswith("s") else "s")
    text = prefix + ", ".join(plural(n, g) for g, n in expected.items())
    pieces_boxed = sum(v for g, v in boxed.items() if g != "stain")
    if 0 < pieces_boxed < sum(expected.values()):
        text += ". Stacked pieces share a box"
    if boxed.get("stain"):
        text += ". Damage circled in red"
    return text


def build_reply(photos: list[Path], words: str, work: Path) -> tuple[str, bytes, str]:
    """Returns the text for staff, the counted photo, and its caption."""
    if is_handover(words):
        return build_handover(photos, words, work)
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
    customer = staff.get("customer_phone") or phone_in(words)
    head = f"Customer {customer}\n" if customer else "No customer number heard. Send it as a reply.\n"
    text = head + staff_message(draft) + "\n" + damage_note(damage) + f"\n({secs:.0f} s)"

    # The picture shows what the photo reading counted, no more, plus where the stains are.
    expected = {c.garment: c.seen for c in draft.checks if c.seen}
    marks = [i["look_for"] for i in damage.get("issues", []) if i.get("look_for")]
    out = work / f"{photos[0].stem}-counted.jpg"
    counts = counted_photo(photos[0], expected, out, marks=marks)
    caption = counted_caption("Counted at the counter: ", expected, counts)

    if customer:
        # What staff billed is what must come back; the photo count is the check on it.
        billed: dict[str, int] = {}
        for line in draft.lines:
            g = garment_of(line["name"])
            if g:
                billed[g] = billed.get(g, 0) + int(round(line["quantity"]))
        record_intake(customer, billed, _seen(photo), damage.get("issues", []), photos[0])
    return text, out.read_bytes(), caption


def build_handover(photos: list[Path], words: str, work: Path) -> tuple[str, bytes, str]:
    customer = phone_in(words)
    if not customer:
        return ("Handover needs the customer's number, e.g. \"handover 98470 00000\".", b"", "")
    intake = last_intake(customer)
    if not intake:
        return (f"No intake on record for {customer}. Was the lot photographed at the counter?", b"", "")
    started = time.time()
    photo = read_photo(photos)
    seen = _seen(photo)
    came_in = intake["billed"] or intake["seen"]
    n_in, n_out = sum(came_in.values()), sum(seen.values())
    short = {g: n - seen.get(g, 0) for g, n in came_in.items() if seen.get(g, 0) < n}
    extra = {g: n - came_in.get(g, 0) for g, n in seen.items() if n > came_in.get(g, 0)}

    if not short and not extra:
        head = f"Customer {customer}: {n_in} in on {intake['at']}, {n_out} going out. All there."
    else:
        rows = [f"- missing {n} {g}" for g, n in short.items()] + [f"- {n} {g} not in the intake" for g, n in extra.items()]
        head = (f"Customer {customer}: {n_in} in on {intake['at']}, the photo shows {n_out}. "
                "Check before the bag leaves:\n" + "\n".join(rows))
    if intake.get("damage"):
        head += "\nRecorded at intake, before washing:\n" + "\n".join(
            f"- {i.get('piece')}: {i.get('issue')}, {i.get('where')}" for i in intake["damage"])
    text = head + f"\n({time.time() - started:.0f} s)"

    out = work / f"{photos[0].stem}-handover.jpg"
    counts = counted_photo(photos[0], seen, out)
    caption = counted_caption(f"Handed over {n_out} of {n_in}: ", seen, counts)
    return text, out.read_bytes(), caption
