# Practice refresh 2026-11-25 (lane `PRACTICE-REFRESH-20261125`)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Tier 1, read-only on production. Dispatched by Manager Session 2026-11-25a (session_01AFoLuKKEyjyRMDSxQ1prHf) under the weekly
> reset job `practice-refresh`, governed by [`.claude/skills/frontier-research/SKILL.md`](../../.claude/skills/frontier-research/SKILL.md)
> § "Practice & methodology refresh". **Deltas only.** The baseline and earlier refreshes are in
> [`practice-review-trade-mgmt-and-ai-2026-10-28.md`](practice-review-trade-mgmt-and-ai-2026-10-28.md) (`[S1]`–`[S78]`) and
> [`practice-review-2026-11-18.md`](practice-review-2026-11-18.md) (`[S79]`–`[S87]`). The canonical list is
> [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
> Read on `main` `4ab9993bf`, 2026-11-25 ~18:15–19:30Z. Live reads were direct HTTPS to the read-only API (`/api/diag/journal`,
> `/api/bot/ml/{status,registry,builds,cycle}`), the latter served from the trainer mirror, which was 32–34 s old at read time.
>
> **Gates this adds or changes:** none. This lane queues no unit and edits no config, src, roster or row. Every gap below is a
> **proposal** for the manager: each names the row or unit it would become and a `due_by`, or a named operator decision
> (audit-outcome contract).

## 1. Previous refresh read (the § 5 items of 2026-11-18 and their state)

States come from the work store (`scripts/ops/work.py get <ID>`), read 2026-11-25 ~18:20Z. Unit states come from the `status:` and
`grading:` fields of `research/queue/<id>.yaml`.

| Item (11-18) | State 2026-11-25 | Reading |
|---|---|---|
| `RQ-20261118-a5b3-01` book-level pre-event flatten | **done · FAIL** (graded 11-19) | See E2. `flatten@T-60m` vs hold: 0 of 6 folds held, 0 of 200 matched random controls beaten. The risk-cut clause failed (`cvar5_cut_pct` 0.059 and `dd_cut_pct` 0.026, as recorded). Cost 0.012 R/trade. 137 events, 304 trades flattened |
| `RQ-20261118-a5b3-02` event-class weights | **done · PASS** (graded 11-20) | See E3. "DECISION > MINUTES on 5 of 5 symbols", n = 819 |
| `RQ-20261118-a5b3-03` markout vs recorded cost | **done · PASS** (graded 11-19) | See E1. The recorded cost is **understated**: pooled +1 h (markout cost − recorded cost) = +3.78 bps, CI [+0.36, +7.34], n = 2,375 fills |
| `MARKOUT-HARNESS` | **in_flight** (owner PROGRAMME-REPLAN-20261119, due 11-25) | Its unit has landed and been graded, but the row is still open. Close-out is missing |
| `EVENT-SPAN-HISTORY` | **in_flight** (same owner, due 11-25) | Its units -01 and -02 graded. Same close-out gap |
| `CALENDAR-FOMC-RELEASE-SPLIT` | **queued**, untouched since 11-18 | The evidence it waited for (a5b3-02) is now in. **The 2026-12-09 FOMC decision is 14 days out** (§ 6 TG2) |
| `RESEARCH-TRIAL-CENSUS` · `FLOOR-LIVENESS-CHECK` · `VERDICT-LEFT-TAIL` · `DESK-REPEATABILITY` · `PERF-FOLLOWUP-DEFLATION` | **queued**, all untouched since 11-18 18:20Z, all due 11-25 | `FLOOR-LIVENESS-CHECK`, `VERDICT-LEFT-TAIL`, `DESK-REPEATABILITY` and `PERF-FOLLOWUP-DEFLATION` carry gaps first raised 11-04 or 11-11. **Raised to the manager** under the skill's two-refresh rule, not re-filed |
| `BOOK-CORR-VIEW-LTR` (note appended 11-18) | **done** 11-19 | — |
| `DESK-PAPER-ACCOUNTS` | **landed_unproven since 11-07**, the fifth refresh running | This week `claude_desk` had **0** fills on `alpaca_paper` and 0 on `ib_paper`, and 3 on `bybit_1` (§ 5a). Still unproven. Raised again |
| `SOAK-FAULT-INTAKE` | **done** 11-19 | — |
| `VIRTUAL-LEG-POSITIONS` | **queued**, due 11-17, now past due | Raised |
| `PI-20261029-IFMPNGJK-0004` (superseded) | not re-checked | — |

## 2. Our own evidence this week (MEASURED; from the units above)

- **E1 · cost (T3).** `RQ-20261118-a5b3-03` PASS. The journal's recorded cost understates the +1 h markout cost by **+3.78 bps
  pooled**, CI [+0.36, +7.34], n = 2,375 fills since 2026-09-01. The population is all fills, paper and real money together.
  The real-money-only slice, `RQ-20261122-b18a-01`, is **INDETERMINATE**: CI [−6.81, +32.77] straddles both bars.
  Evidence: `research/results/RQ-20261118-a5b3-03/44561843728.jsonl`.
- **E2 · book event risk (T15, T1).** `RQ-20261118-a5b3-01` FAIL under `RULE-AM-RISK-ADJUSTED-V1`. On our history, flattening the
  book's same-direction risk 60 min before a high-impact release
  - **did not cut book risk enough** to pay for itself (R2 failed),
  - held in **0 of 6** walk-forward folds,
  - beat **0 of 200** matched random flatten sets.
  The best static choice per fold was **hold** in every fold. Evidence: `research/results/RQ-20261118-a5b3-01/44551250786.jsonl`.
- **E3 · event weights (T15).** `RQ-20261118-a5b3-02` PASS. Our own symbols' 2 h realized vol rates an FOMC decision above the FOMC
  minutes on **5 of 5** symbols tested, n = 819 event windows. The cells where vol is elevated are `cpi/SOLUSDT`, `fomc_decision` on
  BTC, ETH, GLD, SOL and SPY, and `fomc_minutes` on GLD and SPY. This confirms S80 and S81 on our own data.

## 3. Sources checked (what was actually read)

Six web searches, five abstract fetches. Every arXiv item below was read **at abstract level only**, and no full text was read.

**TRADING**
- [S88] Bui & Nguyen, "Systematic Trend-Following with Adaptive Portfolio Construction: Enhancing Risk-Adjusted Alpha in
  Cryptocurrency Markets", arXiv 2602.11708 (Feb 2026). https://arxiv.org/abs/2602.11708 [ACAD preprint; **abstract**].
  - Design: a volatility-regime-calibrated trailing stop on 6 h bars, monthly rebalance, 150+ pairs, OOS 2022–2024.
  - Reported: Sharpe 2.41, MDD −12.7%.
  - The abstract **does not say the figures are net of cost.** **Cautionary**: a reported Sharpe without a stated cost basis is
    a claim (T3, M14).
- [S93] LPL Research, "A Tale of Two CTAs" (2025–26). https://www.lpl.com/research/blog/a-tale-of-two-ctas.html [PRAC; **search
  summary**]. Practice splits exit style by **holding period**:
  - medium- and long-horizon trend programmes exit on signal reversal, a trailing stop or a vol cut;
  - short-term programmes use profit targets, tight stops and time stops.
- [S94] Clare, Seaton, Smith & Thomas, trend following and stop-losses on the S&P 500, as summarized by Alpha Architect.
  https://alphaarchitect.com/trend-following-the-sp-500-some-practical-advice/ [ACAD via PRAC summary; **summary**]. Stop-loss rules
  added to trend signals did not help, and the better lever was the trend signal itself. Single market. This is consistent with T2.
- Checked, nothing new kept:
  - Li et al., arXiv 2604.27150, is S75, already held.
  - Krestenko & Butov, arXiv 2605.05089 (perp basis): funding explains realized P&L, already covered by T3 and S61.
  - A Research Square trailing-stop note (one parameter set) and blog backtests (setup4alpha, mql5, Concretum): single
    unrefereed tests, not kept.

**MODEL**
- [S89] Zhang, Li, Peng & Chen, "When Alpha Disappears: A One-Switch Benchmark for Decision-Time Leakage in Financial Backtests",
  arXiv 2605.23959 (May 2026). https://arxiv.org/abs/2605.23959 [ACAD preprint; **abstract**].
  - Method: toggle **one** evaluation convention at a time against a clean t+1-open reference, holding fixed the data, split,
    model, horizon, portfolio rule and costs. Two daily equity panels, six model families, yearly tests 2016–2024.
  - Inflation is **selective**. **Centered temporal features** and **same-day-open execution that uses post-open daily-bar
    information** inflate predictive and trading metrics strongly and stably.
  - Global normalization, future-informed graphs and same-day-close execution are weak in most settings.
  - No effect sizes are given in the abstract.
- [S90] Nikolopoulos, "Spurious Predictability in Financial Machine Learning", arXiv 2604.15531 (Apr 2026).
  https://arxiv.org/abs/2604.15531 [ACAD preprint; **abstract**].
  - Adaptive specification search produces significant backtests **under a martingale-difference null**.
  - Proposed audit: run the **whole workflow, search included**, on synthetic zero-predictability and microstructure-placebo
    environments. A workflow that shows significant walk-forward evidence there is falsified.
  - For survivors, measure the in-sample vs disjoint walk-forward gap, adjusted for effective multiplicity.
  - No numbers in the abstract.
- [S91] Li, Wang & Ma, "Summoning the Oracle to Slay It: Mitigating Look-Ahead Bias in Financial Backtesting with Large Language
  Models" (FinCAD), arXiv 2605.24564, EMNLP 2026 main. https://arxiv.org/abs/2605.24564 [ACAD; **abstract**].
  - "Parametric look-ahead bias": an LLM's pretraining holds the outcomes being backtested.
  - The fix was tested on five 7–14B models and five mega-caps. It corrected the mean **in-sample** return by as much as
    **−67.1%**, while 2025 OOS Sharpe moved by at most ±0.10.
  - The in-sample vs OOS rank correlation across 11 models rose from +0.779 to +0.846.
  - Reading: much of an LLM's in-sample "skill" on pre-cutoff history is memory.
- [S92] Zhou et al., "TradingMoE: Routing the Right Experts in Evolving Markets", arXiv 2608.11785 (Aug 2026).
  https://arxiv.org/abs/2608.11785 [ACAD preprint; **abstract**].
  - Claims about 30% cumulative-return gains over 22 baselines and says the edge persists in rolling forward-only paper trading.
  - The abstract gives no period, no costs and no trial count. **Cautionary** (M14).
- Checked, nothing new kept:
  - AI-Trader (2512.10971), LiveTradeBench (2511.03628), Agent Market Arena (2510.11695) and StockBench (2510.02209 v2) are
    already held as S53, S72 and S73. No 2026 live results surfaced.
  - AlgoXpert IS–WFA–OOS (2603.09219) restates R7 and M2.
  - A HackerNoon pointer to a July 2026 "Quantifying Backtest Overfitting from Information Leakage" paper could not be verified on
    arXiv, so it is not cited.

## 4. Deltas (each one is now in the canonical list, dated 2026-11-25)

| Track | Principle | Delta | Source |
|---|---|---|---|
| TRADING | T3 strengthened | On our own fills the recorded cost understates the +1 h markout cost by ~3.8 bps pooled. A harness cost stack that uses recorded fees and slippage is therefore optimistic by about that much per fill until a markout term is in it | E1 (`RQ-20261118-a5b3-03`); S74 |
| TRADING | T15 qualified | **Measuring** book event exposure stays. **Acting** on it by a blanket pre-release flatten failed our registered test (0/6 folds, 0/200 random controls): no flatten class is supported on our data. Release weights by measured effect are confirmed on our symbols (decision > minutes, 5/5) | E2, E3 |
| TRADING | T2 / T9 noted | Practice chooses the exit **family by holding period**: long-horizon trend programmes use signal reversal, a trail or a vol cut, and short-horizon programmes use targets, tight stops and time stops. On S&P trend signals, adding stops did not help; changing the signal did. Under the TP doctrine this is evidence on which arms to test, never an exemption | S93, S94; cautionary S88 |
| MODEL | M3 strengthened | Leakage is a **degree**, measured one convention at a time against a clean t+1-open reference. The two strong inflators are **centered temporal features** and **same-bar-open execution that uses that bar's later information**. LLMs add **parametric look-ahead**: pre-cutoff in-sample skill is largely memory | S89, S91 |
| MODEL | M5 strengthened | Run the **whole workflow, search included, on a synthetic null** (a martingale target or microstructure placebo) before reading a real result. A workflow that "passes" on the null is falsified, whatever its real-data score | S90 |
| MODEL | M14 noted | Another self-reported LLM-trading gain with no costs or trial count | S92 |

No principle was removed.

## 5. Two measurements

### 5a. Demo-floor data generation (last 7 days)

**Population.**
- Every leg on the `strategies:` roster of the three demo-floor accounts (`bybit_1` 29, `alpaca_paper` 18, `ib_paper` 11, re-parsed from
  `config/accounts.yaml` on `main` `4ab9993bf`): **58 leg × account cells**.
- Trade rows come from `/api/diag/journal?table=trades`, paged with `offset` (5 × 1,000 rows, newest id 8613). Window
  **2026-11-18T18:26Z → 2026-11-25T18:26Z**. Page 0 alone reaches back to 11-16, so the window is complete.
- "Trades" = journal rows with status `closed` or `open`, i.e. fills. Rejected rows are counted separately.
- Order packages come from `journal?table=order_packages`, page 0, which reaches back to 11-15. It is keyed by strategy, not account.

**Headline.**
- **29 of 58 cells filled ≥ 1 trade, for 97 fills in total.**
  - By account: `bybit_1` 25/29 cells (79 fills), `alpaca_paper` 3/18 (16), `ib_paper` 1/11 (2).
  - Outside the roster: 3 `orphan_adopt` rows on `alpaca_paper` (reconciler adopt-and-flatten).
- 491 rows on rostered cells were refusals or rejections:
  - `bybit_1`: `slice_budget_exhausted` 286, `opposite_slice_one_way_book` 53, `slice_ledger_divergent` 6, exchange 2.
  - `ib_paper`: IBKR `status=Inactive` 73, `flip_suppressed_hold_policy` 46, `hold_to_bracket_reduce_non_derivative` 18.
  - `alpaca_paper`: `risk_refused` 3, `ml_entry_symbol_held` 4.

**Classification of the 29 quiet cells** (0 fills in 7 days):

| Class | Cells | Cause (evidence) |
|---|---|---|
| **BLOCKED: venue rejects** | `ib_paper` `ict_scalp_mgc_15m`. `ib_paper` `mgc_trend_1h` is only partly quiet: 2 fills and 71 rejects | **73 rejects: "IB rejected order for MGC: IBKR rejected/cancelled parent order: status=Inactive"**, all **today, 14:45–17:25Z**. The rest are hold-policy no-ops. At read time no open row named it. The manager has since opened row `IB-MGC-INACTIVE-1125` (§ 6 TG3) |
| **BLOCKED: sizing** | `alpaca_paper` `ml_entry_eq` | 1 package, refused `risk_refused: sized_qty=…` (the exposure-ceiling class, row `ZERO-QTY-EXPOSURE-EXPLAIN`, queued) |
| **BLOCKED: desk not trading the venue** | `alpaca_paper` `claude_desk`, `ib_paper` `claude_desk` | 3 desk packages in the window, all filled on `bybit_1`. `DESK-PAPER-ACCOUNTS` has been landed_unproven since 11-07 |
| **QUIET BY DESIGN: holding** | `alpaca_paper` `tlt_pullback_1d` (open since 11-16), `alpaca_paper` `ief_pullback_1d` (11-17), `ib_paper` `tlt_pullback_1d` (11-16) | An open position, so a daily leg takes no new entry |
| **CANNOT TELL** (0 packages, no eval line) | 22 cells. `bybit_1`: `fade_breakout_4h`, `fvg_range_15m`, `squeeze_breakout_4h`, `trend_donchian_xrp_adx25`. `alpaca_paper`: `spy/qqq/iwm/tqqq/qld/splg/scha_trend_long_1d`, `slv/gdx/iaum_pullback_1d`, `uso_trend_1h`. `ib_paper`: `mes_trend_long_1d`, `mgc/mhg/gld_pullback_1d`, `spy/qqq/iwm_trend_long_1d` | Without a per-leg eval or refusal line, quiet-by-design cannot be told from blocked. This is the gap of rows `AUD-20261028-DEMO-FLOOR-NO-EVAL` and `FLOOR-LIVENESS-CHECK`, both queued. **Long silences that look suspicious:** on `alpaca_paper`, `spy_trend_long_1d`'s last fill was 08-03, `iwm_trend_long_1d`'s 08-05, `gld_pullback_1d`'s 07-24, and `qqq`/`qld_trend_long_1d`'s 09-21, each a long-only trend leg through a period that included up-trends. Stated as a suspicion, not a finding |

The `bybit_1` refusals are **policy holds by design** (`slice_budget_exhausted` is the risk layer declining on purpose:
`src/runtime/execution_diagnostics.py:1032`). The legs behind them still filled (for example `eth_pullback_2h` had 1 fill and 96 refusals).
They are re-emissions while a slice is held, not blocks. Even so, 347 refusals in a week is a large logging load for 79 fills.

### 5b. Is it learning? (rows → datasets → models trained → models scored)

**Population.**
- The trainer registry through the live API's trainer mirror: `/api/bot/ml/registry`, **100 registry rows** plus 8 served or overlay
  ids not in the registry, 108 in all. Mirror age 32 s.
- Dataset builds: `/api/bot/ml/builds`, the last 100 build events, all from the 2026-11-25 01:07–01:24Z cycle.
- The learning ledger: `scripts/ops/ml_learning_ledger.py --json`, window 2026-11-18T18:28Z → 11-25T18:28Z.
- The relay route (`trainer-vm-diag`) was **not used**. The mirror is the trainer's own published status and is about 30 s
  behind it. Use the relay if the two ever disagree.
- "Trained" = a registry run with `at` in the window. "Scored" = that run carries metrics.

| Data family | Rows built (latest cycle) | Models in registry | Trained in window | Scored in window | Last run | First broken hop |
|---|---|---|---|---|---|---|
| `market_features` (regime heads) | 876,336 (15 builds); `market_raw` 832,656 (25) | 74 | **22** | 22 | 11-25 15:21Z | none. Stages: 16 shadow, 3 advisory/LIVE (btc-15m fc-pcv, sol-15m fc-pcv, mes-5m) |
| `conviction_meta` | — (not in the last 100 events) | 4 | 1 | 1 | 11-25 01:24Z | none. All candidate |
| `setup_candidates` | — | 10 | 1 | 1 | 11-25 01:24Z | none. All candidate |
| `trade_outcomes` | 34 (MES only in this cycle) | 4 | 0 | 0 | 11-11 | **H4**: rows build daily but nothing trained for 14 days |
| `setup_labels` / `_audit` | 3,381 / 41 | 3 / 1 | 0 | 0 | 10-21 / 11-11 | **H4** |
| `execution_quality` | — | 1 | 0 | 0 | 11-11 | H4 |
| `claude_judgments` (desk + LTR teacher) | **1,511** | **0** | 0 | 0 | — | **H3/H4**. The ledger shows desk H1 = 9 produced, H2 = 5 labelled, H3 = **0 all-time** (`consumed.jsonl` holds 0 rows), live-review H1 = 45, H2 = 83, H3 `could_not_look`. Rows `ML-LEDGER-COULD-NOT-LOOK` and `DESK-LABEL-JOIN` are queued |
| `review_journal` · `cross_asset` · `forecasts` · `macro` | **0** each | 0 | 0 | 0 | — | **H1**: the builds succeed with zero rows |
| `account_context` · `corpus_panel` · `market_sequences` | 45 / — / — | 1 / 1 / 1 | 0 | 0 | 07-03 → 07-26 | dormant |

- Registry total: **24 of 100 models trained and scored in the window, all of them regime or setup heads.** **0 trade-decision models**
  were trained (ledger H6 = 0, an estimate).
- Last cycle 11-25 08:08Z: `overall_rc` 0, outcome `complete_with_refusals`, 3 refusals, 0 trained. Regime heads train every third day.
- `exit-policy-v1` has **0 registered runs in 121 days** (`manifest_untrained_stale` every cycle).
- Ledger H5: 163 `ml_health` verdicts in the window (pass 20, fail 50, indeterminate 74, other 19). H7: 6 of 59 live-execution legs
  can be changed by ML output, 3 of them on real money. Both are lower-bound estimates.
- **Reading:** the system learns about **regime**, but not about **trades or decisions**. Teacher rows are produced and labelled every
  day, and nothing consumes them. That is the same first broken hop that 11-13's `ML-LEARNING-LEDGER` record found. It is
  unchanged, and its two owning rows have not moved.

## 6. Our live designs vs the list, and the gaps for Thursday

Population: `config/live_trade_review.yaml`, `.claude/skills/{trading-desk,live-trade-review,exit-refinement,model-training,
ml-review,performance-review,perf-followup,health-review}/SKILL.md`, `scripts/research/ml_bakeoff.py`, the checklist store and the
two measurements above, on `main` `4ab9993bf`.

**Matches practice (checked):**
- M3 / S89 centered features: **0** `center=` arguments among **214** `.rolling(` calls in `ml/`, `src/` and `scripts/` (non-test).
- M8 trigger set as a factor: `scripts/research/live_review_trigger_tune.py` and `ltr_action_trigger_s0.py` exist. A first, narrower
  probe for `by_trigger|per_trigger` found 0 hits, so that negative was the probe's fault, not the design's.
- T15: the release-weight question now has our own answer (E3).
- The CJ-7 backfill already marks pre-cutoff judgments as train-only, never validate.

**Gaps for Thursday** (each one a proposal; nothing is queued by this lane):

| # | Track | Gap (principle) | Proposal → row/unit | due_by / decision |
|---|---|---|---|---|
| TG1 | TRADING | **Harness cost stacks omit the markout term** that E1 measured (+3.8 bps/fill pooled). Every Stage-0 net figure is optimistic by that much (T3) | Row `COST-STACK-MARKOUT-TERM` (Tier 1, report-only first): print a markout-adjusted net **beside** the current net in the dispatchable harnesses. Making it the grading basis changes promotion evidence, so that step is a **named operator decision**. Also close `MARKOUT-HARNESS` and `EVENT-SPAN-HISTORY`, whose units landed | row due 2026-12-02; operator decision on the grading basis |
| TG2 | TRADING | **The calendar still weights the FOMC minutes like a decision and times the 12-09 decision 30 min late.** The evidence is now in (E3) (T15) | Existing row `CALENDAR-FOMC-RELEASE-SPLIT` (Tier 2): **an operator OK before 2026-12-08** | **operator decision, before 12-08** |
| TG3 | TRADING | **`ib_paper` MGC orders all rejected by IBKR (`status=Inactive`), 73 today 14:45–17:25Z.** Two rostered legs produce no floor data (the R3 mechanics loop is broken on futures) | Already owned: row `IB-MGC-INACTIVE-1125` (lane dispatched by the manager 18:35Z). This lane's evidence for it: 73 rejects today 14:45–17:25Z | in flight under that row |
| TG4 | TRADING | 22 of 58 floor cells are **undeterminable**: no eval or refusal line. The floor-liveness CHECK has been proposed three times and is still queued (R3, R6) | Existing rows `FLOOR-LIVENESS-CHECK` + `AUD-20261028-DEMO-FLOOR-NO-EVAL`: **raise** (the two-refresh rule) | manager: assign or kill with a reason |
| TG5 | TRADING | No refusal-volume budget: 286 `slice_budget_exhausted` re-emissions for 79 `bybit_1` fills inflate logs and the teacher corpora with duplicates (M4 / R9 analogue) | Note on row `NETTED-SLICES` (landed_unproven): suppress re-emission while a slice is held, or log once per bar | note due 2026-12-02 |
| TG6 | TRADING | `DESK-PAPER-ACCOUNTS` unproven for five refreshes, with 0 desk fills on the paper venues this week; `VERDICT-LEFT-TAIL` (T14) and `DESK-REPEATABILITY` (M11) untouched | **Raise** | manager |
| MG1 | MODEL | **No one-switch execution-convention audit** on the daily harnesses: same-bar open or close vs t+1 open (M3, S89) | Unit (proposed, rule registered first): on the daily trend/pullback harness, re-run the rostered 1d legs with entry at t+1 open vs the current convention. PASS-to-worry if the net R/trade gap is > 0.05 R with a CI that excludes 0 | unit due 2026-12-02 |
| MG2 | MODEL | **`ml_bakeoff` never runs its workflow on a null** (M5, S90) | Row `ML-BAKEOFF-NULL-ARM` (Tier 1): an optional `null_controls:` block (a shuffled-within-fold target, and a synthetic martingale series). A candidate that clears `pass_if` on a null fails the unit | row due 2026-12-09 |
| MG3 | MODEL | **Teacher labels from pre-cutoff history carry parametric look-ahead** (S91). CJ-7 keeps them out of validation but still lets them **train** a student, which can learn the leak | Note on `CJ-7-BACKFILL-SCOPE` + a unit: compare teacher-label skill on pre-cutoff vs post-cutoff trades on one grader. A gap whose CI excludes 0 → pre-cutoff rows leave the training set | note now; unit due 2026-12-09 |
| MG4 | MODEL | **The learning chain is broken at H3/H4 for every trade-decision source** (§ 5b), unchanged since 11-13, and its rows are idle. `exit-policy-v1` has been untrained for 121 days. Four dataset families build 0 rows daily | **Raise** `DESK-LABEL-JOIN`, `ML-LEDGER-COULD-NOT-LOOK`. New row `ML-ZERO-ROW-FAMILIES` (Tier 1): fix or retire `review_journal`, `cross_asset`, `forecasts` and `macro` builds and the `exit-policy-v1` manifest, each with a terminal reason | row due 2026-12-02 |
| MG5 | MODEL | `RESEARCH-TRIAL-CENSUS` (R9) and `PERF-FOLLOWUP-DEFLATION` (M5) untouched since filing | **Raise** | manager |

**Dropped, with reasons:**
- A pre-release flatten or blackout. E2 failed it on our data, and it would be a gate.
- Moving trend legs to trail-only exits on the strength of S88, S93 and S94. The TP doctrine binds, S88 states no cost basis, and
  the T9 arm already exists.
- An LLM debiasing decoder (FinCAD) for the desk. Our desk uses hosted models, where decoding cannot be changed. The usable lesson
  is MG3.

## 7. Run record (`practice` block)

```json
{"practice": {
  "run": "PRACTICE-REFRESH-20261125", "finished_at": "2026-11-25",
  "previous_refresh_read": [
    {"gap": "RQ-20261118-a5b3-01", "state": "done FAIL"},
    {"gap": "RQ-20261118-a5b3-02", "state": "done PASS"},
    {"gap": "RQ-20261118-a5b3-03", "state": "done PASS (real-money slice RQ-20261122-b18a-01 INDETERMINATE)"},
    {"gap": "MARKOUT-HARNESS", "state": "in_flight; unit landed, row not closed"},
    {"gap": "EVENT-SPAN-HISTORY", "state": "in_flight; units landed, row not closed"},
    {"gap": "CALENDAR-FOMC-RELEASE-SPLIT", "state": "queued; 12-09 decision 14 days out"},
    {"gap": "RESEARCH-TRIAL-CENSUS|FLOOR-LIVENESS-CHECK|VERDICT-LEFT-TAIL|DESK-REPEATABILITY|PERF-FOLLOWUP-DEFLATION", "state": "queued, untouched; raised"},
    {"gap": "DESK-PAPER-ACCOUNTS", "state": "landed_unproven since 11-07; raised"},
    {"gap": "VIRTUAL-LEG-POSITIONS", "state": "queued, past due 11-17"}],
  "trading": {"sources_checked": [
      {"url": "https://arxiv.org/abs/2602.11708", "tag": "ACAD", "read": "abstract"},
      {"url": "https://www.lpl.com/research/blog/a-tale-of-two-ctas.html", "tag": "PRAC", "read": "summary"},
      {"url": "https://alphaarchitect.com/trend-following-the-sp-500-some-practical-advice/", "tag": "ACAD", "read": "summary"},
      {"url": "https://arxiv.org/abs/2604.27150", "tag": "ACAD", "read": "summary (already S75)"},
      {"url": "https://huggingface.co/papers/2605.05089", "tag": "ACAD", "read": "summary"}],
    "deltas": ["T3 strengthened (own markout)", "T15 qualified (own flatten FAIL; weights confirmed)", "T2/T9 noted (exit family by holding period)"],
    "gaps_filed": [], "gaps_proposed": ["TG1", "TG2", "TG3", "TG4", "TG5", "TG6"], "none_because": null},
  "model": {"sources_checked": [
      {"url": "https://arxiv.org/abs/2605.23959", "tag": "ACAD", "read": "abstract"},
      {"url": "https://arxiv.org/abs/2604.15531", "tag": "ACAD", "read": "abstract"},
      {"url": "https://arxiv.org/abs/2605.24564", "tag": "ACAD", "read": "abstract"},
      {"url": "https://arxiv.org/abs/2608.11785", "tag": "ACAD", "read": "abstract"},
      {"url": "https://arxiv.org/abs/2511.03628", "tag": "ACAD", "read": "summary (already held)"}],
    "deltas": ["M3 strengthened (decision-time leakage degrees; parametric look-ahead)", "M5 strengthened (null-environment falsification)", "M14 note"],
    "gaps_filed": [], "gaps_proposed": ["MG1", "MG2", "MG3", "MG4", "MG5"], "none_because": null},
  "measurements": {
    "floor": {"population": "58 rostered leg x floor-account cells; journal trades 2026-11-18T18:26Z..11-25T18:26Z", "cells_with_fill": 29, "fills": 97, "refusals": 491, "quiet": 29, "blocked": 4, "holding": 3, "cannot_tell": 22},
    "learning": {"population": "100 trainer-registry rows (mirror, 32 s old) + 100 build events of the 11-25 cycle + ml_learning_ledger 7d", "trained_7d": 24, "scored_7d": 24, "trade_decision_trained_7d": 0, "first_broken_hop": "H3/H4 for desk, live_review and trade_outcomes; H1 for review_journal, cross_asset, forecasts and macro"}},
  "principles_revised": ["T3: strengthened", "T15: qualified", "T2/T9: noted", "M3: strengthened", "M5: strengthened", "M14: noted"]}}
```

## 8. Sources added by this refresh

- [S88] D. Bui & T. Nguyen, arXiv 2602.11708 (2026). https://arxiv.org/abs/2602.11708 [ACAD preprint; abstract; cautionary]
- [S89] F. Zhang, Z. Li, S. Peng & Y. Chen, "When Alpha Disappears", arXiv 2605.23959 (2026). https://arxiv.org/abs/2605.23959 [ACAD preprint; abstract]
- [S90] S. D. Nikolopoulos, "Spurious Predictability in Financial Machine Learning", arXiv 2604.15531 (2026). https://arxiv.org/abs/2604.15531 [ACAD preprint; abstract]
- [S91] W. W. Li, M. Wang & T. Ma, "Summoning the Oracle to Slay It" (FinCAD), arXiv 2605.24564, EMNLP 2026. https://arxiv.org/abs/2605.24564 [ACAD; abstract]
- [S92] C. Zhou et al., "TradingMoE", arXiv 2608.11785 (2026). https://arxiv.org/abs/2608.11785 [ACAD preprint; abstract; cautionary]
- [S93] LPL Research, "A Tale of Two CTAs". https://www.lpl.com/research/blog/a-tale-of-two-ctas.html [PRAC; search summary]
- [S94] Clare, Seaton, Smith & Thomas, trend following and stop-losses on the S&P 500, via Alpha Architect. https://alphaarchitect.com/trend-following-the-sp-500-some-practical-advice/ [ACAD via PRAC; summary]
