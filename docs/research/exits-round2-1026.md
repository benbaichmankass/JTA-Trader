# Exits round 2: what the 2026-10-25 grade says, and the units it earns (2026-10-25)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

Lane `EXITS-ROUND2-1026` (Tier 1; dispatched by Manager Session 2026-10-25). Question: from the exit / trade-management results graded in `comms/research/grading/RESULTS-GRADE-1025.json` (#19997) and the results landed since 2026-10-22, what is the second round of pre-registered variants worth running? Rule 2026-10-22: a first-test fail is diagnosed and varied, never retired. No family is retired here.

## 1. Population (who has a verdict)

The grade covers 67 units of six families (pass 9, fail 47, underpowered 9, indeterminate 2). The ones that are exit / active-trade-management by what they vary (my classification; the grade file has no such column): **29**, namely eba2-01..15, 4b82-10..17, 4b82-22/-23, 7c2b-11, 326f-08, 4b82-03, 4b82-07. Of those **3 pass** (eba2-01, eba2-04 = the giveback metric ranks giveback; 4b82-14 = cold-vol window), **24 fail**, **2 underpowered** (4b82-03, 4b82-07). The other 38 units vary entries, direction filters, models or prop-pace baskets and are out of this lane; 7 of the 9 underpowered ones are among them (see § 3).

Landed since: f08c-01..22, 4ef5-01/-02, a1f3-*, 1d5c-*, 8961-01, 09a6-01 (pass), 09a6-02 (indeterminate), 09a6-03 (fail), 09a6-04 (indeterminate), 1eb9-01 (fail). The 10-22 batch's per-lever diagnosis already exists (`exit-failed-levers-diag-2026-10-24.md`); this note does not repeat it.

## 2. Did the design fail or the edge? (MEASURED, 35 candidate arms of the 13 failed eba2 units)

Method: the committed per-arm trade emits (`comms/research/RQ-20261022-eba2-*/*/arms/`), paired on (leg, entry_time, direction), a side missing from one arm counted 0 R, month-block bootstrap CI (1000 resamples), minimum detectable effect (MDE) = 2.487 x paired sd / sqrt(n) (one-sided 0.05, power 0.80). Function: `scripts/research/pool_arm_diff.py`. Single leg, harness fills a stop at the stop price (stated in the earlier diagnosis).

| class | arms | reading |
|---|--:|---|
| CI entirely below 0 | 7 | **edge failed**: eba2-07 UB (-0.148 R/trade), 08 MB (-0.032) and UB (-0.050), 12 P33 / PT, 14 P33 / PT |
| CI contains 0, MDE <= 0.02 | 7 | **resolved null** at the registered bar: eba2-10 F30 / S30, 12 P25, 13 P25, 14 P25, 15 M3 / M5 (best positive: eba2-15 M3 +0.0057 R/trade, CI [0.000, 0.013], 4 of 275 trades changed) |
| CI contains 0, MDE > 0.02 | 21 | **design failed**: one leg cannot tell (MDE 0.028 to 0.125 R/trade against a 0.02 bar), e.g. eba2-07 MT +0.011 [-0.047, +0.065] at MDE 0.100 |

So the grade's 13 eba2 FAILs are not one thing: about 40% of the candidate arms are unresolvable at the registered bar, and the unconditional 50% bank / tight trail lose outright. The selective arms are the open question, and they are the ones a single leg cannot answer. Pooled over ada + xrp (n 796) the 50% bank MB reads -0.031 R/trade CI [-0.060, -0.004] (edge failed at that dose and that 53%-of-trades selectivity), the tight arm MT -0.007 [-0.051, +0.043] at MDE 0.072 (unresolved).

Not measured here: 4b82-10..17, 4b82-22/-23, 7c2b-11, 326f-08 (no kept arm emits under `comms/`), so no edge-or-design call is made for them; they keep the earlier diagnosis.

## 3. The 9 underpowered units, and whether a pooled or longer design reaches the floor

Floors are the grade's (two-sample, one-sided, sd from the baseline arm); the repo's `required_n` is two-sided and about 27% higher.

| unit | pooled n_B vs floor per arm | exit? | does a pooled / longer design reach the floor? |
|---|---|---|---|
| 4b82-03 squeeze 1h exits | 6891 vs 9488 | yes | yes: 16 symbols disjoint from the first 6 (about 1150 baseline trades per cell): **d7e6-08**. WIDE is already being replicated by 71e8-01 and is not re-run. |
| 4b82-07 trend 1h day-flat | 8896 vs 8908 (12 short) | yes | yes: 14 disjoint symbols (about 1480 per cell): **d7e6-09** |
| 4b82-01 trend 1h slow / ADX | 8892 vs 9189 | no (entry) | yes, by one or two more cells; not authored here (prop-pace entry lane), filed in the pipeline |
| 4b82-05 trend 2h slow / ADX | 4520 vs 8385 | no (entry) | about 12 cells at the same density; filed |
| 4b82-06 trend 4h long / ADX | 2298 vs 7741 | no (entry) | about 20 cells; filed |
| 4b82-02 pullback 1h direction | 4951 vs 17668 (sd 1.89 R) | no (entry) | about 3.6x the trades: a large basket; filed with that caveat |
| 7c2b-02, -03 daily Donchian (equities) | 256 vs 4740; 243 vs 6422 (sd 1.96 / 2.28 R) | no | **no**: 18-26x the trades at a 0.1 R bar; daily equity history cannot supply that. The question needs a bigger-effect bar in its own new unit, not a pool. Filed. |
| 7c2b-12 breakout_2 sizing | 517 vs 785 (declared d = 0.10) | no | more prop rulesets or a longer sizing-sim window; filed |

## 4. Round-2 units (all dry-run `would_dispatch` with `dispatch_queue.py`; the two pooled reads are gated on their inputs by design)

| id | what | why it is not a duplicate |
|---|---|---|
| RQ-20261025-d7e6-02..06 | 25% bank at +1 R only where P(big giveback) >= 0.7, vs unconditional bank and random flag, one unit per pullback-2h leg (ada, xrp, eth, sol, avax) | 9a7e-* tests the TIGHTEN gate; this is the node `P1-RG1025-giveback-trigger-variant`'s bank twin at the dose the pooled evidence says (25%, not 50%) and a selective threshold |
| RQ-20261025-d7e6-07 | pooled paired read of -02..-06: bar 0.03 R/trade (MDE about 0.02 at n 1900, sd 0.37 MEASURED) | the decision unit; one leg cannot resolve the bar |
| RQ-20261025-d7e6-01 | pooled paired read of 9a7e-01/-02/-03 (bar 0.07 R/trade; sd 0.82 MEASURED, n about 1170) | 9a7e's per-leg rule sits below its own MDE (its own power note says so); this reads the same emits pooled |
| RQ-20261025-d7e6-08 | squeeze 1h BE1 / ST12 on 16 disjoint symbols | 4b82-03 was underpowered; 71e8-01 covers WIDE only |
| RQ-20261025-d7e6-09 | trend 1h FLAT / FLATE / CONF on 14 disjoint symbols | 4b82-07 was 12 trades short |
| RQ-20261025-d7e6-10 | A2 flow grade from the open-interest era (2021-12-15) plus three roster legs | 09a6-02 was INDETERMINATE: OI history starts 2021-12-01, so four of six legs fell under the 80% coverage rule and 471 trades < 600. Floor from the MEASURED sd 0.0349 nats/trade is 2390 trades; the six legs alone give about 2000 |
| RQ-20261025-d7e6-11 | C1 chooser with arms A, D, M only | 09a6-04 was INDETERMINATE: 14.2% of entries excluded by the join (> 10%). MEASURED on its emits: A,D,M excludes 8.95%, 2604 joined trades. The chooser collapsed to arm A on every trade, so a second collapse closes entry-bar arm choice |

Programme 01: node `P1-RG1025-giveback-trigger-variant` now follows `d7e6-07`; new nodes `P1-ATM-pooled-tighten-gate-read` and `P1-ATM-remaining-move-flow-variant`.

## 5. Looked at and deliberately not authored

* **f08c-13 PASS** (ADX-loss trail M25_35 on `trend_donchian_ada_4h`: 63.67 R vs 59.92 R, >= 5 of 6 folds): +3.75 R over 6.25 years is about 0.6 R a year on one leg. A confirmation on the four sibling legs would pool about 850 trades against a paired sd near 0.25 R, MDE about 0.021 R/trade against an effect near 0.015 R/trade. It could not resolve the effect and the effect would not move the book. Recorded, not queued.
* **09a6-03 (B1 remaining-move head)** failed on EDGE, not design: 2558 trades / 50,926 states, 1 of 6 folds beat Q0, tau-0.5 coverage 0.617 against 0.5, and the pulled-in TP earned 51.2 R against 409.6 R as traded (mean diff -0.140 R/trade, CI [-0.188, -0.092]). It is varied only after A2 shows flow carries exit information (programme node above), not re-run on price.
* **1eb9-01** failed to confirm f08c-22's pass at bar 24 on the prop legs (R2 gain -0.091, log-loss -0.057, 2-3 of 6 folds): the bar-24 log-loss-only pass stays a lead.

## 6. Tier-3 notes

None. Every unit edits no config and places no order; nothing here argues for or against a live change.
