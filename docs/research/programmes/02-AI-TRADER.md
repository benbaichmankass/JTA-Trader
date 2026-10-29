# 02 — AI trader: research programme of record

> **Doc status:** `live` · category `evidence` · last verified `2026-10-14` (every number below is MEASURED on `main` at d577b215e or in this lane's sandbox on 2026-10-14 unless marked INFERRED; re-run the named command rather than quoting the figure) · lane `AI-TRADER-PROGRAMME` · checklist row `AI-TRADER-PROGRAMME` · requested by the operator's weekly planning, 2026-10-14, via the manager (session_01G16FfyYSmDPQuuW55BuTmK) · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md)

> **What this is.** The research half of goal **G4 (AI trader)** laid out as questions in dependency order, each with a ladder of pre-registered tests, and a 3–4 week backlog. It is a **plan**: it authorises nothing (tiers, mandates and the two execution gates are unchanged) and it is not a third category of work. **The work is the rows and units it names.** The machine-readable carrier of the ML plan stays [`docs/plans/ml-plan-items.yaml`](../../plans/ml-plan-items.yaml) (checked weekly by `python3 scripts/ops/ml_plan_status.py`); where this document and a row or unit disagree, the row or unit wins and this document gets fixed. The build-side plan (infra, producers, parity) stays in `ROADMAP.md` § "AI trader (ML) — build plan"; this document does not restate it.
>
> **Sibling documents.** `docs/research/programmes/RESEARCH-MAP.md` (the cross-programme map) and the Active Trade Management plan are being written by a parallel lane (session_01XhRKuC7ba8TzVLCpyeY3aN) and were **not on `main` when this was landed** (checked at d577b215e). Where this programme touches exits it names the lever the ATM plan owns and stops; the manager reconciles the two at the next weekly pass. The signals half of this programme is [`docs/research/SIGNALS-CATALOG.md`](../SIGNALS-CATALOG.md).

---

## Programme review 2026-10-28 (lane PROGRAMME-REVIEW-20261028) — MODEL track

Population: research units with a result row generated 2026-10-21T19:30Z..2026-10-28T19:30Z (`research_ops_checks.py --kind programme_review --since 7d`, 1,480 units read, 0 unreadable): **445 units, 412 graded** (70 pass, 50 indeterminate, 292 fail), 285 with a programme field and 160 without (live_strategy 70, regime 27, ml_health 21, macro 20, infra 13, new_strategy_prop 8, none 1). This review assigns the 160 by what they ask, not by the field (map section). Every PASS below is a discovery until its confirmation unit passes. **Cost basis:** about 36 of the 70 PASS rows are crypto-harness runs charged 7.5 bps round-trip (MEASURED from each result's argv); only RQ-20261028-001 carried the measured Bybit-linear 11.0 bps. A lever A/B delta is nearly fee-neutral (both arms pay it); an absolute Stage-0 or breadth PASS is not.

**Graded in the window: 41 with `programme: P2`** (ml_health 2 pass, 20 fail, 13 indeterminate; regime 2 pass, 4 fail), plus 21 unprogrammed `ml_health` units (3 pass, 6 fail, 11 indeterminate), which this review assigns to P2. `runnable_by_track` in the packet: **MODEL 0**, TRADING 41, INFRA 4.

**What was learned**
- **The learner is not the bottleneck; stop adding learner-family arms to the regime head.** 23 learner/capacity units graded this week on the shipped-shape LightGBM regime head (1h and 15m published shards, BTC/ETH/SOL) and **0 passed**: 13 FAIL and 10 INDETERMINATE. The units are `3947-19..26`, `916f-01`, `90d3-01..03`, `a142-01`, `ed1c-29..34`, `b376-01` and `RQ-20261025-008..010`, covering HistGB, ExtraTrees, MLP (default and regularised), CatBoost, multinomial logit, calibrated logistic, larger and smaller LightGBM, and heavier regularisation. With 23 tries the expected count of chance passes is about 1, so zero means "no learner is better", not "underpowered". The competing hypothesis "the features cap every learner" fits the next point.
- **Information beats capacity, and calibration moves before ranking.** The four range-vol (Yang-Zhang set) estimators lift the SOL 1h regime head on macro-F1 (`3a84-11`), on a longer tail (`c584-01`) and on log-loss (`RQ-20261024-002`). They lift BTC and ETH 1h on LOG-LOSS (`a1f3-15`) but not on macro-F1 (BTC `3a84-09`/`RQ-20261027-006` FAIL, ETH `RQ-20261027-002` INDETERMINATE). New information improves probability quality broadly and ranking only on SOL.
- **Direction is not predictable from these features at 1h; 15m is unresolved.** At 1h four variants of the direction head failed against the class prior on log-loss: recent window `a1f3-13`, range-vol `-14`, wider embargo `-16`, and SOL family transfer `2a2e-10`; the regularised arm `a1f3-12` is INDETERMINATE. At 15m `3e41-15/-16` are INDETERMINATE.
- **The setup-metalabel refusal (#20869) is not a verdict on edge.** The new cost gate refuses all 9 setup-candidates heads with `eval_not_cost_net`. Their datasets are frozen GROSS builds from 2026-06/08, and the cycle never rebuilds them (PI-20261028-V8KBRR5H-0004). Until a cost-net rebuild exists, the meta-label line has **no measured answer at the cost basis that matters**. That is a build gap, not a FAIL.
- Drift (`RQ-20261025-004` FAIL; `6e85-01` FAIL): the regime-head score drift is not explained as input-mix shift on the read run. No new node; `P2-Q1.3-*` carries it.

**Failed first tests: diagnoses**

| FAIL cluster | likely cause | evidence | next |
|---|---|---|---|
| learner families vs LightGBM (13 fail, 10 indet.) | **idea at this feature set**: the features cap the learner | 0 of 23; range-vol information moves log-loss where learners do not | no new learner arm on the regime head until a new information block lands (cross-asset, `P2-Q4-cross-asset-features`, build-gated) |
| 1h direction vs prior (4 fail, 1 indet.) | **idea / information** | 4 variants, same sign | no 1h re-ask on the six shared features; any direction work needs new information first |
| setup-metalabel cost refusal (9 heads) | **harness / data** (gross rows) | refusal reason `eval_not_cost_net` | `P2-Q2-costnet-metalabel-regate` after PI-...-0004 |
| giveback from entry columns (`4b82-22/-23`) | **information**: the signal is in-trade | P1 `eba2-01/-04` PASS in-trade | `P2-desk-checkin-exit-head` |

**Answered / unlocked / retired.** Answered: learner choice on the regime head at the six shared features plus range-vol (the 23 tested learner configurations did not beat the shipped LightGBM; LightGBM stands; nothing retired). Unlocked: the in-trade action-value target (desk labels). Nothing retired.

**Next 3-4 weeks (value-ranked; MODEL supply is a BUILD gap, named)**

| # | node | decision it changes | on PASS | on FAIL | blocker / cost | pre-mortem |
|---|---|---|---|---|---|---|
| 1 | `P2-Q2-costnet-metalabel-regate` (new) | does M23 setup meta-labelling continue at all | shadow candidate under the 1-2 prediction mechanical soak | close the setup-metalabel line for this feature set; capacity moves to in-trade targets | build PI-20261028-V8KBRR5H-0004 | the rebuild keeps the 2026-08 data cut and the n is too small for the gate |
| 2 | `P2-desk-checkin-exit-head` (new) | is there a learnable exit/close signal on action value, not giveback | exit-head candidate composing with P1-Q8 | desk exits rest on mechanical rules | #20967 merge; trainer or runner | label leakage through the entry join; check first |
| 3 | `P2-Q4-cross-asset-features` (re-scoped) | is new information the lever for the regime head | feed P3 overlap reads | that information class is closed at 1h | build: a correlation feature block in `ml_bakeoff.py` | PIT alignment of daily ES/DXY to 1h bars |
| 4 | `RQ-20261028-4dd3-01` (queued) | AX50 forward confirmation on `eth_4h` (regime lever) | Tier-3 packet | lever stays harness-only | runner | 2 days of new bars is too few; INDETERMINATE likely |

**Feeds.** P1 -> P2: the desk labels, and the in-trade information result (path state beats entry state). P2 -> P1/P3: no head is a gate yet (none beats its prior net of cost), so nothing is proposed as Tier-3 this week. P6 -> P2: PI-...-0004 is the top build for this track.

## Programme review 2026-10-21 (lane RESEARCH-PROGRAMME-REVIEW-1021)

Population: units whose `grading.graded_at` is 2026-10-14..2026-10-21 and whose file names this programme (`programme:` or `programme_node.programme`), read from `research/queue/*.yaml` on main at 2026-10-21 ~18Z. Units with no programme field (486 of the 657 graded in the window) are counted in the research map, not here.

**Graded in the window: 7** — 1 pass, 2 fail, 4 indeterminate. ml_health-theme units with no programme field graded 58: 14 pass,
13 fail, 28 indeterminate, 3 open.

**What was learned**
- Regime gating transfers unevenly: VH95 on `ada_pullback_2h` CONFIRMED on a disjoint window (RQ-20261018-002). The line is MERGED
  on main (`ada_pullback_2h: vol_skip_above_pctl: 0.95`), though its comment still reads "HOLD for operator approval" -- field
  beats comment; deployed/observed not checked this review, while VH80 on `trend_donchian_sol_prop` FAILED its fresh window (RQ-20261018-008).
- The rich in-trade state (P2-Q3.1, RQ-20261017-003/-004/-005) read INDETERMINATE on all three families: the samples are bounded by
  one year of live ledger (e.g. 73 trend_donchian closes on BTC 1h, 57 per pullback leg). More ledger is the only fix; a
  re-run before ~2026-12 would re-measure the same n.
- Conformal abstention at 1h FAILED (RQ-20261016-65ff-25): the conformal rule had HIGHER selective error than the plain
  max-probability threshold on BTC at matched coverage, and coverage was not matched at every level. With two classes the
  Mondrian-per-class rule is close to a threshold; `conformal_abstain_eval.py` supports only `predicted_class | none`, so the
  vol-bucket refinement P2-Q1.5-fail asks for is a scorer build, not a unit.
- Learner family is second-order (RQ-20261016-1fa6-08 FAIL; ExtraTrees/MLP vs LightGBM indeterminate, RQ-20261016-001).

**Answered / unlocked / retired**
- Answered: P2-R3.c03 / c04 PASS -> Tier-3 packets (not units). P2-R3.c05 (sol_prop VH80) FAIL -> that gate stays off.
- Not authored, and why: ml_health supply is **build-bound** — every blocked ml_health unit (15) waits on a build (label
  joiner, exit-head transfer, TSFM serving, pooling parity). No runnable ml_health unit worth its compute could be written
  this review; the H1-THEME ml_health shortfall (0 of 5) is a build-queue fact for the manager, not an authoring gap.

**Next 3–4 weeks**
- P2-R5 vol-target sizing waits on IR-VOL-TARGET-SIZING-STAGE0 (verdict wrapper over `backtest_vol_target.py`).
- Re-ask P2-Q3.1 only when the ledger has grown ~50% (≈ 2026-12); file nothing earlier.

**Operator ideas folded in (IDEAS.md, manager routing 2026-10-21)**
- `P2-Q4-var-price-vector`: a multivariate linear/VAR next-bar price-vector arm as the linear baseline in the ML-F1 bake-off.
- `P2-Q4-cross-asset-features`: rolling cross-symbol correlation, basket PC1 share and point-in-time ES/DXY/gold returns as
  regime-learner features, graded on log-loss gain. It goes beyond FRONTIER-LEVER-LEADLAG's BTC->alt 5m lead-lag.

**Cross-programme feeds**
- → P1/P5: VH95 ada packet (live leg) and the failed sol_prop VH80 both belong on REGIME-PROGRAM's Tier-3 list.

## 0. Operator direction this programme is built from (2026-10-14, relayed by the manager)

1. Research is the main focus: a long-term, deep, well-researched roster per goal; no one-off queue filler.
2. The programmes are mutually supportive: **the AI trader is fed ALL test results and trade outcomes**, not only the closed real-money trades.
3. **M23 meta-labeling is REVIVED** (it should never have gone dormant) and **merges with a signals catalog**: every signal we collect and study, how it is defined, where it is used, what it feeds.
4. **The headline measure is net P&L per capital-day (R and $).**
5. Compute: the trainer is saturated (drift retrain alone is 63.7% of its service CPU, `docs/plans/KAGGLE-TRAINING-PIPELINE-DESIGN-2026-10-13.md` § 1); Kaggle offers 2× T4 and ~29 GPU-h this week; the private market dataset is published and verified in-kernel; a GitHub-runner download of it fails, so data-dependent units run as Kaggle kernels.

Standing rules that bind every unit below: edge is decided **offline, net of the full cost stack, against a rule registered before the run** (CLAUDE.md § The promotion ladder); a live or paper book never establishes edge; never retire an idea after one bad pass, retire a **line** only when its registered exhaustion condition fires (operator, 2026-09-27); "the data leaves the question open" is itself a task, not a popup (operator, 2026-09-29).

## 1. End goal and measure

**End goal (operator, 2026-07-01, restated 2026-09-28 and 2026-10-14):** an independent AI trader — one overall model that reads everything we collect (every strategy's signals, the ICT structure, regime and volatility state, funding, flow, news, macro, our own test results and trade outcomes) and decides **whether to act on a signal, how to manage the trade, and when to stand aside**, with each capability earned offline and promoted through `candidate → shadow → advisory` before it touches size.

**Headline measure: net P&L per capital-day, in R and in USD**, per book and per leg, over provenance-trustworthy closes only, net of fees, slippage and funding. Every result in this programme is read against the change it would make to that number, not against macro-F1 or AUC alone (those are feature-lift gates that route into a net-of-cost walk-forward).

- **Where the measure lives today (MEASURED 2026-10-14, `grep -rn capital.day`):** as a clause in `config/mandates.yaml` (`net_r_per_capital_day` in the tune-before-demote verdict), in `src/runtime/hold_vs_cash.py`'s reasoning, and in a handful of queue units. **No API route or brief section serves it per book.** Building it is checklist row **`HEADLINE-MEASURE-CAPITAL-DAY`** (Tier-1 read path); until it lands, the nearest served numbers are `/api/bot/performance` expectancy per book.
- **Baseline we can state honestly:** lifetime real-money expectancy −0.3231 R (n = 431, profit factor 0.68, `/api/bot/performance` all-window, 2026-09-21, before the roster cut); the latest review window 2026-10-04..10-10 had 4 priced real-money closes (+$2.10), too few to read (`docs/roadmap/milestones.yaml` G1 baseline). A per-capital-day baseline is the first observation `HEADLINE-MEASURE-CAPITAL-DAY` owes.

## 2. Where the AI trader stands (measured 2026-10-14)

| what | state | locator |
|---|---|---|
| Order-influencing ML | **3 advisory heads, all volatility-regime GBDT** (`btc-regime-15m-lgbm-fc-pcv-v2`, `sol-regime-15m-lgbm-fc-pcv-v2`, `mes-regime-5m-lgbm-v2`); they reach size only through the reductive `advisory_sizing` downsize (`advisory_policy` default `annotate`). No head predicts a trade outcome in production. | ROADMAP § build plan table (2026-10-11 read); `src/runtime/advisory_sizing.py` |
| Model-family concentration | gbdt **75 of 96** registered models; live/shadow 18 gbdt of 28. Families with 0 registered models: linear_logit, ts_foundation_model, tabular_foundation_model, rl_bandit, conformal_calibration, ensemble_stack (open items 2 / 4 / 2 / 1 / 2 / 1). 17 open plan items carry no `family:` tag. | `python3 scripts/ops/ml_plan_status.py --diversity` (this session) |
| The spine | S1 veto FAILED twice at power (RQ-20260928-002/-003); S2-exit three negatives (donchian −14.66 R OOS; INDETERMINATE SOL/XRP/ETH; XRP multi-fold FAIL); S3 proposer parked behind an S1/S2 PASS. | `docs/plans/ml-plan-items.yaml` ML-S1..S3 |
| The label wall | ~99 closed BTC real-money trades → n_eval 20 (M19 post-mortem); M23 P1's honest result: a pooled meta-head learns cross-cell base rates, not a within-cell edge; per-cell n ≈ 78. | `docs/research/M23-meta-labeling-DESIGN.md`; `RQ-20261011-17f4-02` (label census, queued) |
| **The test-result corpus nobody used as labels** | `comms/strategy_evidence/runs/*/*__trades.jsonl`: 157 ledger files, 13,070 rows; **newest ledger per leg = 54 legs, 5,063 trades** (resample sub-ledgers excluded); win rate 0.357; mean net_r 0.12 R; 4,774 rows carry a positive peak (`mfe_r`). Decision-time columns carried: `confidence` (100%), `direction`, `entry_time`, `regime_weight` and `adx_at_entry` (both on 3,137 rows; adx non-null on ~4%). | `python3 scripts/research/ledger_metalabel.py --mode census` (this lane's instrument) |
| Peak-to-exit (the exit line's raw material) | Of the 4,774 positive-peak trades, **78.7% give back more than half their peak** (median giveback_frac 1.6: the typical trade ends below where it peaked by more than its whole peak); mean oracle-peak R 1.47 vs realised 0.12 per trade. `mfe_r` is a lagged lower bound (gross_r > mfe_r on 825 of 12,141 rows), so these understate. **Live `position_telemetry` keeps one upserted row per position (peak_r, giveback_r, bars_since_peak), not a per-bar history; MAE is recorded nowhere live and emitted by no harness.** | same command; `src/runtime/position_telemetry.py`; the trade-outcome inventory behind `SIGNALS-CATALOG.md` § 6 |
| Research queue, ML slice | 629 unit files: 306 done, 256 queued, 57 blocked, 10 retired. `ml_health` open 36, `regime` open 29. **Of the `ml_health` units in state `done`, only 1 has a measured record** (verdict fail; population: theme `ml_health`, status `done`, rows under `research/results/<id>/`). The ML runner route is OBSERVED (smoke `RQ-20261011-0ac8-01` landed `measured/pass`, run 38169810099, listed in research-ops 20261012T0330Z). | `research/queue/`, `research/results/`, `comms/research/ops/` |
| Compute | Trainer: 1 OCPU, saturated (drift retrain 30.45 CPU-h/week = 63.7%); `needs_vm_data` units release only into idle windows and `RQ-20261013-1414-06` died waiting 3,601 s for the heavy lock. Runner: 4 vCPU / 16 GB / 6 h, free; `research-script-run.yml` installs only numpy/pandas/pyyaml/requests, `research-script-run-data.yml` adds lightgbm + scikit-learn + the published dataset. Kaggle: 2× T4, 30 GPU-h/week quota, internet off (weights must ride in the bundle), one kernel slot. | `scripts/research/research_compute.yaml`; the three workflows |
| Published data | `metis-market-data` (private): BTC/ETH/SOL 15m + 1h `market_features`/`market_raw` v002, MARKET only. **BTC and SOL 15m shards are withheld** (cut short, `ML-SHARD-TRUNCATED`); the 1h shards are the ones to read this week. Funding/OI columns are real only on BTC 1h, order flow only on BTC 5m, macro only on MES; elsewhere those columns are the builder's `0.0` default (dead features). | `docs/research/ml-data-classification-2026-10-13.md`; `ml/datasets/families/market_features.py` |

**The inference this programme rests on (INFERRED from the table; re-check it each weekly pass):** the only ML that has earned an order-influencing role answers *when is volatility high*; every attempt to make a model say *what to do* on price-derived inputs has failed offline, and the binding constraint has been **labels and information, not model depth**. The operator's 2026-10-14 direction changes exactly that constraint: the test-result corpus is ~50× the real-money label count, and the signals catalog says what information each model may be fed. So the programme's first job is to **turn test results into a labelled corpus that carries the signals**, and to **fix the peak-to-exit label**, before any new head is built.

## 3. Questions in dependency order

Each question names its test ladder (cheapest and most decisive first), the decision rule registered on the unit, and what a PASS unlocks or a FAIL retires. Compute class per the dispatcher's vocabulary (`research/queue/PLANNING.md` § 1b): `cpu_light`/`cpu_long` → free runner; `auto` + `published_data` → runner with the Kaggle dataset (CPU) or Kaggle GPU when `needs_gpu`; `gpu` → Kaggle (RunPod as the ledger-capped fallback); `needs_vm_data` → trainer, idle windows only.

### Q0 — Measurement: do we trust the number, the labels and the signals we are about to learn from?

Everything else reads against Q0's outputs. No model is built until the label it would learn is defined and its headroom is measured.

| rung | test | rule (registered on the unit) | unlock / retire | compute | carried by |
|---|---|---|---|---|---|
| 0.1 | Serve the headline measure per book | build, not a test | gates reading every later result | — | `HEADLINE-MEASURE-CAPITAL-DAY` (row) |
| 0.2 | Signals catalog: every signal's definition, producer, store, consumers, feed | documentation + the `signal-catalog-guard` keeps the inventory true | the meta-label feature list (Q2) and the information-class list (Q5) are read from it | — | `SIGNALS-CATALOG.md` + `signals-catalog.yaml` (this lane) |
| 0.3 | **Peak-to-exit census**: giveback distribution and the oracle-peak headroom per family on the committed ledgers | PASS if any family at n ≥ 100 has headroom ≥ 0.25 R/trade; FAIL if all < 0.10 R | PASS releases Q3.1; FAIL retires the exit-model line on this corpus | cpu_light | **`RQ-20261014-9d20-01`** |
| 0.4 | Label census per (strategy, symbol) cell vs the n ≥ 300 / n ≥ 1,000 gates, live + backtest-augmented | GO / PARK / NEEDS-BACKFILL per cell | names which cells can carry a live-label head at all | needs_vm_data | `RQ-20261011-17f4-02` (`ML-LABEL-WALL`, queued) |
| 0.5 | Shards whole: BTC/SOL 15m repaired, row-count check in dataset validation | build | un-withholds two of three symbols for every 15m unit | — | `ML-SHARD-TRUNCATED` (Tier-2 repair) |

### Q1 — Regime and volatility heads: do they separate a strategy's good trades from its bad ones, net of cost?

The regime half is the only part of the AI trader with a live role. The question is not "is macro-F1 high" but "does gating or weighting on it lift net R per capital-day for a leg". This question is already carried by **`REGIME-PROGRAM`** (deliverables 1–5) and by units queued on 2026-10-12/13/14; this programme adds nothing to the queue for it this fortnight and names what comes next.

| rung | test | rule | unlock / retire | compute | carried by |
|---|---|---|---|---|---|
| 1.1 | Trend-axis headroom per population (upper bound: drop test-block trades in cells selected on train blocks) | pass if A=0.70 pooled Δ ≥ 0.03 R/trade with p5 > 0 | a PASS is a lead for `regime_cell_walkforward.py`, never a cell flip | cpu_light | `RQ-20261012-75b2-01..15` (queued) |
| 1.2 | Hot/cold-vol tail skips per live leg | per-unit Stage-0 rule, full cost stack | Tier-3 packet via `regime-selectivity` on a PASS | cpu_light | `RQ-20261013-407c-20/21`, `RQ-20261014-f0e2-08..12` (queued) |
| 1.3 | Head quality off the trainer: drift (CV vs last-90-day holdout), HAR-RV ablation, training-window sensitivity, log-loss vs prior | per unit; a log-loss FAIL retires the conformal lever | decides whether the advisory heads are capability or regime-mix (`ML-N5`) | needs_vm_data / auto | `RQ-20261012-75b2-16..27`, `RQ-20261013-1414-01/02/04`, `RQ-20261014-65cc-09/10` |
| 1.4 | Vol-axis headroom with the ML head's label (the `--axis vol` arm of 1.1) | same bar as 1.1 | the first Tier-3 regime proposal if it separates net of cost | cpu_light + trainer labels | **gap**: needs per-symbol `labels.jsonl` from the trainer; file as a lever in W3 (see § 6) |
| 1.5 | Conformal abstention on the advisory heads vs a plain threshold at matched coverage | no selective-error gain on ≥ 2/3 heads → retire | a per-trade refusal signal | cpu_light | `RQ-20261011-9da8-03` (blocked on `FRONTIER-LEVER-CONFORMAL`) |

### Q2 — Meta-labeling over ALL strategy signals, trained on test results plus trade outcomes (M23, revived)

The secondary head: *given this strategy's own signal, act or stand aside*. Within-cell by construction (M23 P1's lesson). Fed by **test results** (the harness ledgers) first, **trade outcomes** (journal, provenance-filtered) second, pooled only after a parity check.

| rung | test | rule | unlock / retire | compute | carried by |
|---|---|---|---|---|---|
| 2.1 | **Thin-column baseline**: do the columns the ledgers already carry (confidence, direction, entry hour/day, adx, regime_weight) separate net-positive trades within a leg; does skipping the bottom scored fifth lift net R? | PASS: AUC gain ≥ 0.05 with interval > 0 AND lift ≥ 0.05 R on some leg; FAIL: every interval contains the prior | PASS → within-family confirmation + raise the emit lever; FAIL closes **only these columns** and makes the emit lever gating | cpu_light | **`RQ-20261014-9d20-02`** (disclosed: a sandbox dry run with the logit arm found no leg clearing both bars) |
| 2.2 | **Emit lever**: every harness `--emit-trades` row carries the catalog's decision-time features (ADX label, ATR percentile, vol bucket, regime cell, session hour, funding z where real, confidence components, `fc_*` where served) and `mae_r` | build; done when fresh family ledgers carry the columns non-null on ≥ 90% of rows | unblocks 2.3 and 3.3 | — | **`METALABEL-EMIT-FEATURES`** (row) |
| 2.3 | **M23 P3 on test results**: within-family take/skip head vs take-all AND vs the confidence-only control, net R and max DD in ≥ 2/3 folds, per-fold AUC ≥ 0.55 | as written on the unit | PASS → shadow-registration proposal (P4, Tier-3 note) + backtest-vs-live parity for that family; FAIL closes the test-results route for the family | cpu_light | **`RQ-20261014-9d20-04`** (blocked on 2.2) |
| 2.4 | Small-n learner for the live label: TabICL / TabPFN (research-eval) / CatBoost vs LightGBM on the meta-label dataset at n ≥ 300 | paired log-loss CI < 0 and top-quintile net R ≥ incumbent | the learner for any GO cell from Q0.4 | gpu (Kaggle) | `RQ-20261011-9da8-02` (blocked on `FRONTIER-LEVER-TABULAR` + Q0.4); off-trainer feature-lift twins `RQ-20261014-65cc-06/08` queued |
| 2.5 | Pooling test results with trade outcomes: KS on the feature marginals and the realised-R distribution per cell before any pooled fit | parity holds → pool; fails → the head learns the simulator, do not pool | the only route past the label wall that keeps the label honest | needs_vm_data | W3 unit (§ 6) |
| 2.6 | Shadow soak → advisory (P4) and a reductive-only live skip (P5) | live agreement + net-R lift; A/B PASS + operator | Tier-3, operator-gated | — | not before a 2.3 PASS |

### Q3 — Exit models fed by active-management labels (peak-to-exit)

> **MERGED 2026-10-24 (lane `ATM-AI-MERGE`, operator direction verbatim on that row):** this question is now part of ONE programme, [`01-ACTIVE-TRADE-MANAGEMENT.md`](01-ACTIVE-TRADE-MANAGEMENT.md) § "AI active trade management — the merged programme". The model ladder (A1/A2 in-trade information on the legs as traded, B1 remaining-move TP head, C1 policy over proven rule exits, D gates), the observe-only bracket advisor and the critical-path builds live there. The table below is kept as history; where it and that section disagree, that section wins. Do not author exit-model units against this section.

Three exit heads on price features failed (ML-S2). The new information is the **peak-to-exit label** (how much of the in-trade peak was given back) and, once recorded, the **per-bar in-trade trajectory**. The ATM plan (parallel lane) owns the live levers; this programme owns the labels and the models.

**Destination (amended 2026-10-14, lane `IN-TRADE-EXIT-MODEL`, operator direction verbatim on that row).** The exit line ends at an **in-trade first-passage model**: at every bar of an open trade, P(SL before TP | state now), and an exit-now rule (exit when E[R | hold] < R_now − cost) graded by net P&L per capital-day vs the fixed bracket, net of the full cost stack, out of sample. **Rung 3.1 (giveback predictable at entry) is a cheap first rung, not the destination** — even a PASS there leaves the operator's question ("if the momentum suddenly turns … are we going to hit the stop loss before the take profit?") unanswered, because that information arrives after entry. The ladder and its units live in `01-ACTIVE-TRADE-MANAGEMENT.md` § Q8 (`RQ-20261014-d6e7-01..06`); this programme owns the model rungs (8.2/8.4) and their learners. **Why ML-S2 failed and what differs:** the three heads were LightGBM on a per-trade "does holding pay" target, one leg/family at a time, ~20–120 OOS trades per fold; Q8 uses per-bar first-passage labels, a ~3,000-trade pooled corpus, a closed-form null (gambler's ruin) plus a calibrated distance-only reference so "learned where the trade is" cannot pass as information, and a linear model before any GBDT. Rung 3.3's lever is now filed: **`EXIT-PATH-EMIT-OFFLINE`** (Tier-1, offline harness `--emit-paths`, the priority) and **`EXIT-PATH-TELEMETRY-LIVE`** (Tier-2 proposal, live per-bar history). The bandit (3.4, `RQ-20261011-9da8-04`) consumes the **offline** emit.

| rung | test | rule | unlock / retire | compute | carried by |
|---|---|---|---|---|---|
| 3.1 | **Is giveback predictable at entry?** Within-leg logit on the thin columns for `giveback_frac > 0.5`, plus the lift of keeping low-giveback trades | PASS/FAIL as 2.1 | PASS → an entry-conditioned bracket is the cheap exit model (route: `exit-refinement`); FAIL → the information is in-trade: route through the telemetry lever and the bandit | cpu_light | **`RQ-20261014-9d20-03`** (requires 0.3 PASS) |
| 3.2 | Per-trade emits for the six live legs + `mfe_r` baselines per quantile (the corpus the bandit and the TP head need) | build | releases 3.4 and `TP-PREDICT-HEAD` | — | `ML-LEG-CORPUS` (row, queued) |
| 3.3 | **Per-bar in-trade history**: offline harness path emit (stop/target in force per bar, open_r, peak_r, `mae_r`, bars_since_peak, ATR/ADX) first; live `position_telemetry` history second | build | the exit model's in-trade feature set; the fixed-bracket interim is `first_passage.py` (runs now) | — | **`EXIT-PATH-EMIT-OFFLINE`** (row, Tier-1) · `EXIT-PATH-TELEMETRY-LIVE` (row, Tier-2 proposal) |
| 3.6 | **In-trade first-passage model + exit-now policy** (the destination; ATM Q8) | as registered on each unit | census → simple → rich → policy → harness-native → shadow → Tier-3 | cpu_light | **`RQ-20261014-d6e7-01..05`**, `blocked/RQ-20261014-d6e7-06` |
| 3.4 | Offline contextual bandit over the exit-ladder arms (doubly-robust OPE) vs the best fixed ladder | n ≥ 150 and policy ≤ best fixed → retire | an arm-choosing exit policy (discrete, low variance) | cpu_long | `RQ-20261011-9da8-04` (blocked on 3.2; its per-bar states come from `EXIT-PATH-EMIT-OFFLINE`, not from live telemetry) |
| 3.5 | TP-doctrine predict-head: sharper than four naive baselines, then a net-of-cost overlay | build the head only if both pass, else "B4 is enough" | the real predictive TP every bracket must carry | needs_vm_data | `RQ-20261009-900/-901` (blocked on 3.2) |

### Q4 — Model-family diversity: which families earn a place beyond GBDT?

Policy (frontier-research skill): every family-tagged unit writes its verdict to `families.<f>.history`; a family stops being fed after three consecutive FAILs; a PASS earns a candidate manifest and the net-of-cost walk-forward, never a stage change.

| family | this fortnight | rule | compute | carried by |
|---|---|---|---|---|
| linear_logit | within 0.01 macro-F1 of LightGBM on the 15m (trainer) and 1h (published) regime heads | non-inferiority ±0.01 / FAIL < −0.03 everywhere | needs_vm_data / auto | `RQ-20261013-1414-01`, `RQ-20261014-65cc-09` |
| ensemble_stack (ExtraTrees, MLP) | twins on trainer 15m and **published 1h** | same | needs_vm_data / **auto (published)** | `RQ-20261013-1414-07`, **`RQ-20261014-9d20-05`** |
| tabular_foundation_model | TabICL / TabPFN vs LightGBM at n ≈ 3k, direction, scaling to 12k | +0.01 macro-F1 on both symbols | **gpu (Kaggle)** | `RQ-20261014-65cc-06/07/08`, `RQ-20261013-1414-06` |
| conformal_calibration | log-loss vs prior first (prerequisite), then abstention | a log-loss FAIL retires the lever | needs_vm_data / auto | `RQ-20261013-1414-02`, `RQ-20261014-65cc-10`, `RQ-20261011-9da8-03` |
| ts_foundation_model | HAR-RV control for the shipped `fc_*` lift; then the bake-off; LoRA only after a zero-shot PASS; covariate-native after funding/OI datasets | per scan table | needs_vm_data → **gpu** | `RQ-20261013-1414-04`, `RQ-20261011-9da8-01`, `RQ-20261013-1414-08/09` |
| rl_bandit | exit-arm OPE | see Q3.4 | cpu_long | `RQ-20261011-9da8-04` |
| deep_sequence, ssl_representation | **dropped this fortnight** (same inputs as the closed TCN/MAE; reopen only with a new information class) | — | — | scan record |

### Q5 — New information classes: does anything beyond price change the veto / exit / proposer answer?

| class | where it is real today (measured) | first test | compute | carried by |
|---|---|---|---|---|
| Funding / open interest | BTC 1h only (`datasets-out/funding_oi/BTCUSDT`); ETH/SOL datasets not built; no live serving | serveable funding-augmented heads for ETH/SOL | needs_vm_data | `RQ-20260929-109/110` (blocked on `FUNDING-OI-DATASETS-ETH-SOL`) |
| Order flow (OFI, VPIN, imbalance) | BTC 5m capture only; no live serving | regime-head lift from the flow block (`btc-regime-5m-lgbm-flow-v1` is research_only) | needs_vm_data | `ML-PRODUCERS` M2 feasibility |
| News | live RSS score + a live veto (`src/news/`); GDELT history off-repo; the declared `news_alpha_ic.py` harness **does not exist** | NEWS-ALPHA U01..U14 | cpu_long | `RQ-20261012-5bd1-01..14` (blocked), `RQ-20261009-902` |
| Prediction markets | Kalshi/Polymarket snapshots on the trainer, 4×/day, no order path | surprise vs consensus | needs_vm_data | `RQ-20261009-903`, `RQ-20261012-904` |
| Cross-asset / lead-lag | ETH 1h xa features; `xa_*_ret_lag1` is the only lead term | multi-timeframe head agreement; BTC→alt lead-lag with placebo | cpu_light | `RQ-20261011-17f4-03`, `RQ-20261011-9da8-07` (blocked) |
| Our own signals as information (the catalog) | every strategy's ICT components are stamped on `order_packages.meta` and in `signal_audit.jsonl`; killzone and bias columns are **always NULL** | Q2.2 makes them label-joinable | — | `METALABEL-EMIT-FEATURES` |

### Q6 — Serve parity and producers (build track, named for completeness)

A head is only as good as the features it is served with. `ML-PARITY-HARNESS` (P0), `ML-PRODUCER-FUNDING` (P1), `ML-PRODUCERS` (P2) and the value-equal parity audit `RQ-20261011-17f4-01` are the carriers; the known gap is that the yz heads froze `yang_zhang_vol` while serving uses close-to-close vol (`src/runtime/regime/vol_detector.py` docstring). No research unit here; a parity FAIL reprioritises Q6 above everything (ROADMAP build plan).

### Q7 — The proposer (S3) and Q8 — the portfolio layer (M18)

Both stay parked. S3 unparks only on a PASS from Q2.3, Q3.4/3.5 or Q5 (ML-S3's registered gate). M18 reopens only after the arbitration soak is observed writing again (`E50`). Neither gets a unit in the next four weeks.

## 4. How the pieces feed each other (the programme's data flow)

```
 harness --emit-trades (test results)  ──┐                      journal trades + order_packages.meta
 + the catalog's decision-time columns    │  METALABEL-EMIT-FEATURES   (trade outcomes, provenance-filtered)
   (Q2.2)                                 ▼                                      │
                       comms/strategy_evidence/runs/<run>/<leg>__trades.jsonl    │  parity check (Q2.5)
                                          │                                      ▼
            ledger_metalabel.py ──► Q0.3 census ─► Q3.1 giveback ─► exit models (Q3)      pooled corpus
                        └─────────► Q2.1 thin ─► Q2.3 within-family take/skip ─► shadow (P4) ─► advisory ─► reductive skip (P5, Tier-3)
                                                                                        ▲
 published market shards ──► regime / vol heads (Q1), family bake-offs (Q4) ────────────┘ (features served at signal time, Q6)
                                          │
                                          ▼
                 every verdict ─► research/results (E5) ─► research-ops applies the rule ─► families.history / plan items / next unit
                                          │
                                          ▼
                     read against: net P&L per capital-day per book (HEADLINE-MEASURE-CAPITAL-DAY)
```

## 5. Compute placement (where each run computes, and why)

| run shape | class | backend | why |
|---|---|---|---|
| Reads committed repo files only (ledgers, panels, configs) | `cpu_light` / `cpu_long` | GitHub runner (`research-script-run.yml`) | free; numpy/pandas only — a logit arm, never lightgbm |
| Reads BTC/ETH/SOL 1h (and whole 15m) market shards, CPU learners | `auto` + `routing.published_data` | runner with the Kaggle dataset (`research-script-run-data.yml`) | installs lightgbm + scikit-learn; the trainer is not in the path |
| Needs a GPU (TabICL/TabPFN, TSFM forecasters, LoRA) | `gpu` / `gpu_preferred` | Kaggle 2× T4 (`research-script-run-kaggle.yml`), RunPod only as the ledger-capped fallback | the ~29 GPU-h/week otherwise expire; internet is off, so weights ride in the bundle or the arm reads `unavailable` |
| Reads OURS data (journal, setup_labels, conviction_meta) or trainer-only datasets (setup_candidates, funding/OI, flow) | `needs_vm_data` | trainer, idle windows only | the data never leaves the VM (`ml-data-classification-2026-10-13.md`); expect `deferred` while saturated |
| Nightly training, drift retrain, shadow fleet | not research units | trainer | the registry is trainer-local; moving the cycle is the Kaggle design doc's phases 2–4 (Tier-2) |

Rule of thumb this fortnight: **if a unit can be asked on the committed ledgers or the published 1h shards, it is asked there**; only Q0.4, Q2.4/2.5 and Q5 need the trainer, and they wait for its idle windows rather than widen them.

## 6. Backlog — 3 to 4 weeks (W1 = 2026-10-14..20)

Status key: **queued** (dispatchable now) · **blocked** (named blocker) · **row** (a build). Everything marked *new* was landed by this lane; everything else already existed and is named so the backlog is the whole picture, not only this lane's additions.

### Update 2026-10-16 (lane P2-AI-REGIME-BACKLOG-1016) — read this before the W1–W4 tables

The tables below are the 2026-10-14 plan; several "queued" items have since closed (manager audit `docs/research/programmes/reviews/2026-10-16/02-AI-REGIME-DATA.md`). The live tree is now machine-read: `research/programmes/02-ai-trader.yaml` (AI trader), `research/programmes/02-ai-trader.yaml (regime section)` (the regime half, L-REGIME) and `research/programmes/06-data-infra.yaml` (programme 06). Added on 2026-10-16, held for a human merge:

| what | units | state |
|---|---|---|
| Regime: fresh-window confirmations of the four unconfirmed lever PASSes + the sol VH90 transfer to the prop leg | `RQ-20261016-65ff-01..05` | runnable |
| Regime: per-leg good-vs-bad trade conditions on the real-money pullback legs (hot / cold vol; 07 grades ada's declared cold skip). 11 donchian-leg skip units were dropped before merge (IDEA-REVIEW-1016 s11: skips are predicted to fail on trend legs and already read so in-repo); the trend-leg question is vol-target SIZING, row `IR-VOL-TARGET-SIZING-STAGE0`, node `P2-R5-voltarget-sizing` | `RQ-20261016-65ff-06..08` | runnable |
| Regime: classifier comparison on trade separation (ML vol head vs HMM vs ATR control); the alpaca_live equity legs | `blocked/RQ-20261016-65ff-28`, `-29` | blocked on `REGIME-VOL-LABELS-EXPORT`, `REGIME-EQUITY-LEG-FETCH` |
| Q6 off-VM training parity, HMM + RegimeClassifier classes (regression class: OURS data, stays on the trainer) | `RQ-20261016-65ff-20..23` | runnable (21/23 gated on 20/22) |
| Q1.3 drift: 1h twin on published data; drift-flag artifact question for the 9 flagged heads | `RQ-20261016-65ff-24`; `blocked/-27` | runnable; blocked on `ML-DRIFT-SPLIT-INSTRUMENT` |
| Q4 CatBoost confirmation out of time and on SOL (from `de02-01` PASS) | `RQ-20261016-65ff-30` | runnable |
| Q1.5 conformal at 1h (scorer only); Q2.5 pooling parity | `blocked/RQ-20261016-65ff-25`, `-26` | blocked on `FRONTIER-LEVER-CONFORMAL`, `POOLING-PARITY-INSTRUMENT` |
| Q3.1 rich in-trade state per class (refines `d6e7-04` INDETERMINATE; `d6e7-05` retired as moot) | nodes `P2-Q3.1-fail`, `-b-pullback`, `-c-scalp` | emitted by the next replenish |

Corrections to the tables below: `RQ-20261011-17f4-02` (Q0.4) is **not** queued — it exists only on held PR #17556. The `75b2`/`1414` units listed as queued are done. `P2-Q2.1-fail`: no cheaper step than `METALABEL-EMIT-FEATURES` exists (9d20-02 already covered the legs whose emits carry `adx_at_entry`).

### W1 (Oct 14–20) — fix the labels, measure the headroom, run what the free compute can run

| # | item | kind | compute | status |
|---|---|---|---|---|
| 1 | `RQ-20261014-9d20-01` peak-to-exit census *(new)* | Q0.3 | cpu_light | queued |
| 1b | `RQ-20261014-d6e7-01` first-passage census, then `d6e7-02/04` (state models) on its PASS *(new, lane IN-TRADE-EXIT-MODEL)* | Q3.6 | cpu_light | queued |
| 2 | `RQ-20261014-9d20-02` meta-label thin-column baseline *(new)* | Q2.1 | cpu_light | queued |
| 3 | `RQ-20261014-9d20-05` ExtraTrees/MLP vs LightGBM on published 1h *(new)* | Q4 | auto (published) | queued |
| 4 | `RQ-20261014-65cc-06/07/08` TabICL/TabPFN on Kaggle GPU; `65cc-09/10` logit + log-loss at 1h | Q4 / Q1.3 | gpu / auto | queued (other lane, 2026-10-14) |
| 5 | `RQ-20261012-75b2-01..15` trend-axis headroom; `RQ-20261013-407c-20/21`, `RQ-20261014-f0e2-08..12` vol-tail skips | Q1.1 / Q1.2 | cpu_light | queued |
| 6 | `METALABEL-EMIT-FEATURES` *(new row)*: widen the emits; one evidence run per family | Q2.2 | — | row, queued |
| 7 | `HEADLINE-MEASURE-CAPITAL-DAY` *(new row)* | Q0.1 | — | row, queued |
| 8 | `ML-SHARD-TRUNCATED` repair (Tier-2) | Q0.5 | — | row, queued |

### W2 (Oct 21–27) — read W1, release the dependents

| # | item | kind | compute | status |
|---|---|---|---|---|
| 9 | `RQ-20261014-9d20-03` giveback predictable at entry *(new)* | Q3.1 | cpu_light | queued; fires on a 9d20-01 PASS |
| 10 | `RQ-20261014-9d20-04` M23 P3 within-family head on the widened emits *(new)* | Q2.3 | cpu_light | blocked on #6 |
| 11 | `RQ-20261011-17f4-02` label census per cell | Q0.4 | needs_vm_data | queued (trainer window) |
| 12 | `RQ-20261013-1414-01/02/04/05/07` trainer twins (linear, log-loss, HAR-RV control, MES small-n, ExtraTrees/MLP) | Q1.3 / Q4 | needs_vm_data | queued; expect `deferred` while saturated — the published twins (#3, #4) are the ones that will land |
| 13 | `RQ-20261012-75b2-16..27`, `RQ-20261013-a793-01..03` regime-head drift / HAR-RV ablation / window sensitivity | Q1.3 | runner | queued |
| 14 | Research-ops reads every W1 record against its rule; `families.history` written; this document's § 2 re-measured | loop | — | recurring (research-ops 4×/day, ml-review Sunday) |

### W3 (Oct 28–Nov 3) — the first heads, and the in-trade label

| # | item | kind | compute |
|---|---|---|---|
| 15 | Per-bar in-trade path: **`EXIT-PATH-EMIT-OFFLINE`** (filed 2026-10-14, Tier-1, pulled forward to W1–W2 — it does not wait for live data) and `EXIT-PATH-TELEMETRY-LIVE` (Tier-2 proposal); `EXIT-INTRADE-HISTORY` is not filed — these two rows replace it | Q3.3 | — |
| 16 | Vol-axis headroom with the ML head's labels (`regime_impact_scoping.py --axis vol`): lever to export per-symbol `labels.jsonl` from the trainer to the repo (market-only, publishable) | Q1.4 | cpu_light after the lever |
| 17 | Pooling parity: KS on feature marginals and realised-R per cell, test results vs trade outcomes (unit, trainer) | Q2.5 | needs_vm_data |
| 18 | `RQ-20261011-9da8-02` tabular bake-off on the live meta-label dataset, if Q0.4 returns a GO cell and the trainer venv has the arms (`FRONTIER-LEVER-TABULAR`) | Q2.4 | gpu |
| 19 | `RQ-20261011-9da8-01` TSFM bake-off with the HAR-RV control, on Kaggle GPU with weights bundled (`FRONTIER-LEVER-TSFM`) | Q4 | gpu |
| 20 | Conformal abstention `RQ-20261011-9da8-03` once `RQ-20261013-1414-02` / `65cc-10` say the heads beat the prior on log-loss | Q1.5 | cpu_light |

### W4 (Nov 4–10) — decide, write back, re-plan

| # | item | kind |
|---|---|---|
| 21 | Q2.3 result → shadow-registration proposal for the passing family (Tier-3 note) or the family's test-results route closed with numbers | Q2.6 |
| 22 | Q3.1 + #15 → the first exit-model unit on in-trade features (bandit `RQ-20261011-9da8-04` if `ML-LEG-CORPUS` is done; else an entry-conditioned bracket via `exit-refinement`) | Q3.4/3.5 |
| 23 | Weekly roadmap pass: M23 status `backlog → active`, L-REGIME/M25 `where` re-measured, this document's § 2 and § 6 rewritten from the field | loop |
| 24 | Frontier scan #3 reads `families.history` and this backlog first | Q4 |

**What would change this backlog:** an advisory head failing the value-equal parity audit (Q6 first); Q0.3 FAIL (retire the exit-model line on this corpus; W3 #15 becomes the ATM plan's alone); Q2.1 PASS (skip straight to the within-family confirmation; #6 drops from gating to widening); Q0.4 returning GO for any cell (author the per-cell live-label head unit immediately).

## 7. What this programme does not do, and what it did not verify

- It changes no config, roster, sizing, stage or lever; every Tier-2/3 step above is a *proposal* that routes through the existing packets and the operator's recorded approval.
- Nothing here has run yet except the authoring reads disclosed on the units; **the committed records are the verdicts, not those reads.**
- The parallel lane's RESEARCH-MAP and ATM plan were not on `main` when this landed; § 3 Q3 and § 6 W3 #15 are written to defer to them and must be reconciled by the manager.
- Kaggle session limits other than the GPU quota are unverified (Kaggle design doc § 9); a kernel that cannot fetch weights grades INDETERMINATE, not FAIL.
- The headline measure is not yet served; until `HEADLINE-MEASURE-CAPITAL-DAY` lands, "read against net P&L per capital-day" is a commitment, not a practice.
