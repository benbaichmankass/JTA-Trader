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

Last revised: 2026-10-28 (lane `PRACTICE-RESEARCH-TRADE-MGMT-AI`); weekly refresh 2026-10-28 (lane `PRACTICE-REFRESH`,
session_01AFoLuJpe2bJTErX7QGAmaS): added T11–T12 and M11; strengthened T2, T3 and M6; noted a tension on R3. Evidence in
§ 10 of the practice review (`[S56]`–`[S63]`). T13 added by lane `ROADMAP-PRIORITIES-AM-PRINCIPLE` (2026-10-28, operator rule).

## TRADING

- **T1.** Judge any in-trade intervention (human, LLM or rule) against **hold-to-exit AND a matched random intervention** (same count and type of actions at random checkpoints). Experts' exits often lose to random ones. [S1, S2, S3]
- **T2.** The value of a stop, trail or cut depends on the return process. It helps under momentum or regime switching and hurts under mean reversion. Evaluate it **per leg and per regime**, never pooled. [S4, S5, S30] *Strengthened 2026-10-28 for crypto: stop-loss momentum beat plain momentum across 147 coins, 2015–2022 [S62 ACAD, abstract].*
- **T3.** Evaluate every management rule **net of the full cost stack**. Cost is what turns tight stops from helpful into harmful. [S5, S6] *Strengthened 2026-10-28: for perpetuals the stack includes funding paid over the holding period, which changes the optimal exit schedule itself [S61 ACAD preprint, abstract].*
- **T4.** Size stops and trails from **volatility and the intended holding period**, not from the entry price. A breakeven move has no special standing. [S9, S10, S11]
- **T5.** **Separate the check-in clock from the action rate.** Check in on the position's own bar and on events, and record "no action" as a decision. Large, information-driven actions add value; frequent small tweaks do not. [S12, S15]
- **T6.** Let **closed-list reasons** drive in-trade action: level broken, momentum reversal, volatility change against the position, thesis invalidated, time. Never act on salience of P&L alone. [S1, S15]
- **T7.** Put giveback limits at the **account or day level**. A per-trade giveback exit is a hypothesis to test, not established practice. [S16]
- **T8.** Isolate the exit's contribution with **fixed or random entries** before crediting management. [S17]
- **T9.** Profit targets are justified for **mean-reversion** legs. For **trend** legs, practice lets a trail do the work. Under our TP doctrine, measure that cost; do not assume it. [S9, S25]
- **T10.** Partials and scaling out **reshape the distribution** of outcomes; the evidence does not show they add expectancy. Test them as arms, never as defaults. [S26]
- **T11.** *(added 2026-10-28 refresh)* **Size by forecast volatility, and expect its benefit to differ by asset.** Volatility targeting cut extreme returns and vol-of-vol in all 60+ assets tested. It raised Sharpe only for risk assets with a leverage effect (equities, credit) and was negligible for bonds, FX and commodities. Judge a vol-scaled sizing arm **per asset class**, on tails as well as Sharpe. [S56 ACAD/PRAC]
- **T12.** *(added 2026-10-28 refresh)* **Trade only when the target leaves a no-trade buffer.** Choose the buffer width on after-cost results, then widen it, because a backtest-optimal buffer is too narrow. The same logic caps how often in-trade management may act (T5). [S57 PRAC/VEND; S64 ACAD, secondary]
- **T13.** **Active management is the whole bracket, one action class at a time** (operator, binding, 2026-10-28: *"active management isn't only tightening - it can be any movement in either bracket triggered by developments in the live market data"*). The classes are SL tighten / widen / move-to-structure, TP extend / pull-in / revise, partial / full close, and hold. Each is triggered by live market data and leaves both brackets in place. Each graduates from advice-only to executed on its own registered, net-of-cost test under the risk-adjusted rule `RULE-AM-RISK-ADJUSTED-V1` (operator 2026-10-29). Under that rule, a small pre-stated R cost can buy a large cut in book risk, and the class must still beat a matched random intervention (T1). No class passes it on the landed records (re-grade 2026-10-29). This is a binding rule, and the canonical text is [`docs/ARCHITECTURE-CANONICAL.md`](../ARCHITECTURE-CANONICAL.md) § "Active management". Evidence for the hold baseline: [S1, S2, S3]

## MODEL

- **M1.** **Label with the path-dependent, cost-net outcome of the exit policy actually traded**: triple-barrier from each decision state, or the priced outcome of every action. A binary label or a gross label is not enough. [S50, S38]
- **M2.** **Validate with purged, embargoed walk-forward or combinatorial purged CV**, grouped by trade when several decision points share one price path. [S50]
- **M3.** **Control leakage** explicitly: point-in-time features, a hold-out after any pretrained model's release, and masked identifiers for LLM inputs. [S55, S53]
- **M4.** **Pre-register the decision rule and the analysis plan** (transforms, windows, exclusions, strata). Count every configuration tried. [S20, S49]
- **M5.** **Deflate for selection**: deflated or probabilistic Sharpe, PBO, and a t-hurdle above 3 for new effects. Confirm once on a fresh window. [S45, S46, S47, S48]
- **M6.** **Beat random and simple-rule baselines at the same decision points**, net of cost. A gain in AUC or Brier score over a constant is feature lift, not edge. [S1, S20, S42] *Strengthened 2026-10-28: on a live, contamination-free benchmark most LLM agents posted poor returns and weak risk control [S53 AI-Trader, re-read at abstract level].*
- **M7.** **Stratify evaluation by regime** (trend and volatility). LLM and ML edges are regime-asymmetric. [S22, S4]
- **M8.** For any trade-management model, **evaluate the check-in cadence and the trigger set as factors**, with action-level and no-action lift reported separately. [S12, S1]
- **M9.** **Prefer a supervised meta-model over the best rule** to an end-to-end policy. Use RL only as fine-tuning initialized from it. Do not use pure imitation of a teacher's choices as the target. [S19, S38, S39]
- **M10.** **Promote on out-of-sample decision value net of cost** against the incumbent, the best rule and the random control. Agreement with a teacher never gates promotion. Monitor live decay with a CUSUM after promotion. [S1, S43, benchmark S14]
- **M11.** *(added 2026-10-28 refresh)* **Measure an LLM decision-maker's repeatability before grading its edge.** Re-run the same snapshot k ≥ 3 times. Report agreement on the final decision separately from agreement on reasoning or tool sequence. A recommendation that flips across reruns is noise, not a decision. LLM agents show large run-to-run variance even at temperature 0, and they flip actions between adjacent steps. In one replay harness, decisions repeated in 84% of cases, but tool sequences repeated in only 26%. [S58 ACAD preprint, abstract + snippet; S59 ACAD preprint, abstract]

## RESEARCH-OPS (both tracks)

- **R1.** Every design arm **names its practice precedent** (source and tag) or is declared `novel`. [operator 2026-10-28]
- **R2.** Run an **assembly line, not lone end-to-end builders**, and measure each station's quality on its own. [S18]
- **R3.** **A live or paper book establishes mechanics, not edge.** Treat history as having no true OOS and do not tweak models on live results. [S20, S40, S41] *Tension noted 2026-10-28: S20's "keep models simple" is weakened as stated, because shrunk high-parameter models out-predicted sparse ones on US equity returns [S63 ACAD, abstract + secondary]. What survives is "simple to validate": the OOS gates (M5, M10) decide, not the parameter count. Nothing is removed.*
- **R4.** **Plan for decay.** Expect large out-of-sample and post-publication shortfalls. [S43]
- **R5.** **More backtests per idea means a larger live gap.** The count of backtests is an anti-metric. [S42]
- **R6.** **Refresh this list weekly from outside evidence**, and turn every gap it reveals into a checklist row or a queue unit. Never leave it as a memo. [frontier-research]
