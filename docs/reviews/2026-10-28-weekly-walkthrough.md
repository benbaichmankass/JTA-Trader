# Weekly walkthrough 2026-10-28

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP-20261028`, below), **ML + FRONTIER**
> (lane `ML-FRONTIER-PREP`) and **PRACTICE REFRESH** (lane `PRACTICE-REFRESH`). A section another lane has not
> landed yet is simply absent; on a collision, the later lane merges `main` first.

# PERFORMANCE — /performance-review 2026-10-28: the losses are stops in a two-sided chop, multiplied ×3 by account fan-out; exits are giving back more of the peak, and the scalp family has gone quiet

> Skill: `.claude/skills/performance-review/SKILL.md` (2026-10-28 redesign), run in full: Layer 0, CHECKS C1–C12,
> ANALYSIS, decisions. **`/perf-followup` was not run.** It is handed off (§3). Machine record:
> `comms/reviews/performance-review-20261028-190000.json`.
>
> **Merged ≠ deployed ≠ observed.** Every trade figure here is **OBSERVED** on the live read-only API and the diag relay
> on 2026-10-28, 19:00–19:40Z (trader `git_sha_running 3b6794253`). The TP-doctrine table is **OBSERVED on repo config**
> at `main` `85921539`, not a live-VM read. This PR changes no code and no config. **Public repo:** no balances are
> stated. $ is absolute P&L only, and real-money $ is single digits at its sizing.

## Headline (the operator's three measures)

| measure | real_money (`bybit_2`+`alpaca_live`) | paper+mirror (journal `account_class: paper`) | source |
|---|---|---|---|
| **net R, 7d** | **−3.89 R** over 7 closes (expR −0.56) | **−15.31 R** over 30 closes (expR −0.51) | `/api/bot/performance?window=7d`, R basis `declaredInitial` |
| **net R, 30d** | −8.77 R / 20 (expR −0.44) | −17.91 R / 267 (expR −0.07) | same, `window=30d` |
| **net R, lifetime** | −157.3 R / 467 (expR −0.34; `vwap` carries −145.9 R of it, retired) | −141.7 R / 1650 (expR −0.09) | same, `window=all` |
| **R per capital-day** (telemetry-joined minority) | 90d **+0.023** (n=13) · 30d −0.63 (n=3) · 7d −1.80 (n=1): all `insufficient_n` below 90d | 90d **+0.075** (n=351) · 30d **−0.020** (n=73) · 7d **−0.216** (n=24) | `giveback_census.py`, trade dump filtered by `closed_at` per window |
| **giveback (share of peak R given back)** | 90d 93% (n=13) | 90d **91%** (n=351) → 30d **107%** (n=73) → 7d **133%** (n=24) | same |
| **TP compliance** | **0 of 6** routings compliant | paper 0/60 · mirror 0/5 · prop 0/6 | `check_tp_doctrine.py`, re-run, 77 routings |

**7-day closes by account** (journal, `closed_at` ≥ 2026-10-21T19:00Z, n=39; `/api/bot/trades/closed` gives 40 over a
5-minute-wider window, so the two reads agree). R here is pnl ÷ (|entry − stop| × size × contract multiplier):

| account | class | n | wins | ΣR | exits |
|---|---|--:|--:|--:|---|
| `bybit_1` | paper | 20 | 5 | −6.96 | sl 16 (3 of them trailed-stop wins), live_review_close 2, tp 1, operator_flatten_reconciled 1 |
| `bybit_portfolio` | mirror | 8 | 2 | −4.28 | sl 7 (1 trailed win), operator_flatten_reconciled 1 |
| `bybit_2` | **real money** | 7 | 1 | −5.39 | sl 7 (1 trailed win) |
| `ib_paper` | paper | 2 | 0 | −2.08 | sl_cross 1, **exchange_flat_reconciled 1** |
| `alpaca_paper` | paper | 2 | 0 | −2.00 | sl 1, sl_cross 1 |
| `alpaca_live`, `alpaca_portfolio`, prop books (`breakout_*`, `tradeify_1`, `velotrade_1`) | | 0 | | | no closes |

31 of 39 closes are `sl`, and 1 is `tp`. The 39 trades come from **25 distinct decisions**. Today, 10-28, had 11 closes
from 9 packages: 9 `sl`, 1 `tp` (`ict_scalp_xrp_5m` +3.2 R) and 1 `live_review_close`. **Both sides were stopped
within hours:** SOL/ETH pullback **shorts** at ~08:30Z, BTC/SOL donchian **longs** at ~12:15Z, an ETH donchian
**short** at 18:02Z.

> ⚠️ **Correction to the 19:02Z preliminary.** It stated that `mes_trend_long_1d` was the "biggest $ hit". In $ that is true
> on paper (−16,256, MEASURED), but in R it is −1.02 R, an ordinary stop-sized loss. I first computed MES/MGC R without
> the contract multiplier (−5.1 R / −10.6 R); the table above has the multiplier. The preliminary's account R figures already
> carried the correction.

---

## 0. Prior calls (Layer 0)

`review_followthrough.py --source performance-review --window-days 7`: **cohort** 14 filed in 7 d, 2 done, 0 killed,
12 open (14% closed within 7 d). **Backlog** 69 open (59 pipeline + 10 checklist rows), 26% due, median age 46 d,
**42 with no owner**.

The newest JSON review (`performance-review-20261010-191000.json`) and the 10-21 brief carry **no `calls[]` and no `p`**:
they predate the redesign. They were graded from `recommended_action` and the 10-21 brief's §7 follow-ups instead.
**Brier: INDETERMINATE** (0 calls carried a probability). The scorecard starts this week.

| # | prior call (source) | check re-run now | result | did the action happen? |
|---|---|---|---|---|
| 1 | 10-21 §7-1: `bybit_2` xrp / ada `BELOW_BACKTEST` → attribute, do not demote | `live_vs_backtest.py` | xrp **still BELOW** (n=19, −11.98 R, pct **1.2**, was 2.2); ada → **CONSISTENT** (n=17, −4.33 R, pct 7.2) | **Yes.** PI-…-0001 done (cause: forming-bar decisions). DECISION-BAR-MATCH merged and deployed 10-22, and **OBSERVED today** (§2 Q1) |
| 2 | 10-21 §7-2: giveback is "structural and stable" at ~85–87% | `giveback_census.py` | **miss.** 90d 91% → 30d 107% → 7d 133%; deep-then-loss 12% (prior 60d) → 31% (30d), Fisher p=0.013 | no unit ran on it |
| 3 | 10-21 §7-3: TP doctrine 0/54 → fix real money first | `check_tp_doctrine.py` | 0/77 (real money 0/6) | **no.** Routings grew by 23 through the operator-approved DEMO-FLOOR roster PRs (#20561, #20551); nothing became compliant |
| 4 | 10-21 §7-4: MGC paper $ mis-sized / mis-valued (PI-20261021-4ZLRFEV1-0002) | rerun in the item | 6610/6603 still ESTIMATED; the new MGC trade 6740 is 1 contract, −398 ESTIMATED (−1.06 R) | **partial**: sizing looks sane on the one new trade; valuation is still ESTIMATED |
| 5 | 10-21 §7-5: diagnose the negative-R scalps (sol_5m / sol_15m / mgc_15m) | C1 | the family has nearly stopped signalling (§2 Q4), so there is nothing new to diagnose on | **no**, and superseded by Q4 |
| 6 | 10-21 §7-6: understand the positive `ict_scalp_avax_5m` | C1 | lifetime expR now −0.14 (n=82); **1 close in 30 d** | **no.** Folded into Q4 |
| 7 | 10-21 §7-8: `giveback_census.py` ignores `--since-days` on dump input (PI-…-0003) | `--since-days 7` on the 30d dump | still ignored (n_graded 76 = the 30d count) | **no.** Unowned (`dispatch_lane`, owner null); kept open |
| 8 | 10-10 rec (2): run the M8 tune sweep for ada / avax / sol pullback before any demotion (PI-20261010-WQAPZD8B-0004) | `paper_book_tracker.py` + `research/results` grep | no M8 artifact for avax / sol; tracker now **DECAY FLAG** | **no, for the third review running.** This is the failure Layer 0 exists to stop. Re-filed **with an owner** (`/perf-followup` Track 1), §3 D4 |
| 9 | 10-10 rec (1): real-money watchdog closes PI-…-WQAPZD8B-0001 | rerun in the item | 6549 / 6528 now read `sl`, MEASURED | done in effect: kept open only for the root-cause half (health) |

---

## 1. CHECKS (numbers only)

**C1. Per-leg scorecard.** `/api/bot/performance?window=all|30d|7d` `perStrategy[]` (no `90d` token exists, so the 90d
column comes from `giveback_census.py` over the telemetry-joined minority, `could_not_look: no 90d window on the
route`). Legs shown: n ≥ 10 lifetime, any 30 d activity, and every real-money leg. Cell = n / win% / ΣR / expR.

| class | leg | lifetime | 30d | 7d | pnl coverage |
|---|---|---|---|---|---|
| real_money | vwap (retired) | 318/24%/−145.85/−0.459 | — | — | 0.75 |
| real_money | ict_scalp_5m | 35/54%/+4.94/+0.141 | — | — | 0.91 |
| real_money | eth_pullback_2h | 19/26%/−2.47/−0.130 | — | — | 0.74 |
| real_money | **xrp_pullback_2h** | 19/16%/**−11.98/−0.631** | 5/0%/−4.65 | 2/0%/−2.06 | 0.68 |
| real_money | ada_pullback_2h | 17/24%/−4.33/−0.255 | 6/50%/+3.42 | 1/100%/+2.35 | 1.00 |
| real_money | trend_donchian_eth_4h | 16/31%/+6.20/+0.388 | 5/20%/−3.59 | 2/0%/−2.16 | 0.63 |
| real_money | trend_donchian | 15/40%/+7.64/+0.509 | — | — | 0.87 |
| real_money | trend_donchian_xrp_4h | 7/14%/−0.94 | 1/0%/−1.02 | — | 0.57 |
| real_money | trend_donchian_sol_prop | 3/0%/−2.92 | 3/0%/−2.92 | 2/0%/−2.02 | 1.00 |
| real_money | iaum_pullback_1d (`alpaca_live`) | 1/0%/−1.47 | — | — | 1.00 |
| paper | ada_pullback_2h | 49/39%/+4.86/+0.099 | 12/50%/+7.00 | 2/100%/+4.81 | 0.63 |
| paper | xrp_pullback_2h | 36/19%/−9.15/−0.254 | 11/18%/−4.15 | 4/0%/−3.86 | 0.50 |
| paper | trend_donchian_eth_4h | 31/39%/−5.86/−0.189 | 9/22%/−5.74 | 3/0%/−3.10 | 0.35 |
| paper | trend_donchian_sol_prop | 6/0%/−5.57 | 6/0%/−5.57 | 4/0%/−3.72 | 0.67 |
| paper | trend_donchian_eth_prop | 7/29%/−2.44 | 7/29%/−2.44 | 3/67%/+0.56 | 1.00 |
| paper | ict_scalp_xrp_5m | 44/50%/−33.75/−0.767 | 6/67%/+2.76 | 1/100%/+1.49 | 0.57 |
| paper | ict_scalp_avax_5m | 82/50%/−11.58/−0.141 | 1/0%/−1.00 | 1/0%/−1.00 | 0.65 |
| paper | ict_scalp_sol_5m | 61/52%/+9.78/+0.160 | — | — | 0.41 |
| paper | ict_scalp_mgc_15m | 22/9%/+8.24/+0.374 | 6/0%/−3.58 | 1/0%/−1.06 | **0.00** |
| paper | trend_donchian | 29/41%/+23.86/+0.823 | 2/50%/−0.66 | 1/0%/−0.93 | 0.48 |
| paper | pairs ×4 legs | 172–187 each, ΣR ≈ 0 | 37–48 each, ΣR ≈ 0 | — | 0.24–0.35 |

Class totals: real_money all 467 / −157.3 R / PF 0.59 · 30d 20 / −8.77 R · 7d 7 / −3.89 R. Paper all 1650 / −141.7 R
/ PF 0.97 · 30d 267 / −17.9 R / PF 0.21 · 7d 30 / −15.3 R / PF 0.20. ⚠️ `ict_scalp_mgc_15m` has **0% MEASURED pnl
coverage**: its $ is not graded (C8).

**C2. Expected vs realised** (`live_vs_backtest.py`, whole history per book, bootstrap p5–p95, seed 20261015):

| book | leg | n | live ΣR | band p5 … p95 | pct | verdict |
|---|---|--:|--:|---|--:|---|
| `bybit_2` real | xrp_pullback_2h | 19 | −11.98 | −8.36 … +13.93 | **1.2** | **BELOW_BACKTEST** |
| `bybit_2` mirror | xrp_pullback_2h | 15 | −8.14 | −7.70 … +12.26 | 4.1 | **BELOW_BACKTEST** |
| `bybit_2` real | trend_donchian_eth_4h | 16 | +6.20 | −9.04 … +20.96 | 60.5 | CONSISTENT |
| mirror | trend_donchian_eth_4h | 14 | −6.13 | −8.63 … +19.14 | 10.8 | CONSISTENT |
| real | trend_donchian_xrp_4h | 7 | −0.94 | −4.25 … +7.33 | 29.0 | CONSISTENT |
| real | ada_pullback_2h | 17 | −4.33 | −5.39 … +22.38 | 7.2 | CONSISTENT (was BELOW at n=15) |
| mirror | ada_pullback_2h | 11 | −1.38 | −6.38 … +16.43 | 19.5 | CONSISTENT |
| real / mirror | trend_donchian_sol_prop | 3 / 3 | −2.92 / −2.69 | −2.92 … +4.63 | 4.9 / 7.9 | INSUFFICIENT_N |
| `alpaca_live` real | iaum_pullback_1d | 1 | −1.47 | −1.01 … +3.48 | 0.0 | INSUFFICIENT_N (worse than every backtest trade; bt_n = 8) |

Comparisons: 12 book-legs. At p5, about 0.6 would land below by chance. Two did, and both are the **same decisions** on
two accounts, so they are not independent.

**C3. Decay (interim).** No sequential test exists yet (row `PERF-CHECKS-SCORECARD`). From C1: real-money 30d expR −0.44
against lifetime −0.34 (lifetime ex-`vwap` −0.08); paper 30d expR −0.07 against lifetime −0.09, but **7d −0.51**.
`as_traded_stage0.py` was not re-run this session. Its xrp result (MIXED, folds 3–4 at −0.04 / −0.86 R) is from
2026-10-22 and is cited, not re-measured.

**C4. Attribution.** `real_money_close_attribution.py`, over 486 real-money closes from 2026-05-09 to 2026-10-28; decision
set 467 (dropped 12 reduce legs and 7 reconciler pseudo-strategy). **Strategy exits 361 (77.3%) · not-strategy 106
(22.7%)** (`reconciler_filled` 71, `backfill_closed_pnl_recovery` 21, `operator_flatten_reconciled` 4,
`manual_closeall` 3, …). **All 7 real-money closes this week are `sl`, a strategy exit.** ⚠️ The script's own route
`/api/bot/db/table/trades` now answers **HTTP 401** (with or without the diag bearer). I ran the unmodified `analyse()`
over the diag-journal dump instead, which uses the same raw `exit_reason` column; that is the tooling finding in §3 D7.
`live_bt_trade_join.py` was not re-run (no new emit-trades corpus since 10-18).

**C5. Cost drift.** `realized_slippage.py pull` + `analyze` (4,230 fills, 90 d). Bybit perps real-money round trip
**0.66 bps** measured (95% CI −1.33 … +2.64) against the 3.0 bps the Stage-0 corpus assumes. Repricing at 0.66 bps:
**0 of 27 verdicts flip**. Alpaca, IBKR, prop and OANDA: `unmeasurable` (no real-money account with n ≥ 20 per side).

**C6. Baselines.**
- **Live review** (`live_review_grade.py --live --since 2026-10-21`): 124 reviews on 22 packages; 2 altering calls,
  **0 priced** (2 `no_trade_row`). **Hold vs close-at-review: n=8, mean dR −1.00, hit 0/8** (ESTIMATED; the close side
  carries no cost). Calibration hold/judgement: n=7, INDETERMINATE. Q1 (0.25 R vs 0.5 R policy): INDETERMINATE (0 discordant).
- **Desk** (`desk_grade.py --live`): 69 decisions (65 `no_trade`, 4 `propose_entry`); 1 priced, +2.42 R net, INDETERMINATE
  at n=1. System legs, same window and universe: **n=14, mean −1.52 R, CI [−3.23, +0.19]**. Gate: NOT_YET.
- **Role roll-up** (`claude_role_grade.py --live`): every class `insufficient_n` or `no_data`. Holds: 53 recorded, 8 graded.

**C7. TP doctrine** (`check_tp_doctrine.py`, re-run): 77 routings / 51 legs. real_money 6 (entry_tp FAIL 2, tp_revision
FAIL 5, **compliant 0**) · prop 6 (6, 6, **0**) · mirror 5 (2, 4, **0**) · paper 60 (30, 59, **0**).
TP-REACH-FLOOR: below_floor 11, reachable 9, unmeasured 28 of 48 declared-target routings. The baseline went from
54 → 77 lines; the +23 are the operator-approved DEMO-FLOOR roster PRs of 10-27, not new debt anyone accepted silently.

**C8. Data coverage** (`classify_paper_records.py`, journal shape, 30d, n=287): A gradeable **103 (36%)** · B artifact 7
· C reconstructable 9 · P pairs 168. pnl coverage (MEASURED share): real money 0.95 (30d) / 1.00 (7d); paper 0.90 / 0.83.
Telemetry R join: 25 of 39 closes in 7 d, 76 of 287 in 30 d.

**C9. Grading.** `check_grading_freshness.py`: fresh (max `reviewed_at` 03:51Z, 4,354 rows). Grade vs outcome, 90d, joined
to the journal (n=1,358): **A 10 (100% win) · B 366 (36.6%) · C 862 (44.3%) · D 120 (33.3%)**. **B < C: the
cohort inversion persists (`grade_drift`).** A is assigned only to TP-hit trades (n=10, all wins), which is an outcome
leak. `risk_management: unknown` on 447 of 448 rows since 09-27.

**C10. Research pipeline.** Latest research-ops record `20261028T1530Z`: floor 58; runnable TRADING 46 / MODEL 4 / INFRA 3;
7d graded TRADING pass 73 / fail 300 / indeterminate 29; `needs_review` 28. `research_disposition.py --unread-only`:
dispositioned 160 · **unread 0** · superseded_unread 294 · corpus_unreadable 0.

**C11. Books and benchmarks.**
- **Diversified paper book** (`paper_book_tracker.py`, snapshot appended): n=192, net +$305, WR 38%; **recent 30d n=19
  −$6,219 vs prior 173 +$6,524 → ⚠ DECAY FLAG**. Families: trend +$12,832, **pullback −$12,527**. Per cell: avax_pullback_2h
  n=8 −$5,530; xrp_pullback_2h n=23 −$5,387; sol_pullback_2h n=12 −$2,644; trend_donchian_ada_4h n=21 +$7,280.
- **Real-money allocation benchmark**: incumbent `bybit_2` lifetime ex-`vwap` expR ≈ −0.08 (149 closes); candidate
  sleeve: none queued. The Alpaca real book is one proxy leg with an empty mirror (Q7). Verdict `neutral`: nothing to
  benchmark against.
- **Prop trade quality** (`trade_quality_review.py`, `breakout_1`): 24 closed fills of 82; bridge median entry slip
  −0.2 bps, worst 98.5 bps; strategy: 11 at the stop, 1 at the target, 5 manual (4 in profit), 1 past the stop;
  net −$205 over 23, WR 21.7%. No rows near the tolerance boundary.

**C12. Backlog gate.** 69 open → **69 triaged, count_untriaged 0** (59 pipeline items each got a fresh `update` record
this run; 10 checklist rows are the manager's register and are listed for the manager, not edited). Details in
`backlog_drain[]` in the JSON.

`could_not_look`: 90d window on `/api/bot/performance` (no token); `/api/bot/db/table/trades` (401); a decision-bar
ledger route (`decision_bar_ledger` 404, so the closed-bar check used package `meta.entry_time`); M13 insights (not pulled
this run).

---

## 2. ANALYSIS

Ranking: real money first, then the size of the deviation from expectation, then mechanisms that touch several legs.
Seven questions.

### Q1 — Is `bybit_2` `xrp_pullback_2h` (BELOW_BACKTEST, pct 1.2) broken, or paying for an old fidelity gap? *(real money)*

- **Noise.** It predicts no structure in which trades lost. Twelve book-legs were compared, with about 0.6 expected
  below p5; xrp's real and mirror books share decisions. This hypothesis cannot be excluded on its own.
- **Fidelity (forming bar).** It predicts the live arm differs from the Stage-0 arm on entry. The 10-18 trade join
  established this (ENTRY gap, EXIT and EXECUTION ≈ 0); the as-traded bootstrap put xrp at pct 1.8 even on its forming arm.
- **Cost.** It predicts realised slippage above the 3 bps assumption. **Eliminated**: 0.66 bps measured, 0 flips (C5).
- **Regime.** It predicts the paper sibling and the other pullback legs sag together. Partly supported: the paper-book
  pullback family is −$12.5k against trend +$12.8k (C11).
- **Test run now.** Is the fix live? The 10-22 DECISION-BAR-MATCH change was merged and deployed but never observed. I
  read `order_packages.meta.entry_time` against `created_at` for every package on the three switched legs since
  10-20. **Before the switch** the bar was the forming bar: xrp 10-22T02:02 decided on `02:00`, eth_prop 10-22T08:19 on
  `08:00`, eth_prop 10-21T13:05 on `13:00`. **After it**, every package decided on the prior **closed** bar: xrp
  10-25T06:00:36 → `04:00` bar, ada 10-23T08:01 → `06:00`, ada 10-24T22:00 → `20:00`, eth_prop 10-23T23:00 → `22:00`,
  10-24T15:00 → `14:00`, 10-24T16:00 → `15:00`. As a control, `trend_donchian_eth_4h` was deliberately left on the
  forming bar, and its 10-24T15:09 package decided on `12:00`, the bar that was still forming. **The fix is OBSERVED.**
- **Survivor:** fidelity explains the pre-fix record (p 0.6); regime and noise share the rest. The 17 pre-switch trades
  were made by a different arm from the one that now trades. The live-vs-backtest verdict should be re-read on
  post-switch trades only.
- **Money:** real money is single-digit $. In R the leg loses −0.63 R per trade lifetime, at roughly 3 trades a week:
  about −8 R a month on real money and the same on the mirror and paper copies.

### Q2 — Exits are giving back more of the peak: regime, a change, or noise? *(all classes, several legs)*

- Measured on paper+mirror: share of peak given back is **91% (90d, n=351) → 107% (30d, n=73) → 133% (7d, n=24)**.
  Deep-then-loss (peak ≥ 1 R, closed ≤ 0) is **12% of 126 in the prior 60 d vs 31% of 32 in the last 30 d (Fisher
  p = 0.013)**. About four comparisons were looked at here, so this one survives a simple Bonferroni correction
  (0.013 × 4 ≈ 0.05), but only just.
- **Noise.** It predicts the 30d rate falls inside the 90d one. Weakened by the p-value.
- **Regime (two-sided chop).** It predicts losses on both directions in the same days and the same pattern on trend and
  pullback families. Supported by today's sequence (shorts stopped at 08:30, longs at 12:15, a short at 18:02), but
  this is one day.
- **A change to the exit path.** It predicts a break date. Candidates are the 10-22 bar switch (entries one bar later)
  and live-review touches. Untested: the live-review grader lists `touched_packages`, and applied calls were 0 priced,
  so touches cannot explain much.
- **Measurement.** It predicts coverage shifts. Telemetry joined 25 of 39 in 7 d (64%) against 76 of 287 in 30 d (26%).
  The 30d population is pairs-heavy (no telemetry), so the populations are not identical. Not eliminated.
- **Survivor:** regime plus an exit path that does not adapt to it (p 0.5); measurement (0.25); noise (0.25). This is
  the one structural question this week. It belongs to the exit-refinement programme as one unit, not N leg rows (§3 D2).

### Q3 — Is the diversified paper book decaying or just in a bad month?

- Tracker DECAY FLAG: recent 30d n=19 −$6,219. The 2026-YTD backtest of this cohort was flat (−1.7 R), so "flat is
  expected" (noise) is the prior. Pullback −$12.5k against trend +$12.8k lifetime, and the 10-10 tracker already showed
  the same split (−$10.2k vs +$7.3k).
- **Decay** predicts trend cells fail too. They do not: trend_donchian_ada_4h +$7.3k, xrp_4h +$5.9k. **Family-specific
  regime** predicts the pullback cells co-move, which they do (avax, sol, xrp, ada pullbacks all negative).
- The test the 10-10 review asked for, an M8 sweep per pullback leg, **never ran**. Survivor: family regime sag (p 0.55),
  not book decay. Money: paper only, but the same pullback family carries two real-money legs (Q1).

### Q4 — Why did the ict_scalp 5m family nearly stop trading?

- **Measured.** Closes: ict_scalp_5m Aug 44 / Sep 23 / **Oct 1**; avax_5m Aug 18 / Sep 53 / **Oct 1**; sol_5m Aug 23 /
  Sep 32 / **Oct 0**; xrp_5m Sep 17 / Oct 4. Packages: avax 86 in Sep vs 14 in Oct; sol 64 vs 2. All four legs read
  `enabled: true, execution: live` (`strategy_liveness.py`: LIVE). The evaluators run every bar
  (`ict_scalp_*_eval` in the audit tail, 14 each) and return "no qualifying FVG", "no sweep" or "no displacement".
- **Regime (fewer setups in October's structure)** predicts the backtest harness on the same October bars also finds
  few setups. **A live-side detector or parameter change near 10-01** predicts the harness on October bars finds
  September-like counts. A **data-feed problem** predicts eval rows with stale `bar_open_ts`; the tail shows current
  timestamps, which weakens this hypothesis.
- **Not settled in session.** The shallow clone hides `config/strategies.yaml` history before 10-26. Filed as a unit
  with the rule written first (§3 D3). Money: `ict_scalp_avax_5m` was the only measured positive leg at the 10-21 brief
  (+5.94 R/cap-day, W30). If it is stranded rather than idle, that is the largest silently missing P&L in the book.

### Q5 — Are the live reviewer's "hold" calls costing money?

- Measured: 8 graded holds, mean dR −1.00 against closing at the review mark, 0 of 8 better (ESTIMATED; the close side
  carries no cost, which understates holds by about one round trip, roughly 0.05–0.1 R, far less than 1 R).
- **Selection** predicts the graded holds are the ones that closed early, and stopped-out trades close earlier than
  trailing winners. Of 53 holds, only 8 are graded. **A real skill gap** predicts the gap persists as winners close.
- Survivor: selection (p 0.55). Not actionable at n=8. The rule reads at n ≥ 20 graded (§3 D5).

### Q6 — Does the per-decision grade carry information? (C9)

No. B wins 36.6% (n=366), C 44.3% (n=862) and D 33.3% (n=120), and A is outcome-leaked. That matches the 10-28
redesign's own measurement. This is not a new finding: the skill already demotes the rubric to a check.
PI-20261004-ZBHFJG6X-0004 (risk_management unknown, grade_drift) is **killed** as superseded by the redesign. The C9
check now carries the cohort table every week.

### Q7 — The Alpaca real-money book is one proxy leg with no mirror (PI-20261026-4A80398B-0002)

- `alpaca_live` roster: `[iaum_pullback_1d]`; `alpaca_portfolio`: `[]`. IAUM is a declared **affordability proxy for
  GLD**, and its primary is on no roster. The proxy carve-out therefore empties the mirror, and the Alpaca Gate-2
  demotion signal does not exist.
- Its Stage-0 evidence (`comms/strategy_evidence/iaum_pullback_1d.json`) is **n_oos = 8** over 4 folds, `fidelity:
  approximate`, with fold net R **+5.47 → +1.89 → +0.52 → −0.72**, falling monotonically. That is below the queue's
  own power floor (n_oos ≈ 49 at α 0.05, power 0.8, d 0.4). `check_roster_promotion_evidence.py` still passes it
  (12/12 pass), so the guard's bar and the power floor disagree. The live record is 1 trade at −1.47 R, worse than every
  backtest trade.
- (1) Live record and cost: n=1, Alpaca slippage unmeasurable (C5). (2) It no longer serves as a proxy: with GLD off
  every roster it is a standalone real-money leg standing on 8 OOS trades. (3) The empty mirror costs the demotion
  signal, so a degrading leg would be caught by nothing but this review. (4) Proposal (Tier 3, operator), §3 D6.
- Money: single-digit $ per trade. The risk is governance, not P&L.

### Surprises (A4)

1. **The ict_scalp 5m collapse (Q4)**: no prior review or row mentions it.
2. **Giveback worsened** when the last brief called it stable (Q2, prior call 2 was a miss).
3. **`/api/bot/db/table/trades` now returns 401.** Its caller's docstring says the route was verified unauthenticated
   on 2026-09-08. The real-money attribution check would have read `void` without the workaround.
4. **The prop roster guard passes a real-money leg on n_oos = 8** (Q7).
5. **Today's stops came from both sides**: longs and shorts on the same coins within hours. This is the strongest single
   piece of evidence for the chop hypothesis, and it is one day.
6. Checked and **not** surprising: no real-money close this week was a non-strategy exit (all 7 `sl`); no research
   result is unread; grading is fresh.

---

## 3. Decisions (ranked by money; each has a pre-registered check for the next review's Layer 0)

| id | call | p | money at stake | decision · tier | pre-registered check | ending |
|---|---|--:|---|---|---|---|
| **D1** | xrp_pullback_2h's live shortfall is mostly the pre-switch forming-bar arm; post-switch it trades inside its band | 0.55 | ~−8 R/month per book if wrong (≈3 trades/week × −0.63 R) | re-read on post-switch trades only; **no demote** · T1 | `live_vs_backtest.py --leg xrp_pullback_2h` restricted to closes whose package `created_at` ≥ 2026-10-22T11:51Z; **rule:** at n ≥ 10 post-switch closes on `bybit_2`, pct ≥ 5 → hit; pct < 5 → miss and file the regime/decay unit | pipeline **PI-20261028-PVRNY2JI-0001**; DECISION-BAR-MATCH observation is **met** (for the manager's register) |
| **D2** | the giveback rise is real and regime-linked: the 30d deep-then-loss rate stays ≥ 20% at n ≥ 40 deep trades | 0.5 | at 351 trades / 90 d, each +0.1 R of retained peak ≈ +12 R/month across books | one exit-refinement unit, split by regime cell and family · T1 (research) | `giveback_census.py` on a 30d `closed_at` filter; **rule:** deep_then_loss ≥ 0.20 with n_deep ≥ 40 → hit; < 0.15 → miss (noise) | pipeline **PI-20261028-PVRNY2JI-0002** → `/perf-followup` Track 2 / `exit-refinement` |
| **D3** | the ict_scalp 5m silence is market structure, not a live-side change: the harness on 2026-10-01…10-28 bars finds ≤ 2× live's package count | 0.5 | avax_5m alone was +7.3 R over 19 trades in W30 (10-21 brief); a stranded leg costs about that a month | queue unit, harness replay Sep vs Oct · T1 | `scripts/backtest_ict_scalp.py` for avax/sol/xrp/btc 5m with live params on Sep and Oct bars; **rule:** if harness Oct signals ≤ 2× live Oct packages → hit (market); > 3× → miss, and it becomes a health-review bug | pipeline **PI-20261028-PVRNY2JI-0003** |
| **D4** | the pullback family sag is regime, not overfit: an M8 walk-forward per leg (avax, sol, xrp, ada pullback) shows positive net R in ≥ 2 of 4 folds | 0.55 | paper −$12.5k lifetime; real money via xrp / ada | **run it this time**: owner `/perf-followup` Track 1 · T1 | M8 / `direction_walkforward.py` on `--emit-trades` per leg; **rule:** ≥ 2 of 4 folds net > 0 → regime (hit); ≤ 1 → overfit (miss, demotion diagnosis opens) | PI-20261010-WQAPZD8B-0004 re-filed **with owner** |
| **D5** | the hold-vs-close gap is selection: at n ≥ 20 graded holds the mean dR is > −0.25 R | 0.55 | the reviewer touches every open package | no action until n; then a REVIEWER-BRIEF amendment if missed · T1 | `live_review_grade.py --live --json` `hold_vs_close`; **rule:** n ≥ 20 and mean > −0.25 → hit; ≤ −0.5 → miss → `/perf-followup` Track 2 brief amendment | pipeline **PI-20261028-PVRNY2JI-0004** |
| **D6** | `iaum_pullback_1d` cannot clear the power floor on its own evidence | 0.7 | tiny $; governance | **Tier 3 proposal for the operator:** (a) re-evidence IAUM as a standalone leg at declared power (a data task, filed), and (b) until then **keep it as-is** (a removal is a roster decision the data does not yet force). The guard-vs-power-floor gap is a methodology row | `research_queue.py` admission for the IAUM re-evidence unit; **rule:** n_oos ≥ 49 and net R > 0 → keep; else propose roster removal with the diagnosis block | pipeline **PI-20261028-PVRNY2JI-0005**; PI-20261026-4A80398B-0002 → done (answered here) |
| **D7** | the real-money attribution check is `void` until its route is fixed | 0.9 | void check = blind on real-money close mechanics | Tier-1 tooling: point the script at the diag journal or restore auth on the route; health-review owns which | `python3 scripts/research/real_money_close_attribution.py` exits 0 unmodified | pipeline **PI-20261028-PVRNY2JI-0006** |
| D8 | TP doctrine: real money first (2 entry_tp, 5 tp_revision fails on 6 routings) | — | every real-money leg carries a non-compliant bracket | no new row: TP doctrine work is owned by its existing programme; reported here as the measure | `check_tp_doctrine.py` real_money compliant > 0 | measure only, `no action, because` the work has an owner (`tp-doctrine-guard` baseline) |

**Premortems.** D1: "we waited for post-switch n while xrp kept losing." The bound is n=10 at about 3 trades a week
(≈ 3.5 weeks); its check names a miss route. D4: "the sweep chose params that overfit the recent regime." The rule
grades folds, not one in-sample number. D6: "keeping IAUM let a degrading real-money leg run unwatched." The mirror gap
is stated to the operator, and the review reads it weekly until re-evidenced.

**Candidate follow-ups for the walk-through (not run here):** D1–D7 above, plus (a) a fan-out-aware rate: the 39 trades
this week were 25 decisions, and every per-trade rate overstates n (existing BL-20260911 row, kept open); (b) `ib_paper`
`mes_trend_long_1d` closed by `exchange_flat_reconciled` after a 17-day hold (PI-20261025-KERS1025-0001, health-owned,
open); (c) `giveback_census.py --since-days` (PI-20261021-4ZLRFEV1-0003, still unowned).

**Hand-off:** this review hands off to **`/perf-followup`**, which tests D2–D5 and the open hypotheses in Q2–Q4. It was
not run here.

---

## 4. Not done

- **M13 insights cross-check**: not pulled this run.
- **Blind-then-reveal grades**: not run (that needs fresh grader sessions; out of this lane's ceiling).
- **`as_traded_stage0.py` / `live_bt_trade_join.py`**: not re-run; no new emit-trades corpus since 10-18. The xrp fold
  result is cited from 10-22.
- **Sequential decay test (C3)**: no instrument (`PERF-CHECKS-SCORECARD`).
- **Config history behind Q4**: the clone is shallow before 10-26, so the "change near 10-01" hypothesis is untested
  in session. D3 tests it by replay instead.
- **Checklist rows (10 of the 69 backlog)** were triaged and reported to the manager, not edited (the register is the manager's).
