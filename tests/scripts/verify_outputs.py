from pathlib import Path
import sys, json

vid = Path('tests/out/videos/phaseA_demo.mp4')
log = Path('tests/out/logs/run.log.json')
csv = Path('tests/out/logs/summary.csv')

err = 0
if not vid.exists() or vid.stat().st_size == 0:
    print('[FAIL] MP4 missing or empty:', vid, file=sys.stderr); err += 1
if not log.exists():
    print('[WARN] run.log.json missing')
if not csv.exists():
    print('[WARN] summary.csv missing')

if err:
    sys.exit(1)
print('[OK] Outputs present.')
