# Frontier scan — 2026-11-11 (lane ML-FRONTIER-PREP-20261111)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**Gates this adds or changes:** none.

This file is the evidence behind the frontier half of the 2026-11-11 weekly brief
([`docs/reviews/2026-11-11-weekly-walkthrough.md`](../reviews/2026-11-11-weekly-walkthrough.md) § ML-FRONTIER-PREP). It was written to
[`.claude/skills/frontier-research/SKILL.md`](../../.claude/skills/frontier-research/SKILL.md). **The dispatch said "queue no new units;
propose them"**, so every kept idea below is a **proposal** (labelled MODEL or TRADING), not a unit. The machine record is
`comms/ml-plan/20261111T2000Z-ML-FRONTIER-PREP.json` § `frontier`.

## 1. Where we stand (F2, MEASURED 2026-11-11, `python3 scripts/ops/ml_plan_status.py --diversity`)

| family | manifests | live/shadow | open plan items | graded history |
|---|---|---|---|---|
| gbdt | 77 | 18 | 14 | INDETERMINATE |
| rule_baseline | 14 | 5 | 2 | — |
| UNMAPPED (served ENTRY / overlay / exit artifacts) | 8 | 8 | 0 | — |
| bayesian_probabilistic | 5 | 0 | 1 | — |
| deep_sequence · ssl_representation | 1 · 1 | 0 | 1 · 0 | FAIL · FAIL |
| linear_logit · ts_foundation_model · tabular_foundation_model · rl_bandit · conformal_calibration · ensemble_stack | 0 | 0 | 1 · 2 · 1 · 1 · 1 · 0 | mixed |

- `MANIFEST-CONCENTRATION`: gbdt 77 of 106 registry rows (73 %). Reported, not failed.
- gbdt holds 14 of 24 family-tagged open items, which is 58 %. The `CONCENTRATION` bar is 60 %, so this is 2 points under it. No `FAIL-STREAK`.
- `UNMAPPED-TRAINER`: the 8 served artifacts carry no `model_family`, which is why they read `UNMAPPED:None`. `ML-N1` and `ML-V1` carry no `family:` tag.
- **The concentration that matters is by question, not by family.** All 38 ML bake-off result records generated since 2026-11-04 20:00Z (27 distinct units)
  target `regime_label` (25) or `direction_label` (13). That is 100 %, for the third week running (last week 33 of 33, the week before 50 of 50).
  The 3 regime heads that the registry calls advisory change 0 rostered legs (§ C3 of the brief).

## 2. Sources checked (F3)

| source | state | what I read (PRIMARY = paper or model card; secondary = blog or aggregator) |
|---|---|---|
| Hugging Face Hub | checked | `hf://papers/trending` (top 25), `hf://papers/daily/latest` (2026-11-11), four paper searches (financial TSFM, crypto perps, RV/HAR, tabular FM), and a model search sorted by creation date. Model cards read: `ibm-granite/granite-timeseries-ensemble-r1` (Apache-2.0, updated 2026-10-27, a GIFT-Eval probabilistic ensemble); `ibm-granite/granite-timeseries-patchtst-fm-r2` (384.6 M, `openmdw-1.0`); `google/tabfm-1.1.0-pytorch` (`license:other`); `LG-AI-Research/EXAONE-Tabular` (`license:other`) |
| arXiv | checked (via HF papers) | **2611.13572** Market-Conditioned JEPA (HKU, 2026-11-10; abstract and introduction, PRIMARY). **2609.37959** TabFM (Google, 400 M, zero-shot ICL, ranked first on TabArena's 51 sets; abstract, PRIMARY). 2608.25774 EXAONE Tabular (title and summary). 2611.07464 FINCOSMOS (open-world finance-agent evaluation; summary only). 2606.27100 and 2511.18578 (re-read: TSFMs give sparse gains on returns; domain pretraining helps) |
| Lab releases | checked, **secondary only** | No TSFM release dated November 2026 was found. The newest are TimesFM-3 (Google, 2026-08-31, primary blog `research.google/blog/timesfm-3-…`), Timestral (Mistral, 2026-10-15) and t0-alpha (Apache-2.0, 2026-06). On HF the one new primary card is IBM's Granite ensemble-r1 (2026-10-27) |
| Quant practitioner literature | checked, thin | A web search for 2026 SSRN work on perp funding / basis cross-sectional predictability found no 2026 primary. The references are still He–Manela–Ross–von Wachter (*Fundamentals of Perpetual Futures*, 2212.06888) and practitioner notes (Presto Research: funding is more useful cross-sectionally). A cost-aware execution-filter claim (arXiv 2606.00060) was seen only second-hand on a blog, so it is **not carried** |
| GitHub / competitions | not required this week | Both were checked on 2026-11-04 (every-other-week rows). The code links seen this week are `github.com/OpenFinMind/MC-JEPA` and `github.com/google-research/tabfm` |

Source floor: **4 of 4 required rows checked.** The lab-release row is secondary-only, for the second week running.

## 3. Triage (six gates) and ranking

The money consumer this week is still **D3 ENTRY**: Foxhound-1 (refit r20261106) on `bybit_2` (real money) and five other books, plus Foxhound-4 on
`alpaca_live`. The week's most informative result is that the served ENTRY replay loses entirely on the **long side**:

- `RQ-20261108-98e3-23`, window 2026-10-25..11-07: pool −0.13 R/decision, n = 317, CI [−0.25, −0.01]. Longs −0.90 R (n = 51, 8 % winners). Shorts +0.017 R (n = 266). Verdict: SIDE-DRIVER and DECAY.
- `RQ-20261108-98e3-26`: the frozen v1 over its clean held-out year reads a mean of +0.0085 R/decision across 13 windows of 28 days. The window sd is 0.127. Verdicts: NOT-AGE, NOT-REGIME, NO-LEVER for cadence.
- `RQ-20261108-98e3-25`: the side effect is window-specific, and a short-only gate is NO-LEVER.

**An ENTRY model whose result flips with which side the market moved is pricing the common crypto factor, not the asset-specific part.** That is the
mechanism 2611.13572 formalises: under a latent factor model, per-asset prediction treats the market shock as noise, and conditioning on the market
factor isolates the asset-specific signal.

| # | candidate | family | gates 1–4 (data · compute · serve · leakage/licence) | gate 5: business question | gate 6: power (test unit) | kept? | p_pass |
|---|---|---|---|---|---|---|---|
| K1 | **Market-residual target for ENTRY**: train the same recipe on the asset's 24 h net return *minus* β × BTC return (rolling β, causal), with a decision rule that is market-neutral at each timestamp. Source: 2611.13572's factor-conditioning argument plus the 98e3-23 SIDE-DRIVER diagnosis | gbdt (a target lever, not a learner) | data ✅ (BTC and asset bars are in the store) · compute ✅ (the same recipe) · serve ✅ (inline OHLCV, zero torch) · leakage ✅ (β from past bars only) | D3 on `bybit_2` (real money) plus five books: it would replace or refit Foxhound-1 | 13 × 28-day windows over the clean held-out year (the 98e3-26 design). Paired sd 0.074 R, so the MDE at 80 % power is **+0.058 R/decision**. Registered effect ≥ +0.06 R/decision, plus a placebo (shuffled-β) control | **PROPOSED** (MODEL, P2 in the brief) | 0.15 |
| K2 | **MC-JEPA encoder** as a feature source (2611.13572; code public) | ssl_representation | data ⚠️ (trained on minute-level A-shares; we have crypto 5m) · compute ❌ (torch training; the trainer has 1 vCPU) · serve ⚠️ (mirror-publish is possible) | the same D3, through K1's mechanism at much higher cost | not computed | **dropped (compute)**. K1 tests the mechanism at zero model cost first. Re-open only if K1 passes | — |
| K3 | **TabFM / EXAONE-Tabular** as an ENTRY learner arm | tabular_foundation_model | licence ⚠️ (`other` on both cards, so research-only) · compute ❌ (400 M ICL over ~777 k ENTRY rows on a 1 vCPU trainer) | D3 | — | **dropped (compute, licence)**. It belongs to the open lever row `FRONTIER-LEVER-TABULAR`, now in its 4th scan and raised to the manager again (§ 5) | — |
| K4 | **Granite ensemble-r1 quantile forecasts** as an input to the TP-revision head (Labrador-1b, D7) | ts_foundation_model | licence ✅ Apache-2.0 · compute ✅ (small) · serve ✅ (mirror-publish) · **leakage ❌**: released 2026-10-27, so a clean post-release holdout is 15 days of bars | D7 TP revision on `ml_entry`: a real consumer this time, unlike last week's TSFM drop | ❌ 15 days cannot power any fold design | **dropped (leakage/power)**. Re-open at ≥ 3 months post-release (2027-02-01), when it is the first TSFM with a named consumer | — |
| K5 | Short-only / side gate on ENTRY | gbdt (rule) | ✅ | D3 | — | **dropped (already answered)**. 98e3-25 measured NO-LEVER, SIDE-WINDOW-SPECIFIC | — |
| K6 | More learners or feature blocks on `regime_label` / `direction_label` | various | ✅ | ❌ 0 rostered legs read a regime head (C3) | n/a | **dropped, third week.** ML-CONSOLIDATION (#24897) proposes retiring 41 D2 regime manifests for the same reason | — |
| K7 | FINCOSMOS-style open-world evaluation for the desk agent (2611.07464) | — | — | the desk is graded against benchmark B3 already | — | **dropped (business question)** | — |

**Kept: 1 (K1, proposed, not queued). Dropped: 6.** Strategy half: none this week, because `perf-followup` Track 3 owns it and the one
practitioner mechanism in scope (perp funding / basis) is already a covered iteration subject (`funding-carry`, `RQ-20261101-d1f3-07` PASS).

### Kill criterion for K1 (written now so next week's Step 0 can grade the keep call)

- **PASS** iff the residual-target ENTRY beats the frozen v1 by at least +0.06 R/decision, paired over 13 windows, with a CI lower bound > 0 and the shuffled-β placebo not passing.
- **FAIL** iff the paired mean is ≤ 0 or the placebo matches the candidate.
- **INDETERMINATE** otherwise. A FAIL closes *this target definition* (BTC-β residual, 24 h, the v1 recipe), not market-neutral ENTRY as an idea.

## 4. M41 scoping answer (Step 0b; `PI-20261022-J9X7ACR3-0001`)

**Question:** what would a production-ready local LLM do for us, what would it cost, and can it run on our VMs?

- **Compute (gate 2): fails on both VMs.** The trainer reported 1 vCPU and 5.9 GB RAM on 2026-11-04 (pull #22899); this week's figure is in the brief's C1. A 7 B 4-bit model needs about 5 GB resident and runs at a few tokens per second on one ARM core. The live box carries the "zero torch on the money box" rule.
- **Business (gate 5): no consumer needs a per-call LLM.** The desk and reviews run on the Claude plan (CLAUDE.md: nothing spends API credits), and no live decision path waits on text generation.
- **Verdict: kill M41 as scoped.**
- **Re-entry test:** a named consumer that needs offline text inference at a volume the plan cannot carry, plus a host with ≥ 16 GB RAM.
- The pipeline item is closed `killed` with this reason, and M41's `next` in `docs/roadmap/milestones.yaml` records the verdict and the re-entry test (both in this lane's PR).

## 5. Lever rows (F4): still queued across scans

| row | first filed | scans queued | disposition this run |
|---|---|---|---|
| `FRONTIER-LEVER-TABULAR` | 2026-10-23 | 4 | **raised again; recommend KILL.** K3 shows the licence and compute gates now fail for the newest tabular FMs too |
| `FRONTIER-LEVER-TSFM-TIMESTRAL` | 2026-10-25 | 3 | **raised again; recommend KILL.** The licence is revenue-capped and no consumer reads a point forecast (K4 names the only consumer, and that waits for 2027-02) |
| `FRONTIER-LEVER-HARNESS-COSTS` | 2026-10-23 | 4 | **raised again; recommend DISPATCH.** The fee-only harnesses still cannot enter a promotion corpus |
| `FRONTIER-LEVER-LEADLAG` | 2026-10-23 | 4 | **raised again; the manager decides.** No new evidence either way this week |

Per the skill, none of these is re-filed. Each sits in the brief's `handoff` to the manager.
