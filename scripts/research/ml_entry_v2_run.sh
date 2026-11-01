#!/usr/bin/env bash
# Runner entry for RQ-20261101-fs01-01 (ablation) and RQ-20261101-fs02-01 (forward). Usage: ml_entry_v2_run.sh <ablation|forward> <unit> <out_dir>
# Fetches the Binance Vision streams itself (keyless), builds the family table, runs the arms in parallel (dev folds only),
# combines under the registered rule; `forward` additionally claims ONE read of W1 through scripts/research/holdout_lock.py.
set -euo pipefail
MODE="$1"; UNIT="$2"; OUT="$3"
cd "$(dirname "$0")/../.."
pip install -q lightgbm scikit-learn pyarrow >/dev/null 2>&1 || pip install -q lightgbm scikit-learn
S="$OUT/streams"; O="$OUT/oct"; W="$OUT/work"
mkdir -p "$S" "$O" "$W"
python3 scripts/research/vision_streams.py --out "$S" --streams klines12,funding,premium --workers 24
python3 scripts/research/vision_streams.py --out "$S" --streams metrics --start 2021-12-01 --end 2026-10-31 --workers 32
python3 scripts/research/vision_streams.py --out "$O" --streams klines12d,premiumd --start 2026-10-01 --end 2026-10-31 --workers 16
python3 scripts/research/vision_streams.py --out "$O" --streams funding --start 2026-10 --end 2026-10 --workers 16
python3 scripts/research/ml_entry_v2.py build-table --streams "$S" --oct-dir "$O" --out "$W"
if [ "$MODE" = "ablation" ]; then
  for A in A B C D E F G; do python3 scripts/research/ml_entry_v2.py arm --arm "$A" --out "$W" --n-jobs 2 & done
  wait
  python3 scripts/research/ml_entry_v2.py combine --out "$W"
  cp "$W"/ablation.json "$W"/arm_*.json "$OUT"/
else
  python3 scripts/research/ml_entry_v2.py forward --out "$W" --ablation "${ABLATION_JSON:?set ABLATION_JSON to the fs01-01 ablation.json}" --unit "$UNIT"
  cp "$W"/forward.json "$OUT"/
fi
