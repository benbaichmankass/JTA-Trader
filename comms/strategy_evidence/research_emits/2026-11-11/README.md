# research_emits/2026-11-11 — meta-label corpus (M23)

Per-trade ledgers for the 19 crypto trend_donchian / pullback legs, built 2026-11-11 by

    python3 scripts/ops/build_strategy_evidence.py --strategy <leg> ... --days 1825 --research-emits

(binance_vision 1h/2h/4h bars, 2021-11-11 -> 2026-11-10; net_r net of fee + slippage + funding). Every row carries
`features_schema: harness_decision_v1` (f_adx_14, f_atr_pct, f_atr_pctl, f_atr_pctl_bucket, f_regime, f_regime_cell,
f_rlr_vol_20, f_ret_20, f_hour_utc, f_dow_utc) plus mae_r. MEASURED on these files: 6,214 trades; every f_* column
non-null on >= 99.28% of rows (f_atr_pctl lowest).

NOT an edge record: the per-leg Stage-0 records in comms/strategy_evidence/*.json were NOT rewritten (the build wrote
its records to a scratch path), and this directory is deliberately outside comms/strategy_evidence/runs/ so no
"newest ledger per leg" reader picks it up. `*__paths.jsonl` and `*__data.csv` were not committed (size).
Equity / futures legs are absent: their harness fetch failed in the authoring sandbox (no broker data source).
Consumer: research/queue/RQ-20261111-3a23-01.yaml.
