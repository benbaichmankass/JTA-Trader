# Frontier scan 2026-11-25 (lane ML-FRONTIER-PREP-20261125)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Run record: `comms/ml-plan/20261125T2000Z-ML-FRONTIER-PREP.json`. Walk-through section: `docs/reviews/2026-11-25-weekly-walkthrough.md`.
Gates this adds or changes: none. Per the dispatch, this lane queues **no** units. Kept ideas are proposals mapped in the walk-through § 3.

## What the business needs this week (gate 5 first)

1. The operator's promotion-rule fix (2026-11-25): *a number measured only over the grading window must not promote.* It needs
   an instrument that says when a window is spent.
2. The D7 and D8 slots have no next unit.
3. AM v2: every random control leaked exit-time knowledge.
4. ml_entry: 33 levers and 0 PASS, over a dev base of +0.003 R/decision.

So the question this week is **methodology, not another model family**.

## F1–F4 checks

- **F1** (the last scan's units): dbf8-01 FAIL (informative, powered at 13 folds). dbf8-02 is still blocked.
- **F2** `--diversity`: CONCENTRATION gbdt 14 of 19 open items (74%). Manifests are 79 of 108 gbdt. 8 served models are `UNMAPPED`.
- **F3** source floor: every required row was checked (table below). GitHub and competitions were due this week, because they were
  skipped on 11-18, and both were checked.
- **F4** lever rows: **FRONTIER-LEVER-TABULAR has been `dropped` since 2026-10-23**, yet the 11-18 scan called it queued. dbf8-02
  therefore has no live lever. This goes to the manager as a blocker; it is not re-filed.

## Sources checked

| source | state | what it gave (primary / secondary) |
|---|---|---|
| Hugging Face Hub (papers search) | checked | TabAbax tech report, arXiv 2611.00562 (primary; TabICLv2-based; TabArena regression Elo +336 over TabICLv2, self-reported). NVIDIA Kumo Tabular, 2611.23001 (primary, 2026-11-17). TabPFN-3.5 tech report, 2609.17895. "Beyond IID: How General Are Tabular Foundation Models, Really?", 2606.30410 (primary; the open question is TFM generality off iid data). |
| arXiv / methods | checked | Dwork et al., "Generalization in Adaptive Data Analysis and Holdout Reuse", [arXiv 1506.02629](https://arxiv.org/abs/1506.02629) (primary, NeurIPS 2015; Thresholdout / reusable holdout). Bailey, Borwein, López de Prado, Zhu, ["The Probability of Backtest Overfitting"](https://papers.ssrn.com/abstract=2326253) (primary; CSCV). arXiv 2604.27150 (exit-policy replay over 900 trades, cs.AI; no ML or lookahead test, so dropped). |
| Lab releases | checked (secondary) | Toto 2.0, TiRex-2, TimesFM-3, t0-gamma, Timestral and Chronos-2 per a [TDS roundup](https://towardsdatascience.com/timestral-t0-tabby-and-morpheus-20-compared-on-gift-eval/). The fev-bench gaps are small and self-reported. Per that roundup, TimesFM-3 is research-only and Timestral has a revenue-capped licence (secondary; read the Hub licence before any use). |
| Quant practitioner literature | checked | PBO/CSCV (above): selection among N configs must be deflated, and "almost never declare the number of trials". |
| GitHub | checked | Triple-barrier / meta-labelling libraries (OpenQuant, FinMLKit, mlfinpy). None shows dated 2026 maintenance in the results, and we already have our own harness, so dropped. |
| Competitions | checked | The VN2 winner ([arXiv 2601.18919](https://arxiv.org/abs/2601.18919)) used a global CatBoost plus a cost-aware policy. GBDT stays the tabular default, which agrees with dbf8-01. |

## Triage (six gates) and keep ≤ 5

| candidate | family | gates | kept? | p | maps to |
|---|---|---|---|---|---|
| **Held-out read ledger / reusable holdout** (Dwork 2015): count adaptive reads per (subject, window); a window past k reads is spent; promotion needs a fresh window | methodology (conformal_calibration-adjacent; no model) | data ✓ (results + trial ledger in git) · compute ✓ · latency n/a · leakage: it is the leakage control · business ✓ (decides what promotes; ml_entry has 27 recorded reads of its window) · power n/a (instrument) | **kept** | 0.6 adopted | walk-through P-6 → the operator's promotion-rule-fix decision, 11-30 |
| **PBO / CSCV deflation for configuration selection** | methodology | data: partial (no per-trade series for ml_entry, C10) · business ✓ · power: the needed per-config series exist for the f1a0 family | **kept** as part of P-6 | 0.4 | same as above |
| Fresh-window confirmation as the standard second read (outside practice; already our `pass_action` text) | methodology | ✓ all | **kept** | 0.25 PASS | walk-through P-2 |
| TabAbax / Kumo Tabular regression TFM on the D3 net-R target | tabular_foundation_model | compute: no learner kind, and the lever row is `dropped` · business: capped by the D3 base ≈ 0 · licence: unread | dropped (compute; re-rank once dbf8-02 has a live lever) | 0.1 | — |
| TiRex-2 / Toto 2.0 / TimesFM-3 features for D2 | ts_foundation_model | data: D2 live-vs-replay label parity is still broken (PI-20261118-ZZUFKM1F-0001) · licence (TimesFM-3 research-only, secondary) | dropped (data) | 0.1 | — |
| Exit-policy replay (2604.27150) | rule_baseline | no ML, no lookahead control | dropped (business: we already run a stricter design) | — | — |
| Triple-barrier libraries | — | duplicates our harness | dropped | — | — |

**Answer to the standing question "are we stuck on one model family?"** Yes on capacity (gbdt holds 14 of 19 open family-tagged plan items, 74%; `ml_plan_status.py --diversity`). But this week's evidence says
the binding limit is the **D3 label/base and the evaluation design** (spent windows, leaky controls), not the learner. A new family
on the same base cannot clear an MDE of +0.0068 when the base is +0.003. Re-point capacity to the evaluation instruments (P-6) and the
empty D7/D8 slots before adding another family.

## Calls (graded next week)

- P-6 is adopted into the promotion-rule text by 11-30 (p 0.6).
- dbf8-02 is still blocked at the 12-02 scan (p 0.8; check the unit status and the FRONTIER-LEVER-TABULAR state).
