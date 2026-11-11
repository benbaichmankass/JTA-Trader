# Weekly audit 2026-11-11: every live position is protected at the venue, but no book makes money, and last week's 17 audit rows did not move

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-11` · lane `WEEKLY-AUDIT-20261111` (session_01AFoLuLZUWddKKncPqapt9k, dispatched by Manager Session 2026-11-11a under reset 2026-11-11, `config/reset_protocol.yaml` job `weekly-audit`) · window 2026-11-04T18:40Z → 2026-11-11T18:55Z · deep pass **2 MODULARITY** (ISO week 46 mod 4 = 2) · live reads 18:45–18:52Z through `/api/bot/*` direct and the vm-diag relay (#24898, #24899, #24900), because diag direct returned 401 after the token rotation

## S. Scoreboard (`GET /api/bot/work/scoreboard`, 18:49Z, read_state `read`; this is a public repo, so it gives % and PF only and no account amounts)

| book | inception: n · net % · PF · measured share | trailing 30 d: n · net % · PF |
|---|---|---|
| real money | 510 · −37.75 % · 0.68 · 78 % | 31 · −6.43 % · 0.70 |
| prop (3 accounts) | — · −2.65 % (equity vs declared size) · — | 27 · −0.99 % · 0.60 |
| mirror | 168 · −16.86 % · 0.63 · 60 % | 34 · −1.34 % · 0.85 |
| paper | 1759 · −2.80 % · 0.91 · 41 % | 198 · −8.58 % · **0.27** |

**Would a sceptical quant believe the production legs have edge? No, not by the repo's own bar.** All 6 production legs (`strategy_status.py`) trade below DSR 0.95. Three are on recorded DSR probation: trend_donchian_xrp_4h 0.023, ada_pullback_2h 0.254, trend_donchian_sol_prop 0.340. ml_entry is an operator baseline exception at 0.839. The trial ledger (11-06) counts **0 survivors in 3,457 configs**. These figures are measured, but the probation record is a claim in the `config/accounts.yaml` comments.

## 0. Prior calls (the 11-04 audit had 16 calls, plus the open 10-28 and 10-19 rows; all 17 rows re-read with `work.py get`)

- **Stalled: 15 of 17 rows are open, and none has changed state since it was filed.** 13 are past due, even though last week's fix gave every row a `due_by`, so a date alone did not move them. Cause: the operator's 11-07 usage cut paused the backlog drain until the 18:00Z reset (p 0.7 INFERRED). Separately, **DETECTOR-IS-A-GATE stayed `queued` for 5 days after the operator answered it** ("Yes, non-blocking OK", 11-06). **Decision:** that row is closed here with the answer. The two detector rows it unblocked (TP-BASELINE-GROWS, NO-API-IMPORT-GUARD) are re-dated as report-only work. The ranked list goes to the general/backlog lane. Class row: AUD-20261111-AUDIT-ROWS-NOT-LANED.
- **RESEARCH-SLO-RED is stalled across 3 audits.** It goes to Thursday 11-12 planning as a lane, or it is killed with a reason. It is not re-filed.
- Graded: hit 7 (TP-BASELINE worse, AMENDMENTS worse, SLO-RED, PRODUCER-OK, DUE-DOUBLED, PIPELINE-DOC, TICK-SIZE) · resolved 3 (TLT-DOUBLE-PROTECT and PROP-INVARIANT were already done; MGC qty 11 = 11, source unconfirmed) · moving 3 (ITERATION, UNDATED, TWO-REGISTERS) · unresolved 4. Closure ratio (closed+detector ÷ filed): 3/33 · Brier INDETERMINATE (fewer than 10 resolved with p) · `review_followthrough`: cohort 11 filed / 2 done; backlog 17 open, **88 % past due** (it read 0 % before the fix in this PR).

## 1. CHECKS (self-tests 7/7 green; "prior" = 11-04)

| id | status | value · population | prior | positive control |
|---|---|---|---|---|
| C1 | **pass (manual)** | 17 of 17 open positions on 5 venue accounts match the journal on qty. Each has a venue SL and TP at full qty: real money bybit_2 2/2, mirror 2/2, bybit_1 5 symbols / 6 rows (ETH 2.35+2.89 = 5.24), ib_paper 4/4 with one OCA group each (**TLT double cover gone**), alpaca_paper 3/3 bracket legs `held`. exit loop `fresh`, 0 breaches over 73 intervals. Prop: 3 accounts, positions `null` (phone feed) → `could_not_look`. `system_invariants.py` ran on positions + prop only (0 FAIL / **11 NOT-MEASURED**): relay output cannot feed it (row). Trace (demo, bybit_1 SOL 7070): package → journal → venue SL/TP whose ids equal the journal's `sl_order_id`/`tp_order_id` → **open, so the trace stops at "protected"** | 2 FAIL | TLT/MGC FAILs from 11-04 re-checked on the same rows |
| C2 | fail | 7 of 82 routings compliant (real money 1/6, prop 1/9, mirror 1/6, paper 4/61); **baseline 72 → 75** | 3/75 | the guard's STRICT findings |
| C3 | pass | 15 passed, 1 skipped | 15 | removing `ada_pullback_2h` from bybit_portfolio fails `test_bybit_portfolio_mirrors_bybit_2_exactly` (re-run, then restored) |
| C4 | pass | cost-model single owner: clean (5 registered duplicates, 0 drifted) | clean | — |
| C5 | pass | stated-population guard over this report (output in the PR body) | pass | guard self-test |
| C6 | **fail** | **730 due**; 311 unrouted (alarm breached); oldest unrouted 163 d; 800 open of 2,700 items | 577 / 166 / 156 d | alarm reproduces |
| C7 | **fail (instrument)** | `--capacity` said **KEEP 5 LANES** from a 117 h-old 68 % reading taken 41 min after its reset had passed. **Fixed here** (`reset_passed`). Lane-hours `not_observed` | 91 % | 2 new self-test cases |
| C8 | pass/watch | re-derived 11-04 health **H2** against today's state: trader 8a76e1343, web-api = main HEAD, 0 src/config diff, **agrees**. **H3**: prop is still read as `null` by every broker route, so its "8/8" population still excludes the 3 live prop accounts | 1 agree / 1 qualified | raw `version` + `exchange_positions` |
| C9 | **fail** | breached on 7/7 days; breaches per day 6, 6, 7, 7, 8, 9, 8; research-ops record 38.7 h old | 7/7 | — |
| C10 | pass | 20 registry entries; 1 shadow leg (`vwap`, status inactive) | 20 / 1 | self-test 7/7 planted breaks |
| C11 | watch | 5 ledgers fresh; news_decisions `could_not_look` while the summary still prints "OK" (row PRODUCER-OK-OVER-CNL) | watch | — |
| C12 | fail | **29** unlogged SKILL/BRIEF amendments; `ltr_graded` is `could_not_look` under `--live` | 28 | self-test 12/12 |
| C13 | partial | (a) floor rosters: bybit_1 30, alpaca_paper 17, ib_paper 11 legs; 0 non-retired shadow legs; refusals are logged (slice_budget_exhausted, risk_refused, both seen in the journal tail). Per-leg 7-day trade counts **not_reached** (the journal relay is truncated). (b) learning chain **not_reached**. (c) the research-ops trigger fired at 11:20Z, but **no pass record** since 11-10 03:25Z (row) | partial | — |
| C14 | watch (improving) | 251 units: 43.4 % cite a parent or map (rule ≥ 50 %), 57.4 % structured; orphans: legs 8/60, LTR 5/7; **ML 8/9 overdue**. Sample of 5 (seed 20261111): 5/5 rules registered first, 2/5 have a diagnosis and a design | 18.8 % / 34.4 % | — |

## 2. ANALYSIS

**Trend (3–4 audits):** due 253 → 510 → 577 → **730**; unrouted 23 → 59 → 166 → **311**; oldest unrouted 24 → 94 → 156 → 163 d; TP baseline 77 → 72 → **75**; amendments 18 → 28 → 29; SLO breaches per day climbing (1–3 → 8). Improving: C14 shares, leg orphans 36 → 8, money-path invariants (2 FAIL → 0 on the rows read). If nothing changes, unrouted passes 400 by the next audit and the follow-through store becomes a write-only log.

**Q1. Did C1 pass because protection is real, or because the read is partial?** H0 is a stale or partial read: the relay truncated bybit_1's batch, and IB orders carry a stale-view caveat. H1 is that the protection is real. Test: each real-money and mirror account was re-read alone (#24899, untruncated), and each IB OCA pair was matched to the venue qty. **H1 survives for the 14 non-prop accounts (p 0.9).** Prop remains unobserved, and that is the blind spot that matters most for money.

**Q2. Why did dated rows still not move?** H0 (expected variation): the 4-day usage cut. H1: no owner between audits. Test: before the cut, BACKLOG-DRAIN-20261106 closed 2 AUD rows; after it, nothing moved, and a row whose decision had already arrived was never closed. **Both hold** (H0 explains the timing, p 0.7; H1 explains the answered row, p 0.8). Mechanism: the follow-through instrument read 0 % due, so no control could have flagged the stall. Fixed in this PR.

**Recurrence (2b):** the "reducer over a could_not_look" class recurs 3 times this week: follow-through due% (fixed), producer-liveness "OK" (open), and capacity computed over a stale reading (fixed). Class sweep: grep found 3 instances among the 14 instruments run here. Each fix carries a self-test case.

**Deep pass 2: MODULARITY.** *Edit sites.* #24657 (TELEGRAM-TRIM) took 10 runtime edits for one concept, because each of 5 `scripts/ops` callers passes its own `source=` label. A default on the helper would have made it 1–2 edits; this is noted, with no row (low risk). #24596 (size-up to the venue minimum) needed 4 runtime files for one policy. The policy is an opt-in flag (`size_up=True`) at 4 call sites, and 2 entry-order callers (`pairs_executor.py:1462`, `coordinator.py:3025`) do not pass it. That is filed as a question, not a bug. *Definitions per concept.* The reconciler/superseded KPI predicates have 4 definitions. **`build_research_panel.py`'s fallback has drifted** (`setup_type='adopted_orphan'` against the canonical `strategy_name IN ('orphan_adopt')`), which silently changes a research population whenever the import fails. IB tick sizes are unchanged (row due 11-18). The cost model is clean.

**Surprises:** (1) The work store's `checklist.py` prints "wrote docs/…/X.json", but the write goes to the store and the file is untouched. That is cosmetic, so no action. (2) The paper book's trailing-30-day PF is 0.27 on n 198. Grading that belongs to the performance review, so it gets no row here.

## 3. Decisions (ranked by money at risk; every id resolves via `work.py get`)

| # | id | class · tier | p | detector | ending · due_by |
|---|---|---|---|---|---|
| 1 | AUD-20261111-RELAY-INVARIANTS-BRIDGE | money path · T1 | 1.0 M | extractor self-test | row · 11-18 |
| 2 | AUD-20261028-TP-BASELINE-GROWS | real money · T1 | 0.95 M | report-only entry-growth line (now allowed) | row re-dated · 11-18 |
| 3 | AUD-20261104-FLATTEN-LABEL | real money · T2 | 0.8 M | INV-FLATTEN-INTENT-LABELLED | row re-dated · 11-14 |
| 4 | AUD-20261028-MGC-JOURNAL-QTY | demo floor · T2 | 0.7 I | INV-JOURNAL-EXCHANGE | row, close on a fresh row-6673 read · 11-14 |
| 5 | AUD-20261111-SIZE-UP-AT-CALLERS | order path · T1 → T3 | 0.5 I | caller-intent test | row (investigate; change = ask_operator) · 11-18 |
| 6 | AUD-20261111-RESEARCH-OPS-NO-RECORD | research · T1 | 0.9 M | research_slo age (exists) | row · 11-13 |
| 7 | AUD-20261019-RESEARCH-SLO-RED | research · T1 | 0.95 M | research_slo (exists) | Thursday lane or kill · 11-12 |
| 8 | AUD-20261104-ITERATION-ORPHANS | research · T1 | 0.9 M | research_ops_checks | row re-dated · 11-18 |
| 9 | AUD-20261111-PREDICATE-FALLBACK-DRIFT | research data · T1 | 1.0 M | report-only single-owner | row · 11-18 |
| 10 | AUD-20261104-AMENDMENTS-UNLOGGED | learning · T1 | 0.95 M | grade-loop amendments | row re-dated · 11-18 |
| 11 | AUD-20261111-AUDIT-ROWS-NOT-LANED | observability · T1 | 0.8 I | followthrough due% | row · 11-14 |
| 12 | AUD-20261111-FOLLOWTHROUGH-DUE-REDUCER | observability · T1 | 1.0 M | 2 self-test cases | **fixed in this PR** (landed_unproven → done on merge) · 11-12 |
| 13 | AUD-20261111-CAPACITY-RESET-PASSED | spend · T1 | 1.0 M | 2 self-test cases | **fixed in this PR** · 11-12 |
| 14 | AUD-20261104-DETECTOR-IS-A-GATE | observability · T1 | 1.0 M | — | **closed** (operator answer of 11-06 recorded) |
| — | PRODUCER-OK-OVER-CNL · OWNER-LIVENESS-ZOMBIE · PIPELINE-DOC-PATH · TICK-SIZE-OWNERS · ROWS-WITHOUT-DUE-BY · TWO-PICKUP-REGISTERS · NO-API-IMPORT-GUARD | obs/docs · T1 | — | own | rows noted / re-dated · 11-18 |

Each row carries its `check` {command, rule, resolves_when} in its note. Premortem #5: if sizing pairs legs up to the venue minimum were "fixed" blindly, it could unbalance a hedge. That is why the row is an investigation and why any change goes to the operator.

## 4. Not done

- C13(a): per-leg 7-day trade counts (the journal relay is capped at about 55 KB). C13(b): the learning chain (ML-FRONTIER-PREP's job). C1: the prop positions read and `system_invariants` over relay payloads (row #1). C7 lane-hours. C8 against the 11-11 health review (it runs at 19:11Z, after this audit). All of these sit on rows above.
- Checks done: behavioural 8 (C1 recompute, 2 untruncated real-money reads, trace, C3 plus its control, C8 ×2, C14 sample); reading 10. **This was not a whole-system audit.**

**For the operator:** none of these needs a new decision. Already with the manager: update the `DIAG_READ_TOKEN` environment secret, and record this week's usage reading.
