import json, sys, shutil
from pathlib import Path
import yaml
import subprocess

def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    out = dict(base)
    for k, v in override.items():
        out[k] = deep_merge(out.get(k), v)
    return out

def load_yaml(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def to_runner_schema(cfg: dict, repo: Path) -> dict:
    # If already in runner schema, return as-is
    if "io" in cfg and "video" in cfg and "inputs" in cfg:
        return cfg
    # Legacy -> Runner mapping (best-effort)
    out_dir = cfg.get("output", {}).get("dir", "tests/out")
    basename = cfg.get("output", {}).get("basename", "phaseA_demo")
    fps = cfg.get("render", {}).get("fps", 25)
    atlas_path = cfg.get("atlas_path", "tests/assets_min/atlas.min.json")
    return {
        "io": {
            "assets_dir": "tests/assets_min",
            "out_dir": out_dir,
            "exp_name": basename
        },
        "video": {
            "width": 640,
            "height": 640,
            "fps": cfg.get("render", {}).get("fps", 25),
            "duration_s": 3
        },
        "render": {
            "crossfade_frames": 4
        },
        "inputs": {
            "mouth_timeline": "timelines/mouth_timeline.json",
            "pose_timeline": "timelines/pose_timeline_yaw.flat.json",
            "expression_timeline": "timelines/expression_timeline.json"
        },
        "atlas": {
            "atlas_json": "atlas.min.json" if "atlas.min.json" in atlas_path else atlas_path
        }
    }

def main():
    repo = Path(__file__).resolve().parents[2]
    cfg_dir = repo / "configs"
    paths = load_yaml(cfg_dir / "paths.yaml")

    base_cfg_path = cfg_dir / "phaseA.base.json"
    base_cfg = json.loads(base_cfg_path.read_text(encoding="utf-8"))
    override = load_yaml(cfg_dir / "phaseA_yaw.override.yaml")
    final_cfg = deep_merge(base_cfg, override) if override else base_cfg
    final_cfg = to_runner_schema(final_cfg, repo)

    # Enforce outputs
    videos_dir = repo / paths["videos_dir"]
    logs_dir   = repo / paths["logs_dir"]
    ensure_dir(videos_dir); ensure_dir(logs_dir)
    final_cfg["io"]["out_dir"] = str(repo / paths["out_root"])

    # Prefer flat pose if exists, else sample in inputs_dir
    pose_flat = repo / paths["inputs_dir"] / "pose_timeline_yaw.flat.json"
    if pose_flat.exists():
        final_cfg["inputs"]["pose_timeline"] = str(Path(paths["inputs_dir"]).joinpath("pose_timeline_yaw.flat.json").relative_to(paths["assets_dir"]))
    else:
        final_cfg["inputs"]["pose_timeline"] = str(Path(paths["inputs_dir"]).joinpath("pose_timeline.sample.json").relative_to(paths["assets_dir"]))

    # Write final config
    final_json = cfg_dir / "phaseA.config.json"
    final_json.write_text(json.dumps(final_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # Call vendor runner
    runner = repo / "vendor" / "src" / "m0_runner.py"
    env = dict(**os.environ)
    cmd = [sys.executable, str(runner), "--config", str(final_json)]
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        (logs_dir / "error.log").write_text(str(e), encoding="utf-8")
        raise

    # Move/copy outputs to standardized locations
    exp_dir = repo / final_cfg["io"]["out_dir"] / final_cfg["io"]["exp_name"]
    src_mp4 = exp_dir / "demo.mp4"
    dst_mp4 = videos_dir / "phaseA_demo.mp4"
    if src_mp4.exists():
        shutil.copy2(src_mp4, dst_mp4)
    # Move logs
    for name in ["run.log.json", "summary.csv"]:
        p = exp_dir / name
        if p.exists():
            shutil.copy2(p, logs_dir / name)

    print("[OK] phaseA completed. MP4:", dst_mp4)

if __name__ == "__main__":
    import os
    main()
