# Weekly planning pre-read 2026-11-04 — 577–583 pipeline items due, 166–176 unrouted, capacity at 0% after the reset, and the operator's open asks from five reviews

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-04` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `WEEKLY-PLANNING` pre-read (session_01AFoLuMqvFfUd8mRSRBNiuy, dispatched by Manager Session 2026-11-04a, session_01AFoLuHgZaSYnm9avjeZE33)

> **What this is.** Part (A) "Prepare, lean" of weekly planning (manager SKILL § "Weekly planning (Wednesday) and the weekly cycle", § "Review
> follow-through" steps 0–4). The operator moved planning from Thu 06:17Z to tonight (2026-11-04 ~22:05Z). **Facts only**: every number names
> its population; merged / deployed / observed are kept apart; anything that is a reading rather than a measurement is marked
> *[lane reading]*. **No priorities are drafted** — section 4 lists open questions only. Gates this adds or changes: none.
>
> All commands were run on `origin/main` @ `d8a34e41b` (2026-11-04, after #22908). The clone is shallow (oldest commit 2026-11-04), so every
> "opened in 7 d" flow count below that depends on git history reads **COULD NOT LOOK**, not 0.

---

## 0. Follow-through numbers (step 0)

`python3 scripts/ops/review_followthrough.py --window-days 7`, verbatim:

```
REVIEW FOLLOW-THROUGH  as of 2026-11-04  window 7 d  closed-within 7 d
POPULATION: 2618 pipeline items (store read, 0 unreadable) + 1303 checklist rows; source classified from id/origin/title text (see SOURCES)

source             | cohort(filed 7d): filed done kill open ≤7d | backlog(now): open due% med-age no-owner
--------------------------------------------------------------------------------------------------------
perf-followup      |                 3    2    0    1  67% |                 9  56%      23        2
performance-review |                23    1    5   17  26% |                36  56%     8.5       15
frontier           |                22    8    6    8  64% |                18  33%    10.5        1
ml-review          |                 6    0    2    4  33% |                14  50%      17        0
health-review      |                14    3    0   11  21% |                89  58%      66       46
weekly-audit       |                21    3    0   18  14% |                20   0%       0        0
programme-review   |                15    3    3    9  40% |                14  36%       3        2
research-ops       |                48   12   14   22  54% |                64  66%    10.5       17
ltr                |                30    7    1   22  27% |                38  16%       7        3
desk               |                71   13    4   54  24% |                74  32%       5       17
```

Arithmetic (this lane): this week's cohort = **253 filed, 52 done, 35 killed, 166 still open** (sum of the cohort columns). The `no-owner`
column sums to **103** over the current backlog; step 2 requires it to read 0 for this week's cohort after planning.

Oldest open per source (from the same run): health-review `BL-20260525-005` (163 d), ml-review `MB-20260712-SHADOW-LOG-HISTORY` (115 d),
performance-review `SRQ-20260715-REALMONEY-ALLOC-BENCHMARK` (112 d, no owner), perf-followup `PI-20261011-YJAYF7GD-0001..0004` (24 d, intent_reduce
reduce-leg accounting), research-ops `PI-20261013-HOPS1447-0003` (22 d), programme-review `DATA-DERIV-ARCHIVE` (21 d; the operator decided
"Schedule it" tonight — § 3).

## 0b. BACKLOG

**BACKLOG — due 577–583 · unrouted 166–176 · open pipeline 711–736 · checklist overdue 113 · oldest unrouted 156 d · opened vs closed 7 d: opened COULD NOT LOOK / closed 274 · last week's drain: not yet reported.**

| source | due | unrouted | other | population / note |
|---|---|---|---|---|
| weekly audit C6 (`2026-11-04-weekly-audit.md` L22) | 577 | **166** (alarm breached) | oldest unrouted 156 d; 711 open of 2,591 | prior week 510 / 59 / 94 d. Checklist (1,274 rows): 39 in_flight, ≥ 20 unsupported, 287 landed_unproven, 272 undated. Instrument `owner_liveness.py` is a zombie (reads the retired SESSIONS.json) |
| health H15 (`2026-11-04-health-review.md` L38) | 577 | **166** | gate 274 (prior 87) | "274 gate items are untriaged. BACKLOG-DRAIN-20261104 owns the register" (§ 4) |
| `checklist_daily_measure.py` (run now) | pipeline 583 | 176 | open 736 | 1,303 rows, 623 non-terminal: blocked 20 · in_flight 35 · landed_unproven 281 · queued 287 · done 535 · dropped 145. **OVERDUE 113**, due today 15, no date 220, landed_unproven with observation due 100. Research units queued, not run: 222 of 1,819 |
| ml C9 `backlog_coverage` | — | — | — | not separately read by this lane; the walk-through's MODEL section reports `ML-LEARNING-LEDGER` queued after two refreshes and `LIVE-DECAY-MONITOR` queued 19 d |
| performance backlog gate | — | — | — | not separately read by this lane; follow-through table above shows performance-review 36 open, 56% due, 15 no-owner |

The audit/health figures (577 / 166) and the daily measure (583 / 176) differ by 6 due and 10 unrouted: different read times on the same
store, not a contradiction (both are MEASURED; the later read is the daily measure).

**Last week's drain:** row `BACKLOG-DRAIN-20261104` is `in_flight` (lane session_01AFoLuM1JYKXSjfqdp6rzT1, Sonnet, $30 ceiling, due 2026-11-05),
`prs: []` on main at the time of this read. I found no `BACKLOG-DRAIN` commit on main. The drain's result is therefore **not yet reported**,
not zero. (The dispatch cites #22913; I did not read that PR.) The 10-29 bulk reset dropped rows rather than draining them (manager SKILL
§ 0b; register holds 145 `dropped` rows over all time — not split by cause).

## 1. Capacity

`python3 scripts/ops/spend_meter.py --capacity`:

- **weekly 0% as of 2026-11-04T18:00Z** (operator screenshot at the reset); reset 2026-11-11T18:00Z (6.83 d).
- Sustainable rate (gross) 14.6 pp/day; reserve for live review 20.0 pp (roster bound n=12, `exposure_unknown`); **net 11.7 pp/day**.
- At the inferred 1.00 pp per lane-hour (basis: **1 reading** in the 24 h window, so the rate is a constant, not measured) → "KEEP 1 LANES
  RUNNING (a target, not a cap; floor 1, judgment up to 5)".
- **No usage reading has been recorded since the 18:00Z reset reading.** Tonight's reset jobs (reviews, drain, this lane) have run since.
  The operator should give a fresh Usage reading before allotments are sized; until then the lane-hour rate rests on one point.
- Desk scale (from the same run): hourly desk wake $0.6181/decision, $103.85/week [MEASURED, n=10, plan allowance]; DESK-18 session path
  $0.3368/decision [MEASURED, n=50].
- Standing rule on `WEEKLY-PLANNING` (operator 2026-10-29): when capacity allows only ONE lane, that lane runs the week's priorities.

## 2. Week review

### 2.1 Performance (`docs/reviews/2026-11-04-weekly-walkthrough.md` L9–295)

- Real money (`bybit_2` + `alpaca_live`): **+1.41 R over 9 closes (expR +0.16), 7 d**; −7.36 R / 29 (expR −0.25), 30 d; −155.9 R / 476
  lifetime (retired `vwap` carries −145.8 R).
- Paper: −14.13 R / 231 (expR −0.06), 30 d. Paper giveback 92% (90 d, n=380) → 100% (30 d, n=78) → 102% (7 d, n=30).
- TP compliance: **1 of 7 real-money routings** (`ml_entry` passes); paper 1/58; prop 0/3.
- `ml_entry` real money: 4 closes, +1.35 R since 11-01; C2 reads NO_BACKTEST. `xrp_pullback_2h` real money: BELOW_BACKTEST, n=20, −12.10 R.
- Paper-book tracker: recent 30 d n=21, −$5,907 vs prior +$6,538 — DECAY FLAG, second week; pullback family −$11,725.
- Open asks: TP doctrine on real money (Tier 3, proposal only — 6 of 7 non-compliant; `trend_donchian_eth_4h` sentinel `tp_r` 50;
  `trend_donchian_sol_prop` 6 R TP reached 1.9% of the time; "each needs a real predictive TP measured on its own record"); re-open the
  pullback-2h walk-forward (E4) — killed by the operator 10-29 as "value unknown", "re-open only if the operator now sees the value";
  `/perf-followup` dispatch is the manager's call; D6 needs an owner.

### 2.2 Model + frontier (walk-through L368–557)

- ML changes **14 of 75 rostered (account, leg) pairs**, including 2 of 7 real-money and 3 of 3 prop pairs (10-28: 0/7 real money). Not one
  of those order-changing models is a registry row.
- Registry 98 rows: advisory 3 · shadow 20 · candidate 74 · research_only 1. Foxhound-1 data freshness 408 d (RED).
- All 33 ML research units graded this week target `regime_label` (22) or `direction_label` (11); GBDT is 77 of 98 registry rows.
- Q-TM1 FAIL: −0.059 to −0.079 R/trade over 2,627 trades, 6 purged folds. Prior calls: 1 hit, 2 miss, 2 unresolved, 1 void.
- Trainer disk 80.2% (10-28: 52%).
- "No promote and no demote this week." Proposals P1–P7 (none queued); raised to the manager: dispatch or kill each FRONTIER-LEVER row,
  `-XSEC-RUNNER` silent since 10-28, `LIVE-DECAY-MONITOR` queued 19 d (row state `queued` on main, confirmed).

### 2.3 Practice refresh (walk-through L298–366)

- The 10-29 bulk reset dropped every one of last week's 11 practice proposals unread.
- Floor fills 10-28 → 11-04 (55 cells): bybit_1 42 fills / 30 rejected; alpaca_paper 5 fills; ib_paper 2 fills / 25 rejected. 47 of 57
  floor rejections are netting/slice refusals with no outcome row (`slice_budget_exhausted` 22, 18 on SOL legs).
- market_features: 52 models retrained, 22 heads scoring (40,709 predictions), 3 advisory; trade-level families: 13 retrained, **0 score
  live**. `review_journal` = 0 rows, second week.
- Gaps for Thursday (proposals): VIRTUAL-LEG-LEDGER (not on main), exit head on `trend_donchian_eth` outside the registry — "register and
  gate it, or set it to `annotate` (Tier 3)", k=3 desk/LTR rerun, ML-LEARNING-LEDGER (queued, two refreshes).

### 2.4 Weekly audit, monthly deep (`docs/reviews/2026-11-04-weekly-audit.md`)

- C1 **fail**: 11 invariants, 7 pass / 2 FAIL / 2 not measured. INV-PROTECT-OVERCOVER (ib_paper TLT: 7,443 shares held, 12,743 of stops
  across 2 OCA groups); INV-JOURNAL-EXCHANGE (ib_paper MGC 14 journal vs 11 venue). Real-money SOL flatten 11-03 closed `reconciler_filled`
  though `operator_flatten_intent=true`.
- C6 **fail** (§ 0b). C12 **fail**: 28 unlogged SKILL/BRIEF versions.
- Root cause of stalled audit rows (MEASURED p 0.8): 0 of 10 AUD-20261028 rows had a `due_by`; 549 of 617 open rows undated.
- Asks for the operator (§ 4 of the audit): #1 OK running `mark-operator-flattened --from-intent` for the two flatten rows; #4 OK cancelling
  the duplicate TLT protect group after root cause; #5 MGC journal qty writeback; #11 may audit detectors land as non-blocking reports
  without a per-detector OK?; #13 one follow-through register, or a funded drain of both?

### 2.5 Health (`docs/reviews/2026-11-04-health-review.md`, #22926)

- **Grade: investigate** — 4 concerns (H4, H10, H12, H15), 7 watches, 1 could_not_look (H16).
- Real money: 9 closes, all TP / SL / strategy / operator exits; 0 reconciler, watchdog or orphan closes (window 10-28 19:40Z → 11-04 19:35Z).
- H6 close reasons (all books): SL 29 · TP 14 · sl_cross 4 · tp_cross 1 · strategy 10 · operator flatten 3 · netting_attributed 1; 0 orphans.
- H11 trainer disk 80.3% (10-28: 52%) → projected 90% around 11-06. H5: 68 Bybit leverage-preflight failures in 27 min (equity/futures
  symbols only).
- Calls with tier 2: C1 TLT over-cover (cancel ib_paper 1232/1233, dry-run first; due 11-05), C2 trainer disk retention (11-06), C3 MGC
  drift (11-11), C4 leverage preflight (11-13). **C6 GLD wedge: stalled, 5th review, "needs a venue action"**, stays `ask_operator`.

### 2.6 Research programme review (`comms/research/programme_review/20261104.json`, #22938)

- Population (window 2026-10-28T19:41Z..2026-11-04T19:41Z): 1,932 units read, 0 unreadable, 662 result rows; 447 units with rows — 107 pass,
  210 fail, 25 indeterminate, 11 no_action_warranted, 94 no unit verdict yet.
- 7-day grades by track: TRADING 82 pass / 210 fail / 25 indeterminate; MODEL 37 / 32 / 11; INFRA 7 pass.
- Runnable units: TRADING 23, **MODEL 0**, INFRA 8 (total 31); `fails_without_next` 163; queued 214 vs floor 64.
- needs_review **74 (49 no owner)** in the checks block; the handoff text says 72 — the two counts in the same file differ by 2.
- Iteration orphans: strategy_leg 36 → 31, ml_model 0, ltr_class 5. Authored 5 P3-ITER2 nodes + 3 P2-MECE nodes.
- **3 survivors** — slv_trend_1h, uso_trend_1h, qqq_pullback_1h, "CONFIRMED on 8-year dukascopy holdout"; each goes to a Tier-3 promotion
  proposal (qqq has "no book today"). Handoffs to the manager: promotion proposals due 11-06; structure_exit pivot=5 default on 20 legs, due
  11-06; DATA-DERIV-ARCHIVE schedule-or-kill (decided tonight, § 3); triage owner for needs_review.
- Prior calls: Brier 0.088 over n=5 non-void calls. 6 new calls resolve 2026-11-11.
- **Research SLOs** (`comms/research/health/2026-11-04.json`, as_of 19:23Z, re-read by this lane): **7 breach / 12 ok / 0 could_not_look.**
  Breaches: survivors_per_month **0.0** (ledger definition: Stage-0 pass AND DSR > 0.95 AND BHY haircut > 0; open since 11-01), trials_per_survivor
  2,832, runnable_floor 31, producer_failed_rate_24h 0.317, grade_latency_p90_d 3.0, undispositioned_24h 51, blocked_over_age 13. The SLO's
  survivor ledger and the programme review's 3 holdout survivors use different definitions; which one should count is open (§ 4 Q11).

### 2.7 Roadmap re-baseline (`docs/reviews/2026-11-04-roadmap-rebaseline.md`, #22939)

- **30 of 33 milestones past their review date**; file-level `reviewed: 2026-10-22` (13 days). Nine entries carry a status, `where` or
  `no_rows_reason` their own counts contradict.
- Week-priority targets lapsed without an outcome: L-ML-LIVE (11-01), L-AM-STANDARD and L-DESK-V1 (11-04).
- G3 money-path defects are filed under G5's L-OPS, so the "live-money defect first" rule cannot see them.
- Stale open work: L-PROP 18 of 23 open rows > 14 d; M25 11 of 32; L-TIMEFRAMES 3 of 3.
- Theme weights vs work: regime (weight 5) has 7 queued units; live_strategy (weight 4) has 129.
- § 3 carries a proposed `milestones.yaml` diff, **NOT applied**; planning applies it and sets `reviewed`.

`roadmap_map.py --report` (re-run via helper): every listed milestone verdict is OK or "NONE-YET (reason given)"; most `reviewed` dates read
**OVERDUE** — only L-AM-STANDARD, L-ML-LIVE and L-DESK-V1 (reviewed 2026-10-28) are not.

### 2.8 ML roadmap § 10 and compute allocation § 8–9

**ML roadmap MECE § 10** (`docs/plans/ML-ROADMAP-MECE-2026-11.md` L514–543): new register entries 2 rows + 4 units (P3 `ML-SLOT-REPORT`;
units `RQ-20261105-mece-01` Foxhound-1 filter — "Tier 3 to widen", `-mece-02` Pointer v0, `-mece-03` aggregator harness, `-mece-04` filed only
when -03 is graded). Its five Thursday questions: (1) aggregator scope vs the 11-01 "no position sizing" rule; (2) adopt L-ML-MECE +
L-ML-AGGREGATOR — **decided tonight** ("Adopt both"); (3) breed restatement (Pointer → bracket at entry, Mastiff → aggregator, Chihuahua → 5m
regime sub-brand); (4) widen Foxhound-1 real money from 5 symbols to its tested 60-perp population — **decided tonight** ("Test, widen on
pass"), and whether the 13 `alpaca_paper` ETFs stay a Stage-1 testing leg with no edge claim; (5) confirm per-asset scores (M12) are reported
but never decide what trades. (1) is covered by tonight's "Research offline only" only if that answer was about this question — not
established here.

**Compute allocation § 8–9** (`docs/plans/COMPUTE-ALLOCATION-2026-11-03.md`; population 2026-11-03T23:42Z → 11-04T20:00Z, 5,049 runs, job-hours
ESTIMATED): mean hosted concurrency 20.0 → 8.0; merge-path job-h per 20.3 h ≈267 → 73 (−73%); required-check queue p95 48.2/38.6/31.7 →
3.3/3.3/3.4 min; ops queue p95 32.1 → 6.2 min (n=30, target ≤ 5 not met); PR open→merge p50 28.6 → 13.0 min (n=41). "Buying capacity is not
justified by this data." § 9: four PI-20261103-RAM7EH86 items proposed `killed`; B5/B6/B8/B9/B13 each need a row with `due_by`; three owners
disagree on the money-path workflow list; B13 would add a non-blocking report — "a blocking guard needs the operator's OK".

### 2.9 Cost / infra review (monthly; `docs/reviews/2026-11-04-cost-infra-review.md`, merged on main as `220bb248a`)

- Lane dollars: **UNKNOWN** (`cost_usd` not returned by list_sessions/get_session; per-lane dollars `not_observed`). Declared ceilings for
  reset-protocol jobs: 94 USD/week (ceilings, not spend).
- CI: $0 (public repo, hosted runners); the binding cost is the 20-slot cap — ~3,362 job-hours/week, merge path 2,211 h (66%); queue-wait
  q95 38.6 min (pytest-run) / 48.2 (Guards) / 87.1 (automation) [7 d, 60,244 runs].
- Scheduled cadence not delivered: `live-review-wake` `*/5` (~8,640 nominal runs/30 d) delivered **41**.
- Chronic-red schedules (≤100-run samples): research-watchdog 69/100 red; research-loss-detector 17/62; ml-data-export-kaggle 17/22.
  Whether red is signal or breakage: UNKNOWN (payloads not read).
- **IB gateway disk 75% (11-01) → 100% (11-02) → 93–94% now** — the report's highest-urgency item (F4). Trainer CPU p95 ≥ 90% on 31/31 days.
- No `import anthropic` in the repo (PASS, static). UNVERIFIED: whether the VM `.env` still holds a funded API key (F5, operator Tier 2).

### 2.10 TP doctrine and research throughput (re-run by this lane)

`python3 scripts/ci/check_tp_doctrine.py` (re-run by this lane), population 75 routings / 54 distinct legs, every account in `config/accounts.yaml`:

| book | routings | entry_tp FAIL | tp_revision FAIL | compliant |
|---|---|---|---|---|
| real money | 7 | 2 | 5 | 1 |
| prop | 3 | 3 | 3 | 0 |
| mirror | 7 | 2 | 5 | 1 |
| paper | 58 | 28 | 57 | 1 |

TP-REACH-FLOOR (10%) over 47 declared-target routings: below_floor 7, reachable 6, unmeasured 34. Baselined debt: 72 routings (the weekly audit
recorded the baseline growing 50 → 77 on 10-27; AUD-20261028-TP-BASELINE-GROWS).

Research throughput (same health file): fires_24h 82, lands_24h 84 (ok); authoring_supply_ratio_7d 1.09 (ok); research units queued, not run:
222 of 1,819 (daily measure).

## 3. Already decided by the operator tonight (do not re-ask)

As relayed by the manager's dispatch (times UTC, 2026-11-04); this lane did not re-read the popup records.

| when | decision | answer |
|---|---|---|
| 19:33Z | ML universe | group-level ML universe |
| 21:31–21:33Z | promotions | "Check, then promote" (lane running) |
| 21:31–21:33Z | gateway disk | "Pre-approve, fix if confirmed" |
| 21:31–21:33Z | Foxhound-1 | "Test, widen on pass" |
| 21:31–21:33Z | symbol-set check | "No check" |
| 21:31–21:33Z | aggregator | "Research offline only" |
| 21:31–21:33Z | milestones L-ML-MECE + L-ML-AGGREGATOR | "Adopt both" |
| 21:31–21:33Z | DATA-DERIV-ARCHIVE | "Schedule it" |
| 21:31–21:33Z | refill | "Prop fix now, rest as lanes finish" |
| tonight | structure exits | "Apply on_pass" + "Revert on losing legs" (empty diff) |
| 21:46Z | deployed | #22894, #22897, #22900, #22908 (incl. TLT stale OCA cancelled) — **deployed per the manager; observed not established by this lane** |

Note *[lane reading]*: the TLT stale-OCA cancel deployed tonight overlaps health C1 / audit #4 (TLT over-cover). Whether INV-PROTECT-OVERCOVER
now passes is not observed here.

## 4. Open questions for the dialogue (not priorities; each with its source)

**Carry-over (step 1).** Last week's system-defect order (header `priorities.this_week`, operator 10-29: TP-doctrine system, follow-through,
LTR pricing default, research SLOs). State on main now:

| item | row | state on main |
|---|---|---|
| TP-doctrine system | `TP-DOCTRINE` | landed_unproven, no `due_by` |
| follow-through | `REVIEW-FOLLOWTHROUGH` | landed_unproven, no `due_by` (updated 10-28) |
| LTR pricing default (PI-20261029-KXR1VUPP-0002) | `CF-D2-LTR-PRICING` | queued, no `due_by` |
| research SLOs | `AUD-20261019-RESEARCH-SLO-RED` | queued, due 11-07 (filed 10-19; stalled across 2 audits) |

Q1. For each of the four: schedule this week, date for a named week, or kill? (manager SKILL § Review follow-through step 1)

**Repeat carry-overs that now need the operator (step 1: "a second carry-over of the same item is a decision for the operator").**

Q2. **GLD wedge** (PI-20260930-ZPDIPMDA-0001) — unresolved for the 5th health review; Alpaca still accepts the cancel without effect; needs a
venue action by the operator (health C6).
Q3. `AUD-20261019-PROP-INVARIANT-BLIND` and `AUD-20261019-RESEARCH-SLO-RED` — open since 10-19, stalled across 2 audits (audit § 0).
Q4. `ML-LEARNING-LEDGER` (queued after two refreshes), `LIVE-DECAY-MONITOR` (queued since 10-16, 19 d), `PASS-TO-DECISION-SLO` (queued since
10-29) — schedule, date, or kill?

**What the reviews asked of the operator that is not in § 3.**

Q5. Real-money TP doctrine — 6 of 7 real-money routings non-compliant: authorize per-leg Tier-3 candidates measured on each leg's own record?
(perf L277–279)
Q6. Re-open the pullback-2h family walk-forward you killed 10-29 as "value unknown"? (perf L280–281; paper pullback family −$11,725, DECAY
FLAG second week)
Q7. Audit #1 / #4 / #5: OK `mark-operator-flattened --from-intent` for the two 11-03 flatten rows (one real money); OK cancelling the
duplicate TLT group after root cause (may be moot after tonight's deploy — needs observing); MGC journal qty writeback.
Q8. Audit #11: may audit detectors land as non-blocking reports without a per-detector OK (No-new-gates)?
Q9. Audit #13 / roadmap finding 4: one follow-through register (REGISTER-CONSOLIDATION, queued, due 11-11, "blocked until approved"), or a
funded drain of both?
Q10. Triage owner for the research needs_review set — 74 (49 no owner) per the programme review's checks block (72 in its handoff text); separately
the follow-through table shows 103 no-owner pipeline items across sources, health-review 46 of them and HEALTH-20261028-PIPELINE-ROUTING-OWNER is
stalled (health C8).
Q11. Research SLOs: 7 of 19 in breach; survivors_per_month reads 0.0 while the programme review lists 3 holdout survivors (different
definitions, § 2.6) — which count should the SLO use, and who owns the fix? (AUD-20261019-RESEARCH-SLO-RED, due 11-07)
Q11b. ML MECE § 10 open questions not answered tonight: aggregator scope vs "no position sizing" (if not covered by "Research offline only"),
breed restatement, the 13 ETFs' status, M12 per-asset scores never deciding what trades.
Q12. Exit head on `trend_donchian_eth` outside the registry: register and gate it, or set it to `annotate` (Tier 3)? (practice refresh L359)
Q13. Roadmap: apply the re-baseline § 3 diff, record outcomes for the lapsed L-ML-LIVE / L-AM-STANDARD / L-DESK-V1 targets, and the regime
theme-weight gap (weight 5, 7 units vs live_strategy weight 4, 129 units)?
Q14. Cost/infra F4/F5: IB gateway disk (covered by tonight's "pre-approve, fix if confirmed"? — the decision named "gateway disk"); VM `.env`
API-key residue (operator Tier 2).
Q15. Schedule (see § 5).

## 5. Schedule

`list_triggers(enabled=true, recurring=true)` at ~22:30Z, all 7 rows:

| name | cron (UTC) | bound to | last run |
|---|---|---|---|
| Manager review (once daily: 05:52Z after the 05:30Z report) | `52 5 * * *` | manager 2026-11-04a | none yet (created 18:09Z) |
| Manager lane check-in (every 3h) | `17 */3 * * *` | manager 2026-11-04a | SUCCEEDED 21:17Z |
| Thursday review walk-through + weekly planning (with operator) | `17 6 * * 4` | assistant manager | none recorded |
| Weekly reset protocol (primary, Wed 18:05Z) | `5 18 * * 3` | assistant manager | SUCCEEDED 11-04 18:05Z |
| Daily research authoring dispatch (assistant) | `53 5 */2 * *` | assistant manager | SUCCEEDED 11-03 05:53Z |
| Research-ops pass via assistant manager (4x/day) | `47 2,8,14,20 * * *` | assistant manager | SUCCEEDED 11-04 20:47Z |
| Lane check-in (assistant manager, every 6h) | `17 */6 * * *` | assistant manager | SUCCEEDED 11-04 18:18Z |

Facts for the schedule part of the dialogue:

- The reset-protocol prompt step (1) says "restore … manager review `52 5,17 * * *`"; the live trigger reads `52 5 * * *` (once daily). Its
  name says "once daily", so this may be deliberate; I did not find the record.
- The Thursday trigger fires 06:17Z tomorrow; planning was pulled forward to tonight, so it would run the walk-through + planning again
  unless re-timed or told to skip.
- The weekly-cycle table in manager SKILL lists separate triggers for review prep (Wed 18:53), health (Sat 07:23), audit (Mon 06:07) and
  programme review (Wed 19:29). **None of those ids appears among the enabled recurring triggers** — the reviews ran tonight via the reset
  protocol (`config/reset_protocol.yaml` jobs). The SKILL table and the live schedule disagree.
- Research-ops is 4×/day on the live trigger; its prompt text still says "once a day at 14:47Z while pacing".
- `live-review-wake` GitHub cron `*/5` delivered 41 runs in 30 d (cost-infra F2); the manager's 3-hourly check-in is the effective live-review
  dispatch path.
