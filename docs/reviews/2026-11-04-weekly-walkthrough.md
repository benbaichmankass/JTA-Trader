# Weekly walkthrough 2026-11-04

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH** (lane `PRACTICE-REFRESH-20261104`, below). A section that another lane has not landed yet is simply absent.
> On a collision, the later lane merges `main` first.

## TRADING + MODEL — weekly practice refresh (lane `PRACTICE-REFRESH-20261104`)

Tier 1, read-only on production. Nothing was queued and no config changed. Full evidence:
[`docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md` § 11](../research/practice-review-trade-mgmt-and-ai-2026-10-28.md).
The canonical list was revised in place:
[`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).

**First, a process finding.** The 2026-10-29 bulk reset dropped **every one of last week's 11 practice proposals unread**
(`PRACTICE-GAPS-20261029`, "value unknown"), along with `IB-PAPER-ETF-LEGS-NO-ROWS` and `FRONTIER-SCAN-COMPLETENESS`. This refresh
re-measured each of them. The proposals whose value is now measured are re-proposed below, and the rest stay dropped.

**TRADING:** 5 sources checked (1 read in full; 1 could-not-look). **Deltas:**
- **T3 strengthened.** Estimate edge pooled and gross, shrink it, then apply the leg's own cost; a per-leg net estimate is noise at our n [S65, Carver 2026-11-04].
- **T9 strengthened.** This is evidence only; the TP doctrine still binds. A large crypto trend study exits by trail only [S67].
- **T14 added.** Report the left tail (p10/p25 R, max DD) beside the mean, because rankings flip with the objective [S66, S68].

**MODEL:** 5 sources checked (abstracts). **Deltas:**
- **M12 added.** Score a model per asset against the simple baseline (e.g. HAR), not on pooled loss, and recalibrate before crediting skill [S69].
- **M3 strengthened.** Leakage includes temporal overlap of correlated series [S70, S71].
- **M11 strengthened.** The agent harness moves behaviour more than the model does, so a harness change is a treatment to re-test [S72, S73].

### Demo-floor data generation

Population: 55 rostered leg × floor cells. Data: trades created 2026-10-28T18:30Z → 11-04T18:56Z (`/api/diag/journal`, 2 × 1000 rows paged).

| Account | Cells | Cells with ≥1 row | Fills | Rejected | Fills a week ago |
|---|---|---|---|---|---|
| bybit_1 | 28 | 18 | 42 | 30 | 20 |
| alpaca_paper | 16 | 5 | 5 | 1 (+1 exchange) | 0 |
| ib_paper | 11 | 3 | 2 | 25 | 1 |

- **Blocked:**
  - **The book refuses signals.** 47 of 57 floor rejections are netting/slice refusals that leave no outcome row:
    `slice_budget_exhausted` 22 (18 on the five SOL legs), `flip_suppressed` 14 and `at_target` 7 (the MGC pair on ib_paper), and
    `opposite_slice` 4. The trading side of this is `PI-20261104-BCZDXJNR-0002`; the lost **data** is not owned by anyone.
  - **`claude_desk` on alpaca_paper / ib_paper:** 0 rows in 8 days, and the cause is not established (`DESK-PAPER-ACCOUNTS`,
    `landed_unproven`).
- **Quiet by design:** 27 cells. Every eval reason reads "no setup / no breakout / regime not chop / not a decision bar".
- **Resolved since last week:**
  - SPLG → SPYM is live and evaluating, but `SPLG-TICKER-DEAD` is still `queued`.
  - ib_paper `tlt_pullback_1d` has its first ib_paper row.
  - `trend_donchian_1h` trades live on bybit_1 (2 closed, 1 open), so `AUD-20261028-DEMO-FLOOR-SHADOW-LEG` may already be met.

### Is it learning?

Population: 98 registry files (`trainer-vm-diag` #22901, agreeing row for row with the live mirror), 24 dataset directories, and the
shadow log 10-24 → 11-04 (45,913 records).

- **market_features:** the chain works end to end. 52 models were retrained (364 runs), 22 heads are scoring (40,709 predictions) and 3 are advisory.
- **Trade-level families** (setup_candidates, conviction_meta, trade_outcomes): 13 models retrained (92 runs), but **0 score live**.
  Improvement: the **setup_candidates dataset is unfrozen** (48,445 rows, newest 10-29; it was frozen at 08-04).
- **LTR:** `review_journal` = **0 rows**, for the second week.
- **Desk:** `claude_judgments` grew 627 → 883 rows, but still no family trains on it.
- **Exit heads:** 4 heads score from **outside the registry**, and their dataset has been frozen since 09-07. One of them,
  `trend_donchian_eth`, is still configured to `close`. The pipeline item was killed on 09-28 on a premise this contradicts.
  No exit-head close was observed in 7 days.
- **Never trained:** `exit-policy-v1` (100.7 days) and `setup-candidates-metalabel-paper-v1`.

### Gaps for Thursday (12 in § 11.7; proposals, nothing queued). Top of the list:

1. **TRADING:** ~47 floor signals a week are discarded by netting/slices with no outcome. **Re-proposed:** a `VIRTUAL-LEG-LEDGER` build row (T12/R3).
2. **MODEL:** the exit head still wired to `close` sits outside the registry. Decide: register and gate it, or set it to `annotate` (Tier 3, one line) (M10).
3. **MODEL:** desk/LTR repeatability is unmeasured, and a harness or brief edit does not re-run D-S0. **Re-proposed:** a k = 3 rerun unit, plus a skill-edit proposal (M11).
4. **MODEL:** trade-level families never score; `review_journal` is 0; `exit-policy-v1` has never trained. Fold these into `ML-PROGRAMME-PLAN` (M1/M10).
5. **BOTH:** there is no per-leg × floor liveness check, and the cells were hand-classified two weeks running. **Re-proposed:** a health-review CHECK (R6).
6. **TRADING:** pooled-gross, own-cost re-grade of the per-leg verdicts (T3), and p10/p25 R in every management verdict (T14).
7. **MODEL:** the 3 advisory regime/vol heads against `ml_bakeoff.py`'s `har_rv_control`, per asset (M12).
8. **MODEL:** `ML-LEARNING-LEDGER` is still queued after two refreshes. It is **raised** to the manager.
<!-- PRACTICE-REFRESH:END -->
