from __future__ import annotations
import os, json
from typing import Dict, Any
import numpy as np
import cv2

# -----------------------------
# 画像I/Oユーティリティ
# -----------------------------
def _load_rgba(path: str) -> np.ndarray:
    """PNGなどを BGRA で読む。アルファ無しなら255で補完。"""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 2:
        # グレースケール → BGRA
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        b, g, r = cv2.split(img)
        a = np.full_like(b, 255)
        img = cv2.merge([b, g, r, a])
    return img


def _alpha_paste(canvas_bgra: np.ndarray, src_bgra: np.ndarray, cx: int, cy: int) -> None:
    """src をアルファブレンドで canvas に貼り付ける。両方 BGRA 前提。"""
    h, w = canvas_bgra.shape[:2]
    sh, sw = src_bgra.shape[:2]

    x0 = int(cx - sw // 2)
    y0 = int(cy - sh // 2)
    x1 = x0 + sw
    y1 = y0 + sh

    # 画面外クリップ
    sx0 = max(0, -x0)
    sy0 = max(0, -y0)
    dx0 = max(0, x0)
    dy0 = max(0, y0)

    sw2 = min(sw - sx0, w - dx0)
    sh2 = min(sh - sy0, h - dy0)
    if sw2 <= 0 or sh2 <= 0:
        return

    roi_dst = canvas_bgra[dy0:dy0 + sh2, dx0:dx0 + sw2]
    roi_src = src_bgra[sy0:sy0 + sh2, sx0:sx0 + sw2]

    alpha = roi_src[:, :, 3:4].astype(np.float32) / 255.0
    inv_a = 1.0 - alpha

    roi_dst[:, :, :3] = (
        alpha * roi_src[:, :, :3].astype(np.float32)
        + inv_a * roi_dst[:, :, :3].astype(np.float32)
    ).astype(np.uint8)


# -----------------------------
# 背景＆ビュー選択
# -----------------------------
def _solid_bg(w: int, h: int) -> np.ndarray:
    """やや暗い BGRA 背景"""
    bg = np.zeros((h, w, 4), dtype=np.uint8)
    bg[:, :, :3] = 16  # ほぼ黒
    bg[:, :, 3] = 255
    return bg


def _select_view(yaw_deg: float, rules: Dict[str, Any]) -> str:
    """
    旧版互換の view 選択。
    atlas.json の view_rules を使う。なければ単純な front/±30deg。
    """
    # ルール無しなら簡易版
    thr = float(rules.get("thr_front", 16.0)) if isinstance(rules, dict) else 16.0
    if not isinstance(rules, dict) or "buckets" not in rules:
        if abs(yaw_deg) <= thr:
            return "front"
        return "right30" if yaw_deg > 0 else "left30"

    # ルールありの場合（例: {"buckets":[...]}）は必要に応じて拡張。
    # ここでは簡易に thr_front だけ使う。
    if abs(yaw_deg) <= thr:
        return "front"
    return "right30" if yaw_deg > 0 else "left30"


def _normalize_mouth(mouth: str) -> str:
    """口型ラベルを atlas のキーに揃える簡易正規化"""
    if not mouth:
        return "closed"
    m = mouth.lower()
    if m in ("close", "mouth_close"):
        return "closed"
    return m


# -----------------------------
# atlas 読み込み（★expressionメタも素通し）
# -----------------------------
def load_atlas_index(atlas_json_path: str) -> Dict[str, Any]:
    """
    atlas.min.json の実体を内部形式に正規化する。

    - トップレベルに front/left30/right30/... がある旧形式もサポート
    - data["views"][view][mouth] で必ず参照できるようにする
    - expression_labels / expression_default などはそのまま返す
    """
    with open(atlas_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    views = data.get("views")
    if not isinstance(views, dict):
        views = {}
        for key, value in data.items():
            # front / left30 / right30 ... のようなビュー辞書を拾う
            if isinstance(value, dict) and "closed" in value:
                # mouthキーは小文字に統一
                views[key] = {str(m).lower(): path for m, path in value.items()}
        data["views"] = views
    else:
        # mouthキーを小文字に揃えておく
        norm_views = {}
        for vname, vdict in views.items():
            if isinstance(vdict, dict):
                norm_views[vname] = {str(m).lower(): path for m, path in vdict.items()}
        data["views"] = norm_views

    return data


# -----------------------------
# pose 変形まわり
# -----------------------------
def _make_pose_transform(transform_cfg: Dict[str, Any] | None):
    """
    transform_cfg に従って BGRA 画像へ yaw/pitch/roll 変形を適用する関数を返す。
    - dict の場合: enabled / roll_coef / yaw_coef / pitch_coef を解釈
    - dict 以外(str など)や None の場合: 変形なし(noop)として扱う
    """
    # dict でなければ、変形なし
    if not transform_cfg or not isinstance(transform_cfg, dict):
        def _noop(img, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0):
            return img
        return _noop

    enabled = bool(transform_cfg.get("enabled", False))
    roll_coef  = float(transform_cfg.get("roll_coef", 1.0))
    yaw_coef   = float(transform_cfg.get("yaw_coef", 0.0))
    pitch_coef = float(transform_cfg.get("pitch_coef", 0.0))

    def _transform(img_bgra, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0):
        if not enabled:
            return img_bgra

        h, w = img_bgra.shape[:2]
        center = (w / 2.0, h / 2.0)

        # roll をメインに、必要なら yaw/pitch も足す
        angle = roll_coef * roll_deg + yaw_coef * yaw_deg + pitch_coef * pitch_deg
        if abs(angle) < 1e-3:
            return img_bgra

        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            img_bgra,
            M,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        return rotated

    return _transform


# -----------------------------
# 口スプライト解決ヘルパ
# -----------------------------
def _resolve_base_sprite_path(
    atlas_idx: Dict[str, Any],
    view: str,
    mouth: str,
) -> tuple[str | None, bool]:
    """
    view / mouth から「normal表情」を前提にしたベースPNGパスを解決する。
    - atlas_idx["views"][view][mouth] を参照
    - 無ければ fallback.view / fallback.mouth にフォールバック
    戻り値: (path_rel or None, used_fallback)
    """
    views = atlas_idx.get("views", {}) or {}

    # まずはそのままの view/mouth
    path_rel = views.get(view, {}).get(mouth)
    used_fallback = False

    if not path_rel:
        fb_cfg = atlas_idx.get("fallback", {}) or {}
        fb_view = fb_cfg.get("view", "front")
        fb_mouth = _normalize_mouth(fb_cfg.get("mouth", "closed"))
        path_rel = views.get(fb_view, {}).get(fb_mouth)
        used_fallback = True

    return path_rel, used_fallback


def _derive_expression_path(
    atlas_idx: Dict[str, Any],
    view: str,
    mouth: str,
    expression: str | None,
    base_path_rel: str,
) -> str:
    """
    expression ラベルとベースPNGパスから、
    assets_dir/<expr>_<view>/<mouth_xxx.png> を導出する。

    - expression が None の場合や "normal" の場合は base_path_rel をそのまま返す
    - expression_labels に含まれないラベルなら無視して base_path_rel を返す
    """
    expr_default = str(atlas_idx.get("expression_default", "normal")).lower()
    expr = (expression or expr_default).lower()

    if expr in ("normal", "", None):
        return base_path_rel

    labels = [
        str(e).lower()
        for e in atlas_idx.get("expression_labels", [])
    ]
    if labels and expr not in labels:
        # 未知のラベル → normal と同じ扱い
        return base_path_rel

    # base_path_rel からファイル名だけ拝借（mouth_a.png など）
    base_name = os.path.basename(base_path_rel)
    # ディレクトリは <expr>_<view> に固定（事前合意済み）
    expr_dir = f"{expr}_{view}"
    expr_path_rel = os.path.join(expr_dir, base_name)
    # Windows 対策で / に揃えておく
    return expr_path_rel.replace("\\", "/")


# -----------------------------
# メインレンダラー
# -----------------------------
def render_video(
    out_mp4: str,
    width: int,
    height: int,
    fps: int,
    duration_s: int,
    crossfade_frames: int,
    timeline_value_fn,
    assets_dir: str | None = None,
    atlas_json_rel: str | None = None,
    transform_cfg: Dict[str, Any] | None = None,
    per_frame_hook=None,
) -> Dict[str, Any]:
    """
    BGRA レンダラー + pose_transform フック + expression 対応。

    - pose_timeline / mouth_timeline / expression_timeline を統合した
      timeline_value_fn(t_ms) の戻り dict から mouth/yaw/pitch/roll/expression を読む。
    - expression に応じて
        assets_dir/<expression>_<view>/mouth_*.png
      を優先的に参照し、存在しなければ normal 表情にフォールバック。
    - per_frame_hook が指定されていれば、各フレームの BGRA を渡して
      加工後の BGRA を受け取り、それを出力に使う（M3.5 合成など）。
    """
    os.makedirs(os.path.dirname(out_mp4) or ".", exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(out_mp4, fourcc, fps, (width, height))

    total_frames = int(duration_s * fps)
    prev_frame = None

    # atlas 読み込み
    atlas_idx = None
    if assets_dir and atlas_json_rel:
        atlas_path = atlas_json_rel
        if not os.path.isabs(atlas_path):
            atlas_path = os.path.join(assets_dir, atlas_json_rel)
        atlas_idx = load_atlas_index(atlas_path)

    target_h_ratio = 0.32  # 顔高さの目安

    # 統計
    views_count: Dict[str, int] = {}
    fallback_frames = 0
    first_fallback_ms = None

    # 変形関数
    pose_transform = _make_pose_transform(transform_cfg)

    for i in range(total_frames):
        t_ms = int(1000 * i / fps)
        vals: Dict[str, Any] = timeline_value_fn(t_ms)

        mouth = _normalize_mouth(vals.get("mouth", "closed"))
        yaw = float(vals.get("yaw", vals.get("yaw_deg", 0.0)))
        pitch = float(vals.get("pitch", vals.get("pitch_deg", 0.0)))
        roll = float(vals.get("roll", vals.get("roll_deg", 0.0)))
        expression = vals.get("expression")  # None の場合は normal 扱い

        frame = _solid_bg(width, height)

        used_fallback = False
        view = "front"

        if atlas_idx is not None:
            view_rules = atlas_idx.get("view_rules", {})
            view = _select_view(yaw, view_rules)
            views = atlas_idx.get("views", {})
            views_count[view] = views_count.get(view, 0) + 1

            # 1. normal 表情前提のベースPNGパスを解決
            base_path_rel, used_fallback_base = _resolve_base_sprite_path(atlas_idx, view, mouth)
            used_fallback = used_fallback or used_fallback_base

            if base_path_rel:
                # 2. expression 用にパスを上書き
                expr_path_rel = _derive_expression_path(
                    atlas_idx=atlas_idx,
                    view=view,
                    mouth=mouth,
                    expression=expression,
                    base_path_rel=base_path_rel,
                )

                # 実際の読み込み：まず expression 専用 → 無ければ normal にフォールバック
                asset_path = None
                src = None

                # 2-1. expression 専用のパスを試す
                try:
                    asset_path = os.path.join(assets_dir, expr_path_rel)
                    src = _load_rgba(asset_path)
                except FileNotFoundError:
                    # expression 用PNGが無い → normal 表情にフォールバック
                    if expr_path_rel != base_path_rel:
                        try:
                            asset_path = os.path.join(assets_dir, base_path_rel)
                            src = _load_rgba(asset_path)
                            used_fallback = True  # 「表情」の意味ではフォールバック
                        except FileNotFoundError:
                            src = None

                if src is not None:
                    # リサイズ
                    tgt_h = max(1, int(height * target_h_ratio))
                    scale = tgt_h / src.shape[0]
                    tgt_w = max(1, int(src.shape[1] * scale))
                    src_rs = cv2.resize(src, (tgt_w, tgt_h), interpolation=cv2.INTER_AREA)

                    # ★ yaw/pitch/roll 変形をここで適用 ★
                    src_rs = pose_transform(
                        src_rs, yaw_deg=yaw, pitch_deg=pitch, roll_deg=roll
                    )

                    cx = width // 2
                    cy = int(height * 0.58)
                    _alpha_paste(frame, src_rs, cx, cy)
                else:
                    # baseもexpressionも読めなかった場合
                    used_fallback = True

        if used_fallback:
            fallback_frames += 1
            if first_fallback_ms is None:
                first_fallback_ms = t_ms

        # ★ ここで per_frame_hook に BGRA フレームを渡す（M3.5 合成など）★
        if per_frame_hook is not None:
            frame = per_frame_hook(frame, t_ms, i)

        # クロスフェード（旧版互換）
        if crossfade_frames > 0 and prev_frame is not None and i % (fps // 2 or 1) == 0:
            for k in range(crossfade_frames):
                alpha = (k + 1) / crossfade_frames
                blended = (
                    prev_frame.astype(np.float32) * (1 - alpha)
                    + frame.astype(np.float32) * alpha
                ).astype(np.uint8)
                vw.write(cv2.cvtColor(blended, cv2.COLOR_BGRA2BGR))
            prev_frame = frame
        else:
            vw.write(cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR))
            prev_frame = frame

    vw.release()

    # transform 設定の有効・無効（dict 以外が来ても安全に扱う）
    if isinstance(transform_cfg, dict):
        transform_enabled = bool(transform_cfg.get("enabled", False))
    else:
        transform_enabled = False

    return {
        "views": views_count,
        "fallback_frames": int(fallback_frames),
        "first_fallback_ms": int(first_fallback_ms) if first_fallback_ms is not None else None,
        "total_frames": int(total_frames),
        "transform": {"enabled": transform_enabled},
    }
