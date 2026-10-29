# System conformance audit — 2026-10-29

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-29` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `SYSTEM-CONFORMANCE-AUDIT` (Manager Session 2026-10-29c) · measured on `origin/main` 2026-10-29 ~07:20–08:00Z

**Question (operator, 2026-10-29 ~07:30Z):** *"do like an audit to see where else we have gaps like this that like are holding us back from
having like a technically robust system that matches the design specs that we researched and decided on ... for the strategies improvement,
like we need to make sure that we're not letting gaps like this continue to back us up."*

**Defect class hunted** (precedent: rows `ML-PIPELINE-DESIGN`, `ML-REAL-MONEY-OVERLAY`). These are the four ways the ML system failed:
- **(a) Wrong metric.** A gate measures something other than the operator's objective. The objective is stated once in
  ARCH § Active management on `claude/am-risk-adjusted-rule`: absolute net P&L in $ and %, R as the unit, and risk reduction as the
  tie-breaker.
- **(b) Wrong target.** Work aims at existing artefacts rather than at money decisions.
- **(c) Unbuilt stations.** A station is designed but not built or not running.
- **(d) Unreachable counts.** A process depends on live-trade counts the system cannot generate.

ML itself is out of scope; `ML-PIPELINE-DESIGN` owns it.

**Method.** Six read-only sub-audits ran, one per subsystem. Each read code, config, committed artifacts and checklist row fields, never a doc's
claim about itself. The lane then re-ran every headline number it carries into the top-10. One sub-audit claim was overturned on re-check: the
shadow-leg count is 17 of 57 `execution: shadow`, not 1. That claim is dropped.

**Populations.**
- `config/strategies.yaml`: 57 legs. `strategy_status.py` classes them as production 6, testing 48, inactive 3.
- `check_tp_doctrine.py`: 72 routings.
- `comms/live_review/reviews.jsonl`: 152 rows (2026-10-25..29). `outcomes.jsonl`: 52.
- `comms/desk/decisions.jsonl`: 90 (2026-10-26..29).
- `comms/strategy_evidence/*.json`: 54.
- `research/queue`: 1429 units.
- Pipeline: 2397 items, 1021 of them open.
- Checklist: 1055 rows.

**Real-money legs** (production): `ada_pullback_2h`, `xrp_pullback_2h`, `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `trend_donchian_sol_prop`
and `iaum_pullback_1d`. Prop accounts also carry `trend_donchian_eth_prop`.

This lane ranks; it fixes nothing. Each HIGH or MEDIUM gap has a closing row. Gaps with no existing owner get a new row in this PR.

---

## Top 10 across all subsystems

| # | Gap | Class | Blocks | Closing row(s) |
|---|---|---|---|---|
| 1 | **Prop survival gate is a form check on live prop money.** `scripts/ci/check_prop_roster_gate.py::record_problems` checks only that the fields exist and `verdict == "pass"`. It never thresholds `p_breach`. The rule `RULE-P5-GATE-BRK-PER-LEG` ran `--p-floor 0.0` (`research/queue/RQ-20261016-026.yaml:47`). The `trend_donchian_eth_prop` survival record has `p_breach 0.934` and passes. Its Stage-0 record flipped from **+9.32R (n=163) to −0.25R (n=165)** at the 11.0 bps re-cost on 10-28 (`rebaseline_history`); the prop gate was never re-run. The leg is live on breakout_2, tradeify_1 and velotrade_1, and its grandfather exemption lapses **2026-11-07**. | a, c | **H**, 9-day deadline, real prop money | `PROP-GATE-RERUN-20261029` (manager lane, in flight: re-cost + registered floor); **NEW `PROP-GATE-RECOST-AND-FLOOR`** (t1, guard enforcement, blocked on it); related `SOL-PROP-GATE-FIX`, `PROP-GATE-ADA-XRP`, `PROP-GATE-PARITY` |
| 2 | **Demotion cannot fire on any real-money leg.** `MD-DEMOTE-S2-S1` needs the last **40** live closed trades. At each leg's Stage-0 trade rate that takes about 13 weeks (eth_prop) to 261 weeks (iaum). The 10-28 r4 gate returned **abstain_thin on 6 of 6** production legs. On those rows measured USD is negative on 5 of 6 legs, net about −$62. No mandate firing has ever been recorded (`comms/mandate_firings/` absent). The promotion soak snapshot is 25 days old, against the resolver's 7-day max age. | d | **H**, no de-risking path on real money | **NEW `STAGE2-OFFLINE-DEMOTION-SIGNAL`** (t3); **NEW `MANDATE-EVIDENCE-SNAPSHOT-CRON`** (t1) |
| 3 | **Every ladder and desk gate is mean-R with no risk or $ term, the ML defect system-wide.** Stage-0 `RULE-D1-STAGE0-NET-OF-FULL-COST` is pooled `net_r_oos > 0`. Demotion is R-only. The desk entry gate is "CI of mean net_r > 0" (`scripts/ops/desk_grade.py:111`). The prop gate is EV only. Of 1429 unit decision rules, **6** mention $ or % return. | a | **H**, every promotion, demotion and graduation is graded against the wrong objective | `AM-RISK-ADJUSTED-RULE`, `BOOK-SIM-REAL-SIZER` (in flight); `RISK-OBJECTIVE-AUDIT` (branch `claude/am-risk-adjusted-rule`, queued) must take the Stage-0 rule, demotion T3, the desk gate (`desk_grade.promotion_gate`) and the prop gate by name, with a $/% readout per account |
| 4 | **The holdout was never applied to the legs already on real money.** The operator required it on 2026-10-16 ("all 8 real-money legs get holdout re-runs first"). **0 of 54** evidence records carry `holdout_confirmation`. The trial ledger shows **0 of 31** Stage-0 passes survive DSR plus the BHY haircut. All 54 records read `param_selection_provenance: not_established`. MD-PROMOTE cannot return FIRE (NEEDS_DATA). | a, c | **H**, the 6 production legs are not re-validated, and the only multiplicity control is unbuilt | `HOLDOUT-INCUMBENT-GRADE` (queued since 10-25, rank 23); re-rank |
| 5 | **Graduation depends on live counts the system cannot make.** LTR has 152 reviews, all **152 unapplied**. All 52 graded outcomes are hold, no_recommendation or flag_mechanics with `cf_method: no_path_change`, so **0 priced non-hold calls** exist. The desk has 90 decisions, **2 priced**, and its gate needs n ≥ 30 graded live proposals (about 2 per 3 days). | d | **H**, no in-trade class and no desk entry can ever graduate from live counts | **NEW `LTR-COUNTERFACTUAL-PRICING`** (t1), **NEW `DESK-GATE-OFFLINE-PATH`** (t3); `HARNESS-BE-RANDOM-CONTROL` |
| 6 | **Live reviews on money legs are judgement, not evidence.** `evidence_source` over 152 reviews: table **7**, judgement 71, none 6, absent 68. The 7 table reads are trend_donchian_eth and avax_pullback_2h. A full-history LTR corpus (`comms/strategy_evidence/ltr_corpus/`) exists for **1 of 7** money legs (ada). | b | **H**, the in-trade advice on real money has no priced basis | **NEW `LTR-CORPUS-REAL-MONEY-LEGS`** (t1); extends `ADA-AM-CASE` |
| 7 | **The root cause of the money legs' live shortfall is parked.** `LIVE-BT-STAGE-B` attributes −3.89R to entry from forming-bar decisions on ada and xrp. It is queued with no lane and has not been touched since 10-18. Meanwhile the dispatcher fires about 60 units a day, and 39% of last week's 457 dispatches name no leg. | b | **H**, ada and xrp are the largest bybit_2 legs, and the mismatch acts on live entries now | `LIVE-BT-STAGE-B` (queued, no rank); re-rank |
| 8 | **TP doctrine: 0 of 72 routings compliant** (guard re-run; real_money 0/6, prop 0/6, mirror 0/5). The baseline grew 50 → 77 through lines added in the same PRs that added debt, and is now 72 only because of a roster change. `tp_extend` is registered in `src/runtime/tp_revision.py`, but no leg declares it. | c, a | **H**, real-money brackets carry no predictive TP, and new legs roster non-compliant with CI green | `AUD-20261028-TP-BASELINE-GROWS` (queued), `RM-AM-ADA-TPX` (t3, unit a7c3-01 PASS awaiting operator), `TPX-XRP-DECLARE`, `TP-DOCTRINE` B2 |
| 9 | **Amend paths are unobserved on 3 prop firms and on Alpaca.** The prop path passes `take_profit=None` on breakout_2 and tradeify_1. No prop trail amend has been observed. Alpaca amends have no venue read-back. | c | **H** for prop and Alpaca legs | `RM-AM-PROP-TRAIL-OBSERVE` (queued), `AMEND-PARITY-ALPACA-TRAIL-READBACK` (landed_unproven) |
| 10 | **The cost stack is under-charged in research.** Of 1221 result rows since 10-15, 396 ran at a 7.5 bps fee, 14 at the measured 11.0, 87 at 0.0, and 719 carry no fee flag. Funding in the core trend and pullback harnesses is a flat 1 bps per 8h (`execution_costs.py:70`), not the settled series. | a | **M**, every crypto candidate is overstated until the resolver lands | `COST-STACK-HARNESS-RESOLVER` (in flight, held), `-REMAINDER`; **NEW `HARNESS-SETTLED-FUNDING`** (t1) |

**The pattern across all ten.** The system built its *measurements*: the TP guard, the r4 gate, the trial ledger, LTR rows, desk grades and
SLOs all run. It did not build the *stations that turn a measurement into a money decision*:
- a gate threshold that means something (#1, #3);
- a demotion that can fire (#2);
- a holdout on incumbents (#4);
- offline evidence in place of live counts (#5, #6);
- a declare that ships (#8).

That is the ML precedent repeated in five subsystems.

---

## Counts, and the High items beyond the top 10

The operator asked for this on 2026-10-29 ~07:33Z: *"That means theres probably more than 10 critical items in that log"*.

The counts below are gap rows in the subsystem tables (§1–§6), with conformant rows excluded. A gap that appears in two tables is counted
once in each. The holdout (3.2 = 4.3) and the wrong-metric gaps (2.2, 3.7, 4.4) do this.

| Subsystem | High | Medium | Low | Total |
|---|--:|--:|--:|--:|
| 1 Active management + LTR | 4 | 2 | 0 | 6 |
| 2 Trading desk | 2 | 3 | 1 | 6 |
| 3 Research pipeline | 2 | 5 | 0 | 7 |
| 4 Ladder / mandates / status | 3 | 5 | 0 | 8 |
| 5 TP doctrine | 3 | 3 | 0 | 6 |
| 6 Data and ops | 0 | 5 | 2 | 7 |
| **All rows** | **14** | **23** | **3** | **40** |

After de-duplication there are **11 distinct High gaps**. Nine are top-10 items #1–#9; #10 (cost stack) is Medium. The two Highs outside
the top 10 are:

- **1.1 (active management).** No book-level $ simulation with the production sizer exists, so `RULE-AM-RISK-ADJUSTED-V1` cannot be measured.
  It blocks every in-trade action class from graduating on real money. Money at risk: no direct risk; it blocks de-risking.
  Owner: `BOOK-SIM-REAL-SIZER`.
- **5.3 (TP doctrine).** Prop TPs sit at 6R with 0.9–1.9% reach, so they are effectively unreachable. The prop path passes `take_profit=None`
  on breakout_2 and tradeify_1. **Money at risk: yes**, live prop legs. Owners: `RM-AM-SOLPROP-TP25` (re-plan, step 1 failed),
  `TP-DOCTRINE` B2.

Three Mediums touch a live money path and are candidates to upgrade to High:
- **6.3.** `DAILY-DD-SWITCH` is the only automatic loss limiter on real-money and prop accounts. It is armed on 13 of 14 accounts, but it has
  never been observed reading equity. If that read is null, it fails open.
- **4.6.** `iaum_pullback_1d` trades real money on n = 8, with placeholder costs and no mirror.
- **6.1.** The pipeline has 649 due items, and the demo-floor soak verdicts are buried among them. The sub-audit rated this High.

**High items that touch a live real-money or prop path now**, to go ahead of any cap:
- **#1 prop gate:** eth_prop and sol_prop on 3 prop firms. Being re-run by `PROP-GATE-RERUN-20261029`.
- **#2 no working demotion:** all 6 production legs.
- **#4 no holdout:** all 6 production legs.
- **#6 judgement-only live reviews:** open real-money packages.
- **#7 forming-bar entries:** live ada and xrp entries.
- **#8 TP doctrine:** live brackets on every real-money leg.
- **#9 unobserved amend paths:** prop and Alpaca.
- **5.3 unreachable prop TPs:** live prop legs.

High items that are not on a live path today:
- **#3 wrong metric:** it governs the decisions above, not orders.
- **#5 graduation from live counts:** every class is advice-only.
- **1.1 book simulation:** research tooling.

---

## 1. Active management + live trade review

Design: ARCH § Active management (branch version), `docs/plans/live-trade-review-DESIGN.md`, `docs/plans/real-money-active-mgmt-plan-2026-10-29.md`,
skills `exit-refinement` and `live-trade-review`.

| # | Promise | Actual (measured) | Gap | Blocks | Row |
|---|---|---|---|---|---|
| 1.1 | Classes graduate under `RULE-AM-RISK-ADJUSTED-V1`, measured on a book-level $ sim | The per-trade R grader `am_risk_adjusted.py` is a screen only. No book sim with the production sizer exists. The branch re-grade passes no class. `RQ-20261029-1f39-01` is blocked. | Known | H | `AM-RISK-ADJUSTED-RULE`, `BOOK-SIM-REAL-SIZER`, `HARNESS-BE-RANDOM-CONTROL` |
| 1.2 | Graduation needs n ≥ 20 priced calls per class (mandates ~1138) | 0 priced non-hold calls in 52 outcomes; 152 of 152 reviews unapplied | d | H | NEW `LTR-COUNTERFACTUAL-PRICING` |
| 1.3 | Options priced from the leg's own history | table 7 of 152; LTR corpus for 1 of 7 money legs | b | H | NEW `LTR-CORPUS-REAL-MONEY-LEGS` |
| 1.4 | Prop trail and Alpaca amend proven stable (plan § 2) | `RM-AM-PROP-TRAIL-OBSERVE`, `RM-AM-TRAIL-EXPECTED-DETECTOR`, `RM-AM-STANDARD-GUARD` and `RM-AM-DUE-COULDNOTLOOK` all queued 10-28; Alpaca read-back landed_unproven | c | H (prop / Alpaca) | existing rows |
| 1.5 | A harness-tested lever is executable live | `trail_level_tight_mult` has no consumer in `src/` (outside the advisor); `be_floor_r` is UNMODELLED (`bracket_advisor._UNMODELLED_SL_KEYS`, line 100); no guard pairs a harness lever with its live consumer | c | M | NEW `LEVER-LIVE-CONSUMER-PARITY` |
| 1.6 | Coverage matrix is M20's done-condition, with an advisor spec per passed cell | `docs/research/exit-refinement-coverage.json` was last updated 10-18; 4 of 6 real-money `passed_unshipped` cells have no advisor spec | c | M | NEW `COVERAGE-MATRIX-REFRESH` |
| 1.7 | Live-vs-harness parity | `comms/live_parity/latest.json`: 0 real-money divergences on 6 legs | — | conformant | — |

Conformant:
- Reviews run at cadence (24–61 a day).
- `live_review_apply.py` covers Bybit, prop, Alpaca and phone, with a RiskManager gate and read-back.
- The `due.daily_floor` accounts cover every money account.

## 2. Trading desk

Design: `.claude/skills/trading-desk`, `docs/plans/claude-trading-desk-DESIGN.md`, `docs/plans/desk-v1-production-plan-2026-10-29.md`, MD-TRADE-DESK.

| # | Promise | Actual | Gap | Blocks | Row |
|---|---|---|---|---|---|
| 2.1 | Entry gate (DESK-13) beats random, n ≥ 30 graded | 90 decisions: 84 no_trade, 6 propose_entry (3 probes); `role_grade.json` priced n = 2 | d | H | NEW `DESK-GATE-OFFLINE-PATH` |
| 2.2 | Gate measures the operator objective | `desk_grade.py:111` passes when the 95% CI of mean net_r is above 0, with no risk or $ term; the baseline R (atr_stop_1x) differs from the proposal's own R | a | H | `RISK-OBJECTIVE-AUDIT` (add the desk gate by name) |
| 2.3 | no_trade decisions priced | 84 of 90 "not_computable"; `DESK-20-OUTCOME-JOIN` is blocked on DESK-0B and DESK-6, both done or landed (stale blocker) | c | M | `DESK-20-OUTCOME-JOIN`, re-check `blocked_on` |
| 2.4 | Hourly wake runs unattended | 30 of 38 hourly wakes present (10-27T17Z..10-29T06Z); the spawn depends on a manager session | c | M | `DESK-V1-SPAWN` (queued), `DESK-V1-ALERTS` (in flight) |
| 2.5 | Demo-floor mechanics soak | 0 desk fills ever; rostered on bybit_1, ib_paper and alpaca_paper only | c | M | `DESK-V1-SOAK` (queued) |
| 2.6 | Learning loop (stations 4B/4C) | `consumed.jsonl` and `touches.jsonl` are empty | c | L (ML) | `DESK-11-ML-FEED` |

Conformant:
- Both brackets are mandatory in the `claude_desk` builder.
- The demo gate in `desk_intake` matches the mandate's demo accounts.
- Packets and grading run hourly.

## 3. Research pipeline + strategy improvement

Design: skills `research-ops`, `programme-review`, `frontier-research`, `backtesting`, `perf-followup`; RESEARCH-PLAN; OPERATING-PLAN § Stage 0; practice principles.

Queue measured: 1429 units (1225 done, 155 queued, 49 retired) plus 74 blocked. 480 graded in 7 days. Verdicts since 10-15: 601 fail,
218 pass, 135 indeterminate.

| # | Promise | Actual | Gap | Blocks | Row |
|---|---|---|---|---|---|
| 3.1 | Explain and fix the money legs' live shortfall first | `LIVE-BT-STAGE-B` queued, untouched since 10-18 | b | H | `LIVE-BT-STAGE-B`, re-rank |
| 3.2 | Promotion needs a pre-registered holdout on every money leg | 0 of 54 records carry it; 11 units have a `holdout_rerun` block | c | H | `HOLDOUT-INCUMBENT-GRADE` |
| 3.3 | Full cost stack | 396 of 1221 rows at 7.5 bps; flat funding in the core harnesses | a | M | `COST-STACK-HARNESS-RESOLVER`, NEW `HARNESS-SETTLED-FUNDING` |
| 3.4 | Configuration counting enforced | Trial ledger built and refreshed weekly, but graders still pass "any candidate"; strategy research does not use CPCV | a | M | `IR-SWEEP-PLATEAU-PBO-GRADER` (queued since 10-16) |
| 3.5 | A PASS reaches a decision | 218 passes since 10-15; 7 money-leg Tier-3 packets queued; no pass-to-decision latency measure | c | M | NEW `PASS-TO-DECISION-SLO` |
| 3.6 | SLOs say whether real work is done | 17 SLOs are volume or latency; none for money-leg share. 457 dispatches in 7 days: 40% name a money leg, 21% paper only, 39% no leg (name match, approximate) | a/b | M | folded into `PASS-TO-DECISION-SLO` |
| 3.7 | Rules measure the objective | 999 of 1429 rules mention R; 6 mention $ or % | a | M | `RISK-OBJECTIVE-AUDIT` |

Conformant:
- The power declaration is enforced at dispatch.
- Pre-registered rules carry `registered_before_run`.
- `research_slo.py` runs on cron with read-states.
- Folds appear in 786 of 1429 rules.

## 4. Promotion ladder, mandates, strategy status

Design: OPERATING-PLAN § 2, `config/mandates.yaml`, `strategy_status.py`, `mandate_resolver.py`, `comms/prop_survival/`.

| # | Promise | Actual | Gap | Blocks | Row |
|---|---|---|---|---|---|
| 4.1 | Mirror net-of-cost window demotes | 40-trade minimum; abstain_thin 6 of 6; never fired | d | H | NEW `STAGE2-OFFLINE-DEMOTION-SIGNAL` |
| 4.2 | Prop superset gate vs the firm's DD limits | Form check; `p_breach` 0.934 / 0.595 / 0.63 / 0.48 all pass; record predates the re-cost | a | H | `PROP-GATE-RERUN-20261029` + NEW `PROP-GATE-RECOST-AND-FLOOR` (guard) |
| 4.3 | Holdout on incumbents | 0 of 54 | c | H | `HOLDOUT-INCUMBENT-GRADE` |
| 4.4 | Gates use the objective's risk term | Stage-0, MD-PROMOTE and T3 are mean R; `path_stats` is `not_a_verdict` | a | M | `RISK-OBJECTIVE-AUDIT` |
| 4.5 | Ladder automation can fire for every timeframe | 12 of 28 positive-OOS 1d legs have n_oos 6–17 over 365d against `min_n_closed 30` / `holdout_min_n 25` | d | M | NEW `STAGE0-LONGER-WINDOW-1D` |
| 4.6 | Production legs rest on a sound record, with a mirror | iaum_pullback_1d: n = 8, `low_n_warning`, fee 0 / slip 5 placeholder; `alpaca_portfolio.strategies: []` so no mirror window | a | M | NEW `IAUM-RECORD-OR-PULL` |
| 4.7 | Resolver evidence is fresh | Soak snapshot `soak_state/2026-10-04.json` is 25 days old against `soak_snapshot_max_age_days` 7; snapshot scripts are on no workflow | c | M | NEW `MANDATE-EVIDENCE-SNAPSHOT-CRON` |
| 4.8 | Every testing leg trades on the demo floor | 45 of 48; spy, qqq and tlt pullback_1h are unhomed; 7 rostered legs emit no eval line | c | M | `ALPACA-SLICES-REHOME-1H`, `AUD-20261028-DEMO-FLOOR-NO-EVAL`, `AUD-20261028-DEMO-FLOOR-SHADOW-LEG` |

Conformant:
- `strategy_status` is derived and no leg sits on both books.
- `soak-contract-guard` passes (69 contracts).
- r4 gate runs daily.
- The `proposed:` list is empty, with no self-grant.

## 5. TP doctrine

Design: ARCH § TP doctrine. Guard `check_tp_doctrine.py`, re-run 2026-10-29:

| Bucket | Routings | entry_tp fail | tp_revision fail | Compliant |
|---|--:|--:|--:|--:|
| real_money | 6 | 2 | 5 | 0 |
| prop | 6 | 6 | 6 | 0 |
| mirror | 5 | 2 | 4 | 0 |
| paper | 55 | 28 | 55 | 0 |

Reach floor: 10 below floor, 6 reachable, 28 unmeasured of 44 declared. `config/strategies.yaml` holds 29 `tp_r: 50.0` sentinels.

| # | Promise | Actual | Gap | Blocks | Row |
|---|---|---|---|---|---|
| 5.1 | Real-money TP predictive and revised in-trade | Revision rules exist (`donchian_measured_move`, `tp_extend`); only eth_4h declares one; `tp_extend` is declared nowhere | c | H | `RM-AM-ADA-TPX` (t3), `TPX-XRP-DECLARE` |
| 5.2 | Debt may only shrink | Baseline grew 50 → 77 through self-added lines | c | H | `AUD-20261028-TP-BASELINE-GROWS` |
| 5.3 | Prop TP reachable and revisable | Prop targets at 6R, reach 0.9–1.9%; `take_profit=None` on 2 of 3 firms; sol_prop 2.5R confirmation a7c3-03 FAIL | c | H | `RM-AM-SOLPROP-TP25` (re-plan), `TP-DOCTRINE` B2 |
| 5.4 | Calibration graded before P&L | No emitter on main | c | M | `ABLATION-TP-CALIBRATION` |
| 5.5 | Sweep results land as records | `tp_revision_sweep` output refused by the emitter; recollect is on no workflow | c | M | `TP-REVISION-RECORD-CONTRACT` |
| 5.6 | eth_4h finite entry TP | 50R sentinel; unit a7c3-04 has no result | c | M | `RM-AM-ETH4H-ENTRYTP` |

**Answer to "is the system that should produce compliant TPs built?"** Partly:
- **Built:** the revision mechanism (`monitor()` → `modify_open_order`), the guard, and the per-leg research screens.
- **Not built:** no production loop takes a PASS to a declare. That needs Tier-3 declares, the baseline-growth detector, the prop amend path,
  and calibration grading.

The ML TP head (`TP-PREDICT-HEAD`) is out of scope.

## 6. Data and ops

Design: CLAUDE.md follow-through pipeline, `docs/reference/shadowed-features.yaml`, manager skill (brief), Prime Directive rule 7, DAILY-DD-SWITCH.

| # | Promise | Actual | Gap | Blocks | Row |
|---|---|---|---|---|---|
| 6.1 | The pipeline is a pull: due is computed, items route | 1021 open: **649 due**, 101 unrouted (bound 100), oldest unrouted 95 days, oldest open 157 days, 214 over 60 days; 103 BL- and 9 OI- carry-overs from retired registers | c | M | NEW `PIPELINE-DUE-TRIAGE-SWEEP` |
| 6.2 | Shadowed feature keeps a freshness check | **0 of 18** entries have one (`state: exists`); 16 are gaps pointing at `NEWS-DATA-FRESHNESS` (queued, no lane) | c | M | `NEWS-DATA-FRESHNESS` |
| 6.3 | Daily DD switch proven | Implemented (`src/units/accounts/risk.py`); armed on 13 of 14 accounts; the observation needs a VM read and was redated | c | M | `DAILY-DD-SWITCH` (landed_unproven, due 10-31) |
| 6.4 | Persistent failure raises ONE red flag (canonical rule 7) | Channel exists; no shared helper; one Python caller found (`telegram_split.py:162`). The shell ticks were not all read, so severity is unmeasured | c | M (unverified) | NEW `RED-FLAG-HELPER` (first step: measure) |
| 6.5 | `landed_unproven` gets proven | 330 rows; 36 past `due_by`; observations needing a VM read are redated by lanes without VM egress | c | M | NEW `LU-OBSERVATION-DRAIN` |
| 6.6 | Data-infra builds (P6) | `DATA-KLINE-ARCHIVE`, `DATA-DERIV-ARCHIVE`, `DATA-LABEL-TIES` and `DATA-CATALOG` queued since 10-14 | c | L | existing |
| 6.7 | VM disk managed | `VM-DB-BACKUP-PRUNE` (queued, t2) has no allowlisted action | c | L | existing |

Conformant:
- The daily brief renders all six sections (`render_daily_brief.py --check`).
- `pipeline.py` computes due and raises its own routing alarm.
- The DD switch is implemented in `RiskManager` and `PropRiskManager`.
- `attention_watch` pushes operator-asks.

---

## Could not measure (needs a VM diag pull or more reading)

- Live soak state per leg, and the live closed-trade counts per Stage-2 leg. Stage-0 trade rates were used as the proxy.
- Whether the daily DD switch reads real equity or has ever tripped (`runtime_logs/daily_dd_switch_state.json`).
- `advisor_state` counts in `position_path_history` (decides `BRACKET-ADVISOR-SHADOW`).
- Whether eth_4h's live TP amends still happen.
- Whether the prop VM trail has amended anything.
- Whether the prop EV simulator applies the 11.0 bps fee internally.
- Whether the 11 `holdout_rerun` units produced results anywhere.
- The "3 consecutive" red-flag counting in shell tick scripts not opened.

## New rows filed by this lane

| Row | Rank class | Tier | Model | Ceiling |
|---|---|---|---|---|
| `PROP-GATE-RECOST-AND-FLOOR` (guard only; re-run owned by `PROP-GATE-RERUN-20261029`) | H | 1 | sonnet | $4 |
| `STAGE2-OFFLINE-DEMOTION-SIGNAL` | H | 3 | opus | $15 |
| `LTR-COUNTERFACTUAL-PRICING` | H | 1 | sonnet | $8 |
| `DESK-GATE-OFFLINE-PATH` | H | 3 | opus | $8 |
| `LTR-CORPUS-REAL-MONEY-LEGS` | H | 1 | sonnet | $10 |
| `MANDATE-EVIDENCE-SNAPSHOT-CRON` | M | 1 | sonnet | $3 |
| `HARNESS-SETTLED-FUNDING` | M | 1 | sonnet | $4 |
| `LEVER-LIVE-CONSUMER-PARITY` | M | 1 | sonnet | $6 |
| `COVERAGE-MATRIX-REFRESH` | M | 1 | sonnet | $6 |
| `PASS-TO-DECISION-SLO` | M | 1 | sonnet | $4 |
| `STAGE0-LONGER-WINDOW-1D` | M | 3 | sonnet | $8 |
| `IAUM-RECORD-OR-PULL` | M | 3 | sonnet | $4 |
| `PIPELINE-DUE-TRIAGE-SWEEP` | M | 1 | sonnet | $5 |
| `LU-OBSERVATION-DRAIN` | M | 1 | sonnet | $10 |
| `RED-FLAG-HELPER` | M | 1 | sonnet | $5 |

**Existing rows this audit recommends re-ranking** (the manager's call; the lane did not edit them):
- `LIVE-BT-STAGE-B`
- `HOLDOUT-INCUMBENT-GRADE`
- `AUD-20261028-TP-BASELINE-GROWS`
- `RM-AM-PROP-TRAIL-OBSERVE`
- `DESK-20-OUTCOME-JOIN` (stale blocker)
- `NEWS-DATA-FRESHNESS`
- `RISK-OBJECTIVE-AUDIT`: scope it to the Stage-0 rule, demotion T3, the desk gate and the prop gate by name.
