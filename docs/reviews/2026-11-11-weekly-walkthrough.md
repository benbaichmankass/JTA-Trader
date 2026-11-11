# Weekly walkthrough 2026-11-11

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP-20261111`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH** (lane `PRACTICE-REFRESH`). A section that another lane has not landed yet is simply absent.
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
