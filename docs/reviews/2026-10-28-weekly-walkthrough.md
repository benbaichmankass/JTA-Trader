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

---

<!-- ML-FRONTIER-PREP:BEGIN -->
# MODEL track — /ml-review 2026-10-28 — the ML is learning, but nothing it learns reaches a real-money order; this week's ML research did not ask whether it could

> Lane `ML-FRONTIER-PREP-20261028` (Tier 1, read-only, Opus). Runs `.claude/skills/ml-review/SKILL.md` and
> `.claude/skills/frontier-research/SKILL.md` (both two-layer). **Nothing was promoted or queued, and no config, src or manifest was touched.** New units are
> **proposed** in § 3 (each labelled MODEL or TRADING), as the dispatch asked. Merged / deployed / observed are labelled throughout.
> Records: `comms/reviews/ml-review-20261028-200000.json` · `comms/ml-plan/20261028T2000Z-ML-FRONTIER-PREP.json`.
> Practice & methodology refresh: owned this week by the sibling lane `PRACTICE-REFRESH-20261028`, so this section does not repeat it.

**Headline numbers (MEASURED):**
- **ML changes 5 of 51 rostered legs, and 0 of 7 real-money legs.** I re-parsed `config/accounts.yaml`, `config/regime_policy.yaml::trend_vol` and the `exit_head_action` entries in `config/strategies.yaml` at `main@6e12741c9`. The 5 legs are: router cells on `trend_donchian`, `ict_scalp_5m` and `squeeze_breakout_4h`; exit-head `close` on `trend_donchian`, `trend_donchian_sol` and `trend_donchian_eth`. All 5 are on `bybit_1`, which matches ML-COVERAGE-AUDIT.
- **First broken hop of the learning chain: H6 promoted → H7 changes an order.** For the teacher and trade data, the chain breaks earlier, at H3 → H4 (C4).

**Trainer pulls:** #20968 (cycle, cost gate, builds; its 10 MB `list-models` dump crowded out the rest), #20982 (stage-guard, gate-check parity/labels/AUC, drift scan, audit) and #20991 (gate `ready`/`blocking`). Trainer HEAD `859215393`, timer active (next 2026-10-29 00:52Z), disk 52 %, 5.9 GB RAM, **1 vCPU**.

## 0 · Prior calls

- **Follow-through** (`review_followthrough.py`, window 7 d):
  - ml-review cohort: 4 filed, 0 done, 0 killed, 4 open.
  - ml-review backlog: 23 open, 48 % due, median age 24 d, 6 with no owner.
  - frontier cohort: 19 filed, 7 done, 12 open; backlog 24 open.
- **The last scan's kept calls** (`comms/ml-plan/20261018T0700Z.json` frontier block; ML-READ-1025 left no `calls[]`): 5 kept, 1 dropped.

| call (10-18) | unit | outcome | grade | why |
|---|---|---|---|---|
| yz vs advisory fc, identical folds | ff8f-01 | INDETERMINATE (`power_state: accruing`) | **miss** | underpowered by design: 5-fold macro-F1 |
| TabICL at full n | ff8f-02 | INDETERMINATE; the TabPFN arm was *unavailable* (CPU > 5,000-row limit) | **miss** | an arm was missing and the design could not reach power |
| calibrated linear head | ff8f-03 | FAIL (2 measured runs) | **hit** | informative |
| GRU over the feature window | ff8f-04 (+3 c0d* variants) | INDETERMINATE ×4 | **miss** | power was registered on 24,000 rows; the test was over 5 folds, which needed about 70 |
| TSFM bake-off | 9da8-01 | machine FAIL; lane: underpowered for the FAIL | **miss** | about 17 folds were needed; 5 were run |
| TabPFN arm (dropped, licence) | — | not tested | **unresolved** | — |

- **Score: 1 hit, 4 miss, 1 unresolved.** The Brier series is INDETERMINATE (fewer than 10 resolved calls).
- **What changes in this week's triage because of the grade:** gate 6 (power on the test unit) is now applied *before* a candidate is kept, not after it runs. § 2.2 shows the rule is metric-specific.

## 1 · CHECKS

| # | check | population | state | reading |
|---|---|---|---|---|
| C1 | trainer + registry | 97 registry rows (`/api/bot/ml/registry`, mirror age 118 s, ~18:55Z); last cycle | **ok** (one stage drift filed) | Timer active; the 10-28 cycle trained 66, refused 6 (all tracked), rc 0. One finished (complete_with_refusals) and one resumed at 08:22Z with 0 to run. No `manifest_oom_red_flag` in the 100-line cycle tail. Stage counts: advisory 3 · shadow 20 · candidate 73 · research_only 1, against a plan expectation of shadow 21 / candidate 72. That gap is one shadow→candidate move with no recorded decision, already filed (ML-F26 close note). `stage-guard`: every head `hold`; no demote proposed. |
| C2 | data + label freshness | 72 manifests; dataset families | **finding** | Builds: 98 ok / 0 failed / 2 skipped in 24 h. `TRAINING-STALENESS`: 5 stale, 2 never trained, 1 awaiting source (each tracked by a plan row). **Every `setup_candidates` dataset is frozen gross (2026-06..08) and has not been rebuilt since the cost-net label switch** (MEASURED by trainer #20864/#20865; rebuild = `PI-20261028-V8KBRR5H-0004`, due 11-06). Labels: gate-check `labels_accruing` is 0.92–0.99 on all 8 heads read (BTC/ETH 1h 0.98–0.99). **The 1h label wall of 10-18 is cleared.** |
| C3 | business-use map | 51 rostered legs, 7 real-money (re-parsed); 23 shadow/advisory models | **finding** | **5/51 legs; 0/7 real-money.** Of the 3 advisory heads, only the BTC 15m vol head reaches a router cell; **SOL-15m and MES-5m advisory change 0 legs.** Since 10-22, conviction carries `c_strat` only, with no learned input (ML-COVERAGE-AUDIT § 6, not re-measured). **The one model that closes trades, `exit-head-donchian-1h-v1` on 3 legs, is not in the registry** (0 of 97 rows), so neither stage-guard nor the new cost gate sees it. |
| C4 | learning chain H1→H7 | sources in ML-PROGRAMME § 7; since 10-21 | **finding** | H1 produced ✅ (desk, live-review rows and closes accrue). H2 labelled ✅ for synthetic and trade rows. H3 in a dataset ✅ (`claude_judgments`, 627 rows, built nightly). **H4 trained ❌ for teacher data: 0 manifests train on it.** H4 ✅ for market features (66 manifests trained 10-28). H5 scored ✅ (26 heads log live, 25 varying). **H6 promoted: no stage change since 10-11** except one unexplained shadow→candidate (filed). **H7: 5/51 legs.** |
| C5 | serve parity + soak | 23 shadow/advisory heads | **finding** | gate-check `live_parity` on 8 heads: 0 mismatches in every sample (24–50 rows sampled of 3,546–16,200). **But both yang-zhang heads serve `vol_bucket` dead on the live side** (`dead_live=['vol_bucket']` on btc-15m yz-v1 and btc-1h yz-v1), while fc/lgbm heads show none. This is the open audit defect `PI-20260927-3WM5HADW-0005`, now MEASURED live. The served multiclass score is still max-probability-shaped (BTC 5m mean 0.995): `PI-20260927-3WM5HADW-0004`, INFERRED. Soak: mechanical (`shadow_soak` 1 clean prediction; 10,721 on sol-5m), per OPERATING-PLAN § 2. |
| C6 | champion vs challenger + cost gate | the 9 cost-gated heads; shadow pairs | **finding** | See § 2.1. **The 9 `setup-candidates-metalabel-*` heads were all refused at 10:11Z** (`cost_gate_passed: 0`, enforced). The trainer dry-run on #20880 gave the reason as `eval_not_cost_net`: 376/376 eval rows unstamped. Confirmed on the trainer (#20968): `eval_not_cost_net: 376 of 376 eval rows … {'unstamped': 376}` ×5, 354/354 ×2, 324/324 ×2. On the 23 shadow/advisory heads, `cost_net` reads `insufficient_data: family has no net-R decision value yet`. Live regime discrimination AUC (advisory metric, not a gate): MES-5m 0.755 · BTC-15m fc-v2 0.721 · yz-v1 0.709 · SOL-15m 0.696 · fc-v1 0.651 · BTC-1h v2 0.600 · yz 0.590 · **ETH-1h 0.539 (below the 0.55 RG4 floor)**. Same-replay comparisons this window are the `ml_bakeoff` units (same folds and rows per unit, fixed-cost-free classification metric): no cross-unit comparison is reported as a result. |
| C7 | drift, split | advisory + the nearest shadow | **watch** | (a) KS/PSI from `/api/bot/shadow/drift`: BTC-15m fc-pcv-v2 *moderate* KS 0.129 (10-11 0.12; 10-21 *minor* 0.075). SOL-15m fc-pcv-v2 *moderate* KS 0.103 (10-21 *minor* 0.079). MES-5m *minor* KS 0.093. btc-15m yz-v1 *moderate* KS 0.139 / PSI 0.154. Plan-only drift scan (run in #20968, read in #20982): 23 rows in 3 h, **all `skip_no_drift`**, service Result=success. 0 drifted, 0 persistent, no `DRIFT-REMEDIATE` row. The timer stays retired (unit file absent). (b) Labelled decay: **could-not-look, no instrument** (`LIVE-DECAY-MONITOR` row). The MES margin series is in § 2.4. |
| C8 | concentration | registry; open plan items | **finding** | `MANIFEST-CONCENTRATION`: gbdt is 76/97. All 3 advisory heads share one target (`regime_label`). **This week's research: 50 ML units graded; 43 on `regime_label`, 7 on `direction_label`, 0 on a target any consumer prices** (§ 2.2). |
| C9 | research landed + backlog | 79 ML result records / 50 units, `generated_at` ≥ 10-21; 27 open ML pipeline rows | **finding** | Verdicts on the latest record per unit: 21 FAIL · 21 INDETERMINATE · 6 PASS · 2 producer_failed. All 6 PASSes are regime-head log-loss or feature lift (SOL 1h range-vol ×3, SOL 1h HGB/ExtraTrees, the weekly LightGBM-vs-prior monitor). Backlog: § 4. |

## 2 · ANALYSIS

**2.1 What the cost gate (#20869) means for the registry.**

What was merged, deployed and observed:
- #20869 was merged at 09:18Z as `a65ef0085`, and was deployed on the trainer (HEAD contains it, #20880).
- Observed: the 9 cost-gated heads wrote `cost_gate_*` metrics at 10:11Z, all refused.

Why they were refused (MEASURED, #20880 and the registry):
- The evaluation rows predate the `label_cost_basis` column. The `setup_candidates` datasets were built gross in June–August and never rebuilt.
- The refusal is therefore **about the data, not about the models**.

What it means for the registry:
1. **No entry-decision model can be promoted at all until the cost-net rebuild lands** (`PI-20261028-V8KBRR5H-0004`, routed to ML-PROGRAMME-PLAN, due 11-06). That was the point of the gate.
2. **The gate is `not_applicable` to all 23 shadow and advisory heads.** They are regime classifiers or execution-quality scorers with no value column. So **every head that can be promoted today faces no decision-value gate.** The cost gate closes the door on the models that could be priced, and leaves open the door for the ones that cannot. This is the stated gap in `cost_gate.py`'s docstring, and it now governs every pending stage decision.
3. **The numbers under the refusal say the setups lose; the meta-label does not rescue them.**
   - Take-all is −0.43 R/opp (BTC metalabel set, n=376) and −0.49 R/opp (p2pool, n=324).
   - `p2pool-v1`'s +0.041 R/opp (PSR 0.79) is on these unstamped rows: 42 taken, about +0.31 R per taken trade.
   - The full cost stack measured on #20880 (~0.34 R per synthetic BTC 1h trade) is the same size.
   - My preliminary called this the "cheapest real test". **Corrected:** it is probably ≈ 0 net (INFERRED, p ≈ 0.25 that it beats take-none after the rebuild).
4. **Rejected alternative:** relaxing the gate to accept `harness` or unstamped rows for the 9 heads. That would put gross evidence back into the promotion path that the operator closed this morning.

**2.2 The research question monoculture got worse, and half of it cannot answer its own question.**

- The 10-28 diagnosis counted 7 frontier units all on one regime classifier. This week the whole ML research stream ran **50 graded units, 43 on `regime_label` and 7 on `direction_label`**. Every model family tried (HGB, ExtraTrees, MLP, CatBoost, logit, larger and smaller LightGBM, GRU, TabICL, TSFM) was tried on the same target.
- **Pattern no single unit shows:** every arm either matches the shipped LightGBM or loses to it on log-loss. Logit, MLP and ExtraTrees FAIL at 1h, and HGB and CatBoost come back INDETERMINATE. The SOL 1h exceptions are feature lift.

Is it the learner, the test design or the target? Two competing hypotheses:
- **(i) The target is saturated.** The regime label is a 3-class volatility bucket, and LightGBM on these features already extracts what there is. Test: the weekly monitor shows LightGBM beating the class prior by about 0.10 log-loss with tight CIs (2a2e-11), while challengers move by ≤ 0.005. That fits saturation.
- **(ii) Noise.** Does not fit: the 1h FAILs are sign-consistent losses, not noise.

Power audit (pipeline item `PI-20261028-LFC7HPXG-0001`, routed to this review):
- The fold sd of the paired log-loss delta is MEASURED at about 0.003 (3947-22 and ed1c-29: CI half-width 0.0035–0.0042 over 5 folds).
- So a +0.005 bar at 5 folds is borderline powered (about 60 %), and a +0.002 bar (2a2e-10) needs about 19 folds.
- The macro-F1 bars (+0.005/+0.010) need 17–70 folds (9da8-01, ff8f-04).
- All **4 queued ML units and the blocked 7ee1-01 register power on OOS rows**, not on folds.

Conclusion: more learners on `regime_label` are low value per dollar. The open questions that change orders are trade management (Q-TM1/2), take/skip (Q-SEL1) and breadth onto real-money symbols (Q-REG1), and ML-PROGRAMME § 4.3 ranks them top-5. They have **0 units queued** (grep of `research/queue` for Q-TM/Q-SEL/Q-REG/TM-BENCH: 0 hits).

**2.3 Is it learning?** Yes, up to scoring:
- The nightly cycle trains 66 manifests at rc 0, builds are clean, and 25 heads score live with varying output.
- The breaks are structural, not mechanical:
  - (H4) the 627-row teacher corpus and the trade data train no head that can be promoted;
  - (H6) no stage has moved in 17 days;
  - (H7) the decision surfaces read one BTC vol head and one exit head that is outside the registry.
- **The first broken hop is H6→H7, for the reason in ML-COVERAGE-AUDIT § 3.** The plan aimed at BTC-15m depth and never had a breadth objective. Nothing is broken in the pipes.

**2.4 Drift and the MES advisory watch.**
- Score drift on the BTC and SOL advisory heads went from minor on 10-21 to moderate today. That is the first moderate read since 10-11 for SOL, so it is a **watch**, not persistent (persistent needs 2 consecutive weekly reads; the 10-21 read was minor).
- **MES** (`PI-20261004-AHCVAAF5-0001`, registered rule: margin < 4.0 pts for 3 consecutive cycles → open a `[refinement]` row):
  - The margin over `mes-regime-5m-baseline-v1` was 3.95, 3.91 and 3.84 on 10-23..25, then 4.04, 3.97 and 4.19 (registry runs).
  - **The rule fired on 10-25**, so the row is filed (§ 4).
  - Analysis: the 6-cycle mean is 3.98 with sd 0.12. The rule's 4.0 threshold sits in the noise of the series, so the rule measures noise, not decay.
  - The refinement row's hypothesis is therefore "no capability loss; replace the macro-F1 margin rule with the head's decision value on the legs it feeds". MES-5m feeds **0** legs (C3), which makes this a wiring-or-retire question, not a promotion question.

**2.5 Frontier scan (sources and triage).**

Sources:

| source | state | read |
|---|---|---|
| Hugging Face Hub | checked | model search for time-series and tabular models; papers search. **NX-AI/TiRex-2**: Apache-2.0 on the Hub card, 82.5 M parameters, updated 2026-10-07, arXiv 2607.01204. **ibm-granite TTM-r2**: Apache-2.0, 805 K parameters |
| arXiv | checked | via HF papers. 2606.27100 (*TSFMs for financial return forecasting*, abstract read): gains over random walk "small and sparse"; Diebold–Mariano rejects only 2 of 10 tasks. 2607.05291 (*RV forecasting with TSFMs vs econometric benchmarks*, abstract read): only TTM beats Log-HAR at every horizon, narrowly; a TTM+Log-HAR equal-weight average enters the MCS for 98–100 % of assets. 2607.10286 (*TradeLens*, abstract read): judge agentic trading by intelligence-to-profit conversion from traces. 2605.16895 (*The Alpha Illusion*, secondary listing): LLM-agent backtest alpha is not deployment evidence (contamination) |
| Lab releases | checked (secondary) | an aggregator dated 2026-10-23 lists Toto 2.0, TiRex-2, TimesFM-3 (research-only licence), t0-gamma and Timestral (USD 20 M revenue cap) as released May–Oct 2026. Only TiRex-2's licence was confirmed primary |
| Quant practitioner literature | checked, thin | no 2026 primary on crypto TSMOM net of funding, and no 2026 meta-labeling primary found. Perpetuals background only (He, Manela, Ross, von Wachter; SSRN 4301150) |
| GitHub / competitions | **could-not-look** (not run this week; required every other week) | named so that `FRONTIER-SCAN-COMPLETENESS` counts it |

Triage (six gates):

| candidate | family | gate result | kept? | p_pass | power |
|---|---|---|---|---|---|
| TTM-r2 + Log-HAR average as the vol input for a pooled crypto vol head (Q-REG1) | ts_foundation_model + econometric | passes all 6 (CPU, Apache-2.0, mirror-publishable; business = router cells on XRP/ADA/AVAX, which carry 4 of the 7 real-money legs) | **proposed** (§ 3, P3) | 0.25 | folds; needs ≥ 17 (measured sd) |
| TiRex-2 as a remaining-move feature for Q-TM1 | ts_foundation_model | gate 5: no consumer until Q-TM1 passes (the plan's earned-learner rule); the loader for non-Chronos TSFMs is missing (`PI-20261022-5AEVV1RL-0001`) | dropped this week | — | — |
| TradeLens-style intelligence-to-profit attribution of `claude_desk` decisions | method | passes; business = Q-TM4(a), whether the desk earns its decisions | **proposed** (P4, TRADING) | 0.5 informative | decisions; desk n accruing |
| further TabICL/TabPFN/GRU/learner variants on `regime_label` | various | gate 5 (no consumer reads the gain) + C8 (crowded cell) | **dropped** | — | — |
| conformal abstention / selective classification as a wrapper on Q-SEL1 take/skip | conformal_calibration | passes; cost gate applicable | **proposed** inside P1 | 0.3 | trades (5,063-trade ledger corpus: MDE ≈ 0.018 R at sd 0.45) |

## 3 · Decisions — proposed units and rows (none queued; each labelled)

Ranked by expected value per cost. Each carries `p` and a pre-registered check in the review JSON `calls[]`.

| # | track | proposal | why now | cost to a verdict | rejected alternative |
|---|---|---|---|---|---|
| **P1** | **MODEL** | **Q-SEL1, net:** a within-family take/skip head on the ledger corpus (5,063+ trades, cost-net R), against take-all / take-none / matched-random / the strategy's own confidence, with a conformal-abstention arm. Rule: S-OFFLINE plus beats take-all by ≥ +0.02 R/trade net. Power on trades: MDE ≈ 0.018 R | the only ML question the new cost gate can price; real-money legs are in the corpus | runner, about $3 | re-running the 9 metalabel heads on the rebuilt synthetic set alone (smaller n, synthetic) |
| **P2** | **MODEL** | **Q-TM1:** a GBDT action-value exit/tighten policy vs the incumbent on TM-BENCH v1 (6 money legs, 6 purged folds), registered exactly as ML-PROGRAMME § 4.3 drafts it | the plan's #1 by information per dollar; earned by A1's PASS; 0 units queued | runner, about $4 | another regime-head learner |
| **P3** | **MODEL → TRADING** | **Q-REG1 with a frontier arm:** a pooled crypto vol head for XRP/ADA/AVAX, with a Log-HAR control and a TTM-r2 + Log-HAR average arm (2607.05291). Rule: beats the per-symbol prior and HAR on log-loss by ≥ 0.005 over ≥ 20 walk-forward folds (measured sd 0.003), then the net-of-cost regime-cell walk-forward | puts the one proven signal in reach of 4 of the 7 real-money legs | runner, about $4; TTM is CPU-sized | a TiRex-2 or Chronos-2 arm (bigger, the 2607.05291 evidence favours TTM) |
| **P4** | **TRADING** | **Desk viability:** attribute each `claude_desk` decision's net R against the rule counterfactual (B0/B1), TradeLens-style. Rule: desk decision value > 0 net and ≥ B1, at n ≥ 150 decisions (DESK-19) | decides whether desk labels are teacher data (C4 H4) | Tier-1 script, about $3 | training on the 627 desk rows now (no evidence the teacher beats the incumbent) |
| **P5** | **MODEL** | **Price the regime heads and the exit head:** a decision-value column for the router cells (blocked vs allowed intents, net R) and for `exit-head-donchian-1h-v1` (closes vs hold-to-rule), so the cost gate stops reading `not_applicable` on every head that can change an order, and the exit head enters the registry | closes the gap § 2.1 names; required before any shadow→advisory call | build row, Sonnet, about $6 | promotion decisions on macro-F1 (the M6 anti-pattern) |
| **P6** | **MODEL** | **Pause new `regime_label`/`direction_label` learner variants** (research-ops intake) until P1–P3 have run; re-register or retire the 4 queued ML units (power on rows, not folds) | 43 of 50 units this week; power audit | $0 (a manager call) | letting the queue drain as is |

**Stages:** no promote and no demote. No head is gate-ready on a decision value. A head that changes nothing (SOL-15m, MES-5m advisory) is a wiring-or-retire question for the operator once P5 can price it.

**Gate packets (`ready`/`blocking`):** `stage-guard` (#20982) returns `hold` for every shadow and advisory head, so it proposes no stage change. The per-head `ready`/`blocking` reprint with `--datasets-root` was chased three times. #20982 had a summary-script error, #20991 a heredoc error, and #21005 was still **queued on the runner at publish time** (fired 20:19Z). So the packet flags are **could-not-look**, and no conclusion here depends on them: no promotion is argued. The nearest head, btc-15m yz-v1, is blocked anyway by the dead live `vol_bucket` (C5).

## 4 · Backlog drain and not done

**Population:** 27 open ML pipeline rows at the start of the run (`origin.ref` names ml-review, `routed_to` starts `ML`, or `what` starts `[ml]`/`[refinement]`). **All 27 triaged, so `count_untriaged` = 0.**

| disposition | n | items |
|---|---|---|
| resolved (done) | 5 | `PI-20261015-WNBZB5WN-0001` (holdouts evaluated again) · `PI-20261004-AHCVAAF5-0001` (MES rule fired → refinement row) · `PI-20261018-WH81NW96-0002` (1h labels 0.98) · `PI-20261021-WG8OPB7N-0002` (drift timer retired) · `PI-20260929-K85Q64SF-0005` (MES baselines demoted with a stated reason) |
| killed (superseded) | 2 | `MB-20260613-002` VPIN → Q-TM7 · `MB-20260705-FC-SLTP-GEOMETRY` → Q-TM9 |
| kept open, re-read this run | 19 | 16 re-dated with a fresh observation (`pipeline.py --redate`). The **MEASURED news**: yz `vol_bucket` dead live (`3WM5HADW-0005`); label provenance still unfixed (`MVBJLVJ3`, 0 grep hits); ETH-1h AUC 0.539 (`MB-20260627-003`); the drift endpoint now reads 5 archives but still has no covered-span field (`BL-…DRIFT-GATE…`). Plus `LFC7HPXG` (power audit done, re-register proposed), `PI-20260925-D9FNL9SC-0001` (live_parity now computes on 8 heads, 0 mismatches; its pass/fail status waits on #21005) and `PI-20261018-WH81NW96-0003` (yz blocked by `vol_bucket`; packet waits on #21005) |
| kept open, not due | 1 | `PI-20261022-5AEVV1RL-0001` (TSFM loaders, due 11-05) |

**Filed this run:**
- `PI-20261028-GNVUF1ES-0001`: the MES-5m `[refinement]` row (attempt 1/3: price it or retire it).
- `-0002`: the cost gate covers no promotable head; the exit head is outside the registry (P5).
- `-0003`: research monoculture and the P1–P6 decision for the manager.

**Raised to the manager (not re-filed):**
- `FRONTIER-LEVER-XSEC-RUNNER`: queued 17 d across ≥ 2 scans. Dispatch or kill; about $5 Sonnet to build the runner wrapper.
- `MB-20260618-XA-D2B` (c_reg conviction lens): 132 d, no owner. Schedule under ML-PROGRAMME-PLAN or kill.

**Not done:**
- GitHub and competitions sources (every other week; next week).
- C7(b) labelled decay (no instrument).
- Practice refresh (sibling lane).
- No send-ping. The manager relays the brief, and the lane's report goes to the manager.

<!-- ML-FRONTIER-PREP:END -->

<!-- PRACTICE-REFRESH:BEGIN -->
## TRADING + MODEL — weekly practice refresh (lane `PRACTICE-REFRESH-20261028`, session_01AFoLuJpe2bJTErX7QGAmaS)

Tier 1, read-only on production; nothing queued, no config changes. Full evidence:
[`docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md` § 10](../research/practice-review-trade-mgmt-and-ai-2026-10-28.md).
Canonical list revised in place: [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).

**TRADING:** 6 sources (2 read in full); **deltas:** T11 added (vol-scaled sizing helps tails everywhere, but Sharpe only for risk assets [S56]),
T12 added (no-trade buffer [S57]), T2 and T3 strengthened (crypto stop-loss momentum [S62]; funding is part of the exit's cost [S61]).
**Gaps filed:** `IB-PAPER-ETF-LEGS-NO-ROWS`, `SPLG-TICKER-DEAD`.

**MODEL:** 4 sources (abstract level); **deltas:** M11 added (measure an LLM decision's repeatability before grading its edge [S58, S59]),
M6 strengthened [S53], R3 tension noted [S63]. **Gaps filed:** none new; the exit-head registry gap (queued since 2026-09-08) is **escalated**.

### Demo-floor data generation — population: 57 rostered leg × floor cells, trades created 2026-10-21T19Z → 10-28T19Z (`/api/diag/journal`, 3 × 1000 rows paged)

| Account | Cells | Cells with ≥1 row | Fills | Rejected |
|---|---|---|---|---|
| bybit_1 | 31 | 19 | 20 | 7 |
| alpaca_paper | 15 | 1 | **0** | 3 |
| ib_paper | 11 | 2 | **1** | 14 |

- **Blocked:**
  - ib_paper spy, qqq and iwm `_trend_long_1d` plus tlt_pullback_1d: **no ib_paper row ever** (2026-07-21 onward), while the same legs journal on Alpaca. Row filed.
  - `splg_trend_long_1d`: **SPLG became SPYM on 2025-10-31**. Empty bars and a raise every tick, and no audit row. Row filed with the exact Tier-3 change.
  - `mgc_trend_1h`: 13/13 rejected (7 shadow, then 6 flip-suppressed by mgc_pullback_1d's short).
  - The bybit_1 margin refusals (`available_usd=0.00`, 10-20 and 10-27) have **cleared**: none since 10-27 18:07Z, and 7 entries on 10-28. The sizing basis stays open on `BYBIT1-SIZING-COLLATERAL-BASIS`.
- **Quiet by design:** the daily equity and futures legs, the 4h donchians and the chop-only legs. Every eval reason is "no setup / no breakout / regime not chop".
- `trend_donchian_1h` is retired by record but still listed on bybit_1, so it is quiet by retirement.

### Is it learning? — population: 97 registry rows (mirror, 72 s old) + 23 trainer dataset dirs + the shadow log 10-24→10-28

- **market_features:** the chain works end to end (52 models retrained in 7 d, 22 heads scoring, 3 advisory).
- **Trade-level families** (setup_candidates, conviction_meta, trade_outcomes): they retrain, but **0 score live**. `setup_candidates` retrains on a dataset **frozen since 08-04**.
- **Desk judgments:** in a dataset (627 rows), but no family trains on them.
- **LTR review rows:** `review_journal` = **0 rows**.
- **Exit heads:** they can close trades, but sit **outside the registry**, with their dataset frozen since 09-07.
- **Last trainer cycle:** trained 0 models (72 already done).

### Gaps for Thursday (proposals; 13 in § 10.7). Top of the list:

1. **TRADING:** ib_paper ETF legs silently produce no rows (filed, Tier 2).
2. **TRADING:** SPLG → SPYM (filed, Tier 3: operator yes/no).
3. **MODEL:** exit heads close trades from outside the registry, with a frozen dataset (escalated, M10).
4. **MODEL:** trade-level families never score, and `review_journal` is empty (M1/M10).
5. **TRADING:** a suppressed opposing intent leaves no outcome record; propose a virtual per-leg ledger (T12/R3).
6. **MODEL:** desk/LTR recommendations are never re-run for repeatability (M11).
7. **TRADING:** LTR in-trade triggers are R-denominated only, with no ATR twin arm (T4).
8. **BOTH:** health-review has no per-leg × floor liveness check, and a raising builder leaves no audit row (R6).
<!-- PRACTICE-REFRESH:END -->
