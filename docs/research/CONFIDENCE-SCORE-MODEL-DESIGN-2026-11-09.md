# Confidence-score model: design v1 (research tooling only, no training run)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · lane ML-ENTRY-EQ-STRUCTURE-RETEST
> Gates this adds or changes: none. This is a design. It registers nothing, trains nothing and changes no config; every rule below that says "registered" is registered in the unit that runs it, before that run.
> Source: row `CONFIDENCE-SCORE-EVERY-TRADE` (live work store; plan v1 and the operator addenda of 2026-11-09 ~11:20Z, ~12:30Z, ~12:33Z). Owner after the 2026-11-11 reset: the one ML lane.

## 1. What is being built

1. **A separate confidence-scoring model**, independent of the entry models. It scores ANY strategy's order package at entry and **re-scores each open trade at every live review**. The entry model's own probability (e.g. `ml_entry`) is recorded beside it, never instead of it.
2. **One append-only score log for EVERY scorer** (operator correction 12:33Z): every ML head (entry, confidence, shadow/advisory, regime, setup-quality, execution-quality, exit), every LTR review's judgement confidence and forecast (`p_target`, direction, horizon), every desk review score, joined to the realized outcome.
3. **A weekly CONFIDENCE section** in `/performance-review` that grades all scorers: calibration (reliability by decile, Brier), discrimination (AUC), score vs realized R per strategy and book, entry score vs later re-scores, and whether acting on the score would have helped net of cost.

## 2. Why the live trades show no score today (measured by the manager, 11:15Z, 200 most recent packages)

- `conviction-meta-v1` and `setup-quality-lgbm-v2` last scored a package on 2026-09-28; both were demoted shadow to candidate on 2026-09-29 (JC-SA-02) because the live scorer served 3/10 and 5/9 of their declared features (**train/serve skew**). The fix items PI-20260929-K85Q64SF-0001..0004 sat queued since.
- The package `confidence` field is a constant 1.0 on 61 of 200 packages (a strategy default, not a model output); the UI must render it as "—".
- `ml_entry` packages carry no `modelScores`; `/api/bot/positions` carries no strategy and no scores.

The design below is built so that this failure cannot recur: **a declared feature that is not served fails CI**.

## 3. Design

### 3.1 Sample unit and label

| | entry sample | re-score sample |
|---|---|---|
| unit | (order package, entry time) | (trade, decision time) for each review or bar checkpoint |
| state features | package context + market state at entry | the same, plus open R, peak R, give-back, bars held, distance to SL and TP in ATR, regime now |
| label (net of the full cost stack) | won / R multiple of the trade | measured FROM that checkpoint: P(TP before SL) and remaining net R |

Every checkpoint of one trade is one group. **Splits are walk-forward and GROUPED BY TRADE**: no trade has checkpoints in both train and test.

### 3.2 Inputs (each must be servable at entry or review time from the live path)

- Package context: strategy id, direction, R:R, stop distance in ATR, session/time.
- Market state: volatility regime, trend/ADX; funding/basis/OI where the symbol has them; book depth from `scripts/research/book_depth_pit.py` for ETH and SOL (2023-01 onward, coverage >= 0.99 at 4 h, builder unit RQ-20261109-98e3-36).
- The entry model's own score when one exists; account/book context.
- Anything not servable live is out. No input is added because a backtest can compute it.

### 3.3 Parity first (the JC-SA-02 lesson)

- **One feature builder** shared by training and the live scorer (a single module, imported by both).
- A **CI parity test** that (a) enumerates the model's declared features from its manifest, (b) builds a row through the live path, and (c) FAILS if any declared feature is missing, NaN by construction, or differs from the training builder on a pinned fixture. Nothing is shadowed or promoted without it.

### 3.4 Data

- **Label corpus**: every closed trade across books (state n per book; the live corpus is hundreds, not thousands), plus walk-forward replayed trades from the backtest corpus (committed evidence records only; the fee-only harnesses `scripts/backtest_orb.py` and `src/backtest/backtester.py` stay out) to get past the live label count.
- **State n per book and per strategy before any model is fitted**; a book with too few labels is scored by the pooled model and reported as such, never fitted alone.
- Replayed trades are flagged as replayed in the corpus and every metric is reported live-only and pooled.

### 3.5 Validation (registered before the first run, in the unit that runs it)

1. Walk-forward, grouped by trade, train only on trades closed before each scored trade's entry.
2. Calibration by decile (reliability, Brier), discrimination (AUC), both with block-bootstrap intervals; population stated each time.
3. **The money test**, registered before the run: does filtering or sizing by the score improve net P&L on held-out trades versus no filter, net of cost, with the matched-random-filter control (the same share of trades dropped at random, 2,000 draws).
4. Promotion shadow to advisory only on that registered test. A mandate is not a gate; nothing here adds one.

### 3.6 Live behaviour

- **Shadow-score every new package from day one**; the score and its change since entry travel in the LTR packet and the reviewer records it (operator addendum C).
- No score is shown as an ML confidence unless a model produced it; a missing score renders "—", never 0.

### 3.7 The score log (operator addenda A and correction)

One append-only store, read by the performance review. One row per score:

`scorer` (model id + version, or review_id + session) · `kind` (entry / confidence / re-score / head / ltr / desk) · `subject` (order package id, trade id, review_id) · `scored_at` (UTC) · `score` and `meaning` (what the number is: a probability of what, a forecast of what) · `inputs_hash` · `horizon` where it has one · later joined: `outcome` (realized net R, closed_at).

Existing partial stores to fold in, not duplicate: `order_packages.modelScores`, the trainer shadow log, `comms/live_review/reviews.jsonl` (+ the forecast-grade first-passage grades), desk decisions, `comms/claude_strategy_scores.jsonl`. A write path to the new store is a Tier-2 change (it touches the order path); this document does not make it.

### 3.8 Backfill (operator item D)

Walk-forward scores for every historical trade AND every historical checkpoint, stored with the trade, compared to its outcome. Reported with the n and the live-only/replayed split. No in-sample scores, ever.

## 4. Work breakdown (each item becomes a queue unit or a checklist row when authored; none is dispatched by this document)

| # | item | kind | tier | needs |
|---|---|---|---|---|
| 1 | **Data audit**: closed trades per book and per strategy, labels per checkpoint type, share served-at-entry per candidate input, `confidence`-field audit | research unit (deterministic, VM data read via diag relay) | 1 | read access to `trade_journal.db`; no training |
| 2 | **Shared feature builder + CI parity test** | build row | 2 (order path) | item 1; manager approval for the live-path import |
| 3 | **Score-log store + writers** (all scorers) | build row | 2 | item 2 not required; schema above |
| 4 | **Replay corpus** from committed evidence records, flagged | research unit | 1 | item 1 |
| 5 | **Walk-forward model unit** with the money test registered first | research unit | 1 | items 1, 2, 4 |
| 6 | **Backfill** (entry + checkpoints) | research unit | 1 | item 5 |
| 7 | **CONFIDENCE section** in `/performance-review` | skill edit | 1 | item 3 |
| 8 | **Shadow scoring live + trade-card display** | runtime + UI | 2 | items 2, 3, 5 |

## 5. Open questions (for the manager; none blocks item 1)

1. Item 1 needs the journal: it reads live trade rows. Confirm the diag relay route to use (a read-only `/api/diag` query or a `system-actions` read) rather than the lane copying the DB.
2. The per-checkpoint re-score label needs the path of each trade (open R and peak R through time). Does `trade_journal.db` keep it, or must it be reconstructed from fills and bars? Item 1 answers this by measurement.
3. Where does the score log live (VM SQLite next to the journal, or committed JSONL)? Recommendation: the journal DB (one source of truth, `db-wiring`), exported read-only for the review. Tier-2, so this is a proposal.

## 6. Honest limits

- The live label corpus is small; every number is reported with its n, and a pooled or replayed estimate is never presented as live evidence.
- A calibrated score is not a profitable filter: the money test decides, not calibration.
- Book-depth inputs exist only for ETH and SOL and only from 2023-01; any strategy or symbol without them is scored without them and flagged.
