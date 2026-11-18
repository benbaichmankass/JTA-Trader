# ML week plan, Thu 2026-11-19 to Sun 2026-11-22 (unattended run)

> **Doc status:** `unknown` · category `plan` · last verified `2026-11-18` (state read from graded results on `main` and a dry run of `scripts/research/dispatch_queue.py --json` at 2026-11-18 ~18:20Z) · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Checklist row:** `ML-WEEK-PLAN-1119` · lane ML-PRIMARY-5 (session_01AFoLuMFLP9yi6gZzUfKM1F), dispatched by Manager Session 2026-11-15a · Tier 1, planning · track **MODEL**.

**Gates this adds or changes: none.** Every task below is a research unit, a checklist row or a pipeline item with its own registered rule. This page lists them and their order. It authorizes nothing.

The operator is away Thu 11-19 to Sun evening. The ML lane runs unattended under the standing rule (data-backed Tier-2/3 decisions ship; demotions wait for the operator). The operator's priorities, in order:

1. A live ML model at every decision step D1–D10, across all accounts.
2. A deep iteration plan per model family: labels, features, and stronger families.
3. Frontier research feeding both.

## 0. Where we are (MEASURED unless marked)

**Queue runway (dry run, 18:20Z).** 25 runnable units, all on `github_runner`. Every other backend has nothing runnable:

| backend | runnable units |
|---|---|
| github_runner | 25 |
| trainer | 0 |
| Kaggle CPU | 0 |
| Kaggle GPU | 0 |
| HF | 0 |

Section 4 fills these.

**Model families in use.** One L2 logistic regression (D4 Beagle-1). Everything else is LightGBM. The exception is one GRU challenger (D2, `RQ-20261117-c21d-05`, Kaggle GPU).

**Infrastructure defects that stop the loop.** These come first; nothing below runs reliably without them.

| ref | defect | effect | owner |
|---|---|---|---|
| `PI-20261118-JFWRQYOV-0001` | `research-queue-dispatch` cron not firing; schedule-keeper only runs on pushes | nothing dispatches or collects on a quiet main (2.6 h stall 11-18) | manager |
| `PI-20261115-PWMQY8LM-0001` | runner holdout claims never land in the repo ledger | deflation undercounts n_tries (aadc-10 read at aadc-02's percentile) | ML-PRIMARY |
| `#26781` (merged 11-18) | re-armed unit with a lost run read as "already dispatched" for 48 h | **fixed and observed** (aadc-01 fired 07:58Z) | done |

## 1. Slot by slot: live state, this week's tasks, dependencies, owner

"Live" means an ML artifact that changes an order on some book: real money or the demo floor. A shadow log is not live.

### D1 Universe and book: a rule, on purpose

- **Live now:** the promotion ladder (rule). No learned leg selector at about 51 legs.
- **This week:** none.
- **Re-entry test:** `ML-LINE-S1-CORPUS`, at least 30 legs with Stage-0 records on one cost basis.
- **Owner:** n/a.

### D2 Regime gate (Collie)

- **Live now:** 3 advisory vol heads (BTC and SOL fc-pcv-v2, MES v2). The BTC trend_vol off-cells act on bybit_1.
- **Blocking finding:** `RQ-20261117-aadc-01` FAIL. The trainer-replayed labels are not the live labels: BTC κ 0.24 (agreement 0.937, n 1,111); SOL κ 0.51, agreement 0.77 (n 676).
  - Every D2 money test so far (bcd2-01, b819-01) graded the replay population. Their grading blocks now say so.
- **Tasks:**
  1. **Serve-path diff** (`PI-20261118-ZZUFKM1F-0001`; build, runner, ~1 day).
     - On the disagreeing bars, rebuild the live feature row from the committed audit snapshot.
     - Diff it against the v002 row, with the p delta attributed by feature block (`fc_*` first).
     - Owner: ML-PRIMARY.
  2. Fix whichever side is wrong (replay builder or live path). **Re-run aadc-01** (trainer, ~1 h). Owner: ML-PRIMARY.
  3. On PASS, re-run the cell money test on live-reproducible labels (b819-01's rule, trainer). Owner: ML-PRIMARY.
  4. **yz heads for ETH and SOL** (`ML-D2-YZ-HEADS-ETH-SOL`; c21d-03 PASS, yz beats v2 on both). Owner: refill lane.
- **Dependencies:** task 3 needs task 2. No live D2 change ships before the labels match.

### D3 Entry generation (Foxhound)

- **Live now:** Foxhound-1 on real money (tau 0.10); Foxhound-2 on demo.
- **Graded:** `2e3b-01` FAIL at per-symbol cost (−0.068 R/decision, n 12,746).
- **Open:** `c21d-01` (tau 0.30, held-out year) and `c21d-06` (ATR-neutral and gross-minus-cost targets).
- **Tasks:**
  1. Grade c21d-01 and c21d-06 as they land. Owner: refill lane.
  2. **Cost-aware ranking label** (new unit, trainer). LightGBM LambdaRank on net R within each decision bar vs the live binary classifier. Same folds and per-symbol cost. Owner: ML-PRIMARY.
  3. **Tabular-transformer challenger** (new unit, Kaggle GPU). FT-Transformer on the Foxhound features vs live, same held-out year. Owner: ML-PRIMARY.
- **Dependencies:** none. A real-money change needs a pass on the held-out year (data-backed Tier-3).

### D4 Signal filter (Beagle)

- **Live now:** Beagle-1 (logistic, TD family, reduce ×0.5) on real money.
  - The EV-threshold challenger shadow-logs; first live rows were OBSERVED 11-17 23:13Z.
  - The forward read `cc86-02` is at 0 of 60 disagreements.
- **Blocking defect:** `PI-20261117-ZZUFKM1F-0002`.
  - TD trade parity vs the 09a6-01 reference corpus is 0.09–0.85 on all four gate legs.
  - So every TD overlay read is INDETERMINATE (cc86-01, aadc-03).
  - Separately, `cpcv_challengers` drops the family INDETERMINATE.
- **Tasks:**
  1. **Name the parity cause** (runner, ~half a day): strategy-code change since 10-24, or data/fetch.
     - Re-pin the reference with a disclosed record, or fix the harness.
     - Patch the record writer. Owner: ML-PRIMARY.
  2. **Re-run aadc-03** (tail1r / evweight targets) on a parity-clean corpus (runner). Owner: ML-PRIMARY.
  3. **Feature-family arm** (aadc-03's fail_action): the path_state block, made live-computable in `overlay_features` first.
     - This is a build plus a unit (runner). Owner: ML-PRIMARY.
  4. **Monotone GBM challenger** (new unit, runner). LightGBM with monotone constraints on the Beagle features, same CPCV. Owner: ML-PRIMARY.
- **Dependencies:** tasks 2–4 need task 1.

### D5 Position aggregation: a rule

- **Live now:** slices / election.
- **Graded:** `a474-02` FAIL. The re-entry trigger is filed (`PI-20261117-ZFRREVN5-0001`).
- **This week:** none. **Owner:** n/a.

### D6 Bracket at entry (Pointer)

- **Live now:** nothing. ml_entry uses a fixed SL 2 / TP 3 ATR.
- **Graded:** v0 and bracket-by-cell FAIL; they move many trades for about zero.
- **Open:** `c21d-02` (static TP 4 ATR), refill lane.
- **Tasks:**
  1. **Distributional TP head** (new unit, trainer).
     - LightGBM quantile models of forward MFE and MAE.
     - TP at the predicted 60th-percentile MFE, SL unchanged.
     - Held-out year, per-symbol cost. Owner: ML-PRIMARY.
- **Dependencies:** none. A pass is a data-backed Tier-3 change for ml_entry's bracket.

### D7 In-trade management (Labrador)

- **Live now:** Labrador-1b (TP extend-only, ml_entry).
- **Graded:** tm-action-value iterations 1–5 and `c21d-04` all FAIL S-OFFLINE.
- **Tasks:**
  1. **Fitted-Q baseline** (new unit, trainer). Fitted-Q iteration on the same action grid and cost stack, with holdbias labels (`ML-EXIT-ACTIONGRID-LABELS`).
     - This is a family step up from one-step action values. Owner: ML-PRIMARY.
- **Dependencies:** the action-grid labels row.

### D8 Exit now (exit-head-donchian-1h)

- **Live now:** exit-head-donchian-1h-v1 (advisory) closes trades on trend_donchian, _eth and _sol (bybit_1 demo floor).
- **Graded:**
  - `aadc-11` PASS, dev: margin −0.25 label, +0.0134 R/trade.
  - `aadc-12` PASS, five held-out perps: +0.0160 R/trade, CI [+0.0063, +0.0256], n 18,649; vs hold +0.026.
- **In progress (manager GO, data-backed Tier-3, 2026-11-18):**
  1. Target change; self-landing PR, branch `claude/ml-primary-5-exithead-neg25`.
  2. Export `exit-head-donchian-1h-v2-neg25` to the trainer mirror. It scores in shadow beside v1, because only the pinned artifact closes.
  3. HELD PR switching `exit_head_model` on the three legs. Revert: pin back to `exit-head-donchian-1h-v1`.
- **This week after the switch:**
  - Observe the first v2 score and the first v2-driven close.
  - Then a population test widening to the 4h donchian legs (new unit, trainer).
- **Owner:** ML-PRIMARY.

### D9 Execution (Whippet)

- **Live now:** nothing (baseline only).
- **Graded:**
  - Maker exit W 5 (`aadc-02`) and W 1 (`aadc-10`) both FAIL: net about +0.002 R per exit, lower bound below 0.
  - At W 1 the unfilled loss shrank from −18 to −7 bps, but the fill rate fell from 0.72 to 0.54.
- **Tasks:**
  1. **Mid-price peg arm** (build in `ml_entry_maker_replay.py`, ~half a day, then a runner unit). Owner: ML-PRIMARY.
  2. **Fill-probability model** (new unit, runner). Logistic and LightGBM on spread, short-horizon volatility and order-flow imbalance proxies from 1m bars.
     - Policy: post maker only when P(fill) × filled gain exceeds (1 − P(fill)) × unfilled cost.
     - This is the learned step D9 lacks. Owner: ML-PRIMARY.
- **Dependencies:** task 2 uses task 1's replay.

### D10 Review and grading (Basset)

- **Live now:** nothing.
- **Graded:**
  - Page-CUSUM baseline detector PASS (`aadc-05`, AUC 0.654).
  - The alarm action failed fresh-window confirmation (`aadc-09`).
- **Tasks:**
  1. **Learned degradation score** (new unit, Kaggle CPU or runner). GBM on rolling leg stats predicting P(next-20 net R < 0).
     - It must beat AUC 0.654 on the same leg-cluster bootstrap. Owner: ML-PRIMARY.
  2. **CJ-LABEL-ALTERNATIVE** (its 19:00Z trigger, carried over). Owner: per its row.

## 2. Iteration plan per model family

Each line is one factor against the incumbent on the incumbent's harness, folds and cost stack.

| family (slot) | labels next | features next | stronger model next | compute |
|---|---|---|---|---|
| Collie (D2) | live-reproducible labels first (above) | yz realized-vol block (PASS on ETH/SOL); TS-foundation embeddings (Chronos-Bolt) as a block | GRU (c21d-05), then a small temporal transformer (PatchTST) on 1h bars | Kaggle GPU; HF for model weights |
| Foxhound (D3) | net-R ranking (LambdaRank); gross-minus-cost (c21d-06) | per-symbol cost as a feature; funding / basis | FT-Transformer; TabPFN-v2 as a fast tabular baseline (key on the trainer) | trainer (TabPFN), Kaggle GPU (FT-T) |
| Beagle (D4) | tail1r / evweight (re-run on clean corpus) | path_state block (live-computable first) | monotone LightGBM; then GBM ensemble (LGBM + CatBoost averaged) | runner |
| Pointer (D6) | forward MFE/MAE quantiles | same as Foxhound | quantile LightGBM; NGBoost (distributional) | trainer |
| Labrador (D7) | holdbias action-grid labels | time-in-trade, MFE-so-far | fitted-Q iteration (offline RL baseline) | trainer |
| exit head (D8) | margin −0.25 shipped; next more_mfe (needs `peak_is_in` emitted by the row builder) | exhaustion block (`--features extended`) | sequence model over the trade path (GRU on bar-by-bar open_r) | trainer / Kaggle GPU |
| Whippet (D9) | fill / no-fill and filled gain | spread, short-vol, imbalance proxies | logistic, then LightGBM | runner |
| Basset (D10) | next-20 net R < 0 | rolling leg stats, regime, cost drift | GBM, then a survival model (time to drawdown) | Kaggle CPU |

**Rules that bind every line:**

- One factor per unit, registered before the run.
- Paired against the incumbent on identical splits.
- Every arm counted in the deflation.
- Net of the full cost stack.
- No unit without a diagnosis behind it (STOP-GENERATED-AUTHORING).

## 3. Frontier research feeding both

These are three bounded scans. Each kept idea becomes a queue unit with a declared baseline. Owner: the weekly `frontier-research` lane, with these named inputs.

1. **Time-series foundation models as feature extractors.** Chronos-Bolt and TimesFM embeddings for the D2 regime block and the D8 trade-path block. Check point-in-time safety and latency first. Compute: HF weights, Kaggle GPU inference.
2. **Tabular deep learning against GBMs.** TabPFN-v2, FT-Transformer and TabM on D3/D4 features. Our n is about 10k–20k per slot, where these are competitive.
3. **Offline RL for in-trade management.** Fitted-Q, then CQL/IQL, on the D7 action grid. The baseline is the S-OFFLINE rule.

## 4. Units to author tonight and Thursday (fills trainer and Kaggle)

Each needs a registered rule and pytest before landing.

| # | slot | unit (one factor) | backend | est |
|---|---|---|---|---|
| 1 | D3 | LambdaRank net-R label vs live classifier | trainer | ~2 h |
| 2 | D3 | FT-Transformer vs live, held-out year | Kaggle GPU | ~2 h (estimate) |
| 3 | D6 | quantile-MFE TP head | trainer | ~1.5 h |
| 4 | D7 | fitted-Q baseline on the action grid | trainer | ~3 h (estimate) |
| 5 | D8 | v2-neg25 on the 4h donchian legs (population widening) | trainer | ~2 h |
| 6 | D10 | learned degradation score vs AUC 0.654 | Kaggle CPU | ~1 h |
| 7 | D4 | monotone LightGBM vs Beagle-1 (after the parity fix) | runner | ~1 h |
| 8 | D2 | aadc-01 re-run (after the serve-path fix) | trainer | ~1 h |

**Runway through Sunday night (estimate):**

| backend | queued |
|---|---|
| github_runner | 25 queued now, plus #7 |
| trainer | about 11 h (#1, 3, 4, 5, 8) |
| Kaggle GPU | about 2 h (#2), plus c21d-05 |
| Kaggle CPU | about 1 h (#6) |
| HF | none |

**The trainer runs units serially**, so these alone do not fill four days. Each graded result authors its follow-up within 24 h (`PI-20261117-ZFRREVN5-0004`), which is what keeps the queue fed.

## 5. What would block on the operator (pre-clear tonight)

1. **Real-money promotions from D3/D6.** Data-backed Tier-3 under the standing rule once a held-out pass lands; no click needed. Listed so the operator knows they may ship while away.
2. **Demotions.** Wait for the operator by rule. None are planned. If a live model fails a monitoring read, the plan files it and does not demote.
3. **HF paid compute.** Spending on HF GPU (Spaces or Inference Endpoints) would be new spend. Default: use HF only for free weight downloads and run on Kaggle GPU. Needs a popup if the operator wants paid HF GPU.
4. **D4 challenger swap.** A Tier-3 swap of the TD overlay artifact needs the cc86-02 forward read (60 disagreements), which will not accrue by Sunday. Nothing to pre-clear; stated so it does not look stalled.

Nothing else in this plan needs a click.
