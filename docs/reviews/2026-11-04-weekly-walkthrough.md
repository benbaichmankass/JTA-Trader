# Weekly walkthrough 2026-11-04

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH** (lane `PRACTICE-REFRESH-20261104`, below). A section that another lane has not landed yet is simply absent.
> On a collision, the later lane merges `main` first.

<!-- PERF-REVIEW-PREP:START -->
# PERFORMANCE — /performance-review 2026-11-04: a flat week; the one leg new to real money (`ml_entry`) has no backtest band to be judged against, and the reviewer's "widen `close`" signal was double-counting

> Skill: `.claude/skills/performance-review/SKILL.md` (on `main` at `924aeee35`), run in full: Layer 0, CHECKS C1–C12,
> ANALYSIS, decisions. **`/perf-followup` was not run.** The candidate follow-ups are listed in §3.
> Machine record: `comms/reviews/performance-review-20261104-190000.json`. Lookback: 30 days is the main window
> (operator, 2026-11-02), with lifetime, 90d and 7d beside it.
>
> **Merged ≠ deployed ≠ observed.** Every trade figure here is **OBSERVED** on the live read-only API
> (`/api/bot/performance`, `/api/bot/trades/closed`) and the diag route (`journal?table=trades`, 4 × 1000 rows, ids
> 2896–6895, opened 2026-06-26 → 2026-11-04; `position_telemetry`, 725 rows), read 2026-11-04 18:55–19:05Z. The TP table
> is **OBSERVED on repo config** at `main` `924aeee35`, not a live-VM read. This PR changes **two grader scripts**
> (Tier 1, §3 E2) and no runtime code or config. **Public repo:** no balances. $ figures are P&L only.

## Headline (the operator's three measures)

| measure | real_money (`bybit_2` + `alpaca_live`) | paper + mirror | source |
|---|---|---|---|
| **net R, 7d** | **+1.41 R** over 9 closes (expR +0.16) | paper **+0.57 R** / 52 (expR +0.01) · mirror +1.94 R / 9 | `/api/bot/performance?window=7d` (since 10-28T18:55Z), R basis `declaredInitial` 8 of 9 |
| **net R, 30d** | **−7.36 R** / 29 (expR −0.25) | paper **−14.13 R** / 231 (expR −0.06) · mirror −0.19 R / 32 | same, `window=30d` |
| **net R, lifetime** | −155.9 R / 476 (expR −0.33; retired `vwap` carries −145.8 R) | paper −141.3 R / 1702 · mirror −36.5 R / 158 | same, `window=all` |
| **R per capital-day** (telemetry-joined subset) | 90d +0.010 (n=19) · 30d −0.257 (n=9) · 7d −0.092 (n=6): all `insufficient_n` | 90d **+0.072** (n=380) · 30d **−0.001** (n=78) · 7d **−0.015** (n=30) | `giveback_census.py`, journal dump filtered by `closed_at` per window |
| **giveback (share of peak R given back)** | 90d 98% (n=19) · 30d 135% (n=9) · 7d 116% (n=6), `insufficient_n` | 90d **92%** (n=380) → 30d **100%** (n=78) → 7d **102%** (n=30) | same |
| **TP compliance** | **1 of 7** routings (`ml_entry` passes) | paper 1/58 · mirror 1/7 · prop 0/3 | `check_tp_doctrine.py`, re-run, 75 routings / 54 legs |

The API has no `90d` window (it answers `unknown window '90d'; valid: ['24h','30d','7d','all']`), so 90d is `could_not_look`
on the API and is measured only by the census subset.

**7-day closes by account** (journal, `closed_at` ≥ 2026-10-28T19:00Z, n=61):

| account | class | n | wins | exits |
|---|---|--:|--:|---|
| `bybit_1` | paper | 38 | 13 | sl 23, tp 9, sl_cross 2, strategy_close 1, e4_time_stop_24h 1, netting_attributed 1, operator_flatten_reconciled 1 |
| `bybit_2` | **real money** | 9 | 4 | tp 2, sl 2 (one a trailed win), max_hold 2, stale_stop 1, **reconciler_filled 1**, intent_reduce_executed 1 |
| `bybit_portfolio` | mirror | 9 | 4 | identical to `bybit_2`, row for row (Stage-2 equality holds) |
| `alpaca_paper` | paper | 4 | 3 | tp 1, tp_cross 1, sl 1, sl_cross 1 |
| `ib_paper` | paper | 1 | 1 | sl_cross 1 |
| `alpaca_live`, `alpaca_portfolio`, prop books | | 0 | | no closes |

4 of the 9 real-money closes are `ml_entry` (live on `bybit_2` since 2026-11-01). The rest are one close each from the
four older legs. The week is small and flat, so the window carries little information. The questions below are
chosen by money at stake, not by this week's P&L.

---

## 0. Prior calls (Layer 0)

`review_followthrough.py --source performance-review --window-days 7`: **cohort** 18 filed in 7 d, 1 done, **5 killed**,
12 open (33% closed within 7 d). **Backlog** 31 open, 52% due, median age 14 d, **11 with no owner**. (Last week the
backlog was 69. The drop is the operator's bulk reset of 2026-10-29, "value unknown".)

The 2026-10-28 review was the first with `calls[]` and `p`. **Four of its seven items were killed by that bulk reset**
(PI-…-PVRNY2JI-0002, -0003, -0006 and PI-20261010-WQAPZD8B-0004). That is the operator's decision, so this review does
**not** re-file them. Each one's check was re-run anyway where it could be, and the result is below.

| # | call (p) | check re-run now | result | did the action happen? |
|---|---|---|---|---|
| D1 | `xrp_pullback_2h` (real money) trades inside its band after the closed-bar switch (0.55) | `live_vs_backtest.py` | still `BELOW_BACKTEST`: n=20, −12.10 R, pct **1.5** (was 1.2). Only **1** post-switch close (6807, `intent_reduce_executed`, −0.12 R) | **unresolved**, needs n ≥ 10 post-switch closes. PI-…-0001 is queued and observing |
| D2 | deep-then-loss stays ≥ 20% at n_deep ≥ 40 (30d) (0.5) | census, 30d `closed_at` filter | dtl **0.25**, but n_deep **36** < 40 | **unresolved** (leaning hit). The item was killed 10-29, so no exit-refinement unit ran |
| D3 | ict_scalp 5m silence is market structure (0.5) | harness replay Sep vs Oct | not run | **void**: killed 10-29. The family is trading again: `ict_scalp_xrp_15m` 6 closes in 7d, `ict_scalp_avax_5m` 3 |
| D4 | pullback sag is regime: ≥ 2 of 4 walk-forward folds net > 0 (0.55) | `direction_walkforward.py` artifacts | none exist | **void**: killed 10-29, the fourth review running without the M8 sweep. Tracker still flags DECAY (§1 C11) |
| D5 | the hold-vs-close gap is selection: n ≥ 20, mean dR > −0.25 (0.55) | `live_review_grade.py --live` | n=130, mean **−0.114** | **hit** by the rule as written. ⚠️ n counts reviews, not packages, so it overstates the evidence (§2 Q3; PI-20261104-PREP1104-0003) |
| D6 | IAUM cannot clear the power floor on its own evidence (0.7) | queue + evidence `n_oos` | no re-evidence unit admitted; live n still 1 (−1.47 R) | **unresolved**. PI-…-0005 is queued with no owner |
| D7 | attribution check is void until its route is fixed (0.9) | `real_money_close_attribution.py` unmodified | still **HTTP 401** on `/api/bot/db/table/trades` | **unresolved**: no fix landed, item killed 10-29. C4 ran its `analyse()` over the diag dump instead (§1) |

**Scorecard:** 7 calls · hit 1 · miss 0 · unresolved 4 · void 2. **Brier: INDETERMINATE** (1 resolved call < 10).
Series: 10-28 n_resolved 1 · 11-04 n_resolved 1.

---

## 1. CHECKS (numbers only)

**C1 — per-leg scorecard.** Real money, by leg (`/api/bot/performance` `perStrategy`):

| leg (`bybit_2` unless noted) | 7d n / R | 30d n / R | lifetime n / R / expR |
|---|---|---|---|
| `ml_entry` | 4 / +1.35 | 4 / +1.35 | 4 / +1.35 / +0.34 |
| `ada_pullback_2h` | 1 / +0.89 | 7 / **+4.31** | 18 / −3.44 / −0.19 |
| `xrp_pullback_2h` | 1 / −0.12 | 6 / **−4.77** | 20 / −12.10 / −0.60 |
| `trend_donchian_eth_4h` | 2 / −0.51 | 7 / **−4.10** | 18 / +5.69 / +0.32 |
| `trend_donchian_xrp_4h` | 1 / −0.20 | 2 / −1.22 | 8 / −1.14 / −0.14 |
| `trend_donchian_sol_prop` | 0 | 3 / −2.92 | 3 / −2.92 / −0.97 |
| `iaum_pullback_1d` (`alpaca_live`) | 0 | 0 | 1 / −1.47 |

Paper (40 strategies with a 30d close). The extremes, 30d R (lifetime n / R in brackets): worst `trend_donchian_eth_4h`
−6.24 (33 / −6.4), `trend_donchian_sol_prop` −5.63 (6 / −5.6), `uso_trend_1h` −4.39 (23 / +13.0), `xrp_pullback_2h`
−4.25 (37 / −9.3), `trend_donchian_eth` −4.17, `ict_scalp_xrp_15m` −3.65 (45 / −13.5). Best `ada_pullback_2h` **+9.59**
(51 / +7.5), `ief_pullback_1d` +6.13 (4 / +5.9), `e4_oi_shock_1h` +4.45 (8, all in 7d), `ml_entry` +3.26 (5).

**C2 — expected vs realised** (`live_vs_backtest.py`, Stage-2 legs, whole history per book):

| leg | real money | mirror |
|---|---|---|
| `xrp_pullback_2h` | **BELOW_BACKTEST** n=20, −12.10 R, pct 1.5 | CONSISTENT n=16, pct 5.0 (at the edge) |
| `ada_pullback_2h` | CONSISTENT n=18, pct 7.1 | CONSISTENT pct 16.8 |
| `trend_donchian_eth_4h` | CONSISTENT n=18, pct 51.9 | CONSISTENT pct 7.3 |
| `trend_donchian_xrp_4h` | CONSISTENT n=8, pct 27.4 | CONSISTENT pct 11.3 |
| `trend_donchian_sol_prop` | INSUFFICIENT_N n=3, −2.92 R, pct 3.6 | INSUFFICIENT_N n=3, pct 5.9 |
| **`ml_entry`** | **NO_BACKTEST**: source_run has 0 per-trade `net_r` rows | **NO_BACKTEST** |
| `iaum_pullback_1d` (`alpaca_live`) | INSUFFICIENT_N n=1, worse than every backtest trade | NO_LIVE_TRADES |

**C3 — decay (interim; no sequential instrument, row `PERF-CHECKS-SCORECARD`).** Paper expR 7d +0.01, 30d −0.06,
lifetime −0.08. Real money 30d −0.25 vs lifetime ex-`vwap` −0.06 (−10.0 R / 158). Neither is outside the C2 bands
except `xrp_pullback_2h`.

**C4 — attribution** (`real_money_close_attribution.analyse()` run unmodified over the diag journal dump, because its own
second route answers 401). Population: 132 real-money closes 2026-06-27 → 11-03 joinable to the dump (of 495 on the
wire). Decision set is 124 (8 reduce legs dropped). **Strategy exits 80.6%** (sl 72, tp 15, exit_head 5, stale_stop 4,
sl_cross 3, tp_cross 1). **Not strategy exits 17.7%** (reconciler_filled 15, operator_flatten_reconciled 4,
netting_attributed 1, intent_reduce 1, stuck_strategy_watchdog 1). Unknown 1.6% (max_hold 2: `ml_entry`'s designed
24 h time stop, which the script's map does not know). 7d: 1 of 9 is `reconciler_filled` (§2 Q2).

**C5 — cost drift: `could_not_look`.** `realized_slippage.py pull` fetched 4198 fills, then `analyze` crashed
(`KeyError: 'net_r'` in `reprice`). PI-20261104-PREP1104-0004. Last week: bybit perps 0.66 bps round trip vs 3.0 assumed.

**C6 — baselines.**
- **Live review** (since 10-28, 291 reviews on 56 packages): 34 altering calls, 29 priced. `close`: 20 priced calls on
  **3 packages**, mean dR +0.82, 1 applied. `tighten_sl`: 9 calls on 3 packages, 0 applied. Hold vs close-at-review:
  n=130 reviews, mean dR −0.11 (ESTIMATED; the close side is charged no cost).
- **Desk** (since 10-28): 116 decisions (108 no_trade, 8 propose_entry). 6 proposals priced: mean +0.01 R, minus random
  −0.90 R, **INDETERMINATE** (n=6 < 30). Promotion gate NOT_YET.
- **Per role** (`claude_role_grade.py --live`): `no_trade` counterfactual −0.39 R mean (n=13 independent), INSUFFICIENT_N.

**C7 — TP doctrine** (re-run; 75 routings / 54 legs): compliant **3** (`ml_entry` on `bybit_2`, `bybit_portfolio`,
`alpaca_paper`). Real money 1/7: `trend_donchian_eth_4h` carries a sentinel TP (`tp_r` 50), `trend_donchian_sol_prop`
an unreachable one (6 R, reached 1.9% of the time), the other four fail `tp_revision`. Prop 0/3. TP-REACH floor: 7 below,
6 reachable, 34 unmeasured of 47 declared targets.

**C8 — data coverage** (`classify_paper_records.py`, 30d journal rows, n=260): gradeable A 128, artifact B 8,
reconstructable C 17, pairs P 107. `journalTrust` `accountsKnownDivergent: ['bybit_2']`, 0 unreadable.

**C9 — grading.** Fresh: newest `reviewed_at` 2026-11-04T03:47Z, 0.6 d (limit 3 d), 4416 rows. Grade vs outcome
(1222 packages graded since 2026-08-06, joined to the journal): A 7 (100% win, outcome-leaked), B 324 (**39.2%**),
C 782 (**44.9%**), D 109 (36.7%). **`grade_drift` persists**: C beats B for the third review running.

**C10 — research pipeline** (`research_disposition.py --unread-only`): dispositioned 154, **unread 17** (last week 0),
superseded_unread 297, corpus_unreadable 0. The 17 unread are e35 results from 10-29 → 11-03 across pullback and
donchian legs. 15 are `accruing` and 2 are `infeasible` (`trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, both real-money legs).

**C11 — books.** Paper-book tracker (`bybit_1`, 1520 rows → cohort 195): book +$630.7. Recent 30d n=21, **−$5,907**; prior
+$6,538. **DECAY FLAG, second week**. Families: trend +$12,355, pullback −$11,725. Prop (`breakout_1`, 23 resolved fills):
−$205, win rate 21.7%. 11 exited at the stop, 5 have no ticket link, 1 exited past the stop.

**C12 — backlog gate.** 31 open performance-review items, each read through `review_followthrough`. **count_untriaged 0**
(each is owned, queued with a due rule, or was killed by the operator's 10-29 reset).

---

## 2. ANALYSIS

I compared 7 real-money legs and about 40 paper legs. At 5%, about 2 will look unusual by chance.

### Q1 — `ml_entry` went straight to real money on 2026-11-01. Can we tell whether it is working? *(real money, new)*

**What we know.** Its evidence record (`comms/strategy_evidence/ml_entry.json`) is a 907-trade held-out year, +0.027 R per
trade net of an 11 + 3 + 1 bps cost stack. The fixed-TP bootstrap CI is **[−0.042, +0.099]**, and the operator's bar is a
point estimate ≥ 0. Live so far: 4 real-money closes, **+1.35 R**, plus 5 paper closes (+3.26 R).
- **H-noise:** at n=4 the result is noise either way. At the backtest's per-trade spread, 4 trades at +0.34 R mean are
  well inside the range. **Survives.** It is the default.
- **H-measurement:** can the review tell when it stops working? **No.** C2 returns `NO_BACKTEST`, because the record's
  `source_run` holds a summary, not per-trade `net_r` rows. The replay file
  (`comms/research/RQ-20261101-383f-01/evidence_extend_only_c692-06_population.json`) is also a 10-key summary.
  **Tested and confirmed.** The leg is the only real-money leg with no demotion signal.
- **H-mechanics:** 3 of its 4 real-money exits are not TP/SL. Two are `max_hold`, which is its designed 24 h time stop
  (the record's backtest exits are time 285 / sl 420 / tp 202, so this is expected). One is `reconciler_filled`
  (trade 6844): the operator flattened it after the live reviewer recommended close at 14:08Z. The journal carries
  `operator_flatten_intent: true` but the label is `reconciler_filled` with `exit_reason_source: unresolved`.
  **A labelling defect, not a strategy one** (PI-20261104-PREP1104-0002, routed to health).

**p = 0.8** that ml_entry is inside its band once the band exists. **Money:** about 40 decisions a month at the
recorded expectancy is about +1 R a month expected, with a spread of several R. The risk is that a decay goes
unseen, not this week's P&L. → **E1**.

### Q2 — `xrp_pullback_2h` is still the one real-money leg below its band. Is the 10-22 fix working? *(real money)*

Pct 1.5 at n=20 (−12.1 R). The cause named last week was forming-bar decisions, and that was fixed and deployed
2026-10-22. Since then there has been **one** real-money close, an `intent_reduce_executed` at −0.12 R. So there is
nothing yet to test the fix on. The mirror leg reads pct 5.0, and paper `xrp_pullback_2h` is −4.25 R over 30d (n=12).
- **H-old-gap** (losses are pre-fix): predicts that post-fix closes track the band. Untestable at n=1.
- **H-decay:** predicts that paper, which shares the signal, keeps losing after 10-22. 30d paper is negative, but most
  of its 12 closes are before 10-22. **Not separable yet.**
- **H-noise:** pct 1.5 over 20 is unusual but not extreme across 7 legs (the expected count below p5 is 0.35).

No new action. D1's observation stands (PI-…-0001). **Money:** −12 R lifetime, and the leg trades about 3 times a month.

### Q3 — The live reviewer's "widen `close`" verdict: real signal or double-counting? *(the reviewer touches every package)*

`live_review_grade.py` printed **`close` → PROPOSE_WIDEN** (n=20, mean dR +0.82, CI95 [0.67, 0.97], hit 1.0). That is
the first action class to reach the bar that takes it off advice-only, so it is material.
- **H-real:** predicts 20 independent packages, across legs, each improved by closing.
- **H-pseudo-replication:** predicts a few packages each reviewed many times. **Tested** against
  `comms/live_review/reviews.jsonl`: the 22 `close` recommendations since 10-28 come from **5 packages**, and
  **12 of them are one package** (`pkg-5d74ca7451`, `ict_scalp_xrp_15m`, reviews every ~5 minutes 15:32–17:54Z on 10-29),
  7 more are a second `ict_scalp_xrp_15m` package, and only **3 packages** priced. **Survives; H-real is eliminated.**
- **What I did:** fixed the grader (Tier 1, this PR). `use_rules` now treats the order package as the independent unit
  (the mean dR per package), so the verdict and CI are on n_packages. `close` now reads **HOLD_SCOPE (n_packages=3 < 20;
  20 priced calls)**, with a per-package CI95 of [0.28, 1.38]. `claude_role_grade.py` keys its state on n_packages, and a test
  pins it (`test_use_rules_count_packages_not_repeated_reviews`). The calibration strata and hold-vs-close
  still count reviews (PI-20261104-PREP1104-0003), and D5's "hit" carries that caveat.
- **What is still true:** on the 3 packages, closing would have helped. That is an early signal, not evidence.

**p = 0.9** that the old verdict was an artefact. **Money:** a premature widen would let one leg's reviews decide
real-money closes on every account. → **E2**.

### Q4 — The pullback-2h family on the demo floor: decay or regime? *(paper, second DECAY FLAG)*

The tracker's recent 30d is −$5,907 on n=21 vs +$6,538 prior. Pullback cells are −$11,725 lifetime on the book and trend
cells +$12,355. By cell: `avax_pullback_2h` −$6,264 (n=9, 11% WR), `xrp_pullback_2h` −$5,387, `sol_pullback_2h`
−$2,644. **But `ada_pullback_2h` is the best paper leg over 30d** (+9.59 R, n=14) and is +4.31 R on real money.
- **H-regime:** predicts that the same family, on different coins, splits by the coin's own trend. ada vs
  avax/sol/xrp is consistent with that.
- **H-decay:** predicts that the family loses uniformly. **Contradicted by ada.**
- **H-noise:** the tracker's own note says the 2026-YTD backtest of this book was flat (−1.7 R). A flat-edge book has
  red months.

The walk-forward that would settle it (D4) was killed by the operator on 10-29 as "value unknown". **I do not re-file it.**
It is a candidate for Thursday (§3). **p = 0.6** regime / noise over decay.

### Q5 — Exits: is the giveback still rising? *(all classes)*

Paper giveback share 90d 92% → 30d 100% → 7d 102%. Last week it was 91% → 107% → 133%. Deep-then-loss 30d is 25%
(n_deep 36). The rise **flattened**. The 7d figure fell from 133% to 102% as the chop in last week's window rolled off.
- **H-regime (chop):** predicts that giveback relaxes when the market trends. It did, a little. **Survives.**
- **H-exit-path change:** predicts a step at a deploy date, independent of regime. No exit deploy is in the window.
  **Not supported.**

**p = 0.55** that 30d giveback is ≤ 105% next week. → **E5**. No new unit: D2's unit was killed 10-29.

### Q6 — `trend_donchian_sol_prop` is 0 for 9 across three books. Broken? *(real money)*

The 9 closes are **4 packages** fanned out to `bybit_1`, `bybit_2` and `bybit_portfolio`. All 4 were long and all were stopped
(10-20, 10-20, 10-21, 10-28). The backtest is n=395, expR +0.12, with a 6 R TP that is reached 1.9% of the time, so
its win rate is low. The record does not state the rate. At an assumed 25% win rate, P(4 straight losses) ≈ 0.32.
- **H-noise:** survives at p ≈ 0.3.
- **H-fidelity:** predicts that live entries differ from the harness. No join was run: n=4 cannot separate them.

**No action, because** four independent losses are ordinary for a low-hit-rate leg. The real issue is the TP, which
the doctrine says is not a real prediction (C7). → **E3**, and a Tier-3 candidate in §3.

### Surprises (A4)

1. **The "widen `close`" verdict** (Q3). It looked like the first evidence-backed scope step for the reviewer, and it was
   12 reviews of one trade. Fixed in this PR.
2. **A real-money operator flatten mislabelled `reconciler_filled`** (trade 6844 / 6845). The session contract treats
   any non-TP/SL/strategy close as a bug. Root cause is not found yet. It is filed to health with the rows named
   (PI-20261104-PREP1104-0002).
3. **17 unread research results reappeared** (last week 0). They are the e35 batch from 10-29 → 11-03. 2 of them are `infeasible`
   for real-money legs (`trend_donchian_eth_4h`, `trend_donchian_xrp_4h`). This belongs to research-ops; noted.
4. **`/api/bot/performance` has no 90d window**, although the skill's C1 asks for one. The census covers it on the telemetry
   subset only.

---

## 3. Decisions (ranked by money; each carries a pre-registered check)

| id | call | p | decision · tier | pre-registered check (`command` · rule · resolves_when) | ending |
|---|---|---|---|---|---|
| **E1** | `ml_entry`'s live R stays inside its Stage-0 band | 0.8 | build the per-trade band · T1 | `live_vs_backtest.py --leg ml_entry` · CONSISTENT/INSUFFICIENT_N = hit, BELOW = miss, NO_BACKTEST = void · per-trade rows committed | **PI-20261104-PREP1104-0001** (owner ml-review) |
| **E2** | the old `close` PROPOSE_WIDEN was pseudo-replication; per package it stays HOLD_SCOPE until n_packages ≥ 20 | 0.9 | **fixed in this PR** (grader); calibration and hold-vs-close still to fix · T1 | `live_review_grade.py --live` · at n_packages ≥ 20: per-package CI95 lower > 0 = the class has real support; ≤ 0 = it did not · n_packages ≥ 20 | this PR + **PI-20261104-PREP1104-0003** (owner perf-followup) |
| **E3** | `trend_donchian_sol_prop`'s 0/4 packages is noise | 0.7 | no action, because P ≈ 0.3 at its hit rate · — | `live_vs_backtest.py --leg trend_donchian_sol_prop` · real-money pct ≥ 5 at n ≥ 5 = hit; < 5 = miss · n ≥ 5 | none (check only) |
| **E4** | pullback-2h demo-floor sag is regime, not decay | 0.6 | candidate for Thursday; the operator killed the walk-forward 10-29 · T1 | `paper_book_tracker.py --no-append` · pullback cells' recent-30d net > $0 within 4 weeks = hit; still < 0 = miss · 2026-12-02 | candidate (manager decides) |
| **E5** | giveback has stopped rising | 0.55 | no action, because the rise flattened with the regime · — | census, 30d `closed_at` filter · share ≤ 1.05 = hit; > 1.15 = miss · next review | none (check only) |
| **E6** | the 6844/6845 label is a labeller defect, not a strategy exit | 0.8 | route to health · T1 to find, T2 to fix if runtime | the item's `clears_when` | **PI-20261104-PREP1104-0002** (owner health-review) |
| **E7** | C5 is void until `realized_slippage.py analyze` skips rows without `net_r` | 0.9 | tooling · T1 | `realized_slippage.py analyze` exits 0 on a fresh pull | **PI-20261104-PREP1104-0004** (owner perf-followup) |

The D-series calls carry forward: D1 (PI-…-0001, observing) and D6 (PI-…-0005, queued, **no owner**: the manager should give it one).

**Candidate follow-ups for Thursday (not run; `/perf-followup` is the manager's call):**
1. **TP doctrine on real money (Tier 3, proposal only):** 6 of 7 real-money routings are non-compliant.
   `trend_donchian_eth_4h` carries a sentinel `tp_r` 50, and `trend_donchian_sol_prop` a 6 R TP reached 1.9% of the time.
   Each needs a real predictive TP measured on its own record before any change.
2. **Pullback-2h family walk-forward (E4):** re-open only if the operator now sees the value. It has been the open
   question for four reviews.
3. **`ml_entry` per-trade evidence (E1):** this is the only real-money leg with no demotion signal.
4. **The reviewer's `close` class:** keep collecting. Do not widen until there are 20 packages.

## 4. Not done

- **90d per-leg API window:** `could_not_look` (the route has no 90d). It is covered by the census subset only.
- **C5 slippage:** void (E7).
- **`real_money_close_attribution.py` unmodified:** void (401). It ran over the diag dump instead, on 132 of 495
  wire rows (the dump reaches back to 06-26 only).
- **M13 insights and the sweep mirror:** not pulled this week (budget). No call depends on them.
- **Claude-channel ping:** not sent by this lane. The manager carries the result in its brief.
- **`/perf-followup`:** not run, as briefed.

<!-- PERF-REVIEW-PREP:END -->
---

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
