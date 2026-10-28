# ML programme: models that manage trades (2026-10-28)

> **Doc status:** `unknown` · category `plan` · last verified `2026-10-28` (registry/status read 06:25Z; nobody but this lane has verified it) · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Checklist row:** [`ML-PROGRAMME-PLAN`](../claude/work/checklist/ML-PROGRAMME-PLAN.json) · roadmap `M25`, `L-ATM`, `L-DESK` · lane dispatched by Manager Session 2026-10-27a · Tier 1, planning only.
> **What this is:** ONE consolidated ML plan. It folds the ML items of `ROADMAP.md` § "AI trader (ML) — build plan", `docs/plans/ml-plan-items.yaml`, research programmes 01/02/06, the desk design's student hand-off (§ 4, 4A–4C) and the checklist into one set of tracks.
> **What it authorises:** nothing. The § 5 rows are **proposals**. The manager files them with the operator. Every promotion is still the ladder: an offline rule registered before the run, net of the full cost stack, then the existing tier gates.
> **Fact base:** lane `ML-COVERAGE-AUDIT`, [`docs/research/ml-coverage-audit-2026-10-28.md`](../research/ml-coverage-audit-2026-10-28.md) (branch `claude/ml-coverage-audit-20261028`, draft at 06:45Z). Its measurement is not repeated here, only cited.

> **Operator, 2026-10-28 ~06:30Z (paraphrased, relayed by the manager; binding for this lane):** *"Give ML infra priority: the whole point of the trading desk is to TEACH the models; without the infra set up correctly we won't learn correctly. Stop and think about the best way to approach this given our resources and the goal of creating models that can MANAGE TRADES. … make ONE consolidated plan that tests lots of different things and builds what works — thorough and research-oriented."*
>
> **Operator, 2026-10-27 ~07:20Z (row `ML-ARCH-GENERALIST-VS-SPECIALIST`, close paraphrase):** the main AI goal is still ONE in-house AI that watches markets and manages trades from start to end. Keep a generalist and per-market specialists side by side and always test which is better, possibly as a committee.

---

## 0. The programme in eight lines

1. **The target is a POLICY, not a classifier.** At every bar of an open trade it picks one action from a closed enum: hold, tighten the stop, pull in the TP, partial close or close. At entry it picks take/skip and a size bucket. It is scored on **net R per capital-day vs the bracket the leg trades today**, out of sample, net of the full cost stack.
2. **The outcome is the teacher, and it is free.** For every stop/TP/close action, the counterfactual can be replayed exactly on the real price path. So one replayed trade yields a per-bar table of what each action would have earned. That is unlimited, cheap and leakage-controllable. Claude's desk decisions are a **benchmark policy and an optional extra label source**. A desk label is earned into training only by an ablation that shows it adds value, because plan-session labels are scarce (~$0.34 a packet, MEASURED) and so far the desk has not beaten its baselines.
3. **Most models have been aimed at the wrong question.** 68 of 97 registered models predict a market regime or direction label. 0 predict an in-trade action. The one in-trade manifest (`exit-policy-v1`, target `should_hold`) is **not in the registry**: it has never trained. The capacity went into BTC 15m volatility depth, not trade management.
4. **The evidence says the information exists but the decision rule is the gap.** On the six money legs as traded (2,627 trades, 50,926 bar-states): the linear in-trade model PASSES on log-loss (`RQ-20261024-09a6-01`, +0.0023 nats, 6/6 folds), but the one-step exit-now policy FAILS on money (`d6e7-06`). The hindsight oracle leaves **0.756 R/trade** on the table. So the next tests are about **how a decision is formed**: continuation value, a richer action set, cost-aware learning, and a bigger corpus. They are not about yet another feature on the same head.
5. **One bench decides everything.** `TM-BENCH` holds a frozen corpus, fixed purged folds, one cost stack, one action enum, one replay engine, the baselines and one scorer. Every model family, every rule lever and the desk itself submit a policy file and get scored on the same states.
6. **The tracks** are T0 measurement and bench, T1 data breadth, T2 labels and the teacher pipeline, T3 trade-management models, T4 selection and sizing, T5 regime state as features, T6 frontier, and T7 promotion and serving (§ 4).
7. **Build order:** TM-BENCH → paths corpus widened to every leg the harnesses can replay → learning ledger (the standing proof) → desk/LTR label join into the bench schema → the audit's data-breadth rows (§ 5).
8. **This week's milestone, beside the desk:** TM-BENCH v1 scores baselines B0–B4 plus three model families on one corpus, and the first learning-ledger record lands (§ 6).

---

## 1. Goal and success criteria

### 1.1 What "a model that manages trades" is

A trade-management policy π maps a **point-in-time state** to an **action**:

| decision point | state (all known at the bar close; nothing later) | action enum (closed; mirrors desk schema v2 and the live-review enum) |
|---|---|---|
| **in-trade, every closed bar** | open R, peak R, MAE, bars held, bars since peak, distance to stop and to target in R and ATR, the stop/TP in force, the leg's own trail state, momentum/ADX/range features, the vol-regime head output for that symbol (T5), flow where history exists (funding, taker imbalance, OI) | `hold` · `tighten_sl{atr k | r level}` · `tp_pull_in{r level}` · `partial_close{fraction}` · `close` |
| **entry (selection)** | the strategy's signal and confidence, the signals-catalog decision-time features, regime state, the leg's recent record | `take` · `skip` · size bucket {0.5×, 1×} (reductive only; sizing itself stays with each account's `RiskManager`) |

It never widens a stop past entry risk, never sizes up past the leg's risk, and never touches `mode:`, `execution:` or the roster. Those limits are the same as the desk's and the live review's.

### 1.2 What it must beat (all net of the full cost stack, out of sample, same states)

| id | baseline | why it is the bar |
|---|---|---|
| **B0** | **the leg as traded**: its own bracket, trail, stale-stop and TP rules, replayed config-exact (`--emit-paths`) | "do nothing new". A model that cannot beat the incumbent rules is not a manager |
| **B1** | **best static rule per leg**: the best of the confirmed rule levers (ADX trail, momentum-stale stop, measured-move TP), plus the per-leg best `exit_lever_ablation` arm **chosen in-sample, scored out of sample** | a model must beat what a cheap rule already captures (programme 01: *"Two things work today, and both are rules"*) |
| **B2** | **distance-only reference**: a calibrated logit on room-to-stop and room-to-target alone (the A1 reference) | "learned where the trade sits" is not trade management (room-to-stop alone has AUC ~0.81, `EXIT-PATH-METRICS-W43`) |
| **B3** | **the desk**: Claude's continuous management on the same masked states (`DESK-LIFECYCLE-S0`, `desk_replay_driver.py`) | the operator's benchmark (*"measure the MLs against the Claude trading desk"*, design § 4B) and DESK-19's S-drives bar |
| **B4** | **matched-rate placebo**: the same number of non-hold actions at random bars of the same trades | catches a policy that "wins" by acting more or less often, not by acting at the right time |
| (ceiling) | hindsight oracle, best single close per trade | scale only: 0.756 R/trade on the 2,627-trade corpus (MEASURED, `research/results/RQ-20261024-09a6-01/40143286436.jsonl`, `census.__pooled__.oracle_best_close_saving_r_per_trade`) |

### 1.3 Success criteria, registered here so units cannot be tuned to them afterwards

- **S-OFFLINE (a model family earns a place):** on TM-BENCH, policy − max(B0, B1) ≥ **+0.03 R/trade** pooled, 95% CI lower bound > 0, ≥ 5 of 6 folds positive, max drawdown not worse than B0, and net R per capital-day not worse than B0 (`scripts/capital_efficiency.py`, single home). It must also beat B2 and B4. Each unit restates this rule verbatim before its run. A unit may set a stricter bar, never a looser one.
- **S-CONFIRM:** harness-native confirmation per leg under the exit-refinement P2 gate (Path A or B, 6-fold walk-forward), then the bracket-advisor parity read (`BRACKET-ADVISOR-SHADOW`, 1–2 live trades per leg). Then a Tier-3 proposal with the record (§ T7).
- **S-STUDENT (replacing a desk role):** DESK-19's criteria, unchanged (design § 4.3). S-shadow → S-advisory at n ≥ 150 OOS decisions, net R per capital-day > 0 and ≥ the role's baseline. S-drives requires ≥ Claude at margin 0 with a 95% CI half-width ≤ 0.02 R, which needs about 1,540 paired decisions per role.
- **S-LEARNING (the pipeline is learning, § 7):** every hop of the learning ledger is non-zero and moving week over week, and the "best policy vs B0" line on the bench improves or a FAIL is recorded against a named configuration.

**Programme done-condition (first cycle, ~4 weeks):** either at least one policy clears S-OFFLINE on ≥ 2 legs and reaches the bracket advisor, or every T3 question in § 4 is graded, with the configurations tested and not tested written to `families.<f>.history`. The second outcome is a valid end: it closes the price-state trade-management line on the legs as traded, and it says which information class is missing.

---

## 2. Resources, measured

Each line names its population and where it was read. "Re-run, never quote" applies: these are dated readings.

### 2.1 Compute

| resource | measured state | read at | what it means for this programme |
|---|---|---|---|
| **Trainer VM** `ict-trainer-vm` (aarch64, 1 OCPU, 6 GB) | nightly cycle trained **66** manifests, 3 audit refusals, rc 0 (cycle_end 01:24Z); 110 dataset builds ok / 0 failed in 24 h; disk 53.5 of 103.9 GB (51.5%); `load_1m` 0.0 at 06:25Z | `GET /api/bot/ml/status`, 2026-10-28 06:25Z (mirror age 84 s) | the trainer is **not on the trade-management critical path**: path replay uses public candles on a runner. It is needed for serving, the registry and the nightly retrain only |
| trainer spare capacity | **0.0 spare OCPU**, 0.649 GB spare memory (p95 over 7 days); cpu_p95 ~100% on 2026-10-27 (partial day) | `comms/cloud/compute_spare.json` (as_of 2026-10-27T12:40Z), `comms/cloud/compute_util_ledger.jsonl` | INFERRED: the 7-day window still contains days before `ict-drift-retrain.timer` was retired on 2026-10-25. That timer was 30.45 CPU-h/week (63.7%) in the 2026-10-13 profile (`comms/cloud/trainer_workload_profile.json`). **Re-measure after 2026-11-01**, when the window is clean. Until then treat the trainer as full |
| GitHub runners | 4 vCPU / 16 GB / 6 h per job, free; research capped at 3 in flight (+2 data) because CI p90 holds ~17 of ~20 shared slots | `scripts/research/research_compute.yaml` (`limits`, cap measurement 2026-10-13) | **the main engine of this programme.** Every TM-BENCH unit is `cpu_light`/`cpu_long` on a runner |
| Kaggle CPU kernel | 1 slot, free, not metered; mounts the private published dataset | same file, `kaggle_cpu` | for units that need the published market shards |
| Kaggle GPU | 2× T4, ~30 GPU-h/week, 1 slot, internet off (weights ride in the bundle) | same file, `kaggle` | sequence models and TSFM forecasters: earned only after a tree/linear PASS (§ T3, T6) |
| RunPod | fallback only, ledger-capped at $10/month, operator-armed | same file, `runpod` | not planned for this programme |

### 2.2 Data and labels available today

| source | volume | read at | bounds |
|---|---|---|---|
| **Paths corpus: six money legs as traded** (`--emit-paths`) | **2,627 trades, 50,926 bar-states**; exits: trail 1,198, stop 933, TP 459, stale 29, timeout 8; net 0.1445 R/trade | `research/results/RQ-20261024-09a6-01/40143286436.jsonl` (`census.__pooled__`) | **the n of every T3 question today.** Paired per-trade sd of policy − incumbent ≈ **0.40–0.51 R** (INFERRED from `d6e7-06`'s CIs: pullback n 796, half-width 0.028; donchian n 1,831, half-width 0.023). So 2,627 trades detect ≈ +0.03 R/trade at 80% power, and ≈ 640 trades are needed for +0.05 R |
| Stage-0 trade ledgers (all legs) | **14,601 rows in 172 `*__trades.jsonl` files** across 31 runs; the 2026-10-14 census found 54 legs / 5,063 trades in the newest ledger per leg | `find comms/strategy_evidence/runs -name '*__trades.jsonl'` (this lane); `02-AI-TRADER.md` § 2 | per-trade only (no per-bar path). Widening paths to these legs (§ 5, row 2) roughly doubles T3's n |
| journal closed trades (all accounts incl. paper/demo) | `trade_outcomes` 2,875 rows (incl. backtest), `setup_labels` 2,875, `conviction_meta` 1,545 | audit § 1c | selection (T4) and parity. Real-money R-graded: **466 trades, expectancy −0.3355 R** (`GET /api/bot/performance`, window `all`, 2026-10-28; journalTrust flags `bybit_2` divergent and `alpaca_live` unrecorded) |
| live per-bar path history | `position_path_history`: one row per (package, bar) with sl/tp in force, peak, MAE, ATR, ADX; observe-only | row `EXIT-PATH-TELEMETRY-LIVE` (`done`) | live parity and validation only; too few trades to train on |
| **desk decisions** | **59 rows** (2026-10-26 13:50Z → 2026-10-28 05:04Z): 56 `no_trade`, 3 `propose_entry` (2 `basis: mechanics`, excluded from edge replay; 1 SLV with no outcome row yet). `outcomes.jsonl` 58 rows, **all `not_computable`**. `consumed.jsonl` **0 rows** | `comms/desk/*.jsonl` at `main@4329698a1` | **0 edge-sample desk labels with an outcome today.** Entry generation showed no edge vs random (judged-1/-2, e535). One-shot management at +1R failed (#20836: in-trade −0.048 R, CI [−0.143, +0.041]; exit −0.091 R, CI [−0.198, −0.003], n = 176) |
| live-trade-review rows | **98 rows on 16 packages**: `no_recommendation` 45, `hold` 32, `flag_mechanics` 20, `close` 1, `tighten_sl` 0 | `comms/live_review/reviews.jsonl` | 16 distinct trades is far below every floor (CJ-4 n ≥ 150 distinct trades) |
| Claude post-trade grades | 617 blind / 546 revealed | `comms/claude_judgments/*.jsonl` | built nightly into `claude_judgments` (627 rows, audit § 1c); **no manifest trains on it** |
| market data for features | `market_features` only for BTC, ETH, SOL, MES; ADA/AVAX/XRP raw 15m only; ETFs and metals raw 1d only; the exporter publishes BTC/ETH/SOL × 15m/1h only | audit § 1c and § 3.2 | the vol-regime state feature (T5) exists for 4 of 23 rostered symbols |

### 2.3 Session budget

- **Plan sessions only.** Nothing spends Anthropic API credits (`docs/CLAUDE-RULES-CANONICAL.md` § "Nothing spends Anthropic API credits", 2026-10-27). `scripts/research/desk_judge_api.py` is retired and refuses.
- The weekly plan bar is shared with every project the operator runs. The repo records no dollar budget for ML (manager SKILL § "The budget"). Lanes carry dollar ceilings: comparable Tier-1 build lanes landed at **$2.45–$10.44** (`PATH-FLOW-JOIN` $2.45, `REMAINING-MOVE-HEAD` $3.37, `BRACKET-ADVISOR-SHADOW` $10.36, `FIRST-PASSAGE-ON-PATHS` $10.44; checklist notes).
- **Teacher labels are the scarce resource.** MEASURED: $0.337 per judged packet in plan sessions (DESK-18B pilot, `desk_judge_api.py` docstring) and $0.34–$0.47 per desk wake (trading-desk SKILL § 6b, n = 4). INFERRED: DESK-19's ~1,540 paired decisions per role cost ≈ **$520 of plan usage per role per judging pass**. Outcome labels from replay cost $0 in model usage.

### 2.4 What bounds n, per question

| question class | binding constraint | how this plan moves it |
|---|---|---|
| in-trade/exit policy (T3) | trades in the paths corpus (2,627 on 6 legs) | widen the corpus to every leg the harnesses replay (row 2); pool across legs (Q-TM5) |
| flow-augmented state (A2) | point-in-time flow coverage: 471 trades left after dropping legs with < 80% coverage (`RQ-20261024-09a6-02`); OI history starts 2021-12 | per-leg coverage design + `DATA-DERIV-ARCHIVE` (Q-TM7) |
| imitation of / comparison with the desk (B3, Q-TM4) | plan-session budget per judged packet | judge only where the bench says the models are uncertain (active sampling, T2) |
| student hand-off (DESK-19) | distinct live trades (16 LTR packages; 0 desk outcomes) | offline masked sessions (DESK-24) on plan; forward shadow |
| selection (T4) | per-cell labels (~78 real decision rows per cell, M23) | the ledger corpus with catalog features (`METALABEL-EMIT-FEATURES`) |
| regime state (T5) | symbols with `market_features` (4 of 23) | the audit's breadth rows |

---

## 3. Roadmap consolidation

Every ML item found in `ROADMAP.md` § "AI trader (ML) — build plan", `docs/plans/ml-plan-items.yaml` (population: 80 items at `main@4329698a1`), `docs/roadmap/milestones.yaml` and the checklist rows that resolve to `M25`, `M23`, `M14`, `M9`, `L-ATM`, `L-DESK`, `L-DATA` or `L-REGIME`. Rule applied: **never kill a line on one bad pass** (operator, 2026-09-27). "Kill" below closes a *configuration* whose registered rule already failed, or an item superseded by a merge. It never closes a family.

### 3.1 Map: item → track → disposition

| item(s) | track | disposition | reason |
|---|---|---|---|
| ML-S2 (exit line), `IN-TRADE-EXIT-MODEL`, `FIRST-PASSAGE-ON-PATHS`, `REMAINING-MOVE-HEAD`, `EXIT-ARM-CHOICE-CORPUS`, `PATH-FLOW-JOIN`, programme 01 "AI active trade management" ladder (A1/A2/B1/C1/D) | **T3** | **merge** into the TM-BENCH questions (§ 4.3) | one population, one scorer. The A/B/C/D rungs become bench questions; their units keep their ids |
| ML-S2's per-trade LightGBM "does holding pay" head (donchian −14.66 R OOS; INDETERMINATE SOL/XRP/ETH; XRP multi-fold FAIL) | T3 | **kill the configuration** | three graded negatives at the registered rule. The *family* stays open on the per-bar target (Q-TM1) |
| `exit-policy-v1.yaml` (`should_hold`, the only in-trade manifest) | T3 / T0 | **re-scope** onto the bench's action-value labels; its family `exit_candidates` is never built by `build_trainer_datasets.sh` (0 mentions), the likely reason it never registered | its model_id is absent from `/api/bot/ml/registry` (MEASURED, 2026-10-28: manifest model_ids diffed against the 97 registry rows; also absent: `mes-execution-quality-baseline-v0`, `setup-candidates-metalabel-paper-v1`) |
| ML-X1 / `ML-LEG-CORPUS` | T1 | **merge** into `PATHS-CORPUS-WIDEN` (§ 5 row 2) | same corpus, wider |
| ML-X2 TP-predict head (`RQ-20261009-900/-901`) | T3 | **re-scope** to Q-TM9 (competing-risks TP) | B1's clause 1 FAILED at τ 0.5 and 0.7 (`RQ-20261024-09a6-03`): remaining move is not linearly predictable beyond the leg's own quantile. A TP head built on the same target would repeat that test |
| ML-X3 / `EXIT-HEAD-PULLBACK-DRIVER` (`RQ-20261008-901`) | T3 | **merge** into Q-TM5 (pooled across leg families) | a per-family transfer is one cell of the pooled-vs-per-leg question |
| `MOMENTUM-STOP-MODEL`, `EXIT-GIVEBACK-PREDICTOR-GATE` (`9a7e-01..04` all FAIL "incumbent stands") | T3 | **merge** into Q-TM3 (tighten as an action) | a learned stop is a `tighten_sl` policy. The P ≥ 0.5 gate configuration is closed |
| `DATA-INTRADE-LABEL-STORE` | T2 | **superseded** by the TM-BENCH action-value labeler | the labeler computes the per-(trade, bar) label in the bench, from the same emit. A persisted family is built only if a promoted model needs it on the trainer |
| ML-R1/R2/R4/R5/R6/R7/R8, ML-N1/N1J, `REGIME-*` rows, audit rows `ML-COV-POOLED-CRYPTO-VOL`, `ML-COV-ROUTER-CELLS`, `ML-COV-EQUITY-DAILY` | **T5** | **keep**, re-aimed: the vol heads become **state features** for T3 and T4, besides gating | the only head type that has earned advisory. Today it reaches 3 BTC demo legs (audit § 2) |
| ML-F0 (weekly frontier scan), `FRONTIER-RESEARCH` | **T6** | **keep**, re-pointed: the scan's first question each week is trade-management families (§ 4.4) | the skill is unchanged; its target list changes |
| ML-F2/F2T/F3/F15/F27/F28 (vol-label family bake-offs, queued or open) | T6 | **finish what is queued; author no new vol-label bake-offs** for 4 weeks | the regime head is not the bottleneck. The 21 graded family verdicts in `families.*.history` (mostly on the regime label) changed no order |
| ML-F14 (TSFM LoRA fine-tune) | T6 | **park** | its registered condition, an F1 PASS, did not occur: 9da8-01 graded FAIL (Chronos-2 zero-shot only, n 78,735; `ml-plan-items.yaml` ML-F1 close note). TimesFM/TiRex arms remain untested, so the family stays open |
| ML-F22L / ML-F29 (GRU on the regime label) | T6 → T3 | **re-scope**: a sequence learner is earned on the trade-management target by a tree PASS (Q-TM8) | deep_sequence is FAIL ×1 on the regime label; the same inputs would not be a new test |
| ML-F4 (offline bandit over exit arms, `RQ-20261011-9da8-04`) | T3 | **merge** into Q-TM6 (C1 chooser re-run) | the same question. C1 is INDETERMINATE only because the join drops 14.2% of entries |
| ML-F5, `FRONTIER-LEVER-HARNESS-COSTS`, `-LEADLAG`, `-XSEC-RUNNER` | strategy research | **out of this programme** | strategies, not trade management. They stay on programme 03 |
| ML-P0/P1/P2/V1/V1J, `ML-PARITY-*`, `ML-PRODUCER*` | **T7** | **keep** | serve parity gates every promotion |
| ML-D1/D2/D3/D4/D6, `ML-DATASET-FIXES`, `ML-HYGIENE`, `ML-LABEL-WALL`, `ML-SHARD-TRUNCATED` | T1 / T0 | **keep**; `ML-LABEL-WALL` becomes a ledger column (§ 7) | |
| ML-S1 (veto), ML-S3 (proposer), ML-N6 / `ML-NETR-RANKER`, `PROP-MISSION-MODEL` (label 0 of 267) | T4 | **stay parked**, on their registered gates | no new information class has passed. The desk's entry generation also shows no edge (`DESK-18D-JUDGE-2` blocked) |
| ML-M0/M2/M3/M4/M5 (meta-labelling on the ledger corpus), `METALABEL-EMIT-FEATURES` | **T4** | **keep** | selection is a manage-the-book decision; M5 is the take/skip test |
| ML-M6, `HEADLINE-MEASURE-CAPITAL-DAY` | **T0** | **keep, raise** | three definitions currently share the headline's name (row note). The bench uses `scripts/capital_efficiency.py` only |
| `DESK-11/20/21/22/23/24/25`, `CJ-2/4/5/6/7`, `ML-CLAUDE-DISTILL-DESIGN` | **T2** (11, 20, 23, 24, CJ-*), **T0** (21, 22), **T7** (19, 25) | **keep**; DESK-21 merges with audit row 7 into `ML-LEARNING-LEDGER` (§ 5 row 3); DESK-22's scorecard is the bench's desk/student block | design § 4A–4C are the label requirements. This plan supplies the bench they are scored on |
| `DESK-19-STUDENT-HANDOFF` | T7 | **keep**, with Q-TM4 as its precondition | a student is trained only on a source that has shown value |
| CJ-7 backfill | T2 | **keep, plan-only from now on** | tier A spent $12.37 of API credits before the 2026-10-27 rule. Future backfill runs in plan sessions |
| `ML-ARCH-GENERALIST-VS-SPECIALIST` | T3 + T5 | **keep**: Q-TM5 (trade management) and audit row 2 (vol head) are its first two tests; a committee arm rides Q-TM10 | operator 2026-10-27 |
| `KAGGLE-*`, `ML-DATA-OFF-TRAINER`, `ML-DATA-RUNNER-FETCH`, `ML-RUNPOD-RESULT-LANDING`, `ML-NONGBDT-RUNNERS`, `FRONTIER-LEVER-TRAINER-DEPS`, `ML-RQ-RUNNER` | T1 / T6 infra | **keep** | the routes T3/T6 units run on |
| `DATA-KLINE-ARCHIVE`, `DATA-DERIV-ARCHIVE`, `DATA-LABEL-TIES`, audit `ML-COV-DATA-ALTS`, `ML-COV-EXPORTER-WIDEN` | **T1** | **keep, sequenced** in § 5 | |
| M14, M9 (dormant milestones) | — | unchanged (already superseded by M25 / L-DATA) | |
| M41 local LLM | — | unchanged (backlog; no build) | |

### 3.2 BTC regime variant sprawl: the cap

MEASURED at `main@4329698a1` (72 enabled manifests in `ml/configs/*.yaml`): **48 predict `regime_label`**, of which **26 are BTCUSDT**, 9 ETH, 8 MES and 5 SOL.

- **Adopt the audit's freeze list** (audit § 4, about 17 BTC manifests: the vt00x threshold sweep, the HMM line, the v003 controls, `fc-v1`, the direction heads and the 5 BTC-only metalabel variants). Those move to a weekly retrain through `TRAINING_MANIFESTS` (audit row `ML-COV-TRAINER-BUDGET`, Tier 2). Nothing is retired: a line ends only on its registered exhaustion condition.
- **The standing cap (proposed rule, enforced by the ledger, not by a new guard):** no new manifest on a (symbol, target, timeframe) cell that already has **3** manifests on the nightly cycle, unless the PR names the one it replaces. `ml_plan_status.py --coverage` (§ 5 row 3) prints the per-cell count every week, so a fourth variant is visible in the ML review instead of being found months later.

---

## 4. The programme

### 4.1 Tracks

| track | question it answers | done when (first cycle) | owner surface |
|---|---|---|---|
| **T0 Measurement and bench** | can every policy be scored the same way, and can we prove the pipeline learns? | TM-BENCH v1 scores B0–B4; the learning ledger writes weekly | rows 1 and 3; `/ml-review` step 1 |
| **T1 Data breadth** | does every rostered leg have paths, and does every symbol have market features? | paths emitted for every leg the trend/pullback/squeeze/fade harnesses can replay; `market_features` for XRP/ADA/AVAX; exporter widened | rows 2 and 5 |
| **T2 Labels and the teacher pipeline** | does every decision the system or the desk makes become a label with an outcome, and is it consumed? | the action-value labeler runs inside the bench; desk/LTR/lifecycle rows are in the bench schema with outcomes; `consumed.jsonl` > 0 | rows 1 and 4; DESK-11/20/24, CJ-2/4 |
| **T3 Trade-management models** | which model family, if any, manages an open trade better than the incumbent rules? | Q-TM1..Q-TM10 graded | research queue; research-ops grades |
| **T4 Selection and sizing** | can a model skip or downsize the trades a leg should not take? | M5 graded on the widened ledger corpus with catalog features | programme 02 Q2 units |
| **T5 Regime state** | does the one proven signal (the vol head) help management when used as a feature, and on how many symbols does it exist? | audit rows 1/2/4/5 landed; Q-TM2's regime arm graded | audit rows; `REGIME-VOL-LABELS-EXPORT` |
| **T6 Frontier** | which outside model families fit trade management, under our data/compute/latency/licence gates? | the § 4.4 triage is registered as units and re-read weekly | `frontier-research` skill |
| **T7 Promotion and serving** | can a passing policy reach a live bracket safely and match the offline replay? | the first S-OFFLINE pass (if any) reaches the bracket advisor | `BRACKET-ADVISOR-SHADOW`, DESK-19, ML-P*/V* |

### 4.2 The common evaluation harness: TM-BENCH

**One bench, every policy, the same states.** It composes existing pieces; it does not replace them.

| component | built from (existing) | what TM-BENCH adds |
|---|---|---|
| **corpus** | harness `--emit-paths` (#18536), `first_passage_paths.py` / `path_metric_giveback.run_leg_paths` (leg config-exact inside a unit), `PATH-FLOW-JOIN` flow columns | a **frozen, hashed** corpus version (`corpus_id`, per-leg config sha, candle source, window). Every score names the corpus_id, so two results are comparable or visibly not |
| **folds** | 6 calendar folds by entry, purged and embargoed (the A1/d6e7 construction) | one fold file reused by every unit |
| **cost stack** | `execution_costs.resolve_cost_policy()` | asserted equal in every result (`cost_policy_check`, as C1 already does) |
| **action enum + replay engine** | `desk_replay_driver.py` (SL-first, a gap fills at the open, an invalid level scored as HOLD and counted); `exit_lever_ablation.py` (rule arms) | one replay function for model, rule and desk actions |
| **action-value labeler (the outcome teacher)** | — (new) | for every (trade, bar, action in the enum): the net R of taking that action at that bar vs holding, replayed on the real path. This is the training target for Q-learning-style and imitation-of-oracle learners, and it is past-features / future-label by construction |
| **baselines** | B0 = the emit itself; B1 = `exit_lever_ablation` arms + confirmed levers; B2 = A1's reference logit | B3 = desk policy file from `desk_replay_driver`; B4 = matched-rate placebo; oracle |
| **scorer** | `capital_efficiency.py` (net R per capital-day), the A1/d6e7 fold CI code | one `score` entry point: policy file (`state_id → action`) in, verdict-ready JSON out. The desk and every model submit the same file format |
| **learner kinds** | `ml_bakeoff.py` kinds (prior, numpy_logit, lightgbm, catboost, sklearn_hgb) | policy wrappers (§ 4.3 Q-TM1/2/3) so a learner produces actions, not just probabilities |

**Composition with the desk lifecycle factorial.** `DESK-LIFECYCLE-S0` (lane `session_01AFoLuJGUG7n1WDzgCysB32`) is testing continuous full-trade management by Claude now. When its packets are drawn from TM-BENCH's corpus (same trades, same masked states), the desk's result *is* B3, and every model is compared with it on the same packets at zero extra judging cost. If DESK-LIFECYCLE-S0 lands on a different trade set, the bench imports its states by `(leg, entry_time, bar)` and scores the overlap; it does not re-judge.

**Composition with exit-refinement.** A bench PASS is Stage-0 evidence for a *model* lever. It still goes through the exit-refinement pipeline per leg (P2 gate, grant cap, MIN_OOS_TRADES = 25, TP doctrine) before any Tier-3 flip. The bench never writes `config/strategies.yaml`.

### 4.3 Research questions (each becomes ONE pre-registered unit; the rule text below is the registration draft)

Common to all: population = TM-BENCH corpus v1 (the six money legs as traded, window 2020-07..2026-10 as emitted, 6 purged calendar folds by entry), widened by row 2 when it lands. Rule = S-OFFLINE (§ 1.3) unless a stricter one is stated. Power = from the measured paired sd 0.40–0.51 R (§ 2.2). If realised n is below the floor the verdict is `underpowered`, never `fail`. Compute = runner `cpu_long` unless stated. Model usage = the authoring lane only.

| id | question | candidate vs baseline | pre-registered rule (beyond S-OFFLINE) | n / power | compute · cost | why it could work where A1-policy failed |
|---|---|---|---|---|---|---|
| **Q-TM1** | **Does a GBDT action-value model produce an exit/tighten policy that beats the incumbent?** (A3, already earned by A1's PASS under plan rule 8.7) | LightGBM regression of each action's net-R advantage on the full state; act when the predicted advantage exceeds the action's cost by a margin chosen in-fold | must also beat the linear twin by ≥ +0.01 R/trade, so tree depth has to earn its place | 2,627 trades: detects ≈ +0.03 R at 80% | runner · lane ~$10 (learner wrapper) | nonlinear interactions of distance-to-stop × momentum × regime that a logit cannot express |
| **Q-TM2** | **Does optimal stopping with a continuation value beat the one-step exit rule?** | Longstaff–Schwartz-style backward induction: regress the continuation value on state, bar by bar from the trade's last bar, and exit when the immediate value exceeds it | arms: linear and GBDT regressors; with and without the vol-head state (T5); must beat `d6e7-06`'s own policy | same | runner · ~$8 | `d6e7-06` compared exit-now with one-step-ahead odds. LSM values the whole remaining path, which is the classical answer to "exit now or continue" |
| **Q-TM3** | **Does a richer action set (ratchet the stop, pull in the TP, partial) beat exit-only?** | the Q-TM1 learner over the full enum vs the same learner restricted to {hold, close} | the richer set must beat exit-only by ≥ +0.01 R/trade *and* clear S-OFFLINE | same | runner · within Q-TM1's lane | the evidence says rules that **tighten** work (ADX trail, momentum-stale) while models that **exit** fail. A model that chooses where to put the stop is closer to what already works |
| **Q-TM4** | **Is the desk a better manager than B0/B1, and does adding desk labels improve an outcome-trained student?** | (a) B3 vs B0/B1 on the shared packets; (b) the best Q-TM1..3 policy trained with vs without desk-decision features and auxiliary imitation targets | (a) is DESK-LIFECYCLE-S0's own registered rule. (b) runs **only if (a) passes**; then the with-desk arm must beat without-desk by ≥ +0.01 R/trade OOS, on post-cutoff states only (pre_cutoff rows train, never gate) | (a) as registered by that lane; (b) the judged packets it already holds, no new judging | runner · $0 new judging | answers the operator's teacher question with data: a teacher is worth distilling only if it beats the incumbent, and a desk label is worth its ~$0.34 only if the student improves |
| **Q-TM5** | **Generalist or specialist: one pooled trade-management model over all legs, or one per leg family?** (`ML-ARCH-GENERALIST-VS-SPECIALIST`, first test) | pooled with leg/family/symbol as features vs per-family models vs per-leg models, same learner (the best of Q-TM1..3) | the pooled model must be within 0.01 R/trade of the per-leg models on every leg and beat them pooled; otherwise the specialist wins | needs row 2 (widened corpus); per-family n from the widened census | runner · ~$6 | pooling multiplies n per parameter. The 6-leg corpus mixes only two harness families |
| **Q-TM6** | **Can a chooser pick, per trade, among rule exits that already confirmed, better than the best single rule?** (C1 re-run; absorbs ML-F4) | state-conditioned chooser, plus doubly-robust OPE as a cross-check | C1's registered rule; the join must exclude ≤ 10% of entries (the clause that made it INDETERMINATE: 14.2%) | the C1 corpus | runner · ~$5 (join fix) | choosing among rules that work is a low-variance way to beat any single one |
| **Q-TM7** | **Does flow (funding, taker imbalance, OI) add management value beyond price?** (A2 re-run) | the A1/Q-TM1 learner with vs without the flow block, **per leg where coverage ≥ 80%**, pooled only across those legs | A2's rule, with the population restated per leg; n floor recomputed for the covered legs | 471 trades today (`09a6-02`); more after `DATA-DERIV-ARCHIVE` | runner · ~$5 | the one new information class with point-in-time history; its first test died on coverage, not on signal |
| **Q-TM8** | **Does a sequence model over the in-trade path beat the tree?** | small GRU/TCN over the last k bars of state (numpy-servable size) vs the Q-TM1 winner | runs **only after** a Q-TM1/2/3 PASS (earned-learner rule); must beat the tree by ≥ +0.01 R/trade | same | Kaggle GPU or runner CPU · ~$8 | path shape may carry what bar summaries lose; on the regime label it did not (deep_sequence FAIL ×1), which is why it is gated |
| **Q-TM9** | **Does a competing-risks model (time to stop vs time to target vs timeout) place a better TP than the leg's own?** (re-scoped ML-X2 / B1) | discrete-time hazard per bar (multinomial logit, then GBDT) → the TP level that maximises expected net R; pull-in only | calibration first (Brier per horizon vs the leg's own bucketed frequency), then money as S-OFFLINE vs B0 | same | runner · ~$6 | B1 regressed the remaining move directly and failed. A hazard model asks a different question: *which barrier first, and when* |
| **Q-TM10** | **Does a committee beat its best member?** (operator's committee idea) | majority vote / advantage-averaging over the Q-TM1..3 policies (and B3 when (a) of Q-TM4 passes) | must beat the best single member by ≥ +0.01 R/trade, so a committee earns its complexity | same | runner · within a later lane | ensembling decorrelated policies is a cheap variance cut; this is the operator's committee arm made testable |
| **Q-SEL1** | **Does a within-family take/skip head beat take-all and the strategy's own confidence?** (M5) | logit, then GBDT, on the ledger corpus with catalog features | M5's registered rule (programme 02 Q2) | ledger corpus (5,063+ trades) | runner · as filed | selection is part of managing the book; it is the entry-side lever with the most labels |
| **Q-REG1** | **Does one pooled crypto vol head serve the uncovered symbols?** (audit row 2) | as the audit specifies | as the audit specifies | as specified | as specified | puts the one proven signal on XRP/ADA/AVAX, which carry 4 of the 7 real-money legs |

**Top 5 by information per dollar:** Q-TM1, Q-TM2, Q-TM4, Q-TM5 and Q-REG1. Q-TM1/2 are cheap and decide whether price-state trade management is alive on the legs as traded. Q-TM4 decides what the desk is for. Q-TM5 decides the architecture. Q-REG1 decides whether the state features exist for real-money symbols.

**What a FAIL closes.** Each FAIL is written to `families.<family>.history` with the exact configuration (corpus_id, learner, state block, action set). If Q-TM1, Q-TM2, Q-TM3 and Q-TM6 all FAIL at power, the conclusion is recorded as: *price- and regime-state management on the legs as traded does not beat the rule levers at +0.03 R/trade*. The programme then moves to new information (Q-TM7 and successors; programme 02 Q5), not to more variants.

### 4.4 Frontier scan: model families for trade management, triaged

Four gates per the frontier-research skill: **D**ata, **C**ompute, **L**atency/serving (mirror-publish, zero torch on the money box), **K** leakage and licence.

| family | fit to trade management | D | C | L | K | verdict |
|---|---|---|---|---|---|---|
| linear / logit first-passage and action-value | the reference; A1 PASS on log-loss | ✅ | ✅ | ✅ numpy | ✅ | **kept** (baseline in every unit) |
| GBDT action-value (LightGBM/CatBoost) | earned by A1's PASS | ✅ | ✅ runner | ✅ existing exit-head artifact pattern | ✅ | **kept: Q-TM1** |
| optimal stopping via regression (Longstaff–Schwartz) | the textbook form of "exit now vs continue"; works with any regressor | ✅ | ✅ | ✅ | ✅ (backward induction is in-trade only, past features) | **kept: Q-TM2** |
| survival / competing risks (discrete-time hazard; DeepHit-class later) | first-passage is a competing-risks problem | ✅ | ✅ | ✅ (hazard logit) | ✅ | **kept: Q-TM9** (deep variants gated) |
| offline RL, fitted-Q (tree-based FQI) | our exit/tighten actions have **exact counterfactuals**, so the usual offline-RL coverage problem largely disappears and FQI reduces to Q-TM1/2 with a bootstrap target | ✅ | ✅ | ✅ | ✅ | **folded into Q-TM1/Q-TM2** as an arm |
| offline RL, deep (CQL/IQL, e.g. `d3rlpy`) | overkill at 2.6k trades; its value is for actions without counterfactuals (entries), which are parked | ⚠️ thin n | Kaggle GPU | ⚠️ torch | ✅ | **dropped (data gate)**: reopen when the corpus passes ~20k trades |
| contextual bandit over rule arms + doubly-robust OPE | C1's shape | ✅ | ✅ | ✅ | ✅ | **kept: Q-TM6** |
| imitation learning / behaviour cloning of the desk | needs a teacher that beats the incumbent | ❌ today (0 edge-sample desk outcomes; #20836 FAIL) | ✅ | ✅ | ⚠️ pre_cutoff memory | **gated on Q-TM4(a)** |
| active learning: query Claude only on high-uncertainty states (DAgger-style) | the cheap way to spend plan sessions on labels | ✅ | plan sessions | n/a | ⚠️ pre_cutoff | **kept as the T2 sampling rule** once Q-TM4(a) passes |
| sequence models (GRU/TCN/small transformer over the path) | path shape | ✅ | Kaggle GPU | ⚠️ numpy export needed at small size | ✅ | **gated: Q-TM8** |
| TSFM quantile forecasts (Chronos-2, TimesFM-2.5, TiRex) as a remaining-move feature | B1 failed linearly; a forecaster is a different information source | ✅ OHLCV | Kaggle GPU | ✅ mirror-publish of features | ⚠️ pretraining overlap: hold out bars after each model's release; licences read from the Hub card | **one unit after Q-TM9**, as a feature arm (Chronos-2 zero-shot already FAILED on the vol label; that closed only that configuration) |
| tabular foundation models (TabPFN/TabICL) | small-n tabular, fits state tables | ✅ | Kaggle GPU | ❌ for TabPFN live (non-commercial weights) | licence | **research arm only** inside Q-TM1, never served |
| conformal abstention wrapper | most bars should be `hold`; act only on calibrated confidence | ✅ | ✅ | ✅ | ✅ | **kept as a wrapper arm** on the Q-TM1 winner (conformal history: PASS ×1, FAIL ×1, INDET ×1) |
| local LLM as policy (M41) | no use case clears the latency/cost gates | — | ❌ trainer 1 OCPU | ❌ | — | **dropped** (M41 stays backlog) |

The weekly scan (Sunday, `/ml-review` step 9 → `frontier-research`) re-reads this table first and adds sources. **A family with 0 trade-management units is "untested", not "not promising"** (skill Step 1).

### 4.5 The desk as teacher: how the plan uses it

1. **The desk's job in the programme is to be B3 and an explorer.** Every desk decision is recorded, priced and joined (DESK-20). The bench scores it like any policy.
2. **Desk labels go into training only through an ablation that shows value** (Q-TM4(b), DESK-25). This is design § 4.1's rule — *"Claude is a teacher, never ground truth … every source re-qualifies through CJ-4"* — made concrete.
3. **Where the desk wins, spend plan sessions on its labels, aimed by the student's uncertainty** (active sampling, rho per design § 4.5). Where it loses, its decisions remain useful as *negative* examples and as coverage of states the strategies do not trade (DESK-23 exploration).
4. **Offline desk sessions (DESK-24) run on the TM-BENCH corpus**, through `desk_replay_driver.py`'s masked packets, on plan sessions only. Their cost per label is measured on a pilot before any volume is scheduled.

---

## 5. Infra build order (proposed rows: the manager files them with the operator)

Ordered by questions unblocked per dollar. Each row is Tier 1 unless marked. Each would carry the `roadmap` refs shown and the re-entry test that closes it. **None is filed by this lane.**

| # | proposed row | what | unblocks | tier · model · ceiling | roadmap | re-entry test |
|---|---|---|---|---|---|---|
| **1** | **TM-BENCH** | `scripts/research/tm_bench.py`: frozen corpus build (hashed `corpus_id`), shared fold file, the action-value labeler, baselines B0–B4 and oracle, one `score` entry point taking a policy file; learner wrappers for logit and LightGBM action-value; `selfcheck` mode (B0 scored against itself = 0 exactly; oracle ≥ every arm) | Q-TM1/2/3/6/9/10, B3 import, DESK-22's desk/student block | 1 · Opus (it defines the numbers every later verdict rests on) · $15 | L-ATM, M25, L-DESK | a runner unit lands `selfcheck` pass, then B0–B4 scored on corpus v1 with B0 − B0 = 0 and the oracle saving reproducing 0.756 R/trade ± 0.005 on the 6-leg population |
| **2** | **PATHS-CORPUS-WIDEN** | emit paths for every rostered leg whose harness supports `--emit-paths` (trend and pullback first, then squeeze/fade/ict_scalp); add the missing emit to a harness where it is a flag-sized change; the bench's corpus v2 | Q-TM5, power for every T3 question; merges ML-LEG-CORPUS | 1 · Sonnet · $12 | L-ATM, L-DATA | corpus v2 census: ≥ 15 legs and ≥ 5,000 trades, every leg's emit reproducing its committed Stage-0 net R within 0.01 R/trade |
| **3** | **ML-LEARNING-LEDGER** | the § 7 measurement: `scripts/ops/ml_learning_ledger.py` writes `comms/ml-learning/<stamp>.json` weekly (hops H1–H7) and a brief line; folds in DESK-21 (never-trained detector: a decision row older than 14 days in no `consumed.jsonl`; a manifest whose model_id is not in the registry after 2 cycles) and audit row 7 (`ml_plan_status.py --coverage`: tiers A–D per leg, the per-cell manifest cap) | S-LEARNING; makes "merged reported as working" mechanically visible | 1 · Sonnet · $8 | M25, L-DESK, M39 | first record reproduces this doc's § 7 baseline values at its commit, and flags `exit-policy-v1` as never-registered |
| **4** | **DESK-LABEL-JOIN** (scopes DESK-11 + DESK-20 to the bench schema) | desk decisions, LTR rows and DESK-LIFECYCLE-S0 judged packets mapped to bench `state_id`s with their replayed outcomes; `consumed.jsonl` written by every dataset build or bench run that reads them | Q-TM4, B3, CJ-4's population, DESK-19 | 1 · Sonnet · $10 | L-DESK, M25 | every desk/LTR row older than its horizon has an outcome or a named `not_computable` reason; `consumed.jsonl` > 0 after the first bench run that reads them |
| **5** | **Data breadth** = audit rows `ML-COV-DATA-ALTS` ($8) + `ML-COV-EXPORTER-WIDEN` ($5) + `ML-COV-TRAINER-BUDGET` (Tier 2, $3) | `market_features` for XRP/ADA/AVAX at 15m/1h; the exporter widened to every rostered crypto symbol plus a 1d equity/metal set; the BTC freeze list moved to a weekly retrain | Q-REG1, T5 state features on real-money symbols, Q-TM2's regime arm beyond BTC/SOL | as the audit states | L-DATA, M25 | as the audit states |
| 6 | **TM-LEARNERS-2** | bench wrappers for the LSM backward-induction policy, the competing-risks hazard and the conformal abstention wrapper | Q-TM2, Q-TM9, the conformal arm | 1 · Sonnet · $8 | L-ATM, M25 | each wrapper passes the bench `selfcheck` and scores B0's states without error |
| 7 | **C1-JOIN-FIX** | fix the EXIT-ARM-CHOICE-CORPUS join that excludes 14.2% of entries | Q-TM6 | 1 · Sonnet · $5 | L-ATM | the re-run's `entry_set_agreement` excludes ≤ 10% |
| 8 | **REGIME-STATE-EXPORT** (extends `REGIME-VOL-LABELS-EXPORT`) | per-bar vol-head outputs, point in time, joinable to bench states for every symbol with a head | Q-TM2 regime arm, audit row 3 | 1 · Sonnet · $6 | L-REGIME, M25 | the bench joins the vol-head column on ≥ 95% of BTC/SOL states, with timestamps ≤ the state's bar close |
| 9 | `HEADLINE-MEASURE-CAPITAL-DAY` (exists, queued) | one served definition | G1 and the bench's per-capital-day line | as filed | as filed | as filed |
| 10 | `DATA-DERIV-ARCHIVE` (exists, queued) | flow history for the six crypto symbols | Q-TM7 | as filed | as filed | as filed |

**Critical path:** 1 → (2 ∥ 3 ∥ 4) → 6 → the T3 units. Row 5 runs in parallel; it does not block T3, only T5. Rows 7/8 are small and slot in wherever a lane is free.

**Total proposed ceilings, new rows only (1, 2, 3, 4, 6, 7, 8):** $64, plus the audit's rows. INFERRED from the comparable lanes' measured spends (§ 2.3); the T3 units themselves run on free runners.

---

## 6. The next 7 days, and what is safe before the reset (~18:00Z today)

### 6.1 Before the weekly reset (Tier 1, small, no order path)

| # | what | why now | size |
|---|---|---|---|
| a | **land this plan** (this PR) and its row `ML-PROGRAMME-PLAN` | the manager files § 5 from it with the operator | this lane |
| b | **dispatch TM-BENCH (row 1)** | everything in T3 waits on it; it needs no trainer time and no decision | Opus, $15 |
| c | **dispatch ML-LEARNING-LEDGER (row 3) v0** | makes today's zeros (desk outcomes 0, consumed 0, in-trade models 0) a weekly record before more is built on top | Sonnet, $8 |
| d | **land the audit's `ML-COV-DETECTOR`** if row 3 is not dispatched today | the same visibility at $3 | Sonnet, $3 |
| e | **one `get-env` read** of `REGIME_ML_VERDICT_MODE`, `CONVICTION_SIZING_MODE`, `CONVICTION_SIZING_ACCOUNTS` (audit § 5) | tier A's size depends on it; a read is Tier 1 | system-action, $0 |
| f | **C1-JOIN-FIX (row 7)** | turns an INDETERMINATE into a verdict for $5 | Sonnet, $5 |

Not before the reset: row 2 (it overlaps with row 1's corpus code; dispatch after row 1's corpus format lands), and anything Tier 2 (`ML-COV-TRAINER-BUDGET`).

### 6.2 The week's milestone (week of 2026-11-02, beside the desk)

**"TM-BENCH v1 is the scorer of record":**
1. B0–B4 scored on corpus v1, and the oracle saving reproduced.
2. Q-TM1, Q-TM2 and Q-TM6 registered (hold PRs per E57) and run on the runner; research-ops grades them.
3. Corpus v2 (row 2) built, and Q-TM5 registered on it.
4. The first `comms/ml-learning/` record, and its line in the brief's "what moved".
5. DESK-LIFECYCLE-S0's result imported as B3 (or a dated reason why not).
6. The audit's data-breadth rows landed, with XRP/ADA/AVAX `market_features` observed in two consecutive nightly builds.

**Weekly review hook:** the Sunday `/ml-review` § "The ML plan loop" reads this plan's § 4.3 table as track T3 in `ml-plan-items.yaml`. Adding those items is the first ML review's write-back; this lane does not edit the plan-items file, so the review is not pre-empted.

---

## 7. The standing measurement: is the pipeline LEARNING?

**Why.** The audit found every teacher-side record *recorded → built into a dataset → never trained*, and every trade-side model *trained → never promoted* (audit § 1c). Each of those hops was reported as shipped. A merged builder is not a learning system.

**The ledger** (row 3; one JSON per week under `comms/ml-learning/`, one line in the brief; read by `/ml-review` step 1):

| hop | counted as | source | baseline today (MEASURED, 2026-10-28, `main@4329698a1` + `/api/bot/ml/*` 06:25Z) |
|---|---|---|---|
| **H1 produced** | decisions and trades produced in the window, per source | `comms/desk/decisions.jsonl`, `comms/live_review/reviews.jsonl`, journal closes, bench emits | desk 59 rows (all time); LTR 98 rows on 16 packages; trade_outcomes 2,875; paths corpus 2,627 trades |
| **H2 labelled** | rows with an outcome joined (replayed or realised, net of cost) | `comms/desk/outcomes.jsonl` (kind ≠ `not_computable`), LTR replay, bench labeler | desk **0** edge-sample outcomes (58 `not_computable`, 1 pending); LTR replay labels: not built (DESK-20); paths: 50,926 states labelled inside units, not persisted |
| **H3 in a dataset** | labelled rows listed in a dataset build's or bench run's consumed ids | `comms/desk/consumed.jsonl`, dataset metadata, bench `corpus_id` | `consumed.jsonl` **0**; `claude_judgments` 627 rows built nightly (audit) |
| **H4 trained** | manifests or bench learners that read the dataset in the window | training cycle log, bench run records | **0** manifests read `claude_judgments`; 0 in-trade manifests in the registry (`exit-policy-v1` never registered) |
| **H5 scored** | policies scored on TM-BENCH vs B0/B1, with verdicts | `research/results/` | 5 in-trade units graded on the paths corpus since 2026-10-24: A1 pass (log-loss), d6e7-06 fail, B1 fail, C1 indeterminate, A2 indeterminate; plus the giveback-gate units 9a7e-01..04, all fail |
| **H6 promoted** | models at shadow/advisory whose target is a trade decision | registry | **0** (advisory 3, all vol-regime; shadow 20) |
| **H7 changes an order** | legs where an ML output can change an order; real-money legs among them | audit tier A | **5 of 51** rostered legs, **0 of 7** real-money/prop legs (audit § 2) |

**Alarms** (one flag each to the manager, never a halt; Prime Directive rule 7):
- any hop at 0 for 14 days while the hop before it is non-zero (the "recorded but never trained" shape);
- a manifest absent from the registry after 2 nightly cycles;
- a newly rostered leg in tier D;
- a (symbol, target, timeframe) cell with more than 3 nightly manifests (§ 3.2).

**Reporting rule.** A capability counts as *working* in a brief or row only when the ledger shows its hop moved. "Merged" and "deployed" are reported as such, never as "learning".

---

## 8. What this lane did and did not verify

- **Measured this session:** `/api/bot/ml/status`, `/api/bot/ml/registry` and `/api/bot/performance` (direct HTTPS, ~06:25Z); manifest parse of `ml/configs/*.yaml`; `config/strategies.yaml` (57 entries; 54 not `enabled: false`; 23 distinct symbols among those); every committed JSONL counted in § 2.2 and § 7; the A1/A2/B1/C1/d6e7-06/9a7e verdicts read from `research/results/`.
- **Taken from the audit, not re-measured:** rostered-leg tiers (5/51, 0/7), trainer cycle minutes, dataset-family row counts, the freeze list and the causes in audit § 3.
- **INFERRED (arithmetic or reading, not measured):** the paired sd and power figures (§ 2.2), the freed trainer capacity after the drift-timer retirement (§ 2.1), teacher-label cost per role (§ 2.3), and lane ceilings (§ 5).
- **Not verified:** whether `tm_bench.py` can reuse `desk_replay_driver.py`'s replay function without changes (row 1 establishes this); the DESK-LIFECYCLE-S0 trade population (that lane is running); the exact trainer log line for `exit-policy-v1`. The cause is INFERRED: its dataset family `exit_candidates` exists (`ml/datasets/families/exit_candidates.py`) but `scripts/ops/build_trainer_datasets.sh` never builds it (0 mentions; positive control: `setup_candidates` 9 mentions), so the manifest most likely clean-skips on an empty dataset (exit 78) every night.
