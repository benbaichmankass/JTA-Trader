# ML pipeline design: a standing assembly line from the money roster backward (2026-10-29)

> **Doc status:** `unknown` · category `architecture` · last verified `2026-10-29` (code, config and committed artifacts read at `main@9341857a`; nobody but this lane has verified it) · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Checklist row:** [`ML-PIPELINE-DESIGN`](../claude/work/checklist/ML-PIPELINE-DESIGN.json) · roadmap `L-ML-LIVE` · track **MODEL** · lane dispatched by Manager Session 2026-10-29c (session_01AFoLuKwNMzjtn2CH2kVd86) · Tier 1 (design, skills, a CI guard, a `proposed:` mandate).
> **Operator rule this answers (verbatim, `docs/claude/work/checklist/_header.json` `priorities.system_first`):** *"if we've designed the wrong system to continuously build and improve those features, then that has to take top priority, because nothing else we're going to do is going to matter"*.
> **What it authorises:** nothing. It names the stations, their owners and gaps, files the build rows, adds an intake rule and a guard, and **proposes** (never grants) a mandate for stations 5–6. Every stage change past `shadow` stays Tier 3.

---

## 0. The answer in eight lines

1. **The ML system was built to improve the models it had, not to put a model on the decisions that carry money.** MEASURED: 0 of 75 manifests in `ml/configs/` name any of the 7 money legs (the probe finds `trend_donchian` in `setup-candidates-metalabel-p2pool-v1.yaml`, so it can find a positive); of the 54 ML units minted 2026-10-22..28 (ids by date, `research/queue/` + `blocked/`, detector of § 4), 51 are `theme: ml_health` and 1 by title targets the money legs as traded (`RQ-20261024-09a6-03`).
2. **Redesign: one assembly line, six stations, run for every money leg first and then every demo-floor leg** (practice R2 [S18]). The line starts from the roster, not from a model.
3. **The data the line needs mostly exists.** Config-exact, cost-net trade corpora exist for 6 of the 7 money legs (§ 2, S1). What is missing is a *standing* producer, a combinatorial CV, a gate with a risk term, the serve features, a canary policy and any CUSUM monitor.
4. **The gate is the operator's objective, not a new rule:** net P&L first (RULE-ML-OVERLAY-NONINFERIOR-V1, owned by `ML-REAL-MONEY-OVERLAY`), risk second (RULE-AM-RISK-ADJUSTED-V1, owned by `AM-RISK-ADJUSTED-RULE`), and both against a same-rate random arm (M6). No third rule is invented here.
5. **`ML-REAL-MONEY-OVERLAY` is instance #1.** It walks stations 1–5 by hand this week; the build rows of § 3 turn each hand step into a station that runs for every leg and every retrain.
6. **Intake rule (binding from this PR):** an ML unit is admitted only if it names its consumer and the live or demo decision it would change (`ml_consumer:`, `research/queue/PLANNING.md` § 1c). Guard `research-queue-ml-consumer-guard` refuses a new unit without it.
7. **Proposed, not granted:** `MD-ML-OVERLAY-CANARY` in `config/mandates.yaml` `proposed:`, to run stations 5–6 under the ladder once the first overlay passes. Only the operator moves it to `mandates:`.
8. **Six build rows**, ranked (§ 3). The S4 gap is already owned by `ML-SERVE-SETUP-FEATURES`, `ML-PROMO-PARITY` and `ML-CONSUMER-LIVENESS`; this plan does not duplicate them.

---

## 1. The line

### 1.1 Which legs, in what order

Re-parse `config/accounts.yaml` (`python3 scripts/ops/strategy_status.py`); never quote the counts from here. At `main@9341857a` the line's first pass is:

- **Money legs** (real money, its mirror, or prop; `production` status or on an `account_class: prop` roster): `ada_pullback_2h`, `iaum_pullback_1d`, `trend_donchian_eth_4h`, `trend_donchian_sol_prop`, `trend_donchian_xrp_4h`, `xrp_pullback_2h` (all `production`), and `trend_donchian_eth_prop` (`testing`, but on `breakout_2`, `tradeify_1` and `velotrade_1`).
- **Then the demo floor**: every other `testing` leg on `bybit_1` / `alpaca_paper` / `ib_paper` (OPERATING-PLAN § 2 "Stage 1 is the DEMO FLOOR"). A demo-floor overlay is the cheap rehearsal of stations 4–6 for a leg that may be promoted later.

**Pooled by family.** A leg's own corpus is a few hundred trades (§ 2, S1), so a per-leg model is under-powered. Each station runs per **family** (Donchian trend 1h/4h; 2h pullback; 1d ETF pullback) with `leg` / `symbol` as features, and every gate reads **per leg as well as pooled**: a pooled pass does not license a leg whose own slice fails (T2: evaluate per leg, never pooled only).

### 1.2 The stations

| # | station | what it produces | owner | cadence | quality metric, measured on the station alone | practice |
|---|---|---|---|---|---|---|
| **S1** | **Dataset** | per leg: config-exact harness trades + per-bar paths from the leg's own Stage-0 corpus; label = net R of the exit **actually traded** (fee + slippage + funding); pooled per family | a weekly recurring research unit per family, expanded over the roster by `queue_replenish.py` (research-ops routine), run on the free runner; the trainer ingests the landed artifact | weekly, and on any change to the leg's `config/strategies.yaml` block | **coverage** = money legs with a corpus ≤ 7 days old ÷ money legs; **fidelity** = harness `params` hash equals the leg's config hash; **cost completeness** = share of trades with fee, slippage and funding all non-null | M1 [S50, S38]; [LdP-2018-AFML-ch3] § 3.4 triple-barrier |
| **S2** | **Validation** | combinatorial purged CV with embargo, grouped by trade; every configuration tried counted per dataset | trainer VM (`ict-trainer.service` cycle; `ml/experiments/splitters.py`) | each training run | **leakage test**: a planted look-ahead feature must FAIL validation (self-test); **folds achieved** vs declared; **n_trials recorded** (never defaulted to 1) | M2, M4, M5 [S45–S50]; [LdP-2018-AFML-ch7/12]; [BBLZ-2017-PBO]; [BLdP-2014-DSR] |
| **S3** | **Gate** | a verdict under the two registered rules, per leg and pooled, vs take-all, take-none, the champion and a **same-rate random arm** (drawn, ≥ 1,000 draws) | trainer `gate-check` (`ml/promotion/`) computes; `research-ops` § D applies the registered rule verbatim | each candidate | rule **registered before the run** (timestamp precedes the run id); **false-pass rate** on a permuted-label null dataset ≤ the rule's alpha | M6, M10 [S1, S20, S42]; T1; [Kim-2025-arXiv] (count-matched random baseline) |
| **S4** | **Shadow** | the candidate scored on the live serve path for every package of the leg, logged beside the order it would change | live trader (`_emit_shadow_preds` → `runtime_logs/shadow_predictions.jsonl`); graded weekly by `/ml-review` C-checks (`ml/promotion/live_parity.py`) | every package; graded weekly | **parity**: every trained feature present, non-default and equal to the training value on identical bars, score re-computes within tolerance; **coverage** = scored packages ÷ the leg's packages | [Zinkevich-RulesOfML] #29, #37; [Breck-2017-MLTestScore] training/serving skew; [Uber-2025-DeploySafety] shadow |
| **S5** | **Canary** | reduce-only influence: `advisory_policy: downsize` with `size_floor` ≥ 0.5 (never zero, never up), live and mirror together | the manager, through the Tier-3 path or the proposed `MD-ML-OVERLAY-CANARY`; applied by `src/runtime/advisory_sizing.py` | per package once armed | **applied-as-intended**: every canary decision in `advisory_decisions.jsonl`, live == mirror factor, factor ≥ floor; **mechanics**: 1–2 clean trades (the soak is mechanical, OPERATING-PLAN § 2) | [Breck-2017-MLTestScore] Infra 6 canary; [RTS6-2017/589] Art. 8 controlled deployment; [FRB-SR26-2-2026] limits on use before full validation |
| **S6** | **Demote and retrain** | a CUSUM on the overlay's realized decision value vs its Stage-0 expectation, at a declared false-alarm rate; a trip demotes to `shadow` (de-risking) and opens a cause-naming unit; a weekly retrain re-gates the challenger against the champion | daily step after the trainer cycle, surfaced on `/api/bot/ml/status`; retrain = trainer timer; demotion = manager under the ladder | daily monitor; weekly retrain | **ARL0** (false alarms per year) measured on Stage-0 replay at the declared rate; **detection delay** on a planted decay; **staleness** = days since the champion's last re-gate | M10, R4 [S43]; [PYS-2003-JPM] CUSUM on manager alpha; [Page-1954]; [Gama-2014-CSUR]; [Google-MLOps-CD] |

**Champion/challenger** is S3 + S6 run on every retrain: the retrained model is the challenger, the deployed one the champion, and the challenger replaces it only by clearing S3 against it on the same rows ([Uber-2025-DeploySafety]; [Google-MLOps-CD]). **NO SOURCE FOUND** for a trading firm's published champion/challenger procedure; the structure is taken from the engineering and supervisory sources above.

### 1.3 The gate (S3): the objective, stated once elsewhere

The objective is lexicographic: **net P&L first, risk second, and a large risk cut for a small R cost is preferred** (operator 2026-10-29, verbatim on row `AM-RISK-ADJUSTED-RULE`). The line uses two rules and invents none:

- **RULE-ML-OVERLAY-NONINFERIOR-V1**: the overlay is non-inferior to take-all on net R per opportunity, net of the full cost stack. Its text and margin are registered by `ML-REAL-MONEY-OVERLAY`. MEASURED: it is on no branch at the time of writing (`git grep` over `origin/main` and the 40 most recent `origin/claude/*` branches, 2026-10-29 ~07Z). Until it lands, S3 has no rule to apply and no overlay passes.
- **RULE-AM-RISK-ADJUSTED-V1**: gives up at most a pre-stated R per trade while cutting book max drawdown or worst-5% outcome materially, across folds, vs a random-intervention control (row `AM-RISK-ADJUSTED-RULE`, operator popup 2026-10-29 ~06:25Z). An overlay that skips or downsizes entries is graded under it as the risk leg of the objective.
- **Both against the same-rate random arm** (M6): a random skip/downsize at the overlay's own rate, drawn ≥ 1,000 times. MEASURED: today's `ml/promotion/cost_gate.py` computes `matched_random` as its expectation (`take_rate × mean R`), which prices the mean but not the risk leg; the risk comparison needs the draws.

---

## 2. The gap per station (MEASURED from code, config and committed artifacts at `main@9341857a`)

| # | exists today | gap | owning row |
|---|---|---|---|
| **S1** | Per-leg corpora from `RQ-20261024-09a6-01` run 40143286436 (`comms/research/RQ-20261024-09a6-01/40143286436/first_passage_paths_4b_c03_b/`): trades `trend_donchian_eth_prop` 1,085, `trend_donchian_sol_prop` 403, `ada_pullback_2h` 402, `xrp_pullback_2h` 394, `trend_donchian_eth_4h` 275, `trend_donchian_xrp_4h` 68 (`wc -l *__trades.jsonl`); each trade carries `net_r` with `cost_fee_r`, `cost_slippage_r`, `cost_funding_r`. | (a) **one-off run artifact, not a standing producer**; (b) **`iaum_pullback_1d` has no corpus** (equity harness); (c) **no ML dataset family reads these emits**: 0 of 75 manifests name a money leg, and the setup meta-label family trains on a 3-strategy harness roster at BTC/ETH/SOL; (d) `trend_donchian_eth_4h__bt.json` and `trend_donchian_xrp_4h__bt.json` read `"timeframe": "1h"`, but 275 of 275 and 68 of 68 entries fall on 4-hour boundaries (on 1h bars about a quarter would), so INFERRED: the field is mislabelled, the bars are 4h. The label still needs fixing before a fidelity metric can read it. | `ML-LINE-S1-CORPUS` (extends `ML-LEG-CORPUS`, state `landed_unproven`) |
| **S2** | `split_purged_walk_forward` with `purge_and_embargo_indices` (`ml/experiments/splitters.py`); `oos_edge.py` scores on purged WF-CV folds; `cost_gate.py` computes PSR and DSR. | (a) **no combinatorial purged CV**: 0 hits for `cpcv` / `combinatorial` in `ml/`; (b) **`n_trials` defaults to 1** (`CostGateResult.n_trials: int = 1`) and nothing counts configurations per dataset, so the DSR is not deflated in practice (the p2pool head's registry row reads `n_trials 1`, per `docs/plans/ml-live-promotion-plan-2026-10-29.md` § 1); (c) no trade-grouping for multi-row trades in the splitter API. | `ML-LINE-S2-CPCV` |
| **S3** | `ml/promotion/cost_gate.py`: PASS iff the candidate's net R per opportunity is **strictly greater** than take-all, take-none, matched-random (expectation) and the champion; refuses non-cost-net rows (`eval_not_cost_net`). | (a) **superiority, not non-inferiority**: a conservative overlay that matches take-all and cuts drawdown fails today; (b) **no risk term** (max drawdown, worst-5%); (c) **pooled only**, no per-leg read; (d) matched-random is an expectation, not draws; (e) RULE-ML-OVERLAY-NONINFERIOR-V1 not yet registered (§ 1.3). | `ML-LINE-S3-GATE` (after `ML-REAL-MONEY-OVERLAY` registers its rule) |
| **S4** | `_emit_shadow_preds` is called by the builders of all 7 money legs (`src/runtime/strategy_signal_builders.py`: the Donchian variants through `_trend_donchian_variant_builder` at L2099, the 2h pullbacks through `_htf_pullback_variant_builder` at L5997, `iaum_pullback_1d` at L4431); `ml/promotion/live_parity.py` checks serving fidelity and dead features. | the advisory serve row is **6 fields** (`_feature_row_from_pkg`: strategy, symbol, direction, confidence, setup_type, killzone), so a meta-label head's candle features are absent at serve time. | already owned: `ML-SERVE-SETUP-FEATURES` (in flight), `ML-PROMO-PARITY` (queued), `ML-CONSUMER-LIVENESS` (queued). No new row. |
| **S5** | `src/runtime/advisory_sizing.py` + `advisory_influence.py`: reductive per-package factor, applied to every account carrying the package (Stage-2 equality holds), `size_floor` default 0.5, stage-gated on registry `advisory`. | (a) **0 strategies carry `advisory_policy`** in `config/` (`git grep -c advisory_policy config/` is empty; the key is read in `src/`), so every leg is `annotate`; (b) no mandate covers arming one; (c) the scope guard keyed on roster membership is still queued. | `ML-LINE-S5-CANARY` (Tier 3) + `ML-ADVISORY-SCOPE-GUARD` (queued) + the proposed `MD-ML-OVERLAY-CANARY` |
| **S6** | `ml/promotion/readiness_report.py` proposes demotions from drift and attribution evidence; the trainer timer runs daily. | (a) **no CUSUM monitor anywhere** in `src/` or `scripts/` (`git grep -il cusum` hits only label event-sampling in `ml/datasets` and three `scripts/ml/m23_*` label scripts); (b) `LIVE-DECAY-MONITOR` (queued) covers legs, not models; (c) the setup-candidates datasets are never rebuilt by the daily cycle (pipeline `PI-20261028-V8KBRR5H-0004`), so "scheduled retraining" does not reach the meta-label family. | `ML-LINE-S6-CUSUM-RETRAIN` (+ `ML-TRAINER-TIMER-PROOF`, `LIVE-DECAY-MONITOR`) |
| **line** | `scripts/ops/ml_plan_status.py` (plan items), `ml_learning_ledger.py` **absent** (row `ML-LEARNING-LEDGER`). | nothing reports **leg × station** state with each station's own metric, so a broken station is invisible behind a green model metric (R2). | `ML-LINE-STATUS` (shares output with `ML-LEARNING-LEDGER`) |

---

## 3. Build rows (ranked; filed with `scripts/ops/checklist.py add`)

Rank 1 is `ML-REAL-MONEY-OVERLAY` (in flight) and this row. The rows below generalise each of its hand steps; none rebuilds it.

| rank | row | tier | closes when (observation) |
|---|---|---|---|
| 2 | `ML-LINE-S1-CORPUS` | 1 | a weekly unit per family lands corpora for all 7 money legs (incl. `iaum_pullback_1d`) ≤ 7 days old, `bt.json` timeframe equal to the leg's config, and an `ml/datasets` family that reads them pooled by family with `leg` as a feature |
| 3 | `ML-LINE-S3-GATE` | 1 | `cost_gate.py` (or a sibling) grades a candidate under RULE-ML-OVERLAY-NONINFERIOR-V1 + RULE-AM-RISK-ADJUSTED-V1 per leg and pooled, with drawn same-rate random arms, and its self-test shows a permuted-label null passing at ≤ alpha |
| 4 | `ML-LINE-S2-CPCV` | 1 | a CPCV splitter with purge, embargo and trade grouping, whose planted-leak self-test fails as it should, and an automatic per-dataset trial counter feeding `n_trials` |
| 5 | `ML-LINE-S6-CUSUM-RETRAIN` | 1 (monitor) / ladder (demotion) | a daily CUSUM per advisory overlay with ARL0 measured on Stage-0 replay, its trip writing a pipeline item and a demotion proposal; the line's datasets rebuilt and re-gated weekly as challenger vs champion |
| 6 | `ML-LINE-S5-CANARY` | 3 | the first overlay that passes S3 runs with `advisory_policy: downsize`, `size_floor` ≥ 0.5 on its legs (live and mirror together), with 1–2 clean downsized trades observed |
| 7 | `ML-LINE-STATUS` | 1 | `scripts/ops/ml_line_status.py` prints leg × station with each station's metric and read-state, wired into `/ml-review` CHECKS |

S6 is ranked before S5 on purpose: a canary does not start without the alarm that would demote it (canonical § "A soak must carry its own alarm").

---

## 4. The intake rule

Written into `research/queue/PLANNING.md` § 1c (the binding authoring contract) and pointed at from `research-ops` § E, `frontier-research` Step 5, `programme-review` Step 3 and `ml-review` (next experiments).

- An ML unit carries `ml_consumer: {consumer, decision, legs, book?}`. `consumer` is an existing repo path or the checklist row that builds it; `legs` must be on a `mode: live` real-money, prop or demo-floor roster.
- Detector (the guard's): an `ml_consumer` / `ml_bakeoff` block, `theme: ml_health`, or an ML term in the title or question. Tested on the 1,503 units at `main@9341857a`: 161 are ML units, all grandfathered. On the 1,026 units in `research/queue/` with ids dated 2026-10-10..29 (glob `RQ-202610[12]*`) it flags 125: all 122 `theme: ml_health` units, 1 `infra`, 1 `live_strategy` (a quantile head) and 1 `regime` (a foundation-model bake-off for the vol-regime head). It excludes the "head-to-head" prop comparisons, the prop-fit "sizing model" units and the regime *classifier* rule studies that a bare `model|head|classifier` match hit (the first two are self-test cases).
- Guard: `scripts/ci/check_research_queue_ml_consumer.py`, `--self-test` (32 planted cases) plus `--base` grading in `run_guards.py` (`research-queue-ml-consumer-guard`). New units graded, old units counted, `base_unresolved` refuses.
- Generated units: `queue_replenish.py` passes a template's `ml_consumer:` through; programme nodes already pass any `unit:` field through.

---

## 5. Automating stations 5–6 (a proposal)

`config/mandates.yaml` `proposed:` gains `MD-ML-OVERLAY-CANARY`. It would let the manager arm the reduce-only canary (S5) on a leg whose overlay cleared S3 under both registered rules, and demote it to `shadow` on a CUSUM trip (S6), each followed by an immediate operator notification. It is `derisk_only` in direction (it can only shrink size), carries `blocked_until` = the first overlay passing and the operator's Tier-3 approval of that first canary, and never touches `mode:`, a roster, a risk cap or an SL/TP. **A session may propose a mandate; only the operator grants one** (CLAUDE.md § The daily sync).

---

## 6. Sources

Tags are this plan's; principle ids and `[S#]` tags are from `docs/reference/trading-and-model-practice-principles.md`. FETCHED = the page was read; SNIPPET = search result only; META = bibliographic record verified, full text not read.

| tag | source | state | used for |
|---|---|---|---|
| [LdP-2018-AFML-ch3] | López de Prado, *Advances in Financial Machine Learning*, Wiley 2018, ch. 3 (§ 3.4 triple-barrier, § 3.6–3.7 meta-labeling), ch. 10 § 10.3 bet sizing. TOC: https://catalogimages.wiley.com/images/db/pdf/9781119482086.toc.pdf | FETCHED (TOC only) | S1, meta-label overlay shape |
| [LdP-2018-AFML-ch7/12] | same book, § 7.4.1 purging, § 7.4.2 embargo, § 12.4–12.5 CPCV, § 14.7.3 deflated Sharpe | FETCHED (TOC only) | S2 |
| [Joubert-2022-JFDS] | Joubert, "Meta-Labeling: Theory and Framework", *J. Financial Data Science* 4(3), 2022, doi:10.3905/jfds.2022.1.098 | META | S1/S3 meta-label as a secondary take/size model |
| [TBJ-2023-JFDS] | Thumm, Barucca, Joubert, "Ensemble Meta-Labeling", *JFDS* 5(1):10–26, doi:10.3905/jfds.2022.1.114 | SNIPPET + META | pooled-by-family design (ensembles help most across regimes) |
| [BBLZ-2017-PBO] | Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting", *J. Computational Finance* 20(4), doi:10.21314/jcf.2016.322 | SNIPPET + META | S2 trial counting |
| [BLdP-2014-DSR] | Bailey, López de Prado, "The Deflated Sharpe Ratio", *J. Portfolio Management* 40(5):94–107, doi:10.3905/jpm.2014.40.5.094 | SNIPPET + META | S2/S3 deflation |
| [FRB-SR26-2-2026] | Federal Reserve SR 26-2 (with FDIC, OCC), *Revised Guidance on Model Risk Management*, 2026-04-17, https://www.federalreserve.gov/supervisionreg/srletters/SR2602.pdf — supersedes SR 11-7 | FETCHED | effective challenge, outcomes analysis, ongoing monitoring, model inventory, limits on use before validation (S5, S6, line status) |
| [OCC-2026-13] | OCC Bulletin 2026-13 (rescinds OCC 2011-12), https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html | SNIPPET | that SR 11-7 / OCC 2011-12 are no longer current |
| [PRA-SS1/23] | Bank of England PRA SS1/23, *Model risk management principles for banks* (revised version effective 2026-04-23), https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss | FETCHED (headings only) | five principles incl. independent validation and model risk mitigants |
| [Breck-2017-MLTestScore] | Breck et al., "The ML Test Score", IEEE Big Data 2017, https://research.google/pubs/pub46555/ | FETCHED | canary (Infra 6), training/serving skew, staleness (S4–S6) |
| [Zinkevich-RulesOfML] | Google, "Rules of Machine Learning", https://developers.google.com/machine-learning/guides/rules-of-ml/ | FETCHED | Rule #29 (log serving features, train on them), #37 (measure training/serving skew) — S4 |
| [Sculley-2015-HTD] | Sculley et al., "Hidden Technical Debt in ML Systems", NeurIPS 2015 | SNIPPET | undeclared consumers — the intake rule's rationale |
| [Uber-2025-DeploySafety] | Uber Engineering, "Raising the Bar on ML Model Deployment Safety", 2025-10-30, https://www.uber.com/gb/en/blog/raising-the-bar-on-ml-model-deployment-safety | FETCHED | shadow on live inputs, then a small slice with automatic rollback (S4–S6) |
| [RTS6-2017/589] | Commission Delegated Regulation (EU) 2017/589 (MiFID II RTS 6), Art. 5 testing, Art. 8 controlled deployment with predefined limits, Art. 12 kill functionality; https://eur-lex.europa.eu/eli/reg/2017/589/oj (UK copy marked revoked by FSMA 2023) | FETCHED (UK legislation.gov.uk copy, Art. 8) | S5 reduce-only canary with predefined limits |
| [PYS-2003-JPM] | Philips, Yashchin, Stein, "Using Statistical Process Control to Monitor Active Managers", *J. Portfolio Management* 30(1), 2003, doi:10.3905/jpm.2003.319922 | META + SNIPPET | S6 CUSUM on decayed alpha |
| [Page-1954] | Page, "Continuous Inspection Schemes", *Biometrika* 41(1/2):100–115 | SNIPPET | S6 CUSUM origin |
| [Gama-2014-CSUR] | Gama et al., "A Survey on Concept Drift Adaptation", *ACM Computing Surveys* 46(4):44, doi:10.1145/2523813 | FETCHED (abstract) | S6 retraining |
| [Google-MLOps-CD] | Google Cloud, "MLOps: Continuous delivery and automation pipelines in ML", https://docs.cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning | FETCHED | triggers for retraining (schedule, new data, decay), online validation before serving |
| [Kim-2025-arXiv] | Kim et al., arXiv:2509.15040 (2025), https://arxiv.org/pdf/2509.15040 | FETCHED | a random baseline restricted to the same number of trades (S3 same-rate random arm) |

**NO SOURCE FOUND** (said plainly, so nobody cites this plan as if there were one):
- labels taken from the **exit actually traded, net of costs**: no primary source sets labels this way; it is our design choice under M1.
- a **meta-labeling** study that compares the overlay against a **random filter at the same rejection rate**: none found; [Kim-2025-arXiv] is the nearest (a forecasting paper), and the permutation-test lineage (Aronson 2006; Masters 2020) was seen only in snippets.
- a **trading firm's** published champion/challenger procedure: none found.
- that SR 11-7 / OCC 2011-12 still apply: they were withdrawn on 2026-04-17 ([FRB-SR26-2-2026], [OCC-2026-13]); cite the 2026 guidance.

---

## 7. What this plan does not do

- It does not build `ML-REAL-MONEY-OVERLAY`, register its rule, or set either rule's thresholds.
- It does not arm any `advisory_policy`, edit any roster, `mode:` or risk cap, or grant a mandate.
- It does not stop the existing ML research; it changes what may enter the queue. Grandfathered units run as filed.
- It does not settle where prop legs sit on the ladder (OPERATING-PLAN § 2 leaves that open); it treats them as money legs for intake order only.
