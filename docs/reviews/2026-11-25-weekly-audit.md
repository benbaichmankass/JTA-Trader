# Weekly audit 2026-11-25: the paper book's positive headline rests on one estimated row (measured-only paper −$67.8k vs +$28.4k shown), and the 15 audit rows released last week went to a lane that died the next day, so none moved

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-25` · lane `WEEKLY-AUDIT-20261125` (session_01AFoLuKGvpUCcY4M5i6uUuF, dispatched by Manager Session 2026-11-25a, session_01AFoLuKKEyjyRMDSxQ1prHf) · window 2026-11-18T18:30Z → 2026-11-25T18:45Z · deep pass **0 OUTCOME + INDEPENDENCE** (ISO week 48 mod 4 = 0) · live reads 18:27–18:45Z: `/api/bot/*` and `/api/diag/*` direct; full trades journal paged (8,613 rows)

## S. Scoreboard (`GET /api/bot/work/scoreboard`, 18:27Z, read_state `read`; public repo, so % and PF only)

| book | inception: n · net % · PF · measured share | trailing 30 d: n · net % · PF · measured share |
|---|---|---|
| real money | 566 · −50.26 % · 0.65 · 81 % | 77 · −7.29 % · 0.68 · 100 % |
| prop (2 of 3 accounts read) | — · −3.78 % (equity vs declared size) · — | 41 · −1.13 % · 0.67 (fills 39 unverified) |
| mirror | 237 · −19.90 % · 0.66 · 68 % | 90 · −3.04 % · 0.86 · 92 % |
| paper | 1,970 · +2.51 % · 1.04 · **46 %** | 340 · +2.80 % · 1.13 · 91 % |

- **The paper sign is not measured.** Split by `provenance.classify_pnl` over the full journal (8,613 rows, closed + priced, non-backtest), the paper book is measured 908 rows / **−$67.8k**, estimated 674 / +$185.6k, unverified 197 / −$58.4k, fabricated 191 / −$31.0k. **One estimated row carries +$249k**: id 4773, ib_paper MGC, priced 262 points past its TP during the August protection failure. The 11-18 swing (−2.80 % → +0.94 %) and this week's (→ +2.51 %) are estimated rows too: 7737 (MGC, +$52.2k) and 6951 (GLD, +$16.2k), both closed 11-20. Real money: measured −$200.39 vs headline −$154.50. Fixed in this PR (the split is now published); the rest is on row SCOREBOARD-SIGN-ON-ESTIMATED.
- **Would a sceptical quant believe the production legs have edge? Mostly no.** The trial ledger (11-20, 58 evidence records) counts 4,432 configs tried, 32 Stage-0 passes and **1 survivor**: `ml_entry_eq_struct` (DSR 1.0, BHY-haircut expectancy +0.49 R). Its haircut is computed at N_used = 1, so the multiple-testing correction barely applies. The other 8 of 9 production legs per `strategy_status.py` (ada_pullback_2h, ml_entry, slv_trend_1h, tlt_pullback_1h, tqqq_trend_long_1d, the three donchians) do not survive. Real money is down 6.4 points of inception % in a week.

## 0. Prior calls (21 rows from the 10-19…11-18 audits, each re-read with `work.py get`)

- **Stalled, and why.** The 15 rows released to the manager on 11-18 were folded on 11-19 06:20Z into AM-OPS-7's backlog drain (WEEKLY-PLANNING note). AM-OPS-7 was archived at 13:17Z that day, and **none of the 15 changed state in 7 days**. That includes LANES-ON-DEAD-SESSIONS, the detector for this exact class. "Owner: manager" is not a lane. **Decision:** every one is re-dated to 11-26, so Thursday planning gives each a live lane or kills it (row HANDOFF-TO-DYING-LANE). Re-run results:
  - DEMO-FLOOR-NO-EVAL reproduces (C13).
  - ITERATION-ORPHANS is worse: legs 6 orphan + 39 overdue of 57; LTR 0 → 5 orphan.
  - AMENDMENTS-UNLOGGED is 41 → 43.
  - PRODUCER-OK-OVER-CNL reproduces for the 5th week.
  - The other 9 were not re-run.
- **RESEARCH-OPS-NO-RECORD** (open 3 audits) is re-scoped. Its clears_when (`research_ops_age_h` ≤ 8 for 3 days) cannot be met. The SLO, CLAUDE.md:246 and the research-ops skill assume 4×/day, but the routine fires once a day (`47 14 * * *`, citing the operator on 11-17). The decision is on CADENCE-CONTRADICTION.
- **Closed with evidence:**
  - ALPACA-FLAT-CLOSE-LEAVES-ENTRY: fixed under another id (#26862/#27151), **deployed** (trader 779dc01d90) and **observed** (0 Alpaca false-flat closes 11-19…25 vs 14 in 11-07…18). Detector: `tests/test_entry_order_working_hold.py`.
  - SCOREBOARD-PAPER-SWING: root-caused, see S.
  - TP-BASELINE-GROWS: a miss for 3 audits (77→75→74→73); a blocking detector would be a new gate.
  - NO-API-IMPORT-GUARD: the class is empty, 0 SDK importers (the same grep found 3 on 10-28).
- Footer: hit 10 · miss 1 · void 1 · unresolved 9. Closed+detector this week 3 (ALPACA, MGC-OVERCOVER, SWING); cumulative closure 5/44. Brier INDETERMINATE (< 10 resolved calls with a stated p). `review_followthrough`: cohort 8 filed / 2 done; backlog 21 open, 90 % past due.

## 1. CHECKS (self-tests 7/7 green; "prior" = 11-18)

| id | status | value · population | prior | positive control |
|---|---|---|---|---|
| C1 | **FAIL** | `system_invariants.py` over 9 payloads: **1 FAIL / 4 NOT-MEASURED / 7 pass**. FAIL INV-EXIT-INTERVAL: max 61.3 s vs 60 s, 1 breach in 1,573 intervals (15:00:50Z). Journal⇄venue 9/9 pairs equal (prop 2 read, breakout_2 stale). **Alpaca is not graded by any invariant**; my recompute is 4/4 alpaca_paper positions with stop + target = qty. **Trace (demo, alpaca_options_paper slv_trend_1h):** row 8569 closed `sl_cross` 17:11Z, both put legs stayed at the venue → bare-adopted 18:11Z → flattened 18:13Z, pnl NULL. **It died at close.** SH 0.5-share orphan adopted 3× on 11-24 | 2 FAIL / 4 NM | invariant self-test 72/72; the 11-18 FAILs (QQQ 1981, MGC 70) no longer reproduce |
| C2 | fail (flat) | 12 of 85 routings compliant (real money 2/9, prop 4/6, mirror 2/9, paper 4/61); baseline 73 | 12/86 · 74 | guard `--strict` rc 1 |
| C3 | pass | 15 passed, 1 skipped | 15 | **re-run:** dropping slv_trend_1h from alpaca_portfolio fails `test_alpaca_portfolio_covers_every_alpaca_live_leg` (restored) |
| C4 | pass | cost-model single owner clean (5 registered duplicates, 0 drifted) | clean | — |
| C5 | **fail → fixed** | paper headline sign flips on a provenance filter (S); this report passes `check_stated_population.py` (PR body) | pass | the split itself |
| C6 | fail (worse) | due 868; **unrouted 35 → 140**; oldest unrouted 14 → 21 d (PI-20261104-PREP1104-0003); 977 open of 3,059 | 730 / 35 / 14 d | alarm breached on both rules |
| C7 | could_not_look | `--capacity`: the weekly reading names no reset time (2nd week) | could_not_look | — |
| C8 | 1 agree / 1 qualified | 11-18 **H2** (trader e0c1a09, 0 src/config diff): re-derived at window_end 18:20Z, 0 files; the two src merges came at 19:04Z+ → agrees. **H3** "exchange_positions read_state ok for all": 2 of 14 accounts are `ok` with positions null (blind) → the check read a reducer | 2 agree | raw `git diff`, `/api/diag/exchange_positions` |
| C9 | fail (flat) | last-run breaches per day 3,4,6,2,4,3,5 (7/7 days present); red all 7 days: runnable_floor, theme_share; research_ops_age_h red 4/7 (by construction, see 0) | 3,3,4,2,3,2,4 | — |
| C10 | pass | 21 registry entries; 1 shadow leg | 21 / 1 | self-test 7/7 planted breaks |
| C11 | watch | 5 ledgers fresh; news_decisions `could_not_look`, and the summary still prints "OK" | watch | — |
| C12 | fail | **43** unlogged SKILL/BRIEF amendments (17+17+9; needed a full unshallow); ltr_graded 1 missing outcome (LR-20261103T1400Z, 3rd week); desk + role_grade pass | 41 | self-test 12/12 |
| C13 | partial | (a) floor rosters bybit_1 29 · alpaca_paper 18 · ib_paper 11: **27 of 58 legs left no journal row in 7 d** (4 / 14 / 9). 3 of those hold an open position (tlt/ief pullbacks), so 24 are quiet with no eval line to say why; 1 shadow leg. (b) learning chain not_reached (ML review's lane, 3rd week). (c) all recurring routines were re-created at 18:22Z by the handover, so `last_run` is blank; output observed: research-ops lanes 11-20, 21, 22 ×2, 24, 25 (none found 11-23); live-review lanes hourly 11-20…24 | 24 / 57 | — |
| C14 | watch | 378 units in 7 d: **79.4 %** cite a parent or map (was 54.9 %), but **structured 48 % → 37.6 %** (fell). Sample of 5 (seed 20261125): 5/5 rules registered first, 5/5 cite a parent or plan node, 2/5 are multi-arm lever designs | 54.9 / 48 % | — |
| C15 | fixed + filed | `trading-pipeline-map.md` was stale → regenerated in this PR (`pipeline_map_numbers.py`, live read). roadmap_map ok (36 milestones, 0 orphans); document index OK. CLAUDE.md:246 (research-ops 4×/day; weekly-audit "Mon 06:07Z") disagrees with the live schedule → CADENCE-CONTRADICTION | — | the stale map diff |

## 2. ANALYSIS

**Trend (5 audits, 10-28 → 11-25):**
- Unrouted 166 → 311 → 35 → **140**. Oldest unrouted 156 → 163 → 14 → **21 d**. Last week's improvement reversed.
- Amendments 18 → 28 → 29 → 41 → **43**: wrong way for 4 audits.
- TP compliant 3 → 7 → 12 → **12**: stalled.
- Due 730 → **868**.
- Real-money inception −43.9 % → **−50.3 %**.
- Audit closure 2/37 → **5/44**: moving, but only where another lane's row did the work.
- If nothing changes, the audit's own rows keep landing on lanes that die, while the fixes that do happen arrive under other ids.

**Q1. Is the paper book profitable?**
- H0 (noise): mixed provenance averages out.
- H1: the sign is set by a few estimated rows.
- Test: split net by provenance over the full journal. Measured −$67.8k (n = 908); dropping the single row 4773 turns the headline to about −$221k.
- **H1 survives (p 0.95, MEASURED).** Mechanism: `scoreboard.aggregate()` sums every priced row. The cost block is never folded; the P&L line is. Two audits headlined it.

**Q2. Why did audit rows not move again?**
- H0 (expected variation): 7 days is short.
- H1: they were handed to a lane that died.
- Test: `get_session` AM-OPS-7 (archived 11-19 13:17Z) and the 11-19 planning note.
- **H1 survives (p 0.9).** This is the 11-18 class (LANES-ON-DEAD-SESSIONS) recurring because its detector was not built.

**Q3. Is research-ops broken, or is the yardstick?**
- H0: the passes are missing.
- H1: the SLO assumes 4×/day while the cadence is once daily.
- Test: the routine's cron (`47 14 * * *`) against the SLO threshold (8 h). Lanes were seen on 6 of 7 days.
- **H1 survives (p 0.85).**

**Recurrence (2b):**
- Closed this week with a detector: ALPACA (regression test), MGC-OVERCOVER (INV-PROTECT-OVERCOVER, now pass), SWING (scoreboard test).
- Class sweep for "a close that leaves venue legs open", 7 d: 5 `orphan_adopt` rows (2 option legs, 3 SH), 0 on real money.

**Deep pass 0: OUTCOME + INDEPENDENCE.**
- *Outcome:*
  1. Alpaca working-entry reconciler (promise: no flat close while the entry works): **delivered**, 0 vs 14 (6 d; n small).
  2. Scoreboard (promise: "open with money; provenance never folded"): **harmed until today**. It folded P&L provenance, so two audit headlines quoted a paper % that measured data contradicts. Fixed in this PR.
  3. BRACKETS-ALWAYS Alpaca items (11-18/19): **not yet measurable** by the standing instrument, because no invariant reads Alpaca orders. One manual read: 4/4 covered. Row INV-ALPACA-PROTECT-BLIND.
- *Independence (reducer hunt):*
  1. `exchange_positions.read_state = ok` while positions is null (ib_live, oanda_practice), and H3 graded on it (READSTATE-OK-ON-NULL).
  2. `check_producer_liveness` prints "OK" over a could_not_look (PRODUCER-OK-OVER-CNL, 5th week).
  3. `system_invariants` money-at-risk checks cover IB and Bybit only.
  4. INV-EXIT-INTERVAL is the only exit-loop verdict, and nothing runs it on a schedule (RELAY-INVARIANTS-BRIDGE, stalled).

**Surprises:**
1. An options-overlay close does not close its legs.
2. The manager's reset created a second row for this lane (`WEEKLY-AUDIT-20261125` beside the skill's `WEEKLY-AUDIT-2026-11-25`). Both are closed by this lane.

## 3. Decisions (ranked by money at risk; every id resolves via `work.py get`)

| # | id | class · tier | p | detector | ending · due_by |
|---|---|---|---|---|---|
| 1 | AUD-20261125-SCOREBOARD-SIGN-ON-ESTIMATED | real money / all books (decision surface) · T1 (+T3 on row 4773) | 0.95 M | `test_net_is_split_by_provenance_never_folded` | **fixed in this PR** (split published); row for renderers + the 4773 decision · 12-02 |
| 2 | AUD-20261125-INV-ALPACA-PROTECT-BLIND | real money (alpaca_live) · T1 | 0.9 M | an Alpaca INV-PROTECT stem + self-test fixture | row · 12-02 |
| 3 | AUD-20261125-OPTIONS-CLOSE-LEAVES-LEGS | demo floor (production leg's overlay) · **T2** | 0.8 M | 0 `orphan_adopt` rows in 7 d | row, `ask_operator` for the deploy · 12-02 |
| 4 | AUD-20261125-EXIT-LOOP-BREACH | money path · T2 | 0.5 I | INV-EXIT-INTERVAL (exists, unscheduled) | row · 12-02 |
| 5 | AUD-20261125-HANDOFF-TO-DYING-LANE | follow-through · T1 | 0.9 M | the dead-lane list (LANES-ON-DEAD-SESSIONS) | row; **15 rows re-dated to 11-26 in this audit** · 11-26 |
| 6 | AUD-20261125-RESEARCH-OPS-CADENCE-CONTRADICTION | research · T1 | 0.85 M | research_slo age at the real cadence | row, manager decision (a) 26 h + doc fix or (b) 4×/day · 11-26 |
| 7 | AUD-20261125-READSTATE-OK-ON-NULL | observability · T1 | 0.9 M | no account `ok` with positions null | row · 12-02 |
| 8 | AUD-20261111-RESEARCH-OPS-NO-RECORD | research · T1 | — | — | blocked, re-scoped onto #6 |
| — | ALPACA-FLAT · SWING · TP-BASELINE · NO-API-IMPORT | — | — | own | **closed** in this audit with evidence |
| — | the 13 other stalled AUD rows | mixed | — | own | re-dated 11-26; lane or kill at planning |

Each new row carries its `check` {command, rule, resolves_when} in its note. Premortem for #3: if the fix closes the legs before the row, a failed row update could leave an open row on a flat venue. Close legs and row in one step, with a test.

## 4. Not done

- **Not reached** (each covered by a row above):
  - C13(b), the learning chain (3rd week).
  - C7, capacity (operator reading).
  - Re-runs of 9 stalled calls.
  - Prop breakout_2 (snapshot stale).
  - One full real-money trace (this week's trace was demo).
- **Checks done:**
  - Behavioural, 11: C1 recompute, Alpaca coverage recompute, the trace, the C3 control, the C8 re-derivation ×2, C13(a) per-leg count, the full-journal provenance split, the C14 sample, lane liveness, the C15 regeneration.
  - Reading, 8.
- **This was not a whole-system audit.**

**For the operator:**
- **#1:** should the August MGC row 4773 (+$249k estimated, priced past its TP during the protection failure) stay in the paper corpus? (Tier 3, row SCOREBOARD-SIGN-ON-ESTIMATED.)
- **#6:** please confirm the 11-17 "research-ops once a day" words, so they can be recorded and the SLO moved.
- Record a usage reading with its reset time (C7, 2nd week).
