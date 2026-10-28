# LLM analyst skill design — the shared pattern for every recurring review

> **Doc status:** `unknown` · category `lookup` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**What this is.** The one design that every recurring analytical or monitoring skill follows: performance-review,
perf-followup, health-review, weekly-audit, ml-review, frontier-research, research-ops and the programme review.
Lanes redesigning those skills adopt it and **point at it rather than restating it**. It authorizes nothing. A binding
operator rule (CLAUDE.md, `docs/CLAUDE-RULES-CANONICAL.md`) wins any conflict.

**Why (operator, 2026-10-28, paraphrased by the manager):** the reviews were either *"not structured enough and do no
deep research or thinking"* or *"too structured: we feed it statistics and it spits out deterministic statistics, not
using the LLM at all."* The ask was to find the design that uses the LLM's wide-context analysis **and** keeps a
format that guarantees what must be checked. The first measured case is the performance review. It had both failures
at once: a scripted grading core plus week-only reads with no hypotheses and no memory of prior calls. The
measurements are in `docs/research/analytic-skill-design-2026-10-28.md` § 1 (lane `ANALYTIC-SKILL-DESIGN`).

## 1. The pattern: four layers, never merged

| Layer | Done by | Produces | Must not |
|---|---|---|---|
| **0. Prior calls** | the LLM, re-running each check the last run's `calls[]` named | each call `hit / miss / unresolved / void`; a Brier series; one line on every action that did not happen | re-argue a call instead of running its check |
| **1. CHECKS** | scripts; the LLM runs them and states populations | a fixed, short list of must-checks, each with its script, population and windows; a failed read is `could_not_look`, never `0` or omitted | interpret, rank, or compute a number itself |
| **2. ANALYSIS** | the LLM | a few material questions, each with competing hypotheses, the test run and its result, the survivor, a probability and the impact; surprises; cross-cutting causes | paraphrase the CHECKS; end on "n too small"; inherit a prior run's framing |
| **3. Decisions** | the LLM | each call is a checklist row, a queue unit or a pipeline item carrying a **pre-registered check** (`command`, `rule`, `resolves_when`), or `no action, because …` | write a memo; enact anything above its tier |

**Division of labour.** Code does every number; the LLM never computes in its own tokens [S1, S2]. The LLM does what
code cannot: read wide context, propose explanations, choose the test that discriminates between them, notice what
does not fit, and weigh the decision [S3]. The CHECKS layer is a *do-confirm* list: short, deterministic and
confirmable [S4, S5]. The ANALYSIS layer is framed by a goal, not scripted step by step. Over-scripted reasoning
degrades it [S6, S7], and under-specified procedure regresses [S8]. So: **specify procedure precisely, and leave
reasoning open.**

## 2. The CHECKS layer: what every skill's list must cover

Each skill picks its own checks. Every list must satisfy these rules:

- **Windows: lifetime + medium + recent, every run** (for trading, lifetime / 90d / 30d / 7d). Never "since the last run"
  alone.
- **Against its own expectation**: a pre-declared baseline, SLO, backtest band or incumbent. A threshold set during the
  review is not a check [S9].
- **Decay or drift by a sequential test** (CUSUM or equivalent), not by reacting to one window [S10].
- **Coverage**: what share of the population the check could read, with read-state beside every count.
- **Each check names its script.** A missing instrument is listed as `could_not_look: no instrument` plus the row that
  builds it. Never hand-roll a cruder substitute in-session.

## 3. The ANALYSIS layer: the prompts every skill carries

1. **Read wide before you form a view.** Read the subject's whole history, its evidence records, related subjects,
   the last few runs' **calls and checks** (not their conclusions), open rows that name it, and operator priorities.
   **Search the repo before claiming a new finding.**
2. **Choose 3–7 material questions by impact** (money, risk, or blocked work), not by recency.
3. **Compete hypotheses** [S11, S12, S13].
   - Write at least two hypotheses; one is always *noise / expected variation*.
   - For each, state what it predicts that the others do not, in data you can read.
   - Run the discriminating test now, or file it as a unit with the rule written first.
   - Record what was eliminated and by what evidence.
4. **Judge the residual.** Remove what the environment did (regime, the instrument, a shared upstream) before
   blaming the subject [S14].
5. **Count comparisons.** Scanning 30 things at 5% flags ~1.5 by chance [S15].
6. **Hunt surprises.** List what contradicts a prior run, a doc or the expectation, including good news that looks too
   good. If nothing surprised you, say what you checked [S12, S16].
7. **Look across subjects.** One mechanism behind several symptoms is one structural row, not N local ones.
8. **Verify against data, not by re-reading your own reasoning** [S17].
9. **Premortem each decision.** Assume it made things worse three months from now and say why [S18].
10. **State confidence as a probability**, attach a pre-registered check, and let the next run grade it [S19, S20,
    S21].

**Neutral framing.** Do not put the hoped-for conclusion, a prior verdict, or "we suspect X" into a skill's analysis
prompt. Models tailor answers to the framing, then rationalise the result [S22, S23, S24]. There is **no quota** of
findings, proposals or demotions. "Nothing material changed" is a valid conclusion only when the falsification attempt
behind it is shown.

**Reason first, format last.** Write the analysis in prose, then copy it into the structured record [S6].

## 4. Output template (every skill's markdown follows this order)

```
# <Review> <date> — <one sentence: what most affects money/risk now>
## 0. Prior calls   — call · p · check re-run · hit/miss/unresolved/void · did the action happen?
## 1. CHECKS        — tables only; population + windows on each; could_not_look listed
## 2. ANALYSIS      — per question: hypotheses · test · result · survivor · p · impact; then Surprises
## 3. Decisions     — ranked by impact: call · decision · tier · pre-registered check · ending (row/unit/PI id)
## 4. Not done      — what was not run or not read, and why
```

The JSON record carries the same four blocks: `prior_calls_scorecard`, `checks`, `analysis`, `calls`. The
performance-review response template (`comms/schema/performance_review_response.template.json`) is the reference
shape.

## 5. Anti-patterns (each measured in this repo's reviews, 2026-09-24…10-21)

- **Week-only windows**: reading since the last run and ignoring each subject's whole record.
- **Restating numbers**: an ANALYSIS section that paraphrases the CHECKS tables.
- **Predetermined outcomes**: a dispatch or skill line that fixes the conclusion ("numbers only", "find N issues",
  a default action), or a deterministic rubric treated as the judgement.
- **Amnesia**: a recommendation repeated without saying why it did not happen; a "new" finding the repo had already
  answered.
- **Crowding out**: mechanics findings filed under the wrong review, displacing the review's own subject.
- **Dead-end endings**: "n too small", "monitor", or "investigate" with no owner, no n and no check.

## 6. Grading the reviewer (closing the loop)

- **Every run starts with Layer 0.** Below 10 resolved calls, report the counts and mark the Brier score
  `INDETERMINATE`.
- **Keep the series in the JSON record** so calibration is visible across runs.
- **Act on a skill that keeps missing**: one that is persistently overconfident, or whose actions never happen, needs
  its skill amended. That is a versioned PR with the evidence, as perf-followup Track 2 already does for the Claude
  reviewer and desk briefs.

## Sources

Tags: **ACAD** (academic), **PRAC** (practitioner), **VEND** (vendor). The full table, with URLs and verification
notes, is in `docs/research/analytic-skill-design-2026-10-28.md` § 2.

| id | source | tag |
|---|---|---|
| S1 | Chen et al., "Program of Thoughts Prompting", TMLR 2023 | ACAD |
| S2 | Chen et al., "FinQA", EMNLP 2021 | ACAD |
| S3 | Majumder et al., "DiscoveryBench", ICLR 2025 (unaided LLM discovery is weak; LLM proposes, code tests) | ACAD |
| S4 | Gawande, *The Checklist Manifesto*, 2009 (read-do vs do-confirm) | PRAC |
| S5 | Haynes et al., NEJM 360, 2009; Degani & Wiener, NASA CR-177549, 1990 | ACAD |
| S6 | Tam et al., "Let Me Speak Freely?", EMNLP 2024 (format constraints degrade reasoning) | ACAD |
| S7 | Anthropic, "Extended thinking tips" (high-level instructions first) | VEND |
| S8 | "What Prompts Don't Say", 2025; "DETAIL Matters", 2025 | ACAD |
| S9 | Nosek et al., "The Preregistration Revolution", PNAS 2018 | ACAD |
| S10 | Philips, Yashchin & Stein, "Using Statistical Process Control to Monitor Active Managers", JPM 2003 | ACAD |
| S11 | Heuer, *Psychology of Intelligence Analysis*, CIA 1999, ch. 8 (analysis of competing hypotheses) | PRAC |
| S12 | Lord, Lepper & Preston, "Considering the Opposite", JPSP 1984 | ACAD |
| S13 | "Failing to Falsify: … Confirmation Bias in Language Models", arXiv 2604.02485, 2026 | ACAD |
| S14 | Liu, "Evaluating Structured Strategy Backtests", arXiv 2604.18821, 2026; Perold, "The Implementation Shortfall", JPM 1988 | ACAD |
| S15 | Harvey & Liu, "Backtesting", JPM 2015; Bailey & López de Prado, "The Deflated Sharpe Ratio", JPM 2014 | ACAD |
| S16 | Wiecki et al., "All that Glitters Is Not Gold", Quantopian 2016 | PRAC/ACAD |
| S17 | Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR 2024 | ACAD |
| S18 | Klein, "Performing a Project Premortem", HBR 2007; Kahneman, Lovallo & Sibony, HBR 2011 | PRAC |
| S19 | Brier, Monthly Weather Review 1950 | ACAD |
| S20 | Mellers, Tetlock et al., Psych. Science 2014 (a 2025 reanalysis disputes parts) | ACAD |
| S21 | Halawi et al., "Approaching Human-Level Forecasting with Language Models", NeurIPS 2024 | ACAD |
| S22 | Sharma et al., "Towards Understanding Sycophancy in Language Models", ICLR 2024 | ACAD |
| S23 | Turpin et al., "Language Models Don't Always Say What They Think", NeurIPS 2023 | ACAD |
| S24 | Lou, "Anchoring Bias in Large Language Models", 2024 | ACAD |
