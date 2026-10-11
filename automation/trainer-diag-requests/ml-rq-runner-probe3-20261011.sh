cd /home/ubuntu/ict-trading-bot 2>/dev/null || { echo NO_REPO; exit 3; }
for s in BTCUSDT ETHUSDT SOLUSDT; do echo "== $s market_features"; ls datasets-out/market_features/$s/15m 2>&1 | head; done
echo "== forecasts"; ls datasets-out/forecasts/BTCUSDT/15m 2>&1 | head
D=$(ls -d datasets-out/market_features/BTCUSDT/15m/v* 2>/dev/null | sort | tail -1)
echo "dir=$D"; ls -la "$D" | head
.venv/bin/python - "$D" <<'PY'
import sys, json, os
d = sys.argv[1]
for name in sorted(os.listdir(d)):
    print("file", name, os.path.getsize(os.path.join(d, name)))
mp = os.path.join(d, "metadata.json")
if os.path.exists(mp):
    m = json.load(open(mp)); print("metadata keys", list(m)[:25]); print(json.dumps({k: m.get(k) for k in ("row_count","symbol_scope","timeframe","feature_columns","label_columns","fc_columns","forecast_path","vol_threshold") if k in m}, default=str)[:1200])
import pandas as pd
for name in ("data.parquet",):
    p = os.path.join(d, name)
    if os.path.exists(p):
        df = pd.read_parquet(p); print("rows", len(df)); print("cols", list(df.columns))
        print("ts", df["ts"].min(), df["ts"].max())
        for c in ("regime_label","vol_bucket"):
            if c in df: print(c, df[c].value_counts().to_dict())
        print("fc nan frac", {c: round(float(df[c].isna().mean()),3) for c in df.columns if c.startswith("fc_")})
    else:
        jp = os.path.join(d, "data.jsonl")
        if os.path.exists(jp):
            print("jsonl head:", open(jp).readline()[:600])
PY
echo "== shadow_predictions.jsonl"; wc -l runtime_logs/shadow_predictions.jsonl; head -c 900 runtime_logs/shadow_predictions.jsonl; echo; ls -la runtime_logs/shadow_predictions*.jsonl
