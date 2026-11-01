# ML decision models — DESIGN and PRE-REGISTRATION (ENTRY · BRACKETS · MANAGE)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `ML-DECISION-MODELS` (row `docs/claude/work/checklist/ML-DECISION-MODELS.json`, roadmap `L-ML-LIVE`)

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

## 1c. One model, one read (operator, 2026-11-01 ~08:48Z, audit ML-BAR-ONE-READ)

Verbatim popup answer: *"Yes, one model, one read (Rec.)"*. The point-estimate ≥ 0 bar is unchanged; it applies to ONE
pre-registered model per question, the held-out window (2025-10-01..2026-09-30) is read ONCE, and the number of variants
tried is reported beside every result. **ENTRY variants read on that window so far: 1** (c692-01; c692-06 re-scores the
SAME frozen model on a subset of the same decisions, not a new variant). A second ENTRY variant — c692-04's arms, c692-05
(ENTRY v2) — needs a FRESH held-out window (forward data after 2026-09-30); their units must be re-pointed at it before
they run. Reported, not gating (audit §4/§5c): ENTRY is benched beside simple factor portfolios on the same universe,
window and costs (12-1 and vol-targeted time-series momentum, weekly cross-sectional momentum; funding carry if its harness
runs), next to the random and always-long baselines.

## 1b. The FIRST-PASSAGE label contract — every price prediction (operator, 2026-11-01 ~08:15Z, binding)

Verbatim: *"I think in general when MLs are making price predictions (which is great), we should try to add 1. Within what
timeframe 2. before/after crossing the other bracket. Just to help with labeling and verifying the MLs."* — and, on the
manager's proposal, *"yes, send it to the lane"*. Also (~08:00Z): *"improving our labeling is super important"*.

1. Every price prediction any of the three models makes is a first-passage prediction: P(target touched BEFORE the
   opposite bracket, WITHIN H bars), over **three labelled outcomes**: `target_first`, `stop_first`, `timeout` (neither by
   H — its own class, never dropped).
2. **H and the bar timeframe are declared per model and stored on every label and prediction row.** ENTRY: timeframe 1h,
   H = 24, check cadence 4h. BRACKETS: 1h, H = 24 (per cell). MANAGE: 1h, H = the remaining bars of the entry's H, check-in 4h.
3. **Same-bar double touches are resolved from 1m data** (Binance Vision daily 1m klines for exactly the tie bars); a tie
   the 1m bar cannot split (both inside one minute) is `still_ambiguous`, kept SL-first by convention and COUNTED in the
   label manifest (`tie_resolution` ∈ {`no_tie`, `1m`, `still_ambiguous`}). MEASURED on the c692-01 table: 3.5% of side-
   labels (56,548 of 1,615,860) end on a double-touch bar, 5,111 symbol-days.
4. **Every label carries its realized net R** net of the full cost stack (§1.3) — a target-first path can still lose after cost.
5. **Evaluation reports calibration per outcome class** (Brier score and a 10-bin reliability table per class) on the
   held-out window beside the net-R rule. Calibration is reported, never a gate (§ "No new gates").
6. BRACKETS' SL / TP and MANAGE's hold / adjust / close are scored on the same first-passage labels.
7. Owner: `scripts/research/decision_labels.py` (the decision-model label store: label build + 1m tie resolution +
   manifest); checklist row `DATA-LABEL-TIES` (re-opened 2026-11-01).

**What c692-01 did and did not do.** It was registered and run before this contract: its labels are the same first-passage
walk with ties SL-first (the conservative side: resolving a tie TP-first can only raise R), its model regressed net R, and it
reported no calibration. Its PASS stands under its own rule. `RQ-20261101-c692-05` (ENTRY v2) re-runs ENTRY under this
contract: 1m-resolved labels, a 3-class first-passage classifier per side whose expected net R
(Σ P(class) × the class's mean net R on the training rows) drives the same τ policy, per-class calibration reported, and the
same registered bar.

## 1a. TRAINING UNIVERSE is a researched factor, not an assumption (operator, 2026-11-01 ~07:50Z)

Verbatim: *"The MLs don't only need to train on the data of the symbols that we're trading. Like, for training purposes, we
need to, like, research this before we just do things, but, like, we can train them on all sorts of data, even if it's not
things that we're planning on trading immediately, if it will improve their decision-making for the things that they are
trading."*

- **Evaluation population = what we trade.** The symbols `bybit_2` / `bybit_portfolio` pull today (MEASURED from
  `config/accounts.yaml` 2026-11-01: BTCUSDT, ETHUSDT, XRPUSDT, ADAUSDT, SOLUSDT; re-parsed at run time, never quoted).
  The ENTRY unit c692-01 (registered before this directive) pools its held-out over all 60 perps of the frozen universe —
  every one a USDT perp, i.e. "can trade on bybit_2" in kind; its rule is not edited. Its harness ALSO reports the
  held-out restricted to the five traded symbols (reported, not gating).
- **Training set = the variable**, unit `RQ-20261101-c692-04`: the same ENTRY recipe trained on (a) the traded symbols
  only, (b) the frozen 60-perp universe, (c) wider — every Binance Vision USDT-M perp passing the same listing-age rule
  with no cap of 60 (310 qualified on 2026-10-30, MEASURED by ML-DATA-BROAD-PATHS). Each arm is scored on the SAME
  held-out window restricted to the traded symbols, same mechanics, same cost stack, same rule. Cross-sectional
  features are computed against the frozen-60 reference set in every arm, so the traded rows' inputs are identical
  across arms and only the training rows differ. Point-in-time and purge / embargo rules apply to every added series.
- **Data inventory (what exists now):** public Binance Vision USDT-M 1h klines for every listed perp (keyless, used by
  arms a–c); the trainer's `market_raw` / `market_features` shards: BTC / ETH / SOL 15m + 1h (Bybit V5, a subset of the
  60) and MES / ETF bars from yfinance / IBKR (third-party licence, trainer-resident, daily depth; yfinance 1h history
  is capped near 730 days); FX: only a Dukascopy span probe (`scripts/research/dukascopy_span_probe.py`), no store.
  So **other asset classes at 1h over 2020–2026 do not exist in any store today** — that arm (d) is filed as data row
  `ML-DATA-XASSET-1H` rather than waited on.

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
