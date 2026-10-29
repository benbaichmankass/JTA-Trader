#!/usr/bin/env bash
# ML-P1-COSTNET-REBUILD (plan docs/plans/ml-live-promotion-plan-2026-10-29.md section 4 B1).
# Rebuilds setup_candidates/all/all/v022 = v020's build params (harness replay of the 3-strategy
# roster over BTC/ETH/SOL, the same widened eval shards, include_paper=true) with the CURRENT
# cost-net builder and live_r_basis=initial_only (eval R on the entry-time initial risk,
# PI-20261014-MVBJLVJ3-0001); trains setup-candidates-metalabel-p2pool-v2 (research_only, registered);
# grades it against plan section 3 P1 with scripts/ml/p1_costnet_grade.py. v020/v021 are NOT touched.
# wiring: manual-only - the ML-P1-COSTNET-REBUILD lane runs it on the trainer, between cycles.
set -uo pipefail

REPO="${REPO:-/home/ubuntu/ict-trading-bot}"
cd "$REPO"
LIVE_JOURNAL="${LIVE_JOURNAL:-data/trade_journal.db}"
BT_DB="${BT_DB:-/tmp/p1_costnet_backtest.db}"
SC_V_WON="${SC_V_WON:-v022}"
SC_V_C1="${SC_V_C1:-v021}"
RUN_TAG="${RUN_TAG:-p1-costnet-$(date +%Y%m%d 2>/dev/null || echo 20260719)}"
RESULT="${RESULT:-/tmp/p1_costnet_result.txt}"
SYMBOLS=(BTCUSDT ETHUSDT SOLUSDT)
MR_VER="${MR_VER:-v002}"
# L3 paper-book eval population — OFF by default (byte-for-byte the real-only
# build). Set INCLUDE_PAPER=true to ALSO emit the PAPER cohort as a distinct,
# tagged (event_source="live_paper") population for the paper-eval manifest;
# NEVER blended into the real-money eval (see setup_candidates.py::iter_rows).
INCLUDE_PAPER="${INCLUDE_PAPER:-true}"

: > "$RESULT"
log() { echo "[$(date -u +%H:%M:%S 2>/dev/null || echo m23p2)] $*" | tee -a "$RESULT"; }
source .venv/bin/activate 2>/dev/null || log "WARN: no .venv"

# Serialize against the nightly cycle / other heavy jobs (6 GB box).
# shellcheck source=/dev/null
. scripts/ops/_trainer_heavy_lock.sh
if ! take_trainer_heavy_lock "p1_costnet_rebuild"; then
  log "ABORT: trainer heavy-job queue busy past the wait; re-run later"
  echo '{"m23_p2_done":false,"error":"heavy_lock_timeout"}' >> "$RESULT"
  exit 0
fi

log "STEP 1: per-symbol market_raw -> 1h/2h/4h CSVs"
declare -A CSV  # "SYM|tf" -> path
for sym in "${SYMBOLS[@]}"; do
  src="datasets-out/market_raw/${sym}/1h/${MR_VER}/data.jsonl"
  if [ ! -f "$src" ]; then log "  WARN: $src missing — $sym dropped from the pool"; continue; fi
  c1="/tmp/m23p2_${sym}_1h.csv"; c2="/tmp/m23p2_${sym}_2h.csv"; c4="/tmp/m23p2_${sym}_4h.csv"
  python3 - "$src" "$c1" "$c2" "$c4" <<'PY' 2>>"$RESULT"
import json, sys, csv
src, d1, d2, d4 = sys.argv[1:5]
rows = []
with open(src) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        ts = r.get("ts") or r.get("timestamp") or r.get("time")
        rows.append((int(ts) if str(ts).isdigit() else ts,
                     float(r["open"]), float(r["high"]), float(r["low"]),
                     float(r["close"]), float(r.get("volume") or 0.0)))
rows.sort(key=lambda x: x[0])
cols = ["timestamp", "open", "high", "low", "close", "volume"]
def write(path, data):
    with open(path, "w", newline="") as out:
        w = csv.writer(out); w.writerow(cols)
        for x in data:
            w.writerow(list(x))
def resample(data, n):
    out = []
    for i in range(0, len(data) - n + 1, n):
        g = data[i:i+n]
        out.append((g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g),
                    g[-1][4], sum(x[5] for x in g)))
    return out
write(d1, rows); write(d2, resample(rows, 2)); write(d4, resample(rows, 4))
print("csv rows: 1h", len(rows))
PY
  CSV["$sym|1h"]="$c1"; CSV["$sym|2h"]="$c2"; CSV["$sym|4h"]="$c4"
  log "  $sym: 1h=$(wc -l < "$c1" 2>/dev/null) 2h=$(wc -l < "$c2" 2>/dev/null) 4h=$(wc -l < "$c4" 2>/dev/null)"
done

log "STEP 2: harness replay per (strategy × symbol)"
ROSTER=(
  "trend_donchian|scripts/backtest_trend.py|1h"
  "squeeze_breakout_4h|scripts/backtest_squeeze.py|4h"
  "htf_pullback_trend_2h|scripts/backtest_pullback.py|2h"
)
rm -f "$BT_DB"
python3 - "$LIVE_JOURNAL" "$BT_DB" <<'PY' 2>>"$RESULT"
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
row = s.execute("select sql from sqlite_master where type='table' and name='trades'").fetchone()
if not row:
    print("SCHEMA_SEED_ERR: no trades table in journal"); sys.exit(1)
d = sqlite3.connect(dst); d.execute(row[0]); d.commit(); d.close(); s.close()
print("seeded trades schema into temp db")
PY

total_bt=0
for sym in "${SYMBOLS[@]}"; do
  declare -a RECORD_ARGS=()
  for entry in "${ROSTER[@]}"; do
    IFS='|' read -r strat harness tf <<< "$entry"
    csv="${CSV[$sym|$tf]:-}"
    [ -z "$csv" ] || [ ! -f "$csv" ] && continue
    jsonl="/tmp/m23p2_${sym}_${strat}_trades.jsonl"
    python3 "$harness" --data "$csv" --timeframe "$tf" --symbol "$sym" \
      --emit-trades "$jsonl" --json "/tmp/m23p2_${sym}_${strat}_summary.json" >>"$RESULT" 2>&1 \
      || log "    WARN: ${sym}/${strat} harness returned nonzero"
    n=$(wc -l < "$jsonl" 2>/dev/null || echo 0)
    log "  ${sym}/${strat}@${tf}: emitted $n"
    [ "${n:-0}" != "0" ] && RECORD_ARGS+=(--trades-jsonl "${jsonl}=${strat}")
  done
  if [ "${#RECORD_ARGS[@]}" != "0" ]; then
    python3 -m scripts.ml.record_harness_trades --db "$BT_DB" --symbol "$sym" \
      "${RECORD_ARGS[@]}" --run-tag "$RUN_TAG" >>"$RESULT" 2>&1
  fi
done
NBT=$(python3 - "$BT_DB" <<'PY' 2>>"$RESULT"
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
print(c.execute("select count(*) from trades where is_backtest=1").fetchone()[0])
for r in c.execute("select symbol, strategy_name, count(*) from trades where is_backtest=1 group by 1,2"):
    print("  ", r[0], r[1], r[2], file=sys.stderr)
PY
)
log "  pooled backtest rows recorded: $NBT"
if [ "${NBT:-0}" = "0" ]; then log "ABORT: 0 backtest rows"; echo '{"m23_p2_done":false,"error":"no_backtest_rows"}' >> "$RESULT"; exit 1; fi

# --- Eval-book market_raw coverage (WS-3b, MB-20260717 label-volume follow-on) ---
# The eval book (real closed trades — the P1 wall of 376 BTC-only rows) grows only
# for symbols whose market_raw shard is passed here: setup_candidates derives each
# shard's symbol from its bars and path-resolves THAT symbol's REAL closed trades
# at the covering bar (setup_candidates.py::_iter_one_symbol -> _load_live_trades).
# So widen the resolution set to every WS-B-covered shard at its ACTUAL timeframe
# (build_trainer_datasets.sh: crypto 1h, alt-USDT 15m, equities/metals 1d) — ONE
# shard per symbol (a symbol listed at two timeframes would double-count its
# trades). The backtest-TRAIN pool stays the 3 crypto symbols' intraday replay
# above: equities (1d) / alt (15m) have no 1h base for the 1h/2h/4h strategy
# harnesses, so this run grows the EVAL side (a measurement — the honest widening
# of the wall's denominator), NOT a matching train-side claim; the
# alt-15m->intraday-resample train-side growth is a further follow-on.
# Existence-guarded: _load_market_raw_rows RAISES on a missing shard, so a
# not-yet-built shard (e.g. an alt 15m the parity gate skipped that night) is
# skipped and logged, never crashing the setup_candidates build.
EVAL_SHARDS=(
  "BTCUSDT|1h" "ETHUSDT|1h" "SOLUSDT|1h"
  "ADAUSDT|15m" "AVAXUSDT|15m" "XRPUSDT|15m"
  "SPY|1d" "QQQ|1d" "GLD|1d" "TLT|1d" "IWM|1d" "SLV|1d" "IEF|1d"
  "TQQQ|1d" "QLD|1d" "SPYM|1d" "IAUM|1d" "MGC|1d" "MHG|1d"
)
declare -a MR_PATH_LIST=()
declare -a MR_SKIPPED=()
for entry in "${EVAL_SHARDS[@]}"; do
  IFS='|' read -r esym etf <<< "$entry"
  epath="datasets-out/market_raw/${esym}/${etf}/${MR_VER}"
  if [ -f "${epath}/data.jsonl" ]; then
    MR_PATH_LIST+=("$epath")
  else
    MR_SKIPPED+=("${esym}@${etf}")
  fi
done
if [ "${#MR_PATH_LIST[@]}" = "0" ]; then
  log "ABORT: no market_raw eval shards present under datasets-out/market_raw/*/*/${MR_VER}"
  echo '{"m23_p2_done":false,"error":"no_eval_shards"}' >> "$RESULT"; exit 1
fi
MR_PATHS="$(IFS=,; echo "${MR_PATH_LIST[*]}")"
log "  eval-book shards present (${#MR_PATH_LIST[@]}): ${MR_PATH_LIST[*]##*market_raw/}"
[ "${#MR_SKIPPED[@]}" != "0" ] && log "  eval-book shards SKIPPED (not built): ${MR_SKIPPED[*]}"

build_pool() {
  # build_pool <version> [extra build params...]
  local ver="$1"; shift
  python3 -m ml.datasets build setup_candidates --output-dir datasets-out \
    --version "$ver" --source market_raw --symbol-scope all --timeframe all --overwrite -- \
    "market_raw_paths=$MR_PATHS" "backtest_trades_db=$BT_DB" \
    "live_trades_db=$LIVE_JOURNAL" "include_cusum=false" \
    "include_paper=$INCLUDE_PAPER" "live_r_basis=initial_only" "$@" >>"$RESULT" 2>&1
  python3 - "datasets-out/setup_candidates/all/all/$ver/data.jsonl" <<'PY' 2>&1 | tee -a "$RESULT"
import json, sys, collections
try:
    es = collections.Counter(); lv = collections.Counter(); sym = collections.Counter()
    live_sym = collections.Counter(); won = collections.Counter(); n = 0
    for line in open(sys.argv[1]):
        line = line.strip()
        if not line: continue
        r = json.loads(line); n += 1
        es[r.get("event_source")] += 1
        lv[bool(r.get("is_live_trade"))] += 1
        sym[r.get("symbol")] += 1
        if r.get("is_live_trade"):
            live_sym[r.get("symbol")] += 1
        won[r.get("won")] += 1
    print("rows:", n, "by_source:", dict(es), "is_live:", dict(lv), "won:", dict(won))
    print("by_symbol:", dict(sym), "LIVE by_symbol:", dict(live_sym))
except Exception as e:
    print("dataset read err:", e)
PY
}

log "STEP 3: build $SC_V_WON (v020 params + initial-risk live R)"
[ -e "datasets-out/setup_candidates/all/all/$SC_V_WON/data.jsonl" ] && log "  NOTE: $SC_V_WON exists; --overwrite rebuilds it"
build_pool "$SC_V_WON"

log "STEP 4: train setup-candidates-metalabel-p2pool-v2 (research_only, registered)"
python3 -m ml train ml/configs/setup-candidates-metalabel-p2pool-v2.yaml \
  --datasets-root datasets-out --experiments-root ml/experiments-runs --registry-root ml/registry-store \
  > /tmp/p1_costnet_train.out 2>>"$RESULT" || log "WARN: train returned nonzero"
tail -c 1500 /tmp/p1_costnet_train.out | tee -a "$RESULT"
EXP="$(ls -dt ml/experiments-runs/setup-candidates-metalabel-p2pool-v2/*/ 2>/dev/null | head -1)"
log "  experiment dir: ${EXP:-NONE}"
if [ -n "$EXP" ] && [ -f "${EXP}cost_gate.json" ]; then
  mkdir -p comms/ml
  python3 -m scripts.ml.p1_costnet_grade \
    --manifest ml/configs/setup-candidates-metalabel-p2pool-v2.yaml \
    --model-state "${EXP}model_state.json" \
    --dataset "datasets-out/setup_candidates/all/all/$SC_V_WON/data.jsonl" \
    --cost-gate "${EXP}cost_gate.json" --journal "$LIVE_JOURNAL" \
    --out /tmp/p1_costnet_verdict.json 2>>"$RESULT" | tee -a "$RESULT"
  cp "${EXP}cost_gate.json" /tmp/p1_costnet_cost_gate.json
else
  log "ABORT: no experiment dir / cost_gate.json"
fi
echo '{"p1_costnet_done":true}' >> "$RESULT"
log "DONE"
