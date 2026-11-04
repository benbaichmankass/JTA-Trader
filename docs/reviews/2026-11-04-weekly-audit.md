# Weekly audit 2026-11-04 (monthly deep) — the money-path controls fire, but last week's audit rows never moved: none had a due date, so nothing surfaced them

> **Doc status:** `live` · category `evidence` · last verified `2026-11-04` · lane `DEEP-AUDIT-20261104` (session_01AFoLuJHHNrJpWUPrhHXtjo, dispatched by Manager Session 2026-11-04a under RESET-JOBS-20261104) · window 2026-10-28T18Z → 2026-11-04T18:40Z · **all four deep passes** (monthly; ISO week 45 mod 4 = 1 would run CONSISTENCY+LIVENESS alone) · live reads 18:35Z via diag direct transport

## 0. Prior calls (2026-10-28 audit: 11 calls; 2026-10-19 audit: 11 calls)

`review_followthrough.py --source weekly-audit --window-days 7`: cohort 10 filed, 2 done, 8 open; backlog 10 open, 0 with no owner.
- **10-28 calls:** 6 hit (TP-BASELINE, NO-API, MGC-QTY, SHADOW-LEG, DUE-DOUBLED, invariant route) · 0 miss · 5 unresolved · 0 void. **Actions:** 2 fixed in that PR, 1 closed by #21007 while its row still read `queued` (closed here), 1 risk removed by hard refusals (row re-scoped), 1 moving (TP), **5 stalled**.
- **10-19 calls:** 6 rows `dropped` by the operator's 10-29 bulk reset ("value unknown") → `void` (a recorded operator decision; not re-filed). 2 open rows **stalled across 2 audits**: PROP-INVARIANT-BLIND and RESEARCH-SLO-RED.
- **Closure ratio** (closed+detector ÷ filed, both audits): 3/22. Brier: INDETERMINATE (n resolved with p = 6 < 10).
- **Why they stall (root cause, p 0.8 MEASURED):** 0 of 10 AUD-20261028 rows had a `due_by`. The manager's daily sweep (step 4b) reads rows "whose due_by has passed", so an undated row is never surfaced. The same holds across the register: **549 of 617** open rows are undated. Second cause (p 0.7 INFERRED): two rows' fix was a CI guard, which needs the operator's permission after No new gates (10-29); nobody asked. Every touched row now has a `due_by`. The two stalled 10-19 rows are re-scoped (prop → SYSTEM-AUDIT-INTEGRATION; SLO → Thursday lane).

## 1. CHECKS (self-tests 7/7 green; prior = 10-28)

| id | status | value · population | prior | positive control |
|---|---|---|---|---|
| C1 | **fail** | 11 invariants: 7 pass / **2 FAIL** / 2 not-measured. **INV-PROTECT-OVERCOVER**: ib_paper TLT 6879 holds 7443 shares; resting stops total 12743 across 2 OCA groups, targets 14886. **INV-JOURNAL-EXCHANGE**: ib_paper MGC is 14 in the journal vs 11 at the venue (12 last week). Bybit legs n=22 match. Prop: breakout_2 graded; tradeify_1/velotrade_1 `could_not_look`. Trace (real money): SOL flatten 11-03 → bybit_2 6844 closed `reconciler_filled` though `operator_flatten_intent=true` — **died at the close-reason hop** | 6/3/2 | self-test 66/66; both FAILs real (orders listed on the rows) |
| C2 | fail | 3 of 75 routings compliant (real-money 1/7, prop 0/3, mirror 1/7, paper 1/58); baseline 77 → **72** | 0/77 | the guard's STRICT findings |
| C3 | pass | 15 passed, 1 skipped | 12 passed | dropping `xrp_pullback_2h` from bybit_portfolio fails `test_bybit_portfolio_mirrors_bybit_2_exactly` (re-run) |
| C4 | pass | cost model single owner: clean (5 registered duplicates, 0 drifted) | clean | — |
| C5 | pass | stated-population guard over this report (PR body) | OK | guard self-test |
| C6 | **fail** | **577 due**; 166 unrouted (alarm breached); oldest unrouted **156 d**; 711 open of 2,591. Checklist (1,274 rows): 39 in_flight, ≥ 20 unsupported (19 with no session id, 1 archived owner), 16 owners older than list_sessions page 1; 287 landed_unproven, 272 undated | 510 / 59 / 94 d | alarm reproduces; instrument `owner_liveness.py` is a **zombie** (no CLI, reads the retired SESSIONS.json) |
| C7 | watch | weekly 91 % read 11-03 10:41Z (32 h old, before the reset); `--capacity` cannot compute (no reset time on the reading); spend on 228/713 laned rows (32 %) | 76 % / 37 % | lane-hours **not_observed** |
| C8 | pass/watch | re-derived 10-28 health **H6** from raw journal (24 closes: sl 20, live_review_close 2, tp 1, sl_cross 1): **agrees**. **H3** `ok` = 8/8 probeable accounts read — true, but the population excludes the 3 live prop accounts, and tradeify_1 shows non-zero open P&L with no positions read | 2/2 disagree | raw rows |
| C9 | **fail** | breach on 7/7 days; breaches per run **1–3 → 7–8** since 11-02 (survivors_per_month, trials_per_survivor, producer_failed_rate_24h, grade_latency_p90_d, undispositioned_24h, blocked_over_age, runnable_floor) | 7/7 | — |
| C10 | pass | 20 registry entries; 1 `execution: shadow` leg | 18 / 2 | self-test 7/7 planted breaks |
| C11 | watch | 5 ledgers fresh; news_decisions `could_not_look`, yet the summary prints "OK" (a reducer) | pass | — |
| C12 | **fail** | ltr 1 missing outcome of 43; **28** unlogged SKILL/BRIEF versions; its owning item PI-20261028-KD5SQ3JJ-0004 is `killed` | 18 | self-test 12/12 |
| C13 | partial | (a) traded 10-28..11-04: bybit_1 18/28, alpaca_paper 5/16 (+2 package-only), ib_paper 3/11 (+1); 0 rostered shadow/disabled legs (trend_donchian_1h live since #21007, 4 trades). (b) **not_reached** (learning chain is ML-FRONTIER-PREP's tonight). (c) the weekly routines are disabled and replaced by the reset protocol; its receipt lists 9 jobs; per-routine run records not paged | 1 shadow leg | — |
| C14 | **fail** | 474 units authored; 18.8 % cite a parent or lever map; 34.4 % structured designs; orphans: 36/57 strategy legs, 5/7 LTR classes, 0/9 models. Sample of 5 (seed 20261104): 0 name a parent | new | — |

## 2. ANALYSIS

**Trend (2a), 3 audits (10-19 → 10-28 → 11-04):** due 253 → 510 → 577; unrouted 23 → 59 → 166; oldest unrouted 24 → 94 → 156 d; spend-recorded 40 → 37 → 32 %; SLO breaches per run rising. Improving: TP baseline 77 → 72; shadow legs 2 → 1. If nothing changes, the unrouted alarm becomes a permanent state and these rows get bulk-dropped again, as on 10-29.

**Q1 — Is the TLT over-cover real, or a stale read?** H0: a stale read (the payload carries a `stale_read_caveat`). H1: two live groups. Test: parent 1231's children (5300 STP + 7443 LMT) and group `oca-protect-t6879` (7443 + 7443) are all `Submitted`/`PreSubmitted` in one read, and the journal says 7443. **H1 survives, p 0.9.** IB limits are not reduce-only, so once one group fills the other can open a 5300–7443-share short. `order_monitor.py` (~L11906) says a re-arm must not add on top of a surviving stop; either the entry bracket's short stop (5300) let it re-arm, or a second arm path bypasses that check. The bracket question may be SHARED-BRACKET-FIX's (its row is not on main) → row.

**Q2 — Why did MGC fall from 12 to 11 at the venue?** H0: the venue read is wrong. H1: a 1-lot exit went unjournaled. The protect group was resized to 11 (STP + LMT 11 each), so the bot itself saw 11. **H1, p 0.7.** Still Tier 2 → existing row, now dated.

**Q3 — Is the flatten mislabel a one-off?** Population: the newest 1000 journal rows hold 7 flatten-intent closes, and 2 were not converted. Both are from 11-03 (one real-money SOL flatten). Cause: the conversion is a separate manual step (`mark_operator_flattened.py --from-intent`). **Survivor: a process gap, not a code bug, p 0.8.** Detector proposed as an invariant.

**Recurrence (2b):** the 10-19 STALE-INFLIGHT class (bulk-dropped) recurs: ≥ 20 of 39 in_flight rows are unsupported. Its instrument is dead, so nothing could have caught it.

**Deep pass 0 — OUTCOME + INDEPENDENCE.** *Three strategy statuses* (built this week): `delivered`. 60 legs are classified (production 7 / testing 50 / inactive 3), `check_strategy_status.py` reports 0 findings, and both dual-book legs (iaum_pullback_1d, ml_entry) are recorded operator exceptions. *No-API hard refusals*: `delivered` (0 `import anthropic` in the repo). *Live review*: still `not yet measurable` (1 missing outcome). **Reducers found:** `owner_liveness` (silent), producer-liveness "OK" over a `could_not_look`, health H3 "8/8" over a population that excludes live prop.

**Deep pass 1 — CONSISTENCY + LIVENESS.** canonical-doc-coherence passes. Found:
- CLAUDE.md and canonical name `PIPELINE.jsonl`, but the store is a directory and `pipeline.py` treats a flat file as a defect (field beats comment → row).
- `owner_liveness.py` is a corpse that the skill pointed at (skill fixed here).
- *_ENABLED census: 10 distinct names in `src/`. All are default-on or retired except `COMMS_PUSH_ENABLED=0`, which deliberately stops sandbox git pushes (justified).
- EXCHANGE_MAP has 4 brokers, and every one is referenced by an account.

**Deep pass 2 — MODULARITY.** IB futures **tick sizes have 4+ definitions** (config/instruments.yaml, instrument_profile.py, ib_client.py constants + map, broker_bracket_reconcile.py twice) on a path that rounds stop and target prices → row. Taker-fee literals outside the cost owner: 2, both research scripts (registered single-owner check clean). Not done: edit-site counts of the last two ≥ 4-file changes.

**Deep pass 3 — DESIGN CRITICISM.** Subject: the follow-through registers, chosen by incidents (closure 3/22; 6 rows bulk-dropped; 156-d unrouted item).
- One concept ("pick this up later") has two implementations, and both grow: checklist landed_unproven 287, pipeline due 577.
- An audit row without a date or a lane is a memo with an id.
- Proposal: an audit row is born dated and laned or it is not filed, and one register owns follow-through (row, ask_operator).
- Second subject: research authoring. It produced 474 units in 7 d, while only 18.8 % iterate on a parent. That is volume over learning → row for the programme review.

**Surprises:** three "live lanes" named in this dispatch (SHARED-BRACKET-FIX, SPOTCANDLES-AUDIT, PAPER-MECHANICS-20261104) have **no row on main** at 18:40Z.

## 3. Decisions (ranked by money at risk; every id resolves via checklist.py)

| # | id | class · tier | p | detector | ending · due_by |
|---|---|---|---|---|---|
| 1 | AUD-20261104-FLATTEN-LABEL | real money · **T2** | 0.9 M | new invariant (proposed) | row, ask_operator · 11-06 |
| 2 | AUD-20261028-TP-BASELINE-GROWS | real money · T1 | 0.95 M | DEBT GROWTH (exists) + entry check | row (dated) · 11-11 |
| 3 | AUD-20261019-PROP-INVARIANT-BLIND | prop · T1 | 0.9 M | INV-PROP-POSITIONS | re-scoped to SYSTEM-AUDIT-INTEGRATION · 11-11 |
| 4 | AUD-20261104-IB-TLT-DOUBLE-PROTECT | demo floor · **T2** | 0.9 M | INV-PROTECT-OVERCOVER (fires) | row, ask_operator · 11-06 |
| 5 | AUD-20261028-MGC-JOURNAL-QTY | demo floor · **T2** | 0.9 M | INV-JOURNAL-EXCHANGE | row (dated, worse) · 11-06 |
| 6 | AUD-20261028-DEMO-FLOOR-SHADOW-LEG | demo floor · T3 | 1.0 M | strategy_status + shadowed guard | **closed** (fixed by #21007) |
| 7 | AUD-20261104-ITERATION-ORPHANS | research · T1 | 0.9 M | research_ops_checks shares | row · 11-07 |
| 8 | AUD-20261019-RESEARCH-SLO-RED | research · T1 | 0.95 M | research_slo (exists) | row → Thursday lane · 11-07 |
| 9 | AUD-20261104-AMENDMENTS-UNLOGGED | learning · T1 | 0.95 M | grade-loop amendments | row · 11-11 |
| 10 | AUD-20261104-ROWS-WITHOUT-DUE-BY | observability · T1 | 0.8 M | undated-open count in brief | row; due_by set on 13 AUD rows here · 11-11 |
| 11 | AUD-20261104-DETECTOR-IS-A-GATE | observability · T1 | 0.7 I | — (a decision) | row, ask_operator · 11-06 |
| 12 | AUD-20261104-OWNER-LIVENESS-ZOMBIE | observability · T1 | 1.0 M | CLI smoke test | row; skill C6 line **fixed in this PR** · 11-11 |
| 13 | AUD-20261028-DUE-DOUBLED → AUD-20261104-TWO-PICKUP-REGISTERS | observability · T1 | 0.8 M | unrouted alarm | rows, ask_operator · 11-07 / 11-12 |
| 14 | AUD-20261104-TICK-SIZE-OWNERS | observability · T1/2 | 0.9 M | single-owner report | row · 11-18 |
| 15 | AUD-20261104-PRODUCER-OK-OVER-CNL | observability · T1 | 0.9 M | summary names CNL inputs | row · 11-18 |
| 16 | AUD-20261104-PIPELINE-DOC-PATH | docs · T1 | 1.0 M | doc-coherence path check | row · 11-11 |
| — | NO-API importers (AUD-20261028-NO-API-IMPORT-GUARD) | spend · T1 | 1.0 M | via #11 | risk removed; detector waits on #11 · 11-06 |

Each row carries its `check` {command, rule, resolves_when}. Premortem #4: cancelling the "stale" group leaves a 2143-share hole if the 5300 stop was a deliberate partial. The root cause comes first; the cancel names the group by OCA id.

## 4. Not done

- C13(b) learning chain (ML-FRONTIER-PREP owns it tonight); C13(c) per-routine run records past page 1; C7 lane-hours; deep pass 2 edit-site counts; the DEMO-FLOOR-NO-EVAL re-measure. Each sits on its row above.
- Count: behavioural checks 7 (C1, C3 + control, C8 ×2, C13a, the trace, flatten sweep); reading checks 9. **This was not a whole-system audit.**

**For the operator:**
- #1: OK running `mark-operator-flattened --from-intent` for 6844/6845.
- #4: OK cancelling the duplicate TLT protect group after root cause.
- #5: MGC journal qty writeback.
- #11: may audit detectors land as non-blocking reports without a per-detector OK?
- #13: one follow-through register, or a funded drain of both?
