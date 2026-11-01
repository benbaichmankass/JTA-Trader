# ML decision models — DIAGNOSIS: what the ML line has been doing, measured

> **Doc status:** `live` · category `evidence` · last verified `2026-11-01` · lane `ML-DECISION-MODELS` (row `docs/claude/work/checklist/ML-DECISION-MODELS.json`, roadmap `L-ML-LIVE`)

Gates this adds or changes: none.

**Question (operator, 2026-11-01):** *"what we're not doing correctly and why this is so difficult."*
**Population (MEASURED):** every research unit in `research/queue/**.yaml` that has at least one result record under
`research/results/<id>/` **and** is an ML / AI-trader unit (theme `ml_health`, or an ML term in its title). 1,500 result
directories, 7 with no unit file, **175 ML units with results**. Each unit is classified from its title, question and
registered `decision_rule` by `scripts/research/ml_decision_diagnosis.py` (regex classifier, self-tested); the per-unit
table with the matched fields is [`diagnosis_table.json`](diagnosis_table.json). The verdict is the unit's LAST record.
The M19 post-mortem's 13 retired manifests (`docs/research/M19-ai-trader-postmortem-and-staged-path-2026-09-28.md` §1)
predate the queue and are counted separately below. Re-run: `python3 scripts/research/ml_decision_diagnosis.py --out <file>`.

## The table (counts of units, n = 175)

| what the model was asked | units | label source | metric registered | pooled across symbols | median test n | verdicts (pass / fail / indet. / n.a.) |
|---|---:|---|---|---:|---:|---|
| regime / vol head | 91 | market bars | log-loss / F1 (90), other (1) | 0 | 40,000 rows | 23 / 29 / 36 / 3 |
| direction head | 16 | market bars | log-loss / F1 | 0 | 40,000 rows | 0 / 5 / 11 / 0 |
| entry filter / meta-label / regime gate | 22 | **a strategy's trades** | net R (20), statistical (2) | 0 | 400 trades | 5 / 16 / 1 / 0 |
| in-trade exit / active management | 21 | **a strategy's trades** | net R (12), statistical (9) | 1 | 1,011 trades | 2 / 13 / 6 / 0 |
| plumbing / parity / drift | 21 | none | — | 1 | — | not a decision test |
| other | 4 | mixed | mixed | 0 | — | 0 / 0 / 3 / 1 |

Cross-tab of label source × metric (MEASURED): **market-bar labels × statistical metric 108**; market-bar × net R
**0**; strategy-trade labels × net R 32; strategy-trade × statistical 12; no label 21; other 2.
**Units whose label is market bars AND whose metric is net R AND that pool across symbols: 0 of 175.**
The M19 retirements are the same shape: 12 of 13 heads predicted a price proxy (regime / direction) graded on macro-F1;
the 13th predicted a trade outcome at n_eval = 20; none produced a trade (post-mortem §1, RECORDED there).

## The causes the table supports, each with its count

1. **The two halves of the work never met (108 vs 32, overlap 0).** Market-bar models had the sample (median 40,000
   rows) but were scored on log-loss / F1, which says nothing about whether acting on them makes money — 132 of 175
   units carry no cost stack because their metric cannot. Net-R tests had the right metric but labelled **a strategy's
   own trades**, so the model could only veto or reshape what the strategy already chose. Nothing ever asked "given the
   market at this bar, is a long, a short or nothing worth it net of cost?" — the operator's ENTRY question.
2. **Labels inherited from strategy trades ⇒ n too small and selection inherited (44 units).** Median test n 400 trades
   for entry filters, 1,011 for exit units, against 40,000 rows on the market side (100× less). 23 of the 32
   strategy-trade net-R units FAILED; of the 6 passes, two (RQ-20260922-007 n=73, RQ-20260927-001 n=352) were overturned
   by the multi-fold rerun RQ-20260927-002 (n=1,041 OOS, −0.014 R/trade), two are single-symbol regime gates at n=49 /
   unread (RQ-20261008-902/-903), one is a scoping arm with an ASSUMED accuracy (RQ-20261012-75b2-05) and one a refine
   step (RQ-20261029-5785-04). None became a live decision.
3. **Per-symbol fragmentation (127 per-symbol, 2 pooled, 46 unstated).** Every regime / direction head was trained one
   symbol at a time (BTC, ETH, SOL, MES), so each model saw one market's history and each verdict was a per-symbol
   split of an already small effect. The frozen 60-perp universe (`bp2-f4271084b120`, 146,158 harness trades) has been on
   `main` since 2026-10-30 and no decision model has read it.
4. **Most verdicts could not decide (61 of 175 indeterminate, 35%).** Mostly statistical bake-offs whose registered
   deltas (≥ +0.01 macro-F1, ≤ 0.002 nats) are inside fold noise — learner-family comparisons on a target that is not
   the decision.
5. **Leakage controls: present, not a cause.** Purged / embargoed CV is standard in these units (and §5 of the M19
   post-mortem reaches the same reading); this table found no unit failing for leakage.

**Why this is difficult (one line):** the programme kept improving the *estimator* (learner families, feature lifts,
foundation models) on targets that are not decisions, and kept testing *decisions* only on the few thousand trades a
strategy happened to take. The fix this lane tests (DESIGN.md): bar-level labels built from market data, the decision
itself as the output, scored in net R per decision over a sealed held-out window, one model pooled over 60 symbols.

## What this does not do
It changes nothing and promotes nothing. The classifier is a regex heuristic: `diagnosis_table.json` carries every
row's matched task / label / metric so a reader can overturn any single classification; the headline zero (market-bar
× net R × pooled) was checked by listing every net-R market-bar candidate by hand (all 15 regime heads first matched
were macro-F1 units whose rules merely disclaim "NOT a P&L figure" — the classifier was corrected to read the registered
`statistic` first).
