# ml_entry MOVING TP — PRE-REGISTRATION (`RQ-20261101-383f-01`, row `ML-ENTRY-TP-REVISION`)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `ML-ENTRY-TP-REVISION`

Gates this adds or changes: none. (The bar is the operator's own, popup 2026-11-01 "Point estimate >= 0"; the n floors mirror
DESIGN.md §1.7 and §4; nothing here adds a runtime switch, a flag, an approval step or a CI refusal.)

Registered 2026-11-01 **before any run and before any byte of the held-out window was fetched.** The machine-form rule lives
in the unit (`research/queue/RQ-20261101-383f-01.yaml`); this file is the method. Operator, 2026-11-01 ~09:05Z on PR #22079,
verbatim: *"1, but a moving to needs to be the be t work item"*.

## 1. Population and baseline (exactly as `ml_entry` trades)
- Trades of the FROZEN served ENTRY model `ml/served/ml_decision_entry_v1` (τ = 0.10), frozen 60-perp universe, c692-01
  mechanics: decision at the close of every 4th 1h bar, entry at the next bar's open, SL = 2 × ATR14, TP = 3 × ATR14 (1.5R),
  24-bar time stop at that bar's close, one open position per symbol. Labels, gaps and costs: DESIGN.md §1.3
  (`src/runtime/execution_costs.py` stack). **Baseline = this fixed TP held to the bracket.**

## 2. The policy (one, pre-registered)
- **Cadence:** a check-in at the close of every 4h decision bar while the position is open (4, 8, 12, 16, 20 bars held). A
  revision rests from the next bar. The SL is never touched; both brackets are always set.
- **Grid:** TP ∈ {1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0} × ATR14(entry) from entry. A candidate must sit ≥ 0.25 ATR beyond the
  check-in close (never through price) and within the 9.9% venue cap (`src/runtime/tp_venue_cap.py`) of it.
- **Model (first-passage, DESIGN.md §1b):** one pooled LightGBM multiclass over 18 classes = (highest grid level touched before
  the stop, 0..8) × (stop hit: yes / no — no = timeout at the 24-bar stop). Three outcomes per level follow:
  `target_first` = reach ≥ L, `stop_first` = stop and reach < L, `timeout` = no stop and reach < L. Features: the 20 ENTRY
  features at the check-in bar, plus side, bars held, open R, MFE / MAE so far (R), distance to the SL (ATR), ATR(now) /
  ATR(entry), side-signed 4h / 24h returns. *(Amended 2026-11-01 before any run: the resting TP and the distance to it are NOT
  features — the 18-class label is a property of the remaining price path and the fixed SL alone, so it is the same whatever TP
  rests; the TP enters only through the expected-net-R arithmetic below.)* Training check-ins are those where the SL has not been
  hit (TP-agnostic), so states beyond the 3 ATR level are covered. 200 trees, lr 0.05, 31 leaves, min leaf 500, subsample 0.8,
  colsample 0.8, λ 5, seed 20261101.
- **Expected net R of level L** = P(reach ≥ L) × (L/2 − cost of a TP fill at L) + Σ over classes with reach < L of P(class) ×
  that class's mean net R on the training rows. Move to argmax_L iff E(L*) − E(resting TP) > m.
- **Training rows:** check-ins of every candidate position (every decision bar, both sides) in the label table, deterministic
  random subsample (seed 20261101) to ≤ 1.5M rows; dev ties SL-first (counted), label ends purged + 7-day embargo before each fold.
- **m ∈ {0, 0.02, 0.05, 0.10}**, chosen on dev only: max pooled dev OOS mean Δ per trade (tie → larger m) over the ENTRY OOS
  trades 2022-01-01..2026-09-30 (the c692-01 walk-forward fold trades, re-run with its recipe, plus the served model's trades
  2025-10-01..2026-09-30), TP model walk-forward in yearly folds (2022, 2023, 2024, 2025-01..09, 2025-10..2026-09).

## 3. Held-out window and the one read (ML-BAR-ONE-READ, DESIGN.md §1c)
- **FORWARD: decisions 2026-10-01T00:00Z .. 2026-10-30T23:00Z** whose 24h ends inside October, from Binance Vision DAILY 1h
  klines (the 2026-10 monthly zip is not published yet: MEASURED HTTP 404, 2026-11-01). Read once by one final fit on all dev
  rows (purged + embargoed). The c692-01 held-out year has been read for ENTRY and is dev here, never scored as held-out.
- **Ties in the held-out are resolved from 1m** (Binance Vision daily 1m klines for exactly the tie symbol-days) for BOTH
  arms; a tie inside one minute is `still_ambiguous`, SL-first, counted.
- **Variants read on this window: 1.**

## 4. Rule (copied from the unit)
INDETERMINATE if held-out trades < 300 OR distinct symbols < 10 OR trades with ≥ 1 TP move < 30. **PASS iff held-out mean Δ net R
per trade (policy − fixed 3 ATR TP) ≥ 0, point estimate.** FAIL otherwise.

Reported, never gating: matched random TP moves (200 draws: same per-check-in move rate and pull-in / extend mix, random valid
level), the best static entry-time TP chosen on dev, trade-grouped bootstrap CI, Brier + 10-bin reliability per first-passage
class at the resting TP, Δ split by pull-in / extend, by side, policy and baseline means.

## 5. What a PASS / FAIL does
PASS → `ml_entry.monitor()` returns `{tp, tp_reason}` from this model through `src/runtime/tp_revision.py` (parity-tested
against the harness), the two `ml_entry` lines leave `scripts/ci/check_tp_doctrine.py`; a HELD Tier-3 PR. FAIL → the result
names the next lever, filed as a unit or row that the debt lines then point at.

## 6. RESULT (2026-11-01, the one read) — PASS under the registered rule, a thin one
Record: `research/results/RQ-20261101-383f-01/local-20261101T1030Z.jsonl` (summary + dev under
`comms/research/RQ-20261101-383f-01/local-20261101T1030Z/`). MEASURED, forward 2026-10 (868 ml_entry trades, 49 symbols):

| | mean net R / trade |
|---|---|
| fixed 3 ATR TP (baseline, as ml_entry trades) | −0.0193 |
| moving TP, margin 0.05 (dev-chosen) | −0.0112 |
| **Δ per trade (the rule)** | **+0.0081** (394 trades moved, 560 moves: 300 extend / 260 pull-in) |
| matched random TP moves, 200 draws | −0.0071 mean, p95 +0.0096 → policy at the 93rd percentile |
| best static TP chosen on dev | 3.0 ATR = the baseline (Δ 0) |

- **Reported, not gating, and they matter:** the trade-bootstrap CI of Δ is [−0.022, +0.039] (spans 0), and the policy does not clear
  the matched-random p95. The point estimate clears the operator's bar; the evidence that it beats random TP moves is weak.
- **Where the Δ comes from:** trades whose first move was an EXTEND: n = 296, +0.029; first move PULL-IN: n = 98, −0.017. Longs
  (n = 137) −0.024, shorts (n = 731) +0.014. Dev (72,906 trades with a check-in, 2022-01..2026-09) at m = 0.05: +0.0038.
- **Calibration at 3 ATR** (2,886 forward check-ins) beats climatology on every first-passage class (Brier: target_first 0.138 vs
  0.246, stop_first 0.126 vs 0.174, timeout 0.150 vs 0.224). Ties: 198 resolved from 1m, 6 `still_ambiguous` (SL).
- The October baseline itself is negative (−0.019 R/trade) — ENTRY's forward month, reported; this unit does not grade ENTRY.
- **Next lever** (filed as a unit, not a gate): the pull-in half loses on both dev and forward. An EXTEND-ONLY variant is a NEW variant
  and needs a fresh window (November 2026 forward) under ML-BAR-ONE-READ.
