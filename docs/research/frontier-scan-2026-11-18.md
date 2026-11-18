# Frontier scan 2026-11-18 (lane ML-FRONTIER-PREP-20261118)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Run record: `comms/ml-plan/20261118T2000Z-ML-FRONTIER-PREP.json`.

Gates this adds or changes: none.

**Operator focus this week (2026-11-18):** (1) a live ML at every decision step D1–D10; (2) a deep iteration plan per model
family that covers labels, features and stronger families; (3) frontier research feeding both. This scan answers (2) and (3)
on the family side. The week plan (`docs/plans/ml-week-plan-2026-11-19.md`, lane ML-PRIMARY-5) consumes it.

## 1. Where we are: the family evidence is all on one kind of label (MEASURED)

| read | population | figure |
|---|---|---|
| `ml_plan_status.py --diversity` | open family-tagged plan items | gbdt 13/17 (CONCENTRATION) |
| same | registered models (registry, 108 rows) | gbdt 79/108; 8 served order-changing models `UNMAPPED:None` |
| units with a `tabicl`/`tabpfn`/`torch_gru`/`sklearn_mlp` arm (grep of `research/queue`) | 27 units | **27/27 targeted `regime_label` or `direction_label`** |
| `ml_bakeoff` results generated 2026-11-11T20Z..11-18T20Z | 18 units | **18/18 targeted `regime_label` or `direction_label`** |
| tabular-FM arms (65cc-06/07/08, ff8f-02, 4a3b-01, 38be-01, eda2-02) | 7 units | none ran at full n on a GPU: TabPFN `unavailable` (CPU cap 5,000 rows) or timed out; TabICL capped at 3–12k rows |
| linear/blend on a MONEY label (D3 net R) | 2 units | ridge FAIL (4654-09, paired −0.1001 R, k 10); LGBM+ridge INDETERMINATE (4654-07, +0.0195 R, CI [−0.104, +0.143], k 13, n 3,556) |

**What this shows.** "Trees win" is established only on the D2 vol-regime and direction targets: GRU loses on D2 yz
(c21d-05 FAIL, powered), MLP loses on 1h regime and direction log-loss (a142-01, ed1c-31, 98e3-10 FAIL), and CatBoost beats
LightGBM on D2 yz (dc44-02 PASS). The same claim is **untested** for every learner except ridge on the labels that change an
order (D3 net R, D4 meta-label, D6/D7/D8 first passage). A FAIL closes only the configuration tested. So the
deep/sequence/foundation-model families are not dead. They have mostly been asked the wrong question.

**What it does not show.** Whether a stronger family would pay on a money label. That is the test below.

## 2. Sources checked (F3)

| source | state | read |
|---|---|---|
| Hugging Face Hub (model cards and licences: TabPFN-v2/2.5, TabICL, Chronos-2, TiRex, TimesFM-2.5, Moirai-2.0, Toto, Kronos, Mitra, TTM-r2; paper search "financial time series foundation model") | checked | Hub fields |
| arXiv: 2602.11139 TabICLv2 (PRIMARY abstract); 2607.05291 Brini, TSFM vs HAR for realised vol (PRIMARY abstract); 2606.27100 Noguer i Alonso & Franklin, TSFMs for returns (PRIMARY abstract); 2511.18578 Rahimikia et al., TSFMs in finance (PRIMARY abstract); 2606.00060 Bysik & Ślepaczuk, ML BTC trading under costs (secondary summary) | checked | abstracts |
| Lab releases (Amazon Chronos-2 Apache-2.0; Google TimesFM-2.5 Apache-2.0; Salesforce Moirai-2.0 cc-by-nc-4.0; NX-AI TiRex licence other; Datadog Toto Apache-2.0; IBM TTM-r2 Apache-2.0; Prior Labs TabPFN licence other; Tsinghua Kronos MIT) | checked | Hub licence fields |
| Quant practitioner literature (TabArena-state write-up, mindfulmodeler substack, secondary; offline RL for exits, no 2026 finance benchmark found) | checked | summaries |
| GitHub / competitions | not this week (every-other-week row; checked 2026-11-11) | — |

Vendor benchmark ranks (TabArena, GIFT-Eval) are **self-reported**. They justify a test, never a conclusion.

## 3. Ranked frontier families (EV per cost; p = prior to PASS its first registered test)

| # | family / candidate | licence (primary) | decision slot | why it could beat the incumbent | cost to verdict | p | disposition |
|---|---|---|---|---|---|---|---|
| 1 | **CatBoost** (ordered boosting) on the D3 money label, plus the LGBM+CatBoost+ridge blend | Apache-2.0 | D3 Foxhound (then D4 Beagle) | it beat LightGBM on D2 yz (dc44-02); ordered boosting reduces prediction shift on small, noisy targets; servable on CPU | free runner, ~2.5 h | 0.30 | **KEPT → `RQ-20261118-dbf8-01`** (runnable; harness arm added) |
| 2 | **TabICLv2** in-context tabular FM at full n | BSD-3-Clause (Hub card `jingang/TabICL`) | D3, then D4 | reported SOTA over tuned GBDT on TabArena/TALENT (author-reported); never tested by us at full n or on a money label | Kaggle GPU; blocked on a lever | 0.20 | **KEPT → `RQ-20261118-dbf8-02`** (blocked on `FRONTIER-LEVER-TABULAR`) |
| 3 | Heterogeneous stack (LGBM + CatBoost + ridge + TabICL), extending 4654-07 | — | D3 | 4654-07's mean is positive (+0.0195 R) but underpowered | reuses #1/#2 arms | 0.25 | covered by dbf8-01 `ens3` (reported); a decided stack unit follows #1/#2 |
| 4 | **Mitra** tabular FM (regressor) | Apache-2.0 | D3 net R | a licence-clean tabular FM beside TabICL; TabPFN stays research-only | needs a learner kind in `ml_bakeoff`/harness | 0.15 | idea → `FRONTIER-Q-MITRA-ENTRY` (after #2 lands its GPU route) |
| 5 | Distributional heads (quantile LightGBM / NGBoost + conformal) over the first-passage grid | Apache/MIT | D6 Pointer, D7 Labrador | Pointer v0 failed twice with a point-TP recipe (82fd-01, a474-01); the lever is the distribution, not the tree | free runner, TM-BENCH | 0.15 | idea → `FRONTIER-Q-DIST-POINTER` (the D6 iteration's next lever) |
| 6 | TSFM as a frozen feature or quantile source: **TTM-r2** (805K params, CPU) and **Chronos-2** (covariates) | Apache-2.0 | D2 vol, D6 brackets | Brini 2026: only TTM beats Log-HAR across 50 assets, and the TTM+Log-HAR equal-weight blend is the robust choice | trainer CPU | 0.15 | idea; **after** the D2 label parity fix (PI-20261118-ZZUFKM1F-0001). D2 is crowded (C8) |
| 7 | Domain-pretrained financial sequence model: **Kronos** fine-tuned on our 60-perp archive | MIT | D3 | Rahimikia et al.: off-the-shelf TSFMs poor on finance, domain pretraining strong; no independent Kronos replication found | Kaggle GPU, high | 0.08 | deferred until #1/#2 read; re-rank then |
| 8 | Offline RL / conservative fitted-Q | — | D7/D8 | ml-tm-action-value FAILed 5 iterations; the binding lever there is label/horizon (aadc-12 PASS shows label work pays: holding_pays_neg25 +0.0160 R/trade, deflated CI LB +0.0063 on held-out symbols) | high | 0.05 | dropped this week (gate 6: no powered design over the existing action-value failures) |

**Dropped:** Moirai-2.0 (gate 4, cc-by-nc-4.0); TabPFN-2.5/3 for serving (gate 4, licence `other`; research arm only);
more GRU/MLP on regime labels (closed configurations; a variation, not a test); zero-shot TSFM return forecasting
(Noguer i Alonso & Franklin 2026: gains over a random walk are small and sparse; gate 5, no decision changes on it);
TiRex (licence `other`, unread terms; re-check next scan).

## 4. Practice delta (MODEL track)

- **Cost-aware conversion beats model choice** (Bysik & Ślepaczuk 2026, secondary): on hourly BTC over 27 walk-forward
  folds, XGBoost was at least as good as LSTM/iTransformer, and a forecast-exceeds-cost threshold restored profitability
  where sign trading lost to a 10 bps cost. This strengthens practice principle M6 (decision value net of cost). It argues
  for keeping the D3 tau/cost-per-R lever (c21d-01 FAIL at tau 0.30; the 7e18-02 decomposed score is INDETERMINATE) beside
  family breadth.
- **TSFMs in finance are a prior, not an alpha engine** (2606.27100, 2511.18578, 2607.05291): use them as a feature or
  quantile source next to an econometric baseline (HAR), never as a stand-alone return forecaster.

TRADING track: none this week, because the lane's time-box went to the family question the operator named. The sources it
checked are listed in § 2. The previous refresh's gaps carry forward unchanged in the run record.

## 5. Prior scan graded (Step 0)

| prior keep/drop | call | grade | evidence |
|---|---|---|---|
| K1 market-residual ENTRY target (kept, p 0.15) | kept | **hit** (informative FAIL at the registered design) | RQ-20261112-4654-01 FAIL: paired resid−raw −0.066 R, k 13 |
| FRONTIER-LEVER-TABULAR / -TSFM-TIMESTRAL (dropped pending levers) | dropped | unresolved | both rows still `queued` (since 10-23 / 10-25): **raised to the manager as the blocker** |
| path-signature in-trade (kept, blocked) | kept | miss (still blocked) | behind RQ-20261112-3144-02 |
| regime/direction learner variants (dropped, 3rd week) | dropped | hit | this week 18/18 bake-offs were still on those labels, and the D2 results added no decision value |
