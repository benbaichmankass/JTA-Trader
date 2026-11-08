# ml_entry_eq with the live structure exit — grade and Tier-3 proposal (2026-11-07)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · Tier 3 (HELD, operator decides) · lane ML-ENTRY-EQ-STRUCTURE-RETEST
> Gates this adds or changes: none.

## 1. Grade (rule applied from the record, not from the runner's verdict)

Record: `research/results/RQ-20261106-98e3-01/42315121734.jsonl` (run 42315121734). Rule: `RULE-RQ20261106-98e3-01-ENTRY-EQ-STRUCTURE`.

| Clause | Required | Measured | Met |
|---|---|---|---|
| n >= 30 | 30 | n = 570 trades / 140 symbols (pool 173) | yes |
| (a) confirm mean net R >= t_min(N=2) x iid se | 0.5198 x 0.0462 = 0.024 | +0.2123 net R (gross +0.2618, cost 0.0495) | yes |
| (b) dev OOF mean at selected tau > 0 | > 0 | +0.1222 (tau 0.20, n=3004, 157 symbols) | yes |
| (c) confirm mean >= 0 | >= 0 | +0.2123 | yes |

**PASS, confirmed.** Ledger N=2 (second read of the 2025-07-15..2026-10-31 window), booster sha256 `90329845d55d7dfa...`, 368,757 training rows, config B, structure exit `pivot=5;sl_only`, TP fixed 3 ATR, SL 2 ATR.
Compare: the fixed 2/3 ATR bracket model read +0.0392 (n=858), so the structure-trained model reads +0.17 R higher on a different trade set.

## 2. Honest read (what the PASS does and does not say)

- **Significance:** iid t = 4.6, but trades cluster in time. Month-clustered se 0.105, so t = 2.02. The N=2 deflated *point* bar is cleared. The deflated CI bar (z 2.239) is NOT cleared on the clustered se: 0.2123 - 2.239 x 0.105 = -0.023. It is a holdout pass under the registered point rule, not a statistically proven edge. DSR is probation (OPERATING-PLAN § 2).
- **Concentration (computed from `by_month`):** 11 of 16 months positive. Dropping 2026-03 (n=166) leaves n=404, mean +0.192; dropping 2026-03 and 2026-01 (n=116) leaves n=288, mean +0.223; dropping those two plus 2025-08 leaves n=226, mean +0.200. The result does not depend on any single month. Sparse months with n<=11 are noisy (2025-07 -1.12 n=5, 2025-12 -0.72 n=11, 2026-06/07 n=1).
- **Per symbol:** the 10 most-traded symbols each have n 7-12 (top-10 means -0.15..+0.56; 8 of 10 positive). Per-symbol results never gate (CLAUDE.md, "An account configures strategies, never symbols").
- **Dev folds are not uniformly positive:** 5 dev folds read +0.197, +0.245, -0.051, -0.222, +0.332 (pooled +0.122). The tau grid is monotone up to its edge (0.05 -> +0.054 ... 0.20 -> +0.122): the selected tau is the grid boundary, so a higher tau was never tested.
- **Declared limits of the arm:** TP fixed at 3 ATR (live `ml_entry` also has an `ml_first_passage` tp_revision; `ml_entry_eq` does not); slippage is PROVISIONAL (5 bps); structure levels use each ETF's own 1h RTH bar sequence.

## 3. The proposal (Tier 3, NOT merged by this lane)

**Pre-requisite found while writing this — the served model is not the graded model.** `ml_entry_eq` on `alpaca_paper` serves a fixed-bracket booster (`ml/candidates/ml_entry_eq_v1`, sha `ceeb8698bb130b9b`, the pinned refit; the graded fixed-bracket fit was `af4835e29fe83c86`, also a different fit — corrected 2026-11-07, this line first cited the graded sha). The PASS above is for a *re-trained* booster (`90329845d55d7dfa`). Setting `structure_exit` on the existing leg would put the live exit on a model trained for a different exit. Order of work:

1. **Export** (Tier 1, queued here as `RQ-20261107-98e3-02`): deterministic refit with `--structure`, expected sha `90329845d55d7dfa`, writes `model.json` + `parity_fixture.json` for the serve-parity step (`docs/research/ml-entry-eq-serve-spec-2026-11-06.md`).
2. **Serve** the structure model as a NEW candidate id (do not overwrite `ml_entry_eq_v1`) and pass the serve-parity fixture.
3. **Config** (Tier 3), after 1-2:
   - `config/strategies.yaml::ml_entry_eq`: add `structure_exit: "pivot=5;sl_only"`; keep `atr_stop_mult: 2.0`, `tp_r: 1.5`, `model` -> the structure model id, tau 0.20, restricted long.
   - `config/accounts.yaml`: add `ml_entry_eq` to `alpaca_live.strategies` (real money, `side_filter: long` already matches the long-only model) and to `alpaca_portfolio.strategies` (Stage 2 is one stage; the mirror is a superset, `tests/test_paper_portfolio_accounts.py`). `alpaca_paper` keeps the leg as the Stage-1 mechanics floor.
   - **Symbols:** an account configures strategies, never symbols. The leg's population is the tested 173-ETF pool limited to what Alpaca can trade. The currently-rostered 10 (SPY QQQ IWM TLT IEF SLV USO GDX TQQQ QLD) are a tick-cost rollout stage, not the tested population; widening to the whole pool needs the tick-duration measurement already named in the leg's comments.
   - **Affordability / per-symbol cost: NOT MEASURED here.** `alpaca_live` risk is `risk_pct 0.02`, `daily_usd 200`, `daily_dd_switch armed 0.03`; the account balance is not in the journal snapshots (ALPACA-LIVE-ACTIVITY-ML note: snapshots carry no balance) and I did not read it live. Whole-share sizing means a symbol is affordable only if 2% risk / (2 ATR14 stop distance) buys >= 1 share; the existing affordability-proxy mechanism (full-size underlying, sub-$100 proxies SPYM/IAUM/SCHA) covers the expensive ones. The cost basis tested is slippage 5 bps (PROVISIONAL) + 0.5 bps regulatory, fee 0, per symbol identical. A real per-symbol slippage read comes only from the first fills.
4. **Verification watch (first 1-2 live trades, mechanics only, not edge):** entry fills at the next RTH open within the bracket; SL 2 ATR and TP 3 ATR rest at the venue; the structure verdict tightens the stop only (never looser than the entry stop, `structure_sl_cross` closes at price); no zombie OCO; journal row carries `ml_entry_eq` and the model id; realized slippage vs the 5 bps assumption.

**Revert:** delete `ml_entry_eq` from `alpaca_live.strategies` and `alpaca_portfolio.strategies` (one line each); remove `structure_exit:` from the leg; the fixed-bracket model stays on `alpaca_paper`.

## 4. Why this holds under the rules

Holdout governs real money (OPERATING-PLAN § 2, 2026-11-06): the configuration chosen on dev cleared its registered rule on held-out data net of the full cost stack (committed record above); DSR is probation; paper is not a gate. Mechanics are proven for Alpaca equities by `tqqq_trend_long_1d` on `alpaca_live`; the ML leg's own mechanics are proven on `alpaca_paper`. Not claimed: statistical significance on the clustered se, or a measured affordable symbol set.

## 5. Addendum 2026-11-07 — export, serve-parity and tau-extension results

**Export `RQ-20261107-98e3-02` (run 42394189988).** The unpinned refit did NOT reproduce the graded booster (`a14098f9...` vs graded `90329845...`; train rows 368,752 vs 368,757). Shipped = the pinned deterministic refit, sha `16faaa1948b087ec...`, committed as `ml/candidates/ml_entry_eq_v2_struct/` (model.json + parity_fixture.json; tests `tests/test_ml_entry_eq_struct_artifact.py` pass: booster reproduces the fixture to 1e-9). Against the unpinned fit on 20,000 training-tail rows: spearman 0.961, decision agreement at tau 0.985, max |d| 0.753. **The model that would be served is therefore a close sibling of the graded one, not the graded one itself.**

**Run-to-run variance (finding).** Dev unit `RQ-20261107-98e3-03` (run 42396313667), same config B / structure labels / dates, read tau 0.20 at **+0.083 (n=3191)**; the graded dev stage read **+0.1222 (n=3004)**. The two differ by 0.04 R with an unpinned LightGBM and a few rows of data drift — the same size as the effect being measured. The graded +0.2123 confirm is one unpinned fit. Scoring the shipped pinned model on the confirm window would be a third read of that window (ledger N=3) and has NOT been done.

**Tau extension (rule fixed before the run: plateau / cliff / rising edge).** Dev OOF pooled mean net R: tau 0.20 +0.083 (n 3191), 0.25 +0.109 (1943), 0.30 +0.197 (1122), 0.40 +0.204 (342, only 10 trades in fold 4). Outcome by the registered rule: **RISING EDGE** (tau 0.30, n>=300, reads >= +0.15). Fold 3 reads -0.35..-0.44 at every tau. This is a hypothesis for a later N=3 confirm unit, never an adopted tau; the graded record and the proposed tau 0.20 are unchanged.

**What this changes for the operator.** The PASS stands as recorded. Before real money, the evidence gap is the served pinned model: it is a different fit from the one graded, and the fit-to-fit spread is large relative to the edge.

## 6. Addendum 2026-11-08 — seed variance (04) and 5-seed ensemble (05), registered rules applied

Records: `comms/research/RQ-20261107-98e3-04/42417906259/`, `comms/research/RQ-20261107-98e3-05/42417908525/` (dev stage only; no confirming window loaded).

**04, seed variance (pinned seeds 1-5, config B, structure labels).** Pooled dev OOF mean net R at tau 0.20 per seed: +0.108, +0.082, +0.063, +0.110, +0.098 (n 2990-3254 each): range **0.047**, 5-seed mean **+0.092**. At tau 0.30: +0.194, +0.129, +0.061, +0.213, +0.169: range **0.152**, mean +0.153 (n 936-1144). Registered reading: **SEED-NOISE-DOMINATED** at tau 0.20 (range >= 0.04); the 5-seed mean is above 0, so the graded dev selection is not purely a fit artifact. Higher tau is far noisier (range 0.15 at 0.30 with a third of the trades).

**05, 5-seed ensemble (mean of 5 pinned fits).** Dev OOF at tau 0.20 **+0.092** (n 2879), 0.25 +0.118 (1688), 0.30 +0.190 (954); folds at 0.20: +0.131, +0.196, -0.044, -0.230, +0.295. Registered reading: **ENSEMBLE-ADMITTED** (tau-0.20 mean >= +0.083, and only 1 of 5 folds below -0.10, fold 3). Admission is only the right to run the N=3 confirm unit `RQ-20261107-98e3-06`; it adopts no tau, model or roster.

**Caveats carried into 06.** (1) Fold 3 is negative at every seed, tau and the ensemble (-0.2 to -0.4). (2) 06 selects tau on dev over {0.20, 0.25, 0.30} by max pooled OOF mean, so it will pick the noisiest tau (0.30, ~950 dev trades, so ~1/3 as many confirm trades): its iid se will be ~0.08 and the N=3 point bar (t_min 0.853) ~0.07 R. (3) The +0.04 R margin floor registered in 06 understates the single-fit noise at tau 0.30 (range 0.15); the ensemble averages that noise down but the unit does not measure by how much on the confirm window.

## 7. Addendum 2026-11-08 — re-queued regime/direction-head questions (07-10), Kaggle CPU route

`RQ-20261107-98e3-07..10` re-ask four `ml_bakeoff` questions whose only runs (2026-11-02) ended `producer_failed` (never measured). Units with `routing.published_data` must run on `research-script-run-kaggle-cpu.yml` (a plain GitHub-runner dispatch fails with `dataset path datasets-out/... not found`, run 42432563196, not a record). Sign convention, from `build_deltas`: `deltas[group][window][LEARNER][REF]`, positive = LEARNER better than REF. Records: `comms/research/RQ-20261107-98e3-{07,08,09,10}/<run>/` (runs 42432760067, 42434161072, 42435164154, 42436008571).

| Unit | Question (BTC/ETH/SOL 1h, 5-fold CV) | Result (registered rule) |
|---|---|---|
| 07 | regime head: does HAR-RV lift sklearn HGB? | indeterminate; plain HGB beats the class prior by 0.095-0.12 nats |
| 08 | direction head: does HAR-RV lift default LightGBM? | **FAIL** (lgbm_har below lgbm by 0.0013/0.0029/0.0074); the class prior beats default LightGBM by 0.006-0.007 nats (CIs exclude 0) |
| 09 | regime head, latest 25,000 bars: does the HAR-RV lift persist? | indeterminate (lgbm_har vs lgbm +0.001/+0.004/+0.008, CIs include 0); lgbm beats the prior by 0.089/0.095/0.122 |
| 10 | direction head: does a small sklearn MLP beat the class prior? | **FAIL** (mlp vs prior -0.0004/-0.0008/-0.0373, CIs include 0) |

Reading: the 1h REGIME head has clear skill over the prior (HGB and LightGBM, ~0.09-0.12 nats) and HAR-RV adds at most ~0.001-0.008 (not distinguishable from 0); the 1h DIRECTION head has no skill over the prior for LightGBM (slightly negative) or a small MLP (indistinguishable from 0). These are research bake-off recipes, not any deployed head; no served model was read or changed.
