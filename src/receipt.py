"""The counted photo: every piece SAM 3.1 finds, boxed and numbered.

This is what the customer receives with the quote, and what settles "I gave you
twelve shirts" later. SAM is asked for each garment the reading named ("shirt",
"kurta"), because a garment's own name finds pieces that "garment" merges.
"""
import base64
import io
import json
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


def name_pieces(img: Image.Image, found: list[tuple], allowed: dict[str, int]) -> list[str]:
    """SAM finds a piece it cannot name (dark garments defeat "t-shirt"); Muse Spark names it.

    One request with every crop, answers limited to the garments still owed,
    so a box can never be named something the reading did not count.
    """
    if not found or not allowed:
        return ["piece"] * len(found)
    content = [{"type": "input_text", "text":
        f"Each image is one piece of clothing from a laundry lot, in order. Name each one, choosing ONLY from: "
        f"{', '.join(allowed)}. Reply with a JSON list of names, one per image, nothing else."}]
    for b in found:
        crop = img.crop(b[:4]).convert("RGB")
        crop.thumbnail((512, 512))
        buf = io.BytesIO()
        crop.save(buf, "JPEG", quality=80)
        content.append({"type": "input_image",
                        "image_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()})
    try:
        resp, _ = post("/responses", {"model": "muse-spark-1.3", "reasoning": {"effort": "low"}, "max_output_tokens": 2000,
                                      "input": [{"type": "message", "role": "user", "content": content}]})
        names = json.loads(re.search(r"\[.*\]", response_text(resp), re.S).group(0))
    except Exception:
        return ["piece"] * len(found)
    owed, out = dict(allowed), []
    for n in names[:len(found)]:
        n = str(n).lower()
        if owed.get(n, 0) > 0:
            owed[n] -= 1
            out.append(n)
        else:
            out.append("piece")
    return out + ["piece"] * (len(found) - len(out))


def _overlap(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small else 0


def counted_photo(photo: Path, expected: dict[str, int], out: Path, min_conf: float = 0.5,
                  marks: list[str] | None = None) -> dict[str, int]:
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
        extra = []
        for b in sorted(boxes(photo, "clothing"), key=lambda b: -b[4]):
            if len(extra) >= missing:
                break
            if free(b) and not any(_overlap(b, e) > 0.6 for e in extra):
                extra.append(b)
        owed = {g: n - sum(1 for _, lab, _ in chosen if lab == g) for g, n in expected.items()}
        owed = {g: n for g, n in owed.items() if n > 0}
        order = list(expected)
        for b, name in zip(extra, name_pieces(img, extra, owed)):
            colour = COLOURS[order.index(name) % len(COLOURS)] if name in order else "#555555"
            chosen.append((b, name, colour))
    counts: dict[str, int] = {}
    for n, (b, g, colour) in enumerate(sorted(chosen, key=lambda c: (c[0][1], c[0][0])), start=1):
        counts[g] = counts.get(g, 0) + 1
        draw.rectangle(b[:4], outline=colour, width=max(4, img.width // 250))
        label = f"{n} {g}"
        x, y = b[0] + 8, b[1] + 8
        tw, th = draw.textbbox((0, 0), label, font=font)[2:]
        draw.rectangle((x - 4, y - 4, x + tw + 4, y + th + 8), fill=colour)
        draw.text((x, y), label, fill="white", font=font)
    # Muse Spark says what the damage looks like ("white mark"); SAM finds it by those words.
    # "stain" alone found nothing on small white marks on a black T-shirt (4 Nov).
    seen_marks: list[tuple] = []
    for phrase in marks or []:
        for b in boxes(photo, phrase):
            if b[4] < 0.5 or any(_overlap(b, m) > 0.5 for m in seen_marks):
                continue
            seen_marks.append(b)
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            r = max(35, (b[2] - b[0]) / 2 + 15, (b[3] - b[1]) / 2 + 15)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline="#ff0000", width=max(5, img.width // 200))
    if seen_marks:
        counts["stain"] = len(seen_marks)
        top = min(seen_marks, key=lambda b: b[1])
        x, y = max(8, top[0] - 20), max(8, top[1] - font.size - 60)
        tw, th = draw.textbbox((0, 0), "damage", font=font)[2:]
        draw.rectangle((x - 4, y - 4, x + tw + 4, y + th + 8), fill="#ff0000")
        draw.text((x, y), "damage", fill="white", font=font)
    img.save(out, quality=85)
    return counts
