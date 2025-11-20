from __future__ import annotations
import json
from pathlib import Path


def main() -> None:
    atlas_path = Path("tests/assets_min/atlas.min.json")
    expr_path = Path("tests/assets_min/timelines/expression_phaseB_long.json")

    atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
    exp_tl = json.loads(expr_path.read_text(encoding="utf-8"))

    # atlas 側の expression_labels
    atlas_labels = set(atlas.get("expression_labels", []))

    # expression タイムライン側（ルートが dict の場合 / list の場合 両方に対応）
    if isinstance(exp_tl, dict):
        events = exp_tl.get("events", [])
    elif isinstance(exp_tl, list):
        events = exp_tl
    else:
        print(f"Unexpected timeline root type: {type(exp_tl)}")
        return

    exp_labels = {
        ev["expression"]
        for ev in events
        if isinstance(ev, dict) and "expression" in ev
    }

    print("atlas_labels       :", atlas_labels)
    print("timeline_labels    :", exp_labels)
    print("extra_in_timeline  :", exp_labels - atlas_labels)
    print("missing_in_timeline:", atlas_labels - exp_labels)


if __name__ == "__main__":
    main()
