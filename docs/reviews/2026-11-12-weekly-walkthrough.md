# Weekly walkthrough 2026-11-12 — no real-money leg has a working demotion signal, the backlog grew to ~730 due, and capacity is unknown until this week's Usage reading

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `WEEKLY-PLANNING` pre-read, dispatched by Manager Session 2026-11-11a (session_01AFoLuLyarNRcy3nziCep2U)

> **What this is.** The pre-read for the Thursday 11-12 walk-through and planning dialogue (manager SKILL § "Weekly planning, reviews and the
> weekly cycle"; [`docs/plans/weekly-planning-protocol.md`](../plans/weekly-planning-protocol.md)). It is **not a finished plan**: §6 is a draft
> for the dialogue, and every priority waits on the operator. Public repo: no secrets, IPs, account ids or balances; $ figures are P&L only.
>
> **Sources read (all 2026-11-12 ~06:00–06:40Z unless stated).** Re-run by this lane: `review_followthrough.py --window-days 7`,
> `checklist_daily_measure.py`, `roadmap_map.py --report`, `check_tp_doctrine.py`, `research_slo.py`, `spend_meter.py --capacity`,
> `list_triggers`. Read, not re-measured: the performance review (PR #24953, **still open, not merged**), the ML + frontier review and practice
> refresh (`docs/reviews/2026-11-11-weekly-walkthrough.md` on `main`), the weekly audit (`docs/reviews/2026-11-11-weekly-audit.md`), the health
> review (PR #24963, **still open, not merged**), the programme review (#24940, merged). `scripts/research/queue_throughput.py` crashed
> (`ModuleNotFoundError: scripts`, and silent with `PYTHONPATH=.`), so research throughput below comes from `research_slo.py` only.

## 0. Follow-through (step 0, re-run)

`review_followthrough.py --window-days 7` — population 2,700 pipeline items + 1,398 checklist rows:

| source | filed 7 d | done | open | closed ≤ 7 d | backlog open | % due | median age (d) | no owner |
|---|---|---|---|---|---|---|---|---|
| health-review | 1 | 0 | 1 | 0% | **87** | 95% | 74 | **46** |
| desk | 7 | 2 | 5 | 29% | 72 | 57% | 13 | 17 |
| research-ops | 7 | 1 | 6 | 14% | 54 | 87% | 15.5 | 20 |
| ltr | 8 | 2 | 6 | 25% | 37 | 51% | 14 | 3 |
| performance-review | 5 | 5 | 0 | 100% | 32 | 75% | 20 | 15 |
| weekly-audit | 0 | 0 | 0 | — | 17 | 94% | 8 | 0 |
| frontier | 1 | 1 | 0 | 100% | 16 | 69% | 16.5 | 1 |
| programme-review | 2 | 1 | 1 | 50% | 14 | 71% | 11 | 2 |
| ml-review | 2 | 2 | 0 | 100% | 12 | 83% | 32.5 | 0 |
| perf-followup | 0 | 0 | 0 | — | 9 | 78% | 31 | 2 |

Arithmetic: 87+72+54+37+32+17+16+14+12+9 = **350** classified open items; the review sources close their own new filings (perf, frontier, ML
100%), and the old tail does not move. ⚠️ **Caveat (health C2, p 0.9 MEASURED by that lane):** off-VM readers fall back to the pipeline files,
which were last exported 11-06 22:02Z; the store on the VM holds more items. Every off-VM backlog number in this doc, including this table,
may be up to 6 days stale. Row `HEALTH-20261111-EXPORT-READS-STALE` owns it.

## 1. Performance (PR #24953, PERF-REVIEW-PREP-20261111 — open, so not yet on `main`)

- **Scoreboard (OBSERVED, `/api/bot/performance`, read 11-11 ~19:00Z).** Real money 7 d **+3.81 R** / 10 closes; 30 d **−2.57 R** / 31 (PF 0.70);
  lifetime −152.1 R / 486. Mirror 30 d +4.81 R / 34. Paper 7 d −3.28 R / 84; paper $ is not comparable across the 11-09 `alpaca_paper` reset
  (risk per trade stepped from median $740 to $1.7k–18.8k), so **read paper in R**.
- **Sceptical quant, per real-money leg:** no for all six (`ml_entry`, `ada_pullback_2h`, `trend_donchian_xrp_4h`, `trend_donchian_sol_prop`,
  `tqqq_trend_long_1d`, `ml_entry_eq_struct`). The weekly audit agrees: all six below DSR 0.95; trial ledger 0 survivors in 3,457 configs.
- **The material finding (F1, p 0.9): no real-money leg has a valid live-vs-backtest read.** The two ML legs have no committed per-trade
  backtest rows (NO_BACKTEST), and the three legs re-promoted 11-06 are banded on 30 closes from their *old* config because
  `live_vs_backtest.py` has no config-date cut. A decay on real money would go unseen. Owners: PI-20261104-PREP1104-0001 + PI-20261111-PREP1111-0001.
- **`ml_entry` +5.0 R over 11 real-money closes** is mostly one market move: three shorts on 11-08 made +$11.31 of the leg's +$9.79 30 d $.
  Its offline record is +0.037 R/trade with a CI spanning zero. Plan on the record, not the run-rate.
- **Surprises:** a paper GLD long sat 72 days past its stop (fixed by #24547; deployed not established — health's to verify); a script prints
  its bearer header on failure (PI-20261111-PREP1111-0002, security); C5 cost drift, live-review grading and the desk system leg were
  `could_not_look` because direct diag returns 401 after the 11-11 token rotation.
- **Candidate `/perf-followup` items:** F1 ML per-trade emit; F1 config-date cut for C2; `ml_entry_eq_struct` forward check; TP doctrine on real
  money (Tier 3 proposals); the pullback/trend ADX-split replay (killed 10-29, not re-filed).

## 2. ML + frontier (`docs/reviews/2026-11-11-weekly-walkthrough.md`, ML-FRONTIER-PREP-20261111 + PRACTICE-REFRESH-20261111)

- **Headline:** the live ENTRY model has no established edge. Frozen v1 over its held-out year: +0.0085 R/decision, t ≈ 0.24; served replay
  10-25..11-07: **−0.13 R/decision, n 317, CI [−0.25, −0.01]**, all of it on the long side (−0.90 R, n 51). Hypothesis H1: it prices market
  direction, not asset selection.
- **Capacity misdirected:** 27 ML bake-off units this week targeted regime/direction heads that change no real-money order. 8 of 9 ML
  iteration units are overdue, each blocked on a build (programme review agrees).
- **Trade-management ML:** fifth powered null on R1 state features (SL revision held-out +0.0005 R, CI ±0.0013, n 10,641). Next iteration
  needs path state → `TMBENCH-QTM1B-BUILD` is "the highest value per cost on the ML board".
- **Drift:** every head moved at once (common input shift); the trainer stage-guard proposes demoting advisory BTC-15m fc-pcv-v2; the lane
  recommends HOLD one more weekly read (P8, Tier 3).
- **Proposals P1–P8** (none queued): **P1** Stage-2 demotion read for `ml_entry` (mirror net-of-cost window + computed DSR, ~$3); **P2** K1
  market-residual ENTRY target (~$4); **P3** iteration subject for Foxhound-4 (filed PI-20261111-TX7TX2ZN-0001); **P4** accept ML-CONSOLIDATION
  wave 1 (retire 72 registry rows) and the matching regime subjects; **P5** dispatch `TMBENCH-QTM1B-BUILD` then `ML-EXIT-ACTIONGRID-LABELS` (~$6);
  **P6** kill `FRONTIER-LEVER-TABULAR` + `-TSFM-TIMESTRAL`, dispatch `-HARNESS-COSTS`, decide `-LEADLAG`; **P7** `ml_entry` closeReason `other`
  (to perf); **P8** BTC-15m hold vs soft-off.
- **Practice refresh gaps (top):** `trend_donchian_eth` exit head closing trades on in-sample evidence (now resolved overnight, see §7);
  41 of 63 floor rejections leave no outcome (`VIRTUAL-LEG-LEDGER`); four floor mechanics faults; desk silent on alpaca/ib paper for 3 weeks;
  `ML-LEARNING-LEDGER` queued through three refreshes.
- **Is it learning?** Health H11: the 11-11 trainer cycle returned rc 0, registry 98 → 98. Practice refresh (trainer diag #24905): 67 models
  trained 11-11; trade-level families 0 score live; setup_candidates frozen at 48,445 rows since 10-29. The two reads describe different
  layers (registry count vs retrains); `/ml-review` owns reconciling them (HEALTH-20261111-TRAINER-NO-NEW-MODELS).

## 3. BACKLOG

**BACKLOG:** pipeline **due 729–737, unrouted 311–318, open 800**; oldest unrouted **163–164 d**; checklist 636 non-terminal, **362 overdue**,
192 undated, 241 `landed_unproven` with the observation due; 292 of 2,085 research units queued not run; 7 d closed 47 checklist rows
(opened: could not look, shallow clone). Sources and populations:

| source | due | unrouted | oldest unrouted | other | read |
|---|---|---|---|---|---|
| work report WR-20261112-0530Z | 729 | 318 | 164 d | — | VM store, manager-reported (not re-read here) |
| `checklist_daily_measure.py` (this lane, 11-12) | 737 | 315 | — | open 800; checklist as above | off-VM files (stale export, §0) |
| weekly audit C6 (11-11 18:49Z) | 730 | 311 | 163 d | 800 open of 2,700; **fail**, alarm breached | off-VM |
| health H15 (11-11) | — | 311 (11-06 export) | — | store 4,211 items, 812 open observations, all owned; **concern** | VM store + export |
| performance C12 | — | — | — | 32 open, **15 no owner**, untriaged 0 | — |
| ML review §4 | — | — | — | 16 open, all triaged | — |
| programme review | — | — | — | 8 of 9 ML iteration units blocked past due; needs_review 97 handed off | — |
| last week (11-04 pre-read) | 577–583 | 166–176 | 156 d | — | — |

**Trend: due +~150 and unrouted roughly doubled in a week.** The audit's cause: the 11-07 usage cut paused the drain until the reset (p 0.7
INFERRED), and nobody owned audit rows between audits (p 0.8).

**Ranked (live-money/order-path → risk → grading → ML → oldest):**
1. **Live money / order path:** F1 demotion signal for the 6 real-money legs (PI-20261104-PREP1104-0001, PI-20261111-PREP1111-0001) ·
   live VM disk refilling, 24% free, ~10% free projected ~11-19 (HEALTH-20261111-LIVE-DISK-REGROWTH, Tier 2, due 11-15) · leverage pre-flight
   still failing at boot (HEALTH-20261104-LEVERAGE-PREFLIGHT-EQUITY; PR #24962 open) · `ada_pullback_2h` real-money LTR data question with no
   owner (PI-20261025-LTR3SKIL-0001) · intent_reduce P&L booking (PI-20261011-YJAYF7GD-0001…0004, REDUCE-READERS-INCLUDE) · LTR-6-APPLY-PATH ·
   verify #24547 (stop-less Alpaca position class) is deployed.
2. **Risk / security:** bearer printed on failure (PI-20261111-PREP1111-0002) · IB paper account id in public relay replies
   (HEALTH-20261111-IB-ACCTID-PUBLIC) · literal VM addresses in logs (PI-20261015-KXMANT1S-0001) · no Anthropic-SDK import guard
   (AUD-20261028-NO-API-IMPORT-GUARD) · MGC journal qty (AUD-20261028-MGC-JOURNAL-QTY).
3. **Grading:** stale register export (HEALTH-20261111-EXPORT-READS-STALE — do this **first**, or the drain works off 6-day-old numbers) ·
   R contamination, no owner (PB-20260906-…) · rubric C beats B for the 4th week (C9) · research SLOs red 3 audits (AUD-20261019-RESEARCH-SLO-RED:
   lane this week or kill with a reason).
4. **ML:** drift gate on one unrotated file (BL-20260911-…) · four manifests blocked ~65 d (PI-20260929-UAOAYGBB-0001) · shadow-log horizon
   (MB-20260712) · promotion-readiness OOM (MB-20260719).
5. **Oldest:** BL-20260525-005 (171 d, prop shadow scores all zero) · BL-20260601-003 (164 d, no owner — the oldest unrouted) ·
   BL-20260621-ACCOUNT-HISTORY-PULL (144 d, an operator ask) · SRQ-20260715-REALMONEY-ALLOC-BENCHMARK (120 d, no owner) ·
   PRB-20260720-OPTIONS-PORTFOLIO-GRADUATION (115 d, no owner).

**Proposed drain:** the **GENERAL standing lane** takes it as soon as its surge list empties (row LANE-STRUCTURE-WEEK; the 05:52Z routine's
step 4b), working the list above in order: first the export fix, then tiers 1–2, then one disposition per no-owner item (own, date or kill
with a `terminal_reason`), 46 health + 20 research-ops + 17 desk + 15 perf no-owner items. **Never bulk-drop**: every drop is its own row
with its reason. The daily review keeps measuring regardless. Target for the dialogue: unrouted below last week's 166–176 by 11-19.

## 4. Week + roadmap

- **Weekly audit (11-11):** every live position protected at the venue (C1 pass, 17/17); TP doctrine fail; backlog fail; research SLO fail
  7/7 days; 29 unlogged SKILL amendments; 15 of last week's 17 audit rows unmoved.
- **Health (11-11, grade investigate):** real money clean 3 reviews running; live disk refilling (two leftover journal backups ≈ 4.9 GB of
  ~6 GB regrowth, MEASURED); off-VM register reads stale; trainer registry flat; IB paper id in public relay replies. **Late finding:** the
  Actions backlog is stranded, not slow (412 runs created before 11-11 20:53Z read `queued` and cannot be cancelled; newer runs start).
- **Programme review (#24940, merged):** structure exit a drag on 16/17 legs (9 already off); `tlt_pullback_1h` CONFIRMED on holdout (n 146,
  +6.4 R), fourth 1h ETF survivor; `spy_pullback_1h` did not replicate; M22 pairs 0/4; ML direction heads at the prior; prop ML new data
  families 0/6. Work rows proposed: **PR1111-SURVIVOR-PROMOTIONS** (tlt/qqq/slv/uso 1h, T3, 11-18) and **PR1111-M22-PAIRS-RETIRE-CASE** (T3, 11-18).
- **Roadmap (`roadmap_map.py --report`, re-run):** 0 orphan live rows, 0 orphan open units, 0 dangling refs. **28 of 36 milestone rows print a
  review date marked OVERDUE** (e.g. L-PROGRAMMES 10-14, L-OPS 10-22, M28 10-14). The weekly roadmap pass is filed on `WEEKLY-PLANNING`; re-dating
  them is part of this planning.
- **TP doctrine (`check_tp_doctrine.py`, re-run):** 84 routings / 57 legs. Compliant: real money **1/7**, prop 1/9, mirror 1/7, paper 4/61.
  Baseline 77 lines (audit: it grew 72 → 75 last week). TP-reach: 4 below floor, 5 reachable, 42 unmeasured of 51. (The perf review read
  82/56 and real money 1/6 the evening before: one real-money routing was added since.)
- **Research throughput (`research_slo.py`, re-run):** 7 breaches — survivors/month 0, trials per survivor 3,457, fires 24 h 16 (≥ 24),
  grade latency p90 6 d (≤ 2), undispositioned 24 h 18 (≤ 5), theme share 0.14 (≥ 0.5), research-ops record 9.1 h old (≤ 8); hold-PR wait
  could not look. OK: lands 24 h 21, runnable floor 46, held-out registered passes 30 d 83, authoring supply 1.15.

## 5. Schedule (`list_triggers`, enabled recurring, re-read 11-12)

| routine | cron (UTC) | bound to | last run |
|---|---|---|---|
| Manager review (once daily) | `52 5 * * *` | manager 11-11a | succeeded 11-12 05:52Z |
| Manager lane check-in | `17 */3 * * *` | manager 11-11a | succeeded 11-12 06:17Z |
| Thursday walk-through + planning | `17 6 * * 4` | assistant manager (forwards) | succeeded 11-12 06:17Z |
| Weekly reset protocol | `5 18 * * 3` | assistant manager (forwards) | succeeded 11-11 18:06Z |
| Research-ops pass (4×/day) | `47 2,8,14,20 * * *` | assistant manager | succeeded 11-12 02:48Z |
| Lane check-in (assistant) | `17 */6 * * *` | assistant manager | succeeded 11-12 06:17Z |

Facts for the dialogue: the research-ops routine fires 4×/day, yet its stored prompt still says "once a day at 14:47Z while pacing", and the
SLO reads fires 24 h = 16 and the ops record 9.1 h old. Reviews run from the reset protocol (`config/reset_protocol.yaml`), not separate
triggers. **Research dispatch is throttled by the frozen Actions backlog** (operator decision m1), so fires/lands this week are capped by
runner supply, not authoring.

## 6. Draft workplan (for the dialogue — not agreed)

**Capacity: UNKNOWN.** `spend_meter.py --capacity` → *"could not compute — the reading (2026-11-06T21:41Z) describes last week; record this
week's reading. Meanwhile run ONE lane (the floor)."* **Placeholder: ____ % used at ____ Z (operator's Usage reading).** The (a) set below may
not exceed that capacity less the standing routines; it is sized after the reading.

Spend is ESTIMATED (review lanes' cost estimates, or a typical ceiling for that lane shape); "—" means not estimated.

| # | item | lane | week_lane | tier | est. spend | source |
|---|---|---|---|---|---|---|
| 1 | F1: per-trade backtest rows for `ml_entry` + `ml_entry_eq_struct`, and a config-date cut in `live_vs_backtest.py` | perf-followup (Opus) | surge | 1 | ~$15 | perf F1 |
| 2 | P1: `ml_entry` Stage-2 demotion read (mirror net-of-cost + DSR) | Sonnet | surge | 1 (read) → 3 decision | ~$3 | ML P1 |
| 3 | Live VM disk: prune the two backups (dry-run first), helpers prune their own, cap syslog | vm-ops | surge | 2 | ~$5 | health C1 |
| 4 | PR1111-SURVIVOR-PROMOTIONS (tlt/qqq/slv/uso 1h) — evidence check and proposal | manager | surge | 3 | ~$5 | programme review |
| 5 | P5: `TMBENCH-QTM1B-BUILD`, then `ML-EXIT-ACTIONGRID-LABELS` (the reserved ML lane) | ML lane | surge | 1 | ~$6 | ML P5 |
| 6 | P2: K1 market-residual ENTRY target | ML lane | surge | 1 | ~$4 | ML P2 |
| 7 | P3: Foxhound-4 iteration subject + in-hand-data unit | ML lane | surge | 1 | ~$2 | ML P3 |
| 8 | Security trio: bearer-in-traceback, IB id masking, VM addresses in logs | general | surge | 1 | ~$6 | perf F6, health C5 |
| 9 | Stale register export fix (drain prerequisite) | general | throttle | 1 | ~$4 | health C2 |
| 10 | Backlog drain per §3 | general (after surge) | throttle | 1 | ~$30/day | 0b |
| 11 | P4: ML-CONSOLIDATION wave 1 + retire regime subjects | ML lane | throttle | 1 + one T2 archive | ~$5 | ML P4 |
| 12 | P6: lever rows (kill 2, dispatch 1, decide LEADLAG) | manager | throttle | 1 | $0–3 | ML P6 |
| 13 | RESEARCH-SLO-RED: one lane or kill with reason | research-ops | throttle | 1 | ~$5 | audit |
| 14 | PR1111-M22-PAIRS-RETIRE-CASE | manager | throttle | 3 | ~$2 | programme review |
| 15 | `queue_throughput.py` import crash (found by this lane) | general | throttle | 1 | ~$2 | this pre-read |
| — | Standing: daily review, research-ops 4×/day, live review + desk wakes, health checks | — | standing | — | — | — |

Carry-over from last week that is now on its second carry (a decision for the operator per protocol): ML-LEARNING-LEDGER, the four
`FRONTIER-LEVER-*` rows (3rd–4th scan), RESEARCH-SLO-RED, `ml_entry` per-trade evidence (E1, carried from 11-04).

## 7. Overnight 11-12

**#25120 merged** (`91a0bc032`): `trend_donchian_eth` `exit_head_action` close → annotate, data-backed by RQ-20261101-78fc-03 graded FAIL
(OOS dR/trade −0.061, CI LB −0.195, n 605, below every matched random truncation; #25119). Deployed per the manager; this lane did not
observe the running process. **#25110 merged** (pre-registers RQ-20261112-a7e8-03). Research dispatch is throttled by the frozen Actions
backlog (~199 queued per the manager this morning; health's 05:53Z count was 412 stranded; operator decision m1). The **desk wake has been
silent since 11-07** (lane DESK-WAKE-SILENT-1112; PR #25131 open reads it as "switched off by design, not wake missing"). ML results overnight:
counter-trend split **FAIL** (RQ-20261112-8d20-01, #25042); size-by-score **FAIL** (a7e8-04, −0.016 R per unit risk vs flat, n 11,240,
#25115); vol confound **INDETERMINATE** (a7e8-03, vol-tilt share 0.06, within-tercile t 0.84, #25111); IBS ETFs **FAIL as a near miss**
(a7e8-01, arm L +0.0492 R/trade over baseline vs a 0.05 bar; PR #25134 open; round 2 pre-registered symbol- and time-disjoint in PR #25139);
fade 1d ETFs **FAIL** (a7e8-02, #25134); feature-impact **M1 + M2 measured** (60/60 symbols, #25133, computed in-lane because the scheduled run
was never created).

## 8. Questions for the dialogue (ranked)

1. **Capacity:** this week's Usage reading — without it the WIP limit cannot be computed and the floor is ONE lane.
2. **Surge slot 1:** does F1 + P1 (a working demotion signal for the six real-money legs, starting with `ml_entry`) go ahead of new ML research
   this week?
3. **Diag 401:** direct diag reads return 401 since the 11-11 token rotation, blinding C5 cost drift, live-review grading and the desk system
   leg. Update the session environment's diag secret (an operator credential action), or accept relay-only reads this week?
4. P8: BTC-15m advisory head — hold one more weekly read (lane's recommendation) or soft-off now?
5. PR1111-SURVIVOR-PROMOTIONS and the M22 pairs retire case (both Tier 3, due 11-18).
6. Second carries (§6): ML-LEARNING-LEDGER, the FRONTIER-LEVER rows, RESEARCH-SLO-RED — schedule, date or kill.
7. Two review PRs are still open (#24953 performance, #24963 health): merge them so their records are on `main`.
