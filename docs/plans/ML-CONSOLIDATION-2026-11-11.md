# ML consolidation — inventory and keep/retire proposal (2026-11-11)

> **Doc status:** `live` · category `plan-input` · last verified `2026-11-11` · input to the Thursday plan for row ML-PROGRAMME-CONSOLIDATION

**Gates this adds or changes:** none. This is a proposal; nothing is retired by this file.

**Population:** all 106 rows of the consolidated registry feed (`GET /api/bot/ml/registry`, read 2026-11-11 ~19:10Z,
`inventory_read_state: ok`, mirror 98 + served/candidate/overlay 8), joined to the repo at the PR head. Machine-readable:
[`comms/ml_consolidation/2026-11-11.json`](../../comms/ml_consolidation/2026-11-11.json).

## The rule applied (from the row's scope, step 2)

- **KEEP (consumer):** registry bucket LIVE, or a strategy consumes it, or its id is in `config/*.yaml`.
- **KEEP (open unit):** an open research/queue unit names it.
- **REVIEW:** SHADOW with no consumer and no open unit. It stays only if it beats its slot baseline net of cost on a
  registered population. **That read was NOT done here** (metrics are not joined to the slot baselines), so these are not retired.
- **RETIRE:** OFFLINE, no consumer, no open unit.

## Result

| proposal | n |
|---|---|
| KEEP | 15 |
| REVIEW | 19 |
| RETIRE | 72 |

By slot: D2 regime 4 keep / 18 review / 41 retire; D3 entry 5 keep; D4, D7, D8 1 keep each; D9 1 review;
unassigned 3 keep / 31 retire. Slots D1, D5, D6 and D10 are empty.

**Compute finding:** 44 of the 72 RETIRE models still have a manifest at the top level
of `ml/configs/`. `scripts/ops/run_training_cycle.sh:171-173` trains every top-level manifest when `TRAINING_MANIFESTS`
is unset. I did not read the trainer VM's env, so whether it is set there is UNVERIFIED. If it is unset, the trainer
rebuilds these models every cycle for no consumer. Retiring one means: `git mv` its manifest to `ml/configs/retired/`
(20 already sit there), add a retirement record, and archive its registry entry on the trainer (a Tier-2 data mutation
through system-actions). All three steps can be reverted.

## Per-slot competition (step 3), as the feed shows it

- **D3 entry (Foxhound).** Champion: `ml-decision-entry-v1`, live on bybit_2 / bybit_portfolio and the prop books
  (`v1r20261106` is the refit it serves through the pointer). Challenger: `ml-decision-entry-v2` on bybit_1 (testing);
  its artifact records `w1_verdict: fail`. Equity: `ml-entry-eq-v1` (testing, alpaca_paper) vs `ml-entry-eq-struct-ens5-v1`
  (live, alpaca_live + alpaca_portfolio). **Gap:** neither pair has a pre-registered head-to-head on one replay and one cost
  stack, and none of the served artifacts names its demotion signal. Two live variants of one lineage
  (v1 / v1r20261106) is a pointer, not an ensemble; the feed should say so.
- **D2 regime (Collie / Chihuahua).** 3 LIVE heads (`btc`/`sol-regime-15m-lgbm-fc-pcv-v2`, `mes-regime-5m-lgbm-v2`),
  consumed through `src/runtime/advisory_sizing.py` / `regime/ml_vol_verdict.py`. 18 SHADOW heads have no consumer and
  no open unit. The 4 Mutt baselines are the slot baselines, so the REVIEW read is "does each shadow head beat its Mutt on
  its own shard?".
- **D4 / D7 / D8:** one model each (overlay-td-v1, tp-revision-v1, exit-head-donchian-1h-v1), so there is no competition
  to name yet.

## Proposed next steps (manager / Thursday plan)

1. Approve wave 1: retire the 72 RETIRE rows (one PR moving their manifests, plus a system-action to archive the
   registry entries; Tier 2, operator OK). Before that, read `TRAINING_MANIFESTS` on the trainer to size the compute saving.
2. Wave 2: a scripted read of each REVIEW head vs its slot's Mutt baseline (registry metrics, one shard), then retire
   the ones that do not beat it.
3. One pre-registered champion/challenger unit per D3 pair (v1 vs v2; eq-v1 vs struct-ens5) on a shared held-out window
   and the full cost stack, plus a declared demotion signal per served artifact.
4. Process audit items still open: family diversity (`ml_plan_status.py --diversity`) was not run here.

## KEEP (15)

| slot | model | name | bucket | consumer strategies | open units | active manifest |
|---|---|---|---|---|---|---|
| D2 | `btc-regime-15m-lgbm-fc-pcv-v2` | Collie-5a | LIVE | — | — | yes |
| unassigned | `conviction-meta-v1` | conviction-meta-v1 | OFFLINE | — | RQ-20261101-78fc-06 | yes |
| D2 | `eth-regime-1h-lgbm-xasset-v1` | Collie-3c | SHADOW | — | — | yes |
| D2 | `mes-regime-5m-lgbm-v2` | Chihuahua-1d | LIVE | — | — | yes |
| unassigned | `regime-classifier-baseline-v0` | regime-classifier-baseline-v0 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-p2pool-v2` | setup-candidates-metalabel-p2pool-v2 | OFFLINE | — | RQ-20261101-78fc-02 | yes |
| D2 | `sol-regime-15m-lgbm-fc-pcv-v2` | Collie-5b | LIVE | — | — | yes |
| D8 | `exit-head-donchian-1h-v1` | Labrador-2 | SHADOW | trend_donchian, trend_donchian_eth, trend_donchian_sol | RQ-20261101-78fc-03 | — |
| D3 | `ml-decision-entry-v1r20261106` | Foxhound-1 (refit r20261106) | LIVE | ml_entry | — | — |
| D3 | `ml-decision-entry-v1` | Foxhound-1 | LIVE | ml_entry | RQ-20261102-5e03-01, RQ-20261104-a41f-01 | — |
| D3 | `ml-decision-entry-v2` | Foxhound-2 | SHADOW | ml_entry_v2 | — | — |
| D3 | `ml-entry-eq-struct-ens5-v1` | Foxhound-4 | LIVE | ml_entry_eq_struct | — | — |
| D3 | `ml-entry-eq-v1` | Foxhound-3 | SHADOW | ml_entry_eq | — | — |
| D7 | `ml-entry-tp-revision-v1` | Labrador-1b | LIVE | ml_entry | — | — |
| D4 | `overlay-td-v1` | Beagle-1 | LIVE | trend_donchian_eth_4h, trend_donchian_eth_prop, trend_donchian_sol_prop | — | — |

## REVIEW (19)

| slot | model | name | bucket | consumer strategies | open units | active manifest |
|---|---|---|---|---|---|---|
| D2 | `btc-regime-15m-baseline-v1` | Mutt-Regime-1b | SHADOW | — | — | yes |
| D2 | `btc-regime-15m-lgbm-fc-pcv-v1` | Collie-4a | SHADOW | — | — | yes |
| D2 | `btc-regime-15m-lgbm-v2` | Collie-1a | SHADOW | — | — | yes |
| D2 | `btc-regime-15m-lgbm-yz-v1` | Collie-2a | SHADOW | — | — | yes |
| D2 | `btc-regime-1h-lgbm-v2` | Collie-1b | SHADOW | — | — | yes |
| D2 | `btc-regime-1h-lgbm-yz-v1` | Collie-2b | SHADOW | — | — | yes |
| D2 | `btc-regime-5m-baseline-v1` | Mutt-Regime-1a | SHADOW | — | — | yes |
| D2 | `btc-regime-5m-lgbm-v2` | Chihuahua-1a | SHADOW | — | — | yes |
| D2 | `btc-regime-5m-lgbm-yz-v1` | Chihuahua-2a | SHADOW | — | — | yes |
| D2 | `eth-regime-15m-lgbm-selfonly-v901ctrl` | Collie-3a | SHADOW | — | — | yes |
| D2 | `eth-regime-15m-lgbm-xasset-v1` | Collie-3b | SHADOW | — | — | yes |
| D2 | `eth-regime-1h-lgbm-v1` | Collie-1c | SHADOW | — | — | yes |
| D2 | `eth-regime-5m-lgbm-v1` | Chihuahua-1b | SHADOW | — | — | yes |
| D9 | `execution-quality-baseline-v0` | Mutt-Execution-1a | SHADOW | — | — | yes |
| D2 | `mes-regime-15m-baseline-v1` | Mutt-Regime-1d | SHADOW | — | — | yes |
| D2 | `mes-regime-1d-lgbm-v2` | Collie-1d | SHADOW | — | — | yes |
| D2 | `mes-regime-5m-baseline-v1` | Mutt-Regime-1c | SHADOW | — | — | yes |
| D2 | `sol-regime-15m-lgbm-fc-pcv-v1` | Collie-4b | SHADOW | — | — | yes |
| D2 | `sol-regime-5m-lgbm-v1` | Chihuahua-1c | SHADOW | — | — | yes |

## RETIRE (72)

| slot | model | name | bucket | consumer strategies | open units | active manifest |
|---|---|---|---|---|---|---|
| D2 | `btc-regime-15m-c1-base` | btc-regime-15m-c1-base | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-c1-macro` | btc-regime-15m-c1-macro | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-hmm-cw-v1` | btc-regime-15m-hmm-cw-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-hmm-fc-v1` | btc-regime-15m-hmm-fc-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-hmm-v1` | btc-regime-15m-hmm-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-lgbm-base-pcv-v003` | btc-regime-15m-lgbm-base-pcv-v003 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-lgbm-base-v003` | btc-regime-15m-lgbm-base-v003 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-lgbm-base-vt003-pcv-v1` | btc-regime-15m-lgbm-base-vt003-pcv-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-lgbm-corpusemb-pcv-v1` | btc-regime-15m-lgbm-corpusemb-pcv-v1 | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-lgbm-emb-pca-v1` | btc-regime-15m-lgbm-emb-pca-v1 | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-lgbm-emb-pcv-v1` | btc-regime-15m-lgbm-emb-pcv-v1 | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-lgbm-emb-v1` | btc-regime-15m-lgbm-emb-v1 | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-lgbm-fc-v1` | btc-regime-15m-lgbm-fc-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-lgbm-fcemb-pcv-v1` | btc-regime-15m-lgbm-fcemb-pcv-v1 | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-lgbm-v2-gpuburst` | btc-regime-15m-lgbm-v2-gpuburst | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-lgbm-vt003-pin-v1` | btc-regime-15m-lgbm-vt003-pin-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-lgbm-vt004-pcv-v1` | btc-regime-15m-lgbm-vt004-pcv-v1 | OFFLINE | — | — | — |
| D2 | `btc-regime-15m-lgbm-vt004-pin-v1` | btc-regime-15m-lgbm-vt004-pin-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-lgbm-vt005-pin-v1` | btc-regime-15m-lgbm-vt005-pin-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-15m-tcn-v1-gpuburst` | btc-regime-15m-tcn-v1-gpuburst | OFFLINE | — | — | — |
| D2 | `btc-regime-1h-hmm-v1` | btc-regime-1h-hmm-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-1h-lgbm-base-pcv-v003` | btc-regime-1h-lgbm-base-pcv-v003 | OFFLINE | — | — | yes |
| D2 | `btc-regime-1h-lgbm-emb-pcv-v1` | btc-regime-1h-lgbm-emb-pcv-v1 | OFFLINE | — | — | — |
| D2 | `btc-regime-1h-lgbm-funding-svble-v1` | btc-regime-1h-lgbm-funding-svble-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-1h-lgbm-funding-v1` | btc-regime-1h-lgbm-funding-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-1h-trend-lgbm-v1` | btc-regime-1h-trend-lgbm-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-5m-lgbm-flow-v1` | btc-regime-5m-lgbm-flow-v1 | OFFLINE | — | — | yes |
| D2 | `btc-regime-5m-lgbm-flow-v1-offload` | btc-regime-5m-lgbm-flow-v1-offload | OFFLINE | — | — | — |
| D2 | `eth-regime-15m-hmm-cw-v1` | eth-regime-15m-hmm-cw-v1 | OFFLINE | — | — | yes |
| D2 | `eth-regime-15m-lgbm-base-pcv-v003` | eth-regime-15m-lgbm-base-pcv-v003 | OFFLINE | — | — | yes |
| D2 | `eth-regime-15m-lgbm-emb-pcv-v1` | eth-regime-15m-lgbm-emb-pcv-v1 | OFFLINE | — | — | — |
| D2 | `eth-regime-15m-lgbm-fc-pcv-v1` | eth-regime-15m-lgbm-fc-pcv-v1 | OFFLINE | — | — | yes |
| D2 | `eth-regime-15m-lgbm-v1` | eth-regime-15m-lgbm-v1 | OFFLINE | — | — | yes |
| D2 | `eth-regime-1h-lgbm-v1-offload` | eth-regime-1h-lgbm-v1-offload | OFFLINE | — | — | — |
| D2 | `mes-regime-15m-lgbm-v2` | mes-regime-15m-lgbm-v2 | OFFLINE | — | — | yes |
| D2 | `mes-regime-15m-lgbm-yz-v1` | mes-regime-15m-lgbm-yz-v1 | OFFLINE | — | — | yes |
| D2 | `mes-regime-5m-lgbm-macro-v1` | mes-regime-5m-lgbm-macro-v1 | OFFLINE | — | — | yes |
| D2 | `mes-regime-5m-lgbm-yz-v1` | mes-regime-5m-lgbm-yz-v1 | OFFLINE | — | — | yes |
| D2 | `mes-regime-classifier-baseline-v0` | mes-regime-classifier-baseline-v0 | OFFLINE | — | — | — |
| D2 | `sol-regime-15m-lgbm-base-pcv-v530` | sol-regime-15m-lgbm-base-pcv-v530 | OFFLINE | — | — | yes |
| D2 | `sol-regime-15m-lgbm-v1` | sol-regime-15m-lgbm-v1 | OFFLINE | — | — | yes |
| unassigned | `btc-c1-base-v903` | btc-c1-base-v903 | OFFLINE | — | — | — |
| unassigned | `btc-c1-base-v905` | btc-c1-base-v905 | OFFLINE | — | — | — |
| unassigned | `btc-c1-macro-v903` | btc-c1-macro-v903 | OFFLINE | — | — | — |
| unassigned | `btc-c1-macro-v905` | btc-c1-macro-v905 | OFFLINE | — | — | — |
| unassigned | `btc-direction-15m-lgbm-base-v003` | btc-direction-15m-lgbm-base-v003 | OFFLINE | — | — | yes |
| unassigned | `btc-direction-15m-lgbm-emb-v1` | btc-direction-15m-lgbm-emb-v1 | OFFLINE | — | — | — |
| unassigned | `btc-direction-15m-lgbm-fc-v1` | btc-direction-15m-lgbm-fc-v1 | OFFLINE | — | — | yes |
| unassigned | `conviction-meta-base-btc-v1` | conviction-meta-base-btc-v1 | OFFLINE | — | — | yes |
| unassigned | `conviction-meta-emb-btc-v1` | conviction-meta-emb-btc-v1 | OFFLINE | — | — | — |
| unassigned | `conviction-meta-v1-bt` | conviction-meta-v1-bt | OFFLINE | — | — | yes |
| unassigned | `corpus-ssl-encoder-mae-v1` | corpus-ssl-encoder-mae-v1 | OFFLINE | — | — | — |
| unassigned | `eth-direction-1h-lgbm-v1` | eth-direction-1h-lgbm-v1 | OFFLINE | — | — | yes |
| unassigned | `eth-direction-1h-lgbm-xasset-v1` | eth-direction-1h-lgbm-xasset-v1 | OFFLINE | — | — | yes |
| unassigned | `mes-setup-quality-baseline-v0` | mes-setup-quality-baseline-v0 | OFFLINE | — | — | — |
| unassigned | `mes-trade-outcome-winrate-baseline-v0` | mes-trade-outcome-winrate-baseline-v0 | OFFLINE | — | — | — |
| unassigned | `prop-mission-policy-baseline-v0` | prop-mission-policy-baseline-v0 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-backtest-c1-v1` | setup-candidates-metalabel-backtest-c1-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-backtest-c2-v1` | setup-candidates-metalabel-backtest-c2-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-backtest-v1` | setup-candidates-metalabel-backtest-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-p2pool-c1-v1` | setup-candidates-metalabel-p2pool-c1-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-p2pool-v1` | setup-candidates-metalabel-p2pool-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-siglog-v1` | setup-candidates-metalabel-siglog-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-v1` | setup-candidates-metalabel-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-xsym-v1` | setup-candidates-metalabel-xsym-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-candidates-metalabel-xsym-yz-v1` | setup-candidates-metalabel-xsym-yz-v1 | OFFLINE | — | — | yes |
| unassigned | `setup-quality-audit-baseline-v0` | setup-quality-audit-baseline-v0 | OFFLINE | — | — | yes |
| unassigned | `setup-quality-baseline-v0` | setup-quality-baseline-v0 | OFFLINE | — | — | — |
| unassigned | `setup-quality-lgbm-v2` | setup-quality-lgbm-v2 | OFFLINE | — | — | — |
| unassigned | `trade-outcome-global-baseline-v0` | trade-outcome-global-baseline-v0 | OFFLINE | — | — | — |
| unassigned | `trade-outcome-lgbm-v1` | trade-outcome-lgbm-v1 | OFFLINE | — | — | yes |
| unassigned | `trade-outcome-winrate-baseline-v0` | trade-outcome-winrate-baseline-v0 | OFFLINE | — | — | — |
