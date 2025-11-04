import json, sys

src = sys.argv[1]
dst = sys.argv[2]

with open(src, "r", encoding="utf-8") as f:
    data = json.load(f)

flat = []
# v1: {"timeline":[{"t_ms":..,"euler":{"yaw_deg":..,"pitch_deg":..,"roll_deg":..},"bbox":{...}}, ...]}
for item in data.get("timeline", []):
    e = item.get("euler", {})
    flat.append({
        "t_ms": item["t_ms"],
        "yaw": e.get("yaw_deg", 0.0),
        "pitch": e.get("pitch_deg", 0.0),
        "roll": e.get("roll_deg", 0.0),
        "bbox": item.get("bbox", None)
    })

# 👇 フラット配列で出力（ラップしない）
with open(dst, "w", encoding="utf-8") as f:
    json.dump(flat, f, ensure_ascii=False, indent=2)
