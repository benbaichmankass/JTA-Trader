# Weekly walkthrough 2026-11-25

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH**. A section another lane has not landed yet is simply absent. On a collision, the later lane merges `main` first.

<!-- PRACTICE-REFRESH:START -->
# PRACTICE REFRESH: the system learns regime but not trades, a cost gap is now measured, and two MGC legs on IB paper are rejected by the venue today

> Lane `PRACTICE-REFRESH-20261125` (Tier 1, read-only). Full record: [`docs/research/practice-review-2026-11-25.md`](../research/practice-review-2026-11-25.md).
> Canonical list revised in place: [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
> Live reads 2026-11-25 ~18:20–18:30Z, direct HTTPS to the read-only API. **Nothing was queued or changed; every gap is a proposal.**

**TRADING:** 5 sources read (abstract or summary level), plus our own 3 graded units.
- **T3** is strengthened by our own measurement: the recorded cost understates the +1 h markout cost by **+3.78 bps/fill**, CI [+0.36, +7.34],
  n = 2,375 fills (paper and real money pooled; the real-money slice alone is indeterminate).
- **T15** is qualified by our own registered results: a pre-release book flatten **FAILED** (0/6 folds, 0/200 random controls), and decision > minutes
  on 5/5 symbols.
- **T2/T9** noted: practice picks the exit family by holding period.

**MODEL:** 4 new sources (abstract level).
- **M3** strengthened: leakage is a degree measured one switch at a time. Centered features and same-bar-open execution are the big
  inflators, and LLMs carry parametric look-ahead.
- **M5** strengthened: run the whole workflow on a synthetic null first.
- **M14** noted: one more self-reported LLM-trading gain.

**(a) Demo-floor data generation.**
- Population: 58 rostered leg × floor-account cells, journal fills 11-18T18:26Z → 11-25T18:26Z.
- **29/58 cells filled, 97 fills in all**: `bybit_1` 25/29 cells, `alpaca_paper` 3/18, `ib_paper` 1/11.
- The 29 quiet cells:
  - **4 blocked**: `ib_paper` MGC rejected by IBKR (`status=Inactive`, 73 today); `ml_entry_eq` sizing; the desk not trading either paper venue.
  - **3 quiet by design**: holding a position.
  - **22 cannot tell**: no eval line.
- 491 refusals, of which 347 are `bybit_1` slice-budget policy holds.

**(b) Is it learning?**
- Population: 100 trainer-registry rows (mirror 32 s old), the 11-25 build cycle, and the 7-day learning ledger.
- **24/100 models trained and scored, all of them regime or setup heads; 0 trade-decision models.**
- Teacher data: desk and live-review rows are produced and labelled, and the 1,511-row `claude_judgments` set is built daily. **Consumed: 0 all-time.**
- `review_journal`, `cross_asset`, `forecasts` and `macro` build 0 rows. `exit-policy-v1` has been untrained for 121 days.

## Gaps for Thursday

| # | Track | Gap | Proposal | due_by / decision |
|---|---|---|---|---|
| TG1 | TRADING | Harness cost stacks omit the measured markout term (T3) | Row `COST-STACK-MARKOUT-TERM`, report-only beside the current net. Close `MARKOUT-HARNESS` and `EVENT-SPAN-HISTORY` | 12-02; **operator** on making it the grading basis |
| TG2 | TRADING | The calendar weights FOMC minutes like a decision, and the 12-09 decision is timed 30 min late (T15; evidence now in) | `CALENDAR-FOMC-RELEASE-SPLIT` (Tier 2) | **operator OK before 12-08** |
| TG3 | TRADING | `ib_paper` MGC: 73 IBKR `status=Inactive` rejects today; 2 legs make no floor data | Owned by row `IB-MGC-INACTIVE-1125` (lane dispatched 18:35Z); evidence: 73 rejects | in flight |
| TG4 | TRADING | 22/58 floor cells cannot be classified | Raise `FLOOR-LIVENESS-CHECK` + `AUD-20261028-DEMO-FLOOR-NO-EVAL` | manager |
| TG5 | TRADING | 286 slice-budget re-emissions for 79 `bybit_1` fills | Note on `NETTED-SLICES`: log once per held slice per bar | 12-02 |
| TG6 | TRADING | `DESK-PAPER-ACCOUNTS` unproven for five refreshes; `VERDICT-LEFT-TAIL`, `DESK-REPEATABILITY` idle | Raise | manager |
| MG1 | MODEL | No one-switch execution-convention audit (t+1 open vs current) on the daily harnesses (M3) | Unit, rule registered first | 12-02 |
| MG2 | MODEL | `ml_bakeoff` never runs on a null (M5) | Row `ML-BAKEOFF-NULL-ARM` | 12-09 |
| MG3 | MODEL | Pre-cutoff teacher labels may train a student on memorized outcomes (M3, S91) | Note on `CJ-7-BACKFILL-SCOPE` + a pre/post-cutoff teacher-skill unit | 12-09 |
| MG4 | MODEL | Learning chain broken at H3/H4 for every trade-decision source, unchanged since 11-13; 4 zero-row families; `exit-policy-v1` | Raise `DESK-LABEL-JOIN`, `ML-LEDGER-COULD-NOT-LOOK`; row `ML-ZERO-ROW-FAMILIES` | 12-02 |
| MG5 | MODEL | `RESEARCH-TRIAL-CENSUS`, `PERF-FOLLOWUP-DEFLATION` idle since filing | Raise | manager |
<!-- PRACTICE-REFRESH:END -->
