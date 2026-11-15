# Weekly walkthrough 2026-11-11

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH** (lane `PRACTICE-REFRESH-20261111`). A section that another lane has not landed yet is simply absent.
> On a collision, the later lane merges `main` first.

<!-- PERF-REVIEW-PREP:START -->
# PERFORMANCE — /performance-review 2026-11-11: none of the six real-money legs has a valid demotion signal, and `ml_entry`, which made 8 of this week's 11 real-money closes, is still one of them

> Skill: `.claude/skills/performance-review/SKILL.md` (on `main` at `9ae7cd9a5`), run in full: scoreboard, Layer 0, CHECKS C1–C13,
> ANALYSIS, decisions, backlog drain. **`/perf-followup` was not run.** Candidate follow-ups are listed in §3.
> Machine record: `comms/reviews/performance-review-20261111-200000.json`. Lookback: **30 days is the main window** (operator, 2026-11-02),
> with lifetime, 90d and 7d beside it.
>
> **Merged ≠ deployed ≠ observed.** Every trade figure here is **OBSERVED** on the live read-only API (`/api/bot/performance`,
> `/api/bot/trades/closed`, `/api/bot/order-packages`, `/api/bot/prop/fills`). Journal figures come from the diag routes
> (`journal?table=trades`, 3 × 1000 rows, ids 4072–7071, opened 2026-07-27 → 2026-11-11; `position_telemetry`, 812 rows). Those were
> pulled through `vm-diag-snapshot` **workflow_dispatch artifacts**, because direct diag answers 401 since the 11-11 token rotation. All reads
> were 2026-11-11 18:57–19:20Z. Config facts are **OBSERVED on repo `main`**, not on the VM. This PR changes no code and no config.
> **Public repo:** no balances. $ figures are P&L only.

## S. Scoreboard

| book | 7d | 30d | lifetime | source |
|---|---|---|---|---|
| **real money** (`bybit_2` + `alpaca_live`) | **+3.81 R** / 10 (expR +0.38) · $ +3.93 (cov 1.00) | **−2.57 R** / 31 (expR −0.08) · $ −13.78 (cov 1.00) · PF 0.70 | −152.1 R / 486 · $ −137.68 (cov 0.78) | `/api/bot/performance?window=7d/30d/all`, R basis `declaredInitial` |
| **mirror** (`*_portfolio`) | +3.94 R / 10 | +4.81 R / 34 | −32.6 R / 168 | same, `paperPortfolio` |
| **paper** (demo floor) | **−3.28 R** / 84 (expR −0.04) · $ −37,078 ⚠️ | −18.84 R / 232 (expR −0.08) | −144.2 R / 1786 | same, `paper` |

⚠️ **Paper $ cannot be compared across 2026-11-09.** That day `alpaca_paper` went through the operator-approved close-all + account-reset
sweep (#24547). Risk per new trade rose from $0–2,042 (median $740, 47 trade rows 09-11 → 11-09) to $1.7k–18.8k (6 trades since; 3 still open at about
$14.4k each). The two post-reset closes, 7005 `slv_trend_1h` (−$28,137) and 7011 `ml_entry_eq` (−$9,622), together exceed the whole
book's 7d $ loss. **Read paper in R** (§2 Q3).

**The operator's three measures:**

| measure | real money | paper (journal class, includes the mirror books) | source |
|---|---|---|---|
| **net R per capital-day** | 90d **+0.061** (n=30) · 30d **+0.051** (n=20) · 7d +0.396 (n=11) | 90d +0.065 (n=428) · 30d **+0.003** (n=119) · 7d +0.028 (n=49) | `giveback_census.py`, telemetry-joined subset, trades filtered by `closed_at` per window |
| **giveback** (share of peak R given back) | 90d 89% · 30d 96% · 7d 75% | 90d 92% → 30d **100.5%** → 7d 91% · deep-then-loss 30d 21.6% (n_deep 51) | same |
| **TP compliance** | **1 of 6** routings (`ml_entry`) | paper 4/61 · mirror 1/6 · prop 1/9 | `check_tp_doctrine.py`, re-run: 82 routings / 56 legs |

**Would a sceptical quant believe each real-money leg has edge?** The answer comes from the offline record, net of the full cost stack
(`comms/strategy_evidence/<leg>.json`), plus the C13 DSR:

| leg (book) | record (net of cost) | DSR | sceptic's answer |
|---|---|---|---|
| `ml_entry` (`bybit_2`) | +0.037 R/trade, n=907 held-out year; fixed-TP bootstrap CI [−0.042, +0.099] | not computed | **No, not yet.** The point estimate sits inside noise of zero. |
| `ada_pullback_2h` (`bybit_2`) | +0.40 R/trade, n=67 (11-06 config) | 0.254 | No. Small n, and DSR is far below 0.95. |
| `trend_donchian_xrp_4h` (`bybit_2`) | +0.076 R/trade, n=46 (11-06 config) | **0.023** | No. |
| `trend_donchian_sol_prop` (`bybit_2`) | +0.138 R/trade, n=380 | 0.332 | Plausible, not shown. |
| `tqqq_trend_long_1d` (`alpaca_live`) | +0.206 R/trade, n=120 over 17 y; `param_selection_provenance: not_established` | 0.533 | No. It is declared a mechanics probe, not an edge bet. |
| `ml_entry_eq_struct` (`alpaca_live`) | +0.49 R/trade, n=207; third read of its confirm window; slippage marked PROVISIONAL | not computed | **No.** The size of the claim is itself the warning. |

None of the six would convince a sceptic on its record. They are on real money by operator exception or holdout decision (11-06 / 11-08
commits), which is the operator's call. What this review can do is keep a working demotion signal on each one. **This week it has none** (§2 Q1).

**7-day closes by account** (`/api/bot/trades/closed`, `closedAt` ≥ 2026-11-04T19:00Z, n=97): `bybit_1` 60 (27 wins) · **`bybit_2` 11
(5 wins)** · `bybit_portfolio` 11, row for row like `bybit_2` · `alpaca_paper` 15 (4 wins) · `alpaca_live` / `alpaca_portfolio` 0 · prop books:
4 closed fills across `breakout_2`, `tradeify_1` and `velotrade_1` (`/api/bot/prop/fills`). **Real money by leg (7d):** `ml_entry` 8 (3 tp, 1 sl,
4 designed 24 h `max_hold`), `trend_donchian_xrp_4h` 1 (trailed-stop win), `trend_donchian_eth_4h` 1 (sl, its last close before it moved to the
demo floor), `trend_donchian_sol_prop` 1 (sl).

**What changed on the books this week** (commits on `main`): 11-06 **six real-money legs moved to the demo floor** (`112b4d764`,
PROD-LEGS-DSR-DECISION; `ml_entry` kept by operator exception). 11-06 **three re-promoted on new holdout configs**: `ada_pullback_2h`,
`trend_donchian_xrp_4h`, `trend_donchian_sol_prop` (`d8d60fa84`). 11-06 `tqqq_trend_long_1d` mechanics probe on `alpaca_live` (`60abd7bb2`).
11-08 `ml_entry_eq_struct` on `alpaca_live` (`909134c30`). 11-09 `ml_entry` on prop (`813e2df82` → narrowed `11df318cf` → `ba62a96f7`).
11-06 `structure_exit` off on 9 legs (`b378e38c6`).

---

## 0. Prior calls (Layer 0)

| # | call (p) | check re-run now | result | did the action happen? |
|---|---|---|---|---|
| E1 | `ml_entry` live R stays inside its Stage-0 band (0.8) | `live_vs_backtest.py --leg ml_entry` | **NO_BACKTEST** again. Two causes, not one: `source_run` is the path plus " (run <url>)", so the file check fails; and the file it names (`research/results/RQ-20261103-5e04-01/41823438321.jsonl`) is **one summary line**. No per-trade `net_r` rows are committed anywhere for the 907-trade population. | **void.** No: PI-20261104-PREP1104-0001 sat queued for 7 d. Scope now widened to `ml_entry_eq_struct`, roadmap `L-ML-LIVE` (§3 F1) |
| E2 | `close` stays HOLD_SCOPE until n_packages ≥ 20 (0.9) | `live_review_grade.py --live` | could not run (diag 401). From `comms/live_review/reviews.jsonl`: `close` was recommended on **13 distinct packages** lifetime (8 reviews since 11-04) | **unresolved** (13 < 20). Grader fix landed last week. PI-…-0003 (calibration and hold-vs-close still count reviews) is open |
| E3 | `trend_donchian_sol_prop` 0/4 is noise (0.7) | `live_vs_backtest.py` | INSUFFICIENT_N, n=**4** real money, −3.33 R, pct **10.0** | **unresolved** (needs n ≥ 5). The config changed 11-06, so the next close tests a different config (§2 Q1) |
| E4 | pullback-2h demo-floor sag is regime, not decay (0.6) | pullback cells on `bybit_1`, recent 30d | **+$3,100** over n=15 (ada +$4,489 n=3, eth +$316, sol +$696, avax −$282, xrp −$2,119) | **hit** by the rule as written (> $0 within 4 weeks), early and carried by one cell. The trend cells turned instead (§2 Q4) |
| E5 | giveback has stopped rising (0.55) | census, 30d `closed_at` filter | paper share **1.005** (n=119) | **hit** (≤ 1.05) |
| E6 | 6844/6845 is a labeller defect (0.8) | journal re-read | both rows now read `operator_flatten_reconciled` (`pre_mark_exit_reason: reconciler_filled`) | **unresolved**: the next flatten has not happened. The action happened **under another row**: `AUD-20261104-FLATTEN-LABEL` (`d74a17429`) plus invariant #23002. Noted on PI-…-0002 |
| E7 | C5 void until `realized_slippage.py analyze` tolerates rows without `net_r` (0.9) | `realized_slippage.py pull` + `analyze` | no commit to the script since 11-04, and `pull` now also fails at diag (401) | **unresolved**. Not fixed. It also prints the bearer on failure (§2 surprise 4) |

`review_followthrough.py --source performance-review --window-days 7`: cohort 10 filed in 7 d, 5 done, 0 killed, 5 open (50% closed ≤ 7 d);
backlog 32 open, 66% due, median age 19 d, 15 with no owner.
*Footer (housekeeping, not a health measure):* 7 calls · hit 2 · miss 0 · unresolved 4 · void 1 · Brier **INDETERMINATE** (2 resolved < 10).
Series: 10-28 n_resolved 1 · 11-04 1 · 11-11 2.

---

## 1. CHECKS (numbers only)

**C1 — per-leg scorecard** (`/api/bot/performance` `perStrategy`, R basis `declaredInitial`). Real money:

| leg | 7d n / R | 30d n / R | lifetime n / R / expR | status now |
|---|---|---|---|---|
| `ml_entry` | 7 / **+3.65** (8th close, 7048, landed at 19:00Z after the read) | 11 / **+5.00** | 11 / +5.00 / +0.455 | production (`bybit_2`), also on prop since 11-09 |
| `trend_donchian_xrp_4h` | 1 / +1.60 | 2 / +1.40 | 9 / +0.46 / +0.05 | re-promoted 11-06, new config |
| `ada_pullback_2h` | 0 | 3 / **+3.47** | 18 / −3.44 / −0.19 | re-promoted 11-06, new config |
| `trend_donchian_sol_prop` | 1 / −0.41 | 4 / −3.33 | 4 / −3.33 / −0.83 | re-promoted 11-06, new config |
| `trend_donchian_eth_4h` | 1 / −1.04 | 7 / **−5.85** | 19 / +4.66 / +0.25 | demo floor since 11-06 |
| `xrp_pullback_2h` | 0 | 4 / −3.26 | 20 / −12.10 / −0.61 | demo floor since 11-06 |
| `tqqq_trend_long_1d`, `ml_entry_eq_struct` (`alpaca_live`) | 0 | 0 | 0 | rostered 11-06 / 11-08 |

The API has no 90d window (valid: 24h, 30d, 7d, all), so 90d per leg is `could_not_look` there and is covered only by the census subset.
Paper (49 strategies with a 30d close). Best 30d R: `ada_pullback_2h` +8.13 (n=6), `ief_pullback_1d` +6.13 (3), `ml_entry` +6.10 (17),
`e4_oi_shock_1h` +5.38 (18), `claude_desk` +3.64 (6). Worst: `gld_pullback_1h` **−9.68 (one trade, §2 surprise 1)**,
`trend_donchian_eth_4h` −8.23 (12), `trend_donchian_sol_prop` −5.98 (7), `uso_trend_1h` −4.39 (1), `ict_scalp_mgc_15m` −3.58 (3;
$ −41,066, all ESTIMATED), `ict_scalp_xrp_15m` −3.04 (9).

**C2 — expected vs realised** (`live_vs_backtest.py`, Stage-2 legs, whole history per book):

| leg | real money | mirror | is the read valid? |
|---|---|---|---|
| `ml_entry` | **NO_BACKTEST** | NO_BACKTEST | no: there are no per-trade rows |
| `ml_entry_eq_struct` | **NO_BACKTEST** (`source_run` is an Actions URL) | NO_BACKTEST | no |
| `tqqq_trend_long_1d` | NO_LIVE_TRADES | NO_LIVE_TRADES | nothing to read yet |
| `trend_donchian_xrp_4h` | CONSISTENT n=9, +0.46 R, pct 50.0 | CONSISTENT n=6, pct 27.8 | **no**: 8 of 9 closes are on the pre-11-06 config; the band is the new one |
| `ada_pullback_2h` | CONSISTENT n=18, −3.44 R, pct 10.8 | CONSISTENT n=12, pct 21.6 | **no**: 18 of 18 pre-change |
| `trend_donchian_sol_prop` | INSUFFICIENT_N n=4, pct 10.0 | INSUFFICIENT_N n=4, pct 12.8 | **no**: 4 of 4 pre-change |

**C3 — decay (interim; no sequential instrument, row `PERF-CHECKS-SCORECARD`).** Real money 30d expR −0.08 vs 7d +0.38. Paper expR 7d −0.04,
30d −0.08, lifetime −0.08: flat. With C2 invalid on every real-money leg, C3 has no band to compare against this week.

**C4 — attribution** (`real_money_close_attribution.analyse()` unmodified over the diag dump; its own `/api/bot/db/table` route still 401s).
Population: 108 real-money closes 2026-07-27 → 11-11 that join to the dump (of 506 on the wire). Decision set 101 (7 reduce legs dropped):
**strategy exits 87.1%** (sl 65, tp 16, exit_head 3, stale_stop 2, sl_cross 1, tp_cross 1). **Not strategy exits 6.9%**
(operator_flatten_reconciled 4, reconciler_filled 2, netting_attributed 1). Unknown 5.9%: all 6 are `max_hold`, `ml_entry`'s designed 24 h time
stop, which the script's map does not know. **7d: 7 strategy exits + 4 `max_hold`, 0 non-strategy exits** (last week 1).

**C5 — cost drift: `could_not_look`.** `realized_slippage.py pull` fails at its diag step (401), and the `analyze` fix (E7) has not landed.

**C6 — baselines.**
- **Live review: `could_not_look`.** `live_review_grade.py --live` calls diag directly and has no relay fallback (401). Read from the record
  instead: 635 reviews lifetime, 247 since 11-04 (hold 215, tighten_sl 12, flag_mechanics 9, close 8).
- **Desk** (`desk_grade.py --live --since 2026-11-04T19:00Z`): 27 decisions (21 no_trade, 6 propose_entry). 4 priced: mean **+0.90 R**, CI95
  [−0.75, +2.54]; desk minus random +0.23 R; **INDETERMINATE (n=4 < 30)**. The system leg is `could_not_look` (diag). Promotion gate NOT_YET.
- **Per role** (`claude_role_grade.py --live`): `propose_entry` vs random 11 graded of 17 (insufficient_n, earliest ETA 11-26). `no_trade`
  counterfactual +0.09 R (n=14 independent < 20). The in-trade row is `could_not_look` (diag).

**C7 — TP doctrine** (re-run): 82 routings / 56 legs. Compliant: real money **1/6** (`ml_entry`), mirror 1/6, prop 1/9, paper 4/61. Real-money
failures: `trend_donchian_sol_prop` has an unreachable TP (6 R, reached 1.9% of the time) plus `tp_revision`. `ada_pullback_2h` (reach 0.241),
`trend_donchian_xrp_4h` (0.158), `tqqq_trend_long_1d` and `ml_entry_eq_struct` fail `tp_revision`. TP-REACH floor: 4 below, 5 reachable,
41 unmeasured of 50 declared targets.

**C8 — data coverage** (`classify_paper_records.py`, 30d journal rows, n=266): gradeable A 183 (68.8%), artifact B 5, reconstructable C 37, pairs
P 41. `journalTrust`: read, `accountsKnownDivergent: ['bybit_2']`, `accountsUnrecorded: ['alpaca_live']`, 0 unreadable.

**C9 — grading.** Fresh: newest `reviewed_at` 2026-11-11T03:41Z, 0.6 d (limit 3 d), 4510 rows. Grade vs outcome (90d, 1433 trades graded and
joined to the dump): A 10 (100% win, outcome-leaked), B 420 (**37.4%**), C 875 (**44.3%**), D 128 (32.0%). **`grade_drift` for the 4th review
running**: C beats B.

**C10 — research pipeline** (`research_disposition.py --unread-only`): dispositioned 154, **unread 19** (last week 17), superseded_unread 298,
corpus_unreadable 0. All 19 are e35 results, 2026-10-29 → 11-11: 18 `accruing`, 1 `infeasible` (`trend_donchian_eth_4h`). This belongs to
research-ops.

**C11 — books.** Paper-book tracker (`bybit_1`, 1580 rows → cohort 210; snapshot appended): book **+$2,865**. Recent 30d n=29, **−$3,398**; prior
+$6,263. **DECAY FLAG, third snapshot running.** Families lifetime: trend +$10,567, pullback −$7,702. Recent 30d: trend −$6,498 (n=14), pullback
+$3,100 (n=15). Prop `breakout_1` (`trade_quality_review.py`): 24 closed fills, net −$205.11, win rate 21.7%. 11 exited at the stop, 5 have no ticket
link, 1 exited past the stop. Static since last week. Real-money allocation benchmark: **not computable**. The candidate `alpaca_live` legs have
0 closes.

**C12 — backlog gate.** 32 open performance-review items. **count_untriaged 0.** 23 pipeline items re-checked and written to the work store
(`work.py`, events 9711–9751): 19 kept open with this run's observation, 3 dropped as superseded, 1 done. 9 checklist rows were read; they are the
manager's register, not this lane's. Strategy-refinement queue: 2 open SRQ items, each with a drain note appended.

**C13 — DSR probation** (`dsr_probation.py`): 6 production legs. On probation (DSR ≤ 0.95): `trend_donchian_xrp_4h` 0.023, `ada_pullback_2h`
0.254, `trend_donchian_sol_prop` 0.332, `tqqq_trend_long_1d` 0.533, each with a live unit. `not_computed` (`could_not_look`): `ml_entry`,
`ml_entry_eq_struct`, the latter with **NO LIVE UNIT**.

---

## 2. ANALYSIS

I looked at 6 real-money legs and about 49 paper legs. At 5%, about 2–3 will look unusual by chance.

### Q1 — Can the review tell when a real-money leg stops working? *(real money, all six legs)*

**No, for any of them, this week.** This is a cross-leg finding (A5), not six leg findings.
- `ml_entry` and `ml_entry_eq_struct`: NO_BACKTEST. Their evidence records point at a summary line or an Actions URL, not at per-trade rows.
  `tqqq_trend_long_1d`'s record, built by `build_strategy_evidence.py`, does commit per-trade rows
  (`comms/strategy_evidence/runs/2026-11-06/…__trades.jsonl`). So the gap belongs to the ML harnesses, not the evidence format.
- `ada_pullback_2h`, `trend_donchian_xrp_4h`, `trend_donchian_sol_prop`: the 11-06 re-promotion changed their parameters (e.g. xrp_4h
  `atr_stop_mult` 2.0 → 1.5, `trail_mult` 5.0 → 4.0), and their evidence records were rebuilt at 19:2xZ that day. `live_vs_backtest.py` has no
  date cut, so it bands **31 real-money closes, 30 of them on the old config**, against the new config's distribution. "CONSISTENT" there is a
  statement about a strategy that no longer trades.
- **H-noise** (nothing is wrong; the signals will fill in): it predicts that the reads become valid as trades accrue. Untrue for the ML legs:
  no number of live trades creates backtest rows. Partly true for the three re-promoted legs. **Eliminated** for the ML legs.
- **H-measurement:** **tested and confirmed** for both mechanisms, by reading the records and the commit diff.

**p = 0.9** that without both fixes the next demotion-worthy decay on real money goes unseen by this review. **Money:** all real-money R. At
current rates (about 36 `ml_entry` closes a month plus about 5 on the three re-promoted legs) and the records' expectancies, the expected drift
is about +1–2 R a month. The risk is a silent decay, not this week's number. → **F1**.

### Q2 — `ml_entry` is +5.0 R over 11 real-money closes (expR +0.45) against a record of +0.037. Edge showing, or luck? *(real money)*

- **H-noise:** the record's exits are sl 523 / tp 180 / time 204, so per-trade SD is about 1 R. At n=11 the SE is about 0.3, so +0.45 sits
  about 1.4 SE above +0.037. **And the trades are not independent.** Three ADA/ETH/SOL shorts opened on 11-08 (12:02Z and 20:01Z) and all
  hit TP between 21:47 and 21:54Z, in one market move. Those three (6966, 6969, 6971) made **+$11.31 of `ml_entry`'s
  real-money $** (journal `pnl`, measured). The leg's 30d real-money total is +$9.79, so **without that one move the leg is about flat to
  negative.** **Survives**, and it is the default.
- **H-regime (short-side tailwind):** it predicts a long/short split that follows the market's direction. 9 of 12 real-money decisions were
  short; all 3 longs closed negative (journal sign). Consistent, but n=3 longs is no test. **Untested beyond that.**
- **H-measurement:** per-trade R computed from journal `stop_loss` is contaminated by stops moved after entry. Trade 6966 reads 6.14 R on the
  journal stop; the API's declared-initial basis puts the 7d total at +3.65 R, not the +6.46 R the journal stops give. **Confirmed: quote only the
  API's R.**

**p = 0.75** that `ml_entry` lands inside its band once the band exists. **Money:** expected about +1.3 R a month at the recorded expectancy. The live
run-rate (+15 R a month) is not an expectation and should not be planned on. → **F2** (E1 carried forward).

### Q3 — Paper lost $37k in 7 days at −3.3 R. What happened? *(paper; affects every $-denominated read)*

- **H-strategy:** it predicts losses spread across legs in R. Paper 7d is −3.28 R over 84 (expR −0.04): ordinary.
- **H-sizing step:** it predicts a jump in risk $ at a date, independent of the strategy. **Tested:** `alpaca_paper` risk per trade, journal rows,
  before vs after the 11-09 reset (#24547, "close-all + account_reset sweep", operator popup "Small Tier-2 code fix now"). Before: $0–2,042, median $740, n=47 (09-11 → 11-09).
  After: $1,698–18,784, n=6. The two post-reset closes are −$37,759 together, against the book's −$37,078 for the week. **Survives.**
- **H-mechanics:** one trade, 5209 `gld_pullback_1h`, is −9.68 R on its own (§ surprise 1). Without it, paper 7d is **+6.40 R**.

**Conclusion, p = 0.9:** the week's paper $ is a sizing-regime step plus one mechanics failure, not strategy performance. Paper is never a decision
surface, so no action. Any $-denominated paper or portfolio read that spans 11-09 is invalid, so `/perf-followup`'s portfolio track should work
in R. → **F3**.

### Q4 — On the demo floor the families swapped. Decay or regime? *(paper, third DECAY FLAG)*

Last week the pullback cells were the book's drag (−$11,725 lifetime) and the trend cells carried it. This week, recent 30d: pullback **+$3,100**
(n=15) and trend **−$6,498** (n=14; `trend_donchian_eth_4h` −$4,553 over 5). The book is still +$2,865 lifetime.
- **H-decay (family-level):** it predicts the losing family keeps losing. **Contradicted**: pullback turned within a week.
- **H-regime / complementary families** (the backtest's design: trend wants low-to-moderate ADX, pullback wants high ADX): it predicts the families
  alternate. **Consistent.**
- **H-noise:** the 2026-YTD backtest of this book was flat (−1.7 R). A flat-edge book shows a recent-window flag often.

**p = 0.6** regime/noise over decay. → **F4**. E4 resolved hit. The DECAY FLAG fires on any red 30-day window over ≥ 10 trades. Three in a row on a
book that is up lifetime says more about the flag's sensitivity than about decay.

### Surprises (A4)

1. **A paper GLD long sat 72 days past its stop.** Trade 5209 (`alpaca_paper`, opened 2026-08-29, entry 419.51, stop 416.09) closed 11-09 at
   376.26 (−9.68 R), only because the 11-09 close-all sweep caught it. Root cause, per the #24547 commit: the take-profit reprice PATCH was
   accepted and ignored by Alpaca, and the escalation rung never ran. **Fixed by #24547 (merged 11-09); deployed not established by this lane.**
   It is health's to verify. On `alpaca_live` the same path is one red flag, never a close-all.
2. **The `alpaca_paper` sizing step** (Q3).
3. **E6's action happened under another row** (`AUD-20261104-FLATTEN-LABEL`), so the pipeline item looked idle when it was not. I recorded this
   on the item.
4. **A credential printed in a traceback.** On failure, `realized_slippage.py` prints its curl argv, bearer header included. This session saw the
   pre-rotation token, which is dead. The same failure on a GitHub runner would print a live token into a public Actions log. Filed to health
   (PI-20261111-PREP1111-0002). The value is not repeated anywhere.
5. **Two new real-money legs have emitted no order package on any book** since they were rostered. Positive control: `ml_entry_eq` and
   `slv_trend_1h` packages show on the same route. Expected, so not a finding yet: `tqqq_trend_long_1d` trades about once in 52 days (P(≥ 1 in
   5 d) ≈ 9%), and `ml_entry_eq_struct` about 13 times a month (P(0 in its first ~2 trading days) ≈ 0.3). It becomes a finding if
   `ml_entry_eq_struct` is still at 0 packages by 11-18 (P ≈ 0.01 if it runs at its rate).
6. **The issue-relay path returned curl exit 7 on every path once** (#24904), then worked a minute later (#24907). One transient. Not filed.

---

## 3. Decisions (ranked by money; each carries a pre-registered check)

| id | call | p | decision · tier | pre-registered check (`command` · rule · resolves_when) | ending (owner · due · roadmap) |
|---|---|---|---|---|---|
| **F1** | No real-money leg has a valid C2 read. Two tooling gaps: ML harnesses commit no per-trade rows, and C2 has no config-date cut | 0.9 | tooling · T1 | `live_vs_backtest.py` (all Stage-2 legs) · ≥ 4 of 6 real-money legs return a verdict computed only on post-config closes or from committed per-trade rows = hit; ≤ 1 = miss · 2026-11-25 | **PI-20261104-PREP1104-0001** (scope widened to `ml_entry_eq_struct`; perf-followup · 11-18 · `L-ML-LIVE`) + **PI-20261111-PREP1111-0001** (perf-followup · 11-18 · `L-LADDER`) |
| **F2** | `ml_entry` live R is inside its Stage-0 band once the band exists | 0.75 | no action until F1 lands · — | `live_vs_backtest.py --leg ml_entry` · CONSISTENT / INSUFFICIENT_N = hit; BELOW_BACKTEST = miss; NO_BACKTEST = void · per-trade rows committed | carried on PI-…-PREP1104-0001 |
| **F3** | The week's paper $ loss is the 11-09 sizing step plus trade 5209, not strategy | 0.9 | no action, because paper is never a decision surface; this review reads paper in R · — | journal risk $ per new `alpaca_paper` trade · median ≥ 5× the pre-reset median ($740, n=47) over the next 7 d = hit (the step persists); < 2× = miss · 2026-11-18 | none (check only) |
| **F4** | The demo-floor family swap is regime/noise, not decay | 0.6 | no action · — | `paper_book_tracker.py --no-append` · book recent-30d net > $0 = hit; < 0 = miss · 2026-12-02 | none (check only) |
| **F5** | The 72-day stop-less position class is fixed by #24547 | 0.7 | route to health (deploy + observe) · T2, already merged | next journal read · no `alpaca_*` position open > 7 d past its stop = hit · next health-review | health-review (no new item; the fix commit names it) |
| **F6** | `realized_slippage.py` can leak a live bearer into a public log | 0.95 | tooling/security · T1 | grep for an argv `Authorization` header in `scripts/` · 0 matches + a test = hit · 2026-11-18 | **PI-20261111-PREP1111-0002** (health-review · 11-18 · `L-OPS`) |
| **F7** | Rubric grades carry no outcome information (C9, 4th week) | 0.9 | no action, because the rubric is the documented cheap fallback and the CJ-3 blind grade is the replacement producer (skill § C9) · — | C9 table · B win% > C win% at n ≥ 300 each = miss of this call · next review | none (check only) |

**Backlog drain:** 32 open → 19 kept open (fresh observation each), 3 dropped (PB-20260830-XRP-4H… superseded by the 11-06 config;
PI-20261028-PVRNY2JI-0001 and -0005: `xrp_pullback_2h` and `iaum_pullback_1d` left real money), 1 done (PI-20261028-PVRNY2JI-0004, resolved
hit 11-04), 9 checklist rows read (the manager's register). **15 items still have no owner.** The oldest are
`SRQ-20260715-REALMONEY-ALLOC-BENCHMARK` (119 d) and `PRB-20260720-OPTIONS-PORTFOLIO-GRADUATION` (114 d). The manager should own them or kill
them. Two checklist rows look closable by the manager: `RESET-JOBS-20261104` (in_flight, last week's reset) and `PERF-REVIEW-W41`
(landed_unproven).

**Candidate follow-ups for Thursday (not run; `/perf-followup` is the manager's call):**
1. **F1, ML per-trade evidence:** re-run the `ml_entry` and `ml_entry_eq_struct` harnesses with a per-trade emit into
   `comms/strategy_evidence/runs/`. This one change gives a demotion signal to the two legs that carry most real-money flow.
2. **F1, config-date cut for C2:** small tooling change. Without it, every future re-promotion is invisible for weeks.
3. **`ml_entry_eq_struct` forward check:** +0.49 R/trade on the third read of its confirm window, with provisional slippage. A pre-registered
   forward-window read before any more capital.
4. **TP doctrine on real money (Tier 3, proposals only):** 5 of 6 real-money routings fail `tp_revision`. Carried from last week.
5. **Pullback/trend alternation (F4):** if the operator wants the regime question settled rather than watched, the ADX-split replay of the
   10-cell book is the test. It was killed 10-29 as "value unknown", so not re-filed.

## 4. Not done

- **C5 cost drift, C6 live-review grading, the per-role in-trade row, the desk system leg:** `could_not_look`. Each calls diag directly and has no
  relay fallback; direct diag is 401 until the operator updates the environment secret.
- **90d per-leg API window:** the route has none. The census subset covers 90d.
- **M13 insights and the sweep mirror:** not pulled. No call depends on them.
- **Blind-then-reveal grade (CJ-3):** not run this week.
- **Claude-channel ping:** not sent by this lane. The manager carries the result in its brief.
- **`/perf-followup`:** not run, as briefed.

<!-- PERF-REVIEW-PREP:END -->

<!-- PRACTICE-REFRESH:START -->
## TRADING + MODEL — weekly practice refresh (lane `PRACTICE-REFRESH-20261111`)

Tier 1, read-only on production. Nothing was queued and no config changed. Full evidence:
[`docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md` § 12](../research/practice-review-trade-mgmt-and-ai-2026-10-28.md).
The canonical list was revised in place: [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
Direct `/api/diag/*` reads return 401 this week, so diag reads went through the relays (#24905, #24906, #24910, #24911) and the read-only
console data source; § 12.6 names the route behind each number.

**First, the feedback loop.** Thursday 11-05 decided 2 of last week's 12 proposals. Then the ML-entry focus and the one-lane throttle
(operator, 11-06) left the rest with no decision. Proposal #12 below gives the refresh a fixed slot in Thursday planning.

**TRADING:** 4 sources checked (1 read in full). **Deltas:**
- **T3 strengthened.** Measure execution cost as a **markout** (fill vs the mid later, net of fees), and count order size against depth and
  forced exits as cost channels [S74, AFT 2026: on Hyperliquid's full record, algorithmic takers only broke even on a 2 h markout].
- **T8 strengthened (cautionary).** An exit replay on a leg's own trades stays chronological and deflates its grid [S75: a 900-trade replay
  switched to a random split].

**MODEL:** 4 sources checked (abstracts or summary). **Deltas:**
- **M14 added.** An LLM's own trading returns are a claim, not evidence. Prefer the LLM upstream of deterministic sizing, risk and
  execution, with six validity tests before any deployment claim [S78].
- **M12 strengthened.** Also check forecast amplitude and cross-series ranking; per-series loss hides "forecast collapse" [S76, S77].
  **Scope note:** under the operator rule of 11-04, per-asset scores are reported, not gating.
- **M11 note.** Repeatability is necessary, but it is not skill [S59 re-read].

### Demo-floor data generation

Population: 58 rostered leg × floor cells. Data: trades with entry time ≥ 2026-11-04T19:00Z. The console journal snapshot covers up to
~08:00Z 11-11, and relay #24906 reads ids 7056–7070. Ids 7052–7055 are unread (comment truncation).

| Account | Cells | Cells with ≥1 row | Fills | Rejected | Fills / rejected a week ago |
|---|---|---|---|---|---|
| bybit_1 | 30 | 23 | 58 | 32 | 42 / 30 |
| alpaca_paper | 17 | 6 | 13 | 6 (incl. 1 exchange) | 5 / 2 |
| ib_paper | 11 | 3 | 1 | 25 | 2 / 25 |

- **Blocked:**
  - ib_paper `mgc_trend_1h`: 16 `risk_refused sized_qty=0` since 11-09 01:11Z, cause not established, plus netting against the MGC short.
  - bybit_1: the slice budget refused 24 signals, mostly on the 5m scalps and the SOL legs.
  - alpaca_paper `ml_entry`: zero buying power on 11-05, and a USO hard-to-borrow short sent with a non-day TIF (a mechanics bug).
  - `claude_desk` on alpaca_paper / ib_paper: no row for the **third week**, and no audit row since 11-10.
  - **New:** bybit_1 `htf_pullback_trend_2h` logs a complete sell setup but has no journal row in 7 days.
- **Quiet by design:** 16 cells ("no breakout / no setup / no squeeze release"). **Quiet in position:** 3 ib_paper cells, including an
  MHG short open since 09-17. **Could not look:** 4 cells (relay timeouts).
- 41 of 63 floor rejections are netting/slice refusals with no priced outcome (last week 47 of 57).

### Is it learning?

Population: 98 registry files and 24 datasets (`trainer-vm-diag` #24905), and the shadow log 10-24 → 11-11 (75,831 records, 27 heads).

- **market_features:** works end to end. 52 models were retrained (364 runs), 22 heads score, and 3 are advisory.
- **Trade-level families** (setup_candidates, conviction_meta, trade_outcomes): 13 models retrained (91 runs), **0 score live**. The
  setup_candidates dataset is **frozen again** at 48,445 rows (newest 10-29).
- **LTR:** `review_journal` = 0 rows (third week). **Desk:** `claude_judgments` 883 → 1,203 rows, but no trainer uses them. **Exit heads:**
  dataset frozen since 09-07; the heads are outside the registry.
- **Trainer:** cycle 11-11 trained 67 models with 3 refusals. **New:** a dataset audit refuses `setup-candidates-metalabel-xsym-yz-v1`
  (dead feature or degenerate label). `exit-policy-v1` has never trained (107.6 d).

### Gaps for Thursday (12 in § 12.7; proposals, nothing queued). Top of the list:

1. **MODEL:** `trend_donchian_eth` (bybit_1) still **closes trades** on an exit head with only an in-sample read. Its real-money sibling's
   head **failed** a matched-random control on 11-04. Dispatch the queued OOS walk-forward (`PI-20261029-IFMPNGJK-0004`) with that
   control added; until then, propose `annotate` (Tier 3) (T1, M10).
2. **TRADING:** 41 of 63 floor rejections leave no outcome. **Again:** a `VIRTUAL-LEG-LEDGER` build row (T12, R3).
3. **TRADING:** four floor mechanics faults (ib MGC sizing refusals, USO TIF, Bybit min-notional, the `htf_pullback_trend_2h` setups with
   no row) → the soak-fault intake.
4. **MODEL:** the desk on alpaca_paper / ib_paper is silent for the third week. Diagnose `DESK-PAPER-ACCOUNTS` first.
5. **TRADING:** markout measurement of execution cost on every fill (T3, S74).
6. **MODEL:** name the first trade-level family to reach shadow scoring; fix or kill `exit-policy-v1` and the audit-refused manifest (M1, M10).
7. **BOTH:** a per-leg × floor liveness CHECK in health-review (R6), still hand-classified for the third week.
8. **MODEL:** `ML-LEARNING-LEDGER` has been queued through three refreshes; **raised**.
<!-- PRACTICE-REFRESH:END -->

<!-- ML-FRONTIER-PREP:START -->
# MODEL track — /ml-review 2026-11-11 — the live ENTRY model has no established edge: its served replay loses −0.13 R per decision, every bit of it on the long side, while this week's 27 ML bake-off units again tested heads that change no real-money order

> Lane `ML-FRONTIER-PREP-20261111` (Tier 1, read-only, dispatched by Manager Session 2026-11-11a). It ran `.claude/skills/ml-review/SKILL.md` and
> `.claude/skills/frontier-research/SKILL.md` in full (four layers each). **Nothing was promoted, queued, deployed or demoted, and no `config/`, `src/` or
> `ml/configs/` file was touched.** New work is **proposed** in § 3, each item labelled MODEL or TRADING.
> Records: `comms/reviews/ml-review-20261111-200000.json` · `comms/ml-plan/20261111T2000Z-ML-FRONTIER-PREP.json` · `docs/research/frontier-scan-2026-11-11.md`.
> **Cited, not re-measured:** ML-CONSOLIDATION (#24897, `docs/plans/ML-CONSOLIDATION-2026-11-11.md`) inventories the 106 registry rows by slot: 15 KEEP, 19 REVIEW, 72 RETIRE proposed.
> **Practice refresh:** owned by the sibling lane PRACTICE-REFRESH this week, so it is not repeated here.

## S · Scoreboard (money first)

Source: `GET /api/bot/performance` (2026-11-11 ~19:00Z), lifetime window. **The route ignores `since=`** (it returned identical numbers for 7 d and 30 d), so
the 90 d / 30 d / 7 d windows are **could_not_look** on this route; the PERF-REVIEW-PREP section owns the windowed book view. R is net of the journal's
recorded costs. `$` is the measured P&L, not a balance.

| book | population | net R | exp R / trade | PF | read state |
|---|---|---|---|---|---|
| Real money + prop (journal top level) | 487 closed | **−152.1 R** | −0.31 | 0.63 | read. `bybit_2` known-divergent; `alpaca_live` unrecorded |
| Mirror (`paperPortfolio`) | 168 closed | **−32.6 R** | −0.19 | 0.63 | read. Mirror books partly unrecorded |
| Paper / demo floor | 1,786 closed | **−144.2 R** | −0.08 | 0.91 | read. 128 fabricated-P&L rows; 6 paper accounts unrecorded |

**Would a sceptical quant believe the ML legs have edge? The answer is about the decision each model changes, net of cost.**

- **`ml_entry` (Foxhound-1, refit r20261106; real money on `bybit_2`, plus 5 books): no.**
  - The registered held-out figure is +0.0073 R per decision (c692-01, n = 11,240).
  - Frozen v1 over its clean held-out year reads a mean of **+0.0085 R per decision across 13 windows of 28 days, window sd 0.127, t ≈ 0.24** (`RQ-20261108-98e3-26`).
  - The served replay of 10-25..11-07 reads **−0.13 R per decision, n = 317, CI [−0.25, −0.01]** (`RQ-20261108-98e3-23`).
  - DSR: `not_computed`.
  - Live: 12 closes on `bybit_2` since 11-01 (+4.96 R on the route's mixed R basis). n = 12 is no evidence either way.
- **`ml_entry_eq_struct` (Foxhound-4; real money on `alpaca_live`): plausible, unproven.**
  - Its evidence is one confirm window: +0.49 R per decision, se 0.076, n = 207, deflated bar met at N = 2 (`RQ-20261107-98e3-06`).
  - DSR: `not_computed`. Its only open unit is a forward read that cannot run before 2027-04-01 (`RQ-20261108-98e3-13`), and the iteration census cannot link it (filed, § 3 P3).
  - PR #24889 (operator Tier-3 approval, 11-11) widens this leg to the 173-ETF pool its test passed on.
- **Beagle-1 overlay** (TD `reduce` on `trend_donchian_xrp_4h` and `_sol_prop`, real money): **no standalone record was read this run.** Both legs it trims are on DSR probation (xrp_4h 0.023, sol_prop 0.332).

## 0 · Prior calls

**Follow-through** (`review_followthrough.py --window-days 7`):
- ml-review: cohort 3 filed, 2 done, 0 killed, 1 open. Backlog 12 open, 75 % due, median age 31.5 d, 0 with no owner.
- frontier: cohort 6 filed, 3 done, 0 killed, 3 open. Backlog 16 open, 69 % due, 1 with no owner.

| call (11-04) | p | re-run check | grade |
|---|---|---|---|
| 1 · no ENTRY artifact with data through ≥ 10-28 is served by 11-11 | 0.60 | The check as written reads `ml/served/ml_decision_entry_v1`: `train_end_exclusive` 2025-09-22. The artifact actually served (`ENTRY_SERVED.json` → `v1r20261106`) has `train_end_exclusive` 2026-10-14. Both are < 10-28 | **hit**. A refit *was* served on 11-06, which the call did not foresee. Its training data still ends before the bar |
| 2 · the 11-02 MES baseline collapse is a data/label construction change | 0.75 | No trainer per-day read yet. The baselines are degenerate on all 8 cycles 11-04..11-11, and the volatile-label share keeps climbing (5m 41.2 % → 44.9 %) | **unresolved** (`PI-20261104-DGUBH8UA-0001`) |
| 3 · ≥ 70 % of ML units graded in 7 d still target regime/direction | 0.80 | 38 of 38 `ml_bakeoff` result records generated since 11-04 20:00Z (27 units): 25 regime, 13 direction | **hit** (100 %) |
| 4 · live ENTRY mean ≤ 0 once n ≥ 30 | 0.55 | n = 12 on `bybit_2` | **unresolved** (carried) |
| 5 · yz-v1 drift is the dead `vol_bucket`, not regime (yz moves, fc-pcv-v2 does not) | 0.70 | yz-v1 KS 0.182 moderate; **fc-pcv-v2 KS 0.236 significant** (was 0.029 no_change) | **miss**. Both moved, and so did SOL-15m, MES-5m and fc-pcv-v1. A common input shift, not a yz-only defect |
| 6 · Q-TM1 next iteration (`78fc-04`) still blocked | 0.60 | still under `research/queue/blocked/` | **hit** |

- Frontier keeps graded: taker-flow ENTRY variant (P3), **unresolved**, not registered. LambdaRank ENTRY (P4), **unresolved**, not registered. Drops: TSFM forecasters and regime variants are **hits**, borne out by C3/C8. The LOB FM and LLM-trader drops are **void** (no new evidence).
- **What changes because of the grades:** any call about drift now names a cross-head control, because call 5 assumed the siblings were stable. Calls whose check reads a served artifact read `ENTRY_SERVED.json`, not a fixed directory.
- *Housekeeping:* 3 hit · 1 miss · 2 unresolved. Brier INDETERMINATE (< 10 resolved).

## 1 · CHECKS

**Headline numbers:**
- **ML can change 24 of 82 live-rostered (account, leg) pairs.** That is **4 of 6 real-money pairs** and **6 of 9 prop pairs**.
  - Population: `config/accounts.yaml` re-parsed at `main@9d6112782`, accounts in `mode: live`, joined to each model's consumer map (registry `consuming_strategies`/`accounts`, plus the BTC `trend_vol` cells).
  - The 2 BTC cell pairs (`bybit_1` `ict_scalp_5m`, `squeeze_breakout_4h`) count only if `REGIME_ML_VERDICT_MODE=use` on the VM, which this lane cannot read this week (diag token rotated). They are INFERRED from last week's read.
  - The real-money pairs ML does not touch: `bybit_2` `ada_pullback_2h` and `alpaca_live` `tqqq_trend_long_1d`.
- **First broken hop of the learning chain: H6 → H7 for registry models**, unchanged. The order-changing models are still served artifacts that bypass H6.

| # | check | population | state | reading |
|---|---|---|---|---|
| C1 | trainer + registry | 98 registry rows + 8 served inventory rows (`/api/bot/ml/registry`, mirror 107 s old); the last cycle | **finding** | Registry stages {advisory 3, shadow 20, candidate 74, research_only 1}. `--plumbing` `REGISTRY-STAGES-CHANGED` vs the plan's {shadow 21, candidate 72}: the same gap as last week, owned by `ML-REGISTRY-LADDER-GAPS`, not re-filed. The D2 rows read here (the MES baselines, MES-5m and BTC fc-pcv-v2) each show an 11-11 ~01:00Z run in registry `runs[]`. **Trainer pull #24903** (run 43082654333): timer active, service idle between runs, ExecMainStatus 0. Cycle 11-11 01:53Z: rc 0, trained 67, skipped 6 (3 enforced audit skips), failed 0, `trained_with_refusals`; the 08:05Z resume found all 73 done. **0 `manifest_oom_red_flag`.** Builds rc 0, augmentation not degraded. **Stage-guard: 97 hold, 1 DEMOTE, `btc-regime-15m-lgbm-fc-pcv-v2` (Collie-5a, the advisory BTC-15m head)**; **its only reason is "score-distribution drift verdict is 'significant'"** (#24947). Trainer resources (#24938): disk 82 % (80 / 97 G; 80.2 % last week), RAM 5.9 GB, 1 vCPU. **4 `lifecycle_red_flag` lines: the `serve_parity` lifecycle job has failed 3 times running** for the BTC-5m shadow heads (`btc-regime-5m-lgbm-v2`, `-yz-v1`, `-flow-v1`, and plan `btc-regime-5m`). Retries continue (no halt); the heads change 0 legs |
| C2 | data + label freshness | 73 manifests (`--plumbing`); the served ENTRY artifacts | **finding** | `TRAINING-STALENESS`: 5 stale, 2 never trained (threshold 7 d). The served ENTRY refit has `train_end_exclusive` 2026-10-14 and `data_through` 2026-11-05. MES labels still drifting (C1 / `DGUBH8UA-0001`). 3 manifests built 0 rows (`exit-policy-v1`, `mes-execution-quality`, `setup-candidates-metalabel-paper-v1`). `exit-policy-v1` still has 0 registered runs (the C4 "absent from the registry" class, long-standing). |
| C3 | business-use map | 82 live pairs (6 real money, 9 prop); every model a consumer reads | **finding** | **24 / 82 · real money 4 / 6 · prop 6 / 9.** Consumers: Foxhound-1r + Labrador-1b (`ml_entry`, 6 books) · Foxhound-4 (`ml_entry_eq_struct`, `alpaca_live` + `alpaca_portfolio`) · Beagle-1 overlay (4 TD legs across 6 books, 9 pairs) · Foxhound-2 and -3 and Labrador-2 (demo) · BTC fc-pcv-v2 (2 `bybit_1` cell pairs). **The SOL-15m and MES-5m "live" regime heads still change 0 pairs** (registry `consuming_strategies` = []), for the 4th week |
| C4 | learning chain H1→H7 | the ML-PROGRAMME § 7 sources, since 11-04 | **finding** | H1–H3 accruing (12 real-money ENTRY closes, desk decisions). H4 ✅ (D2 heads retrain daily; the ENTRY refit). H5 ✅. **H6: 0 registry stage changes.** H7 is reached only by served artifacts. `ML-LEARNING-LEDGER` is still queued, so these are computed by hand, not by an instrument |
| C5 | serve parity + soak | shadow/advisory heads (trainer gate-check) | **finding** | Gate-check (pull #24903) was readable for 19 of 23 heads; the comment truncated the last 4; the 3 advisory heads were re-read in #24947 (C6). `ready: true` on BTC-15m v2, fc-pcv-v1, **yz-v1**, SOL-15m fc-pcv-v1 and the ETH self-only control. For yz-v1 that means last week's dead-`vol_bucket` parity failure no longer blocks (INFERRED from `ready`; the parity line is outside the tail). `drift_clean` fails on 8 heads. The BTC-5m `serve_parity` lifecycle job is red-flagged (C1). The served ENTRY artifacts have **no parity check yet**. `ML-FS-SERVE-PARITY` and `ML-PROMO-PARITY` are queued, and `ML-LIVE-PARITY-ML-LEGS` was filed 11-11, after the weekly live-vs-replay parity run could not check `ml_entry` or `ml_entry_eq_struct`. Soak is mechanical (OPERATING-PLAN § 2) |
| C6 | champion vs challenger + cost gate | cost-gated heads; same-replay results this window | **finding** | Advisory gate packets (#24947): BTC-15m fc-pcv-v2 `ready: false`, with **only `drift_clean` (KS 0.226) and `beats_baseline` failing**. `beats_baseline` is the max-proba Brier artefact, `3WM5HADW-0004`. Live parity 24/24, live regime AUC 0.690, OOS edge +0.254 macro-F1. SOL-15m and MES-5m are `ready: true`. **`cost_net` is `insufficient_data` / not applicable on all three**, because they have no net-R column (`GNVUF1ES-0002`). Same-replay comparisons this window: the c4f1 / 98e3 `ml_bakeoff` units used one fold file and cost stack per unit, with the prior as a control. **The ENTRY comparisons that matter (98e3-23/25/26) are on one replay and one cost stack, and none reaches a decision-grade verdict.** Foxhound-1r has no cost-gate packet because it is not a registry head |
| C7 | drift, split | the 3 advisory heads + the nearest shadow | **finding (watch)** | (a) KS, `/api/bot/shadow/drift` (2026-11-11 ~19:05Z): **BTC-15m fc-pcv-v2 (advisory) significant 0.236 / PSI 0.206** (no_change 0.029 last week; score mean 0.976 → 0.936, sd 0.057 → 0.106) · SOL-15m fc-pcv-v2 moderate 0.102 (no_change 0.045) · MES-5m moderate 0.110 (minor 0.095) · fc-pcv-v1 moderate 0.156 (minor 0.079) · yz-v1 moderate 0.182 (3rd moderate read). **Every head moved the same way at once.** That is a common input shift, not a per-head defect (call 5 missed). **Plan-only drift scan** (#24938): Result=success, rc 0, 46 rows, **0 `dispatch` / `skip_no_manifest`, so 0 drifted, 0 persistent, and no `DRIFT-REMEDIATE` row.** The KS moves above are *watch*. (b) Labelled decay: **could_not_look, no instrument** (`LIVE-DECAY-MONITOR` queued 26 d). For ENTRY, 98e3-23 reads DECAY (the last 7 d mean is ≥ 0.10 R below the first 7 d) |
| C8 | concentration | registry; open plan items; this week's ML units | **finding** | `MANIFEST-CONCENTRATION` gbdt 77/106. Open family-tagged items: gbdt 14/24 = 58 % (bar 60 %). **ML bake-off questions: 38/38 regime or direction, the third week at 100 %.** ML-CONSOLIDATION proposes retiring 41 of the 63 D2 regime manifests |
| C9 | research landed + backlog | 447 result records generated since 11-04 20:00Z (307 units); 38 `ml_bakeoff` records (27 units) | **finding** | `ml_bakeoff` verdicts per record: regime 6 pass / 10 fail / 7 indet / 2 n/a; direction 0 pass / 10 fail / 1 indet / 2 n/a. **Order-changing ML work ran outside `ml_bakeoff`:** ENTRY-EQ structure confirm PASS (98e3-06, which put Foxhound-4 live); crypto ENTRY on structure labels FAIL (98e3-22, −0.05 R, n = 212); ML SL revision v2 passed dev (c692-12) and **failed every confirming / held-out read** (c692-13/14/15: +0.0005 R/trade, CI [−0.0007, +0.0018], n = 10,641); MANAGE pooled model FAIL (c692-03); exit head held-out FAIL (e4a1-01); prop ML legs FAIL or INDETERMINATE (fd68-01..06, d256-01/02); ENTRY timeframe levers 5m / 15m / 4h FAIL or INDETERMINATE (b621..b626). Backlog: § 4 |
| C10 | DSR probation | 6 production legs (`dsr_probation.py`) | **could_not_look** for ML | `ml_entry`: dsr `not_computed` · `ml_entry_eq_struct`: `not_computed`, **NO LIVE UNIT** (its forward read 98e3-13 is not linked). Non-ML probation: ada_pullback_2h 0.254, tqqq 0.533, td_sol_prop 0.332, td_xrp_4h 0.023 |

**Iteration census** (`scripts/research/iteration_orphans.py`, 2026-11-11):
- ml_model subjects: 9. Covered 1, **overdue 8**, orphan 0.
- All 8 overdue units (`RQ-20261101-78fc-02..08`) sit in `blocked/`, each on a named work item: `ML-P1-COSTNET-REBUILD` · `ML-VOLGATE-EXITHEAD-REPLAY` · `TMBENCH-QTM1B-BUILD` · `ML-EXIT-ACTIONGRID-LABELS` · `ML-P4-CONVICTION-REGATE` · `ML-REGIME-15M-DRIFT` (×2).
- **Foxhound-4 is not a subject at all, so the census cannot see it** (filed, § 3 P3).

**Weekly progress lines** (row ML-WEEKLY-REVIEW-LINES; the live ENTRY artifact is Foxhound-1r):
1. **Data coverage** per feature family per symbol: **could_not_look**. No instrument reads the live decision log by family.
2. **Feature count in use:** live 20 columns (the v1 recipe, refit) vs 20 admitted (fs01). Not below the admitted count.
3. **Retrain freshness:** `train_end_exclusive` 2026-10-14, **28 days** at 11-11. `data_through` 2026-11-05, 6 days. **AMBER:** the weekly cadence's 8-day bar is met on data-through and missed on training end. It was 408 days RED last week.
4. **Live vs held-out:** 12 closed `ml_entry` trades on `bybit_2` since 11-01.
   - Mean pnl % +0.12. Longs 0 of 3 winners (mean −1.60 %). Shorts 6 of 9 winners (mean +0.70 %).
   - The registered held-out figure is +0.0073 R per decision.
   - The side split matches the replay's SIDE-DRIVER verdict, but n = 12 is no evidence.

## 2 · ANALYSIS

**2.1 The live ENTRY model is pricing market direction, not asset selection (the material finding; real money).**
- **What we know (MEASURED):**
  - Over the replay window the long side loses −0.90 R per decision (n = 51, 8 % winners) and the short side is flat (+0.017, n = 266).
  - Over the clean held-out year, frozen v1's 28-day windows swing from −0.18 to +0.23 R per decision around a mean of +0.0085.
  - A monthly refit does not help (98e3-26: NOT-AGE, NO-LEVER). Neither does a short-only gate (98e3-25: NO-LEVER, window-specific).
- **Competing hypotheses:**
  - (H1) The model's realised edge is the common crypto factor. Its long/short choice is a bet on the market's direction, so its result flips with the tape.
  - (H2) The model has real per-asset skill, and the last fortnight was a bad draw (98e3-23 also reads NOISE-COMPATIBLE).
  - (H3) Serve-time drift: the live feature row differs from training. Not testable, because no ENTRY parity check exists.
- **What discriminates them:**
  - H1 predicts that a **market-residual target** (asset return minus β × BTC) loses the window-to-window swing and keeps any per-asset skill. H2 predicts no change.
  - The year-window sd (0.127) against a mean of 0.0085 is what H1 predicts and H2 explains only as noise.
  - **I have not run that test.** It is proposed as P2, at a powered design (13 paired windows, MDE +0.058 R).
- **Rejected alternatives:**
  - Demoting `ml_entry` on this evidence. The ladder's demotion signal is the mirror's net-of-cost window (OPERATING-PLAN § 2), not an offline replay. P1 asks for that read.
  - Another learner on the same target. fs01 showed the recipe overfits any extra column.

**2.2 The research capacity is still pointed at heads that change nothing.**
- **MEASURED:**
  - 27 ML bake-off units this week. Every one targets a regime or direction label.
  - The regime heads they feed change 2 demo pairs at most (C3).
  - The units are well built: purged folds, the prior as a control, one cost stack each. So their FAILs and PASSes are informative about the regime head.
  - But the business-use map says no answer changes a real-money order.
- **Competing hypotheses:**
  - (i) The iteration loop (programme-review / research-ops) keeps authoring the next lever for every subject that has one, and the regime heads have the most levers.
  - (ii) Order-changing ML questions are blocked on infrastructure (the 8 overdue units all wait on builds), so capacity flows to what can run.
  - Both fit. (ii) is the root: the queue runs what is dispatchable.
- **Rejected alternative:** a rule that refuses regime units. That would be a new gate.
- **The fix proposed is on the supply side:** clear the builds blocking the order-changing units (P5), and accept ML-CONSOLIDATION's retire wave so the regime iteration subjects shrink (P4).

**2.3 Trade-management ML failed its confirming reads.**
- ML SL revision v2 passed its dev stage (c692-12). Three confirming reads then failed: cross-sectional, v1 config, and held-out. The held-out delta is +0.0005 R per trade with CI [−0.0007, +0.0018] over 10,641 trades.
- That is a powered null: the CI is ±0.0013 R, so any effect worth trading would have shown.
- With Q-TM1 and Q-TM1b (last week), MANAGE c692-03 and the exit head e4a1-01, this is the **fifth trade-management ML null on R1-type state features.**
- This closes the tested configurations: BE/BE1/TRAIL/TRAIL15 heads, margin 0.40, the R1 state. It does not close trade management.
- The diagnosis already written into `78fc-04` (the path state is missing) is the right next iteration, and it is blocked on `TMBENCH-QTM1B-BUILD`. **That build is the highest value per cost on the ML board** (P5).

**2.4 Drift: every head moved at once.**
- Five heads on three symbols and two timeframes moved from no_change/minor to moderate/significant in one week.
- The advisory BTC head's mean max-probability fell from 0.976 to 0.936, and its sd nearly doubled. The head is **less sure**, not wrong. Labelled macro-F1 held at 0.582 on 11-11 (registry `runs[]`).
- **Mechanism I believe:** a regime-mix shift in the inputs. The volatile-label share is rising on MES too (C1).
- **Refuting observation:** labelled macro-F1 or recall_volatile on the advisory head falling past its registered tolerance next week.
- First-time drift is *watch* (skill § C7). The trainer's stage-guard independently reads the advisory BTC-15m head as a **demote**. Under the refine-not-abandon rule that becomes a soft-off proposal plus a `[refinement]` row, not a demotion by this lane (§ 3 P8).

**2.5 Frontier (F1–F4)** — full triage in `docs/research/frontier-scan-2026-11-11.md`.
- **F1:** last scan's two keeps (taker-flow and LambdaRank ENTRY variants) were never registered.
- **F2:** gbdt 77/106 manifests. 14/24 open items (58 %, 2 points under the bar). Question concentration 100 % (C8).
- **F3:** 4 of 4 required rows checked. Lab releases are secondary-only, for the 2nd week. No TSFM released in November 2026 was found.
- **F4:** `FRONTIER-LEVER-TABULAR` and `-HARNESS-COSTS` are in their 4th scan queued, `-LEADLAG` its 4th, `-TSFM-TIMESTRAL` its 3rd. Raised again with a recommendation each (§ 4).
- **Kept 1 of 7 (proposed, not queued):** **K1, the market-residual target for ENTRY** (2611.13572's factor-conditioning argument plus 98e3-23's SIDE-DRIVER).
- **Dropped:** MC-JEPA encoder (compute) · TabFM / EXAONE-Tabular (compute, `license:other`) · Granite ensemble-r1 quantiles for the TP head (leakage: released 10-27, so 15 days of clean bars; re-open 2027-02-01) · a short-only gate (already answered) · more regime/direction learners (business, 3rd week) · FINCOSMOS desk evaluation (business).
- **M41 (local LLM) answered: kill as scoped.** It fails compute on both VMs and has no consumer. The pipeline item is closed `killed` and the milestone records the re-entry test.

**Surprises:**
- (a) A real-money model (Foxhound-4) is invisible to the iteration census. Its forward read exists but carries no `iteration:` block.
- (b) The performance route silently ignores `since=`, so every window but lifetime reads the same.
- (c) 7 of 12 real-money `ml_entry` closes carry closeReason `other`, the same as last week.

## 3 · Decisions — proposals (none queued; each labelled)

Ranked by money × decision impact ÷ cost. Each has `p` and a pre-registered check in the review JSON `calls[]`.

| # | track | proposal | why now | cost to a verdict | rejected alternative |
|---|---|---|---|---|---|
| **P1** | **MODEL → Tier-3 read, operator** | **Run the Stage-2 demotion read for `ml_entry` now:** the `bybit_portfolio` mirror's net-of-cost window over the live period, plus a computed DSR for `ml_entry` (C10 reads `not_computed`) | the offline evidence for edge is a t ≈ 0.24 year mean and a −0.13 R replay. The doctrine's demotion signal is the mirror, and nobody has read it | the manager or a Sonnet lane, about $3 | demoting on the replay (wrong signal); waiting for n ≥ 30 live (the live book never establishes edge) |
| **P2** | **MODEL** | **Register K1: market-residual target for ENTRY.** The same v1 recipe on the 24 h net return minus β × BTC (causal rolling β), market-neutral at each timestamp. 13 paired 28-day windows over the clean held-out year; PASS needs ≥ +0.06 R per decision, a CI lower bound > 0, and a shuffled-β placebo that does not pass | it is the one test that separates H1 from H2 in § 2.1, on the real-money model | runner, about $4 | the taker-flow and LambdaRank variants (unregistered for 2 weeks; neither addresses the side effect) |
| **P3** | **MODEL** | **Give Foxhound-4 an iteration subject and an in-hand-data unit:** add `ml-entry-eq-struct` to `iteration_subjects.yaml` and link the forward read `98e3-13` to it. Add a unit that reads in-hand data now (for example a second disjoint pre-2026-10 confirm window), not only after 2027-04-01. **Filed** as `PI-20261111-TX7TX2ZN-0001` (manager) | a real-money model, being widened to 173 ETFs (#24889), sits outside the census with one confirm window behind it | about $2 to author | none: the operating plan requires it |
| **P4** | **MODEL** | **Accept ML-CONSOLIDATION wave 1** (retire 72 rows: 41 D2 regime manifests plus 31 unassigned) and **retire the matching regime iteration subjects by record**, so the loop stops authoring learner arms for heads with no consumer | C8 at 100 % for 3 weeks; 27 units this week fed no order | a Tier-1 PR plus one Tier-2 archive action (#24897 § 52) | a rule refusing regime units (a new gate) |
| **P5** | **MODEL** | **Dispatch `TMBENCH-QTM1B-BUILD` first**, then `ML-EXIT-ACTIONGRID-LABELS`. These unblock `78fc-04` and `78fc-05`, the path-state trade-management iteration on the six money legs | five trade-management nulls on R1 state; the hindsight ceiling is 0.86 R per trade (ML-AM-NEXT-LIVE), so value exists | Sonnet, about $6 | another trade-management variant on the R1 state |
| **P6** | **MODEL** | **Lever rows:** KILL `FRONTIER-LEVER-TABULAR` and `-TSFM-TIMESTRAL`; DISPATCH `-HARNESS-COSTS`; the manager decides `-LEADLAG` | 3–4 scans queued; this week's gates now fail for the newest tabular FMs too | $0 to kill | re-filing them |
| **P7** | **TRADING → `/performance-review`** | `ml_entry` on `bybit_2`: 7 of 12 closes carry closeReason `other` (unchanged from last week's P7), and longs are 0 of 3 | close-reason grading on the real-money ML leg | handed off | — |
| **P8** | **MODEL → Tier-3 (operator)** | **BTC-15m fc-pcv-v2 (advisory) stage-guard demote → soft-off proposal** (advisory → shadow) plus a `[refinement]` row, applying the `drift-remediation` skill. **My recommendation: HOLD advisory one more weekly read.** The trip is drift-only (#24947), and every other gate passes: live parity 24/24, live regime AUC 0.690, OOS edge +0.254. The drift is first-time, every head moved together (a common input shift), labelled macro-F1 held at 0.582, and the head changes at most 2 demo cell pairs | the trainer's stage-guard proposes it, and the refine-not-abandon rule needs a disposition | $0 to decide | an immediate soft-off (it removes the vol axis from 3 `trend_vol` cells on demo, on first-time drift) |

**Stages:** no promote and no demote this week. The one stage signal is the trainer stage-guard's **demote on BTC-15m fc-pcv-v2** (P8). `ready: true` on 5 shadow heads is not a promotion argument, because none of them changes an order (C3).

## 4 · Backlog drain, handoff and not done

**Population:** 16 open ML pipeline items (`origin.ref` names ml-review, `routed_to` starts with `ML`, or `what` starts with `[ml]`/`[refinement]`).
**All 16 triaged; `count_untriaged` = 0.**

| disposition | n | items |
|---|---|---|
| kept open, re-read this run (`work.py observe`, with an observation) | 9 | `3WM5HADW-0004` (max-proba still served: the drift payload's means are about 0.94–0.98) · `DGUBH8UA-0001` (MES still degenerate, 8 cycles) · `DGUBH8UA-0002` (refit served, 23 days train-end to publish, not cleared) · `DGUBH8UA-0003` (no beats-prior clause yet) · `GNVUF1ES-0001` (MES margin void; 0 legs) · `GNVUF1ES-0002` (larger: the money models have no registry cost gate) · `MVBJLVJ3-0001` (0 provenance calls) · `CAZHXZNE-0001` (5 GPU units, none landed through the trainer route) · `MB-…-SHADOW-LOG-HISTORY` (no reader change) |
| kept open, re-read via the trainer | 5 | `3WM5HADW-0005` (yz-v1 now `ready: true`; still needs the code fix) · `UAOAYGBB-0001` (3 enforced skips, 5 stale) · `PROMOREADY-OOSEDGE-OOM` (0 OOM flags; RSS not measured) · `01FXMMUG-0001` (constant by construction, tracked by ML-HYGIENE) · the drift-gate BL (`drift_clean` fails on 8 heads and now drives a demote) |
| kept open, not re-read (needs a trainer measurement this batch did not carry) | 2 | `AHCVAAF5-0002` (calibrators ran twice on 11-11; holdout fields not read) · `SBAQDDVQ-0001` (heavy lock not in this batch) |

**Filed this run:**
- `PI-20261111-TX7TX2ZN-0001`: Foxhound-4 has no iteration subject or live unit.
- `PI-20261111-TX7TX2ZN-0002`: `[refinement]` for the BTC-15m advisory stage-guard demote (P8), with restore / soft-off / retire criteria.
- Closed: `PI-20261022-J9X7ACR3-0001` (M41), `killed` with the scoping verdict.

**Handoff to the manager (not re-filed):**
- the lever rows (P6);
- the 8 overdue ml_model iterations, each blocked on a build (P5 names the order);
- `LIVE-DECAY-MONITOR` (queued 26 d);
- `ML-LEARNING-LEDGER` (queued; C4 is still hand-computed);
- the `/api/bot/performance` `since=` no-op (§ S). This belongs to `/health-review`.

**Not done:**
- practice refresh (sibling lane);
- C7(b) labelled decay (no instrument);
- weekly line 1 (no instrument);
- the MES per-day label-share read (not in this trainer batch; `DGUBH8UA-0001` keeps it);
- a primary-card check of lab releases (secondary only);
- the `REGIME_ML_VERDICT_MODE` env read (diag token rotated 11-11; C3's 2 cell pairs are INFERRED);
- send-ping (the lane reports to the manager).
<!-- ML-FRONTIER-PREP:END -->
