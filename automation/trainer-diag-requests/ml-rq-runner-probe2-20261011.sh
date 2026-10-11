cd /home/ubuntu/ict-trading-bot 2>/dev/null || { echo NO_REPO; exit 3; }
echo "== datasets-out roots"
for d in datasets-out /data/datasets-out /data/bot-data/datasets-out runtime_logs/trainer/datasets-out; do [ -d "$d" ] && echo "FOUND $d" && ls "$d" | head -20; done
echo "== market_features dirs"
find / -maxdepth 7 -type d -path "*market_features/BTCUSDT*" 2>/dev/null | head -12
echo "== forecasts dirs"
find / -maxdepth 7 -type d -path "*forecasts/BTCUSDT*" 2>/dev/null | head -8
echo "== a market_features shard sample"
D=$(find / -maxdepth 7 -type d -path "*market_features/BTCUSDT/15m/v00*" 2>/dev/null | sort | tail -1)
echo "dir=$D"; ls -la "$D" 2>/dev/null | head; 
.venv/bin/python - "$D" <<'PY'
import sys, json, os
d = sys.argv[1]
for name in ("data.parquet","data.jsonl","metadata.json"):
    p = os.path.join(d, name)
    if os.path.exists(p):
        print("exists", name, os.path.getsize(p))
if os.path.exists(os.path.join(d,"metadata.json")):
    m = json.load(open(os.path.join(d,"metadata.json")))
    print(json.dumps({k: m[k] for k in list(m)[:20]}, default=str)[:1500])
p = os.path.join(d,"data.parquet")
if os.path.exists(p):
    import pandas as pd
    df = pd.read_parquet(p)
    print("rows", len(df)); print("cols", list(df.columns)); print(df.dtypes.astype(str).to_dict() if len(df.columns) < 40 else "")
    print("ts range", df["ts"].min() if "ts" in df else None, df["ts"].max() if "ts" in df else None)
    print("regime_label counts", df["regime_label"].value_counts().to_dict() if "regime_label" in df else None)
PY
echo "== shadow log location"
find / -maxdepth 6 -name "*shadow*" \( -name "*.jsonl" -o -name "*.db" -o -name "*.sqlite" \) 2>/dev/null | head -6
