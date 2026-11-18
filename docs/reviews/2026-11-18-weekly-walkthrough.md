# Weekly walkthrough 2026-11-18

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH**. A section that another lane has not landed yet is simply absent. On a collision, the later lane merges `main` first.

<!-- PERF-REVIEW-PREP:START -->
# PERFORMANCE — /performance-review 2026-11-18: real money lost 6.6 R this week, and almost all of it came from `ml_entry` buying 3–5 correlated coins on the same bar three times and getting stopped out on all 13 trades

> Skill: `.claude/skills/performance-review/SKILL.md`, run in full: scoreboard, Layer 0, CHECKS C1–C13, ANALYSIS, decisions, backlog
> drain. **`/perf-followup` was not run.** It takes §3 as its input. Machine record: `comms/reviews/performance-review-20261118-190000.json`.
> Window: **7 d** = since the last review (2026-11-11T20Z), with 30 d and lifetime beside it.
>
> **Merged ≠ deployed ≠ observed.** Every trade figure is **OBSERVED** on the live read-only API (`/api/bot/performance` 24h/7d/30d/all,
> `/api/bot/trades/closed` 376 rows since 10-19, `/api/bot/positions` 22 open at 18:15Z, `/api/bot/performance/recent`) and the diag journal
> (`journal?table=trades`, 2 × 1000 rows, ids 5962–7961). Diag answered **directly** this week (last week it returned 401). Reads 2026-11-18
> 18:10–18:45Z. Config facts are **OBSERVED on repo `main`** at `e66d3b333`, not on the VM. **Public repo:** no balances; $ figures are P&L only.
> This PR changes one tooling script (`realized_slippage.py`, §1 C5). It changes no config.

## S. Scoreboard

| book | 7d | 30d | lifetime | source |
|---|---|---|---|---|
| **real money** (`bybit_2` + `alpaca_live`) | **−6.61 R** / 30 (expR −0.22, WR 36.7%) · $ −15.44 (cov 1.00) · PF 0.61 | −7.03 R / 59 (expR −0.12) · $ −23.05 (cov 1.00) · PF 0.71 | −158.7 R / 516 · $ −153.11 (cov 0.80) | `/api/bot/performance`, R basis `declaredInitial` (7d 30/30) |
| **mirror** (`*_portfolio`) | −3.91 R / 34 (expR −0.12) | −2.76 R / 63 | −36.3 R / 202 | same, `paperPortfolio` |
| **paper** (API `paper`, includes the mirrors) | **+35.85 R** / 128 (expR +0.28) · $ +56,206 (cov 0.91) | +18.15 R / 301 (expR +0.06) | −105.0 R / 1915 | same, `paper` |

**Real money this week, by leg** (journal, real-money closes since 11-11T20Z, n=29; perf 7d n=30):

| leg | closes | how they closed | $ | R (perf 7d) |
|---|---|---|---|---|
| `ml_entry` (`bybit_2`) | 24 (+1 at the window edge) | sl 13 · live_review_close 9 · tp 2 | −19.74 | **−6.63** |
| `ada_pullback_2h` | 1 | tp | +8.71 | +2.88 |
| `trend_donchian_sol_prop` | 1 (7714, today 16:12Z) | **live_review_close** at 73.27 (SL 72.57, entry 75.41) | −1.99 | −0.75 |
| `trend_donchian_xrp_4h` | 1 | sl | −0.66 | −1.00 |
| `trend_donchian_xrp_adx25` | 1 | sl (then removed from real money 11-17) | −1.42 | −1.00 |
| `ml_entry_eq_struct` (`alpaca_live`) | 1 (7615 USO) | max_hold | −0.34 | −0.11 |

Fees on those 29 closes: $3.18 (28 broker-measured, 1 estimated). Funding 0. **10 of 29 real-money closes were Claude live-review closes.**

**Would a sceptical quant believe each real-money leg has edge?** From the offline record, net of the full cost stack
(`comms/strategy_evidence/<leg>.json`), plus C13 DSR:

| leg (book) | record (net of cost, OOS) | DSR | sceptic's answer |
|---|---|---|---|
| `ml_entry` (`bybit_2`) | +0.037 R/trade, n=907 | not computed | **No.** Inside noise of zero (last week's CI [−0.04, +0.10]), and its trades are not independent (§2 Q1). |
| `ada_pullback_2h` | +0.40, n=67 | 0.254 | No. Small n. |
| `trend_donchian_sol_prop` | +0.093, n=538 | 0.332 | Plausible, not shown. |
| `trend_donchian_xrp_4h` | +0.076, n=46 | 0.023 | No. |
| `trend_donchian_eth_4h` (back on real money 11-17) | +0.229, n=135 | 0.286 | Plausible, not shown. |
| `ict_scalp_eth_15m` (real money 11-17) | **−0.038, n=76, verdict FAIL** | 0.026 | **No.** Promoted on its paper record by operator decision; the owed fidelity re-test is not filed (§3 D7). |
| `slv_trend_1h` (`alpaca_live`, 11-12) | +0.59, n=92, at 5 bps | 0.581 | No at this cost: Alpaca fills measure about 26 bps (§2 Q3). |
| `tlt_pullback_1h` (`alpaca_live`, 11-14) | +0.109, n=75, at 5 bps | **0.005** | No. No live iteration unit. |
| `tqqq_trend_long_1d` | +0.236, n=54 | 0.533 | No. Declared a mechanics probe. |
| `ml_entry_eq_struct` | +0.49, n=207 (record cites an Actions URL) | not computed | No. Unverifiable record, and the claim's size is itself the warning. |

None would convince a sceptic. They are on real money by operator decision, which is the operator's call. This review's job is to keep a
working demotion signal on each one. **This week the config-cut C2 works on every leg with committed rows** (9 of 10), but at n ≤ 4 post-config
closes no leg has a verdict yet (§1 C2).

---

## 0. Prior calls (Layer 0)

| # | call (p) | check re-run now | result | did the action happen? |
|---|---|---|---|---|
| F1 | no real-money leg has a valid C2 read; fix the ML rows + add a config cut (0.9) | `live_vs_backtest.py` (full-history clone) | 9 of 10 real-money legs now return a verdict computed on post-config closes against committed per-trade rows (`ml_entry` bands on bt_n=907). Only `ml_entry_eq_struct` is still NO_BACKTEST | **hit** (rule ≥4 of 6). Both fixes landed (config cut 11-12; ML rows committed) |
| F2 | `ml_entry` live R inside its band once it exists (0.75) | `--leg ml_entry` | cut @11-15T13:21Z: **INSUFFICIENT_N** n=4, +1.69 R, pct 75.6; uncut: CONSISTENT n=36, −1.63 R, pct 33.6 | **hit** (CONSISTENT/INSUFFICIENT_N). Caveat: all 4 post-cut closes were live-review closes (touched) |
| F3 | the paper $ loss was the 11-09 `alpaca_paper` sizing step (0.9) | journal risk $ per new `alpaca_paper` trade since 11-11T20Z | median **$1,625** over n=27 = 2.2× the $740 pre-reset median | **unresolved, in the gap the rule left** (hit ≥5×, miss <2×). Killed: the distribution is bimodal (9 of 27 ≥ $5,965), so paper $ stays unreadable; read paper in R |
| F4 | demo-floor family swap is regime/noise (0.6) | `paper_book_tracker.py` (appended) | book recent-30d **+$9,287** (n=37) | **unresolved** (resolves 12-02), on the hit side. Decay flag cleared after 3 snapshots |
| F5 | stop-less alpaca position class fixed by #24547 (0.7) | `/api/bot/positions` | 6 alpaca positions open, oldest opened 11-16, none past its stop | **hit** |
| F6 | `realized_slippage.py` leaks the bearer in argv (0.95) | grep + `tests/test_diag_token_not_printed.py` | fixed by `89cf721ff` (#24965, 11-11): curl config file, test passes | **hit**. PI-20261111-PREP1111-0002 closed this run |
| F7 | rubric grades carry no outcome information (0.9) | C9 table | B 36.6% (n=265) vs C 46.9% (n=456) | **hit** (C still beats B; the miss needs B > C at n ≥ 300) |

`review_followthrough.py --source performance-review --window-days 7`: cohort 9 filed in 7 d, 1 done, 0 killed, 8 open (11% closed ≤ 7 d);
backlog 27 open, 74% due, median age 23.5 d, 7 with no owner.
*Footer (housekeeping, not a health measure):* 7 calls · hit 5 · miss 0 · unresolved 2 · void 0 · Brier **INDETERMINATE** (5 resolved < 10).
Series: 10-28 n_resolved 1 · 11-04 1 · 11-11 2 · 11-18 5.

---

## 1. CHECKS (numbers only)

**C1 — per-leg scorecard** (`/api/bot/performance` `perStrategy`). Real money:

| leg | 7d n / R / $ | 30d n / R / $ | lifetime n / R / $ (cov) |
|---|---|---|---|
| `ml_entry` | 25 / **−6.63** / −19.74 | 36 / −1.63 / −9.90 | 36 / −1.63 / −9.90 (1.00) |
| `ada_pullback_2h` | 1 / +2.88 / +8.71 | 4 / +6.35 / +18.90 | 19 / −0.56 / −8.79 (1.00) |
| `trend_donchian_sol_prop` | 1 / −0.75 / −1.99 | 5 / −4.08 / −11.84 | 5 / −4.08 / −11.84 (1.00) |
| `trend_donchian_xrp_4h` | 1 / −1.00 / −0.66 | 3 / +0.40 / +1.39 | 10 / −0.54 / −6.73 (0.70) |
| `trend_donchian_xrp_adx25` | 1 / −1.00 / −1.42 | 1 / −1.00 | 1 / −1.00 (removed 11-17) |
| `ml_entry_eq_struct` | 1 / −0.11 / −0.34 | 1 | 1 |
| `trend_donchian_eth_4h` | 0 | 5 / −3.71 / −10.17 | 19 / +4.66 / +4.71 (0.68) |
| `xrp_pullback_2h` | 0 | 4 / −3.26 / −9.68 | 20 / −12.10 / −37.51 (0.70) |
| `ict_scalp_eth_15m`, `slv_trend_1h`, `tlt_pullback_1h`, `tqqq_trend_long_1d` | 0 | 0 | 0 real-money closes |

The API has no 90d window, so 90d per leg is `could_not_look`. Paper (48 legs with a 30d close). Best 30d R: `ada_pullback_2h` +11.03 (n=7),
`trend_donchian_eth_prop` +9.41 (10), `e4_oi_shock_1h` +6.74 (33), `slv_trend_1h` +5.74 (5), `claude_desk` +4.72 (11). Worst: `gld_pullback_1h`
−9.68 (1, last week's stop-less trade), `trend_donchian_sol_prop` −6.71 (8), `uso_trend_1h` −5.63 (2), `ml_entry_eq` −4.77 (6), `trend_donchian_eth_4h`
−3.27 (9).

**C2 — expected vs realised** (`live_vs_backtest.py`, default config cut, run on a **full-history** clone):

| leg | real money | mirror | cut at |
|---|---|---|---|
| `ml_entry` | INSUFFICIENT_N n=4 +1.69 R pct 75.6 | INSUFFICIENT_N n=4 pct 75.5 | 11-15T13:21Z |
| `trend_donchian_xrp_4h` | INSUFFICIENT_N n=2 +0.60 R pct 62.4 | same, pct 62.7 | 11-06T21:52Z |
| `ada_pullback_2h` | INSUFFICIENT_N n=1 +2.88 R pct 73.3 | same | 11-06T21:52Z |
| `trend_donchian_sol_prop` | INSUFFICIENT_N n=1 −0.75 R pct 49.7 | same, pct 50.4 | 11-06T21:52Z |
| `slv_trend_1h` | NO_LIVE_TRADES | **INSUFFICIENT_N n=1 +2.40 R pct 80.0** | 11-12T21:20Z |
| `trend_donchian_eth_4h`, `ict_scalp_eth_15m`, `tqqq_trend_long_1d`, `tlt_pullback_1h` | NO_LIVE_TRADES | NO_LIVE_TRADES | 11-13 … 11-17 |
| `ml_entry_eq_struct` | **NO_BACKTEST** (`source_run` is an Actions URL) | NO_BACKTEST | 11-17T08:09Z |

⚠️ **On the default shallow cloud checkout every leg reads `cut=unknown` and is banded on all its closes, pre-config included, with no warning**
(PI-20261118-PREP1118-0005). That shallow run printed `slv_trend_1h` mirror CONSISTENT n=9 pct 9.6 and `tlt_pullback_1h` mirror **BELOW_BACKTEST**
n=10 pct 5.0. Neither is a read of the config that trades now.

**C3 — decay (interim; no sequential instrument, row `PERF-CHECKS-SCORECARD`).** Real money expR 7d −0.22, 30d −0.12, lifetime −0.31. With n ≤ 4
post-config closes per leg, C3 has no band to compare against.

**C4 — attribution.** `real_money_close_attribution.py` still answers **401** on its own `/api/bot/db/table` route (`could_not_look` for the script).
From the journal instead (real-money closes since 11-11T20Z, n=29): **sl 15, live_review_close 10, tp 3, max_hold 1**; 0 reconciler, 0 operator
flatten, 0 watchdog. Strategy exits 19/29; **Claude in-trade closes 10/29** (9 `ml_entry`, 1 `trend_donchian_sol_prop`).

**C5 — cost drift** (`realized_slippage.py pull` 4448 fills → `analyze`, which now runs after this PR's fix; it had crashed for 3 weeks):

| account | class | round trip bps (CI95) | note |
|---|---|---|---|
| `bybit_2` | real money | **0.82** (−1.97, 3.44) | policy 3.0. No drift |
| `bybit_1` / `bybit_portfolio` | paper | 3.36 / 2.93 | |
| `alpaca_live` | real money | — (entry n=4 −38.6 bps, exit n=2 +93 bps) | below min n |
| `alpaca_paper` | paper | **26.1 (5.1, 52.7)**; exit_sl 34.5 bps, n=43 | policy 5.0 |
| `alpaca_portfolio` | paper | 33.9 (−0.8, 79.7) | policy 5.0 |
| `ib_paper` | paper | 17.6 (9.9, 25.2) | |

Repricing at the real-money mean flips no Stage-0 verdict (28 repriced, 30 not repriced: no per-trade rows, or venue unmeasurable).

**C6 — baselines.**
- **Live review** (`live_review_grade.py --live --since 11-11T20Z`): 155 reviews on 61 packages → 14 altering calls → **9 priced**, 5 could not price
  (no_trade_row 3, replay_mismatch 1, hold_replay_unresolved 1). **Close, applied: n=7, mean dR +0.35, worst −0.05, hit 0.86.** Recommended-only close:
  n=2, +0.29. Use rule `close`: 9 packages, per-package CI95 [+0.06, +0.61], **HOLD_SCOPE (n_packages 9 < 20)**. Applied alarm: net dR +2.44 over 7,
  no recommend-mode proposal. Replay fidelity: 2 match the realised path, 7 unvalidated. Q1 (0.25 R vs 0.5 R): INDETERMINATE (0 priced tightens).
  Hold calibration: hold/judgement NO_SKILL (n=66), hold/table NO_SKILL (n=11). ⚠️ `hold_vs_close` prints mean dR **91.47** (n=109) and two by-version
  hold means of 92.7 and 452.1: not R (PI-20261118-PREP1118-0006).
- **Desk** (`desk_grade.py --live --since 11-11T20Z`): 42 decisions (32 no_trade, 10 propose_entry). 10 priced: mean +0.05 R, CI95 [−0.72, +0.81];
  minus random −0.49 R; minus system −0.37 R; all **INDETERMINATE (n=10 < 30)**. `p_hit` calibration NO_SKILL. Gate NOT_YET.
- **Per role** (`claude_role_grade.py --live`): propose_entry vs random 21 of 27 graded (insufficient_n, ETA 11-21); no_trade counterfactual: declining the
  desk's best listed candidate was worth −0.38 R on average (21 independent; interval includes 0); in-trade close 14 graded, 13 packages (insufficient_n).

**C6b — LTR grade freshness** (`attention_watch.py` probe `ltr_grade`): **1 of 14 applied live-review closes ungraded > 24 h** (oldest
`pkg-bba44210885c4180`, closed 11-05 04:07Z). `live_review_counterfactual.py --live`: 790 reviews, 21 priced, 49 could_not_price (candles_start_after_review
30, replay_mismatch 11, no_trade_row 7, hold_replay_unresolved 1). Today's `trend_donchian_sol_prop` close (7714) is not priced yet. At the 18:15Z SOL
mark (≈ 74.2, ESTIMATED from the open `bybit_1` SOL position) holding would read about −0.41 R against the close's −0.75 R; that is a mark, not an outcome.

**C7 — TP doctrine** (re-run): 86 routings / 59 legs. Compliant: **real money 2/10** (`ml_entry`, `trend_donchian_eth_4h`), mirror 2/10, prop 4/6,
paper 4/60. Real-money failures: `trend_donchian_sol_prop` unreachable TP (6 R, reach 0.019) + tp_revision; the other 7 fail tp_revision. TP-REACH floor:
4 below, 9 reachable, 46 unmeasured of 59.

**C8 — data coverage** (`classify_paper_records.py`, 30d journal closes, n=373): A 279 (74.8%), B 19, C 75, P 0. B includes **17 orphan_or_flap**, which
are the repeated-entry rows (§2 Q4). `journalTrust`: read; `accountsKnownDivergent: ['bybit_2']`, `accountsUnrecorded: ['alpaca_live']`.

**C9 — grading.** Fresh: newest `reviewed_at` 2026-11-18T03:41Z, 0.6 d (limit 3 d), 4673 rows. Grade vs outcome (762 graded trades joined to the
journal dump, closed 09-20 → 11-17): A 2 (100%), **B 265 (36.6%)**, **C 456 (46.9%)**, D 39 (25.6%). `grade_drift` for the 5th review running.

**C10 — research pipeline** (`research_disposition.py --unread-only`): dispositioned 154, **unread 20** (last week 19), superseded_unread 298,
corpus_unreadable 0. All 20 are e35 results, 10-29 → 11-13: 19 accruing, 1 infeasible. Research-ops owns these.

**C11 — books.** Paper-book tracker (`bybit_1`, 1653 rows → cohort 221; **snapshot appended**): book **+$11,551**. Recent 30d n=37 **+$9,287**; prior
+$2,264. Δ since 11-11 +11 trades, +$8,686. **DECAY WATCH ok** (last three snapshots flagged). Families lifetime: trend +$17,155, pullback −$5,605.
Prop `breakout_1` (`trade_quality_review.py`): 24 closed fills, net −$205.11, WR 21.7%, unchanged. **Real-money allocation benchmark: not computable**
(`alpaca_live` has 1 close).

**C12 — backlog gate.** 27 open performance-review records (17 pipeline + 10 checklist). **count_untriaged 0.** 17 pipeline items re-checked and written
to the work store (`work.py`, events 16725–16758): **13 kept open** with this run's observation, **4 closed done** (PI-20261104-PREP1104-0004,
PI-20261111-PREP1111-0001, PI-20261111-PREP1111-0002, BL-20260913-EVERY-PROFITABLE-LEG…); PI-20261104-PREP1104-0001 is kept open, narrowed to
`ml_entry_eq_struct`. 10 checklist rows read; they are the manager's register. A correction note was added to all 17
(the first write carried a wrong session id).

**C13 — DSR probation** (`dsr_probation.py`): 10 production legs, 8 on probation. **Iteration orphans (NO LIVE UNIT): `tlt_pullback_1h` (DSR 0.005)**,
`ml_entry_eq_struct` (not computed, 2nd week). `ict_scalp_eth_15m` 0.026 and `trend_donchian_xrp_4h` 0.023 each have a unit.

---

## 2. ANALYSIS

I looked at 10 real-money legs and 48 paper legs. At 5%, about 3 will look unusual by chance.

### Q1 — Why did real money lose 6.6 R this week? *(real money; −6.61 R of the book's −6.61 R)*

`ml_entry` lost −6.63 R over 25 closes. Its closes came from **9 entry bars**. Three of those bars were same-direction **long baskets**: 11-11T20Z
(XRP/ETH/SOL), 11-12T08Z (SOL/XRP/ETH) and 11-14T16Z+20Z (BTC/ETH/ADA/XRP/SOL). **13 of 13 closed at the stop, for −$34.98**, about −11.7 R at the leg's
$2.98/R. The leg's other 12 closes made +$15.24 (2 TP, 9 live-review closes, 1 time exit).
- **H-noise** (a +0.037 R/trade leg has red weeks): per-trade SD is about 1 R. If the 25 closes were independent, −6.6 R is about −1.4 SD.
  **But they are not independent**: three coins on one bar are one decision taken three to five times. At about 9 independent decisions, a −6.6 R
  week is an ordinary outcome for this leg. **Survives.** `live_vs_backtest.py` puts the uncut n=36 at pct 33.6.
- **H-regime** (long crypto into a falling tape): it predicts that the basket losses are longs taken while the market fell, and that the shorts
  worked. Observed: all 13 stop-outs are longs; both TP bars (11-13T00Z) are shorts. **Consistent; not separable from noise at n=9 bars.**
- **H-execution / cost**: `bybit_2` slippage is 0.82 bps against 3.0 assumed (C5). 0 non-strategy exits. **Eliminated.**
- **The finding is the shape, not the week.** The backtest's 907 trades almost certainly share the same per-bar clustering. If so, the record's
  effective n is far below 907, its CI is wider than stated, and C2's i.i.d. band is too narrow. Nobody has measured it.

**p = 0.8** that `ml_entry`'s Stage-0 trades cluster 3+ per bar too, which would make its record's effective n well under 907. **Money:** at the
current rate (~100 real-money closes a month), one losing basket costs 3–5 R. Three of them cost about −11.7 R this week. → **D1, D3**.

### Q2 — Is `slv_trend_1h` on `alpaca_portfolio` below its backtest? *(dispatch item (a); real-money leg since 11-12)*

**Not on any read I can reproduce.** Post-config (cut 11-12T21:20Z): mirror **INSUFFICIENT_N, n=1, +2.40 R, pct 80.0** (trade 7190, a trailed-stop
win, +$4,216); real money **NO_LIVE_TRADES**. Uncut (all 9 mirror closes, mostly on the pre-promotion config): **CONSISTENT, pct 9.6**. The only
`BELOW_BACKTEST` in any run today is **`tlt_pullback_1h` mirror, uncut, n=10, pct 5.0**, from the shallow checkout (§1 C2). It sits on the line
directly below `slv_trend_1h` in that output. If that line is the source of (a), it is a pre-config read on a different leg.
- Real money has not traded SLV because every `alpaca_live` SLV package since 11-12 was a **short**, and `alpaca_live` is long only: `dry_cause:
  side_filter:long` (journal 7189, 7749–7777). That is by design (the mirror carries the shorts).
- **Step 0 decides:** INSUFFICIENT_N / CONSISTENT → keep accruing, **no tune, no demotion proposal.** If the manager holds a different source for
  BELOW_BACKTEST, send it and I will re-run it.
- What does threaten this leg is cost, not live P&L (Q3).

### Q3 — Do the Alpaca real-money legs survive their real cost? *(real money: 4 legs on `alpaca_live`)*

All four `alpaca_live` records (`slv_trend_1h`, `tlt_pullback_1h`, `tqqq_trend_long_1d`, `ml_entry_eq_struct`) were measured at **5 bps** round trip.
Alpaca fills measure **26.1 bps** (CI 5.1–52.7) on `alpaca_paper` and 33.9 bps on `alpaca_portfolio`. Stop exits cost the most (34.5 bps, n=43).
- **H-simulator** (paper fills are the broker's model, not the market): it predicts that `alpaca_live` fills come in near 5 bps. Real money has 4
  entries and 2 exits (entry −38.6 bps, exit +93 bps). That is too few to test, and the 2 exits do not support it. **Untested.**
- **H-real** (equity stop orders on 1h bars slip about 25–35 bps): on `slv_trend_1h`'s stop distance (about 1.7% on 11-18), an extra 21 bps is
  about 0.12 R per trade against a record of +0.59. On `tlt_pullback_1h` (stop about 2.4%, record +0.109) it is about 0.09 R, most of the edge.
- The repricing is mechanical once the per-trade rows are there. **It belongs in a unit, not in this session.** → **D2**.

**p = 0.5** that at 26 bps at least one of the four records goes to ≤ 0 net expectancy (`tlt_pullback_1h` the likeliest). **Money:** the account is
tiny in $. The risk is a real-money leg with no edge at its true cost.

### Q4 — Does the repeated-entry defect (PI-20261118-JFWRQYOV-0004) distort per-leg R? *(dispatch item (d))*

**No for R, yes for size and counts.**
- Every repeat row closes `exchange_flat_reconciled` about 7 minutes after it opens, with `exit_price` and `pnl` **NULL** (journal 7750–7774, 7712, 7780–7782).
  `/api/bot/performance?window=24h` has **no** `slv_trend_1h` or `qqq_pullback_1h` row, and `live_vs_backtest.py` reads the same route. The classifier
  buckets the rows **B / orphan_or_flap**. Per-leg R and C2 are **not** distorted. Tested by reading the route, not inferred.
- **The defect is wider than SLV and QQQ.** In 30 d there are **15 null-PnL close rows across 4 legs**: `slv_trend_1h` 11-18 ×7, `qqq_pullback_1h` 11-17 ×1 +
  11-18 ×3, `spy_pullback_1h` 11-16 ×3, `mgc_trend_1h` (ib_paper) 11-16 ×1.
- **What it does distort:** (1) **size**. The position that survives is a stub. SLV 7784 holds 6 shares (adopted by `reverse_reconciler`) against
  794 on the first attempt. QQQ 7783 holds 2 shares against 1182 and 735. So the leg's $ weight is about 1% of what it should be, and mirror-vs-live
  dollar comparisons break. (2) **Raw counts**: 15 of 376 30d close rows (4.0%) on `/trades/closed` are phantom.
- Real money was not hit this time: the matching `alpaca_live` SLV packages were dry by design (Q2). The order path is shared, so the next long would be.
  The measurement is written to PI-…-0004.

### Q5 — Tonight's book carries one macro bet into FOMC. Is that a portfolio finding? *(dispatch item (c))*

**Yes, for the paper books, not for real money.** At 18:15Z, 22 positions were open. **15 short** (crypto 9, metals SLV/MGC/GLD 3, equity SPY/QQQ/GDX 3)
and 3 **long bonds** (TLT ×2, IEF). Open stop-risk was $9.4k on the shorts and $20.1k on the longs, $18.0k of it the bond longs (paper $; R-normalised
risk is not computable from the route). Real money had **1** open position (`bybit_2` ADA short, $3 risk). The real-money version of this risk did
happen this week, but as Q1's same-bar baskets.
- It is not one bet throughout. Short gold and silver alongside long bonds is a mixed rates view. Shorts in crypto, equity and silver are one
  risk-off direction.
- No instrument measures how often ≥ N legs share one direction, or what that does to drawdown clustering. → **D4** (for `/perf-followup` Track 4).
  This adds **no gate**: it is a readout.

### Surprises (A4)

1. **10 of 29 real-money closes this week were Claude's in-trade closes.** So far they help: applied close mean dR +0.35 (n=7, per-package CI [+0.06,
   +0.61]). They also make the C2 read **touched**: all 4 post-cut `ml_entry` closes were live-review closes. → folded into D3.
2. **The shallow checkout makes `live_vs_backtest.py` lie quietly** (§1 C2). Found because `cut=unknown` appeared on every leg. → D5.
3. **`hold_vs_close` mean dR 91.47** (and 452.1 on one version): a non-R row inside an R mean. → D6.
4. **`ict_scalp_eth_15m` is on real money with a failing Stage-0 record** (−0.038 R/trade, n=76), promoted 11-17 by operator decision on its paper
   record. The owed fidelity re-test is not filed. → D7.
5. **`ml_entry_eq_struct` on `alpaca_live` executed 1 of 21 packages**: 20 `risk_refused sized_qty=0` with available $54.45 of a ~$194.6 balance. Its
   live record will not accrue. → D8 (health).
6. **Paper made +35.9 R this week** while real money lost 6.6 R. Not a contradiction: paper carries 48 legs with a 30d close. I checked whether the paper `ml_entry`
   behaved differently: paper `ml_entry` 7d is −5.58 R (n=31), the same sign and size as real money.

---

## 3. Decisions (ranked by money; each carries a pre-registered check)

| # | call (p) | decision · tier | pre-registered check | ending |
|---|---|---|---|---|
| **D1** | `ml_entry`'s real-money losses come from same-bar baskets; a per-bar same-direction cap would cut drawdown without cutting net R (0.6) | research unit on the 907-row record · T1 (any cap is a Tier-3 proposal) | rule registered before the run: cap k ∈ {1,2,3} PASSES iff net R ≥ uncapped AND max DD ≤ 0.8× uncapped, net of cost | **PI-20261118-PREP1118-0001** → `/perf-followup`; due 11-25 |
| **D2** | at the measured Alpaca cost ≥1 of the 4 `alpaca_live` records goes to ≤ 0 (0.5) | reprice at 26 / 53 bps · T1 → T3 proposal if it flips | each leg's net expectancy at 26 and 53 bps stated; ≤ 0 at 26 = demotion **proposal** with the diagnosis block | **PI-20261118-PREP1118-0003**; due 11-25 |
| **D3** | C2's band is too narrow for clustered legs, and it mixes touched with untouched (0.8) | tooling: block bootstrap by entry bar; print n_touched · T1 | `live_vs_backtest.py --leg ml_entry --json` prints `n_entry_bars` and `n_touched` | **PI-20261118-PREP1118-0004**; due 11-25 |
| **D4** | cross-book same-direction concentration predicts drawdown clustering (0.55) | `/perf-followup` Track 4 unit · T1, no gate | co-direction count per hour vs next-24h book R over ≥ 90 d of journal; rank correlation and CI reported | **PI-20261118-PREP1118-0002**; due 11-25 |
| **D5** | the shallow-clone fallback will produce a wrong verdict again (0.9) | tooling · T1 | on a shallow clone the script deepens history or prints a non-verdict, plus a test | **PI-20261118-PREP1118-0005** |
| **D6** | `hold_vs_close` has a denominator bug (0.85) | tooling · T1 | every hold mean `|dR| < 5`, bad rows named, plus a test | **PI-20261118-PREP1118-0006** |
| **D7** | the `ict_scalp_eth_15m` fidelity re-test owed by its promotion is not filed (0.8) | manager authors the unit · T1 | a queue unit for the per-trade live-bar check + fidelity re-test exists, rule registered first | **PI-20261118-PREP1118-0009** |
| **D8** | `ml_entry_eq_struct` cannot size on `alpaca_live` (0.9) | route to health · T2 | ≥ 50% of its packages execute over 7 d, or a recorded decision accepts the refusal rate | **PI-20261118-PREP1118-0008** (health-review) |
| **D9** | `tlt_pullback_1h` is an iteration orphan (0.95) | author an iteration unit · T1 | `dsr_probation.py` lists a live unit for it | **PI-20261118-PREP1118-0007** |
| — | `slv_trend_1h` BELOW_BACKTEST (dispatch (a)) | **no action, because** Step 0 reads INSUFFICIENT_N post-config / CONSISTENT uncut; no demotion proposal | re-run `--leg slv_trend_1h` on a full clone at n ≥ 5 post-config mirror closes | carried on D2 (cost) |
| — | repeated-entry defect (dispatch (d)) | **no action here, because** R is not distorted. The size/count distortion is written to the defect's own item | — | PI-20261118-JFWRQYOV-0004 (manager), observation added |

**No Tier-3 proposal this week.** Nothing settles a demotion: every real-money leg is INSUFFICIENT_N or NO_LIVE_TRADES post-config. D2 can produce
one. **Premortem on D1:** a cap could drop the one bar that wins (11-13T00Z made +$8.10 on two coins). The check therefore grades net R and DD together.

`/perf-followup` hand-off: D1, D2 and D4 are its Track 1 and Track 4 inputs. Q1's open hypothesis (Stage-0 clustering) is its first test.

## 4. Not done

- **R per capital-day and giveback** (`giveback_census.py`): not run this week, for time. Last week's figures are not carried forward.
- **Blind-then-reveal grades:** none this run (a reviewing session never writes blind grades).
- **M13 insights cross-check:** not run.
- **Order-package rubric grading:** not hand-run. The daily cron is fresh (C9).
- **`real_money_close_attribution.py`:** still 401 on its own route. C4 used the journal instead.
- **Claude-channel ping:** not sent by this lane. The manager is the reporting path tonight.

<!-- PERF-REVIEW-PREP:END -->
