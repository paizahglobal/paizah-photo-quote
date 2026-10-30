"""Score the photo against what was billed: garment and count, per quote.

    python3 -I eval/run_counts.py [--limit N] [--effort minimal|low|medium]

Muse Spark reads every photo of a quote in one request and returns counts per
garment class. SAM 3.1 counts "garment" in each photo, summed. Results go to
eval/results/ (git-ignored: they describe customers' lots).
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from garments import GARMENTS, truth  # noqa: E402
from meta_api import image_data_url, post, response_text  # noqa: E402

DATA = ROOT / "data" / "prezr"
OUT = ROOT / "eval" / "results"

PROMPT = f"""You are the intake desk of a laundry in Kerala, India. The photo(s) show ONE customer's lot, laid out at the counter.
Count every piece. A pair of shoes is one piece. Folded or stacked pieces count separately; look at edges and collars to separate a stack.
Use only these garment names: {", ".join(GARMENTS)}, other.
A dhoti or mundu is a white or cream unstitched cloth, often with a gold or coloured border. A kurta is a long tunic, longer than a shirt.
If some pieces are hidden (inside a bag, under others), say so.
Reply with JSON only, no prose:
{{"items": [{{"garment": "<name>", "count": <int>, "confidence": <0..1>}}], "total": <int>, "all_visible": <true|false>}}"""


def muse(photos: list[Path], effort: str) -> tuple[dict, float, dict]:
    content = [{"type": "input_text", "text": PROMPT}]
    content += [{"type": "input_image", "image_url": image_data_url(p)} for p in photos]
    resp, secs = post("/responses", {
        "model": "muse-spark-1.3",
        "input": [{"type": "message", "role": "user", "content": content}],
        "reasoning": {"effort": effort},
        "max_output_tokens": 8000,
    })
    text = response_text(resp)
    m = re.search(r"\{.*\}", text, re.S)
    parsed = json.loads(m.group(0)) if m else {"items": [], "total": None, "error": text[:300]}
    return parsed, secs, resp.get("usage", {})


def sam(photo: Path) -> tuple[int, float]:
    resp, secs = post("/responses", {
        "model": "sam-3.1",
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "garment"},
            {"type": "input_image", "image_url": image_data_url(photo)},
        ]}],
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
    })
    return len(re.findall(r"<\|box;", response_text(resp))), secs


def one(answer_file: Path, effort: str) -> dict:
    d = json.loads(answer_file.read_text())
    want, by_weight = truth(d["lines"])
    photos = [DATA / p for p in d["photos"]]
    row = {"quote": answer_file.stem, "brand": d["brand"], "status": d["status"], "photos": len(photos),
           "by_weight": by_weight, "truth": want, "truth_total": sum(want.values())}
    try:
        parsed, secs, usage = muse(photos, effort)
        got: dict[str, int] = {}
        for it in parsed.get("items", []):
            g = str(it.get("garment", "other")).lower()
            got[g] = got.get(g, 0) + int(it.get("count") or 0)
        row.update(muse=got, muse_total=sum(got.values()), muse_all_visible=parsed.get("all_visible"),
                   muse_secs=round(secs, 1), muse_in=usage.get("input_tokens"), muse_out=usage.get("output_tokens"),
                   muse_items=parsed.get("items", []))
    except Exception as e:  # one bad quote must not stop the run
        row["muse_error"] = str(e)[:300]
    try:
        counts = [sam(p) for p in photos]
        row.update(sam_total=sum(c for c, _ in counts), sam_secs=round(sum(s for _, s in counts), 1))
    except Exception as e:
        row["sam_error"] = str(e)[:300]
    return row


def summarise(rows: list[dict]) -> dict:
    countable = [r for r in rows if not r["by_weight"] and r["truth_total"] > 0 and "muse_total" in r]
    def rate(key, tol):
        ok = [r for r in countable if key in r and abs(r[key] - r["truth_total"]) <= tol]
        return round(100 * len(ok) / len(countable), 1) if countable else None
    pieces_true = sum(r["truth_total"] for r in countable)
    pieces_matched = sum(sum(min(r["muse"].get(g, 0), n) for g, n in r["truth"].items()) for r in countable)
    pieces_said = sum(r["muse_total"] for r in countable)
    usd = sum((r.get("muse_in") or 0) * 1.25e-6 + (r.get("muse_out") or 0) * 4.25e-6 for r in rows) \
        + sum(r["photos"] for r in rows) * 0.0025
    return {
        "quotes": len(rows), "countable": len(countable),
        "muse_total_exact_pct": rate("muse_total", 0), "muse_total_within1_pct": rate("muse_total", 1),
        "sam_total_exact_pct": rate("sam_total", 0), "sam_total_within1_pct": rate("sam_total", 1),
        "garment_recall_pct": round(100 * pieces_matched / pieces_true, 1) if pieces_true else None,
        "garment_precision_pct": round(100 * pieces_matched / pieces_said, 1) if pieces_said else None,
        "muse_secs_median": sorted(r["muse_secs"] for r in countable)[len(countable) // 2] if countable else None,
        "cost_usd": round(usd, 3),
        "errors": sum(1 for r in rows if "muse_error" in r or "sam_error" in r),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    files = sorted(DATA.glob("*.json"))[: args.limit]
    started = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda f: one(f, args.effort), files))
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    (OUT / f"counts-{args.effort}-{stamp}.json").write_text(json.dumps(rows, indent=1))
    s = summarise(rows)
    s["effort"], s["wall_secs"] = args.effort, round(time.time() - started)
    (OUT / f"summary-{args.effort}-{stamp}.json").write_text(json.dumps(s, indent=1))
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
