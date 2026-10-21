# Research map — the programmes and how they feed each other

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-14` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `RESEARCH-PROGRAMMES` (dispatched by the manager from the 2026-10-14 weekly planning; checklist row `WEEKLY-PLANNING`) · **Tier-1: nothing here changes a config, a roster or an order path.**

**Operator intent (weekly planning 2026-10-14, agreed verbatim):** research is the main focus. One long-term plan per goal, a deep roster of well-researched tests and models — not a filled queue. Programmes are **mutually supportive**: the AI trader is fed every test result; strategy improvement and frontier work inform active management. **Headline measure: net P&L per capital-day, in R and in $, per strategy (every leg pulls its own weight) and at portfolio level, weighted.** Top pain point: **giveback**. Brackets are **predictions** — the TP is where we expect price to reach, the SL is where we stop waiting.

How this fits the work system: a programme is a *plan*, not a third category of work (CLAUDE.md § "Two categories"). Each question below becomes a `research/queue/` unit and each build a checklist row, every one carrying a `roadmap` milestone ref. Full plan per programme: `01-ACTIVE-TRADE-MANAGEMENT.md`, `02-AI-TRADER.md`, `03-STRATEGY-IMPROVEMENT.md` (lane P3-STRATEGY-PROGRAMME), `04-MACRO-SLEEVE.md` (lane P4-MACRO-PROGRAMME) and `05-PROP.md` (lane P5-PROP-PROGRAMME) are all landed (2026-10-14); none is owed.

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
