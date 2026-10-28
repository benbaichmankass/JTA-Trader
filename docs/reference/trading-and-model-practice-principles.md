# Trading and model practice principles (canonical list)

> **Doc status:** `unknown` · category `lookup` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**What this is.** A short, numbered list of principles that skills point at. It is drawn from what real-world practice
and published evidence show. Every line cites the evidence behind it. The evidence lives in the dated practice reviews
(first: [`docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md`](../research/practice-review-trade-mgmt-and-ai-2026-10-28.md),
whose `[S#]` tags are used below). The weekly "Practice & methodology refresh" in
[`.claude/skills/frontier-research/SKILL.md`](../../.claude/skills/frontier-research/SKILL.md) keeps it current. It
edits this list in place, dates each change, and writes a new dated review.

**What this is not.** It is not a gate and not a config. It authorizes nothing. A principle that conflicts with a
binding operator rule (CLAUDE.md, `docs/CLAUDE-RULES-CANONICAL.md`, the TP doctrine, the soak doctrine) loses to that
rule. The conflict is then raised to the manager as a question; nobody resolves it by editing either side.

**Two research tracks** (operator decision 2026-10-28): **TRADING** covers how to trade better (strategies, entries,
exits, active management, sizing, costs, venues). **MODEL** covers how to build a better AI trader (data, labels,
features, training, evaluation, model families, infra, desk-as-teacher). **RESEARCH-OPS** applies to both.

Last revised: 2026-10-28 (lane `PRACTICE-RESEARCH-TRADE-MGMT-AI`).

## TRADING

- **T1.** Judge any in-trade intervention (human, LLM or rule) against **hold-to-exit AND a matched random intervention** (same count and type of actions at random checkpoints). Experts' exits often lose to random ones. [S1, S2, S3]
- **T2.** The value of a stop, trail or cut depends on the return process. It helps under momentum or regime switching and hurts under mean reversion. Evaluate it **per leg and per regime**, never pooled. [S4, S5, S30]
- **T3.** Evaluate every management rule **net of the full cost stack**. Cost is what turns tight stops from helpful into harmful. [S5, S6]
- **T4.** Size stops and trails from **volatility and the intended holding period**, not from the entry price. A breakeven move has no special standing. [S9, S10, S11]
- **T5.** **Separate the check-in clock from the action rate.** Check in on the position's own bar and on events, and record "no action" as a decision. Large, information-driven actions add value; frequent small tweaks do not. [S12, S15]
- **T6.** Let **closed-list reasons** drive in-trade action: level broken, momentum reversal, volatility change against the position, thesis invalidated, time. Never act on salience of P&L alone. [S1, S15]
- **T7.** Put giveback limits at the **account or day level**. A per-trade giveback exit is a hypothesis to test, not established practice. [S16]
- **T8.** Isolate the exit's contribution with **fixed or random entries** before crediting management. [S17]
- **T9.** Profit targets are justified for **mean-reversion** legs. For **trend** legs, practice lets a trail do the work. Under our TP doctrine, measure that cost; do not assume it. [S9, S25]
- **T10.** Partials and scaling out **reshape the distribution** of outcomes; the evidence does not show they add expectancy. Test them as arms, never as defaults. [S26]

## MODEL

- **M1.** **Label with the path-dependent, cost-net outcome of the exit policy actually traded**: triple-barrier from each decision state, or the priced outcome of every action. A binary label or a gross label is not enough. [S50, S38]
- **M2.** **Validate with purged, embargoed walk-forward or combinatorial purged CV**, grouped by trade when several decision points share one price path. [S50]
- **M3.** **Control leakage** explicitly: point-in-time features, a hold-out after any pretrained model's release, and masked identifiers for LLM inputs. [S55, S53]
- **M4.** **Pre-register the decision rule and the analysis plan** (transforms, windows, exclusions, strata). Count every configuration tried. [S20, S49]
- **M5.** **Deflate for selection**: deflated or probabilistic Sharpe, PBO, and a t-hurdle above 3 for new effects. Confirm once on a fresh window. [S45, S46, S47, S48]
- **M6.** **Beat random and simple-rule baselines at the same decision points**, net of cost. A gain in AUC or Brier score over a constant is feature lift, not edge. [S1, S20, S42]
- **M7.** **Stratify evaluation by regime** (trend and volatility). LLM and ML edges are regime-asymmetric. [S22, S4]
- **M8.** For any trade-management model, **evaluate the check-in cadence and the trigger set as factors**, with action-level and no-action lift reported separately. [S12, S1]
- **M9.** **Prefer a supervised meta-model over the best rule** to an end-to-end policy. Use RL only as fine-tuning initialized from it. Do not use pure imitation of a teacher's choices as the target. [S19, S38, S39]
- **M10.** **Promote on out-of-sample decision value net of cost** against the incumbent, the best rule and the random control. Agreement with a teacher never gates promotion. Monitor live decay with a CUSUM after promotion. [S1, S43, benchmark S14]

## RESEARCH-OPS (both tracks)

- **R1.** Every design arm **names its practice precedent** (source and tag) or is declared `novel`. [operator 2026-10-28]
- **R2.** Run an **assembly line, not lone end-to-end builders**, and measure each station's quality on its own. [S18]
- **R3.** **A live or paper book establishes mechanics, not edge.** Treat history as having no true OOS and do not tweak models on live results. [S20, S40, S41]
- **R4.** **Plan for decay.** Expect large out-of-sample and post-publication shortfalls. [S43]
- **R5.** **More backtests per idea means a larger live gap.** The count of backtests is an anti-metric. [S42]
- **R6.** **Refresh this list weekly from outside evidence**, and turn every gap it reveals into a checklist row or a queue unit. Never leave it as a memo. [frontier-research]
