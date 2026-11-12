# Research map — the programmes and how they feed each other

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-14` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `RESEARCH-PROGRAMMES` (dispatched by the manager from the 2026-10-14 weekly planning; checklist row `WEEKLY-PLANNING`) · **Tier-1: nothing here changes a config, a roster or an order path.**

**Operator intent (weekly planning 2026-10-14, agreed verbatim):** research is the main focus. One long-term plan per goal, a deep roster of well-researched tests and models — not a filled queue. Programmes are **mutually supportive**: the AI trader is fed every test result; strategy improvement and frontier work inform active management. **Headline measure: net P&L per capital-day, in R and in $, per strategy (every leg pulls its own weight) and at portfolio level, weighted.** Top pain point: **giveback**. Brackets are **predictions** — the TP is where we expect price to reach, the SL is where we stop waiting.

How this fits the work system: a programme is a *plan*, not a third category of work (CLAUDE.md § "Two categories"). Each question below becomes a `research/queue/` unit and each build a checklist row, every one carrying a `roadmap` milestone ref. Full plan per programme: `01-ACTIVE-TRADE-MANAGEMENT.md`, `02-AI-TRADER.md`, `03-STRATEGY-IMPROVEMENT.md` (lane P3-STRATEGY-PROGRAMME), `04-MACRO-SLEEVE.md` (lane P4-MACRO-PROGRAMME) and `05-PROP.md` (lane P5-PROP-PROGRAMME) are all landed (2026-10-14); none is owed.

## Programme review 2026-11-11 (lane PROGRAMME-REVIEW-20261111)

Population: units with a result row generated 2026-11-04T19:30Z..2026-11-11T19:30Z (`research_ops_checks.py --kind programme_review --since 7d`; 2,183 units read, 0 unreadable; 455 result rows): **311 units with rows** — 72 pass, 134 fail, 42 indeterminate, 5 no_action_warranted, 1 not_applicable, 57 with no unit verdict yet (28 ungraded). 119 carry a programme field (P1 38, P2 50, P3 14, P4 2, P5 9, P6 6, P7 0); **192 do not** (live_strategy 110, new_strategy_prop 37, ml_health 31, infra 11, timeframes 2, none 1) and are assigned below by what they ask. Every PASS is a discovery until its confirmation passes; batch denominators are from the packet's `batches`.

**Two-track summary.**
- **TRADING:** the week's money result is an exit result. The structure exit was the drag on 16 of 17 legs, it came off 9 legs on 2026-11-05 (#23485), and two losing legs (trend_donchian_1h, htf_pullback_trend_2h) turn positive without it. A fourth 1h ETF survivor confirmed (tlt_pullback_1h). **None of the four survivors has a promotion proposal yet, and qqq/tlt 1h are `testing` on no book.** Runnable TRADING units were **0** at review time, a supply gap that the three P3 iteration-3 nodes partly close.
- **MODEL:** answers, not edge. The regime head is skilful but has no consumer. Direction heads sit at the prior. ML SL revision is a dev-stage artefact. ML ENTRY lives at 1h only. Prop ML found no signal in three new data families. 8 of 9 ml_model iteration units are blocked past due. The consolidation (#24897) is the right place to schedule or kill them.

**Iteration loop.** Orphans at review time (`iteration_orphans.py --legacy`): strategy_leg 8, ml_model 0 (8 overdue), ltr_class 5 (2 overdue). Strategy-leg dispositions: spy_pullback_1h authored (P3-ITER3, counts as covered once the replenisher emits it); qqq_pullback_1h and tlt_pullback_1h are CONFIRMED survivors whose next step is a Tier-3 promotion proposal (handoff, manager); tsmom-crypto, xsec-crypto, tsmom-etf, movement-capture and vol-premium-proxy go to research-ops in handoff, each with its top untested lever from its own 58e4 record (their harness `edge_portfolio_discovery.py` takes a scratch data root, so they are not runner-ready from a node). trend_donchian_1h and htf_pullback_trend_2h were covered and got their iteration-3 holdouts. ml_model 0 orphans / 8 overdue-blocked. ltr_class 5 orphans (no driver, PI-20261104-SVCWDSDX-0002; awaiting lane LTR-CLASS-GRADE).

**Feed table (updated)**

| from | to | what | destination | state |
|---|---|---|---|---|
| P1 | P2 | 5e05 structure-OFF + 47b6 tighten fails as MANAGE negative class | MANAGE head labels (ML lane) | open |
| P1 | P5 | structure-OFF on prop pullback legs | eth_pullback_prop_2h (5e05-10) | landed by #23485 |
| P3 | P1 | exit-process every survivor before promotion | tlt/qqq/slv/uso 1h | open (manager) |
| P3 | P2 | survivor legs as labelled rows; spy 1h holdout as a regime-change example | P2-MECE-D2 | open |
| P2 | P3/P1 | no head passed a money gate: no Tier-3 candidate | — | none |
| P5 | P2 | oi_flow / basis / book 0 of 6: negative for new feature families | P2 feature backlog | recorded |
| P4 | P2 | PPI surprise as an event feature | after the ES placebo | waiting |
| P6 | all | needs_review 97 and the research-ops record gap | manager | open |

## Programme review 2026-11-04 (lane PROGRAMME-REVIEW-20261104)

Population: units with a result row generated 2026-10-28T19:41Z..2026-11-04T19:41Z (`research_ops_checks.py --kind programme_review --since 7d`, 1,932 units read, 0 unreadable, 662 result rows): **447 units with rows** — 107 pass, 210 fail, 25 indeterminate, 11 no_action_warranted, 94 with no unit verdict yet (76 ungraded + 18 needs_review/null). 302 carry a programme field (P1 53, P2 54, P3 95, P4 24, P5 48, P6 18, P7 10), 145 do not (live_strategy 70, new_strategy_prop 32, infra 13, ml_health 13, timeframes 6, macro 5, regime 5, none 1) — assigned below by what they ask. Every PASS is a discovery until its confirmation passes.

**Unprogrammed units, assigned by what they ask:** live_strategy 70 → P3 (Stage-0 re-reads, M20 sweeps, same-symbol reads) and P1 (exit levers); new_strategy_prop 32 → P5 (prop pace, replacements) and P3 (structure exits on prop legs → P1); ml_health 13 → P2; infra 13 → P6; timeframes 6 → P7; macro 5 → P4; regime 5 → P3 (entry regime levers) / P2 (heads).

**Two-track summary.**
- **TRADING.** The strongest result of the week is not a lever but a window: three 1h ETF legs (slv/uso/qqq) confirmed on an 8-year dukascopy holdout, and two more (spy/tlt) whose 365-day records fail are positive over 8 years — the 365-day Yahoo record is the binding constraint on every 1h ETF verdict. Against that, the 1h/2h BTC legs lose at power, and the roster-wide `structure_exit: pivot=5` default (20 legs) lost on 5 of 6 powered legs in its static form and on all 3 legs run in its ratcheting form.
- **MODEL.** The regime head is skilful and robust (11 passes against the class prior, no learner family better), so the question has moved from "is the model good" to "does it change a money decision" (D2 on a real-money leg, not yet tested). ML timeframes do not scale below 1h, and the 1h harness itself does not reproduce round 1 — every timeframe read is provisional. MODEL has 0 runnable units: a supply gap that the MECE nodes fill once PR #22892 lands.

**Feed table (this week's changes)**

| from | to | what | destination | state |
|---|---|---|---|---|
| P1 | P3 | structure exit pivot=5 lost on 5/6 legs | NOSX arms in P3-ITER2-htf-pullback-trend-2h, P3-ITER2-trend-donchian-1h; manager Tier-3 packet | authored / handoff |
| P1 | P2 | 5e04-01 PASS: SL-only structure stop + moving TP on ml_entry | P2-MECE-D6-pointer-v0 | needs_authoring |
| P2 | P1/P3 | regime head skilful, not yet a gate | P2-MECE-D2-regime-real-money | needs_authoring |
| P2 | P7 | 15m/5m ENTRY not viable net of cost (provisional) | no 15m/5m ML units until b620 reproduces | standing |
| P3 | P2 | 5 1h ETF legs with 8-year evidence | ETF labels for D3/D6 | open |
| P3 | manager | survivors slv_trend_1h, uso_trend_1h, qqq_pullback_1h | mandate_resolver S1→S2 proposals (Tier 3) | handoff |
| P6 | all | evidence builder omits skip_hours on pullback legs | pipeline item (this review) | filed |
| P1 ↔ P5 | — | M2 stale exit passes on 3 2h pullback legs incl. eth_prop | per-leg confirmations | research-ops |

## Programme review 2026-10-28 (lane PROGRAMME-REVIEW-20261028)

Population: research units with a result row generated 2026-10-21T19:30Z..2026-10-28T19:30Z (`research_ops_checks.py --kind programme_review --since 7d`, 1,480 units read, 0 unreadable): **445 units, 412 graded** (70 pass, 50 indeterminate, 292 fail), 285 with a programme field and 160 without (live_strategy 70, regime 27, ml_health 21, macro 20, infra 13, new_strategy_prop 8, none 1). This review assigns the 160 by what they ask, not by the field (map section). Every PASS below is a discovery until its confirmation unit passes. **Cost basis:** about 36 of the 70 PASS rows are crypto-harness runs charged 7.5 bps round-trip (MEASURED from each result's argv); only RQ-20261028-001 carried the measured Bybit-linear 11.0 bps. A lever A/B delta is nearly fee-neutral (both arms pay it); an absolute Stage-0 or breadth PASS is not.

**Unprogrammed clusters, assigned by what they ask:** `live_strategy` 70 (Stage-0 re-validations `c56e`/`be01`/`bda2`/`008` and desk entry units `e535`/`fe57`/`8a01`/`a3f1` go to P3; desk lifecycle `bf56`/`8b01`/`d1f5` and TP compliance `bea9` go to P1; the giveback census `9807-01` goes to P1); `regime` 27 (single-leg vol/ADX levers `ae17`/`3a84`/`326f` go to P3 Q5); `ml_health` 21 to P2; `macro` 20 (calendar-event types) to P4; `infra` 13 to P6; `new_strategy_prop` 8 to P3/P5.

**Two tracks, three sentences each**
- **TRADING.** The week's strongest result is negative and consistent. Tightening stops on the declared wide-trail legs loses R: about 140 mechanical lever units with 6 passes (chance rate), and the desk's Claude management −0.159 R vs hold driven by 981 tightens. What survives is selective or entry-side: the direction filter confirmed on a disjoint window, the BE floor and CHOP-gated trail awaiting confirmation, the TP-extend compliance, and trend-Donchian breadth across ~17 alt perps. All breadth evidence is priced at 7.5 bps, not the venue's 11.0, so the top TRADING test is a re-cost, not a new idea. The 5 bybit_1 flips in #20966 are mostly window drift for the trend legs (diagnosed by 3 units) and a second, independent FAIL for the two scalps, whose retirement case is the operator's.
- **MODEL.** No learner beats the shipped LightGBM regime head (0 of 23 arms) and the direction heads do not beat the prior at 1h. New information moves log-loss (range-vol on all three symbols), so the lever is information and targets, not capacity. The cost gate's refusal of all 9 setup-metalabel heads is a data refusal (gross frozen datasets), not a measured loss: the meta-label line has no answer at the cost basis that matters until PI-20261028-V8KBRR5H-0004 rebuilds them. MODEL runnable supply is 0. That is a **build gap** (the cost-net rebuild, #20967's labels on main, a cross-asset feature block), not an authoring gap; this review files the three gated nodes rather than more learner arms.

**Feed table (state 2026-10-28)**

| feed | from -> to | what | destination | state |
|---|---|---|---|---|
| tighten-loses belief | P1 -> P2 | "tighten" is the negative class; in-trade state is the information | `P2-desk-checkin-exit-head` | waiting on #20967 |
| desk priced labels (12,500 check-ins) | P1 -> P2 | action-value target | `P2-desk-checkin-exit-head` | waiting on #20967 |
| cost-net datasets | P6 -> P2 | a cost basis for every head | `P2-Q2-costnet-metalabel-regate` | build PI-20261028-V8KBRR5H-0004 |
| no head beats its prior net of cost | P2 -> P1/P3 | nothing is a gate yet; no Tier-3 candidate | — | stated, nothing filed |
| breadth at 11.0 bps | P3 -> P5, P1 | candidate legs for the P5-Q6 pool, and exit processing | `P3-Q8-recost-11bps-eth4h` | authored |
| #20966 flip diagnosis | P3 -> manager | keep on floor vs retirement case | `P3-RECOST-flip-*` x3 | authored |
| loss-cut / BE floor | P1 -> P5 | left-tail levers for the prop EV grid | P1 confirmations | authored |
| PPI tilt | P4 -> P3 | release-day tilt on spy/qqq 1d trend legs | `P4-Q2-ppi-rty-econ` (re-point) | ready; lever `MACRO-EVENT-RANKTILT` |
| daily long-only Donchian | P7 -> P3, P1 | a new position-trade family | `P7-Q5-confirm` disjoint-symbol check | research-ops |
| proxy-symbol fee | P6 -> P3/P5/P7 | breadth symbols priced at the venue fee | build question for the manager | filed in the review record handoff |

The 2026-10-21 feed rows: momentum-levers live is still `landed_unproven` (MOMENTUM-LEVERS-LIVE); breakout_2 sizing is now **applied** (0.35%); the family-breadth units have landed (above); the daily-Donchian and ATR-percentile re-asks have landed (P7 section); `ml_health` supply is still build-bound.

## Programme review 2026-10-21 (lane RESEARCH-PROGRAMME-REVIEW-1021)

**Population:** every unit in `research/queue/*.yaml` with `grading.graded_at` 2026-10-14..2026-10-21, read on main at ~18Z:
**657 graded** -- 171 carry a programme field (P1 122, P2 7, P3 2, P4 20, P5 10, P6 1, P7 9) and 486 do not (by theme:
new_strategy_prop 157, live_strategy 170, ml_health 58, regime 53, macro 22, infra 13, none 13). Per-programme readings are in
each plan's "Programme review 2026-10-21" section.

| feed | from -> to | state |
|---|---|---|
| momentum/stall-keyed exit levers confirmed on eth_4h, xrp_4h, slv_1d (+ Q9 leads) | P1 -> live roster | build-gated: MOMENTUM-LEVERS-LIVE, `stall_pull_in` TP rule |
| trail 4.5 on eth_prop, priced on three prop books | P1 -> P5 | EV read done; adoption is a P5/Tier-3 call |
| breakout_2 sizing 0.5% -> 0.35% dominates (RQ-20261016-029) | P5 -> config | NOT applied; rung 2 queued (7c2b-12) |
| family breadth on new perps (7c2b-06..-10, -13, -14) | P3 -> P5 (1h cells), P1 (exit processing of any new leg) | queued |
| daily Donchian D55 / LONG filter transfers (7c2b-03/-04) | P7 -> P3 overlap read | queued |
| ATR-percentile scale error (ef5d-06/-07) | P7 -> P3 Q5 instrument fidelity | harness guard landed; re-asks 7c2b-01/-02 |
| PPI drift real but sub-cost | P4 -> (an ES/NQ leg to tilt) | parked until such a leg exists |
| ml_health supply | P2 -> infra builds | build-bound: 15 blocked ml_health units, 0 runnable |

## 1. The programmes, in order

| # | programme | goal | the measure it moves | roadmap | core questions, in dependency order |
|---|---|---|---|---|---|
| **P1** | **Active trade management** (merges M20 + M31; "brackets as predictions") | Every leg carries a real TP at entry, revises it through the trade, and stops waiting on a rule — and the giveback shrinks | **Net R per capital-day per leg**, real money first; giveback R (peak − realised) per leg; `check_tp_doctrine.py` compliant routings (MEASURED 2026-10-14 07:28Z: **0 of 50**; re-run 2026-10-16T07:15Z: **0 of 54**; real money + prop 13 routings, 4 real-money with a sentinel TP, 13 with no TP revision) | M20, M31 | Q1 giveback census → Q2 entry TP from the leg's own MFE distribution, conditioned on vol/regime → Q3 per-bar TP revision rule → Q4 SL "stop waiting" rule → Q5 the momentum-turn detector → Q6 producer + live parity → Q7 prop paths. **Destination (2026-10-14, row `IN-TRADE-EXIT-MODEL`): Q8 — per-bar P(SL before TP \| state now) and an exit-now rule, net of cost** (`RQ-20261014-d6e7-01..06`) |
| **P2** | **AI trader** (M23 meta-labeling revived, with the signals catalog; M25, L-REGIME) | One learner that reads every signal and every test result, and separates a leg's good trades from its bad ones net of cost | Net R per capital-day of the *filtered* book vs the unfiltered book, per leg; advisory-head log-loss vs class prior; model-family diversity (`ml_plan_status.py --diversity`, 78 % GBDT on 2026-10-11) | M23, M25, L-REGIME, M41 | labels (the label wall, ML-D2) → signals catalog as the feature contract (`docs/reference/signal-catalog.yaml`, 334 entries 2026-10-08) → meta-label head on P1's per-trade paths → regime good-vs-bad (REGIME-PROGRAM) → frontier families (ML-F1..F15) → proposer line (ML-S3, parked) |
| **P3** | **Strategy improvement** (M21 entries, M22 small-TF/pairs, M27 scalps, perf-followup) | Every live leg pulls its own weight; losers are tuned or retired on evidence | Per-leg net R per capital-day (real, mirror, paper separately); Stage-0 pass rate at configured params (MEASURED 2026-10-14, `stage0_capital_day_census.py`: real money 3 of 7 legs pull weight, 1 drag, 3 underpowered; prop 0 of 2, both drag on 2/4 folds); perf-review grade | M21, M22, M27, L-LADDER | per-leg weight (same census as P1-Q1) → tune-before-retire (perf-followup Track 1) → lessons → extrapolate (Track 3) → new families at Stage 0 → portfolio overlap/concentration (Track 4) |
| **P4** | **Macro sleeve** (M28, M29, WEPE) | A thesis-driven, weeks-horizon sleeve whose conviction axes add net R through defined-risk instruments | Net R of `alpaca_options_paper` per conviction axis vs the naive floor; event-surprise hit rate | M28, M29 | MACRO-RESHAPE wire-and-rescore → PM-surprise (RQ-20261009-903) → news veto / standalone news edge (NEWS-ALPHA-PROGRAM) → M29 wakes only on a read-out |
| **P5** | **Prop** (L-PROP) | Prop accounts execute, protect and clear evaluations as an expected-value question (row B6) | E[profit before the account dies] per account; gradable prop closes (PROP-EXIT-READ) | L-PROP | first gradable closes → per-leg sizing (PROP-PER-LEG-EV-GRID) → breadth units into a candidate pool → P1-Q7 (TP amend on the dxtrade/phone paths) |
| **P6** | **Data infrastructure** (L-DATA; supersedes M9's data half) — the plumbing under P1 and P2 | Every model learns from labels that are measurements, at a grain fine enough for its question, from every free information class, with train = serve features | Finest refreshed grain per crypto symbol (MEASURED 2026-10-14: 5m, 1m only stale BTC/MES v001); shards whole (4 v002 shards cut, SPLG empty); information classes beyond BTC (funding/OI, flow: BTC only); share of SL/TP ties resolved by finer data (0%) | L-DATA | Q1 tie-label error (`RQ-20261014-da7a-01`) → Q2 1m + derivatives archives → Q3 Binance-vs-Bybit label agreement → Q4 tie-aware labels + per-bar first-passage label store (under the exit lane's EXIT-PATH-EMIT-OFFLINE) → Q5 derivatives-metrics information lift → Q6 data catalog → Q7 Parquet + GC |
| **P8** | **The alpaca_live book** (lane ALPACA-LIVE-BOOK-PLAN, 2026-11-11; [`08-ALPACA-LIVE-BOOK.md`](08-ALPACA-LIVE-BOOK.md)) | Something that earns more on the $194.52 cash book than Foxhound-4 alone; Foxhound-4 stays live until a challenger clears the P8 promotion rule (§ 5) | **Net return per month on the alpaca_live cash book** (long only, whole shares, one slot, T+1, live sizer) via `scripts/research/alpaca_live_book.py`, net of the full cost stack | L-ML-LIVE, L-LADDER | Foxhound-4 on the book (207f-01) → selection (207f-02) · label (207f-03) → challengers on the book (207f-04) → head-to-head → Tier-3 packet; rotation / features / pool / horizon / options nodes |

## 2. Cross-programme feeds — what is shared, and where it lives

```
            ┌────────────────── SHARED RESULTS STORE ──────────────────┐
            │ research/results/<unit>/*.jsonl (E5 records, every run)  │
            │ docs/research/{m20,e35}-sweep-corpus.jsonl (cell rows)    │
            │ docs/research/research-disposition-ledger.jsonl (verdicts)│
            └───────────┬───────────────────────────────┬──────────────┘
                        │ every result is a row         │ every verdict is a label
   SHARED SIGNALS       ▼                               ▼          SHARED LABELS
 docs/reference/   ┌─────────┐   per-trade paths    ┌─────────┐  position_telemetry (peak_r,
 signal-catalog    │   P1    │ ───────────────────▶ │   P2    │  giveback_r, bars_since_peak)
 .yaml (334)  ───▶ │ active  │  (ML-LEG-CORPUS)     │   AI    │  trades (realised R, exit_reason)
 regime detector   │  mgmt   │ ◀─────────────────── │ trader  │  harness --emit-trades (mfe_r)
 ADX / vol / fc_*  └────┬────┘  exit heads, bandit  └────┬────┘  disposition verdicts
                        │ "which leg is worth managing"   │ "when is a leg primed"
                        ▼                                 ▼
                   ┌─────────┐    Stage-0 records     ┌─────────┐
                   │   P3    │ ◀────────────────────▶ │   P4    │   P5 prop takes P1's producer
                   │strategy │   regime conditioning  │  macro  │   (TP amend paths) and P3's
                   └─────────┘                        └─────────┘   Stage-0 breadth pool
```

| feed | what travels | producer → consumer | today (MEASURED 2026-10-14) |
|---|---|---|---|
| **Results store** | one E5 record per run; cell rows in the two corpora; verdicts in the disposition ledger | every programme → P2 (training rows), P3 (tune/retire), manager (mandates) | 502 result dirs under `research/results/`; the four active-geometry units landed 2026-10-08 and have **0 ledger dispositions** (unread PASS rows on `xrp_pullback_2h`, `ada_pullback_2h`, `trend_donchian_xrp_4h`) — P1-Q3 starts there |
| **Signals catalog** | every variable a strategy, head or monitor reads; health state per input | `signal-catalog-guard` → P1 (what a revision rule may condition on), P2 (feature contract), P3 (new-strategy inputs) | 334 entries, hand-maintained, guard-enforced; 4 unguarded surfaces listed in the file |
| **Labels** | per-trade path rows: peak R, giveback, bars since peak, exit reason, regime at entry; harness `mfe_r` emits | P1 census + `ML-LEG-CORPUS` → P2 meta-label head (M23) and exit bandit (ML-F4); P3 lessons | `position_telemetry` is live (M31) but is one upserted row per position; the committed per-trade corpus does **not** exist (ML-LEG-CORPUS queued) — the lever that unblocks RQ-20261009-900/901 and ML-F4. **Per-bar in-trade paths exist nowhere** (MAE recorded nowhere): `EXIT-PATH-EMIT-OFFLINE` (Tier-1, offline harness emit — feeds the bandit `RQ-20261011-9da8-04`, `blocked/RQ-20261014-9807-05` and P1-Q8) and `EXIT-PATH-TELEMETRY-LIVE` (Tier-2 proposal, live parity); interim fixed-bracket re-walk `first_passage.py` runs now |
| **Regime knowledge** | which (trend, vol) cells a leg is primed in; advisory head scores | P2 L-REGIME → P1 (condition the TP on regime), P3 (selectivity), P4 (thesis timing) | 8 regime units BLOCKED (G4 baseline); REGIME-PROGRAM queued |
| **Cost stack** | fee + slippage + funding via `execution_costs.resolve_cost_policy()` | L-LADDER → every harness every programme runs | `backtest_orb.py` and `src/backtest/backtester.py` still lack it (CLAUDE.md § D1); out of scope for any promotion corpus |

## 3. Which questions unblock which

| this question (programme) | unblocks |
|---|---|
| P1-Q1 giveback census (`RQ-20261014-9807-01`) | P1-Q4 cell choice; P3 per-leg weight (same record); P2 label of "giveback trade" |
| P1-Q3 confirmation of the landed revision cells (`RQ-20261014-9807-03`) | P1-Q6 producer flip (Tier-3) on the first confirmed real-money leg; retires RQ-20261009-900/901's step-1 need on those legs |
| P1-Q8 first-passage census (`RQ-20261014-d6e7-01`) | the state models (`d6e7-02/04`) → exit-now policies (`d6e7-03/05`) → harness-native confirmation (`blocked/d6e7-06`); P2 Q3.6 |
| `EXIT-PATH-EMIT-OFFLINE` (build, P1/P2 lever) | `blocked/RQ-20261014-d6e7-06`, `blocked/RQ-20261014-9807-05`, the bandit `RQ-20261011-9da8-04` (per-bar states) |
| ML-LEG-CORPUS (build, P2 lever) | P1-Q2 conditioned MFE target (`blocked/RQ-20261014-9807-02`), P1-Q5 momentum-turn labels (`blocked/RQ-20261014-9807-05`), RQ-20261009-900/901, ML-F4 bandit |
| P2 label wall (ML-D2) | whether M23 runs on live labels or backtest-augmented ones; sets P2's whole cadence |
| P3 Stage-0 at configured params (pairs RQ-20261007-005..008 — all four PASSed, but MEASURED 2026-10-14 the rolling-β R scale understates cost ~775×, so they are unreadable until `PAIRS-R-SCALE` + `RQ-20261014-470a-12`) | P5 breadth pool; M22 roster |
| P5 PROP-EXIT-READ (gradable closes) | P1-Q7 prop TP amend; P5 EV grid; RQ-20261007-002's re-run |
| P4 MACRO-RESHAPE read-out | M29 wake; NEWS-ALPHA standalone test's baseline |

## 4. What each programme needs from infra

| programme | needs | state (MEASURED unless marked) |
|---|---|---|
| P1 | `position_telemetry` reachable to a runner (trainer synced journal, or a diag pull); `levers`/`cells` inputs on the m20 sweep for census-keyed cells; a `{"tp"}` producer per strategy unit (TP-DOCTRINE B1, Tier-3); prop TP amend on dxtrade (plumbed) and phone (BUILD B2) | telemetry live; sweep takes `levers` but not custom giveback cells (fixed `gb1R_afterMFE1R/2R`); producer merged, **no leg declares a rule** |
| P2 | ML research runner (ML-RQ-RUNNER) → trainer idle windows 03–05Z / 07–24Z; published market dataset for off-VM bake-offs; GPU via Kaggle (30 h/wk) with RunPod fallback; the per-trade corpus (ML-LEG-CORPUS); label-wall measurement | router + windows landed 2026-10-13; BTC/SOL 15m shards truncated (ML-SHARD-TRUNCATED); drift retrain is 63.7 % of trainer CPU and growing (trainer-workload-2026-10-13) |
| P3 | config-exact harnesses with the full cost stack; monthly M20/E35 generated sweeps; the grade pile cleared (RESEARCH-GRADE-PILE) | 13 harnesses; 2 outside the cost stack; 17 hand-written results ungraded on 2026-10-11 |
| P4 | point-in-time macro store; event join with a production caller; PM collector | PM-COLLECTOR landed; event join has no caller |
| P5 | prop journal exit prices (PROP-EXIT-READ); ticket supersede/reissue | first velotrade close had null exit_price/pnl |
| P6 (serves P1/P2) | a persisted 1m archive + perp-derivatives archive for the 6 crypto roster symbols; tie-aware labels; a catalog of the stores | none persisted at < 5m except stale BTC/MES 1m v001; 4 cut v002 shards; plan `06-DATA-INFRA.md` |

## 5. Cadence and ownership

| when | what | owner |
|---|---|---|
| per merge | result → disposition → roadmap writeback (the lane) | the landing lane |
| 4×/day | research-ops: pipeline health, grade landed results, retire stale units | research-ops Sonnet lane |
| daily | manager review reads `roadmap_map.py --report`; P1 census row is the giveback line in the brief | manager |
| weekly (Wed) | this map re-read against the measured state; re-weight `THEMES.yaml`; the next programme doc lands | WEEKLY-PLANNING |
| weekly (Sun) | `/ml-review` step 9 (ML plan loop) + frontier scan feed P2 | ML-ROADMAP-LOOP |

## 6. Landed programmes (nothing owed)

**Landed since:** `02-AI-TRADER.md` (#18015, lane AI-TRADER-PROGRAMME); `03-STRATEGY-IMPROVEMENT.md` (lane P3-STRATEGY-PROGRAMME, 2026-10-14: Stage-0 capital-day census `RQ-20261014-470a-11`, 11 runnable units `470a-01..11` incl. the fresh-window confirmation `470a-01` of `RQ-20261014-f0e2-05`, and the pairs R-scale finding, row `PAIRS-R-SCALE` + `blocked/RQ-20261014-470a-12`); `04-MACRO-SLEEVE.md` (2026-10-14, lane P4-MACRO-PROGRAMME): Q1..Q7, first-two-week units `RQ-20261014-4a4c-01..08` (runnable) + `blocked/RQ-20261014-4a4c-09`, and `RQ-20260928-010` re-scoped. P4's § 4 infra line is refined there: the event join has no caller in the *offline* replay either (`RQ-20260928-009`), and `macro-valuation-backfill.yml` lands no E5 record (`MACRO-BACKFILL-E5`).

`05-PROP.md` landed 2026-10-14 (lane P5-PROP-PROGRAMME): Q1..Q7, first-two-week units `RQ-20261014-f516-01..10` (runnable) + `blocked/RQ-20261014-f516-11`; P3's census grades both prop legs `drag` on fold consistency (2/4), a P5 input. **Nothing is owed:** all five programmes (01..05) are landed. Each is re-read weekly against the measured state (§ 5, WEEKLY-PLANNING).

`06-DATA-INFRA.md` landed 2026-10-14 (lane DATA-INFRA-PROGRAMME, operator directive ~21:35Z): the data plumbing under P1/P2 — measured audit of every ingest/label/dataset path, ranked open-source sources with licence and size, target architecture, rows `DATA-CATALOG`, `DATA-KLINE-ARCHIVE`, `DATA-DERIV-ARCHIVE`, `DATA-LABEL-TIES`, `DATA-INTRADE-LABEL-STORE`, `DATA-STORE-PARQUET-GC` (Tier-2) and units `RQ-20261014-da7a-01` (runnable) + `blocked/RQ-20261014-da7a-02/03`. It owns the plumbing; the IN-TRADE-EXIT-MODEL lane owns the exit model and the harness path emit (`EXIT-PATH-EMIT-OFFLINE`).
