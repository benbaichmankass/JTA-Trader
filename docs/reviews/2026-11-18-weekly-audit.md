# Weekly audit 2026-11-18: the Alpaca reconciler closes rows whose pre-market entry is still working, so orphaned entries stack at the open (QQQ 1981 at the venue vs 2 in the journal), and last week's audit rows sat with three dead lanes

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-18` · lane `WEEKLY-AUDIT-20261118` (session_01AFoLuKqdbFM5rj92pWUEn9, dispatched by the manager, session_01AFoLuHbhd9wFuGJfWRqyoV) · window 2026-11-11T18:55Z → 2026-11-18T18:30Z · deep pass **3 DESIGN CRITICISM** (ISO week 47 mod 4 = 3). Subjects: the Alpaca flat-reconciler, chosen for this week's incident, and the work store + assistant-manager lanes, chosen for this week's follow-through stall · live reads 18:11–18:25Z: `/api/bot/*` direct, and `/api/diag/*` direct (works again this week; it returned 401 on 11-11)

## S. Scoreboard (`GET /api/bot/work/scoreboard`, 18:11Z, read_state `read`; this is a public repo, so the table gives % and PF only)

| book | inception: n · net % · PF · measured share | trailing 30 d: n · net % · PF |
|---|---|---|
| real money | 540 · −43.88 % · 0.67 · 80 % | 59 · −5.65 % · 0.71 |
| prop (2 of 3 accounts read) | — · −2.45 % (equity vs declared size) · — | 30 · +0.17 % · 1.08 (fills 28 unverified) |
| mirror | 202 · −16.77 % · 0.67 · 66 % | 63 · −0.79 % · 0.95 |
| paper | 1855 · +0.94 % · 1.01 · 43 % | 239 · −0.76 % · 0.96 |

**Would a sceptical quant believe the production legs have edge? No.** The trial ledger (11-13, 58 evidence records) counts **0 survivors in 3,760 configs** (rule: DSR > 0.95 and BHY-haircut expectancy > 0) and 31 Stage-0 passes. The production legs per `strategy_status.py` are ada_pullback_2h, ict_scalp_eth_15m, ml_entry, ml_entry_eq_struct and slv_trend_1h. None of them is a survivor. **Paper moved from −2.80 % to +0.94 % in a week** (trailing-30 d PF 0.27 → 0.96). That jump is not explained here, so it gets its own row, AUD-20261118-SCOREBOARD-PAPER-SWING.

## 0. Prior calls (17 open rows from the 11-11, 11-04 and 10-28 audits, each re-read with `work.py get`)

- **Stalled, and now we know why.** On 11-12, 15 of the 17 open rows were laned to three assistant-manager sessions. **All three are dead:** AM-OPS was archived 11-15, AM-ML was archived 11-13 (it says it reassigned its work to FRONTIER, but the rows still name it), and AM-TRADING has been idle and disconnected since 11-15. No row changed state in 6 days. **Decision:** the 15 lanes are released here (`archive-lane`, owner = manager), so tonight's week plan sees them. The class is filed as AUD-20261118-LANES-ON-DEAD-SESSIONS (271 open rows overall).
- **RESEARCH-SLO-RED** (open across 4 audits) is now `landed_unproven`. Breaches per day are down from 6–9 to **2–4**, but `research_ops_age_h` is still 31.3 h against a rule of ≤ 8, so **RESEARCH-OPS-NO-RECORD (blocked) still reproduces**. The manager should decide that blocker tonight; the row is not re-filed.
- Re-run results:
  - TP baseline **75 → 74** and compliant 7 → 12 (the call that it would grow: miss). Row still open for its detector.
  - MGC journal 27 = venue 27, so **MGC-JOURNAL-QTY is resolved and closed**. A new MGC fault is filed separately.
  - PRODUCER-OK-OVER-CNL reproduces (hit).
  - PREDICATE-FALLBACK-DRIFT reproduces (`build_research_panel.py:98`, hit).
  - AMENDMENTS-UNLOGGED: **29 → 41** (hit, worse).
  - ITERATION-ORPHANS: legs 8 → 7, ML 8/9 overdue → 3 overdue + 3 orphan, LTR 5/7 → 0 (moving).
  - RELAY-INVARIANTS-BRIDGE is re-scoped: direct access is back, so the open value is a scheduled run of the invariants.
- Footer: hit 5 · miss 1 · resolved 2 · unresolved 3 (FLATTEN-LABEL, SIZE-UP, HOLD-VS-CLOSE). Closure ratio 2/37. Brier INDETERMINATE (fewer than 10 resolved calls with a stated p). `review_followthrough`: cohort 9 filed / 4 done; backlog 17 open, 94 % past due.

## 1. CHECKS (self-tests 7/7 green; "prior" = 11-11)

| id | status | value · population | prior | positive control |
|---|---|---|---|---|
| C1 | **FAIL** | `system_invariants.py` over 9 payloads: **2 FAIL / 4 NOT-MEASURED / 6 pass**. **INV-JOURNAL-EXCHANGE:** alpaca_paper/QQQ journal 2 vs venue 1981; alpaca_portfolio (mirror)/SLV 6 vs 877 (n = 17 pairs). **INV-PROTECT-OVERCOVER:** ib_paper MGC short 27 with 70 resting stop qty in 4 groups. Venue protection on the 1981 and 877 is real: one bracket stop per fill, summing to the position. Leg ↔ row match 26/26 on Bybit; exit loop 1,687 intervals, max 44.8 s. Prop not measured (breakout_2 stale; no open prop fill). **Trace (demo, alpaca_paper QQQ):** signal → package → journal row → `exchange_flat_reconciled` close at +6.5 min with the entry still working → re-entry ×4 → all 5 entries fill 14:31–14:34Z. **It died at reconcile** | 0 FAIL / 11 NM | INV fixtures (self-test); the venue qty equals the sum of the closed rows exactly |
| C2 | fail (improving) | 12 of 86 routings compliant (real money 2/10, prop 4/6, mirror 2/10, paper 4/60); baseline 74 | 7/82 · 75 | guard STRICT findings |
| C3 | pass | 15 passed, 1 skipped | 15 | the 11-11 drop-a-leg control still applies; not re-run this week |
| C4 | pass | cost-model single owner clean (5 registered duplicates, 0 drifted) | clean | — |
| C5 | pass | stated-population guard over this report (output in the PR body) | pass | guard self-test |
| C6 | fail (improving) | 730 due; **unrouted 311 → 35**; oldest unrouted 163 → 14 d (alarm still breached); 809 open of 2,856. **271 of 855 open build rows are laned to dead sessions** | 730 / 311 / 163 d | alarm reproduces |
| C7 | could_not_look | `--capacity`: the weekly reading (80 %, 11-16 08:20Z, 58 h old) names no reset time, so the state is `reset_unknown`. Lane spend from get_session: AM-OPS $784, AM-ML $209, AM-TRADING $123 (API-equivalent, plan allowance) | instrument fixed 11-11 | — |
| C8 | 2 agree / 1 superseded | 11-11 health **H2**: running e0c1a0905b, 0 src/ and config/ diff to main → agrees. **H12** (disk to 10 % free by 11-19): now **67.8 % used**, down from 76.1 %, so the projection did not happen (acted on, or wrong) | 1 agree / 1 qualified | raw `/api/diag/status`, `version` |
| C9 | fail (improving) | breaches per day 3,3,4,2,3,2,4 (7/7 days present); open today: runnable_floor 32/72, undispositioned 15/5, theme share 0, research_ops_age 31 h | 6–9/day | — |
| C10 | pass | 21 registry entries; 1 shadow leg | 20 / 1 | self-test 7/7 planted breaks |
| C11 | watch | 5 ledgers fresh; news_decisions `could_not_look`, and the summary still prints "OK" | watch | — |
| C12 | fail | **41** unlogged SKILL/BRIEF amendments; ltr_graded 1 missing outcome (LR-20261103T1400Z); desk 230/230 graded; role_grade fresh | 29 | self-test |
| C13 | partial | (a) floor rosters bybit_1 28 · alpaca_paper 18 · ib_paper 11: **24 of 57 legs left no journal row in 7 d** (5 / 11 / 8; mostly long-only 1d trend legs), with no eval line to tell quiet from blocked (DEMO-FLOOR-NO-EVAL reproduces); 1 shadow leg, inactive. (b) learning chain **not_reached**. (c) research-ops record 31 h old (loop not observed) | partial | — |
| C14 | watch (improving) | 346 units in 7 d: 54.9 % cite a parent or map (rule ≥ 50 %, now met), 48 % structured. Sample of 5 (seed 20261118): 5/5 rules registered first; 1/5 is a lever iteration with a parent; 3/5 are new questions | 43.4 % / 57.4 % | — |
| C15 | fail → **fixed** | `roadmap_map --check` FAIL: NEWS-VETO-ARMB-READ referenced `L-NEWS`, which is not a milestone. Set to M28 in the store; re-run ok. Document index OK (1,511) | — | the FAIL itself |

## 2. ANALYSIS

**Trend (4 audits):**
- Unrouted: 166 → 311 → **35**. Oldest unrouted: 156 → 163 → **14 d**. Real improvement.
- TP compliant: 3 → 7 → **12**.
- SLO breaches per day: 8 → **3**.
- Amendments: 18 → 28 → 29 → **41**. Wrong way for 3 audits.
- Audit-row closure: 3/33 → **2/37**. Wrong way.
- Due: flat at 730.
- If nothing changes, the audit's own findings keep piling up while the pipeline it audits clears.

**Q1. Is the Alpaca qty mismatch a stale read or a false close?**
- H0 (noise / stale read): the venue snapshot lags fills.
- H1: the reconciler closes rows whose entry is still working.
- Test: the venue qty equals the exact sum of the closed rows (QQQ 1182+735+55+7+2 = 1981; SLV 794+53+19+2+2+2+5 = 877). Each row was opened pre-market (13:03–14:17Z), closed after about 6.5 min with pnl NULL, and every entry filled at 14:31–14:34Z (`alpaca_open_orders`). The same pattern shows on SPY 11-16.
- **H1 survives, p 0.9 (MEASURED on 14 of 14 alpaca `exchange_flat_reconciled` closes, 11-07..11-18).**
- Mechanism: `order_monitor.py` snapshot-flat path (~L4940) gates on position absence plus a 300 s age, and never on the entry order's state.
- A control should have caught it: INV-JOURNAL-EXCHANGE does catch it, but **nothing runs the invariants on a schedule**.

**Q2. Why did dated, laned audit rows still not move?**
- H0 (expected variation): too little time, 6 days.
- H1: the owners are gone.
- Test: `get_session` on all three lanes; all three were archived or disconnected by 11-15.
- **H1 survives (p 0.95).** The same mechanism holds 271 rows, 32 % of open work.
- No control flags a queued row with a dead lane. WSD-S5's stale view covers `in_flight` only.

**Recurrence (2b):**
- Closed this week with a detector: MGC-JOURNAL-QTY (INV-JOURNAL-EXCHANGE), FOLLOWTHROUGH-DUE-REDUCER, CAPACITY-RESET-PASSED.
- Class sweep for "an IB protection group added without cancelling the old one": TLT 11-04, then MGC 11-18. That is 1 of 3 IB positions this week; the class recurs.

**Deep pass 3: DESIGN CRITICISM.**
1. **Alpaca flat-reconciler.**
   - *Right mechanism?* No. It infers flat from position absence plus a timer (`_DEFAULT_SNAPSHOT_MIN_FILL_AGE_SECONDS = 300`), a fix for the IWM flap of 06-22. Order state is the truth: an entry that is `new`/`held` is pending, not flat.
   - "Observe first" has become fail-silent here. The close writes pnl NULL and the row disappears from open risk.
   - *What we would build today:* the reconciler reads the row's `broker_order_id` and treats a working entry as pending, and every close cancels its own working entry.
   - Row AUD-20261118-ALPACA-FLAT-CLOSE-LEAVES-ENTRY, Tier 2.
2. **Work store after the S4 freeze.**
   - The store took writes on 11-13, but the guards were not re-pointed: design § 7 says they read the API or a weekly export, and that export is deferred to S7 on 11-30.
   - Result: the store accepted `L-NEWS`, and **528 of 977 items updated since 11-10 have no export file** for CI to read. Two implementations of one register, and the guarded one is the stale one.
   - What should be deleted: nothing yet. What is missing: write-time validation.
   - Row AUD-20261118-STORE-WRITES-UNGUARDED.
3. **Assistant-manager lanes.** The handoff contract has no "return your rows" step. Releasing a lane is the act that makes work runnable, and an archived session never does it (AUD-20261118-LANES-ON-DEAD-SESSIONS).

**Surprises:**
1. Live VM CPU 100 %. The off-tick `reconciliation_loop` holds `journal_sync` for 40.7 s on average, and the tick waits on it for 36 % of its time (tick mean 55 s, max 127 s). This was noted on TICK-STAGE2-RECONCILE-OFFTICK as unmet.
2. The paper scoreboard swing (row filed).

## 3. Decisions (ranked by money at risk; every id resolves via `work.py get`)

| # | id | class · tier | p | detector | ending · due_by |
|---|---|---|---|---|---|
| 1 | AUD-20261118-ALPACA-FLAT-CLOSE-LEAVES-ENTRY | real money (alpaca_live same path) + mirror · **T2** | 0.9 M | new INV-FLAT-CLOSE-WITH-WORKING-ENTRY + reconciler test | row, `ask_operator` for the deploy · 11-20 |
| 2 | AUD-20261118-MGC-OVERCOVER | demo floor (IB class) · T2 | 1.0 M | INV-PROTECT-OVERCOVER (exists; unscheduled) | row · 11-20 |
| 3 | AUD-20261111-RELAY-INVARIANTS-BRIDGE (re-scoped) | money path · T1 | 0.9 I | scheduled invariants run: today it caught 2 FAILs that nothing else alerted on | row released to manager · 11-18 → re-date tonight |
| 4 | AUD-20261118-LANES-ON-DEAD-SESSIONS | follow-through · T1 | 0.95 M | report-only dead-lane list in the brief | row; **15 audit lanes released in this audit** · 11-19 |
| 5 | AUD-20261118-STORE-WRITES-UNGUARDED | observability · T1 | 0.9 M | write-time validation | row; **NEWS-VETO-ARMB-READ fixed in this audit** · 11-25 |
| 6 | AUD-20261111-RESEARCH-OPS-NO-RECORD | research · T1 | 0.9 M | research_slo age (exists) | blocked row: the manager decides the blocker tonight · — |
| 7 | AUD-20261118-SCOREBOARD-PAPER-SWING | observability · T1 | 0.5 I | pre-window pnl checksum | row · 11-25 |
| 8 | AUD-20261028-MGC-JOURNAL-QTY | demo floor · T2 | — | INV-JOURNAL-EXCHANGE | **closed done** (27 = 27) |
| — | TP-BASELINE · FLATTEN-LABEL · SIZE-UP · AMENDMENTS · ITERATION · PREDICATE-DRIFT · PRODUCER-OK · DEMO-FLOOR-NO-EVAL · HOLD-VS-CLOSE · HEALTH-CLOSE-LIST · NO-API-IMPORT · PIPELINE-DOC · TICK-SIZE | mixed · T1/T2 | — | own | lanes released, owner manager, for tonight's plan |

Each new row carries its `check` {command, rule, resolves_when} in its note.

Premortem for #1: if a pending-entry row stays open on an entry that never fills, the open-package gate starves the leg. That is why the fix needs a TTL or cancel-on-expiry with it.

## 4. Not done

- Not reached, each covered by a row above:
  - C13(b), the learning chain, is ML review's lane. Not reached two weeks running.
  - Prop positions (stale snapshot).
  - C3 positive control (not re-run).
  - Lane-hours.
  - The C14 sample read is shallow (key and grep based).
- Checks done: behavioural 9 (C1 recompute over live payloads, alpaca order read, trace, C8 ×2, C13(a) per-leg count, C14 sample, lane liveness ×3, C15 fix); reading 9. **This was not a whole-system audit.**

**For the operator:**
- **#1 needs one Tier-2 OK** to ship the reconciler fix once a lane has it built and tested.
- Record a usage reading with its reset time; C7 cannot compute capacity without one.
- Nothing else.
