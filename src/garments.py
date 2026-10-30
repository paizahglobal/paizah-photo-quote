"""Garment classes, and how a laundry's billed item name maps to one.

A Zoho item name carries brand, service and garment ("Prezr_SP_Shirt",
"Luxe_DC_Dhoti / Mundu (Cotton)"). A photo shows the garment, never the
service, so the photo is scored on garment and count only.
"""
import re

# Order matters: the first match wins, so "t-shirt" is tried before "shirt".
CLASSES = [
    ("t-shirt", r"t[\s-]*shirt"),
    ("hoodie", r"hoodie"),
    ("shirt", r"shirt"),
    ("kurta", r"kurta"),
    ("jeans", r"jeans"),
    ("trouser", r"trouser|pant"),
    ("pyjama", r"pyjama"),
    ("dhoti / mundu", r"dhoti|mundu"),
    ("saree", r"saree"),
    ("blouse", r"blouse"),
    ("shawl / stole", r"shawl|stole"),
    ("bedsheet", r"bed\s*sheet"),
    ("blanket", r"blanket"),
    ("pillow / cushion cover", r"pillow|cushion"),
    ("jacket / blazer", r"jacket|blazer"),
    ("coat", r"coat"),
    ("frock", r"frock"),
    ("skirt and top set", r"skirt"),
    ("seat cover", r"seat cover"),
    ("shoes (pair)", r"shoe"),
]
GARMENTS = [name for name, _ in CLASSES]

# Lines that are not a piece in the photo: charges, add-ons, and work by weight.
NOT_A_PIECE = re.compile(r"pick\s*up|delivery|starching", re.I)
BY_WEIGHT = re.compile(r"per kg|by weight", re.I)


def garment_of(item_name: str) -> str | None:
    if NOT_A_PIECE.search(item_name) or BY_WEIGHT.search(item_name):
        return None
    low = item_name.lower()
    for name, pattern in CLASSES:
        if re.search(pattern, low):
            return name
    return "other"


def truth(lines: list[dict]) -> tuple[dict[str, int], bool]:
    """Garment counts from a quote's lines, and whether any line was by weight
    (a by-weight lot cannot be counted from the photo)."""
    counts: dict[str, int] = {}
    by_weight = False
    for line in lines:
        if BY_WEIGHT.search(line["name"]):
            by_weight = True
        g = garment_of(line["name"])
        if g:
            counts[g] = counts.get(g, 0) + int(round(line["quantity"]))
    return counts, by_weight
