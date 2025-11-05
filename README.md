# M0_phaseA_tests – Pose-only Harness (Jules: MP4生成, PRはリンクのみ)

本リポジトリは **PhaseA（pose-only）** の最小テスト用ハーネスです。  
方針：**MP4はJulesで生成** → **GCSにアップ** → **署名URLをPR本文に記載**（Artifactsは使わない最軽量運用）。

## Quick start

```bash
# (A) v1 → flat 変換（例：yaw）
python tests/scripts/pose_v1_to_flat.py --in tests/timelines/pose_timeline_yaw.json --out tests/flats/yaw.flat.json

# (B) 実行（既定は yaw.flat.json / 明示指定も可）
python tests/scripts/run_phaseA.py
# or
python tests/scripts/run_phaseA.py --pose tests/flats/pitch.flat.json
