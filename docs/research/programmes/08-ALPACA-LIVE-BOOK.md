# Programme 08 — The alpaca_live book: find something that earns more on the account we actually have

> **Doc status:** `live` · category `evidence` · last verified `2026-11-11` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `ALPACA-LIVE-BOOK-PLAN` (Manager Session 2026-11-11a, `session_01AFoLuLyarNRcy3nziCep2U`) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) · roadmap **`L-ML-LIVE`**, **`L-LADDER`** (G1) · track TRADING

Machine tree: [`research/programmes/08-alpaca-live-book.yaml`](../../../research/programmes/08-alpaca-live-book.yaml). Units: `RQ-20261111-207f-01..04` (runnable on merge). Instrument (this lane): [`scripts/research/alpaca_live_book.py`](../../../scripts/research/alpaca_live_book.py). Iteration subject: `ml-entry-eq-struct` ([`scripts/research/iteration_subjects.yaml`](../../../scripts/research/iteration_subjects.yaml), lever map [`research/levers/ml-entry-eq-struct.yaml`](../../../research/levers/ml-entry-eq-struct.yaml)). Every number below is marked MEASURED (with where it was read, this session, 2026-11-11), RELAYED (from the manager's dispatch, not re-verified here) or INFERRED.

**Gates this adds or changes: none.** Nothing here changes what trades. Foxhound-4 stays live until a challenger clears § 5.

## 0. The ask

Operator, 2026-11-11 ~22:40Z, verbatim: *"what's the research and iteration plan for that Alpaca Live strategy so that we can try and get something that's going to work better on that account? Like, it's good that we have this live, and we should keep it that way until we find something better, but we need to make sure we have a plan for finding something better."*

## 1. End goal and measure

**Goal:** the alpaca_live book earns more per month, net of the full cost stack, than it does with Foxhound-4 alone, measured on the book the account can actually hold.

**Measure (the one every P8 test reports):** net return per month on the alpaca_live cash book, in % of the $194.52 starting balance, with its month-clustered t. This is the roadmap's G1 measure (net P&L per capital-day on the real-money books) at monthly grain. A candidate is replayed by `alpaca_live_book.py` through:
- $194.52 cash;
- long only;
- whole-share brackets;
- the live sizer;
- one position at a time;
- T+1 settlement;
- picks in live order, highest predicted net R first.

Net R per trade is reported beside the monthly return, but it is never the decision number on its own: a book that holds one position cannot spend a high per-trade mean that it cannot afford or reach.

## 2. What is known (do not re-derive)

**The account** (MEASURED from `/api/diag/broker_account_status` at 2026-11-11T22:44Z, and from `config/accounts.yaml`):
- The balance is $194.52. Cash, equity and buying power are all 194.52, and the multiplier is 1: it is a cash account, and it is flat.
- `shorting_enabled: false` at the venue, and `side_filter: long` in config.
- Roster: `[tqqq_trend_long_1d, ml_entry_eq_struct]`.
- `risk_pct 0.02`, and `daily_dd_switch` is armed at 3%.
- The live sizer (`src/units/accounts/risk.py`) floors the risk-based quantity. It rounds up to one share when that share's risk is ≤ 1.5× the budget, then caps the position at 0.9× cash. The account's own comments record that the cash wall, not `risk_pct`, decides size.
- T+1 settlement is armed (`ALPACA_CASH_SETTLEMENT_MODE=apply`), so the whole balance recycles on every trade.
- `strategy_status.py`: `ml_entry_eq_struct` is production on alpaca_live and alpaca_portfolio. `tqqq_trend_long_1d` is production on alpaca_live and alpaca_portfolio, and is also listed on alpaca_paper. It sits on alpaca_live as a **mechanics-only exception** (operator popup 2026-11-06, "Probe with tqqq_trend_long (Recommended)"; `accounts.yaml` comment; `check_strategy_status.py` `DUAL_BOOK_EXCEPTIONS`), not as an edge bet. So Foxhound-4 is the only leg there on edge evidence.
- Options approval is UNVERIFIED: the diag read does not expose it.

**Foxhound-4's evidence** (MEASURED from `comms/strategy_evidence/ml_entry_eq_struct.json` and the 98e3 result rows):
- Confirm read RQ-20261107-98e3-06 PASS: +0.492 R per trade, n 207, 113 symbols, 2025-07-15..2026-10-31. It was the third read of that window.
- The month-clustered se is 0.239, so t ≈ 2.06. 75 of the 207 trades fall in 2026-03, and three months carry 141.
- On the dev walk-forward at tau 0.25 it took 1,691 trades in about 30 months (2023-01..2025-06), mean +0.132 R. Folds 2 and 3 were negative (−0.113, −0.271).
- **Confirm-to-dev, the trade rate fell about 4.2× (~56 → ~13 a month) while the mean rose about 3.7×.**
- The harness takes **one position per symbol with no cash limit** (`ml_entry_alpaca_score.take`, code read). The record itself lists "live whole-share cash-book sizing on alpaca_live is not modelled".

**Relayed by the manager, not re-verified here:**
- Since the 2026-11-11 widening the leg covers the full 171-ETF pool.
- It has never produced a package; today's max score is +0.016 against tau 0.25.
- The DSR probation tool prints nothing for this leg.
- Live-parity coverage for the ML legs is missing (ML-LIVE-PARITY-ML-LEGS).
- Equity entries land 15.6 minutes late (ML-EQ-ENTRY-TIMING; the fix is approved).

**The label question is open for this leg.** PR #24996 measured the cost-per-R effect on the CRYPTO decision-entry family: `atr_pct` IC +0.49 against `net_long` and −0.08 against the raw return. Its body states that M2 for the equity ENTRY-EQ pool is not in that increment, so for Foxhound-4 the effect is a hypothesis. 207f-03 measures it.

**Tried on this family** (lever map; per trade, dev):
- Tau grid (98e3-03, single seed): 0.20 → +0.083, 0.25 → +0.109, 0.30 → +0.197, 0.40 → +0.204. Fold 3 is negative at every tau.
- Seed ensemble (98e3-04/05): the 5-seed mean reads +0.092 at tau 0.20, against a seed range of 0.047. At tau 0.30 the seed range is 0.152.
- Features A vs B (98e3-14): flat, indeterminate.
- Structure-exit pivot 8 vs 5 (98e3-16): +0.109 vs +0.132.
- Pivot 3 (98e3-15) is queued after a producer failure.
- The forward read (98e3-13) is not before 2027-04-01.

**The challengers already on the books** (MEASURED from `comms/strategy_evidence/<leg>.json`; Stage-0, R per trade, full cost stack with 5 bps PROVISIONAL slippage; none measured on the cash book):

| leg | verdict | n | net R/trade | book today |
|---|---|---|---|---|
| tqqq_trend_long_1d | pass | 120 | +0.206 | alpaca_live (production) |
| slv_trend_1h | pass | 68 | +0.782 | alpaca_paper |
| qqq_pullback_1h | pass | 55 | +0.197 | — (enabled, not on alpaca_paper's roster) |
| tlt_pullback_1d | pass | 134 | +0.095 | alpaca_paper |
| scha_trend_long_1d | pass | 78 | +0.060 | alpaca_paper |
| gld_pullback_1h | pass | 90 | +0.365 | inactive (disabled) |
| tlt_pullback_1h | **fail** | 94 | −0.071 | — |
| spy/qqq/iwm/qld trend_long_1d, gdx/ief/slv/iaum/gld pullback_1d | pass | 6–11 each | +0.12..+1.33 | alpaca_paper / ib_paper |

The 1d legs with n ≤ 11 cannot qualify at power on their own. `uso_trend_1h` stays excluded on the operator's standing non-financial constraint.

## 3. Questions, in dependency order

```
Q1 does the edge survive the account ──┬──▶ baseline for everything below ──▶ Q4 challengers ──▶ head-to-head (§5) ──▶ Tier-3 packet
Q2 calibration / selection rule ───────┤                                   └─▶ Q7 rotation (a family built for one slot)
Q3 the label (cost-per-R?) ────────────┴──▶ Q5 features · Q6 pool · Q8 horizon          Q9 options (scoping)   Q10 forward read
```

| Q | question | why now | unit / node |
|---|---|---|---|
| **Q1** | Does Foxhound-4's dev edge survive the $194.52 cash book (cash wall, whole shares, one slot, T+1, live sizer)? What does the book earn per month? | Every number behind the leg is per trade with no cash. "Better" must be measured on what the account can hold. | `RQ-20261111-207f-01` → `P8-Q1-fail` |
| **Q2** | Is tau 0.25 calibrated to the score distribution, and does a registered selection rule (tau 0.15/0.20/0.30, top-1/top-3 per close, causal adaptive tau) earn more per month on the book? | The live max score sits 15× below tau, and the trade rate fell 4× from dev to confirm: a fixed threshold on a drifting score trades in clusters. | `RQ-20261111-207f-02` → `P8-Q2-pass` |
| **Q3** | Does the net-R label rank by cost per R on the equity pool, and does a direction-only label (gross R, raw return) select better at the same count? | The crypto sibling's label was measured doing this (PR #24996); it is unmeasured here. If true, no tau fixes it. | `RQ-20261111-207f-03` → `P8-Q3-pass` / `-fail` |
| **Q4** | Which rostered equity legs earn on the alpaca_live book, one at a time and competing for the slot? | Challengers must be scored on the same book, not on R per trade. | `RQ-20261111-207f-04` → `P8-Q4-h2h` |
| **Q5** | Which feature families lift the equity ENTRY on the label Q3 leaves standing? | Config A vs B was flat; volatility-regime, family-relative and event features are untested. | `P8-Q5-features` |
| **Q6** | Do per-family models (equity-beta, rates-credit, commodity, leveraged-inverse) or an affordable-only pool beat the pooled model on the book? | One pool mixes very different instruments, and the account can only buy the cheaper ones. | `P8-Q6-pool` |
| **Q7** | Does an ETF rotation / dual-momentum family, built for one slot and monthly turnover, earn on this book? | It holds one affordable position, trades monthly (T+1 is irrelevant) and is well documented outside the repo. | `P8-Q7-rotation` (ready; needs a harness) |
| **Q8** | Does a longer hold (48/72 bars) or a daily decision bar beat the 24-bar 1h design on the book? | Fewer, longer trades suit a T+1 cash book; only pivot variants have been tried. | `P8-Q8-horizon` (after `98e3-15`) |
| **Q9** | Can alpaca_live trade options, and does any defined-risk structure fit $194.52? | The dispatch asked; approval is unverified and the options executor has build gaps. | `P8-Q9-options` (scoping) |
| **Q10** | Does the frozen ensemble earn on bars after 2026-10-31? | The only fully out-of-time check; it stays as registered. | `RQ-20261108-98e3-13` (carried; not before 2027-04-01) |

## 4. The diagnosis, as competing hypotheses (each has its test)

The fact to explain: no package since the widening, and a 4× lower trade rate in the confirm window than in dev, at a higher mean.
- **(a) Noise / regime.** One window, t ≈ 2.06 clustered, and three months carry 141 of 207 trades. A quiet November is then expected and is no evidence either way. *Test:* 207f-02's report-only share of dev days whose max score ≤ 0.25. If that share is ≥ 0.5, silent weeks are the model's normal behaviour.
- **(b) Score-level drift.** The regressed score's level moves with volatility, so a fixed tau switches the model on and off. *Test:* 207f-02, where rank and adaptive rules are invariant to the score level.
- **(c) The label reads cost per R.** The model buys the highest-ATR ETF because its stop is cheap in R. *Test:* 207f-03's IC decomposition and the direction-only labels.
- **(d) The account cannot realise the edge.** The cash wall makes most of the pool unaffordable; one slot and T+1 cut the trade count; picks are ordered by score, not by affordability. *Test:* 207f-01's refusal mix and arms.
- **(e) Execution drag.** The 15.6-minute late entry (RELAYED) costs part of a 1h edge. *Owner:* ML-EQ-ENTRY-TIMING (fix approved). P8 does not re-test it, and a parity read stays with ML-LIVE-PARITY-ML-LEGS.

INFERRED, to be measured by 207f-01: at $194.52 the 0.9 cash wall leaves about $175 per position, so ETFs priced above that cannot be bought at all.

## 5. The promotion rule — what a challenger must beat to REPLACE or JOIN Foxhound-4

Foxhound-4 stays live until something clears all of this. The rule adds no gate: it is the existing ladder (Stage 0, then Gate 1/2, OPERATING-PLAN § 2), with the comparison population made explicit.

1. **Its own Stage-0 record passes.** That means a committed evidence record, a named harness, a stated n, net of the full cost stack, and a rule registered before the run. A fee-only corpus never counts (`backtest_orb.py` and `src/backtest/backtester.py` stay out).
2. **It wins the head-to-head on the alpaca_live book** (`P8-Q4-h2h` form):
   - the same replay (`alpaca_live_book.py`), on the common window of both trade lists, paired by month;
   - mean monthly return difference ≥ **+0.25% of the book per month**;
   - paired t ≥ `holdout_lock.bar_for(N)["point_t_min"]`, where N = challengers compared in that unit + 1;
   - n_taken ≥ 30 for both books;
   - max drawdown no worse than 1.5× the incumbent's.

   The baseline is Foxhound-4 as configured (tau 0.25, net-R label), replayed through the same book. If the common window overlaps 2025-07-15..2026-10-31, the read is claimed in the holdout ledger (family ENTRY-EQ, N=4 and up) and graded on the deflated bar (PLANNING § 1d).
3. **It is confirmed once on data not used to select it.** For a Foxhound-4 lever this is the N=4 read above, then bars after 2026-10-31. For a rule-based leg it is a window after its Stage-0 window.
4. **REPLACE vs JOIN.** The account holds one position, so joining means sharing the slot. A challenger JOINS only if the combined book (both legs, with a slot-priority rule fixed before the run) beats Foxhound-4 alone by the test in 2. It REPLACES only if it alone beats the incumbent by that test **and** beats the combined book. tqqq_trend_long_1d is part of the current book, and the combined replay includes it.
5. **Who acts.** A pass yields a Tier-3 proposal. The manager carries it, either under the data-backed standing authorization (canonical § "Data-backed Tier-2/3 decisions") or to the operator. alpaca_portfolio follows by the superset rule. Mechanics already proven on alpaca_live (whole-share brackets, a 1d ETF leg) need no paper soak (OPERATING-PLAN § 2); new mechanics prove themselves on one small trade.

## 6. Backlog — the next 3–4 weeks (value-ranked)

| week | research (units / nodes) | builds | owner | decision point |
|---|---|---|---|---|
| **W1** (to 2026-11-18) | `207f-01` (book survival), `207f-04` (challengers on the book), `207f-02` (selection), `207f-03` (label) dispatch on merge, ranked in that order | ML-EQ-ENTRY-TIMING fix (approved; ML lane) | research-ops dispatcher + grader; programme review 2026-11-18 reads all four | the baseline number; whether the edge survives the account; which legs qualify |
| **W2** (to 11-25) | Author from the verdicts: `P8-Q4-h2h` if any leg qualified; `P8-Q1-fail` or `P8-Q2-pass` / `P8-Q3-*`; the options read (`P8-Q9`, step 1, Tier 1) | `--trades-from` input for the head-to-head (in the h2h unit's PR); rotation harness for `P8-Q7` | programme review (Wed) / research-ops; rotation harness: the lane the manager assigns | first head-to-head registered |
| **W3** (to 12-02) | `P8-Q7` Stage 0; `P8-Q5` features or `P8-Q6` pool (the one Q3 points at); `P8-Q8` after `98e3-15` lands | — | research-ops | whether a family built for one slot beats the ML leg |
| **W4** (to 12-09) | Head-to-head graded; the N=4 confirmation of any lead; re-cut W5+ | — | manager (Tier-3 packet on a pass); programme review | REPLACE / JOIN / keep Foxhound-4 |

Pre-mortems:
- If 207f-01 fails, the most likely reason is whole-share affordability. The first variant is the affordable sub-pool in `P8-Q1-fail`.
- If 207f-04 is indeterminate, the 1d legs are too sparse at n < 30. The variant is the combined book, pooled per family.

## 7. What this programme does not do

- It changes no config, roster, tau or artifact.
- It does not retire Foxhound-4 or any leg, and does not re-grade 98e3-06.
- It does not re-read the confirm window except as a ledger-claimed, deflated read inside a registered unit.
- It does not move USO onto real money.
- It does not stand in for the ladder's demotion signal for Foxhound-4. That signal is blank today (RELAYED: the DSR tool prints nothing for this leg), and is flagged to the manager as a separate fix.
