# Analytic skill design: checks + analysis (2026-10-28)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**Lane:** `ANALYTIC-SKILL-DESIGN` (dispatched by Manager Session 2026-10-27a). **Tier 1** (skill and doc edits only).
**Track:** applies to both research tracks. Each skill below is labelled **TRADING** or **MODEL** (operator two-track
split, [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md)).

**The question (operator, 2026-10-28 ~07:15Z, paraphrased by the manager):** does the performance review actually
move performance? The operator suspected one of two failures. Either it is too loose and does no deep research or
thinking, or it is too scripted: statistics go in and deterministic statistics come out, with no use of the LLM.
They also suspected most reviews check last week's trades and ignore each strategy's whole record. The task: find
the correct design, then apply it to every recurring analytical and monitoring skill.

## 1. Diagnosis — the performance review, MEASURED

**Population.** Four JSON review records:
- `comms/reviews/performance-review-20260924-160000.json`
- `-20260927-072944.json`
- `-20261004-103845.json`
- `-20261010-191000.json`

Two weekly walk-through PERFORMANCE sections:
- `docs/reviews/2026-10-15-weekly-walkthrough-perf.md`
- `docs/reviews/2026-10-21-weekly-walkthrough.md` § PERFORMANCE

Also read:
- the 13 pipeline items those reviews filed (`PI-20261004-ZBHFJG6X-0001..6`, `PI-20261010-WQAPZD8B-0001..4`,
  `PI-20261021-4ZLRFEV1-0001..3`), resolved to their latest record in `docs/claude/work/pipeline/`;
- `comms/claude_strategy_scores.jsonl` rows with `reviewed_at` ≥ 2026-09-20 (n = 908);
- the review-prep routine's stored prompt (`trig_01LE61kLKDFKptEfTfZ7vnYS`, read with `get_trigger` 2026-10-28).

| Rubric dimension | What the records show | Example (quoted) |
|---|---|---|
| **Windows** | **4 of 4** JSON reviews read only the window since the previous review (3 to 16 days). The 10-21 walk-through added W30 and 90d and a whole-history live-vs-backtest table. It is the one exception, and it came from the prep prompt's "net per capital-day" ask, not from the skill. | 10-04 `_window_note`: "Anchored on the previous review record … Population: 218 order packages … 113 closed trades" |
| **Baselines** | Live-vs-own-backtest appears once (10-21, Step 0). No review compares a leg with its siblings, with hold, or with a random baseline in the review itself. Those exist only for the reviewer and the desk (generator output). | 10-21: "`xrp_pullback_2h` n=17 −9.92R … BELOW_BACKTEST" |
| **Attribution** | None of the four JSON reviews attributes P&L to entry, exit, sizing, cost or regime. The 10-21 giveback table is an exit-path *measurement*, not an attribution. | 10-04: "n=5 supports no per-leg conclusion" (the analysis ends there) |
| **Decay / regime detection** | No decay test. There is no CUSUM or sequential test anywhere in `scripts/` or `src/`: `grep -rli cusum` returned 0 files. A grep for a known name (`live_vs_backtest`) on the same tree returns hits, so the probe can find a positive. | — |
| **Hypotheses formed and tested** | **0** across the six outputs. Findings are observations plus "file it". | 10-21 § 7: "Positive-R legs to understand, not promote" (no hypothesis about why) |
| **Restated numbers vs reasoning** | Mostly restated numbers. The 10-21 PERFORMANCE section is titled "grading and numbers only". The routine's prompt says *"Run .claude/skills/performance-review/SKILL.md through its grading and numbers only."* | prompt of `trig_01LE61kLKDFKptEfTfZ7vnYS` |
| **Findings → actions → moved anything?** | Of 13 filed items: **10 are mechanics or data-integrity** (orphans, a cron that did not land, exit-reason labels, a watchdog close, valuation) and 3 are performance. **11 of 13 still sit at `routed`.** 1 is `done`, and that one had already been attributed on 10-18, **three days before** the 10-21 review re-surfaced it as its headline. "Run the M8 sweep for `ada_pullback_2h`" was recommended on 10-04 and again on 10-10. **0** tune files exist for that leg (`git ls-tree origin/main` lists 0 `ada_pullback` paths among the 324 `strategy_tunes` files). | 10-10 `recommended_action`: "(2) Tier-1: run the M8 tune sweep for ada/avax/sol pullback before any demotion." |
| **Proposals** | `proposed_tweaks[]` is empty in 3 of 4 JSON reviews (09-27, 10-04, 10-10). | 10-10 `_proposed_tweaks_note`: "None. … no leg has the evidence for one." |
| **Grading (the skill's core)** | 908 grades since 2026-09-20. **747 (82%)** came from the daily cron's deterministic rubric (`source: grade-closed-trades-by-trade*`), labelled `reviewer: claude` until a recent relabel. `risk_management: unknown` on **907 of 908**. No A and no F grades. Grade vs outcome over the rows with a numeric `pnl`: **B n=149, 32% win; C n=547, 46% win; D n=32, 16% win.** The B and C cohorts are inverted, so the letter grade does not predict outcome. | 10-04 anomaly: "grade_drift: A/B cohort (n=13 …) net −$515.33 … Rubric does not separate outcomes" (raised, never fixed) |

**Verdict: both failure modes, in different places.**
- **Too scripted where it should be thinking.**
  - The skill's centre of gravity is a deterministic rubric and about thirteen mandatory procedures that produce numbers.
  - The routine dispatches it as "grading and numbers only" on Sonnet with an $8 ceiling.
- **Too loose where it should be checking and reasoning.**
  - There is no fixed multi-window per-leg check, so each review re-picks its own window.
  - There is no requirement to form or test a hypothesis.
  - There is no memory of prior calls, so recommendations repeat and old findings resurface as new.
  - Mechanics findings crowd out performance.

**Where real analysis did happen.** Real analysis happened in `/perf-followup` (W43). That lane:
- named the forming-bar entry cause;
- built `scripts/research/as_traded_stage0.py`;
- bootstrapped live R against the arm each leg actually trades.

That is the LLM doing what it is good at, but it sat downstream of a review that had not asked the question.

## 2. Sources (practice and evidence)

Tags: **ACAD** (peer-reviewed or academic working paper), **PRAC** (practitioner), **VEND** (vendor). The research
was done by a sub-agent of this lane using web search. Only P8 and P12 were read in full text; the rest were checked
at abstract or publisher level. **[2nd]** marks a claim taken from secondary material.

| id | Source | Tag | Used for |
|---|---|---|---|
| P1 | Bailey & López de Prado, "The Sharpe Ratio Efficient Frontier", *J. Risk* 15(2), 2012 — PSR, MinTRL. https://www.risk.net/journal-risk/2223785/sharpe-ratio-efficient-frontier | ACAD | small-n verdicts |
| P2 | Bailey & López de Prado, "The Deflated Sharpe Ratio", *JPM* 40(5), 2014. https://papers.ssrn.com/abstract=2460551 | ACAD | selection / multiple testing |
| P3 | Bailey & López de Prado, "Stop-outs under serial correlation and the triple penance rule", *J. Risk* 18(2), 2015. https://www.risk.net/journal-of-risk/2435335/stop-outs-under-serial-correlation-and-the-triple-penance-rule | ACAD | drawdown vs expectation |
| P4 | Harvey & Liu, "Backtesting", *JPM* 41(1), 2015. https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF | ACAD | nonlinear haircut |
| P5 | McLean & Pontiff, "Does Academic Research Destroy Stock Return Predictability?", *J. Finance* 71(1), 2016 | ACAD | expect decay (−26% OOS, −58% post-publication) |
| P6 | Falck, Rej & Thesmar, "When do systematic strategies decay?", *Quant. Finance* 22(11), 2022. https://cfm.com/why-and-how-systematic-strategies-decay/ | ACAD | decay drivers |
| P7 | Wiecki et al., "All that Glitters Is Not Gold", Quantopian, 2016 (888 algos; backtest Sharpe R² < 0.025 for OOS) | PRAC/ACAD | backtest ≠ live; more backtests → bigger gap |
| P8 | Liu, "Evaluating Structured Strategy Backtests: Peer Benchmarks, Regime Timing, and Live Performance", arXiv 2604.18821, 2026 (1,726 live strategies; preprint) | ACAD | judge the residual after the regime/common factor; block bootstrap |
| P9 | Perold, "The Implementation Shortfall: Paper versus Reality", *JPM* 14(3), 1988 | ACAD | trade-level paper-vs-live decomposition |
| P10 | Frazzini, Israel & Moskowitz, "Trading Costs", AQR, 2018. https://papers.ssrn.com/abstract=3229719 | ACAD/PRAC | realised cost vs model, residual as drift signal |
| P11 | Philips, Yashchin & Stein, "Using Statistical Process Control to Monitor Active Managers", *JPM* 30(1), 2003 | ACAD | CUSUM on performance vs expectation |
| P12 | López de Prado, "The 10 Reasons Most Machine Learning Funds Fail", *JPM* 44(6), 2018 | ACAD/PRAC | assembly line; reconcile backtest with live |
| P13 | Lo, "The Statistics of Sharpe Ratios", *FAJ* 58(4), 2002 | ACAD | SE of Sharpe; autocorrelation |
| P14 | Magdon-Ismail et al., "On the Maximum Drawdown of a Brownian Motion", *J. Appl. Prob.* 41, 2004 | ACAD | expected-drawdown distribution |
| P15 | Grinold & Kahn fundamental law (summaries + critique) | PRAC [2nd] | breadth needs independence; capacity |
| P16 | Millennium pod rules (~5% DD → half capital, ~7.5% → out), via WSJ/eFinancialCareers | PRAC [2nd, firm-unconfirmed] | scale before kill |
| P17 | Shrinkage-adjusted Sharpe (James–Stein) | ACAD [2nd] | shrink small-n estimates |
| P18 | Sharma et al., "Towards Understanding Sycophancy in Language Models", ICLR 2024. https://arxiv.org/abs/2310.13548 | ACAD | no anchors in prompts |
| P19 | Turpin et al., "Language Models Don't Always Say What They Think", NeurIPS 2023. https://arxiv.org/abs/2305.04388 | ACAD | biased context gets rationalised |
| P20 | Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR 2024. https://arxiv.org/abs/2310.01798 | ACAD | verify externally, not by re-reading |
| P21 | Chen et al., "Program of Thoughts Prompting", TMLR 2023. https://arxiv.org/abs/2211.12588 | ACAD | numbers from code |
| P22 | Tam et al., "Let Me Speak Freely?", EMNLP 2024. https://arxiv.org/abs/2408.02442 | ACAD | format constraints degrade reasoning; reason first, format last |
| P23 | Lou, "Anchoring Bias in LLMs", 2024; Zhou et al., "Are LLMs Rational Investors?", 2024 | ACAD | anchoring |
| P24 | "Failing to Falsify: … Confirmation Bias in Language Models", 2026, arXiv 2604.02485 | ACAD [2nd] | prompt for counterexamples |
| P25 | Majumder et al., "DiscoveryBench", ICLR 2025. https://arxiv.org/abs/2407.01725 | ACAD | unaided discovery is weak; LLM generates hypotheses, code tests |
| P27 | Halawi et al., "Approaching Human-Level Forecasting with Language Models", NeurIPS 2024 | ACAD | calibrated forecasts, Brier |
| P28 | Anthropic, "Extended thinking tips" (high-level instructions first) | VEND | do not over-script reasoning |
| P29 | "What Prompts Don't Say", 2025; "DETAIL Matters", 2025 | ACAD [2nd] | specify procedure, leave reasoning open |
| P30 | Heuer, *Psychology of Intelligence Analysis*, CIA, 1999, ch. 8 (ACH) | PRAC | competing hypotheses, disconfirming evidence |
| P31 | Klein, "Performing a Project Premortem", *HBR*, 2007 | PRAC | premortem on each action |
| P32 | Lord, Lepper & Preston, "Considering the Opposite", *JPSP* 47(6), 1984 | ACAD | consider-the-opposite beats "be unbiased" |
| P33 | Mellers, Tetlock et al., *Psych. Science* 25(5), 2014 (2025 reanalysis disputes parts) | ACAD | tracking and scoring forecasters |
| P34 | Brier, *Monthly Weather Review* 78(1), 1950 | ACAD | scoring probability calls |
| P35 | Nosek et al., "The Preregistration Revolution", *PNAS* 115(11), 2018 | ACAD | rules before results |
| P36 | Kahneman, Lovallo & Sibony, "Before You Make That Big Decision…", *HBR*, 2011 | PRAC | audit the process of a recommendation |
| P37 | Gawande, *The Checklist Manifesto*, 2009 (READ-DO vs DO-CONFIRM) | PRAC [2nd] | checks as a do-confirm pause point |
| P38 | Haynes et al., *NEJM* 360, 2009 (surgical checklist) | ACAD | short checklists work |
| P39 | Degani & Wiener, NASA CR-177549, 1990 | ACAD/PRAC | checklist design and length matter |
| P41 | Chen et al., "FinQA", EMNLP 2021 | ACAD | LLM numeric reasoning over financials is weak |

**Gaps, stated:**
- No primary public document was found on how Man AHL, AQR or Two Sigma kill or scale a strategy.
- Review cadence (daily vs weekly vs monthly checks) is a synthesis, weakly sourced.
- P40 (LLM financial-statement analysis) is withdrawn on arXiv and is not used.

## 3. Design principles for an LLM analyst review (each cites its basis)

1. **Two layers, never merged.**
   - CHECKS: a short, fixed, deterministic DO-CONFIRM list with a read-state (`could_not_look` ≠ 0). [P37, P38, P39, P29]
   - ANALYSIS: goal-framed and open. [P22, P28, P29]
2. **No number comes from the model's own token stream.** Every figure is computed by a script and quoted with its
   population. [P21, P41]
3. **Every leg, every window, against its own expectation.**
   - Windows: lifetime, 90d, 30d and 7d, compared with the leg's own backtest distribution at the same n (a live
     percentile, not up/down).
   - Expect a haircut that grows with how many variants were tried. [P1, P4, P5, P7, P8, P13]
4. **Small n defaults to "inconclusive", quantified.**
   - State the standard error or the band and the n that would answer; a red week is not a finding.
   - Use a sequential test (CUSUM) for decay rather than reacting to windows. [P1, P11, P13, P17]
5. **Judge the residual.** Take out the instrument/regime move and the cost before calling anything decay; attribute
   paper vs reality per trade (entry delay, execution, missed fills, exit, sizing). [P8, P9, P10]
6. **Count comparisons.** Reviewing ~30 legs at 5% gives ~1.5 false alarms. [P2, P4]
7. **Competing hypotheses for every material question.**
   - Noise is always one of them.
   - State what each predicts that the others do not, run the discriminating test, and look for disconfirming
     evidence. [P30, P24, P32, P25]
8. **Hunt surprises explicitly,** including good news that looks too good. [P32, P7]
9. **No anchors.** Do not feed the analyst prior verdicts or the hoped-for conclusion; read prior reviews for their
   calls and checks, not their framing. [P18, P19, P23]
10. **Verify externally.** Check claims with code or data, not by self-reflection. [P20]
11. **Premortem every proposed action.** [P31, P36]
12. **Every call is a calibrated, falsifiable forecast with a pre-registered check and a resolution point.** The next
    run grades it (Brier) before doing anything else. [P27, P33, P34, P35]
13. **Scale before kill; size drawdowns against the expected-drawdown distribution.** This repo's analogue is
    tune-before-demote and the demo floor; nothing halts. [P3, P14, P16]
14. **Reason in prose, then fill the template.** [P22]
15. **Rank by money at stake, not by recency.** This is the operator's priority and the measured gap in § 1. It is our
    own design choice, and no source above prescribes it.

## 4. The performance-review redesign (PR #20854)

`.claude/skills/performance-review/SKILL.md` now opens with four layers:

- **Layer 0 — prior calls.** Re-run each previous call's own check, grade it hit / miss / unresolved / void, and keep
  a Brier series. Any action that did not happen gets one line on why, then is re-filed or killed.
- **Layer 1 — CHECKS C1–C12.** Each check names the script that computes it.
  - Windows: lifetime/90d/30d/7d per leg.
  - The live-vs-own-backtest band.
  - Interim decay.
  - Attribution (`live_bt_trade_join.py`, `real_money_close_attribution.py`, `giveback_census.py`).
  - Cost drift (`realized_slippage.py`).
  - Baselines (`live_review_grade.py`, `desk_grade.py`, `claude_role_grade.py`).
  - TP doctrine, data coverage, grading informativeness, the research pipeline (read from research-ops), books and
    benchmarks, and the backlog gate.
- **Layer 2 — ANALYSIS (A1–A6).**
  - Read wide context and search before claiming.
  - Pick 3–7 material questions by money.
  - Compete hypotheses with noise always present; test, residualise, count comparisons and verify externally.
  - Hunt surprises and look across legs.
  - Decide with a pre-registered check and a premortem.
- **Output.** A fixed markdown template (`0 Prior calls · 1 CHECKS · 2 ANALYSIS · 3 Decisions · 4 Not done`) plus
  new JSON fields: `prior_calls_scorecard`, `checks`, `analysis`, `calls`.

Other changes in the same PR:
- The deterministic rubric is relabelled as check C9 and is no longer the session's centre of gravity.
- `/perf-followup` now starts from `calls[]` and `analysis.questions[]` and tests them rather than redoing them.
- The manager's review-prep line no longer says "numbers only".
- The existing operational procedures (diag pulls, bucket pre-filter, blind grade, live review, desk, drain, books)
  are kept as a reference appendix.

**Missing instruments (filed as rows, not hand-rolled):** `PERF-CHECKS-SCORECARD`, one script that prints C1 + C3:
- the four-window per-leg scorecard;
- the live percentile in the own-backtest band;
- a per-leg CUSUM on standardised per-trade R residuals against the Stage-0 mean;
- the comparison count.

## 5. Per-skill audit

**Scope** (manager, 2026-10-28 07:15Z): this lane owns performance-review, perf-followup and the shared pattern
([`docs/reference/llm-analyst-skill-design.md`](../reference/llm-analyst-skill-design.md), PR #20855). The other skills
were split to parallel lanes:
- `SKILL-DESIGN-SYSTEM`: weekly-audit and health-review.
- `SKILL-DESIGN-MODEL`: ml-review and frontier-research.
- `SKILL-DESIGN-RESEARCH`: research-ops and the programme review.

This lane had also measured live-trade-review and research-ops before the split. Those findings are recorded below
for whoever owns them.

| Skill | Track | Measured failure mode | Basis | Disposition |
|---|---|---|---|---|
| performance-review | TRADING | **both**: a scripted rubric core, plus week-only, hypothesis-free, memory-less analysis (§ 1) | § 2–3 | **redesigned here** (§ 4) |
| perf-followup | TRADING (+MODEL hooks) | **mostly sound; loose on calibration and memory.** Measured over all 3 runs (W41–W43): 8 of 8 units ran and were read, 1 Tier-3 change (#19513). But confidence was ordinal only, lessons had no check, Track 1's cause set lacked *noise*, 0 hypothesis / surprise / premortem keys appeared across the 3 records, and the skill said Sonnet/$6 while the productive W43 run was Opus/$15 (spent $14.28) | P30, P31, P33, P34 | **redesigned here**: it is the testing half; noise added as a cause; each lesson gets `p` and a check; Step 0 grades lessons; model and ceiling aligned |
| live-trade-review | TRADING + MODEL | **too scripted.** Guardrails plus an empty table decide most calls: last 50 rows hold 26 / flag 12 / none 11 / close 1, 0 tighten or move_tp; a priced option on 1 of 98 rows; confidences all in {0.50, 0.55, 0.60}; the prompt contradicts itself (":16 a tool answers it" vs ":10 best decision now"; :143 restricts thin-cell calls to hold/tighten); no hold-vs-random baseline | T1, T5, T6; P18, P19, P23, P27, P34; practice review § E | **not edited (no owner in the split)**. Evidence and proposed fixes are on row `LTR-PRACTICE-REDESIGN` (note 2026-10-28). Proposed text: :16 → "a decision, priced where pricing exists … name the strongest alternative to holding"; :143 → allow the § 3b actions with `p` defined for hold; :157 → an overlay may raise or lower confidence |
| research-ops | ops (both) | **appropriately mostly CHECKS; loose in one place: handoffs never close.** `needs_review_left` = 28 on 15 consecutive records with 0 triaged on the last 4; the `ml_health` shortfall sits in the handoff of 24 of 66 records; Tier-3 candidates are carried in 27 of 66; there is no surprises slot | P35, P37, P39; R6 | **for `SKILL-DESIGN-RESEARCH`**: a Layer 0 that ages handoffs (3 consecutive records → one owner); a `surprises[]` field in the run record; a dedicated triage lane for the 28 `needs_review` units |
| health-review, weekly-audit | ops | not measured by this lane | — | `SKILL-DESIGN-SYSTEM` |
| ml-review, frontier-research | MODEL | not measured by this lane | — | `SKILL-DESIGN-MODEL` |
| close-out | ops | not measured; a completion checklist (do-confirm) is the right shape for it | P37 | no change proposed |

**Rows:**
- `ANALYTIC-SKILL-DESIGN` is this lane.
- `PERF-CHECKS-SCORECARD` is the missing C1+C3 instrument.
- `LTR-PRACTICE-REDESIGN` holds the LTR audit note.
