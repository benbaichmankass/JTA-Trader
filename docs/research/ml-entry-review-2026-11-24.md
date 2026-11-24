# ml_entry review: why it keeps betting against the tape, and why the equity ML legs are quiet (2026-11-24)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ML-ENTRY-REVIEW-20261124`, dispatched by Manager Session 2026-11-22a on the operator's ask (2026-11-24 ~15:15Z)

**Gates this adds or changes:** none. This memo diagnoses and proposes; every change it names is a registered research unit or an existing row. Following the operator's 11-24 scope ("I dont want a demotion recommendation"; "I want solutions"), it makes no demotion recommendation. The answer to a weak model is the next iteration, built on offline evidence (drift-remediation skill).

Operator, verbatim: *"We need to figure out what's going on with ML entry and what to do about it, I want a review and research session regarding the repeated betting long into a short market - what is driving the decisions? Also, how is there still no activity on the equity entries?"*

## Solutions, ranked by money

| # | Cause it fixes | Fix | How it is tested | State |
|---|---|---|---|---|
| 1 | The model has no input that says which **regime** a BTC panic or rally sits in, so its contrarian rule fires the same way in a bear as in a bull | Add 5 slow market-state columns to the recipe: BTC 7d and 30d return, the BTC vol percentile over 90d, BTC distance from its 50d mean, and 7d breadth | **RQ-20261124-e1a7-01**. Dev folds; must beat both the recipe and a 5-column noise placebo by +0.0068 R/decision, week-clustered t ≥ 2, ≥ 6/8 folds, ≥ 3/4 years. Harness arm built in this lane (`ml_decision_entry.py lever-arms --arm regime`) | queued (local read below if it lands) |
| 2 | **One bet ×5**: each bar's 4–5 same-side entries are one market call sized as five independent trades | Per bar, take only the best-predicted candidate | **RQ-20261124-e1a7-02**. Must beat all-candidates and a random 1-of-k pick by +0.0068; per-bar risk reported (`lever-arms --arm top1`) | queued |
| 3 | The replacement read grades a candidate on 14 days, which measures the regime, not skill: the long side lost in every window since 10-23 while the aggregate passed | Read the 14-day replacement verdict next to its by-side split and the window's always-long/always-short baselines | Operator's rule (RULE-ENTRY-PROMOTE-20261106 Amendment 1). Proposal only; row ML-ENTRY-PROMOTE-READ-REGIME | decision for the operator |
| 4 | Equity, real money: alpaca_live cannot buy one whole share of most pool ETFs | Fractional execution (day-only orders plus a daily bracket re-arm) | Existing row **FRACTIONAL-ETF-EXECUTION** (operator OK'd the build 2026-11-23); evidence added | build row |
| — | Exits | **Keep them.** Live management (structure SL tighten plus live-review closes) made **+11.2 R** vs the untouched bracket on the same 26 trades | AM v2 stage-B units already queued (RQ-20261124-b5a1-0x) | no change |

## Part 1: what drives the side decision

### How the side is chosen (code, MEASURED)

`src/units/strategies/ml_entry.py::decide`: two LightGBM **regressors** predict the net R of a long and of a short (`booster_txt.long` / `.short`). The side is the argmax, traded iff its prediction > **tau 0.10** (one tau for both sides). bybit_2 declares no `side_filter` or `account_profiles` (package meta has no `account_profile`). There is no asymmetry in thresholds or gating.

### Population read

Population: all 61 `ml_entry` order packages in the journal from 2026-11-16 00:02Z to 2026-11-24 12:03Z (`journal?table=order_packages&limit=1000`). Of these, 39 are crypto (22 long, 17 short), 22 ETF. Trades: the 31 `ml_entry` rows on `bybit_2` in `journal?table=trades&limit=1000` (2026-11-16..11-24). 26 are closed with venue P&L. R is venue net P&L ÷ (qty × the package's signal-time `risk_per_unit`); provenance MEASURED.

| Model served | bybit_2 closed | Side | Σ R | mean R |
|---|---|---|---|---|
| v1r20261106 | 4 | short | +1.69 | +0.42 |
| v1r20261115 | 6 | short | −2.75 | −0.46 |
| v1r20261115 | 9 | long | −2.68 | −0.30 |
| v1r20261122 (served since 11-24 00:00Z) | 7 | long | −2.05 | −0.29 |
| **all** | **26** | | **−5.79** | **−0.22** |

Live bar (OPERATING-PLAN § 2, ≥ 20 trades, ΣR > 0, ~80% lower bound > 0): **n = 26, ΣR = −5.79**. The leg does not clear it. Reported as a position, not a recommendation.

### Hypotheses

| # | Hypothesis | Measurement | Result |
|---|---|---|---|
| H1 | A structural long bias in the code (an asymmetric threshold, or shorts gated off) | Read `decide()`: symmetric argmax, one tau. bybit_2 has no side filter. 17 of the 39 crypto packages since 11-16 are **short** | **KILLED** |
| H2 | Serve parity: the wrong artifact is loaded | Replayed the committed boosters (v1r20261106 / 1115 / 1122) on the **logged** features of all 61 packages. Max \|replay − logged\| p_long/p_short = **4.9e-6**. `meta.model_id` matches the pointer history (r20261122 from 11-24 00:00Z) | **KILLED** |
| H3 | An input data defect | Recomputed `btc_ret24` / `btc_vol24` at each of the 11 decision bars from Binance spot 1h (independent source). They agree within ~1% (e.g. 11-20 15:00 live −0.05931 / 0.00961 vs −0.05921 / 0.00956) | **KILLED** |
| H4 | Exit mechanics (structure tighten, live review) turn good entries into losers | Same 26 trades, untouched 2/3-ATR bracket with a 24 h stop on Binance 1h (ESTIMATED proxy, ~12 bps cost): **−16.94 R**, vs **−5.79 R** realized. Management **saved ~11 R** | **KILLED**: exits help |
| H5 | **Regime-blind market-wide contrarian rule**: the side is set by BTC vol, BTC 24h return and breadth, against the move; with no regime input it fires the same in a trend as in a range | SHAP `pred_contrib` on the logged rows, contribution to (p_long − p_short). **22 crypto longs: btc_vol24 +0.255, btc_ret24 +0.114**, breadth +0.032. **17 shorts: breadth −0.089, btc_ret24 −0.083**, ret_72 −0.069. **9 of the 10** decision bars with a non-zero BTC 24h move went *against* it; the one bar that went *with* it (11-20 11:00Z, short) won +2.9 R (proxy). Live btc_vol24 0.0096–0.0107 vs Oct–Nov p90 0.0073. Post-train grade windows: long side −0.53 … −0.90 R/decision in every window since 10-23, vs **+0.032** (n 3,500) in the c692-01 held-out year (2025-10..2026-09) | **SURVIVES** (driver) |
| H6 | The promotion read cannot see it | `comms/research/ml_entry_grade/45021344426/grade_evidence.json`: the promoted candidate's long n 220 **−0.526**, short n 214 **+0.836**, aggregate +0.146. The rule compares aggregates only. RQ-20261123-d3a1-01: the side gap tracks the regime (corr 0.89) | **SURVIVES** (process cause) |
| H7 | Correlated stacking amplifies it | 11 bars → 39 crypto decisions, **every bar single-signed** across symbols (11 of 11). Untouched-bracket outcomes by bar (37 decisions with a complete 24 h path): 2 up, 9 down. No correlation cap on the leg; `src/runtime/allocator_corr.py` is observe-only. bybit_2 `risk_pct` 0.015 × 4–5 = 6–7.5% per bar vs an armed 3% `daily_dd_switch` | **SURVIVES** (amplifier) |

Plainly: **the model does not prefer longs. It bets against the last 24 h of BTC**, and it bets hardest when BTC vol is high. Since 11-20 the tape has been a high-vol downtrend with sharp bounces. So the model bought each leg down (11-20 15–23Z, 11-23 23Z, 11-24 03/11Z) and sold the one bounce (11-22 07Z). Both sides lost. What looked like "going long into a short market" is a contrarian rule with no regime input.

### The 11-24 12:00Z bar (what the model saw)

At the 11:00 bar close, four packages reached bybit_2 (BTC, ETH, SOL, XRP); the fifth candidate, ADA, was refused before sizing (`leg_account_scope`). Shared inputs: `btc_ret24` −0.0163, `btc_vol24` 0.0105, `breadth_up24` 0.44. Per-symbol (L − S) was +0.31 to +0.33. Contributions, BTC row: btc_vol24 **+0.244**, btc_ret24 **+0.122**, ret_168 −0.044. The other three were within ±0.01 of that. So all four were one decision, made on two BTC numbers.

### Why prior fixes did not land

Already measured, and not repeated here: the HTF counter-trend filter (RQ-20261112-8d20-01 **FAIL**); a ret_168 side gate and a short-only gate (RQ-20261123-d3a1-01 **FAIL**, +0.012 t 0.83 and +0.009 t 0.46); the residual target, ridge, conformal and the decomposed target (lever map `research/levers/ml-entry.yaml`, all fail or indeterminate). A gate throws decisions away; the dev OOS edge is about +0.003 R/decision. Solution 1 is different: the regime goes in as an **input**, so the model can learn when its contrarian rule works.

## Part 2: equity ML (the blocking step)

Chain traced end to end on the live trader journal (complete scans):

1. **Refresher runs, snapshot fresh.** `ml_entry_eq_refresher bar_close=2026-11-23T20:00:00+00:00 covered=168/173 wrote=True took_s=43.2`.
2. **The pool is scored at every decision close.** **Every symbol is refused `below_tau`.** `ml_entry_eq_struct pool_scored bar=2026-11-23T20:00:00+00:00 scored=162 packages=0 refusals={'symbol_not_in_snapshot': 4, 'below_tau': 158}`. Same at 16:00Z. Best struct pred +0.086 vs tau **0.25**. `ml_entry_eq`: `scored=10 packages=0 refusals={'below_tau': 10}` at tau 0.20. `ml_entry` on alpaca_paper ETFs: `ml_entry_decision symbol=SPY bars=399 outcome=no_signal`.
3. Last packages: struct 2026-11-17 16:09Z, eq 2026-11-18 20:04Z. Journal retention reaches back only to ~11-23 13:24Z, so I could not read the 11-18..11-23 closes; the decided memos hold 12 closes.

**Blocking step: the model's own threshold.** This is in distribution, not a defect. The struct evidence record (RQ-20261107-98e3-06, n = 207, window 2025-07-15..2026-10-31) has **zero trades in 5 of 16 months** (2025-09, 2026-05, -06, -07, -10), and 75 of its 207 trades fall in one month.

**When it does fire, real money cannot place it.** On alpaca_live, 22 of the 23 `ml_entry_eq_struct` attempts in the window (11-16/17) were `risk_refused: sized_qty=0` (margin basis `venue_available`, below one whole share). The mirror's half of this, `mirror_primary_not_placed`, was fixed on 11-16 (`src/runtime/mirror_pairs.py::INDEPENDENT_MIRRORS`); on 11-17 the mirror filled IWF, IVW and TZA while live refused. Fix: solution 4 (FRACTIONAL-ETF-EXECUTION).

No tau change is proposed. Lowering a dev-selected tau because a week was quiet is a Tier-3 change with no evidence behind it.

## Observability gaps filed

- `ml_entry_decision ... outcome=no_signal` for alpaca_paper ETFs does not log the prediction, so ETF near-misses cannot be read from the journal. The crypto path logs `below_tau:pred=...` in the audit.
- Trader journal retention is about 1 day at current volume (lines since 11-17 began at 11-23 13:24Z), so any post-mortem longer than a day needs the DB, not journalctl.

## Provenance

Raw pulls in the lane scratchpad (not committed: they hold account-level fields). Reproduce with `scripts/ops/diag_fetch.sh 'journal?table=order_packages&limit=1000'` and `'journal?table=trades&limit=1000'`. SHAP: `lightgbm` `Booster.predict(pred_contrib=True)` on `meta.features` with the committed `ml/served/ml_decision_entry_v1r2026111{5,22}` / `…1106` boosters. Counterfactual: Binance spot 1h klines (`data-api.binance.vision`), entry at the decision-bar close, SL 2 / TP 3 × logged `atr14`, 24 bars, SL wins ties. It is labelled ESTIMATED: Binance spot is a proxy for Bybit perps, and cost is a 12 bps round-trip proxy.
