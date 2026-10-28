# ML live-promotion plan: models into live decision loops by Monday 2026-11-02 (2026-10-29)

> **Doc status:** `unknown` · category `plan` · last verified `2026-10-28` (registry/status read 20:56Z; relays #21020/#21021, see § 1) · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Checklist row:** [`ML-LIVE-PROMOTION-PLAN`](../claude/work/checklist/ML-LIVE-PROMOTION-PLAN.json) · roadmap `M25` · track **MODEL** · lane dispatched by the manager (session_01AFoLuJi1vLTnYv9LbP6539) · Tier 1, planning only.
> **Operator priority #1 (2026-10-28 ~20:55Z, verbatim):** *"ML research and development - I want to try getting MLs into live trading loops as soon as possible, so let's try and get a concrete plan together to get handful promoted in the next few days. We also need to validate and extend the infra/ops for ongoing ML R&D"*.
> **What it authorises:** nothing by itself. It **registers the promote rules before any run** (§ 3), so a later PASS is a committed, pre-registered evidence record. Every stage change past `shadow` and every `config/` edit is Tier 3: the operator approves, or the manager ships under canonical § "Data-backed Tier-2/3 decisions" when the registered rule is cleanly passed, and notifies the operator at once.
> **Parent plan:** [`ML-PROGRAMME-2026-10-28.md`](ML-PROGRAMME-2026-10-28.md) (trade-management models, TM-BENCH). This plan is the **short path**: it uses consumers that already exist in the order path, so a model that passes can act this week. It does not replace the programme.

---

## 0. The answer in ten lines

1. **ML changes orders on 5 of 51 rostered legs, all on `bybit_1`, and on 0 of 7 real-money legs** (roster re-parsed at `main@71ead79f`; consumers per [`ml-coverage-audit-2026-10-28.md`](../research/ml-coverage-audit-2026-10-28.md) § 1b). The 5 are the BTC router cells (`trend_donchian`, `ict_scalp_5m`, `squeeze_breakout_4h`) and the exit-head close on `trend_donchian` / `_eth` / `_sol`.
2. **Two consumers already exist and are idle**, and they are the fastest route: the WS7 advisory downsize/veto (`src/runtime/advisory_sizing.py`, inert because all 3 advisory models are regime heads) and the router's `trend_vol` OFF-cells (`config/regime_policy.yaml`, only BTC cells exist).
3. **Five candidates** (§ 2): **P1** the pooled setup meta-label as an entry veto, **P2** an ETH vol head with ETH router cells, **P3** re-verifying and extending the BTC router cells, **P4** `conviction-meta-v1` as a size multiplier (stretch), and **P5** bringing the exit head, which already closes positions, under the registry and cost gate.
4. **All five start on the `bybit_1` demo floor**, on legs that trade **only** on `bybit_1`. Real money needs more on top (§ 2, last column).
5. **The binding blocker is not the models. It is the cost-net eval.** #20869's gate refuses all 9 setup meta-label heads because their eval rows were built before the cost-basis stamp (gross/unstamped), not because a loss was measured (§ 1). Rebuilding the dataset (PI-20261028-V8KBRR5H-0004) is step one, on Thursday.
6. **P1 needs one Tier-2 build:** the advisory serve path scores a 6-field row (`_feature_row_from_pkg`), and the meta-label head needs 10 candle features. A serve-side feature builder, with a train-vs-serve parity test, must deploy before shadow parity can be read.
7. **Every promote rule is registered here, before the run** (§ 3), net of the full cost stack, with a matched-random control and a demotion signal.
8. **Forecast, stated honestly:** p(pass) is P1 ≈ 0.25 (lowered after ML-FRONTIER-PREP, § 1a), P2 ≈ 0.40, P3-extension ≈ 0.30, P4 ≈ 0.10. P5 is a validation, not a promotion. **Expected new promotions by Monday ≈ 1.1, and 0 is a real outcome.** The plan still delivers a graded verdict on every candidate by Sunday. A FAIL closes the candidate with its configuration recorded, which is a result, not a slip.
9. **Operator decisions** (§ 5): one Tier-2 OK (deploy the serve feature builder, Friday), and up to three Tier-3 packets (Saturday). Each comes with its evidence record and a one-line revert.
10. **Infra/ops** (§ 6): eight MODEL rows prove the chain *data → labels → train → score → serve → changes an order → graded* end to end, plus the trainer timer, drift alerts, registry hygiene and the missing learning ledger.
11. **P6, added 21:05Z at the operator's request:** a **conservative, hold-biased exit/management model** for this week's "every real-money strategy has basic active management" milestone (§ 2a). MEASURED: the desk labels price `close`/`hold`/`tighten`/`partial` but barely `move_tp` (45 rows) and not `widen`/`structure` at all (0 rows). On the 2,001 hold-vs-close check-ins, closing at ≤ −0.5 R **did not** beat holding (hold − close +0.089 R, CI [−0.08, +0.28]). So the model is expected to say HOLD almost always, and its edge cases have to earn their place on held-out data. Split proposed with lane `ACTIVE-MGMT-REAL-MONEY-PLAN`: this plan owns the model, that lane owns the LTR wiring and the rollout. Per-class graduation is DESK-V1 § 5b (cited, no parallel gate); no non-hold class is expected to graduate this week.

---

## 1. What was measured for this plan (population stated for every number)

| fact | value | population · source · time |
|---|---|---|
| registry stages | advisory 3 · shadow 20 · candidate 73 · research_only 1 (= 97) | every registry row · `GET /api/bot/ml/status` `registry.stages` · 2026-10-28 20:56Z, mirror age 28 s. The manager's relay of "73 candidate" counts `research_only` separately; canonically both are `candidate` (74) |
| deployment buckets | LIVE 3 · SHADOW 20 · OFFLINE 74 | same 97 rows · `GET /api/bot/ml/registry` `deployment_bucket` · same read. ⚠️ the legacy `status` field reads `candidate` on **all 97** rows (§ 6, I4) |
| what the 3 advisory heads are | `btc-regime-15m-lgbm-fc-pcv-v2`, `sol-regime-15m-lgbm-fc-pcv-v2`, `mes-regime-5m-lgbm-v2`: all vol-regime heads | same read |
| family mix | market_features 72 (regime) · setup_candidates 9 · conviction_meta 4 · trade_outcomes 4 · setup_labels 3 · 5 others 1 each | 97 rows, `dataset_ref.family` |
| rostered legs | **51** unique legs on `mode: live` accounts; **7** on real-money/prop accounts (`ada_pullback_2h`, `iaum_pullback_1d`, `trend_donchian_eth_4h`, `trend_donchian_eth_prop`, `trend_donchian_sol_prop`, `trend_donchian_xrp_4h`, `xrp_pullback_2h`) | `config/accounts.yaml` re-parsed at `main@71ead79f` (`bybit_2`, `bybit_portfolio`, `alpaca_live`, `alpaca_portfolio`, `breakout_2`, `tradeify_1`, `velotrade_1`) |
| legs ML changes | 5 / 51; real money 0 / 7 | union of the `trend_vol` cell strategies (3, `config/regime_policy.yaml`) and the `exit_head_action: close` legs (3, `config/strategies.yaml`), overlap `trend_donchian`. **Conditional on `REGIME_ML_VERDICT_MODE=use` on the VM** (relay #21021) |
| setup meta-label heads, cost gate | 9 of 9 `cost_gate_passed: 0` | the 9 `setup_candidates` rows, registry `metrics.cost_*` |
| `setup-candidates-metalabel-p2pool-v1` (as it was evaluated) | `cost_net_value_r` **+0.0407 R/opp**; take-all **−0.492**; matched random **−0.064**; take-none 0; take rate 0.130 (≈ 42 of 324 taken); PSR 0.794; n_trials 1 | `n_eval` 324 = the real closed BTC/ETH/SOL trades of the 3 harness strategies in the `live_holdout` split of dataset v020 (built 2026-08-04). **Gross/unstamped basis**: the gate refused on `eval_not_cost_net`, not on a measured loss |
| why the eval is unstamped | the 7 `setup_candidates` dirs on the trainer were built 2026-06-06 → 08-04, `label_version` triple-barrier-v1; the daily cycle never rebuilds them | PI-20261028-V8KBRR5H-0004 (trainer-vm-diag #20864/#20865); the current builder stamps real-trade rows `label_cost_basis: realized` (`ml/datasets/families/setup_candidates.py:1150`) |
| `conviction-meta-v1` | macro-F1 0.430, accuracy 0.537, n_eval 309; no `cost_*` metrics | registry row; its rows are unstamped (PI-20261028-V8KBRR5H-0002) |
| exit head | `exit-head-donchian-1h-v1`, threshold 0.1, `exit_head_action: close`, on 3 legs; **not a registry row** (a mirror artifact from `scripts/ml/export_exit_head.py`) | `GET /api/bot/config` `strategies.*` 20:56Z; registry has 0 rows with that id |
| BTC/ETH/SOL 15m regime heads, classification bar | all three FAIL the registered macro-F1 lift bar (+0.10): BTC holdout −0.0001, ETH +0.022, SOL +0.054 | RQ-20261012-75b2-16/-17/-18 (row `ML-REGIME-15M-DRIFT`). A classification lift is not decision value. The router cells are judged by walk-forward money (§ 3 P2/P3) |
| trainer | timer active, last trigger 2026-10-28 00:31Z, next 2026-10-29 00:52Z; last cycle_end 08:22Z rc 0 (`complete_with_refusals`, 6 refusals); builds 24 h: 98 ok / 0 failed / 2 skipped; disk 51.6 %; staleness: 5 stale, 2 never trained, of 72 scanned | `GET /api/bot/ml/status` 20:56Z |
| learning ledger | `scripts/ops/ml_learning_ledger.py` **absent** | `ls` on `main@71ead79f` |
| desk lifecycle labels | 12,500 rows | `comms/research/desk_lifecycle/full-c4e/labels.jsonl` (`wc -l`). These are TM-BENCH inputs, not a promotable model this week |
| "0 of 23 learner arms beat the LightGBM regime head" | **not re-measured by this lane** | relayed by the manager. I did not locate the result file in the time box, so it is cited only as context and nothing here depends on it |

**Relay reads** (trainer-vm-diag #21020: stage-guard, gate-check on 6 models, setup_candidates label basis, exit-head artifact; system-action `get-env` #21021: `REGIME_ML_VERDICT_MODE`, `CONVICTION_SIZING_MODE`, `CONVICTION_SIZING_ACCOUNTS`). See § 8 for what they returned.

---

## 1a. The ML-FRONTIER-PREP findings, each accounted for (manager relay 21:21Z; review record `comms/reviews/ml-review-20261028-200000.json`, PR #20972)

The review numbers its proposals P1–P6 too. To avoid a clash they are written **R-P1…R-P6** here.

| finding | how this plan accounts for it |
|---|---|
| **(a)** cost gate #20869 refuses all 9 meta-label heads with `eval_not_cost_net` (a data problem) | the rebuild PI-20261028-V8KBRR5H-0004 is **step B1, the head of P1's critical path**. Row `ML-P1-COSTNET-REBUILD`; owner = the lane the manager dispatches at the Thu 10-29 06:17Z planning (Sonnet, $8); **ETA: v022 built and the P1 verdict by Thu 10-29 ~20:00Z**. Nothing entry-side promotes before it. The review's call ML-20261028-1 puts p = 0.75 on "no meta-label head passes on cost-net rows" and notes that p2pool's +0.041 R/opp is about one measured cost stack per taken trade. **This plan's P1 forecast is lowered to p ≈ 0.25 accordingly** (was 0.35) |
| **(b)** the exit head closing trades on 3 legs is not in the registry | **registered in B4** (`ML-EXITHEAD-VALUE`, which also prices its decision value, P5). It is a **named prerequisite of P6**: no second exit model goes on those legs while the first is unregistered and unpriced |
| **(c)** the yz heads serve `vol_bucket` dead in live (PI-20260927-3WM5HADW-0005), which blocks yz promotion | no yz head is in this slate. ⚠️ **The same feature is in P1**: `vol_bucket` is one of p2pool's 10 features. B2's parity test must show `vol_bucket` present, non-default and equal to the training value on identical bars, or P1 does not move to shadow (§ 3 P1 shadow mechanics already require 10/10) |
| **(d)** label provenance still unfixed (PI-20261014-MVBJLVJ3-0001) | this hits **P1's eval directly**: `setup_candidates._live_realized_r` divides pnl by `|entry − trades.stop_loss|`, and a trail overwrites that stop. So a trailed winner's R is inflated. **B1 is extended**: the v022 eval R uses the initial risk (`r_provenance.initial_risk_usd`), or rows graded CONTAMINATED are excluded and counted. § 3 P1 gains rule (e) for this. P6's corpus B uses harness paths (initial risk by construction) and is not exposed; the desk labels are replay-priced and are not exposed either |
| **(e)** the chain breaks at "promoted → changes an order" (5/51 legs, 0/7 real money); the SOL-15m and MES-5m heads change 0 legs | the whole slate targets that hop, but only on **`bybit_1`-only legs** this week. **Real money stays 0/7 this week by design**, because every real-money route needs Gate 2 (§ 2, last column). SOL-15m: kept as an observer with no cell (regime-selectivity Rule 1 says that is the correct state). That is a disposition, not a gap. MES-5m: wiring-or-retire goes to Thursday planning on its refinement row PI-20261028-GNVUF1ES-0001 (axis fidelity rules out the 1d MES leg) |
| **(f)** R-P1…R-P6 are unqueued (PI-20261028-GNVUF1ES-0003) | **folded into this week:** **R-P5** (a decision-value column for router cells and the exit head; register the exit head) = this plan's P3 re-verify + P5/B4. **R-P6** (pause regime/direction learner variants; re-register or retire 4 queued units; $0) = folded into `ML-REGISTRY-LADDER-GAPS` (I4). **Marked for Thursday planning:** R-P1 (Q-SEL1 net take/skip on the ledger corpus + conformal abstention; the review calls it "the real test" for entry heads, which makes it P1's successor if P1 fails); R-P2 (Q-TM1 GBDT action-value on TM-BENCH; it feeds P6 v2); R-P3 (a pooled crypto vol head for XRP/ADA/AVAX, the only route to router cells on 4 of the 7 real-money symbols); R-P4 (desk decision attribution, TRADING track) |

---

## 2. The five candidates

All five act **only** on legs rostered on `bybit_1` alone, so no real-money account carries the effect. The CI guard in § 6 (I6) keeps it that way.

| # | model | legs it acts on (`bybit_1` only) | how it acts | consumer, and is it wired? | what real money needs on top |
|---|---|---|---|---|---|
| **P1** | `setup-candidates-metalabel-p2pool-v2`: the P2-pool manifest retrained on a **new** dataset version `setup_candidates/all/all/v022` (v020 build params, current cost-net builder; v020 stays immutable) | `trend_donchian` (BTC 1h), `trend_donchian_eth` (ETH 1h), `trend_donchian_sol` (SOL 1h), `squeeze_breakout_4h` (BTC), `htf_pullback_trend_2h` (BTC): the three strategies × three symbols its train/eval book covers | **entry veto**: `advisory_policy: {mode: downsize, size_floor: 0.0, bearish_threshold: τ}`, with τ = the eval threshold. Annotate-only on every other leg (the default when a strategy declares no policy) | WS7 advisory path, `Coordinator.multi_account_execute` → `apply_advisory_downsize`. **Wired, but the serve row lacks the model's features** → build B2 (§ 4) | (1) a fresh-window re-pass (`RESEARCH-CONFIRM-FRESH-WINDOW`); (2) a training book that **covers the real-money leg**: the 7 real-money legs are 4h/2h ETH/XRP/ADA/SOL-prop, and none is in this model's book, so P1 does not transfer as is; (3) Stage-1 mechanics, 1–2 clean vetoed or taken decisions; (4) for prop legs, the prop EV/survival superset |
| **P2** | an ETH vol head promoted to `advisory`: `eth-regime-15m-lgbm-xasset-v1` vs its control `eth-regime-15m-lgbm-selfonly-v901ctrl` (both `shadow`; the better of the two on § 3 P2) | `trend_donchian_eth` (1h), `eth_pullback_2h`. **Not** `trend_donchian_eth_4h` / `trend_donchian_eth_prop` (real money / prop) | **entry veto by regime cell**: new `trend_vol` OFF-cells for those strategies, only the cells that pass | router `_hard_regime_gate` via `ml_vol_regime_for_symbol` (exact symbol). **Wired**; ETH resolves `unknown` today because no ETH head is advisory | a cell for a real-money strategy name gates every account carrying it, so it needs the walk-forward on that leg's own config, then Gate 2 |
| **P3** | `btc-regime-15m-lgbm-fc-pcv-v2` (already advisory): **re-verify** the 6 authored cells under the current head, then **extend** to `htf_pullback_trend_2h`, `fade_breakout_4h`, `turtle_soup`, `fvg_range_15m` only where a cell passes | the 3 legs gated today, plus those 4 | entry veto by regime cell (as above) | **wired** | as P2. No BTC leg is on real money today |
| **P4** (stretch) | `conviction-meta-v1`, retrained on cost-stamped rows | `bybit_1`-only legs with a conviction stamp | **size multiplier**, reductive only (`conviction_sizing.py`, `apply` mode, accounts allowlist = `bybit_1`) | conviction stamp path. **Wired**, gated by `CONVICTION_SIZING_MODE` / `_ACCOUNTS` (VM values from relay #21021) | the same as P1, plus a calibration check (ECE) on real-money-like trades |
| **P5** (validate an incumbent) | `exit-head-donchian-1h-v1` | `trend_donchian`, `trend_donchian_eth`, `trend_donchian_sol` (already acting) | **exit advice → close** (already live) | `exit_head_apply.exit_head_verdict`. **Wired and live, outside the registry and the cost gate** | it already acts. The question is whether it should keep doing so: decision value vs B0 (the leg's own exits) on the paths corpus, net of cost |

**Rejected alternatives (and why):**
- **SOL router cells:** regime-selectivity Rule 1. The SOL book is healthy and its negative cells failed the walk-forward (`A-vol-gating-ETH-SOL-OFFcell-evidence-2026-07-06.md`). Observer with no cell is the correct state. It is reopened only by a retrained head plus a fresh walk-forward, and that is not this week.
- **MES 5m head on the MES daily leg:** axis fidelity (Rule 3). A 5m vol label gating a 1d leg is the wrong axis.
- **Promoting any of the 20 shadow regime heads with no consumer cell:** a promotion with no consumer changes no order. That is the "promotion argument about a head that changes nothing" anti-pattern (ml-review).
- **A trade-management policy model (TM-BENCH, desk labels):** no family has passed S-OFFLINE yet (ML-PROGRAMME § 1.3). It is not promotable this week.
- **The other 8 setup meta-label heads:** they are BTC-only or degenerate. Their take rate is 0 or the value is 0 on the same read (registry `cost_net_*`). Only p2pool shows a positive point estimate.

---

## 2a. P6: the conservative hold-biased exit/management model (operator request, 2026-10-28 ~21:05Z)

**Operator, verbatim (relayed by the manager):** *"regarding the active management milestone - I'll settle for a conservative production ML that will mostly recommend holding outside of edge cases"* and *"active management isn't only tightening - it can be any movement in either bracket triggered by developments in the live market data"*.

**Ownership (to avoid planning it twice):** this plan owns the **model**: action space, labels, gate and the two build rows below. Lane `ACTIVE-MGMT-REAL-MONEY-PLAN` (session_01AFoLuMfbQGw8MoevpjjwwW) owns the **milestone and the wiring**: the LTR apply-path integration (`scripts/ops/live_review_apply.py` under MD-TRADE-DESK, tightens advice-only), the per-real-money-leg rollout, and demo first. I proposed this split to that lane at 21:09Z (trigger `trig_012G5fKXhmvFHY2aPs1C7vjY`); the manager arbitrates any disagreement.

**Action space** (closed enum; both brackets always stay in place; default HOLD):
`hold` · SL {`tighten` k, `widen` k (never below −2.0 R, never past entry risk on real money), `to_structure` (prior 12-bar swing)} · TP {`extend` k, `pull_in` k, `revise` to structure} · `partial_close` 50 % · `close`.

### What the 12,500 desk labels can price (MEASURED, `comms/research/desk_lifecycle/full-c4e/labels.jsonl`)

**Population:** 507 trades (pairs) on 6 crypto symbols, 1h, candles 2025-05-01 → 2026-09-25. The entries are Claude's or random (`src`). Each `value` is a **one-step ablation**: the managed path's net R minus the same path with that one check-in's action swapped (`desk_lifecycle_driver.py:1100-1118`). For the `claude` arm, `hold` is swapped to `close` and any other action to `hold`. For the rule arms (`v2:*`, policy C1E), the action is swapped to `hold`.

| action | rows | priced how | usable for P6? |
|---|---:|---|---|
| `tighten_sl` | 9,545 | at ONE level per check-in (the rule's or the decider's), vs hold | partly. One level, not a grid. Rule-arm levels dominate (8,331 rows from chandelier/breakeven/partial rules) |
| `hold` vs `close` | 2,001 | the value of holding vs closing at that check-in | **yes**, the core of the close-or-hold decision (456 trades) |
| `close` | 430 | vs hold | yes (with the row above) |
| `partial_close` | 479 | 50 %, vs hold | yes, thin |
| `move_tp` | 45 | one level, vs hold; extend and pull-in not separated | **no**. Too thin |
| `widen_sl` | 0 | — | **no** |
| SL/TP to structure | 0 | — | **no** |

**The extra labels needed, and how fast:** the replay engine prices **any** action exactly on the real path at $0 in model usage, so the gap is a build, not a data wall.
- **`ML-EXIT-ACTIONGRID-LABELS`** (Tier 1, Sonnet, $8, about 1 day). Add an `--action-grid` mode to `scripts/research/desk_lifecycle_driver.py`: at **every** check-in of every trade, under the same C×T check-in policy, price the whole enum against hold. That means close, partial, tighten k ∈ {0.25, 0.5, 1.0} R, widen k ∈ {0.25, 0.5} R, SL to structure, TP pull-in k ∈ {0.5, 1.0} R, TP extend k ∈ {1, 2} R and TP to structure, each with the rest of the path = hold-to-bracket.
  - **Corpus A:** the same 507 desk trades. About 12.5k check-ins × 13 actions ≈ 160k labels, one runner job.
  - **Corpus B (the one that matters for real money):** the legs' own Stage-0 paths (`--emit-paths`). The six-money-leg corpus has 2,627 trades and 50,926 bar-states (`RQ-20261024-09a6-01`), widened to the 7 real-money legs' configs: `xrp_pullback_2h`, `ada_pullback_2h`, `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `trend_donchian_eth_prop`, `trend_donchian_sol_prop`, `iaum_pullback_1d`. `iaum_pullback_1d` needs the equity harness's path emit; if it is absent, IAUM is out of scope this week and that is stated.
  - Runner time estimate (INFERRED): 2–6 h per corpus.

### P6 gate: per-class graduation is DESK-V1 § 5b (cited, not duplicated)

**Reconciled 2026-10-28 ~21:20Z, at the manager's instruction (trigger `trig_01N6LxSoeQ2BNK6W5kG9PYiP`).** The single per-class registry is [`desk-v1-production-plan-2026-10-29.md`](desk-v1-production-plan-2026-10-29.md) § 5b (PR #21023). This plan builds **no parallel gate**.
- **`hold` needs no graduation.** It is the default.
- **Every non-hold class the model emits stays advice-only** (recorded, priced, graded, changes nothing) until that class passes § 5b's template **for that leg × regime cell**:
  - dR above BOTH hold AND a matched random intervention of the same class;
  - net of the full cost stack, both brackets present;
  - a fresh OOS window;
  - n ≥ 126 trades with the action;
  - weekly-cluster 95 % CI lower bound > 0 against both;
  - Holm over the classes tested together;
  - the live advice-only record (≥ 20 priced calls) does not contradict it.
- Applying a graduated class needs § 5b's per-class `apply_mode` map (row `DESK-V1-CLASS-GATES`, Tier 3).

**What this plan adds on top (an extension, model-level only, not a class gate):**
- **Model:** `exit-holdbias-v1`. One LightGBM action-value head per class, trained on corpus A ∪ B. State = the packet features (now_r, mfe/mae, bars held, distance to SL/TP in R and ATR, trigger tags, ATR ratio, momentum). Purged walk-forward folds by trade and by time, embargo = the longest trade.
- **Decision rule, fixed now:** emit a non-hold class only if its predicted value beats hold by **≥ τ = 0.15 R**; otherwise HOLD.
- **"Mostly hold" sanity, on held-out corpus-B folds, net of cost.** The model may ship as an **advice producer** (`ML-HOLDBIAS-EXIT-MODEL` done) only if:
  (a) its *as-if-applied* policy is ≥ hold-to-bracket pooled, with trade-clustered LB > −0.01 R/trade;
  (b) its advice rate is ≤ 15 % of check-ins;
  (c) no leg is worse than −0.05 R/trade.
  Failing (a)–(c) means the model is retrained or retired. Its advice is not fed to the LTR record.
- **Label contribution to § 5b:** `ML-EXIT-ACTIONGRID-LABELS` is offered as the **shared Stage-A label source** for § 5b's unpriced classes (widen, TP extend, TP pull-in, to-structure), so the rule replays and the model train on one priced table.
  - One measured correction to § 5b's text: `labels.jsonl` prices more than hold-vs-close. Its `tighten_sl` (9,545), `partial_close` (479) and `close` (430) rows are one-step ablations, mostly of the rule arms (`v2:*`, 8,331 tighten rows) at one level per check-in. `move_tp` has 45 rows; widen and structure have 0.

**P6 forecast (revised under § 5b):**
- p(the model ships as an advice producer this week) ≈ 0.6.
- p(any non-hold class graduates to *applied* this week) ≈ 0.05. n ≥ 126 trades per class on a fresh window per leg × regime is not reachable by Monday, which matches DESK-V1's "nothing graduates this week".
- So the honest end-of-week state for the milestone is: **every real-money leg gets hold-to-bracket plus model advice recorded and graded (monitoring), with no ML-applied bracket move.** ACTIVE-MGMT owns how that is presented against the milestone.

**P6 timeline:** Thu 10-29 labels (`ML-EXIT-ACTIONGRID-LABELS`, shared with § 5b Stage A) → Fri 10-30 train + the model-level sanity check (`ML-HOLDBIAS-EXIT-MODEL`, Sonnet, $10, Tier 1) → Sat 10-31 the advice producer goes live as advice-only on the demo floor via ACTIVE-MGMT's LTR wiring → each class applies only after § 5b.

---

## 3. Pre-registered gates (registered 2026-10-28, before any of the runs below)

Each rule is fixed here and restated verbatim in its unit or row. A rule may be tightened later, never loosened. "Net of the full cost stack" means `src/runtime/execution_costs.py` (fee + slippage + perp funding, venue-correct) for synthetic rows, and journal-realized pnl for real-trade rows (`label_cost_basis ∈ {net, realized}`). A run whose output does not stamp its cost policy cannot be used for promotion.

### P1: setup meta-label veto
- **Data:** `setup_candidates/all/all/v022`, built with v020's `build_params` and the current builder. Train = harness rows; eval = `live_holdout` real closed trades (`is_live_trade` truthy), every eval row `label_cost_basis = realized`. **Assert** that the share of `r_multiple_source = unit_fallback` (the ±1 proxy) among eval rows is ≤ 10%. Above that, the eval is not cost-net in substance and the verdict is `INDETERMINATE`.
- **PROMOTE (candidate → shadow, then the shadow → advisory packet) iff ALL of:**
  (a) `cost_gate.json` `passed: true` (the value beats take-all, take-none, matched-random and any champion on the same rows);
  (b) the 95% **trade-level bootstrap** lower bound (10,000 resamples, seed 42) of `value_r − matched_random_r` is **> 0**;
  (c) `take_rate ∈ [0.05, 0.60]`. A veto that blocks everything is not a filter;
  (d) the value is positive in **≥ 2 of the 3 symbols** separately, with the per-symbol n reported (no pass is claimed on a symbol with < 30 eval rows).
  (e) **label provenance (PI-20261014-MVBJLVJ3-0001):** every eval row's R uses the initial risk, not the trail-overwritten `trades.stop_loss`. Rows that cannot be priced on initial risk are excluded and counted. If more than 20 % of eval rows are excluded, the verdict is `INDETERMINATE`.
- **FAIL** if (a) or (b) fails with ≥ 200 eval rows. **INDETERMINATE** if eval rows < 200 or (d) cannot be computed.
- **Shadow mechanics (C5):** 1–2 clean scored predictions on the five legs, and a serve-vs-train parity diff with every one of the 10 features present, non-default and equal (|Δ| ≤ 1e-6 on identical bars). No calendar term (OPERATING-PLAN § 2).
- **Demotion (advisory → shadow) when ANY of:** a parity diff finds a dead or defaulted feature; the nightly retrain's cost gate fails (the gate keeps the incumbent state; this plan demotes); or on the demo floor after ≥ 30 vetoed + taken decisions, the vetoed trades' counterfactual mean R exceeds the taken trades' mean R with a one-sided bootstrap p < 0.10 (counterfactual from `regime_shadow_gate` / `advisory_decisions.jsonl` packages replayed by the leg's harness).

### P2: ETH vol head and ETH cells
- **Head:** the candidate is whichever of `eth-regime-15m-lgbm-xasset-v1` / `-selfonly-v901ctrl` has the better cell walk-forward below. `gate-check` must show no FAILED `non_degenerate` / `live_parity` gate.
- **Cell rule (regime-selectivity Rule 2, verbatim shape):** for each candidate cell (start from the 07-06 ETH evidence cells, re-derived under the candidate head with `ml_vol_label_replay`), `regime_cell_walkforward.py --regime <t> --vol <v> --vol-labels <head labels>` on the **2-D** cell returns `<dir>_stable_drag` (pooled < 0 AND a strict majority of folds negative under EVERY member of `FOLD_PANEL = (3, 4, 5)`), not `*_fold_sensitive`, for the direction the cell gates, with trades > 0 in that direction. The run uses the full cost stack (`resolve_run_costs`).
- **Book rule:** the gated book (all passing cells together) vs ungated, yearly folds: net ≥ ungated in ≥ 3 of 4 folds AND pooled maxDD ≤ ungated. ⚠️ The 07-06 ETH fixed-cell read was net 4/4, maxDD 2/4. A maxDD regression is now a FAIL, not a footnote.
- **Promote:** `promote-stage <head> --new-stage advisory` plus the passing cells in `config/regime_policy.yaml::trend_vol`, as one Tier-3 PR.
- **Demotion:** remove a cell when its weekly walk-forward re-run (ml-review C6) stops being `stable_drag`; demote the head when drift is persistent on 2 consecutive weekly reads (ml-review C7, then `drift-remediation`), or when live parity fails.

### P3: BTC cells, re-verify and extend
- **Re-verify:** each of the 6 authored cells under the current `btc-regime-15m-lgbm-fc-pcv-v2`, with the P2 cell rule. A cell that is no longer `stable_drag` gets a Tier-3 **removal** proposal. That is de-risking: it unblocks trades the evidence no longer supports blocking.
- **Extend:** each candidate cell for `htf_pullback_trend_2h`, `fade_breakout_4h`, `turtle_soup` and `fvg_range_15m`, under the P2 cell and book rules, after Rule 1 is checked (an all-folds-profitable book gets no cell).
- **Demotion:** as P2.

### P4: conviction-meta size multiplier (stretch)
- **PROMOTE iff** the dataset is rebuilt with every row stamped `realized` (PI-20261028-V8KBRR5H-0002), AND the cost gate passes, AND the bootstrap rule (b) of P1 holds, AND ECE ≤ 0.05 on the eval rows (`ece_with_read_state` = `ok`). Size effect is reductive only: the multiplier is ∈ [0.5, 1.0].
- **Demotion:** as P1.

### P5: exit head (incumbent)
- **KEEP iff**, on the paths corpus for the 3 legs (`--emit-paths`, the six-money-leg corpus extended to `trend_donchian_eth` / `_sol` 1h), replaying the head at threshold 0.1 vs B0 (the leg's own exits) gives Δ net R/trade ≥ 0 with the 95% trade-clustered CI lower bound > −0.02 R, net of cost.
- **Else** a Tier-3 de-risking proposal: `exit_head_action` → annotate (log only) on the failing legs. This is data-backed de-risking, so the manager may ship it and notify.
- **Registry:** register the artifact as a registry row (family `exit_candidates`, stage `advisory`, with its export provenance), so the ladder, the drift scan and the cost gate see it.

---

## 4. Build steps, in order: who, cost, Tier

Lanes are plan sessions (no API credits). The ceilings are per-lane dollar caps on plan usage, sized from comparable lanes (ML-PROGRAMME § 2.3: $2.45–$10.44).

| step | what | lane (row) | model · ceiling | Tier | depends on |
|---|---|---|---|---|---|
| **B1** | **Cost-net rebuild** (PI-20261028-V8KBRR5H-0004) + **label provenance for the real-trade rows** (MVBJLVJ3-0001: initial-risk R): build `setup_candidates/all/all/v022` (v020 params, current builder) on the trainer, and `exit_candidates` for the 1h Donchian legs; add manifest `setup-candidates-metalabel-p2pool-v2.yaml` (`research_only`); train it out of cycle; read `cost_gate.json`; compute § 3 P1 (b)–(d) with `scripts/ml/` (new helper, Tier 1); re-gate the other 8 setup heads on v022 for the record. Then P4: restamp/rebuild `conviction_meta` and re-gate | `ML-P1-COSTNET-REBUILD` | Sonnet · $8 | 1 (non-live trainer build; new research_only manifest) | — |
| **B2** | **Serve feature builder:** in `advisory_sizing._feature_row_from_pkg`, merge the setup-candidates decision-time row (the `market_features` candle features + `direction`, `symbol`, `vol_bucket`, `momentum`, computed by the **same** functions the dataset family uses) from the leg's 1h candles; a parity test that runs both builders over the same bars; a guard test that fails if any `advisory_policy.mode: downsize` leg is rostered on a real-money account | `ML-SERVE-SETUP-FEATURES` | Opus · $12 | **2** (order-path code; held PR, manager merges after one operator OK) | — (parallel to B1) |
| **B3** | **Vol-label replay + 2-D walk-forwards:** `ml_vol_label_replay` for the 2 ETH heads and the BTC advisory head (trainer); `regime_cell_walkforward.py` on every P2/P3 candidate cell with the full cost stack; one evidence record per cell | `ML-VOLGATE-WF-ETH-BTC` | Sonnet · $10 | 1 | — (parallel) |
| **B4** | **Exit-head decision value:** replay `exit-head-donchian-1h-v1` on the paths corpus for the 3 legs vs B0 (§ 3 P5); register it as a registry row | `ML-EXITHEAD-VALUE` | Sonnet · $8 | 1 (the registration is a registry write on the trainer; stage `advisory` mirrors the live fact) | B1's `exit_candidates` build (or the paths corpus, whichever lands first) |
| **B5** | **Deploy B2** (operator OK), then **candidate → shadow** for P1 if it passed (autonomous, `model-training`) | manager | — | 2 (deploy) · 1 (shadow) | B1 PASS, B2 merged |
| **B6** | **Parity + serve check** (ml-review C5) on the first live shadow rows of P1 (and of the P2 head, already in shadow): `GET /api/bot/shadow/predictions` diffed against v022 on the same bars; `gate-check` | `ML-PROMO-PARITY` | Sonnet · $5 | 1 | B5 |
| **B7** | **Tier-3 packets:** one PR per passing candidate (`promote-stage … advisory` plus its `strategies.yaml advisory_policy` or `regime_policy.yaml` cells), each with its evidence record, rule, n, cost basis and one-line revert | manager | — | **3** | B3/B6 PASS |
| **B8** | **Post-flip verification:** `/api/bot/config` shows the policy/cells; first annotated/vetoed package in `advisory_decisions.jsonl` or `regime_shadow_gate`; graded | `ML-PROMO-PARITY` (same row) | — | 1 | B7 |

**The one-line reverts:** P1 `promote-stage setup-candidates-metalabel-p2pool-v2 --new-stage shadow` (stage alone gates WS7). P2/P3: delete the cell lines from `trend_vol`. P2 head: `promote-stage <eth head> --new-stage shadow`. P4: `CONVICTION_SIZING_MODE=annotate`. P5: `exit_head_action` removed (annotate).

---

## 5. Day by day (UTC)

| day | work | output | operator |
|---|---|---|---|
| **Wed 10-28 (tonight)** | this plan; rules registered (§ 3); rows filed; relays #21020/#21021 read | this PR | — |
| **Thu 10-29** | dispatch **B1**, **B2**, **B3** in parallel at the 06:17Z planning session. The trainer cycle runs 00:52Z, so B1 runs after it (load is lowest then) | B1: v022 built, p2pool-v2 trained, `cost_gate.json` + bootstrap read → P1 PASS/FAIL/INDET. B3: vol labels replayed, walk-forwards fired | — |
| **Fri 10-30** | B3 verdicts land; **B4** starts; B2 PR green → **Tier-2 OK asked**; on OK, **B5** deploys B2 and moves P1 to shadow if it passed | per-cell verdicts (P2/P3); P1 at shadow | **Tier-2 OK: deploy the serve feature builder (B2)**, by ~14:00Z |
| **Sat 10-31** | **B6** parity on P1's and the ETH head's live shadow rows (1–2 clean scored predictions); B4 verdict; **B7** packets prepared | parity record; P5 KEEP/annotate verdict; Tier-3 PRs (held) | **Tier-3 packets sent** (one popup listing each, with its record) |
| **Sun 11-01** | daily sync: the operator approves or declines each packet. Under the data-backed authorization, a cleanly passed rule can ship without waiting, with an immediate notification | approved flips merged and deployed | **Tier-3 approvals** (each packet: approve / decline) |
| **Mon 11-02** | **B8**: post-state verified, first live ML decision on each promoted leg observed and graded | `merged / deployed / observed` per model | — |

---

## 6. ML infra/ops validation and extension (each item is a MODEL row)

| id | what to prove or build | done when | tier · lane · ceiling |
|---|---|---|---|
| **I1 `ML-E2E-CHAIN-PROBE`** | one traced instance of every hop for one live consumer (the BTC router): data (candles) → label (vol) → train (last cycle row) → score (`shadow_predictions` row for that bar) → serve (the `regime_shadow_gate` audit row with `vol_gated: true`) → **an intent dropped** → graded (the dropped intent's counterfactual R from the harness). Then the same for P1 after B8 | a committed trace record per consumer, with every hop's locator; a missing hop is a finding row | 1 · Sonnet · $6 |
| **I2 `ML-LEARNING-LEDGER`** | build `scripts/ops/ml_learning_ledger.py` (absent, MEASURED): per source, hops H1–H7 of ML-PROGRAMME § 7 with counts and read-states, weekly record; it feeds ml-review C4 | the first ledger record lands, with every hop either a number or `could_not_look` | 1 · Sonnet · $8 |
| **I3 `ML-TRAINER-TIMER-PROOF`** | the timer fires (last 00:31Z, next 00:52Z), but the 08:22Z cycle shows `trained: 0, already_done: 72`. Prove the nightly retrain actually retrains: per manifest, last trained-at ≤ 26 h, and 5 stale + 2 never-trained resolved or retired. An invariant alerts when `trained == 0` on the first cycle of a day | an invariant in `scripts/ops/system_invariants.py`, plus one observed nightly cycle with trained > 0 | 1 · Sonnet · $5 |
| **I4 `ML-REGISTRY-LADDER-GAPS`** | (a) the legacy `status` field reads `candidate` on all 97 rows while `deployment_bucket` holds LIVE/SHADOW/OFFLINE: list every reader of `status` and move it to the canonical stage; (b) the exit head acts on 3 legs with no registry row (B4 registers it); (c) the BTC 15m variant cap (ML-PROGRAMME § 3.2): retire variants with no consumer | readers fixed or listed; the exit head in the registry; the cap applied | 1 · Sonnet · $6 |
| **I5 `ML-DRIFT-ALERT-E2E`** | prove a drift or decay signal reaches someone: the plan-only drift scan in ml-review (rc/empty-log → could-not-look), `GET /api/bot/shadow/drift` for the 3 advisory heads plus the promoted ones, and the `LIVE-DECAY-MONITOR` row (queued) extended to every advisory head's decision value (CUSUM on vetoed-vs-taken R) | one alert observed end to end (a synthetic drift fixture through the real alert path, or a real one) | 1 · Sonnet · $6 |
| **I6 `ML-ADVISORY-SCOPE-GUARD`** | a CI guard: no `advisory_policy.mode: downsize`, no `trend_vol` cell and no `exit_head_action: close` on a strategy rostered on a real-money/prop account unless the PR carries a Gate-2 evidence record path. It keys on roster membership (CLAUDE.md: CI is asymmetric) | guard green on main, red on a fixture | 1 · Sonnet · $4 (rides B2's lane if cheaper) |
| **I7 `ML-SHADOW-NEVER-ORDERS`** | prove that `shadow` never changes an order: the conviction stamp reads **shadow** models and resizes in `apply` mode (audit § 1b). With `CONVICTION_SIZING_MODE` live (#21021), a shadow promotion (B5) could change size. Measure, and if so make the conviction lens read `advisory` only, or record the exception explicitly | a test asserting that a shadow-only model set yields factor 1.0 on every path, or a recorded operator decision | 2 if code changes · Opus · $8 |
| **I8 `ML-CONSUMER-LIVENESS`** | an invariant: each advisory head that a consumer reads is scored ≥ 1× per 24 h on each leg it can change (router audit rows, `advisory_decisions.jsonl`, exit-head rows), so a head that silently stops scoring (the ETH `xa` all-zeros class, exit-head `not_scored`) is caught | the invariant is live and red on a fixture | 1 · Sonnet · $5 |

Already owned elsewhere, not duplicated: `LIVE-DECAY-MONITOR` (CUSUM per leg), `ML-REGIME-15M-DRIFT` (drift-remediation of the 15m heads), `ML-HYGIENE` (constant-score baselines), `METALABEL-EMIT-FEATURES` (wider meta-label features), PI-20261028-V8KBRR5H-0001/-0002/-0003 (cost gate not applicable to regime heads; unstamped conviction rows; degenerate R at near-zero vol, which B1 must check on v022).

---

## 7. Risks, premortem

- **The rebuild changes the eval book.** v022 adds the real trades closed since 2026-08-04, so the +0.041 point estimate will move. That is the point. The rule was registered before the rebuild.
- **Small taken-n.** About 42 taken trades at n = 324. Rule (b) is a bootstrap on the difference, so a lucky 42 cannot pass on a point estimate alone.
- **`unit_fallback` R.** Real trades with no stop/size in the journal get ±1R. The ≤ 10% assertion catches a book that is mostly proxy.
- **Shadow is not inert today** (I7). Check `CONVICTION_SIZING_MODE` before B5.
- **Walk-forward harness fidelity.** The pullback/trend harness `tp_r` assertion bug class (`regime_debt_matrix.py` docstring). B3 reads each harness's fidelity flag and refuses an unfaithful leg.
- **Trainer capacity.** 0 spare OCPU p95 (ML-PROGRAMME § 2.1). B1 runs one build plus one train after the 00:52Z cycle. The walk-forwards run on runners where possible.

## 8. Relay results (filled at landing)

_See § 8 below; updated when #21020 / #21021 return._
