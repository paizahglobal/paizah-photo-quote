"""Day 1 smoke test: one Muse Spark call and one SAM 3.1 call on a local photo.

    python3 eval/smoke.py path/to/photo.jpg
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from meta_api import image_data_url, post, response_text  # noqa: E402

photo = Path(sys.argv[1])
img = image_data_url(photo)

spark, secs = post("/responses", {
    "model": "muse-spark-1.3",
    "input": [{
        "type": "message", "role": "user",
        "content": [
            {"type": "input_text", "text": "List every garment in this photo, one per line, as: count x garment."},
            {"type": "input_image", "image_url": img},
        ],
    }],
})
print(f"--- muse-spark-1.3 ({secs:.1f}s) usage={json.dumps(spark.get('usage'))}")
print(response_text(spark))

sam, secs = post("/responses", {
    "model": "sam-3.1",
    "input": [{
        "type": "message", "role": "user",
        "content": [
            {"type": "input_text", "text": "garment"},
            {"type": "input_image", "image_url": img},
        ],
    }],
    "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
})
text = response_text(sam)
boxes = re.findall(r"<\|box;([^|]*)\|>", text)
print(f"--- sam-3.1 ({secs:.1f}s): {len(boxes)} garments")
for b in boxes:
    print("  ", b)
