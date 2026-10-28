# ML review and frontier scan: diagnosis and redesign basis (2026-10-28)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-28` · lane `SKILL-DESIGN-MODEL` (dispatched by the manager, session_01AFoLuJi1vLTnYv9LbP6539) · Tier 1 · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Checklist row:** [`docs/claude/work/checklist/SKILL-DESIGN-MODEL.json`](../claude/work/checklist/SKILL-DESIGN-MODEL.json) · roadmap `M25`
> **Outcome:** `.claude/skills/ml-review/SKILL.md` and `.claude/skills/frontier-research/SKILL.md` are rewritten on the shared four-layer pattern (prior calls · CHECKS · ANALYSIS · decisions). This doc is the evidence for that rewrite.

**Operator, 2026-10-28 ~07:15Z (via the manager, paraphrased):** redesign every recurring weekly review today, on researched
best practice. Avoid two failure modes. *Too loose*: the session skims and does no deep analysis. *Too scripted*: it is fed
statistics and restates them, so the outcome is decided in advance. Use the LLM's ability to reason over wide context, AND keep a
fixed format that guarantees the needed checks.

## 1. Population read

| id | what | locator |
|---|---|---|
| R-0927 | ml-review W6-M1 | PR #13075, `comms/reviews/ml-review-20260927-063330.json` |
| R-1011 | ml-review 2026-10-11 (first ML plan loop) | PR #17582, `comms/reviews/ml-review-20261011-140000.json`, `comms/ml-plan/20261011T2100Z.json` |
| P-1014 | ML-FRONTIER-PREP walkthrough | `docs/reviews/2026-10-15-weekly-walkthrough-ml.md` |
| U-1018 | ML-UNBLOCK-1018 plan writeback + frontier block | `comms/ml-plan/20261018T0700Z.json` |
| P-1021 | ML-FRONTIER-PREP walkthrough | `docs/reviews/2026-10-21-weekly-walkthrough.md` §§ 1–5, PR #19366 |
| M-1025 | ML-READ-1025 result read | `comms/ml-plan/20261025T0000Z-ML-READ-1025.json` |
| U-14 | the 14 units these records trace to the frontier scan: `RQ-20261011-9da8-01..07`, `RQ-20261018-ff8f-01..04`, `RQ-20261015-eda2-01`, `RQ-20261016-65ff-25`, `RQ-20261025-7ee1-01` | `research/queue/`, `research/queue/blocked/`, `research/results/` at `main@5b649d568` |
| A-1028 | ML coverage audit (not re-measured here) | `docs/research/ml-coverage-audit-2026-10-28.md`, `docs/plans/ML-PROGRAMME-2026-10-28.md` § 7 |

The full-review response JSONs since 2026-09-24 are the five files `comms/reviews/ml-review-2026{0924,0927,0929,1004,1011}*.json`.
After 2026-10-11 the weekly ML session ran only as a *prep* lane (P-1014, P-1021) and *read* lanes (U-1018, M-1025). **There is no
full ml-review record for 2026-10-18 or 2026-10-25.**

## 2. Scorecard

| dimension | finding (MEASURED unless marked) | failure mode |
|---|---|---|
| **Restated registry vs reasoning** | R-1011 has 96 `model_status[]` rows. **90 of the 96 `note`s are two template phrases**: "candidate: trains, not served" (63) and "ok" (27), counted by prefix. The skill *requires* a row for every registered model, so the session's effort went into a census of 96 rows, most of them candidates that influence nothing. | **too scripted** (a census in place of analysis) |
| **Promotion/demotion calls, and were they right?** | On 2026-09-25 (#12960) and in R-0927 (#13075), two reviews argued whether to demote the BTC and SOL 15m advisory regime heads, and held each time. R-0927 itself recorded that `sol-regime-15m-lgbm-fc-pcv-v2` *"has had zero real-money order effect since promotion because no `trend_vol` OFF-cell names a SOL strategy"*. That was filed as an `experiments_proposed[]` entry, not a unit. A-1028 (§ 1b) measures the same fact a month later: the SOL and MES advisory heads gate nothing. So the hold calls were not wrong, but they were **about a metric with no business use**, and the one decision-relevant fact never became work. | **metric ≠ business use** (SR 26-2 judges outcomes "relative to model objectives and business use", § 3) |
| **Checks actually run** | The trainer relay (stage-guard, gate-check, soak parity, label coverage) was **not run** in R-1011 (queued 30+ min), P-1014 or P-1021. Each said so honestly. Each still published a review, and P-1014 deferred the soak audit to "the Sunday /ml-review", which then did not run. 3 of the last 4 weekly ML outputs therefore have no promotion packet and no soak audit. | **too loose** (a missing check is reported, not chased) |
| **"Is it learning?"** | **No record asks it.** A-1028 measures that 0 manifests train on the 627-row `claude_judgments` teacher data, there are 0 in-trade models, and since 2026-10-22 no learned model feeds conviction on any leg. Every hop was reported as shipped. None of the reviews measured produced → labelled → in a dataset → trained → scored → changes an order. | **declaration checked, output not** |
| **Model-family diversity** | `--diversity` ran every week, and gbdt stayed flat at 75/96 → 76/97 (78%). Families did vary: TabICL, TabPFN, GRU, Chronos-2, conformal and calibrated logit were all tried. **But every one of the 7 units that ran tested the same object**: a volatility-regime classifier's macro-F1 or log-loss on BTC/ETH/SOL (15m/1h, MES 1d). No frontier unit asked a trade-management or order-value question. | **family diversity, question monoculture** |
| **Ideas → pre-registered units that ran** | U-14: **7 ran and 7 are still blocked.** `9da8-02..07` have been blocked since 2026-10-11 (17 days), and `7ee1-01` since 2026-10-25. Verdicts of the 7 that ran: 1 PASS (`eda2-01`), 2 FAIL (`ff8f-03`, `65ff-25`), 1 machine-FAIL read as underpowered (`9da8-01`, per M-1025), 3 INDETERMINATE (`ff8f-01/-02/-04`). The lever row `FRONTIER-LEVER-TSFM` gated its unit across ≥3 scans. The skill's "raise it to the manager" happened only as a prose line in P-1021 § 5. | **filing without follow-through** |
| **Power: the unit of analysis** | `RQ-20261018-ff8f-04` registers `power: expected_n 24000 … d=0.1 needs ~785 rows`. Its rule is a paired t-interval **over 5 folds**, not over rows. M-1025 measured fold sd ≈ 0.03, so "detecting +0.010 needs ~70 folds". `9da8-01` needs ~17 folds and ran 5. **The power block was satisfied on the wrong unit, so the indeterminate result was decided before the run.** | **pre-registration without a valid power calc** |
| **Grading the previous review's calls** | No record grades last week's calls. P-1014 said "BTC moderate drift — re-read next week; if persistent, open a `[refinement]` row". P-1021 reads the BTC head as `minor` and does not mention the call. U-1018's `next_by_value_per_cost` list is not scored by any later record. | **no feedback on the reviewer** |
| **Frontier source coverage** | P-1014: "Not checked: GitHub trending, Kaggle, SSRN". U-1018: "no outside web scan this lane". P-1021: "partial, ~3 sources". Row `FRONTIER-SCAN-COMPLETENESS` (from #20844) already tracks this. | **too loose** |

**What worked, and is kept:** honest could-not-look statements; field-beats-comment corrections (M-1025 on the TabPFN token; R-0927 on
the drift reference window); every kept idea did become a unit with a registered rule; "a FAIL closes only the configuration".

## 3. Best practice, researched (tags: REG regulator · ACAD peer-reviewed/academic · PRAC named practitioner · VEND vendor)

| # | source | tag | read | what it says that we use |
|---|---|---|---|---|
| B1 | Federal Reserve / OCC / FDIC, *SR 26-2 Revised Guidance on Model Risk Management* (2026-04-17, supersedes SR 11-7), attachment [SR2602a1.pdf](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf); cover letter [sr2602.htm](https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm) | REG | full text of the § "Components of Model Validation", "Model Inventory" and "effective challenge" passages | **Outcomes analysis** "compares model outputs to corresponding real-world outcomes to assess model performance **relative to model objectives and business use**". **Ongoing monitoring** asks whether the model "is performing as expected given potential changes in … data relevance, or market conditions", with "procedures for responding". **Effective challenge** is critical analysis "by objective experts" with the "standing and influence to effect any change". **Aggregate risk** includes "reliance on common assumptions, data, or methodologies". The **inventory** holds "sufficient information to understand model risks". → CHECKS C3 (business-use map), C8 (aggregate concentration); the ANALYSIS value question (outcomes vs business use) and Layer 0 (the review grading its own prior calls). |
| B2 | SR 11-7 secondary summaries ([ValidMind](https://docs.validmind.ai/about/use-cases/sr-11-7.html), [ModelOp](https://modelop.com/ai-governance/ai-regulations-standards/sr-11-7)) | VEND | summary | Monitoring sets **triggers** that prompt accelerated review. Outcomes analysis includes **benchmarking against alternative models**. → the challenger check C6. |
| B3 | Breck et al., *The ML Test Score: A Rubric for ML Production Readiness*, IEEE Big Data 2017 ([Google Research](https://research.google/pubs/pub46555/)) | ACAD | abstract | 28 tests and monitors. Testing plus monitoring is what makes ML production-ready, because prediction behaviour cannot be specified in advance. → a fixed CHECKS list that is run, not remembered. |
| B4 | Zinkevich, *Rules of Machine Learning* ([Google Developers](https://developers.google.com/machine-learning/guides/rules-of-ml/)) | PRAC | rule titles | Rule #8 "Know the freshness requirements of your system". Rule #10 "Watch for silent failures". Rule #29: save the features used at serving time. Rule #32: reuse training/serving code. Rule #37 "Measure Training/Serving Skew". → C2 (freshness), C4 (chain/silence), C5 (parity). |
| B5 | Sculley et al., *Hidden Technical Debt in Machine Learning Systems*, NeurIPS 2015 ([proceedings](https://proceedings.neurips.cc/paper/2015/file/86df7dcfd896fcaf2674f757a2463eba-Paper.pdf)) | ACAD | abstract | Names hidden feedback loops, **undeclared consumers**, data dependencies and "changes in the external world". → C3: every model's consumer is declared and measured, not assumed. |
| B6 | Alencar et al., *Concept drift detection in delayed and partially labeled data streams: an experimental survey*, Digital Signal Processing 182 (2026), [doi:10.1016/j.dsp.2026.106325](https://doi.org/10.1016/j.dsp.2026.106325); arXiv [2604.17836](https://arxiv.org/pdf/2604.17836) (preprint) | ACAD | abstract / search summary | Input-distribution tests (KS, PSI) see **data drift only**. **Concept drift** needs labelled performance, and label delay makes error-based detectors inapplicable in their raw form. PSI cut-offs (0.1/0.25) are heuristics. Per-feature tests inflate false alarms (multiple testing). → C7 splits score drift from labelled-performance decay. The drift question must say which kind it is before calling for remediation. |
| B7 | Nadeau & Bengio (2003); Bouckaert & Frank (2004): the corrected resampled t-test (as implemented in [correctR](https://search.r-project.org/CRAN/packages/correctR/correctR.pdf), [MachineShop](https://rdrr.io/cran/MachineShop/man/t.test.html)) | ACAD (via package docs) | package documentation | The CV fold-score variance **underestimates** the true variance, so naive paired fold t-tests raise false positives. The correction is F = 1 + K/(K−1) style. → power and intervals are computed **on folds**, with the correction. That is the `ff8f-04` lesson. |
| B8 | Champion/challenger in production finance ([SAS Model Manager docs](https://support.sas.com/documentation/cdl/en/mdsug/65072/HTML/default/p18fpyidkphf5tn1rbndjkf01ofl.htm), [Hyperbots glossary](https://www.hyperbots.com/glossary/challenger-model-framework)) | VEND | summary | Champion and challenger score **the same inputs**. The swap is a documented governance decision. Development and evaluation are kept separate. → C6: the same replay, folds and cost stack for champion and challenger, and a recorded decision. |
| B9 | Mitchell et al., *Model Cards for Model Reporting*, FAT* 2019 ([arXiv 1810.03993](https://arxiv.org/abs/1810.03993)) | ACAD | abstract | State the **intended use** and **disaggregated** evaluation, not one headline number. → C3 (intended use = consumer) and the value question (per leg / regime, not pooled). |
| B10 | The repo's own practice list, [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md) (#20844): M2 purged CV, M4 pre-register and count trials, M5 deflate, M6 beat random/simple rules at the same decision points, M10 promote on decision value net of cost + CUSUM decay | ACAD/PRAC (compiled) | full | Cited by number in the skills rather than restated. |

**Research triage for frontier scans** (no single standard found; the synthesis is ours, INFERRED from B1, B6, B7 and the
repo's own record): rank a candidate by *(does it attack a question the business uses) × (is it powered at the registered
design) × (is the instrument built)*. An unpowered or unbuildable candidate is a lever, not a test.

## 4. The design these findings imply (written into the two skills)

1. **CHECKS are scripts with fixed populations**, run first. Each check prints a state: `ok`, `finding`, or `could-not-look`. A
   `could-not-look` on a required check is chased in-session (retry, alternate relay), not just reported. Only after that does
   the review publish it as a gap, with a filed row.
2. **The registry census is replaced by a business-use map** (B1, B5, B9): every model at shadow/advisory, plus any model a consumer
   reads, is mapped to the consumer that reads it and to the legs where it can change an order. A head that influences nothing is
   one line, and its question is *should this exist*.
3. **The learning chain is a check** (ML-PROGRAMME § 7 ledger, hops H1–H7). Until `ML-LEARNING-LEDGER` exists the review computes
   the hops from the named sources and says which ones it could not compute.
4. **Champion vs challenger on one replay, one fold file, one cost stack** (B8, M6, M10), or the comparison is not reported.
5. **Drift is split into score/data drift and labelled-performance decay** (B6). Only the second one, persistent, motivates remediation.
6. **Adopt the shared four-layer pattern** (`docs/reference/llm-analyst-skill-design.md`, lane ANALYTIC-SKILL-DESIGN). **Layer 0**
   grades the previous review's calls (B1, effective challenge). **Layer 2** reasons through ML-specific candidate questions:
   value to the decisions a model feeds, what the tests mean (with power on the test unit), whether the ML is learning, drift, the
   next experiments by expected value per cost, and stages. **Layer 3** makes each decision a call with a pre-registered check.
7. **Frontier triage gains a power gate and a "business question" gate**, and Step 0 grades last week's kept/dropped calls.

## 5. Not verified here

- The SR 26-2 passages were read from the attachment's text. The B2, B8 and B6-preprint points come from summaries, not full text.
- A-1028 and the ML-PROGRAMME counts (5/51 legs, 0 teacher-trained manifests) are cited, not re-measured.
- Whether the 2026-10-18 and 2026-10-25 full ml-reviews were dispatched and failed, or were never dispatched, was not established.
  Either way no record exists (positive control: the five earlier `comms/reviews/ml-review-*.json` files are found by the same `ls`).
