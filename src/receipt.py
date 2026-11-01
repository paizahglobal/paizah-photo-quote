"""The counted photo: every piece SAM 3.1 finds, boxed and numbered.

This is what the customer receives with the quote, and what settles "I gave you
twelve shirts" later. SAM is asked for each garment the reading named ("shirt",
"kurta"), because a garment's own name finds pieces that "garment" merges.
"""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from meta_api import image_data_url, post, response_text

COLOURS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324", "#800000"]


def boxes(photo: Path, word: str) -> list[tuple[int, int, int, int, float]]:
    resp, _ = post("/responses", {"model": "sam-3.1", "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
                                  "input": [{"type": "message", "role": "user", "content": [
                                      {"type": "input_text", "text": word},
                                      {"type": "input_image", "image_url": image_data_url(photo)}]}]})
    out = []
    for b in re.findall(r"<\|box;([^|]*)\|>", response_text(resp)):
        kv = dict(p.split("=", 1) for p in b.split(";"))
        out.append((int(kv["x1"]), int(kv["y1"]), int(kv["x2"]), int(kv["y2"]), float(kv.get("c", 1))))
    return out


def _overlap(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small else 0


def counted_photo(photo: Path, expected: dict[str, int], out: Path, min_conf: float = 0.5,
                  stains: int = 0) -> dict[str, int]:
    """Box each piece, never more boxes for a garment than the reading counted.

    ★ THE PICTURE MUST AGREE WITH THE QUOTE. On a real Luxe lot (30 Oct) SAM
    boxed one folded stack of pillow covers three times: six boxes for four
    covers, beside a quote that said four. So per garment the most confident
    boxes are kept up to the reading's count, and "garment" fills only what the
    garment names missed, up to the total.
    """
    img = Image.open(photo).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=max(24, img.width // 30))
    chosen: list[tuple[tuple, str, str]] = []   # box, label, colour
    def free(b):
        return b[4] >= min_conf and not any(_overlap(b, k) > 0.6 for k, _, _ in chosen)
    for i, (g, n) in enumerate(expected.items()):
        colour = COLOURS[i % len(COLOURS)]
        for b in sorted(boxes(photo, g), key=lambda b: -b[4]):
            if sum(1 for _, lab, _ in chosen if lab == g) >= n:
                break
            if free(b):
                chosen.append((b, g, colour))
    missing = sum(expected.values()) - len(chosen)
    if missing > 0:
        for b in sorted(boxes(photo, "garment"), key=lambda b: -b[4]):
            if missing <= 0:
                break
            if free(b):
                chosen.append((b, "piece", "#555555"))
                missing -= 1
    counts: dict[str, int] = {}
    for n, (b, g, colour) in enumerate(sorted(chosen, key=lambda c: (c[0][1], c[0][0])), start=1):
        counts[g] = counts.get(g, 0) + 1
        draw.rectangle(b[:4], outline=colour, width=max(4, img.width // 250))
        label = f"{n} {g}"
        x, y = b[0] + 8, b[1] + 8
        tw, th = draw.textbbox((0, 0), label, font=font)[2:]
        draw.rectangle((x - 4, y - 4, x + tw + 4, y + th + 8), fill=colour)
        draw.text((x, y), label, fill="white", font=font)
    if stains:
        # Only when the reading saw a stain: SAM alone also finds shadows and prints.
        for b in boxes(photo, "stain"):
            if b[4] < 0.4:
                continue
            counts["stain"] = counts.get("stain", 0) + 1
            draw.ellipse(b[:4], outline="#ff0000", width=max(6, img.width // 160))
            x, y = b[0] + 8, b[3] - font.size - 16
            tw, th = draw.textbbox((0, 0), "stain", font=font)[2:]
            draw.rectangle((x - 4, y - 4, x + tw + 4, y + th + 8), fill="#ff0000")
            draw.text((x, y), "stain", fill="white", font=font)
    img.save(out, quality=85)
    return counts
