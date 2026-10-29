#!/usr/bin/env bash
# ML-P1-COSTNET-REBUILD extras (plan section 4 B1): (1) re-gate the pooled setup heads on v022 for the
# record, (2) restamp + regate conviction_meta (P4), (3) build exit_candidates for the 1h Donchian legs.
# Run from an isolated worktree; shared stores live under $MAIN. Nothing here registers a setup head
# (--no-register) or changes a stage. conviction-meta-v1 is registered at its manifest stage (candidate).
# wiring: manual-only - the ML-P1-COSTNET-REBUILD lane runs it on the trainer, between cycles.
set -uo pipefail
MAIN="${MAIN:-/home/ubuntu/ict-trading-bot}"
OUT="${OUT:-/tmp/p1_extras.txt}"; : > "$OUT"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$OUT"; }
source .venv/bin/activate 2>/dev/null
. scripts/ops/_trainer_heavy_lock.sh
take_trainer_heavy_lock "p1_extras" || { log "ABORT heavy lock"; exit 0; }

log "STEP 1: re-gate pooled setup heads on v022 (no-register)"
for m in setup-candidates-metalabel-p2pool-v1 setup-candidates-metalabel-xsym-v1 setup-candidates-metalabel-xsym-yz-v1; do
  mkdir -p /tmp/p1_regate && python3 - "$m" <<'PY'
import sys, yaml
m = sys.argv[1]
d = yaml.safe_load(open(f"ml/configs/{m}.yaml"))
d["model_id"] = m + "-regate-v022"
d["dataset"]["version"] = "v022"
d["dataset"]["symbol_scope"] = "all"; d["dataset"]["timeframe"] = "all"
d["target_deployment_stage"] = "research_only"
yaml.safe_dump(d, open(f"/tmp/p1_regate/{m}-regate-v022.yaml", "w"), sort_keys=False)
PY
  python -m ml train "/tmp/p1_regate/$m-regate-v022.yaml" --datasets-root "$MAIN/datasets-out" \
    --experiments-root /tmp/p1_regate/runs --no-register > "/tmp/p1_regate/$m.out" 2> "/tmp/p1_regate/$m.err"
  rc=$?
  E="$(ls -dt /tmp/p1_regate/runs/$m-regate-v022/*/ 2>/dev/null | head -1)"
  log "  $m rc=$rc $( [ -n "$E" ] && python3 -c "import json;g=json.load(open('${E}cost_gate.json'));print(json.dumps({k:g.get(k) for k in ('passed','applicable','candidate_value_r','take_all_r','matched_random_r','n_rows','n_taken','take_rate','eval_cost_bases')}),g.get('reason'))" || tail -c 300 /tmp/p1_regate/$m.err )"
done
log "  SKIPPED (stated): backtest-v1/c1/c2, siglog-v1, setup-candidates-metalabel-v1 are BTCUSDT-scoped (v022 is the pooled all/all book); p2pool-c1 needs won_r (r_label_threshold build); paper-v1 needs the v030 paper book."

log "STEP 2: P4 conviction_meta restamp + regate"
python -m ml build-dataset conviction_meta --output-dir "$MAIN/datasets-out" --version v002 \
  --source trade_journal.db --overwrite -- "db_path=$MAIN/data/trade_journal.db" "exclude_fabricated_pnl=true" > /tmp/p1_cm_build.out 2>&1
log "  build rc=$? $(tail -n 2 /tmp/p1_cm_build.out | cut -c1-300)"
python3 - "$MAIN/datasets-out/conviction_meta/all/all/v002/data.jsonl" <<'PY' 2>&1 | tee -a "$OUT"
import json, sys, collections
c = collections.Counter(); n = 0
for l in open(sys.argv[1]):
    if l.strip():
        r = json.loads(l); n += 1; c[r.get("label_cost_basis")] += 1
print("conviction_meta v002 rows:", n, "label_cost_basis:", dict(c))
PY
python -m ml train ml/configs/conviction-meta-v1.yaml --datasets-root "$MAIN/datasets-out" \
  --experiments-root "$MAIN/ml/experiments-runs" --registry-root "$MAIN/ml/registry-store" > /tmp/p1_cm_train.out 2> /tmp/p1_cm_train.err
log "  train rc=$?"
E="$(ls -dt $MAIN/ml/experiments-runs/conviction-meta-v1/*/ 2>/dev/null | head -1)"
[ -n "$E" ] && { log "  exp=$E"; cat "${E}cost_gate.json" | tee -a "$OUT"; python3 -c "import json;print(json.dumps(json.load(open('${E}metrics.json'))))" | cut -c1-900 | tee -a "$OUT"; } || tail -c 600 /tmp/p1_cm_train.err | tee -a "$OUT"

log "STEP 3: exit_candidates for the 1h Donchian legs (BTC/ETH/SOL 1h)"
MR="$MAIN/datasets-out/market_raw/BTCUSDT/1h/v002,$MAIN/datasets-out/market_raw/ETHUSDT/1h/v002,$MAIN/datasets-out/market_raw/SOLUSDT/1h/v002"
python -m ml.datasets build exit_candidates --output-dir "$MAIN/datasets-out" --version v001 --source market_raw \
  --symbol-scope all --timeframe 1h --overwrite -- "market_raw_paths=$MR" "live_trades_db=$MAIN/data/trade_journal.db" > /tmp/p1_exit_build.out 2>&1
log "  build rc=$? $(grep -v 'POPULATION CHANGED' /tmp/p1_exit_build.out | tail -n 3 | cut -c1-300)"
ls -la "$MAIN/datasets-out/exit_candidates/all/1h/v001/" 2>&1 | tee -a "$OUT"
python3 - "$MAIN/datasets-out/exit_candidates/all/1h/v001/data.jsonl" <<'PY' 2>&1 | tee -a "$OUT"
import json, sys, collections
c = collections.Counter(); s = collections.Counter(); n = 0
for l in open(sys.argv[1]):
    if l.strip():
        r = json.loads(l); n += 1; c[r.get("label_cost_basis")] += 1; s[(r.get("symbol"), r.get("event_source"))] += 1
print("exit_candidates rows:", n, "label_cost_basis:", dict(c)); print(dict(s))
PY
echo '{"p1_extras_done":true}' >> "$OUT"
