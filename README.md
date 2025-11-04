# M0_phaseA_tests – Strict Template (B' mode)

This repository is a clean, **PhaseA pose-only** test harness for M0, designed to run on GitHub Actions (artifacts on PR) while using **Jules only to create PRs**.

## Quick start (30 seconds)

```bash
# 1) Push the repo (or unzip & push)
# 2) Create a PR using Jules (title is pre-set in the prompt)
# 3) Wait for GitHub Actions to finish; download MP4 from Artifacts
```

## Layout
- `vendor/src/` – pinned runner + render core + timeline (V1: your stable M0_2)
- `tests/assets_min/` – minimal atlas (front/left30/right30 × mouth6) + timelines
- `tests/scripts/run_phaseA.py` – config adapter + execution + output normalization
- `.github/workflows/phaseA-artifacts.yml` – builds on PR and uploads artifacts
- `.jules/runbook.yaml` – PR creation only (no execution)
- `configs/phaseA.base.json` – base config (already in runner schema; adapter supports legacy too)

## Local run (optional)
```bash
python tests/scripts/run_phaseA.py
python tests/scripts/verify_outputs.py
```

Outputs:
- MP4: `tests/out/videos/phaseA_demo.mp4`
- Logs: `tests/out/logs/run.log.json`, `tests/out/logs/summary.csv`

## Notes
- `opencv-python-headless`, `numpy`, `PyYAML` are required in CI.
- `tests/out/` and `configs/phaseA.config.json` are ignored by git.
