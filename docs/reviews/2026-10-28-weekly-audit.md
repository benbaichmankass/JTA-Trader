# Weekly audit 2026-10-28 — the controls pass on what they can see, and three of them could not see the failure

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-28` · lane `WEEKLY-AUDIT-2026-10-28` (session_01AFoLuNJQxJiQDru41ZvLWg, dispatched by manager session_01AFoLuJi1vLTnYv9LbP6539) · window 2026-10-21T19Z → 2026-10-28T19Z · deep pass **0 OUTCOME+INDEPENDENCE** (ISO week 44 mod 4 = 0) · run 18:49–19:10Z, partial where marked

## 0. Prior calls (2026-10-19 audit: 11 findings F1–F10 and D1)

`review_followthrough.py --source weekly-audit --window-days 7`: cohort 4 filed, 1 done, 3 open; backlog 11 open, 0 with no owner. Every finding was re-run against the store (987 rows, 2,361 items, 0 unreadable).

- **Calls:** 8 hit (F1–F8) · 0 miss · 3 unresolved (F9, F10, D1) · 0 void. Brier: **INDETERMINATE**, because last audit recorded no probabilities.
- **Actions:** 1 closed+detector (F1) · 1 closed, detector not verified (F4: 72 → 37 overdue `landed_unproven`) · 3 moving (F2 prop invariant now grades breakout_2, F3 routed-to-closed 62 → 5, F7 SLO root cause on hold PR #20970) · **6 stalled** (F5 soak items 17 → 17; F6 in_flight 6 → 32; F8 spend recorded 40 % → 37 %, worse; F9; F10; D1). **Closure ratio 1/11.**
- **Why they stall:** each is owned by `manager`, and no lane was ever dispatched for it. Re-graded on each row; nothing was re-filed. If F5, F6 or F8 stalls a second time next week, it becomes a follow-through finding.

## 1. CHECKS (self-tests 7/7 green; prior = 2026-10-19 audit)

| id | status | value · population | prior | positive control |
|---|---|---|---|---|
| C1 | **fail** | 11 invariants: 6 pass / **3 FAIL** / 2 n/a. All 3 FAILs come from one row: ib_paper MGC 6673 is 14 in the journal vs 12 at the venue, and its stop+target rest for 12. Bybit protective legs n=10 match. Trace: live-review close 6741 → journal `live_review_close` → grader **could not join it** (fixed, §2) | 8/0/1 | self-test 62/62; FAILs are real |
| C2 | fail | 0 of **77** routings compliant (real-money 0/6, prop 0/6, mirror 0/5, paper 0/60). Baseline **50 → 77** in 3 PRs on 10-27 | 0/54 | guard's own STRICT findings |
| C3 | pass | 12 passed, 1 skipped; alpaca_live ⇄ mirror differ only by the IAUM proxy | 5/5 | dropping `xrp_pullback_2h` from bybit_portfolio fails `test_bybit_portfolio_mirrors_bybit_2_exactly` |
| C4 | pass | cost-model single owner: clean (5 registered duplicates, 0 drifted) | clean | — |
| C5 | pass | stated-population guard over this report (completion test in the PR body) | OK | guard self-test |
| C6 | **fail** | **510 due**, 59 unrouted, oldest unrouted **94 d**; 1,028 open of 2,361 | 253 / 23 / 24 d | alarm `breached` reproduces |
| C7 | watch | weekly 76 % read 10-27 11:52Z (31 h old; reset 10-28 18:00Z); spend on 222/598 laned rows | 90 % / 166/411 | — · lane-hours **not_observed** |
| C8 | **fail** | 2 of 2 re-derivations disagree with the 10-24 health review: `non_tp_sl_closes` missed reconciler close 6470 (10-23), and `orphans: ok` reads a file last written 09-17 | n/a (new) | row 6470 is in the raw journal |
| C9 | fail | a breach on 7/7 days (`research_ops_not_run` 6/7, `theme_share` 6/7, `runnable_floor` 5/7) | 6/6 | — |
| C10 | pass | 18 registry entries; 2 `execution: shadow` legs | — | self-test 7/7 planted breaks |
| C11 | pass | 5 producer ledgers fresh and non-vacuous | — | — |
| C12 | fail | ltr / desk / role-grade pass; **amendments fail**: 18 unlogged SKILL/BRIEF versions, already owned by PI-20261028-KD5SQ3JJ-0004 | — | self-test 9/9 |
| C13 | fail / partial | (a) 57 rostered floor cells: bybit_1 19/31 active, alpaca_paper 1/15, ib_paper 2/11. Most quiet legs log "no breakout" evals, so they are quiet by design. `trend_donchian_1h` is rostered but shadow+disabled. 7 legs log no eval at all. (b) **not_reached** (trainer relay; ML-FRONTIER-PREP has it in flight, #20968). (c) **partial**: list_triggers page 1 holds only one-shots; cron loops not paged | — | `spy_trend_long_1d` eval reproduces |

## 2. ANALYSIS

**Trend (2a):** these series are moving the wrong way across 2 audits:
- TP routings 54 → 77, compliance flat at 0;
- due items 253 → 510;
- unrouted items 23 → 59;
- oldest unrouted item 24 → 94 d;
- spend-recorded share 40 → 37 %;
- research SLO breach days 6/6 → 7/7.

One series improved: overdue `landed_unproven` fell 72 → 37.

The registers grow faster than any reader drains them. If nothing changes, due items pass ~1,000 by mid-November.

**Q1 — Why did C1 pass last week and fail now?**
- H0 (noise): a new MGC divergence appeared this week. H1: the instrument was blind.
- Test: re-fetch with the route as documented.
- `/api/bot/positions` without `?include_paper=true` returns 1 real-money row. On that input, INV-JOURNAL-EXCHANGE **passes at n=2** and excludes 7 accounts. With the flag it grades 12 pairs and fails on MGC.
- `system_invariants.py`'s payload table named the flagless route, and `diag_fetch.sh` refuses `/api/bot/*`.
- **Survivor: H1, p 0.8.** The MGC gap dates from the 10-26 re-arm, which sized the legs to the broker's 12 and left the journal at 14. Fixed the doc here; the data fix is Tier 2.

**Q2 — Is the live-review close path delivering?**
- `live_review_grade --live`: of 124 reviews, 2 altering calls, both `no_trade_row`.
- The journal holds both closes (6741 −274.56, 6759 −2.96). Cause: `price_all` joined trades only on `review.trade_id`, which was null on both.
- **Fixed** (`live_review_counterfactual.py:435`, joins via `linked_trade_id`, test added). Closed trades gradable for holds 11 → 35.
- The 2 closes now stop at `replay_mismatch` (row).

**Surprise:** hold-vs-close-at-review is n=27, mean −0.80 R, hit 0.037. The S0 lifecycle run (#20967) says holds beat closing by +0.142 R.
- H0: the window is SL-dominated (31 of 40 closes) and the comparison is biased toward closing.
- H1: the live holds are genuinely worse.
- The discriminating test is registered on the row.

**Recurrence (2b):** the MGC naked-stop class (IB-MGC-NAKED-REARM, done 10-26) recurs as a qty mismatch, because the fix repaired the venue but not the journal. The detector exists (INV-JOURNAL-EXCHANGE), but it read the wrong route.

**Deep pass 0 — OUTCOME + INDEPENDENCE.**
- **Outcomes:**
  - *Live review* promised to make "the best decision now, priced". Graded `not yet measurable`: 0 of 2 altering calls are priced. It settles when REPLAY-MISMATCH closes and n ≥ 20.
  - *The TP-doctrine ratchet* promised that "the baseline may only shrink". Graded `no measurable effect`: 0 compliant for 22 days, and the baseline grew +27.
- **Independence** — three verdicts whose falsifier the producer can touch, or that cannot see it:
  1. The TP baseline is edited in the same diff that adds the debt.
  2. INV-JOURNAL-EXCHANGE passes on a filtered route.
  3. Health "orphans ok" is a marker-file reducer that cannot tell "no orphans" from "writer dead".

  Each now has a row or a fix.

## 3. Decisions (ranked by money at risk)

| # | id | class · tier | p | detector | ending |
|---|---|---|---|---|---|
| 1 | AUD-20261028-TP-BASELINE-GROWS | real money (0/6) · T1 | 0.95 M | guard on baseline growth vs base ref | row |
| 2 | AUD-20261028-NO-API-IMPORT-GUARD | spend · T1 + operator decision | 0.9 M | allowlist guard on 3 importers | row, ask_operator |
| 3 | AUD-20261028-MGC-JOURNAL-QTY | demo floor · **T2** | 0.9 M | INV-JOURNAL-EXCHANGE | row, ask_operator |
| 4 | AUD-20261028-DEMO-FLOOR-SHADOW-LEG | demo floor · **T3** | 0.95 M | roster re-parse | row, ask_operator |
| 5 | AUD-20261028-DEMO-FLOOR-NO-EVAL | demo floor · T1 | 0.7 I | eval-coverage instrument | row |
| 6 | LTR grader join (`no_trade_row`) | learning · T1 | 1.0 M | new test | **fixed in this PR** (merged ≠ deployed: grader runs in sessions) |
| 7 | AUD-20261028-LTR-CLOSE-REPLAY-MISMATCH | learning · T1 | 0.6 I | applied-close 15m test | row |
| 8 | AUD-20261028-HOLD-VS-CLOSE-CONFLICT | learning · T1 | 0.5 I | registered rule on the row | row (perf-followup) |
| 9 | AUD-20261028-DUE-DOUBLED | observability · T1 | 0.7 I | unrouted alarm (exists, no reader) | row, manager decision |
| 10 | AUD-20261028-HEALTH-CLOSE-LIST-MISS | observability · T1 | 0.85 M | health CHECKS self-test | row |
| 11 | invariant `positions` route | observability · T1 | 0.8 M | payload doc + skill C1 line | **fixed in this PR** |

Each row's `check` is on the row. Premortem for #3: rewriting the qty hides a real 2-lot partial fill that was never journaled, so the root-cause option comes first.

## 4. Not done

- **Not reached:** C13(b) learning chain, C13(c) cron-loop run records (list_triggers past page 1), F10 re-measure, lane-hours (C7). All are covered by ML-FRONTIER-PREP and the rows above.
- **Prop:** tradeify_1 and velotrade_1 are `could_not_look` (AUD-PROP-VENUE-POSITIONS…).
- **Count:** behavioural checks 6 (C1, C3, C8, C13a, the trace, the grader); reading checks 7. This was not a whole-system audit.

**For the operator:**
- #4: un-shadow `trend_donchian_1h` on bybit_1, or retire it.
- #3: OK the MGC 6673 journal qty writeback after root cause.
- #2: keep or disable each of the 3 Anthropic SDK importers.
- D1 (last audit) is still unanswered.
