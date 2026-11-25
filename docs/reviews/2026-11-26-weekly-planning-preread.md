# Weekly planning pre-read W48 (2026-11-26): no real-money leg would convince a sceptic, capacity buys about 4 lanes, and the research queue has 56 runnable hours, all on CPU

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-25` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `PLANNING-PREREAD-W48`, dispatched by Manager Session 2026-11-25b (session_01AFoLuMBFa9R1WfLbufdhqs)

> **What this is.** Part (A) of weekly planning ([`docs/plans/weekly-planning-protocol.md`](../plans/weekly-planning-protocol.md)): facts first, then a
> **proposed** week. Every number names its population. Merged, deployed and observed are kept apart. Anything that is my reading rather
> than a measurement is marked *[lane reading]*. The questions for the operator are in [`comms/planning/w48-decisions.json`](../../comms/planning/w48-decisions.json).
> Read on `origin/main` @ `a499faaca` (2026-11-25 ~22:10Z). **Gates this adds or changes: none.**

---

## 1. Scoreboard (7 d rolling since 2026-11-18 ~18:25Z; `/api/bot/performance`, read 18:25–19:10Z by the performance lane; R on declared signal-time risk)

| book | 7 d: n · net $ · net R | 30 d: n · net $ · net R | lifetime: n · net R | read-state |
|---|---|---|---|---|
| **real money** (`bybit_2` + `alpaca_live`) | 26 · **−$16.05** · **−7.68 R** (PF 0.39, 0 TP reached) | 77 · −$28.51 · −11.11 R | 542 · −166.4 R | read; $ coverage 1.00 (7 d / 30 d), 0.81 lifetime |
| **mirror** (`*_portfolio`) | 35 · **−$6,250** · +33.09 R | 90 · −$4,470 · +33.45 R | 237 · −3.2 R | read; $ coverage 0.80. **The R figure is an artefact**: `slv_trend_1h` fragments count one decision several times. Without it: −7.80 R |
| **paper** (all, includes mirrors) | 143 · +$26,939 · +32.40 R | 417 · — · +54.53 R | 2,053 · −77.5 R | read; $ coverage 0.91. **The sign is not measured.** Over the full journal (8,613 rows), measured paper rows are **−$67.8k** (n 908). One estimated row (id 4773, ib_paper MGC, +$249k) sets the headline sign (weekly audit Q1) |
| prop (2 of 3 accounts read) | — | 41 · −1.13 % | — | partial; 39 fills unverified |

**`ml_entry` caused the real-money week:** 23 of 26 closes, −8.21 R, −$17.59. It took 0 TPs: 12 SL and 11 live-review closes. Its 5 winners were all live-review closes.

**The sceptical-quant line for every leg the operator is asked about** (offline record net of the full cost stack; live bar counted once per decision):

| leg | the one-line answer |
|---|---|
| `ml_entry` (bybit_2) | **No.** Offline +0.037 R/trade, n 907, iid t ≈ 1.03, measured only on the window that graded it. Live: −9.84 R over 59 trades. Per entry bar: 24 bars, −10.90 R, lcb80 −0.81. Tonight's revert to `ml_decision_entry_v1` uses data through 2025-09-22 (freshness WARN) |
| `ml_entry_eq_struct` (alpaca_live) | **Marginal.** +0.49 R/trade, n 207, day-clustered t 2.06. It is the trial ledger's only survivor, but `param_selection_provenance` is null, so the grade-window question applies. Live n = 1 |
| `slv_trend_1h` (alpaca_live; kept by the operator) | **No.** It fails the reprice at 26 bps (2 of 4 folds). Its live-bar PASS falls to FAIL (lcb −0.17) once each decision counts once |
| `tlt_pullback_1h` (alpaca_live; no demotion until the lever map is exhausted) | **No.** −26.24 R at 26 bps, 0 of 4 folds; DSR 0.005 |
| INDEX-CAPIT-1X-LEG (going to alpaca_live at full size) | **No, on the record the operator saw.** The daily edge holds in 2010–26, is concentrated, and fails 2000–10 on every population; 1 h and 4 h fail. The operator decided on 11-25 with these out-of-time FAILs in view |
| `trend_donchian_eth_prop` (the only promotion candidate) | **Not yet.** net_r_oos +10.30, n 135, 3 of 4 folds, faithful. The resolver says NEEDS-DATA: no holdout confirmation. That is a data task, not a question (§ 7) |

No real-money leg currently clears the live bar with one count per decision. Paper legs `trend_donchian`, `trend_donchian_ada_4h`,
`trend_donchian_sol_4h` and `e4_oi_shock_1h` do clear it (performance review § S).

---

## 2. What each review found (5 lines each)

**Performance** ([walkthrough § PERFORMANCE](2026-11-25-weekly-walkthrough.md)):
1. Real money −7.68 R; `ml_entry` −8.21 R of it, and no rule can demote it (D1 → operator question Q1).
2. `live_bar.py` counts accounts and fragments as decisions, so 3 of its 7 PASS legs read FAIL when counted once (D3, D5: tooling, Tier 1).
3. `tlt_pullback_1h` fails at 26 bps; the 8-year re-run is a unit (D2, due 12-02).
4. `ml_entry` placed 0 crypto packages in about 30 h from 11-24 12Z (D4 health read, due 11-27).
5. Not run: C5 slippage, C8, C9 cohorts, C11 paper tracker. 27 of 34 backlog items were not re-checked.

**ML + frontier** ([walkthrough § MODEL](2026-11-25-weekly-walkthrough.md), `comms/reviews/ml-review-20261125-200000.json`):
1. No served order-changing model is in the trainer registry: all 8 fail `gate-check` (P-5, row ML-REGISTRY-SERVED-MODELS-NO-STAGE).
2. ml_entry levers f1a0-01..33 gave 0 PASS. AM v2 c7e3-01..06 gave 0 valid PASS, and **every earlier AM random control leaked exit-time knowledge** (P-8).
3. D7 and D8 have 0 queued units (P-3, P-4). gbdt holds 74% of open family-tagged items (14 of 19).
4. The learning chain breaks at H3: desk and live-review labels are produced, but 0 enter a dataset.
5. The frontier scan keeps two methods and no new models: a held-out read ledger (P-6) and PBO/CSCV deflation.

**Practice refresh** (walkthrough § PRACTICE):
1. Recorded cost understates the +1 h markout by +3.78 bps/fill, CI [+0.36, +7.34], n 2,375 (pooled; the real-money slice alone is indeterminate) → TG1 (question Q5).
2. FOMC minutes are weighted like a decision, and the 12-09 decision is timed 30 min late → TG2 (§ 7, standing authority).
3. Demo floor: 29 of 58 cells filled in 7 d; 22 quiet cells cannot be classified because they print no eval line.
4. 24 of 100 registry models were trained and scored, all regime or setup heads; 0 trade-decision models.
5. The teacher sets (desk, live review, the 1,511-row `claude_judgments` set) have been consumed 0 times.

**Health** ([2026-11-25-health-review.md](2026-11-25-health-review.md), grade *investigate*):
1. Real-money exits clean for the 4th review running.
2. ib_paper MGC re-entry rejected `Inactive` every minute since 14:45Z; the stop fill was booked as a reconciler close with no price (IB-MGC-INACTIVE-1125).
3. The `closed_flat_invariant` alerter threw a TypeError 23 times, so 0 of those violations reached a channel (HEALTH-20261125-CFI-ALERTER, Tier 2).
4. Research floor red on 91 of 92 runs; 0 models trained this week; trainer disk at 85–86%, reaching 90% around 12-16.
5. Live VM free disk is falling (29.7%); the options vertical stayed open 1 h after its row closed.

**Weekly audit** ([2026-11-25-weekly-audit.md](2026-11-25-weekly-audit.md)):
1. The paper headline's sign rests on one estimated row (4773). Scoreboard fixed to split by provenance; the row's fate is question Q3.
2. 15 audit rows went to a lane that died the next day, and 0 moved in 7 days (§ 8 of the planning doc gives the 13 that remain).
3. Unrouted pipeline items went 35 → 140 (the triage since routed 133; `pipeline.py --stats` read 0 after it).
4. No invariant grades Alpaca protection (INV-ALPACA-PROTECT-BLIND); an options close leaves its legs (Tier 2).
5. Research-ops cadence contradiction: **already fixed** by #28887 (SLO 8 h → 26 h, once a day, operator 11-17).

**Programme review** (`comms/research/programme_review/20261125.json`):
1. 39 of 57 testing legs are overdue: the loop turns without learning.
2. The weekly generated sweeps cannot reach 6 lever families, and 8 ict_scalp sweeps were no-ops graded FAIL (RESEARCH-LEVER-ARM-NOOP, -FAMILY-REACH).
3. Single-symbol leads mostly do not travel; prior-call hit rate 2 of 8 at mean p 0.38.
4. One survivor: the `qqq_pullback_1h` session skip (holdout PASS) is a Tier-3 declare candidate (§ 7).
5. Runnable units by track: TRADING 0 · MODEL 9 · INFRA 9; 121 FAILs have no next unit.

---

## 3. Follow-through numbers (protocol step 0)

`python3 scripts/ops/review_followthrough.py --window-days 7`, run 2026-11-25 ~22:15Z. **Population:** 3,083 pipeline items + 2,136 checklist rows, read from the work-store API, 0 unreadable.

```
source             | cohort(filed 7d): filed done kill open ≤7d | backlog(now): open due% med-age no-owner
perf-followup      |                 9    2    0    7  22% |                13  38%       0        0
performance-review |                30    4    0   26  10% |                40  35%     6.5        9
frontier           |                28    2    0   26   7% |                43  12%       7        5
ml-review          |                 8    0    0    8   0% |                15  40%       7        0
health-review      |                13    3    0   10  23% |                77   6%      87        0
weekly-audit       |                14    6    0    8  43% |                21   5%      14        0
programme-review   |                23    2    0   21   9% |                23  39%       0        0
research-ops       |                36    0    1   35   3% |                97  39%      11       10
ltr                |                39    0    0   39   0% |                44  30%       0        2
desk               |                59    2    1   56   5% |                71  32%       0        1
```

Arithmetic (this lane): cohort = **259 filed, 21 done, 2 killed, 236 open** (8% closed within 7 d; on 11-04 it was 52 of 253, 21%).
`no-owner` sums to **27** over the current backlog. Step 2 needs it at 0 for this week's cohort after planning. Oldest open:
performance-review `SRQ-20260715-REALMONEY-ALLOC-BENCHMARK` (133 d, no owner); ml-review `MB-20260712-SHADOW-LOG-HISTORY` (136 d).

## 4. Carry-over from last week

- **There is no W47 planning record on `main`.** I looked in `docs/reviews/*plan*` (latest 11-04), `docs/plans/thursday-planning-*` (latest 11-12 answers) and the `WEEKLY-PLANNING` row note. So the carry-over is the 11-12 plan's three **WEEK PRIORITY** milestones. All were due 11-11 and none is done:
  - **L-ML-LIVE:** `ml_entry` is live, but it is the losing leg and its model has just been reverted.
  - **L-DESK-V1:** DESK-14 and DESK-18G are `landed_unproven`; DESK-19..26 are blocked "later phase".
  - **L-AM-STANDARD:** AM v2 Stage B is all FAIL and the R4 control is void.
  - Protocol step 1 says a **second carry-over is the operator's decision**, so all three re-plans are questions Q8–Q10.
- **The 13 audit rows** (planning doc § 8) re-dated to 11-26 get an owner or a kill this week (§ 9 below).
- **Tonight's operator decisions, recorded, not re-asked:**
  - INDEX-CAPIT-1X-LEG goes to real money at full size (#28869, merging tonight).
  - `tlt_pullback_1h` is not demoted until its lever map is exhausted.
  - `slv_trend_1h` stays on real money.
  - `ml_entry` stays live on `ml_decision_entry_v1` (#28890 merged). Its next candidate is the Sun 11-29 retrain, graded under the grade-window rule (#28870 merged).
  - Pacing is about 4 lanes.
  - The history purge runs after this planning.
  - Tier-2 fixes #28885, #28895 and #28871 are merged.
  - **Merged is established; I did not check deployed or observed for any of these.**

## 5. Research plan per slot D1–D10 and per testing leg

Source: `research/programmes/02-ai-trader.yaml` `rollforward_2026_11_25.decision_steps`, plus `iteration_orphans.py` (run 22:15Z). Format: current iteration → next unit → dependency.

| slot | now | next unit (week of 11-30) | depends on | owner |
|---|---|---|---|---|
| D1 leg selector | parked; no census count yet | run ML-LINE-S1-CORPUS count | nothing | manager → research-ops |
| D2 regime | 5 PASS / 2 FAIL (5m BTC, ETH) / 1 IND, classifier quality only | keep 5 heads; retire 5m BTC/ETH (Tier 3, MLP-D2-REVIEW-HEADS); node D2-survivors-as-D3-features | none for authoring; the cost-net consumer test 78fc-08 is blocked | ML-PRIMARY (REGIME-PROGRAM) |
| D3 entry (`ml_entry`) | f1a0-33 IND; side gate d3a1-01 FAIL; 0 of 33 levers PASS | IPW-ML-ENTRY-SIDE-SPLIT; **P-2 fresh-window read of v1** (10-01..latest); 11-29 retrain graded under Amendment 4 | the 11-29 retrain | ML-PRIMARY (ML-ENTRY-FINETUNE) |
| D4 overlay | 3e98-01 IND (fails on measured-only rows) | grade b18a-02 (queued) | ≥ 300 more measured paper rows for the 3e98 re-read | research-ops |
| D5 aggregator | census PASS; robustness IND | author D5-aggregator-vs-rules | none (allocator_ev.py exists) | research-ops |
| D6 brackets | b18a-03/-04 FAIL | write the failure diagnosis into ML-FS-BRACKETS-HOLD | the manager unblocks that row | research-ops + manager |
| D7 in-trade policy | Stage B FAIL; **0 units** | P-3 Labrador-1b revised-vs-held TP; c7e3-07/08/09 read with R4 voided | the ML-AM-NEXT-LIVE driver build | ML-PRIMARY / row owner |
| D8 exit head | **0 units** | P-4 Labrador-2 ETH out-of-sample read | ML-EXITHEAD-ROWS-KAGGLE lands | row owner |
| D9 fill model | 4 limit-entry reads all IND | **no more arms**; build MLP-D9-WHIPPET + maker-exit harness | the fill model | manager |
| D10 grade count | parked | define the D10 count + CUSUM baseline | nothing | research-ops |

**Per testing leg** (`iteration_orphans.py`, population: testing legs per `strategy_status.py` + `iteration_subjects.yaml`, 2026-11-25):
- strategy_leg: **57 subjects**, covered 16, overdue 37, orphan 4 (claude_desk, xsec-crypto, cost-levers-live-legs, movement-capture).
- ml_model: **13**, covered 10, orphan 3 (ml-exit-head-donchian-1h, ml-holdbias-exit, ml-btc-router-cells).
- ltr_class: **7**, covered **0**, overdue 2 (widen-sl, tp-extend), orphan 5 (tighten-sl, close, partial-close, sl-to-structure, tp-pull-in).
- The programme review wrote two-week designs for every orphan in `rollforward_2026_11_25`, for research-ops / QUEUE-FILL to author.
- The 37 overdue legs are mostly blocked by the generator: the families still to test are timeframe 34, symbol_set 28, sizing_vs_cost 26, entry 22, session 16, regime_gating 15 and direction 7. **RESEARCH-LEVER-FAMILY-REACH is the unblocker, not more units.**

**Runnable hours per backend vs the 164 h left in the week** (MEASURED from `research/queue/*.yaml` status `queued`, ungraded, `cadence: once`, routing `est_minutes`; 22:15Z):

| backend | runnable one-shot units | est hours | share of 164 h | recurring (weekly/monthly/daily) |
|---|---|---|---|---|
| GitHub Actions / kaggle_cpu (no GPU, no trainer data) | 46 | **56.2 h** | 34% | 177 armed, 37 ungraded |
| trainer-resident | **0** | 0 | 0% | 1 weekly |
| GPU (kaggle GPU / runpod) | **0** | 0 | 0% | 0 |

- **Flag:** the trainer and the GPU backends have **nothing queued** for the week. The trainer trained 0 models this week (health H11).
- The research floor has been red on 91 of 92 runs.
- At the current runner rate the CPU queue runs dry in about 2–3 days *[lane reading: that assumes about one CPU unit at a time, which I did not measure]*.
- **So QUEUE-FILL-STANDING-W49 has to supply, from the plans, at least the D2/D3/D5/D10 units and the orphan designs this week.** It must also give the trainer something to do: the 11-29 retrain, the P-2 read and the D2 survivors.

## 6. BACKLOG

**BACKLOG — pipeline open 978 (due 869 before the triage) · unrouted 0 after the triage (140 at the audit) · checklist open 973 (queued 554 · landed_unproven 367 · in_flight 26 · blocked 26) · past-due rows 25 after the re-date · oldest open 136 d · cohort closed within 7 d: 21 of 259 · last week's drain: the BACKLOG-TRIAGE-W48 lane ran tonight (51 soak items killed, 15 rows closed, 20 re-owned, 133 routed, 752 re-dated; about 100 refused by the `due_when` contract).**

Source: the planning doc § 0 and § 7, measured 17:50Z and 19:01Z. These are its figures, not my re-read; the follow-through run above is my read.

**Ranked** (planning doc § 7.5; "class" is a heuristic):
1. **live-money / order-path**:
   - Alpaca stop and re-arm faults: ALPACA-PAPER-BRACKETS-GONE-1116, ALPACA-TP-PARTIAL-CANCELS-STOP-1125, ALPACA-PKG-CLOSE-LEAVES-WORKING-ENTRY-1125.
   - LTR-PROP-CLOSE-FALSE-APPLIED (rank 1): Tradeify reported a close as applied, but the position is still open.
   - FRACTIONAL-ETF-EXECUTION and INV-ALPACA-PROTECT-BLIND.
   - The landed_unproven real-money rows: WATCHDOG-CLOSE-RECURRENCE, ALPACA-LIVE-MECHANICS, REAL-TP-COMPRESSED-ETH4H, ML-REAL-MONEY-OVERLAY.
2. **ML**: ML-REGISTRY-SERVED-MODELS-NO-STAGE, ML-ZERO-ROW-FAMILIES, ML-AM-NEXT-LIVE (overdue 11-12), MLP-D9-WHIPPET, MLP-D2-REVIEW-HEADS.
3. **risk**: HEALTH-20261125-CFI-ALERTER (Tier 2), DISPATCH-DOUBLE-FIRE-1125, LIVE-VM-CPU-SATURATION-1112.
4. **grading**: PI-20261125-PREP1125-0001/-0005 (live_bar counts decisions), COST-STACK-MARKOUT-TERM, ML-BAKEOFF-NULL-ARM.
5. **oldest**: SRQ-20260715-REALMONEY-ALLOC-BENCHMARK (133 d), MB-20260712-SHADOW-LOG-HISTORY (136 d), PI-20261011-YJAYF7GD-0001..4 (45 d).

**Proposed drain:** deferred to the throttle-down under the surge rule (protocol § Surge step 5). The daily review keeps measuring it. One Sonnet drain lane goes in the throttle set, and the HOUSEKEEPING lane takes the 13 audit rows.

## 7. Decided under standing authority, or a data task filed (NOT questions; classified per manager SKILL § "Before any operator popup")

| item | class | why it is not a question | action |
|---|---|---|---|
| `qqq_pullback_1h` session-skip declare | **data-settled** (Tier 3, paper testing leg) | RQ-20261118-001: rule registered 11-18 before the run; 2018–2026 holdout with 4 folds, net of the full cost stack; graded PASS 11-20, 1 row, measured. Canonical § "Data-backed Tier-2/3 decisions" says decide, ship and notify | manager ships it as a data-backed Tier-3 change on the testing book and notifies the operator. **It was on the dispatch's question list; I moved it here. The manager may put it back** |
| CALENDAR-FOMC-RELEASE-SPLIT before 12-08 | **data-settled** (Tier 2, correctness) | 12-09 decision mistimed by 30 min is a calendar defect; the minutes-vs-decision weighting has registered evidence (pre-release flatten 0/6 folds; decision > minutes on 5/5 symbols) | ship by 12-07 and notify. **Also on the dispatch's list; moved here, manager may put it back** |
| research-ops cadence (AUD-…-CADENCE-CONTRADICTION) | settled | operator 11-17 decided once a day; #28887 merged | close the row |
| `trend_donchian_eth_prop` promotion | **data-missing** | resolver NEEDS-DATA: no holdout confirmation | `mandate_resolver.py --file-needs-data` (the triage could not file it while the store was busy); re-run this week |
| `tlt_pullback_1h` at 26/53 bps on the 8-year window | data-missing | the operator has decided no demotion before the lever map is exhausted | unit PI-20261125-PREP1125-0002 + PULLBACK-ENTRY-MODE-LIMIT (cost lever) |
| `ml_entry` silence 11-24/25 | data-missing | a health read names the cause | PI-20261125-PREP1125-0004, due 11-27 |
| MGC `Inactive` loop | data-missing | the IB reject code discriminates the two hypotheses | IB-MGC-INACTIVE-1125 (lane in flight) |
| ml_entry re-grade under the rule (P-1) | landed | #28870 merged; old one-window records recompute to `no_disjoint_number` | the keep/demote call is question Q1/Q2 |
| research-ops 4×/day vs once | settled | see above | — |

## 8. Capacity and the proposed week

**Reading (from the dispatch; I did not re-read the operator's Usage screen):** weekly bar **13% at 2026-11-25T21:58Z**, reset 2026-12-02T17:59Z (6.83 d).
- `spend_meter --capacity` gives **net 11.5 pp/day** after the live-review reserve, which is **78.6 pp for the week**. Its own run here still holds the older 19:14Z reading (6%), so I use the dispatch's figure.
- The meter's 1.00 pp per lane-hour is a **constant, not measured**.
- Tonight's measured burn was about 2.5 pp/h (6% → 13%, 19:14Z → 21:58Z) with about 20 lanes. That is about **0.125 pp per lane-hour** if all 20 lanes ran the whole window *[lane reading]*.
- At that rate, 11.5 pp/day sustains about **3.8 lanes continuous**, which matches the operator's ~4-lane pacing. **At tonight's 2.5 pp/h, the week's 78.6 pp would last about 31 h.** The surge has to be about 1 day wide, not 3.

**Proposed allotment** (pp of the 78.6; ESTIMATED at 0.125 pp/lane-hour; to be agreed in the dialogue):

| set | what | lanes / model | pp | ceiling |
|---|---|---|---|---|
| **standing** (never pauses) | daily review ×7 · research-ops ×7 · live review + desk wakes (inside the 8.4 pp reserve) · health review Sat · weekly audit Mon · manager | Sonnet mostly; manager Opus | **~22** | — |
| **standing: the ONE ML lane** | ML-PRIMARY: D2/D3, the 11-29 retrain graded under Amendment 4, P-2, AM c7e3-07/08/09 read with R4 void | 1 Opus, about half-time | **~10** | $40 |
| **standing: QUEUE-FILL-STANDING-W49** | spec-only units from the D1–D10 plan and the orphan designs, dependency-gated | 1 Sonnet | **~5** | $15 |
| **surge** (Thu–Fri, ~1 day wide) | see below | up to 4 lanes | **~26** | — |
| **throttle** (from about Sat) | see below | 1–2 lanes, paced | **~11** | — |
| contingency (incidents, real-money bugs) | — | — | **~4.6** | — |

**Surge (proposed, ranked by the operator's 11-25 priorities, then money):**
1. **Desk capacity + DESK-MACRO-DAILY** (in_flight, ML-PRIMARY, due 11-27): get the brief into production and get desk wakes back beyond real-money reviews. This also re-plans L-DESK-V1 (Q9). Opus, $25.
2. **Regime (REGIME-PROGRAM)**: state-conditioned entry per family; the D2 survivors become D3 features. This runs on the ML lane, so it costs no extra surge lane.
3. **The ETF leg (INDEX-CAPIT-1X-LEG)**: first live order, plus the Alpaca stop/re-arm diagnosis before it (Q4); FRACTIONAL-ETF-EXECUTION. Opus, $20.
4. **Real-money hygiene:**
   - HEALTH-20261125-CFI-ALERTER (Tier 2, so it needs the OK in Q11);
   - LTR-PROP-CLOSE-FALSE-APPLIED;
   - INV-ALPACA-PROTECT-BLIND;
   - `live_bar.py` counting decisions (PREP1125-0001/-0005).
   One Sonnet lane, $15.
5. **RESEARCH-LEVER-FAMILY-REACH + RESEARCH-LEVER-ARM-NOOP**: this unblocks 37 overdue legs and is the biggest research multiplier. Sonnet, $15.

**Throttle (paced after the surge):**
- ML-REGISTRY-SERVED-MODELS-NO-STAGE (P-5) and ML-ZERO-ROW-FAMILIES;
- the HOUSEKEEPING lane on the 13 audit rows (§ 9);
- the backlog drain;
- COST-STACK-MARKOUT-TERM (report-only);
- DISPATCH-DOUBLE-FIRE-1125;
- the trainer disk;
- the stale draft PRs (planning doc § 4).

## 9. Proposed disposition for every review output

(a) = scheduled this week with an owner · (b) = dated to a later week, with the reason · (c) = killed, with the reason and the data. "Owner" is a proposal for the dialogue.

| output | disp. | owner / date / reason |
|---|---|---|
| PERF D1 ml_entry demotion rule (PREP1125-0003) | operator | Q1 |
| PERF D2 tlt S26/S53 8-year (PREP1125-0002) | (a) throttle | research-ops unit, due 12-02 |
| PERF D3+D5 live_bar / route counts decisions | (a) surge 4 | hygiene lane, 12-02 |
| PERF D4 ml_entry silence | (a) standing | health read via the manager, 11-27 |
| PERF C5/C8/C9/C11 not run | (b) W49 | next review runs them first; no capacity this week |
| ML P-1 re-grade | done | #28870 merged |
| ML P-2 fresh-window v1 read | (a) ML lane | ML-PRIMARY, 12-02 |
| ML P-3 D7 unit · P-4 D8 unit | (a) QUEUE-FILL | 12-01 / 12-02 (D8 gated on ML-EXITHEAD-ROWS-KAGGLE) |
| ML P-5 registry for served models | (a) throttle | ML-REGISTRY-SERVED-MODELS-NO-STAGE, re-date 12-03 |
| ML P-6 held-out read ledger | (b) W49 | builds on #28870; the rule is live without it |
| ML P-7 re-route 15 items on done owners | (a) standing | manager, 11-27 (the triage re-routed 26 ML items to WEEKLY-PLANNING; these are disposed here) |
| ML P-8 void R4 on AM results | (a) ML lane | ML-PRIMARY, 11-27 |
| ML P-9 drift BTC fc-pcv-v2 | (a) ML lane | 12-02 |
| Frontier: TSFM/TFM releases | (c) | dropped by the scan with named gates; the near-zero D3 base caps the benefit |
| FRONTIER-LEVER-TABULAR (reopened by the triage) | (c) proposed | 0 PROBE_LEARNERS records, Kaggle GPU arm does not exist, gbdt default confirmed by dbf8-01 FAIL; kill dbf8-02 with it |
| Practice TG1 markout term | (a) throttle + operator | report-only row; grading basis Q5 |
| Practice TG2 FOMC split | (a) standing authority | § 7 |
| Practice TG3 MGC | (a) in flight | IB-MGC-INACTIVE-1125 |
| Practice TG4 22 unclassifiable floor cells | (a) throttle | AUD-20261028-DEMO-FLOOR-NO-EVAL (housekeeping → build lane), 12-04 |
| Practice TG5 slice-budget log spam | (b) W49 | log noise, no money |
| Practice TG6 desk paper accounts idle | (a) surge 1 | inside desk capacity |
| Practice MG1 t+1-open audit | (a) QUEUE-FILL | HARNESS-ENTRY-NEXT-OPEN then the paired unit, 12-02 |
| Practice MG2 bakeoff null arm | (b) W49 | 12-09 per its row |
| Practice MG3 pre-cutoff teacher labels | (b) W49 | 12-09, no student trains on them this week |
| Practice MG4 learning chain | (a) throttle | ML-ZERO-ROW-FAMILIES |
| Practice MG5 idle census rows | (b) W50 | no consumer this week |
| Health C1 MGC · C2 alerter · C3 options legs | (a) | C1 in flight; C2 surge 4 (Q11); C3 Tier 2 (Q11) |
| Health C4 #28624 unobserved | (a) standing | PI-20261124-RORTRAIL-0001, 11-27 |
| Health C5 research floor stall | (a) surge 5 | LEVER-FAMILY-REACH is the supply fix |
| Health C6 CBOE options source | (b) W50 | options infra is throttle-class and cannot go live this week |
| Health C7 0 models trained | (a) ML lane | 11-29 retrain |
| Health C8 stale rows (OOH, LOCK-TICK) | (a) housekeeping | OOH: close with evidence (0 false-flat rows); LOCK-TICK: re-scope |
| Audit #1 row 4773 | operator | Q3 |
| Audit #2 Alpaca invariant | (a) surge 4 | 12-02 |
| Audit #3 options close legs | operator OK | Q11 |
| Audit #4 exit-loop breach | (a) throttle | 12-02 |
| Audit #5 the 13 stalled AUD rows | (a) | HOUSEKEEPING lane takes PIPELINE-DOC-PATH, PRODUCER-OK-OVER-CNL (11-28), PREDICATE-FALLBACK, RELAY-INVARIANTS-BRIDGE, HEALTH-CLOSE-LIST-MISS (before Sat), LANES-ON-DEAD-SESSIONS (12-02); ITERATION-ORPHANS → research-ops; TICK-SIZE-OWNERS, SIZE-UP-AT-CALLERS, DEMO-FLOOR-NO-EVAL → build lane 12-04; HOLD-VS-CLOSE → desk/live-review research 12-02; FLATTEN-LABEL → live-ops 12-02; AMENDMENTS-UNLOGGED → Q12 |
| Audit #6 cadence | (c) | fixed by #28887 |
| Audit #7 read-state ok on null | (a) throttle | 12-02 |
| Programme RESEARCH-LEVER-ARM-NOOP / FAMILY-REACH | (a) surge 5 | 12-02 / 12-09 |
| Programme qqq session declare | standing authority | § 7 |
| Programme CJ-4-RISK-ATR-HAZARD, FAMILY-REVIEW-HTF-TD1H | (b) W50 | 12-09 per their rows |
| Programme orphan designs (5 LTR, 4 legs, 3 ML) | (a) QUEUE-FILL / research-ops | authored from `rollforward_2026_11_25` |
| Planning doc: 8 stale automation PRs, 11 long-open drafts | (a) throttle | housekeeping proposes keep/land/close per PR; #27086 (S1→S2 resolver) proposed close: the soak step was retired 11-12 |
| Planning doc: ACTIONS-ZOMBIE-QUEUED-RUNS | operator OK | Q11 |
| Planning doc: daily email digest | operator | Q13 |
| Planning doc: run-log account JSON (PI-20261123-NEIELEFR-0002) | (a) standing | delete the run log once the history purge runs (operator act already owed, planning doc § 5.5) |

## 10. Not done by this lane

- `checklist_daily_measure.py` was not re-run; the backlog line quotes the triage's 19:01Z re-read.
- I did not re-read the per-account scoreboard myself; § 1 is the performance lane's read.
- Runner throughput, and so the "queue dry in 2–3 days" figure, is not measured.
- I checked none of tonight's merges for deployed or observed.

---

## 11. Outcome (operator answers 2026-11-25)

Recorded by lane `PLANNING-OUTCOME-W48` (dispatched by Manager Session 2026-11-25b). Source: the W48 planning decision doc, answered ~22:36-22:41Z; choices
copied verbatim. **Q4 is not in this batch on purpose:** the operator had already decided it on 2026-11-25 ("Don't wait", recorded on the body of #28869), so it was dropped from the doc rather than re-asked. **Gates this section adds or changes: none.**

| Q | operator answer (verbatim) | what it changes | where it lives |
|---|---|---|---|
| Q1 | "Refuse; judge it in the weekly review" | No automatic ml_entry demotion trigger. The performance review flags it weekly and the operator decides. Disposition of D1 (PREP1125-0003): **(b) weekly review, no rule** | PI-20261125-PREP1125-0003 |
| Q2 | "Until the Q1 rule fires, with no date" + note "There's is no demotion path, only iteration and improvement" | ml_entry stays on real money with **no date and no rule**: Q1 was refused, so nothing ends it automatically; it changes by iteration (the 11-29 retrain graded under Amendment 4). The note contradicts the "demote stops at the floor" language elsewhere; **the manager should reconcile it with OPERATING-PLAN § 2 (not done here)** | ML-ENTRY-FINETUNE |
| Q3 | "Exclude it from every promotion/demotion read, keep it visible and labelled (Recommended)" | Trade 4773 (ib_paper MGC, ESTIMATED, about +$249k) is out of promotion/demotion reads and stays listed and labelled. **Landed (scripts side):** `config/promotion_exclusions.yaml`, `scripts/ops/promotion_exclusions.py`, applied in `scripts/research/live_bar.py` and `scripts/ops/scoreboard.py`. **Not landed:** the served `/api/bot/performance` and the R4 recent payload in `src/web` still include it (Tier 2) | AUD-20261125-SCOREBOARD-SIGN-ON-ESTIMATED; new row PLAN-W48-PROMOTION-EXCLUSION-WEB-ROUTE (due 12-02) |
| Q5 | "Report it beside the current net for 2 weeks, then decide (Recommended)" | Report-only: a markout-adjusted net beside each Stage-0 net. **The grading basis does not change.** Decision due 2026-12-09 | COST-STACK-MARKOUT-TERM (`due_by` set to 2026-12-09) |
| Q6 | "Yes: measured headline, the other parts labelled beside it (Recommended)" | The scoreboard headline is venue-measured P&L (`headline_usd`; null renders as "—"), with estimated / unverified / fabricated parts named beside it (`headline_beside`). `net_usd` stays as the all-priced total, so the API stays compatible. The `%` columns are still computed on all priced rows and are labelled so | `scripts/ops/scoreboard.py` |
| Q7 | "Paper off live review this week" | Paper accounts get no live review this week (done by the manager: `ltr_paper` OFF 22:42Z) | LTR |
| Q8 | "Close it and fold it into L-ML-MECE" + note "But that is the planning priority this week" | L-ML-LIVE closed and folded; L-ML-MECE is the week's top planning priority (`week_priority: 1`) | `docs/roadmap/milestones.yaml` |
| Q9 | "Re-scope to desk capacity + DESK-MACRO-DAILY in production end to end, target 12-09 (Recommended)" | L-DESK-V1 re-scoped, target 2026-12-09 | `docs/roadmap/milestones.yaml` |
| Q10 | "Target 12-16: decide on c7e3-08/09; if none passes, re-scope to one action family on one leg (Recommended)" | L-AM-STANDARD target 2026-12-16 with the conditional re-scope | `docs/roadmap/milestones.yaml` |
| Q11 | "Approve both (Recommended)" | Tier-2 fixes approved; the manager's HEALTH-20261125-CFI-ALERTER lane and the housekeeping lane carry them. **Not this lane** | HEALTH-20261125-CFI-ALERTER |
| Q12 | "One backfill pass by the housekeeping lane, then keep it (Recommended)" | The amendments log stays; one backfill pass. **Not this lane** | AUD-20261104-AMENDMENTS-UNLOGGED |
| Q13 | "Pause it while you are active; re-arm on request (Recommended)" | The daily email digest trigger is paused (done by the manager) | WEEKLY-PLANNING |

**Disposition check (§ 9).** I resolved every row id named in § 9 against the work store. Of 34 distinct id tokens, 19 did not match literally. Fourteen were short forms with a full-id row; the rest were lane or owner names or bare PI suffixes (PREP1125-0002/-0003 resolve as PI-20261125-PREP1125-000N). Short forms and their full ids (AUD-2026…-AMENDMENTS-UNLOGGED, -DEMO-FLOOR-NO-EVAL, -FLATTEN-LABEL, -HEALTH-CLOSE-LIST-MISS,
-HOLD-VS-CLOSE-CONFLICT, -ITERATION-ORPHANS, -LANES-ON-DEAD-SESSIONS, -PIPELINE-DOC-PATH, -PREDICATE-FALLBACK-DRIFT, -PRODUCER-OK-OVER-CNL, -RELAY-INVARIANTS-BRIDGE, -SIZE-UP-AT-CALLERS,
-TICK-SIZE-OWNERS; HEALTH-20261118-RECONCILE-LOCK-TICK). **Not verified by this lane:** that each row carries an owner and a due date; I checked existence only. Rows filed or changed here: COST-STACK-MARKOUT-TERM
(`due_by` 2026-12-09) and PLAN-W48-PROMOTION-EXCLUSION-WEB-ROUTE (new, due 12-02). `ML-PRIMARY`, `QUEUE-FILL` and `LEVER-FAMILY-REACH` are lane or owner names, not rows.
