# Research-ops and programme-review redesign — diagnosis, practice, design (2026-10-28)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-28` · registered in [`../DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `SKILL-DESIGN-RESEARCH` (dispatched by the manager, session_01AFoLuJi1vLTnYv9LbP6539) · **Tier-1: nothing here changes a config, a roster, a queue unit or a programme tree.**

**Operator, 2026-10-28 ~07:15-07:20Z (paraphrased by the manager, binding):** every recurring weekly review or monitoring
session is redesigned today on researched best practice, so tonight's runs feed Thursday planning with good information.
Avoid two failure modes: **too loose** (the session skims and does no deep analysis) and **too scripted** (we feed it
statistics and it restates them, with predetermined outcomes). Use the model's ability to reason over wide context **and**
keep a fixed format that guarantees the checks. Research is **two tracks: TRADING** (how to trade better) and **MODEL**
(how to build a better AI trader model).

What this lane changed: [`.claude/skills/research-ops/SKILL.md`](../../.claude/skills/research-ops/SKILL.md) (new top
section "How a pass runs"), a new skill [`.claude/skills/programme-review/SKILL.md`](../../.claude/skills/programme-review/SKILL.md)
(the weekly review's procedure previously lived only in the routine prompt), and the CHECKS script
[`scripts/research/research_ops_checks.py`](../../scripts/research/research_ops_checks.py). Shared pattern:
`docs/reference/llm-analyst-skill-design.md` (lane ANALYTIC-SKILL-DESIGN, PR #20855): its four layers (prior calls,
CHECKS, ANALYSIS, decisions), record blocks and ANALYSIS prompts are pointed at by both skills, not restated; what this
doc adds is the research-specific checks and questions.

## 1. Diagnosis — what the last passes actually did

**Population:** the five newest research-ops records `comms/research/ops/20261027T0925Z.json` .. `20261028T0300Z.json`
(four are ops passes, `20261027T2010Z` is a daily authoring lane), the 2026-10-21 programme review (sections
"Programme review 2026-10-21" in `docs/research/programmes/*.md`), and the CHECKS packet
`research_ops_checks.py --since 7d` run 2026-10-28 ~07:20Z on `origin/main` 5b649d568 (1,475 units; 561 result rows
generated in the 7 days; 416 units graded in the window). All numbers MEASURED from those files unless marked.

| # | what was scored | MEASURED | failure mode |
|---|---|---|---|
| 1 | results read vs rule actually applied | 2110Z: "29 FAILs were read at the unit-title level … per-FAIL arm tables were not opened". 0300Z: "25 result files … read at verdict + power_state level … per-arm tables were not opened". The pass restated the grader's verdict; the grader had already applied the rule. | **too scripted**: restating a verdict the machine already wrote |
| 2 | power checked before reading a verdict | 345 of the 368 pass/fail verdicts graded in the window carry only the power label `accruing` (on rows with n up to 458 trades). The skill said an `accruing` read "cannot answer yet"; the grader and `research_digest.py` treat it as decorative. No producer compares realised n with the unit's `power.expected_n`. | **checks that check nothing**: a label everyone learned to ignore |
| 3 | follow-ups filed vs follow-ups that ran | across the last four records: 24 follow-ups traced; 13 fired, 3 graded, 1 queued unfired, **7 programme nodes still `needs_authoring`** (e.g. the four P1-ATM PASS-confirmation nodes filed 2026-10-27 21:10Z, not authored by the 03:00Z pass, which wrote "check … once the grader closes" again) | **filing as parking**: a node is written, then re-handed-off |
| 4 | failed first tests: diagnosed or logged | **167 of 301 FAILs** graded in the window are named by no queue unit and no programme node (149 TRADING, 18 MODEL). The run-record lines are the template sentence ("configuration closed … family stays open; next = …") with `next` often a generic pointer. | **logged, not diagnosed**: fail-is-not-dead is stated, not done |
| 5 | multiple testing at the batch level | 67 pass / 416 graded = **16 %** overall; batch `RQ-20261026-ed1c` 3 pass of 26, `f08c` 3 of 22, `0142` 2 of 20. The 2110Z record forwarded 3 ed1c PASSes as "Tier-3 candidates" with arm denominators (2, 3, 3) but not the batch denominator (26 units). | **selection without its denominator** |
| 6 | queue health vs research value | the pass's numbers are floor, runnable, fired. Meanwhile MODEL-track learner bake-offs on the 1h regime head keep running and failing (ed1c-31..34, a142-01, RQ-20261027-006 all FAIL in the window) although the 2026-10-21 review already concluded "learner family is second-order". Runnable by track now: TRADING 46, MODEL 12, INFRA 3. | **filling the queue, not asking the next question** |
| 7 | needs_review triage | 28 → 28 → 28 → 28 across the four records; triaged 0, 0, 0, 0 (one unit the pass before). 15 of 28 parked on owner `RESEARCH-TOOLING-GAPS`. | **a bucket nobody empties** |
| 8 | restated numbers vs reasoning | the records are ~90 % counts and handoffs. The one piece of real reasoning in four passes (0300Z: e535-04 "filled 0 of 732 proposals and broke its own stopping rule → scorer defect, not a result") is exactly what a pass is for, and it came from opening a row. | mostly too scripted, occasionally right |

**The programme review (2026-10-21)** is the better half: it states its population, reasons in prose ("the samples are
bounded by one year of live ledger … a re-run before ~2026-12 would re-measure the same n"), and names cross-programme
feeds. Its gaps: **486 of 657** graded units carried no programme field and were counted only in the map, not read into
any plan; it did not grade its own previous calls (there were none to grade — it was the first); the "next 3-4 weeks"
were mostly "waits on build X" with no value ranking; and nothing in its format separates TRADING from MODEL.

## 2. Practice — what we take, and from where

Most of the quant methodology was benchmarked on 2026-10-16
([`research-ops-benchmark-2026-10-16.md`](research-ops-benchmark-2026-10-16.md), 23 sources) and re-verified on
2026-10-28 (practice review, PR #20844, § C, not yet on main). Not repeated here. New for the *operations* design:

| practice | source [tag] | what it becomes here |
|---|---|---|
| **Rank research by expected value of information** — what a study is worth is the decision improvement it buys minus its cost; EVPI is a ceiling that screens questions out early; a portfolio's VOI ranges over orders of magnitude and contradicts expert ranking | Value-of-information literature in health research prioritisation, e.g. [PMC5963256](https://pmc.ncbi.nlm.nih.gov/articles/PMC5963256), [PMC6125050](https://pmc.ncbi.nlm.nih.gov/articles/PMC6125050), SWOG's use of EVSI in trial selection [PMC3933300](https://pmc.ncbi.nlm.nih.gov/articles/PMC3933300) [ACAD] | ANALYSIS step "what to test next": each proposal states *which decision it changes, what we would do on each branch, and the cost*. A test whose both branches lead to the same action has VOI ≈ 0 and is not proposed (finding 6). |
| **Online FDR / alpha-investing** — a stream of tests spends and earns an error budget; generalised alpha-investing controls online FDR with little power loss vs offline BH | Foster & Stine 2008 (via secondary citation); Ramdas, Zrnic, Wainwright & Jordan, *Ann. Stat.* 2018 [arXiv 1603.09000](https://arxiv.org/abs/1603.09000v3) [ACAD] | CHECKS `batches` prints k-of-n per authoring batch; ANALYSIS must quote it beside any PASS it forwards. The formal ledger stays `trial_ledger.py` (row RESEARCH-TRIAL-LEDGER, report-only). |
| **Pre-mortem / prospective hindsight** — assume the plan failed, then ask why | Klein, *HBR* Sept 2007 (via secondary summaries, e.g. [Ness Labs](https://nesslabs.com/?p=9829)) [PRAC; the "30 %" figure is secondhand and not used] | programme review: each programme's top proposal carries one line "if this comes back FAIL, the most likely reason is …", which is also the first variant to queue. |
| **Score your own forecasts** — calibration improves only when predictions are written down and graded | Tetlock & Gardner, *Superforecasting* (2015) and the Good Judgment Project's Brier scoring [ACAD; not re-read by this lane] | every record carries top-level `calls` (prediction, probability, pre-registered check); the next run grades them first, from the CHECKS packet's `previous_calls`. |
| **Hold the entries fixed, use matched controls, confirm on a fresh window** | benchmark § 2; practice review § C.2 [ACAD/PRAC] | unchanged; ANALYSIS checks a forwarded PASS has its confirmation unit (finding 3). |
| **Failure post-mortems as a register** — "track every model tried" (Arnott, Harvey & Markowitz 2019) | benchmark S-list [ACAD] | `fails_without_next` is the register's missing column; ANALYSIS writes the diagnosis per FAIL cluster, not per unit. |

Searches that found nothing usable: a published AHL/Man "graveyard" hypothesis-register process (one search; the
probe returned general overfitting material, so it could find positives in the field). Stated, not hidden.

## 3. Design — two layers, a fixed template, a self-grade

**CHECKS (computed, never judged).** `research_ops_checks.py` writes one JSON packet: pipeline + floor, runnable per
track, results with verdict / grader / power label, batch denominators, FAILs with no successor, follow-up survival,
needs_review stagnation, stale units, previous calls. The session does not recompute these and does not restate them
beyond the one-line headline; it **reads** them.

**ANALYSIS (the session's job, the only part that needs a model).** Fixed questions, open answers, per track:
1. Grade the previous run's calls (hit / miss / not yet, one line each, why).
2. What the window's results MEAN — clusters, not units: what moved our belief about which lever, leg or model family,
   and how much (the batch denominator beside every PASS).
3. Diagnose the failed first tests — per FAIL cluster: which of {design, power, cost drag, regime, harness, idea} and the
   evidence; the variant that tests the diagnosis.
4. What to test next and why — value-ranked by the decision each test changes.
5. Cross-track feeds — TRADING results → MODEL labels/features; MODEL results → TRADING decisions.
6. Calls for next time — 2-5 falsifiable predictions with a probability.

**Guardrails against both failure modes.** Against *too loose*: the template has required fields, a minimum of rows
opened (not titles), and the self-grade. Against *too scripted*: the packet already holds every count, so a sentence
that only repeats a packet number is waste; the template's analysis fields reject "n of m passed"-style restatement
without a "so" clause; and the scripts deliberately rank nothing — value ranking is the session's argument.

**What this does not do.** It changes no grader, no rule and no queue unit. It does not fix the power label (filed:
row `RESEARCH-POWER-CHECK`) and it does not author the 167 missing next tests — tonight's passes and the programme review do.
