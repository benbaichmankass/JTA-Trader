# ML decision models — DESIGN and PRE-REGISTRATION (ENTRY · BRACKETS · MANAGE)

> **Doc status:** `live` · category `spec` · last verified `2026-11-01` · lane `ML-DECISION-MODELS` · roadmap `L-ML-LIVE`

Gates this adds or changes: none. (The live bar below is the operator's own, popup 2026-11-01 "Point estimate >= 0";
the n floor is the evidence floor the dispatch asked this lane to justify, §1.4; neither adds a runtime switch, a flag,
an approval step or a CI refusal.)

**Goal (operator, 2026-11-01, verbatim in the row note):** three market-context ML DECISION models, live on real money as
soon as possible — (1) ENTRY: at a bar, long / short / nothing over a designated horizon; (2) BRACKETS: SL and TP at
entry; (3) MANAGE: at each check-in on an open position, hold / adjust a bracket / close. One model per question,
pooled across symbols, not tied to any strategy, not grading a strategy's decisions. **No position sizing** — the
RiskManager owns it; every model here outputs a side, a stop / target, or an in-trade action, never a size.
Why this shape: [DIAGNOSIS.md](DIAGNOSIS.md) — 0 of 175 graded ML units used market-bar labels scored in net R pooled
across symbols.

## 1. Shared design (all three models)

1. **Universe.** The frozen 60-perp universe of manifest `comms/research/broad_paths/bp2-f4271084b120/manifest.json`
   (`hash_inputs.symbols`, chosen by listing age only). Bars: Binance Vision USDT-M **1h** monthly klines,
   2020-07-01 .. 2026-09-30 (the manifest's window), public and regenerable.
2. **Point-in-time.** A decision at bar *t* reads only bars ≤ *t* (its close is the last input). Entry is at bar *t+1*'s
   OPEN. Every feature is a trailing window; cross-sectional features use other symbols' bars at the same timestamp
   (≤ *t*). No symbol id is a feature: the representation is symbol-agnostic (vol-normalised returns, ATR / price,
   range position, volume z, the symbol's cross-sectional return rank, BTC context, universe breadth), so one model
   serves any symbol.
3. **Labels from market data, full cost stack.** First passage over the bracket on bar high / low; a bar touching both
   SL and TP resolves as **SL**; a bar opening through the stop fills at its **open**; a TP fills at the TP price (no
   favourable gap credit); a time stop exits at the horizon bar's close. R = side × (exit − entry) / SL distance. Net R
   subtracts `src/runtime/execution_costs.py`'s stack (identity-tested against `roundtrip_cost_r` in the harness
   self-test): fee **11.0 bps** round trip (the measured `bybit:linear` fee, applied to every symbol, conservative for the
   7.5-bps-default symbols), slippage **3.0 bps** (`resolve_cost_policy`, perp), funding **1.0 bps per 8h window
   crossed** (the canonical directionless drag). Never `scripts/backtest_orb.py` / `src/backtest/backtester.py`.
4. **Evaluation.** Development window 2020-07-01 .. 2025-09-30: expanding walk-forward, 8 half-year test folds from
   2022-01-01, each fold's training rows end `HORIZON + 1 h + 7 days` (purge + embargo) before its test start, and each
   fold's test rows end `HORIZON + 1 h` before the next fold (no label reads past its fold). **Held-out window
   2025-10-01 .. 2026-09-30 is sealed**: no dev fit, no threshold choice and no feature choice reads it; it is scored
   ONCE by one final fit on all dev rows (purged + embargoed from it).
5. **Mechanics as live.** One open position per symbol at a time (a symbol is busy until its exit bar), decisions every
   4 h. Decisions are counted only when taken; "nothing" is never counted as a 0-R decision (that would let a model
   pass by abstaining).
6. **Baselines (reported, under identical mechanics).** No-trade (0 R); always-long; always-short (reported); random at
   the model's take rate and long/short mix (200 draws; the model's percentile reported).
7. **The bar (operator).** **PASS iff held-out mean net R per decision ≥ 0, net of the full cost stack, point estimate**,
   registered before the run. **n floor: ≥ 300 held-out decisions on ≥ 10 distinct symbols**, else INDETERMINATE. Why
   300: per-decision net R under a 2-ATR stop / 3-ATR target is bounded near [−1.1, +1.4] with sd ≈ 1 R, so the
   standard error at n = 300 is ≈ 0.06 R — small enough that a ≥ 0 point estimate is not a handful-of-trades artefact,
   and well under the held-out capacity (60 symbols × 365 days with ~1-day holds ≈ 20,000 free slots). Why 10 symbols:
   the claim is a pooled model; a pass carried by 1–3 symbols is a per-symbol result. The bootstrap CI and the
   ex-max-symbol mean are REPORTED, never gating (the operator chose the point estimate).
8. **What a PASS licenses.** The Tier-3 promotion PR of deliverable D (a new strategy adapter emitting the model's
   decisions as order packages through the existing order path and RiskManager on `bybit_2` + `bybit_portfolio`,
   RiskManager default risk), held for the manager. A FAIL closes the configuration (this horizon, bracket, feature
   block, learner), never the family; §5 names the next lever.

## 2. ENTRY — `RQ-20261101-c692-01` (built: `scripts/research/ml_decision_entry.py`)

- **Decision set:** {LONG, SHORT, NOTHING} at the close of every 4th 1h bar (00, 04, … 20 UTC).
- **Horizon:** 24 h (24 bars) time stop.
- **Reference bracket (until BRACKETS exists):** SL = 2.0 × ATR14(1h), TP = 3.0 × ATR14(1h), both fixed at entry. A
  scoring bracket, not a claim about the right bracket; BRACKETS replaces it.
- **Label:** `net_long`, `net_short` = the net R of each side under the reference bracket (§1.3).
- **Model:** two LightGBM regressors (net R long, net R short), fixed hyper-parameters (300 trees, lr 0.03, 31 leaves,
  min leaf 500, subsample 0.8, colsample 0.8, λ 5, seed 20261101). Features: `FEATURES` in the harness (20 columns).
- **Policy:** take the side with the larger prediction iff it exceeds τ. τ ∈ {0, 0.05, 0.10, 0.15, 0.20, 0.30}, chosen
  on the pooled dev OOS mean net R per decision among τ with dev n ≥ 1,000 (tie → larger τ). Nothing else is tuned.
- **Rule (machine form):** `INDETERMINATE if no tau reaches dev n>=1000 OR heldout.n<300 OR heldout.n_symbols<10;
  PASS if heldout.mean_net_r_per_decision >= 0; FAIL otherwise.`

## 3. BRACKETS — `RQ-20261101-c692-02` (blocked: harness subcommand to build)

- **Decision set:** at an ENTRY decision (side given), one (SL, TP) cell from SL ∈ {1.0, 1.5, 2.0, 3.0} × ATR14 and
  TP ∈ {1.0, 1.5, 2.0, 3.0, 4.0, 6.0} × ATR14 (24 cells), 24 h time stop. Net R per unit of the CHOSEN stop is
  comparable across cells because the RiskManager sizes to the stop distance (sizing stays the RiskManager's).
- **Label:** net R of each cell for the given side, same first-passage / tie / gap / cost rules.
- **Model:** one LightGBM regressor on (features, side, cell SL, cell TP) → net R, argmax over cells; pooled.
- **Scored composed:** the frozen ENTRY model + τ of c692-01 picks the side and the bar; BRACKETS picks the cell.
- **Rule:** `INDETERMINATE if heldout.n<300 OR n_symbols<10; PASS if composed heldout.mean_net_r_per_decision >= 0;
  FAIL otherwise.` Reported: Δ vs the reference 2/3 bracket on the same decisions, the best single static cell chosen
  on dev only, and a random cell (200 draws).

## 4. MANAGE — `RQ-20261101-c692-03` (blocked: harness subcommand to build)

- **Check-in cadence:** every 4 h while a position is open (the ENTRY decision cadence).
- **Decision set:** {HOLD, CLOSE now (next bar open), SL → breakeven, SL → trail 1 ATR behind the 4-h extreme, TP → +1
  ATR}. HOLD = hold-to-bracket.
- **Label:** for each check-in, the trade's final net R under each action minus under HOLD (same bars, same cost
  stack; a CLOSE pays the cost at the close bar).
- **Model:** one LightGBM regressor on (market features at the check-in, open R, bars held, distance to SL / TP in
  ATR, side) per action → Δ net R; act iff the best Δ exceeds a margin chosen on dev only; pooled.
- **Scored against hold-to-bracket** on the composed ENTRY (+ BRACKETS if passed) held-out trades. Controls:
  hold-to-bracket, matched random (same count and type of actions at random check-ins, 200 draws), best static rule
  (grid excludes held-out), bootstrap grouped by trade.
- **Rule:** `INDETERMINATE if heldout trades<300 OR n_symbols<10; PASS if heldout mean net R per trade (managed) >= 0
  AND mean Δ net R per non-HOLD action >= 0; FAIL otherwise.`

## 5. If none passes — the levers, in order

(1) horizon (4 h / 72 h) and decision cadence; (2) the label's bracket (BRACKETS composed); (3) the feature block
(funding rate, open interest, order-book imbalance — not in Binance Vision 1h klines); (4) a classification target
(P(TP before SL)) instead of the regression. Each is a new registered unit; a FAIL never edits this file's rules.

## 6. What this does not do
Registers, serves and promotes nothing; edits no config and no order path; no sizing anywhere. The held-out window is
one year of one regime history; a PASS is the operator's live bar, not proof of edge, and the mirror's net-of-cost
window remains the demotion signal (operator path, popup 2026-11-01 "Straight to real money").
