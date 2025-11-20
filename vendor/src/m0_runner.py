# ======================================================
# vendor/src/m0_runner.py  (FULL UPDATED: transform pass)
# ======================================================
from __future__ import annotations
import argparse, os, json, shutil, time
from typing import Dict, Any
from pathlib import Path

import yaml

# -----------------------------
# 基本ユーティリティ
# -----------------------------
def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    txt = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        return yaml.safe_load(txt) or {}
    # JSONも許容
    return json.loads(txt)

def deep_update(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base

def _safe_get_float(d: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in d:
            try:
                return float(d[k])
            except Exception:
                pass
    return float(default)

# -----------------------------
# エイリアス（フォルダ）作成
# -----------------------------
def _mk_tmp_assets_with_alias(src_assets: Path, exp_dir: Path, alias: Dict[str,str]) -> Path:
    """
    assets_dir配下に view名の別名（エイリアス）を用意する。
    例: {"left30": "down15", "right30": "up15"} → tmp_assets/left30 -> tmp_assets/down15
    symlinkが使えない環境ではコピーにフォールバック。
    """
    tmp = exp_dir / "tmp_assets"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src_assets, tmp, dirs_exist_ok=True)

    def link_or_copy(src: Path, dst: Path):
        if dst.exists():  # 既にあるなら触らない
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            rel = os.path.relpath(src, dst.parent)
            os.symlink(rel, dst)
        except Exception:
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    # 片方向（dst→src）で作る
    for dst_name, src_name in alias.items():
        src_path = tmp / src_name
        dst_path = tmp / dst_name
        if src_path.exists():
            link_or_copy(src_path, dst_path)

    return tmp

# -----------------------------
# atlas 深度置換
# -----------------------------
def _json_deep_replace(obj, replace_map: Dict[str, str]):
    from collections.abc import Mapping, Sequence
    if isinstance(obj, Mapping):
        return {k: _json_deep_replace(v, replace_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_deep_replace(v, replace_map) for v in obj]
    if isinstance(obj, str):
        s = obj
        for old, new in replace_map.items():
            s = s.replace(old, new)
        return s
    return obj

def _rewrite_atlas_for_alias(base_atlas_path: Path, tmp_assets_dir: Path, view_alias: Dict[str, str]) -> Path:
    """
    atlas.min.json 内の全パス文字列に対し、view_aliasに基づく置換を施した
    「別名対応版atlas」を生成して返す。
    - 例: {"left30":"down15"} → "/left30/" を "/down15/" に
    """
    # 置換ルール作成（両方の表記に対応）
    # "/left30/" → "/down15/"、 "left30/" → "down15/"
    pairs = {}
    for dst, src in view_alias.items():
        pairs[f"/{dst}/"] = f"/{src}/"
        pairs[f"{dst}/"]  = f"{src}/"

    text = base_atlas_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        new_data = _json_deep_replace(data, pairs)
        out = tmp_assets_dir / "atlas.alias.json"
        out.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return out
    except Exception:
        # JSONでないor読めない場合でも、単純置換でフォールバック
        for old, new in pairs.items():
            text = text.replace(old, new)
        out = tmp_assets_dir / "atlas.alias.json"
        out.write_text(text, encoding="utf-8")
        return out

# -----------------------------
# Timeline／レンダラー読み込み
# -----------------------------
def _import_timeline_and_render():
    # 依存を遅延import（環境依存のため）
    from src.timeline import Timeline
    from src.render_core import render_video
    return Timeline, render_video

# -----------------------------
# 値マージ・軸適用
# -----------------------------
def _build_merged_value_fn(mouth_tl, pose_tl, expr_tl,
                           value_key: str, thr_front: float, map_deg: float):
    """
    value_key が yaw 以外（pitch/roll）の場合、擬似yaw（±map_deg or 0）を注入して返す。
    """
    def merged_value(t_ms: int) -> Dict[str, Any]:
        vals = {}
        vals.update(mouth_tl.value_at(t_ms))
        vals.update(pose_tl.value_at(t_ms))
        vals.update(expr_tl.value_at(t_ms))

        if value_key == "yaw":
            return vals

        v = None
        if value_key == "pitch":
            v = _safe_get_float(vals, "pitch_deg", "pitch", default=None)
        elif value_key == "roll":
            v = _safe_get_float(vals, "roll_deg", "roll", default=None)

        if v is None:
            pseudo = 0.0
        else:
            pseudo = 0.0 if abs(v) <= thr_front else (map_deg if v > 0 else -map_deg)

        vals["yaw"] = pseudo
        vals["yaw_deg"] = pseudo
        return vals
    return merged_value

# -----------------------------
# メイン
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)          # JSON or YAML
    ap.add_argument("--override", action="append", default=[])
    args = ap.parse_args()

    # 設定ロード
    cfg = load_yaml(args.config)
    for o in args.override:
        cfg = deep_update(cfg, load_yaml(o))

    assets_dir = Path(cfg["io"]["assets_dir"]).resolve()
    out_dir    = Path(cfg["io"]["out_dir"]).resolve()
    exp_name   = cfg["io"]["exp_name"]

    width       = int(cfg["video"]["width"])
    height      = int(cfg["video"]["height"])
    fps         = int(cfg["video"]["fps"])
    duration_s  = int(cfg["video"]["duration_s"])
    crossfade   = int(cfg["render"]["crossfade_frames"])

    # メトリクス・切替設定（Option A：alias＋atlas書き換え）
    mconf       = cfg.get("metrics", {}) or {}
    value_key   = str(mconf.get("value_key", "yaw"))     # "yaw" / "pitch" / "roll"
    thr_front   = float(mconf.get("thr_front", 16.0))    # ±閾値[deg]
    zero_label  = str(mconf.get("zero_label", "front"))  # ラベル（ログ用）
    neg_label   = str(mconf.get("neg_label",  "left30"))
    pos_label   = str(mconf.get("pos_label",  "right30"))
    map_deg     = float(mconf.get("map_deg", 30.0))      # 擬似yawの±度数
    view_alias  = dict(mconf.get("view_alias", {}))      # {"left30":"down15","right30":"up15",...}

    # transform 設定（render_core へ透過）
    transform_cfg = cfg.get("transform")  # そのまま渡す（enabled: False なら render_core 側でno-op）

    # pitch/roll で alias 未指定なら、一般的な既定を補完
    if value_key != "yaw" and not view_alias:
        if value_key == "pitch":
            view_alias = {"left30": "down15", "right30": "up15", "front": "front"}
        else:
            view_alias = {"front": "front", "left30": "left30", "right30": "right30"}

    # パス解決ヘルパ
    def _abs_assets(p: str) -> str:
        return p if os.path.isabs(p) else str(assets_dir / p)

    # タイムライン読み込み
    Timeline, render_video = _import_timeline_and_render()
    inputs = cfg.get("inputs", {})
    mouth_tl = Timeline.load_json(_abs_assets(inputs["mouth_timeline"])) if "mouth_timeline" in inputs else Timeline([])
    pose_tl  = Timeline.load_json(_abs_assets(inputs["pose_timeline"]))  if "pose_timeline"  in inputs else Timeline([])
    expr_tl  = Timeline.load_json(_abs_assets(inputs["expression_timeline"])) if "expression_timeline" in inputs else Timeline([])

    # 出力先
    exp_dir  = out_dir / exp_name
    exp_dir.mkdir(parents=True, exist_ok=True)
    out_mp4  = exp_dir / "demo.mp4"

    # assets の有効ディレクトリ（alias適用）
    use_assets_dir = assets_dir
    if value_key != "yaw" and view_alias:
        use_assets_dir = _mk_tmp_assets_with_alias(assets_dir, exp_dir, view_alias)

    # atlas の有効パス（alias適用で深度置換）
    atlas_json_rel = cfg.get("atlas", {}).get("atlas_json", None)
    atlas_json_for_render = atlas_json_rel
    if atlas_json_rel and (value_key != "yaw") and view_alias:
        base_atlas = Path(atlas_json_rel)
        if not base_atlas.is_absolute():
            base_atlas = use_assets_dir / atlas_json_rel
        if base_atlas.exists():
            atlas_json_for_render = str(_rewrite_atlas_for_alias(base_atlas, use_assets_dir, view_alias))

    # 値マージ関数（擬似yaw注入）
    merged_value = _build_merged_value_fn(mouth_tl, pose_tl, expr_tl,
                                          value_key=value_key, thr_front=thr_front, map_deg=map_deg)

    # 実行
    t0 = time.time()
    stats = render_video(
        str(out_mp4),
        width, height, fps, duration_s, crossfade,
        merged_value,
        assets_dir=str(use_assets_dir),
        atlas_json_rel=atlas_json_for_render,
        transform_cfg=transform_cfg,
    )
    elapsed = round(time.time() - t0, 3)

    # ログ
    run_log = {
        "out_mp4": str(out_mp4),
        "fps": fps, "duration_s": duration_s, "frames": int(duration_s * fps),
        "assets_dir": str(assets_dir),
        "assets_dir_effective": str(use_assets_dir),
        "exp_name": exp_name,
        "elapsed_s": elapsed,
        "axis": value_key,
        "thr_front_deg": thr_front,
        "map_deg": map_deg,
        "labels": {"zero": zero_label, "neg": neg_label, "pos": pos_label},
        "view_alias": view_alias,
    }
    run_log.update(stats or {})

    (exp_dir / "run.log.json").write_text(json.dumps(run_log, ensure_ascii=False, indent=2), encoding="utf-8")

    # summary.csv（簡易）
    summary_keys = ["exp_name", "duration_s", "elapsed_s", "fallback_frames", "first_fallback_ms"]
    with (exp_dir / "summary.csv").open("w", encoding="utf-8") as f:
        f.write("key,value\n")
        for k in summary_keys:
            if k in run_log:
                f.write(f"{k},{run_log[k]}\n")
        views = run_log.get("views", {})
        for name, count in views.items():
            f.write(f"views_{name},{count}\n")

if __name__ == "__main__":
    main()
