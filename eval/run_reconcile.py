"""Score the two-check rule on the real quotes, with no new model calls.

Staff side: the lines the live bot first read from staff's voice note or text.
Photo side: the latest Muse Spark photo reads (eval/results/counts-low-*.json).
Truth: the quote as invoiced.

    python3 -I eval/run_reconcile.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from quote import garment_of, reconcile, staff_message  # noqa: E402

items = json.loads((ROOT / "data" / "pricelist.json").read_text())
by_name = {i["name"]: i for i in items}
latest = sorted((ROOT / "eval" / "results").glob("counts-low-*.json"))[-1]
photo_rows = {r["quote"]: r for r in json.loads(latest.read_text())}

tally = {"auto_right": 0, "auto_wrong": 0, "flag_caught": 0, "flag_false_alarm": 0}
examples = {}
reasons = {}
for q, pr in photo_rows.items():
    if pr["by_weight"] or "muse_items" not in pr:
        continue
    d = json.loads((ROOT / "data" / "prezr" / f"{q}.json").read_text())
    staff = [{"item_id": by_name[l["name"]]["item_id"], "quantity": l["quantity"]}
             for l in d["bot_first_read"]["lines"] if l["name"] in by_name]
    draft = reconcile(staff, {"items": pr["muse_items"], "all_visible": pr["muse_all_visible"]}, items)
    # Right means the staff draft is what was finally billed, item for item.
    # Zoho holds two shoe-cleaning items that differ only in capitals: one item.
    billed = sorted((l["name"].lower(), l["quantity"]) for l in d["lines"])
    drafted = sorted((l["name"].lower(), l["quantity"]) for l in draft.lines)
    right = billed == drafted
    key = ("flag_false_alarm" if right else "flag_caught") if draft.needs_staff else ("auto_right" if right else "auto_wrong")
    tally[key] += 1
    if key == "auto_wrong":
        # Why it was wrong: a piece the photo should have seen, or something no photo shows.
        def pieces(ls):
            out = {}
            for name, qty in ls:
                g = garment_of(name)
                if g:
                    out[g] = out.get(g, 0) + qty
            return out
        same_pieces = pieces(billed) == pieces(drafted)
        added_only = set(drafted) <= set(billed) and all(garment_of(n) is None for n, _ in set(billed) - set(drafted))
        why = "added later (starch, delivery)" if added_only else "service changed" if same_pieces else "pieces wrong"
        reasons[why] = reasons.get(why, 0) + 1
    examples.setdefault(key, staff_message(draft))

n = sum(tally.values())
print(json.dumps({**tally, "quotes": n,
                  "sent_without_a_look_pct": round(100 * (tally["auto_right"] + tally["auto_wrong"]) / n, 1),
                  "of_those_right_pct": round(100 * tally["auto_right"] / max(1, tally["auto_right"] + tally["auto_wrong"]), 1),
                  "auto_wrong_why": reasons, "staff_errors_caught_pct": round(100 * tally["flag_caught"] / max(1, tally["flag_caught"] + tally["auto_wrong"]), 1)},
                 indent=1))
print("\n--- example, sent without a look ---\n" + examples.get("auto_right", ""))
print("\n--- example, caught ---\n" + examples.get("flag_caught", ""))
