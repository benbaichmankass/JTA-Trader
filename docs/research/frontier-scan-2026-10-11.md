# Frontier scan #1 — better models and strategy ideas (2026-10-11)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

First run of the weekly scan defined in [`.claude/skills/frontier-research/SKILL.md`](../../.claude/skills/frontier-research/SKILL.md).
Operator directive (2026-10-11): don't let early choices cap the project; test genuinely different things.
**This file is evidence for the units it names — it is not work. The work is the units
(`research/queue/blocked/RQ-20261011-9da8-01..07`) and checklist row `FRONTIER-RESEARCH`.**

## 1. Where we stand (MEASURED 2026-10-11)

`python3 scripts/ops/ml_plan_status.py --diversity` over `GET /api/bot/ml/registry` (96 models):

| family | registered | live/shadow (28 total) |
|---|---|---|
| gbdt (LightGBM multiclass/regression) | **75 (78%)** | 19 |
| rule_baseline (per-bucket, win-rate, constant) | 14 | 9 |
| bayesian_probabilistic (causal HMM) | 5 | 0 |
| deep_sequence (TCN) | 1 | 0 |
| ssl_representation (MAE encoder) | 1 | 0 |
| linear_logit · ts_foundation_model · tabular_foundation_model · rl_bandit · conformal_calibration · ensemble_stack | **0** | 0 |

All three advisory (order-influencing) heads are GBDT volatility-regime heads. The concentration is real
and is the thing the directive is about.

## 2. What our own history actually tested — and what it did not

| tried | exact configuration | closed? | NOT tested (so still open) |
|---|---|---|---|
| Frozen TSFM **embeddings** | Chronos-Bolt-**Tiny** (9M), frozen, random-projected 256→32, BTC/ETH 15m **volatility** head, label base rate 4.6%; direction head too | negative at the shipped operating point (base-rate cliff; ROADMAP T0.1, `ml/configs/retired/README.md`) | larger/newer checkpoints; any other target; fine-tuning |
| Frozen TSFM **quantile forecasts** (`fc_*`) | same Tiny model, six scale-free cols | **positive** (BTC macro_f1 +0.012 purged, ETH +0.029, SOL win); the one durable win, advisory today. Direction head: −0.001 | **any other forecaster; a classical HAR-RV control (no record of that comparison found — grep 2026-10-11)** |
| TCN deep sequence | price-only, BTC 15m regime | negative vs LightGBM | other architectures (PatchTST/iTransformer/Mamba); non-price inputs; other tasks |
| MAE SSL encoder | daily macro panel → 15m volatility head | negative (majority-class bias) | task-matched daily/cross-asset head (logged, never run) |
| Exit heads | LightGBM on price features, 3 lines | 3 negatives | a different learner class; choosing among exit arms instead of predicting an exit |
| Lead-lag | as an ML *feature block* on an ETH head (2026-06-18) | negligible (−0.0022) | as a 5m impulse trade |

## 3. Sources checked (this run)

Hugging Face Hub (model search + repo details via the HF MCP; trending papers), web search for arXiv /
model cards / vendor posts. **Not checked this run:** Kaggle write-ups, GitHub trending, SSRN — the
next scan should (recorded so the gap is not forgotten).

Licences below are the Hub `license` field read 2026-10-11 (primary) unless marked.

## 4. Ranked shortlist (information per dollar; top 8)

| # | candidate | family | licence | fits | why it could beat our head | cost to try | kill criterion | filed as |
|---|---|---|---|---|---|---|---|---|
| 1 | **TSFM bake-off:** Chronos-2 (119M, covariates), TimesFM-2.5 (231M), TiRex-2 (82M, covariates, streaming), Kronos-base (102M, OHLCV-native, finance-pretrained) vs shipped Chronos-Bolt-Tiny, **plus HAR-RV control** | ts_foundation_model | apache-2.0 · apache-2.0 · apache-2.0 · MIT (TiRex-1 is `other` — avoid) | volatility-regime head; later exit/range prediction | fc is already the one durable win and was measured on a 9M model; bigger/newer/finance-native forecasters are the cheapest lever on a proven feature; the HAR-RV control may show the neural part adds nothing — that finding alone is worth the unit | one producer swap, trainer CPU, ~4h | no candidate > +0.005 macro_f1 over incumbent fc on any symbol → incumbent stays | `RQ-20261011-9da8-01` ← `FRONTIER-LEVER-TSFM` |
| 2 | **Small-n tabular bake-off:** TabICL / TabPFN-v2/3 (research-eval) / CatBoost vs LightGBM on the meta-label dataset | tabular_foundation_model | TabPFN-2.5/3/v2 `other` (2.5 non-commercial); TabICL licence **unverified** | trade-outcome / setup-quality (the label wall) | the binding constraint is ~99 closed trades; tabular foundation models are pretrained for exactly small-n, LightGBM is weakest there | runner script + deps, ~2h on trainer | n≥300 and every challenger's paired log-loss CI contains 0 | `RQ-20261011-9da8-02` ← `FRONTIER-LEVER-TABULAR` |
| 3 | **Conformal abstention** (Mondrian split-conformal) on advisory heads | conformal_calibration | MIT/BSD libs (MAPIE, crepes; **not verified**), or ~50 lines of numpy | all advisory heads; later a per-trade refusal | zero new learner; direct answer to "right only when confident"; tests rolling-window validity because regime shifts break exchangeability (primary: arXiv 2607.24875 flags this) | one script, no training, ~20 min | no selective-error gain at matched coverage on ≥2/3 heads, or coverage drifts >3pt | `RQ-20261011-9da8-03` ← `FRONTIER-LEVER-CONFORMAL` |
| 4 | **Offline contextual bandit** choosing among existing exit-ladder arms (doubly-robust OPE) | rl_bandit | n/a (own code) | exits (3 head-lines failed predicting a continuous exit) | discrete arm choice is far lower variance than regression on thin labels; 0 models in family. Web search found online-RL crypto papers without code and no offline-RL exit result (secondary evidence thin) | needs ML-LEG-CORPUS (ML-X1) first | n≥150 and policy ≤ best fixed ladder | `RQ-20261011-9da8-04` ← `ML-LEG-CORPUS` |
| 5 | TSFM **fine-tuning (LoRA)** of the #1 winner | ts_foundation_model | as #1 | volatility / range | frozen has been the only mode tried | GPU burst | **No unit yet** — conditional on #1 PASS (a fine-tune of a zero-shot loser is a variation) | — |
| 6 | **Chronos-2 / TiRex-2 with covariates** (funding, OI) | ts_foundation_model | apache-2.0 | volatility, the information-class question | covariates are native (not bolted on); ties to ML-R4 | needs ETH/SOL funding/OI datasets | **No unit yet** — blocked on `FUNDING-OI-DATASETS-ETH-SOL`; fold into #1's follow-on | — |
| 7 | PatchTST / iTransformer / Mamba-style sequence models | deep_sequence | permissive (not individually verified) | volatility / direction | one TCN on price-only was negative; these are the same input class | GPU | **Dropped this week:** same inputs as the closed TCN, and the registry's lesson is labels/information, not depth. Reopen only with a new information class | — |
| 8 | Contrastive / SSL pretraining | ssl_representation | — | — | MAE on a daily panel failed by representation-target mismatch | GPU | **Dropped this week:** the logged remaining variant (task-matched daily head) is not worth capacity before #1/#2 report | — |

**Not carried (could not be confirmed):** a vendor-blog claim that "TimesFM 3.0" tops benchmarks with
BigQuery-only production licensing — single secondary source, unverified. Benchmark ranks (Chronos-2 79.8%
GIFT-Eval win rate in its own paper; TimesFM-2.5 70.0%; TiRex 70.4%) are **self-reported** (arXiv 2510.15821);
none of those benchmarks is financial, so they say little about our data.

**Also noted:** "TabPFN-3.5" (one secondary blog) and "TabPFN-3" (Hub card `Prior-Labs/tabpfn_3`, arXiv
2605.13986, `license:other`) — the family is moving fast, which is the argument for a bake-off runner
that takes a learner list rather than a one-off script.

## 5. Strategy ideas (lighter pass)

Gap list vs `config/strategies.yaml` (breakout, pullback, ICT scalp, donchian trend, squeeze, fade, vwap,
turtle soup; pairs via its own executor): no absolute vol-targeted momentum, no cross-sectional momentum,
no microstructure lead-lag.

| # | idea | mechanism (why it should exist) | harness | filed as |
|---|---|---|---|---|
| S1 | TSMOM with volatility targeting, BTC/ETH/SOL daily | trend persistence + risk-parity sizing; structurally different from every entry family | `vol_target` — **cost split missing** | `RQ-20261011-9da8-05` ← `FRONTIER-LEVER-HARNESS-COSTS` |
| S2 | Cross-sectional momentum, funding charged on held legs | relative strength; funding erodes the long leg | `xsec_momentum` — **no funding term** | `RQ-20261011-9da8-06` ← same lever |
| S3 | BTC→alt lead-lag at 5m with a shared-beta placebo | slow information diffusion between venues/assets; prior LOW (own 2026-06 probe: negligible as a feature) | none — new | `RQ-20261011-9da8-07` ← `FRONTIER-LEVER-LEADLAG` |
| — | Funding carry | cash-flow edge | exists | already `RQ-20261007-018` (blocked on a funding fetcher) — not re-filed |
| — | Liquidation-cascade early warning | forced-flow regime | — | **Dropped as a strategy:** arXiv 2607.27070 reports Binance's liquidation snapshot dumps are discontinued, so the key input is unavailable; the OI/aggressor-flow part is a *feature* question for `ML-R4` |

## 6. What this scan did NOT establish

No model here has been run on our data. Every "could beat" above is a hypothesis with a registered kill
rule, not a result. Licence readings are from Hub cards; the one licence that matters for serving
(Prior Labs weights) is `other`/non-commercial and needs an operator decision before any live use.
