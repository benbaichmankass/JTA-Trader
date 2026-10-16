# Programme 02 (AI trader) + Regime + Data Infra: audit, 2026-10-16

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../../../DOCUMENT-INDEX.md`](../../../../DOCUMENT-INDEX.md) · manager programme audit 2026-10-16 (input to the backlog lanes and the 2026-10-20 programme review) · **Tier-1: nothing here changes a config, a roster or an order path.**

## 1. Intent
- **Goal (G4):** one AI trader that reads every signal, regime, funding/flow and test-result input and decides act / manage / stand aside. Each capability is earned offline and climbs candidate → shadow → advisory. The headline measure is **net P&L per capital-day**, in R and USD (02 §1).
- **Q0:** can we trust the measure, the labels and the signals? **Q1:** do regime/vol heads separate good trades from bad, net of cost (L-REGIME/M25)? **Q2:** M23 meta-labeling on test results. **Q3:** peak-to-exit and in-trade exit models. **Q4:** model families beyond GBDT. **Q5:** new information classes.
- **Data (06, L-DATA):** a whole, catalogued store at fine grain; labels that are measurements rather than conventions (ties); funding/OI/flow data beyond BTC.
- **Money:** today only the 3 advisory vol heads can touch size, and only by downsizing (`advisory_sizing`). The P2 node values in the yaml ($150–300/mo) are INFERRED planning weights.

## 2. What has been done (results under `research/results/`)
- **Q0, mostly answered:** `9d20-01` PASS on 10-14: pullback headroom 1.54 R/trade (n=4,900 ledger trades). `d6e7-01` PASS on 10-15: turn-oracle saving 0.656 R/trade at K=2 (n=3,926). `736c-01` PASS: corpus can be built (n=1,831). **Q0.1 headline measure is OPEN** (`HEADLINE-MEASURE-CAPITAL-DAY` is still queued, and three competing definitions are in circulation). **Q0.4 has no unit at all:** `RQ-20261011-17f4-02` is absent from queue/, blocked/ and results/, even though the plan calls it queued.
- **Q2, the thin-column route is closed:** `9d20-02` FAIL on 10-14. On every leg, every arm's AUC interval contains the class prior (n=1,796). The next rung, `9d20-04`, is blocked on `METALABEL-EMIT-FEATURES` (queued, not started).
- **Q3:** `9d20-03` FAIL (giveback cannot be predicted at entry, n=1,680). `d6e7-02` FAIL: the simple in-trade state shows no gain (CI upper 0.00021 nats, n=3,926). `d6e7-04` INDETERMINATE: rich state gain 0.00054 nats, CI [-0.00118, 0.00245]. **OPEN.**
- **Q1 trend axis, effectively answered NO:** of `RQ-20260930-701`, `-703` and `RQ-20261012-75b2-01..15`, 16 FAIL. The one PASS, `75b2-05` (scalp at min_cell_n=8, n=686), has a sibling, `-06` (min_cell_n=20), that FAILs, so it depends on cell-size selection. **Q1.4 vol axis with the ML label has never had a usable unit:** `RQ-20260930-704` is done but has no record.
- **Q1 lever skips on live legs:**
  - PASS: `407c-13`, `-14`, `-15` (session skip on eth/xrp/ada pullback_2h: +4.35 / +6.51 / +1.92 R over the removed-lever baseline, n=116 / 122 / 111) and `407c-21` (trend_donchian_sol VH90 +11.36 R, n=120).
  - `f0e2-10` PASSed, then its confirmation `470a-10` FAILed on a fresh window (n=83).
  - The other 407c/f0e2/470a units FAIL or are underpowered (n=25–36).
- **Q1.3 head quality:**
  - Drift: `75b2-16/17/18` FAIL. 15m LightGBM vs the class prior on the 90-day holdout: BTC −0.0001, ETH +0.022, SOL +0.054, against a +0.10 bar (n=36,000 each).
  - Log-loss beats the prior: `65cc-10`, `4591-01`, `4591-06` (n=14,400) and `eda2-01` (n=315,492) all PASS. That **unlocks Q1.5 conformal.**
  - HAR-RV control for the shipped `fc_*` features (`1414-04`): INDETERMINATE.
- **Direction label:** `4591-02` FAIL. `1414-03` and `4591-05` INDETERMINATE. No price-only direction edge.
- **Q4 families:**
  - logit: `65cc-09` FAIL at 1h, `1414-01` INDETERMINATE. `4591-03` PASS shows LightGBM beats logit on log-loss.
  - CatBoost: `de02-01` PASS (n=48,000) after a fix. `4591-04` had been broken by a CatBoost TypeError.
  - ExtraTrees/MLP: `1414-07`, `9d20-05`, `ab54-01` all INDETERMINATE. ExtraTrees PASS on MES 1d (`1414-05`, n=1,764).
  - TabICL/TabPFN: `65cc-06/07/08` INDETERMINATE because arms were unavailable. `1414-06` producer_failed (trainer lock wait of 3,601 s). `eda2-02` INDETERMINATE.
  - `ml_plan_status --diversity`: gbdt is 76 of 97 manifests. The ensemble_stack history holds no PASS, so the `1414-05` PASS was apparently not written back (INFERRED).
- **Kaggle offload:** `KAGGLE-CPU-ROUTE` is done. `8b93-01` gives the reference and `8b93-02` PASS: parity within tolerance (n=8,694).
- **Data Q1:** `da7a-01` produced `verdict: "MIXED"` and was rejected as malformed (producer_failed, not graded). The measurement inside it says the tie convention is not material:
  - Max mislabel share is 0.54% (ict_scalp K=1, n=919). Pullback is 0%, donchian 0.27%, squeeze 0.24% (25 legs, n=3,356).
  - The rule is NEEDED at ≥2% and NOT_NEEDED below 0.5%, so this lands between the two.
- **Drift flag:** PI-20261016-P3PFA1GK-0001 is due 10-20. The same 9 heads were flagged on 16–17 consecutive hourly scans, including advisory `sol-regime-15m-lgbm-fc-pcv-v2`. The scans run plan-only and have never retrained anything.

## 3. Queue state
I attributed units by theme ∈ {regime, ml_health}, by roadmap ∈ {L-REGIME, M25, M23, L-DATA, M16, M26}, or by id containing `da7a`. That gives **106 units: 86 done · 14 blocked · 5 queued · 1 retired**. On top of these, 6 blocked regime questions carry `theme: None` (RQ-20260927-006/007/008, 20260928-006, 20260929-109/110).
- **None of the 5 queued units is a live open question.** `RQ-20260927-003` has been queued since 09-27 although its result has already landed. `8b93-02`, `RQ-20261016-8b93-01` and `RQ-20261016-001` each already have a result (it landed 10-16 and is not yet graded). `d6e7-05` requires a `d6e7-04` PASS, and `d6e7-04` was INDETERMINATE, so it cannot fire.
- **Regime has 0 queued units against weight 5. Confirmed:** 37 done, 1 blocked (`9da8-01`), last dispatch 10-15T01:04Z. Causes:
  - No automatic producer emits `theme: regime`. Across templates and programme yamls there are 6 `theme:` lines and 0 of them are regime (the positive control found the 6).
  - There is no regime programme yaml; only 01 and 02 exist.
  - The 02 plan says it "adds nothing to the queue for Q1".
  - The hand-authored fills ran dry.
  - `REGIME-PROGRAM` and `QUEUE-THEME-ALIGN` have both been queued since 10-11 and never dispatched.
  - Deliverables 2–4 of `REGIME-PROGRAM` (HMM/clustering comparison, a baseline direction model) never got a unit.
- **Blocked, and on what:**
  - `METALABEL-EMIT-FEATURES` → `9d20-04`
  - `FRONTIER-LEVER-TSFM` → `9da8-01`, `1414-08`
  - `FRONTIER-LEVER-TABULAR` → `9da8-02`
  - `FRONTIER-LEVER-CONFORMAL` → `9da8-03`
  - `ML-LEG-CORPUS` / `EXIT-PATH-EMIT-OFFLINE` → `9da8-04`
  - `FUNDING-OI-DATASETS-ETH-SOL` → `1414-09`, 109, 110
  - `ML-DRIFT-SPLIT-INSTRUMENT` → `6e85-01`
  - `DATA-KLINE-ARCHIVE` → `da7a-02`
  - `DATA-DERIV-ARCHIVE` → `da7a-03`
  - Every one of these build rows is `queued` and not started.

## 4. Misalignments and problems
1. **Regime PASSes nobody acted on.** `407c-13/14/15` and `407c-21` have no confirmation unit, no checklist row and no pipeline item. The `regime-selectivity` rule requires walk-forward before Tier-3, and the `f0e2-10` → `470a-10` reversal shows why. These are real-money legs, and xrp/ada pullback_2h already read BELOW_BACKTEST (`8bbc-01/02`).
2. **Theme weight never reaches the work:** no producer, the blocked regime units are untagged, and the classifier deliverables were never written.
3. **M23 has no runnable unit.** Every next rung waits on two Tier-1 emit rows that have not started.
4. **Integrity defects:**
   - The `da7a-01` verdict enum means a finished measurement was thrown away.
   - Empty 15m holdouts (PI-20261015-WNBZB5WN-0001; 7 units, two of which landed false FAILs).
   - TabICL/TabPFN arms unavailable on Kaggle; CatBoost broken in `4591-04`.
5. **Duplicate spend:** programme node `P2-Q4-et-mlp-extend` generated `RQ-20261016-001`, which repeats `ab54-01` (both at tail_rows 43000, both INDETERMINATE).
6. **Stale plan text:** 02 §3/§6 call `17f4-02` "queued" and list 75b2/1414 units as queued (they are done). 06 §7 W1 is unchanged.
7. **Drift flags never clear,** and `ML-REGIME-15M-DRIFT` has been queued since 10-15.

## 5. Recommended next 5 days (to Tue 2026-10-20)
1. **[research unit] Confirm the 4 regime-lever PASSes on fresh windows,** with `theme: regime`. First step: clone `RQ-20261014-470a-10.yaml` once each for eth/xrp/ada_pullback_2h session-skip and trend_donchian_sol VH90.
2. **[build row] Dispatch `METALABEL-EMIT-FEATURES` + `EXIT-PATH-EMIT-OFFLINE` as one lane.** They gate M23 P3 and the exit line. First step: the shared emit helper in `scripts/backtest_trend.py`, with existing keys kept byte-identical.
3. **[decision for operator] Drift.** Approve Q1 of `TRAINER-DRIFT-NEXT`: the timer goes from hourly to every 3 h, saving about 23 CPU-h/week. Run a drift-remediation pass on `sol-regime-15m-lgbm-fc-pcv-v2` first (`ML-REGIME-15M-DRIFT`). Keep arming retrains (Q2) on hold.
4. **[build row] Fix the `da7a-01` producer** so it emits `indeterminate`, and record the result. Then move `DATA-KLINE-ARCHIVE` down to an information-source priority and move `DATA-DERIV-ARCHIVE` + `DATA-CATALOG` up, since they unblock `da7a-03`, `1414-09` and 109/110.
5. **[research unit] Author the `P2-Q1.5` conformal unit at 1h**, now that the log-loss gate has passed. First step: scope `FRONTIER-LEVER-CONFORMAL`.
6. **STOP or retire:**
   - The `P2-Q4-et-mlp-extend` node and `RQ-20261016-001`.
   - Direction-label units on price-only inputs.
   - Move `RQ-20260927-003` to done or retired.
   - Move `d6e7-05` to blocked.
   - Retag the 6 untagged regime units.
   - Fix 02 §3/§6 to drop the phantom `17f4-02`.

CONFIDENCE: Verified directly: unit statuses, result verdicts and n, checklist states, `THEMES.yaml`, the producer theme grep, the diversity output, and the `da7a-01` `verdict.json`. Inferred: the money ranking, that the `1414-05` PASS was missed in the family history, and that the stale "queued" statuses are grader lag.