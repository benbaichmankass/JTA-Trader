# Programme 01 — AI active trade management: brackets as predictions, moved by models

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `RESEARCH-PROGRAMMES` (manager dispatch, weekly planning 2026-10-14) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) · roadmap `M20` + `M31` · **Tier-1 document: it proposes tests; every flip it leads to is Tier-3 with an evidence record.**

> **2026-10-14 amendment (lane `IN-TRADE-EXIT-MODEL`, operator direction via the manager):** the exit line now has a stated **destination — Q8, the in-trade exit model**: at every bar of an open trade, P(SL before TP | state now), and an exit-now rule graded net of cost. Q1–Q7 are the rungs that feed it or ship alongside it; nothing below was removed. The operator's words are verbatim on checklist row `IN-TRADE-EXIT-MODEL`.

## The full action space — reframe (2026-10-28, lane `ROADMAP-PRIORITIES-AM-PRINCIPLE`)

> **Operator, verbatim (2026-10-28 ~21:00Z, relayed by the Manager Session):** *"active management isn't only tightening - it can be any movement in either bracket triggered by developments in the live market data"* / *"SL tightening is just one lever"*. And (~21:05Z): *"I'll settle for a conservative production ML that will mostly recommend holding outside of edge cases"*.

The binding statement is [`docs/ARCHITECTURE-CANONICAL.md`](../../ARCHITECTURE-CANONICAL.md) § "Active management". Its roadmap milestone is `L-AM-STANDARD` (week priority 3).

**What changes for this programme.**
- Every question here is asked per **action class**, not only for "the stop".
- Each class has its **own** ladder and its **own** registered, net-of-cost graduation test, under the risk-adjusted rule `RULE-AM-RISK-ADJUSTED-V1` (operator 2026-10-29; stated in `docs/ARCHITECTURE-CANONICAL.md` § "Active management" clause 4, which includes the matched random intervention of principle T1).
- A class is advice-only until that test passes.
- A FAIL on one class is evidence about that class only.

| class | bracket move | live-market triggers to test | evidence to date | state |
|---|---|---|---|---|
| **C1 SL tighten** | stop toward price | structure, ATR, momentum, giveback from peak | DESK-LIFECYCLE-S0 (#20967): Claude's management loses to hold, and the loss is in tightening. LTR-TIGHTEN-OPTIMIZE (#21003, held): 0 of 61 registered rules beat hold out of sample. Leg-specific harness arms (e.g. RQ-20261026-ed1c-17 break-even on `trend_donchian_eth`) are separate per-leg records. | **tested, loses as a class** → advice-only |
| **C2 SL widen** | stop away from price | vol expansion, event risk, a liquidity sweep before a level | none | untested |
| **C3 SL move-to-structure** | stop re-anchored to a swing, FVG or level | new structure forming beyond the stop | Q10 level-triggered trail (RQ-20261022-001..006 FAIL as a trail; fvg-on-4h unmeasured) | untested as a re-anchor |
| **C4 TP extend** | target further | momentum intact near the target, regime trend | Q3, RQ-20261007-080 measured-move PASS (pooled) | partly tested (Q3) |
| **C5 TP pull-in** | target nearer | momentum loss, liquidity level ahead, vol contraction | B1 remaining-move head FAIL on edge (L-ATM 2026-10-25) | untested as a triggered class |
| **C6 TP revise** | target re-estimated both ways | the TP doctrine's live prediction | Q2 / Q3 / Q8 | in progress (TP doctrine) |
| **C7 partial close** | part of the size off, both brackets kept on the rest | far-rung / level reached, event ahead | eba2-12..-14 far-rung bank (variants); principle T10: partials reshape, unproven on expectancy | untested as a triggered class |
| **C8 full close** | exit now | thesis invalidated, regime flip, event | Q8 exit-now line CLOSED FAIL on the fixed bracket (2026-10-18) | tested on the fixed bracket only |

**Question Q15** (in § 2) carries this reframe. Nodes `P1-Q15-*` in [`research/programmes/01-active-trade-management.yaml`](../../../research/programmes/01-active-trade-management.yaml) are `needs_authoring` until research-ops drafts each ladder.

## AI active trade management — the merged programme (2026-10-24, lane `ATM-AI-MERGE`)

> **Operator, verbatim (2026-10-24, relayed by Manager Session 2026-10-24, row `ATM-AI-MERGE`):** *"I want to start sort of trying to merge our two top priorities and trying to get active management, like under AI management, and seeing like what kind of models we can build to help us like with the live management of trades and moving the brackets as conditions change."*
>
> **What changed.** Programme 01 (active trade management) and Programme 02 Q3 (exit models) are now **one programme, this document**. 02 Q3 points here and keeps no separate ladder. Q1–Q8 below remain the history and the rule-lever track; this section is the plan of record for models that manage live trades. It is a Tier-1 plan: it authorises nothing, and every bracket flip it leads to is Tier-3 with an evidence record.

### Operator one-pager

**Build first: `FIRST-PASSAGE-ON-PATHS`, then `REMAINING-MOVE-HEAD`.** Every model that has failed here was graded on a bracket no leg trades (a fixed −1 R / +K R reconstruction), or on per-trade targets with ~20–120 out-of-sample trades. The harness can now replay each money leg **as it trades**, bar by bar, with its real stop and target (`--emit-paths`, #18536). The research reader for that is not built: `first_passage.py` takes `--ledgers` only (checked 2026-10-24). That one build unblocks the decisive test. Each rung below is a pre-registered unit whose rule was written before the run.

| rung | what it would prove | unit | gated on | compute |
|---|---|---|---|---|
| **A1** | Does momentum/ADX state say *"holding from here loses to exiting now"* beyond where the trade sits against its own stop and target? Linear model. | `blocked/RQ-20261024-09a6-01` | `FIRST-PASSAGE-ON-PATHS` | runner, cpu_light, ~1 h |
| **A1-policy** | Does an exit-now rule on that state beat each leg's own exit, net of cost, in ≥ 5 of 6 folds? | `blocked/RQ-20261014-d6e7-06` (already registered) | same build | runner, ~1 h |
| **B1** | Can a model predict how much further the move runs from here, and does pulling the TP in to that point raise net R per capital-day? | `blocked/RQ-20261024-09a6-03` | `REMAINING-MOVE-HEAD` | runner, ~1.5 h |
| **C1** | Can a chooser pick, per trade, among the rule exits that already confirmed, better than the single best fixed rule? | `blocked/RQ-20261024-09a6-04` | `EXIT-ARM-CHOICE-CORPUS` | runner, ~2 h |
| **A2** | Do funding, taker flow and open interest add exit information beyond price? | `blocked/RQ-20261024-09a6-02` | `PATH-FLOW-JOIN` + A1 graded | runner, ~1 h |
| **D** | Can a predictor GATE the validated levers (tighten only on flagged trades) better than a random flag? | `RQ-20261024-9a7e-01..04` (queued); `RQ-20261022-b7e1-04..10` graded **FAIL ×7** | — | runner |

**Cost.**
- Each build is one Tier-1 lane: ~$15 Opus for `FIRST-PASSAGE-ON-PATHS` (its row's estimate), and ~$8–15 each for the other three. INFERRED from comparable lanes.
- Every unit runs on the free GitHub runner over keyless public candles. No GPU and no trainer time until a linear rung passes.

**What it would take to reach a live bracket-moving model.**
1. One rung PASSES offline: A1 + A1-policy, B1 or C1.
2. A harness-native confirmation on each leg under the exit-refinement P2 gate (Path A or Path B, 6-fold walk-forward).
3. **The bracket advisor (`BRACKET-ADVISOR-SHADOW`, a Tier-2 proposal) logs, for 1–2 live trades per leg, the bracket the model would set beside the live bracket.** The offline harness must reproduce those values on the same bars. That is the parity read.
4. A Tier-3 proposal with the record. Real money and prop come first. Mirrors follow by roster equality.

If nothing fails, that is about 3–4 weeks: builds in week 1, rungs in week 2, confirmation and advisor in weeks 3–4. INFERRED from the Q8 cadence above, not a commitment.

**What already failed, said plainly.**
- Three LightGBM exit heads (ML-S2).
- The whole linear first-passage line on the fixed-bracket reconstruction (d6e7-02, RQ-20261016-012/-013, 1fa6-06).
- Path metrics once room-to-stop is controlled (EXIT-PATH-METRICS-W43).
- The giveback-predictor gate at P ≥ 0.5 (eba2-07/-08).
- The path-state trail gate (b7e1-04..10, FAIL ×7).

Two things work today, and both are **rules**:
- momentum/stall-keyed trails;
- stall-keyed TP pull-ins.

The honest prior for A1 is therefore *probably FAIL*, and that is why it runs first: it is cheap, and a FAIL closes the price-state model line on the legs as traded. B1 and C1 are built so that they still pay if A1 fails:
- B1's fallback is a per-leg bucketed rule.
- C1 chooses among rules that already work.

### End measure

**Net P&L per capital-day vs the bracket the leg trades today**, in R and in $, net of the full cost stack (`execution_costs.resolve_cost_policy()`), out of sample (6 purged calendar folds), per leg and pooled. Capital-days come from `scripts/capital_efficiency.py` (single home). Real money and prop come first. A paper or live book never establishes edge.

**Supporting measure — the prize.** MEASURED, `docs/reviews/2026-10-21-weekly-walkthrough.md` § 3:
- The paper+mirror book keeps about **13–15% of its peak R** (90 days, n = 328 R-graded closes).
- Peak is an ESTIMATED lower bound, so the true giveback is at least that.
- Real-money giveback is still `insufficient_n`.

The fixed-bracket oracle saving was **0.656 R/trade** (d6e7-01, n_sl_first 2,089). That is a ceiling, not an estimate of what a model captures.

### Measured state this plan is built from (re-read 2026-10-24; re-run, never quote)

| fact | MEASURED where |
|---|---|
| Three LightGBM exit heads failed offline: donchian −14.66 R OOS; S2-exit INDETERMINATE (SOL −4.30 / XRP +0.21 / ETH −1.16); XRP multi-fold FAIL (1 of 3 folds, −1.94 R pooled) | `docs/plans/ml-plan-items.yaml` ML-S2 |
| The linear per-bar first-passage model on the FIXED-bracket reconstruction adds nothing beyond where the trade is (K = 2 and 3, pooled and HTF), and the policy cannot pay for its exits; the same question on legs AS TRADED is **not** ruled out | row `IN-TRADE-EXIT-MODEL` note (2026-10-18 write-back) |
| Room-to-stop is the dominant giveback predictor (AUC ~0.81). The pooled path-metric pass (+0.0115 nats, 5 of 6 folds) shrinks to +0.0022 (3 of 6) once room-to-stop is controlled. Population: 958 trades / 18,770 states on 5 money legs. | row `EXIT-PATH-METRICS-W43`, `docs/research/exit-path-metrics-2026-10-22.md` |
| The giveback predictor has log-loss skill only (OOS R² gain ~0). The P ≥ 0.5 gate FAILED (eba2-07/-08). `RQ-20261024-9a7e-01..04` are `queued`. | row `EXIT-GIVEBACK-PREDICTOR-GATE`; `research/queue/RQ-20261024-9a7e-0*.yaml` |
| Rule levers that confirmed out of sample: ADX trail on xrp_4h (RQ-20261016-015; its sibling corroboration 511e-01 FAILED, so it is declared on the `bybit_1` alias only); momentum-stale stop on slv_1d (RQ-20261016-016; parameter-fragile: 12 bars fails); measured-move TP w0.5 on eth_4h (RQ-20261018-007) | § "Programme review 2026-10-21" and row `MOMENTUM-LEVERS-LIVE` |
| Live momentum levers at harness parity: #19856 MERGED (23c415ae) and DEPLOYED (diag #19870, 13:52Z 2026-10-24, live on 70815f27). **Not yet OBSERVED**: the first closed-bar trail/stale exit is owed by 2026-10-31. | row `MOMENTUM-LEVERS-PARITY` |
| `first_passage.py` has no `--paths` input. No `*__paths.jsonl` is committed under `comms/`. `path_metric_giveback.run_leg_paths` already runs a leg config-exact with `--emit-paths` inside a unit, so no committed corpus is needed. Path rows carry `dist_to_stop_r`, `dist_to_target_r`, `atr_r` and `adx_14`. | grep of `scripts/research/first_passage.py`, `scripts/research/path_metric_giveback.py`, `scripts/research/harness_emit.py` on 2026-10-24 |
| Live per-bar history exists: `position_path_history` holds one row per (package, bar) with sl/tp in force, peak, MAE, ATR and ADX. It is observe-only. | `src/runtime/position_path_history.py`; row `EXIT-PATH-TELEMETRY-LIVE` (`done`) |

### The model ladder — cheapest and decisive first

Common to every rung:
- Population: the six money legs the trend and pullback harnesses replay: `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `xrp_pullback_2h`, `ada_pullback_2h`, `trend_donchian_eth_prop`, `trend_donchian_sol_prop`.
- Window: 2020-07 .. 2026-10. Folds: 6 calendar folds by entry, purged.
- Cost and labels: the full cost stack; labels are truncation-honest (the leg's own exit, never a re-simulated barrier).
- Learner order: linear before GBDT or sequence. A richer learner is earned by a linear PASS (plan 8.7, unchanged).

1. **(a) In-trade information on the legs as traded — A1 → A1-policy → A2 → A3.**
   - **A1** (`09a6-01`) labels each bar *"the leg's own exit loses to exiting now, net of the exit cost"*.
     - The reference **includes** room-to-stop and room-to-target, because that is what the evidence says carries the signal.
     - The candidate adds momentum, ADX, the 3-bar ADX slope, range contraction and close location.
   - **A1-policy** is the already-registered `d6e7-06`: exit-now vs each leg's actual exit, ≥ 0.05 R/trade, ≥ 5 of 6 folds.
   - **A2** (`09a6-02`) adds flow: funding, taker imbalance, OI where point-in-time history exists. It runs on any A1 verdict, because a new information class is a different question.
   - **A3** is a GBDT twin on the same folds. It is not filed; it is earned by an A1 or A2 PASS.
2. **(b) Moving the TP — B1** (`09a6-03`). A per-bar remaining-move quantile head.
   - Graded **calibration first**: pinball loss vs the leg's own bucketed quantile.
   - Then graded on money: a pull-in-only TP replay vs the leg as traded, on net R per capital-day.
   - Pull-in only, because it is the one TP move a path replays honestly. Extensions stay with the harness `tp_revision` lever.
   - A clause-1 FAIL makes the bucketed per-leg quantile the TP-revision answer: a rule, not a model.
   - The entry-time sibling is `TP-PREDICT-HEAD` (`RQ-20261009-900/901`, blocked on its own corpus run).
3. **(c) Policy over proven rules — C1** (`09a6-04`). A chooser picks per trade among the declared exit and the confirmed rule levers.
   - Offline, every arm's outcome is observed by re-running the harness. So this is full-information cost-sensitive classification, with no propensities.
   - `RQ-20261011-9da8-04` (doubly-robust OPE bandit) stays for the live-logged case.
   - A PASS earns C2: per-bar switching, which needs a harness that accepts a policy. Not filed.
4. **(d) Gates on the validated levers.** Two sets are already registered:
   - `9a7e-01..04` (vol-controlled giveback gate vs a matched-rate random flag) are **QUEUED**, not yet run.
   - `b7e1-04..10` (the path-state trail gate) are the seven units graded **FAIL** (their `grading` blocks, read 2026-10-24). Their build `PATHSTATE-TRAIL-GATE` is `landed_unproven`. This lane authors nothing here, to avoid duplicates. The `f08c-*` and `4ef5-*` rule variants also stay as queued.

### The bracket advisor — observe-only, the parity and evidence path

**`BRACKET-ADVISOR-SHADOW`** is a Tier-2 proposal. It is not built and not approved, and any PR for it is held.
- **What it does.** On every monitor pass, for every live position, it writes the SL/TP a candidate would set (`advisor_sl_r`, `advisor_tp_r`, `advisor_source`) beside the live `sl_r` / `tp_r` on the same `position_path_history` row.
- **How it stays safe.** It reuses the same functions the harness uses. It is never read by the exit path and never raises.
- **Phase 0** needs no model. It shadows the rule levers that confirmed but are undeclared on a leg. That gives a live parity read *before* a Tier-3 declare instead of after it. Today's `ADA-LIVE-EXIT-REVIEW-1024`, where the operator moved a real-money stop by hand, is the case it would have logged.
- **Phase 1** carries the output of the first rung that PASSES.
- **The rule it serves.** No Tier-3 bracket flip of a model-driven exit without (1) an offline PASS and (2) the advisor's parity read on 1–2 live trades. That is mechanics only, never a sample size (the soak rule, OPERATING-PLAN § 2).

### Data foundation and the critical path

| build | why | tier | rank | state |
|---|---|---|---|---|
| `FIRST-PASSAGE-ON-PATHS` | reader for as-traded per-bar paths. Gates A1 and A1-policy. Spec extended 2026-10-24: as-traded label, room-to-stop reference, momentum/ADX-slope features, reuse of `run_leg_paths` | 1 | **1 — critical path** | queued |
| `REMAINING-MOVE-HEAD` | B1's head and its pull-in replay | 1 | 2 | queued |
| `EXIT-ARM-CHOICE-CORPUS` | C1's per-arm join and chooser grader | 1 | 3 | queued |
| `PATH-FLOW-JOIN` | point-in-time funding, taker and OI on path rows (A2) | 1 | 4 | queued |
| `BRACKET-ADVISOR-SHADOW` | live parity of any candidate bracket | **2** (proposal) | 5 — critical for any live flip, not for research | queued |
| `EXIT-PATH-EMIT-OFFLINE` | the harness `--emit-paths` (built, #18536). Its close-out observation, a committed path run, is still owed; the rungs above do not need it, because each unit emits in-run | 1 | — | landed_unproven |
| `DATA-INTRADE-LABEL-STORE` | the persisted, versioned label dataset (Programme 06 Q4). Needed for training at scale, not for the linear rungs | 1 | — | blocked |
| `PATHSTATE-TRAIL-GATE` | rung D's harness gate | 1 | — | landed_unproven |

**Write-back.** Every rung verdict is written to:
- row `IN-TRADE-EXIT-MODEL`;
- `ROADMAP.md` milestone L-ATM;
- the exit-refinement coverage matrix (`exit_head_ml` column).

A FAIL is written with its number and closes only the line its rule names. It never closes the family ("first test failed → variants queued", exit-refinement § "Reading a FAIL").

## Programme review 2026-10-28 (lane PROGRAMME-REVIEW-20261028) — TRADING track

Population: research units with a result row generated 2026-10-21T19:30Z..2026-10-28T19:30Z (`research_ops_checks.py --kind programme_review --since 7d`, 1,480 units read, 0 unreadable): **445 units, 412 graded** (70 pass, 50 indeterminate, 292 fail), 285 with a programme field and 160 without (live_strategy 70, regime 27, ml_health 21, macro 20, infra 13, new_strategy_prop 8, none 1). This review assigns the 160 by what they ask, not by the field (map section). Every PASS below is a discovery until its confirmation unit passes. **Cost basis:** about 36 of the 70 PASS rows are crypto-harness runs charged 7.5 bps round-trip (MEASURED from each result's argv); only RQ-20261028-001 carried the measured Bybit-linear 11.0 bps. A lever A/B delta is nearly fee-neutral (both arms pay it); an absolute Stage-0 or breadth PASS is not.

**Graded in the window: 123 with `programme: P1`** (13 pass, 107 fail, 3 indeterminate), plus the unprogrammed desk units (`bf56`, `e535`, `8b01`, `fe57`, `d1f5`) and TP-compliance units (`bea9-01/-02/-04`), which this review assigns to P1.

**What was learned (beliefs, with evidence and denominators)**
- **On the declared wide-trail legs, tightening the stop loses R, almost whatever triggers it.** Across about 140 stop-tightening and exit-management lever units graded this week, 129 FAILED. The triggers covered unconditional, R-armed, level-, ER-, CHOP-, ADX-, giveback-predictor-gated, fractional giveback and partial bank (batches `1d5c`, `3947`, `0142`, `b7e1`, `d7e6`, `9a7e`, `f08c`, `ed1c`, `90d3`, `eba2`). The 6 lever PASSes are `0142-04`, `0142-16`, `f08c-06`, `f08c-13`, `ed1c-10` and `ed1c-17`. That is about 4%, which is the rate chance alone produces at 5% per test, before counting that most units carry 2-4 arms. The desk full run (RQ-20261028-d1f5-02, PR #20967) is independent corroboration from a different instrument. It made 981 Claude stop-tightens over 938 trades, worth −0.097 R each, while its 2,001 holds were worth +0.142 R each against closing. Whole-trade management came out −0.159 R against hold on Claude entries and −0.124 R on random entries. One mechanism, two instruments: these legs earn in the right tail, so taking a trade off early costs more than the giveback it saves. Competing hypotheses: (a) noise. Eliminated: the desk CI excludes 0 and the mechanical units fail in the same direction. (b) Harness artefact, where tight stops are filled optimistically. Not eliminated, but the harness bias would favour tightening, not penalise it. (c) Regime: 2020-2026 was a trend-rich window for crypto. Plausible, and the disjoint 2017-09..2020-06 confirmations below test it.
- **What still survives is selective, thresholded or entry-side.** The EMA-slope direction filter on `trend_donchian` CONFIRMED on the disjoint 2017-09..2020-06 partition (RQ-20261028-001: 30.68 vs 29.34 R, n(A) 39, at 11.0 bps). It is an entry gate, not a tighten. The break-even floor (`ed1c-17`, monotone across 3 arms) and the CHOP-gated trail (`ed1c-10`, which beat the unconditional control in 5 of 6 folds) act only after +0.75..1.5 R. The TP side is moving: the `tp_extend` revision on `xrp_pullback_2h` stayed no worse than the static 3R target out of sample in 3 of 3 compliance units (`bea9-01/-02/-04`).
- **In-trade state carries information; entry state does not.** The bar-6 path metrics predict giveback on six legs the discovery never saw (`eba2-01` PASS) and survive a vol-ratio baseline (`eba2-04` PASS, log-loss gain +0.0145, 5 of 6 folds). The per-bar momentum/ADX state predicts "hold loses to exit now" beyond open R (`09a6-01` PASS, +0.0023 nats, 6 of 6 folds, 50,926 states over 2,627 trades). The effects are small, and every lever built on them so far has failed (`9a7e`, `d7e6`, `b7e1`). Information exists; a profitable action on it has not been found. Giveback is NOT predictable from entry columns (P2 `4b82-22/-23` FAIL).
- **The losing-tail pocket.** The desk's only positive pocket, pilot and full run agreeing in sign, is closing at −0.5 R or worse. It is not significant and was selected from about 6 action buckets, so it is a lead, not a finding.

**Failed first tests: diagnoses (no retirement from one test)**

| FAIL cluster | likely cause | evidence | variant that tests the diagnosis |
|---|---|---|---|
| tightening levers (~129) | **idea, on these legs**: they are right-tail earners | desk dR −0.097 R per tighten; the census (`9807-01`) shows a median peak of ~1 R, so a tighten fires inside the median trade | none on these legs beyond the two confirmations already lined up. Value is moved to loss-cut, TP and entry (below), not to a 14th gate |
| desk whole-trade FAIL (`d1f5-02`) | **design** (the action set allows a tighten) more than **judge** | 981 of 1,155 actions were tightens; holds were positive | `P1-DESK-no-tighten-policy` (needs #20967 merged plus a manager spend decision) and its mechanical twin `P1-Q4-desk-losscut-ada-pb` |
| path-metric-triggered levers (`9a7e`, `d7e6`) | **power / effect size** | log-loss gains of 0.002-0.015 nats cannot move a per-trade dR bar of 0.02-0.07 R | wait for P2 `P2-desk-checkin-exit-head` (a target that is the action's value, not giveback) |

**Answered / unlocked / retired**
- Answered: the ADX-trail declare line is now `f08c-13` (PASS on a fresh leg, `ada_4h`). The direction filter is confirmed (RQ-20261028-001), so it goes to the live-producer check plus a Tier-3 note by the owning row, not a unit. Unlocked: `ed1c-10` and `ed1c-17` confirmations, authored here.
- Retired: nothing. The tightening family stays open per `family_retirement_policy.yaml`. This review lowers its **value**, not its status: no new tightening variant on the 2h/4h trend and pullback legs is ranked in the next four weeks.

**Next 3-4 weeks (pre-registered, value-ranked)**

| # | node -> unit | decision it changes | on PASS | on FAIL | cost | pre-mortem |
|---|---|---|---|---|---|---|
| 1 | `P1-Q4-desk-losscut-ada-pb` (authored) | whether "stop waiting" gets a loss-cut lever on the 2h pullback legs | confirm on `xrp_pullback_2h`, then producer check | close the −0.5 R configuration; the desk pocket was noise | cpu_light, ~40 min | bar-N is a poor proxy for a continuous check-in; first variant is N=2 |
| 2 | `P1-ATM-ed1c17-be-confirm` (authored) | break-even floor as the one tighten shape that survives | producer check, then Tier-3 note | the BE floor was window-fitted | cpu_light, ~40 min | ETH 1h bars before 2019 are thin, giving INDETERMINATE |
| 3 | `P1-ATM-ed1c10-c75-confirm` (authored) | whether the gated-tightener family has ANY confirmed member on a trend leg | producer check, then Tier-3 note | gated tighteners drop to priority 3 on trend legs | cpu_light, ~35 min | one chop threshold selected from 3; the first variant is not to re-tune |
| 4 | `P1-DESK-no-tighten-policy` (gated: #20967 + spend) | is the desk's loss the lever or the judge | a desk policy without tightens enters the shadow pilot | the judge adds nothing over hold; desk effort moves to entries | judge spend, which is the manager's call | a fresh sample shifts the entry mix |
| 5 | existing `P1-Q6-*` declares (`xrp4h`, `eth4h-measured-move-w05`) | Tier-3 declares on confirmed levers | — | — | session work, not units | — |

**Feeds**
- P1 -> P2: the 12,500 priced check-in labels go to node `P2-desk-checkin-exit-head` (state: waiting on #20967).
- P1 -> P5: the BE floor and the loss-cut, if confirmed, go to the prop EV grid (prop drawdown limits price the left tail more than real money does).
- P3 -> P1: every breadth leg that survives re-costing needs exit processing before any re-entry case.

## Programme review 2026-10-21 (lane RESEARCH-PROGRAMME-REVIEW-1021)

Population: units whose `grading.graded_at` is 2026-10-14..2026-10-21 and whose file names this programme (`programme:` or `programme_node.programme`), read from `research/queue/*.yaml` on main at 2026-10-21 ~18Z. Units with no programme field (486 of the 657 graded in the window) are counted in the research map, not here.

**Graded in the window: 122** — 23 pass, 95 fail, 2 indeterminate, 2 not yet graded.

**What was learned**
- The exit levers that confirm are **momentum/stall-keyed trails and stall-keyed TP pull-ins**, not fixed brackets. Confirmed on a
  window they were not chosen on: ADX-conditioned trail on `trend_donchian_eth_4h` (RQ-20261016-005, 5 of 6 folds) and
  `trend_donchian_xrp_4h` (-015, 4 of 4); momentum-stale time stop on `slv_pullback_1d` (-016); measured-move TP width 0.5 on
  eth_4h (RQ-20261018-007); trail_mult 4.5 on `trend_donchian_eth_prop` priced on all three prop books (-028/-040/-041).
- The Q9 runway fill passed the same lever family on more legs (stall decay on xrp/ada/sol 4h; ADX trail on xrp_4h, ief/slv/gld 1d;
  fixed 3R/4R TP on sol_4h; bar-close stale exit on slv_1d). These are leads per leg; each still needs Q6 parity.
- The 95 FAILs are mostly single-cell exit arms on the m20 grid: they close cells, not families.

**Answered / unlocked / retired**
- Answered: Q3/Q4 for eth_4h, xrp_4h, slv_1d (confirmed). Coverage: Q1 is carried by the weekly census RQ-20261014-9807-01 and
  Q5 by blocked/RQ-20261014-9807-05; both are now in the tree's `questions:` map.
- Unlocked but **build-gated, not unit-gated**: P1-Q6 declares wait on build row **MOMENTUM-LEVERS-LIVE** (the ADX/momentum levers are
  harness-only, `src/research/trail_levers.py`) and on a `stall_pull_in` rule in `src/runtime/tp_revision.py`. The authoring queue's
  top P1 nodes (Q6 eth4h measured-move, eth4h stop, xrp4h, slv1d) are Tier-3 declare drafts, not research units.

**Next 3–4 weeks (pre-registered)**
- Queued P1 units (3) plus the generated m20/e35 exit families (29 queued). No new P1 unit was authored this review: the binding
  constraint is the two builds above, and research without a live producer cannot reach a declare.
- Week of 10-26: once MOMENTUM-LEVERS-LIVE lands, Q6 parity on 1–2 live trades per confirmed leg, then the held declare PRs.

**Operator ideas folded in (IDEAS.md, manager routing 2026-10-21)**
- `P1-Q10-level-triggered-trail`: price-level (FVG / swing / round-level) triggered trail tightening. Needs a harness flag first (none exists).
- `P1-Q11-path-metric-giveback`: chop, efficiency ratio and MAE/MFE path shape as giveback predictors (label study), then a
  partial-TP lever arm. Chained after the giveback census 9807-01 and the ada_pullback_2h sweep RQ-20260928-019.

**Overnight 2026-10-21/22 (lane EXITS-OVERNIGHT-1021, Tier-1; nothing live changed)**
- **Q9 TP crash root-caused** (PI-20261021-6SBYWRKB-0001). `trend_donchian_eth_4h` is the only leg declaring
  `tp_revision`, and a GEOM-B1 TP arm on top of it is two TP movers: `backtest_trend` raises `ValueError`. Only
  RQ-20261018-012/-014 were hit; the 22 other TP-lever units measured. The fix (#19423) refuses that arm up front and
  lands `failure.json` and run logs; `.gitignore` had been dropping `*.log` from the landing bundle. Re-armed with
  `-tp_revision` (#19425). Local, unregistered preview: the measured-move incumbent stands (A +115.95 R vs 78–88 R).
- **Field beats the review above:** the P1-Q6 ADX/momentum declares are no longer build-gated. `src/runtime/momentum_levers.py`
  is in both monitors (#18921, merged 10-18; deployment not checked this session). The one declare ready for the
  operator is **xrp_4h ADX trail 25/2.5** (MOMENTUM-LEVERS-LIVE note, 2026-10-22).
  - eth_4h's ADX trail is superseded: it FAILS against the current incumbent (RQ-20261019-010/-011).
  - slv_1d momentum-stale is parameter-fragile: 8 bars passes, 12 bars fails. Not proposed.
- **Q10 built and registered:** `--trail-level {swing,fvg,round}` lives in both harnesses (`src/research/trail_levers.py`,
  default byte-identical). Registered units RQ-20261022-001/-002 use tight 2.5/3.0. An unregistered tight-1.5 look is
  disclosed in each unit (all three kinds below the incumbent on both legs).
- **Q11 unblocked and registered.** It had been stuck `waiting` because recurring prerequisites never reach `done`
  (`queue_replenish.chain_verdict`). The rung-1 label-study unit sits on the node; script `path_metric_giveback.py`.
- **Confirmation gap filed** (PI-20261021-IGHT1021-0001): 10 Q9 PASS discoveries have no confirmation unit.
  - No earlier disjoint window exists on the feed: the perps' klines start 2019-12/2020-01.
  - The proposed build is a replace-on-holdout grade.

**W43 exits/giveback read, 2026-10-22 (lane EXITS-GIVEBACK-W43, Tier-1; nothing live changed)**
Each unit's pre-registered rule applied verbatim; numbers are in the unit's `grading` block (re-run, do not quote).
- **What the day's exit results decide.** Nothing ships. The declared exits stand on every money leg against: level-triggered
  tightening (RQ-20261022-001..006, FAIL x6), a fixed 50% bank (fd06-01/-02/-03, FAIL x3; on ada_pb 23.8-49.3 R against the
  declared 92.1 R), and the ADX corroboration (511e-01, UNIT FAIL: **the xrp_4h ADX trail stays on the bybit_1 alias only**,
  noted on MOMENTUM-LEVERS-LIVE and OPERATOR-DECISIONS-1022). The pattern across levels, bank and the 1R giveback stop is one
  finding: the wide trail earns its R in the right tail, so any rule applied to EVERY trade costs more than it saves. The
  remaining hypothesis is selectivity, which is exactly the operator's metric idea.
- **Giveback census 9807-01 (PASS, a REPORT rule).** Paper pool: giveback_share_of_peak 0.92, deep_then_loss 0.15, n 336, every
  peak a lower bound. Real money: n 7, `insufficient_n` -- the real-money giveback has still never been measured; the live
  telemetry is accruing (EXIT-PATH-TELEMETRY-LIVE). The 90-day 13%-of-peak figure in the weekly walkthrough is a different
  population (paper + mirror, n 328); both say the same thing.
- **Q11 rung 1 is a discovery, not a confirmation.** 007 PASSED on the log-loss clause alone (r2_gain -0.0038), carried by two
  legs; eth_4h read FAIL, xrp_4h underpowered; the time-disjoint confirmation 1f8b-01 is INDETERMINATE (58 trades; the perps'
  klines start 2019-12, so no longer disjoint window exists). By 1f8b-01's own rule rung 2 is NOT opened on 007 alone. The way
  to a decisive read is by LEG (eba2-01, eba2-02) and by controlling volatility (eba2-04).
- **Next units (15, all pre-registered; the 3 runnable + 6 variant units are `would_dispatch` in a `dispatch_queue.py` dry run):**
  | unit | question | state |
  |---|---|---|
  | RQ-20261022-eba2-01 | Q11 transfer: path metrics on 6 legs 007 was not selected on | queued |
  | RQ-20261022-eba2-02 | Q11 on the two prop legs (1h, k=12) | queued |
  | RQ-20261022-eba2-03 | R-armed tight trail (1.5/2.0/3.0 R -> 2.5 ATR) on ada_pullback_2h -- the operator's "once past N R the stop becomes a tight trail" | queued |
  | RQ-20261022-eba2-04 | Q11 rung 1d: path metrics beyond realised-vol-vs-entry-vol | blocked: PATHMETRIC-VOLCTL |
  | RQ-20261022-eba2-05 / -06 | fractional giveback exit (0.5/0.6/0.7 x peak after 2R) on ada_pb / xrp_pb | blocked: GIVEBACK-FRAC-FLAG |
  | RQ-20261022-eba2-07 / -08 | Q11 rung 2: metric-TRIGGERED bank / tight trail vs an unconditional control, ada_pb / xrp_pb | blocked: HARNESS-METRIC-TRIGGER + eba2-01 pass |
  | RQ-20261022-eba2-09 / -10 | Q10 variant: swing level with a WIDER tight mult, FVG lookback 120 (xrp_pb / eth_prop) | queued |
  | RQ-20261022-eba2-11 | Q10 variant: swing level AND peak R >= 1.5 / 2.0 (xrp_pb) | blocked: LEVEL-TRAIL-R-GATE |
  | RQ-20261022-eba2-12 / -13 / -14 | bank variant: far rung (2-3 R), small size (25-33%), and partial + R-armed tight trail (ada_pb / xrp_pb / eth_prop) | queued |
  | RQ-20261022-eba2-15 | ADX variant: momentum LOSS (ADX < 20; ADX < 30 or 20 AND falling 3 bars) on eth_4h | queued |
- **Operator's idea mapped.** Efficiency ratio, chop, MAE/MFE shape: rung 1 (007, eba2-01/-02). Realised vol vs entry vol: eba2-04.
  R-triggered tight trail: eba2-03 (the lever exists). Split / partial exit: fixed (fd06, closed) and metric-triggered (eba2-07/-08).
  Price-level triggers: Q10 (closed on six legs; xrp_4h `fvg` never fired). Loss-of-momentum triggers: the ADX / momentum family
  (MOMENTUM-LEVERS-LIVE).
- **Not authored, with the reason.** A far-rung bank on eth_4h / sol_prop / xrp_4h: eth_4h already stacks a stall decay and a
  TP revision (two TP movers have crashed the harness before, PI-20261021-6SBYWRKB-0001), sol_prop is the same family as eth_prop
  (eba2-14 goes first), and xrp_4h has n 68. Rung 2 on eth_4h / xrp_4h: rung 1 read FAIL / underpowered there (a prop rung 2 is
  node `P1-Q11-prop-rung2`, gated on eba2-02).
- **Idea status (operator 2026-10-22: "those aren't dead, they just didn't pass the first test"; family retirement stays with
  `scripts/research/family_retirement_policy.yaml`, nothing here retires one).** Each fail settles only the config question its
  rule asked.
  | idea | first test | status | why it failed (diagnosis, MEASURED where stated) | variants queued |
  |---|---|---|---|---|
  | level-triggered tight trail | Q10 x6 FAIL | **first test failed -> variants queued** | round levels exist on 100% of trades and are touched on 60-75% (an unconditional tight trail; worst arm everywhere); FVG exists on 4-36% of trades (4 of 68 on xrp_4h, inert); swing was the only selective trigger and the only arm near A (eth_prop +2.2 R, maxDD 16.5 vs 22.0); tight mult fixed at HALF the trail, never wider; the tight exit frees re-entry (n +4-15%). Osler (2000) finds published levels predict short-horizon interruptions, these legs hold 12-48 h | eba2-09, -10, -11 |
  | partial TP / split | fd06 x3 FAIL | **first test failed -> variants queued** | the +1 R rung is reached by about half of all trades (census peak p50 0.9-1.1 R) and 50% size halves every winner that reaches the 3-4 R target (127 of 402 ada_pb trades): the rung sat inside the median trade | eba2-12, -13, -14 (far rung, small size, + R-armed trail), eba2-07/-08 (metric-triggered) |
  | ADX / momentum trail | 511e-01 UNIT FAIL | **first test failed -> variants queued** (the real-money declare stays off: bybit_1 alias only) | ADX < 25 on 4h crypto holds for a large share of bars (near-unconditional); sol_4h / xrp_4h / eth_4h already carry their own tighteners that compose by minimum; cell carried from one n 68 leg; practitioners exit on ADX turning DOWN from a high level, not sitting low | eba2-15 |
  | R-armed tight trail | never registered on ada_pb | queued | operator-named; the lever exists | eba2-03 |
  | path-metric predictors | 007 PASS (ll-only); 1f8b-01 INDETERMINATE | discovery, unconfirmed | n-bound and volatility-confounded | eba2-01, -02, -04 |
- **Sources.** Osler, "Support for Resistance", FRBNY Economic Policy Review 6(2), 2000
  (https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf) is the one primary source. The rest are
  practitioner / secondary and carry no validated result: NexusFi MFE scale-out guide (https://nexusfi.com/a/risk-management/maximum-favorable-excursion-mfe),
  MQL5 article 24466 (R-multiple MFE percentile scale-out), LuxAlgo "Scaling Out" and "MAE/MFE Distributions" (luxalgo.com/library/concept),
  TradingView ATR Chandelier and ADX-exhaustion scripts, StrategyQuant / LuxAlgo on Kaufman's efficiency ratio. A search for a
  controlled study of scale-out vs full exit on trend systems, and for drawdown results of ER-scaled stops, found none; rungs
  fitted to MFE percentiles are flagged by the same sources as fragile, hence fixed pre-registered rungs.
- **Builds filed (checklist, all Tier 1, roadmap L-ATM):** HARNESS-METRIC-TRIGGER, PATHMETRIC-VOLCTL, GIVEBACK-FRAC-FLAG, LEVEL-TRAIL-R-GATE,
  RESEARCH-MULTICMD-OUTDIR (a multi-command unit shares one `{out_dir}`; 511e-01 lost its eth_4h numbers to it).

**Cross-programme feeds**
- → P5: trail 4.5 on eth_prop is priced on all three books; the prop EV read (P5) decides adoption.
- ← P7: the daily Donchian (ef5d-03, D55) is a new position-trade family that will need exit processing if its transfer
  (RQ-20261021-7c2b-04) passes.

## 1. End goal and measure

**Goal.** Every leg's bracket is a prediction that is kept honest through the trade: the TP at entry is where the leg's own history says the move runs out, it is re-estimated every bar from current conditions and moved through the existing `{"tp"}` verdict path, and the SL is the point where we stop waiting — a rule, not a hope. The giveback (a trade that reaches deep profit, pulls back and stops out) shrinks because the TP is reachable and the stop tightens when the thesis dies.

**Measure (headline, operator 2026-10-14).** **Net R per capital-day per leg**, real money first, with the $ figure beside it; at portfolio level weighted by capital. Supporting measures, each with its population stated:

| measure | population | instrument | baseline (MEASURED 2026-10-14) |
|---|---|---|---|
| giveback R = peak R − realised R, per leg and per class | closed trades with a `position_telemetry` row and a readable `peak_r`, joined to `trades` on `order_package_id`, never pooled across account classes | `scripts/research/giveback_census.py` (new, this lane; unit `RQ-20261014-9807-01`, weekly) | **not yet measured** — the first run is the baseline; do not quote one until it lands |
| TP-doctrine compliance | every (account, leg) routing in `config/accounts.yaml` | `python3 scripts/ci/check_tp_doctrine.py --json` | **0 of 50** routings compliant at 07:28Z (re-run 2026-10-16T07:15Z: **0 of 54**); real money + prop = 13 routings: real-money entry states 4 sentinel / 3 declared, producer state `no_tp_verdict` on 5 and `rule_undeclared` on 2; all 6 prop routings `declared` / `rule_undeclared` |
| TP amended mid-trade | closed trades since 2026-09-01 with an entry-time target | amend census (PLANNING.md § 5; GEOM-CENSUS row) | 0 of 748 TP amends vs 131 of 752 SL amends (2026-10-07; re-run, do not quote) |
| real-money expectancy | real-money closes | `/api/bot/performance` | −0.3231 R lifetime (n=431, 2026-09-21, pre-cut); latest window n=4 (G1 baseline) |

Doctrine: `docs/ARCHITECTURE-CANONICAL.md` § "TP doctrine" (four clauses). Gate for every lever: the exit-refinement P2 gate, Path A or Path B, then the yearly walk-forward; Path B's bar is decided (5 of 6 folds, maxDD within 0.35× base). Every harness run is net of the full cost stack via `execution_costs.resolve_cost_policy()`.

## 2. Questions, in dependency order

```
Q1 giveback census ──┬──▶ Q4 SL "stop waiting" (cells keyed to the measured giveback)
 (and capital-day)   └──▶ Q5 momentum-turn detector (labels: path rows from Q1 + the corpus)
Q2 entry TP from the leg's own MFE distribution, conditioned on vol & regime
   └──▶ Q3 per-bar TP revision rule (extend-on-thesis / retarget) ──▶ Q6 producer + live parity ──▶ Tier-3 flip
Q7 prop paths (TP amend on dxtrade / phone) ◀── Q6                       ▲
P2 AI trader: Q1/Q5 rows are M23 labels; a head-chosen TP is Q2's step 2 ┘

DESTINATION (Q8): per-bar path data ─▶ first-passage census ─▶ simple state model ─▶ rich (momentum) state model
                  ─▶ exit-now policy net of cost ─▶ harness-native confirmation ─▶ shadow ─▶ Tier-3 proposal
                  (Q4 and Q5 are special cases of Q8: a stop rule and a turn signal are both "exit when P(SL first) is high")
```

| Q | question | why it is first/next | existing units (do not duplicate) |
|---|---|---|---|
| **Q1** | How much R does each live leg give back between its peak and its close, and what is its net R per capital-day? | The pain point has never been a number per leg; every cell choice in Q3/Q4 keys on it | none — new `RQ-20261014-9807-01` |
| **Q2** | Where does each leg's own history say the move runs out — the entry-time TP as an MFE quantile, conditioned on entry volatility and regime? | Clause 1: a sentinel or venue-cap TP is not a prediction; `mi307` shows the real-money "declared" targets mostly rest at the cap and the predictive target sits at 2.0–2.5 R (INFERRED from the 2026-09-18 distribution) | unconditioned finite target: `RQ-20261010-419b-01` (eth_4h, closed FAIL), `RQ-20261006-061` (alpaca 1d, closed INDETERMINATE → family pooling follow-on `RQ-20261015-cab7-06`, INDETERMINATE), monthly E35 sweeps; head version `blocked/RQ-20261009-900/901`; **new conditioned version** `blocked/RQ-20261014-9807-02` |
| **Q3** | Does a per-bar revision rule (extend while the thesis holds; ATR-rescale; stall pull-in) beat the leg's bracket as it trades today, calibration first? | Clause 2; the landed 2026-10-08 runs already hold **PASS rows nobody has read**: `tp_extend` 6/24 cells on `xrp_pullback_2h` and 6/24 on `ada_pullback_2h` (`RQ-20261007-001`, OOS n=49 each), `tp_retarget` 2/9 on `trend_donchian_xrp_4h` (`RQ-20261007-003`, OOS n=31) — 0 ledger dispositions | `RQ-20261007-001/003` (landed), `RQ-20261007-080` (Donchian measured-move, queued); **new confirmation** `RQ-20261014-9807-03` |
| **Q4** | When do we stop waiting — a giveback / exhaustion stop keyed to the measured giveback, and a momentum-keyed time stop? | Clause 3: the trail says when the thesis failed; today the cells are fixed (`gb1R_afterMFE1R/2R`), not keyed to any leg's distribution | `RQ-20261007-042` (ADX-tightening trail), `RQ-20261007-043` (momentum-keyed time stop), monthly M20 sweeps; **new census-keyed cells** `blocked/RQ-20261014-9807-04` |
| **Q5** | Can a per-bar exhaustion signal (bars since peak, ADX falling, range contraction) predict that the rest of the path from here is negative — the "momentum turning" detector? | The operator's stated fix; it is a label study first (P(path from here < 0 | signal)) and only then a lever; the rows are M23 meta-labels for P2 | none; **new** `blocked/RQ-20261014-9807-05` (blocked on `ML-LEG-CORPUS`) |
| **Q6** | Does the live producer reproduce the harness decision (parity), observe-only, on the first confirmed leg? | TP-DOCTRINE B1 merged the verdict contract; no leg declares a rule; a flip is Tier-3 on an evidence record | rows `TP-DOCTRINE`, `GEOM-CENSUS`; soak `target_extension_soak` (B1 design) |
| **Q8 — destination** | **At every bar of an open trade, what is P(SL before TP \| state now) — and is there an exit-now rule (exit when E[R \| hold] < R_now − cost) that beats holding the bracket, net of the full cost stack, out of sample?** | The operator's stated destination (2026-10-14, row `IN-TRADE-EXIT-MODEL`): *"at any given moment, are we going to hit the stop loss before we hit the take profit? … improving them so that they turn from bad trades to good trades."* Entry-time giveback prediction (`RQ-20261014-9d20-01/-03`) is a cheap first rung, not the destination | **new** `RQ-20261014-d6e7-01..05` (runnable chain) + `blocked/RQ-20261014-d6e7-06`; builds `EXIT-PATH-EMIT-OFFLINE` (Tier-1, the priority), `EXIT-PATH-TELEMETRY-LIVE` (Tier-2 proposal) |
| **Q7** | Can the prop paths carry the same bracket (dxtrade REST TP amend plumbed; browser and phone not)? | Prop is the money at stake after real money; `RQ-20261007-002` found 0/24 extension cells on the 6R near-sentinel | rows `PROP-TRAIL-PHONE`, `PROP-EXIT-READ`; re-run `RQ-20261007-002` only after gradable prop closes |
| **Q15** | **For each action class (SL tighten / widen / move-to-structure, TP extend / pull-in / revise, partial / full close), does a trigger in live market data make that move beat hold, net of the full cost stack, out of sample, and against a matched random intervention?** | Operator 2026-10-28: *"SL tightening is just one lever"*; each class graduates from advice-only on its own test (ARCHITECTURE-CANONICAL § "Active management"); C1 tighten is tested and loses (#20967, #21003) | nodes `P1-Q15-*` (needs_authoring); Q2/Q3/Q8/Q10/Q11 units are its existing rungs for C3, C4, C6 and C8 |

## 3. Test ladders — cheap and decisive first, expensive last

Each rung names its decision rule in the unit; the rung's verdict is what unlocks or retires the next one. "Retire" means the question closes with a stated reason.

### Q1 — giveback census (`RQ-20261014-9807-01`, deterministic, weekly, trainer)
1. **Census over the synced journal, 90 d window** (one run, ~5 min). Rule: report; the record IS the deliverable. Per class with n ≥ 20: if `deep_then_loss` ≥ 0.25 or `giveback_share_of_peak` ≥ 0.5 on the real-money pool → Q4's census-keyed cells are the next rung on that class's legs; if neither, Q4 waits and Q3 goes first. Per-leg rows with n < 20 are listed as `insufficient_n`, never graded.
2. **Weekly re-run** keeps the number live; the manager's brief carries the real-money line. If the trainer's synced journal has no `position_telemetry` table the record reads `producer_failed` and the unit is a route fault (run it from a session on two diag pulls), never a verdict.

### Q2 — entry TP from the leg's own MFE distribution
1. **Unconditioned finite target on the E35 `tp_r` axis**, real-money sentinel legs (`RQ-20261010-419b-01`; `RQ-20261006-061`). Rule in each unit: a reachable finite cell passing IS/OOS at base OOS ≥ 39 → Tier-3 declare proposal; alpaca 1d is expected `infeasible` per leg → the follow-on is a family-pooled unit, not a lower bar.
2. **Calibration read of the declared targets** against realised exits and `peak_r` (`bracket_calibration_report.py --exits --mfe`, session-run on a diag pull). Rule: a declared target whose reach rate is < 0.20 on n ≥ 30 is a sentinel under another name and goes on the TP-doctrine debt list for that leg.
3. **Conditioned target** (`blocked/RQ-20261014-9807-02`): MFE quantile per leg × entry-vol tercile × ADX bucket from config-exact uncapped harness emits. Rule: PASS if the conditioned quantile's calibration error is lower than the unconditioned one in ≥ 2 of 3 vol terciles on every real-money stratum with n ≥ 30 per cell AND the conditioned bracket's OOS net R per capital-day is ≥ the unconditioned; retire the conditioning otherwise (the unconditioned quantile stays the answer, as `ml2-predictive-bracket-2026-09-06.md` found). Unblocks on `ML-LEG-CORPUS` (retained emits).
4. **Head-chosen per-trade target** (`blocked/RQ-20261009-900/901`) only if rung 3 passes — a head on top of a conditioning that added nothing is a variation, not a model.

### Q3 — per-bar TP revision
1. **Confirmation of the landed PASS cells on a fresh partition, calibration first** (`RQ-20261014-9807-03`, runner, ~1 h): the 6+6 `tp_extend` cells and the 2 `tp_retarget` cells, `split_mode=date`, a split the 2026-10-08 run did not use, with `--tp-report` calibration beside the base. Rule: CONFIRMED if the cell clears Path A or Path B on the fresh partition AND `tp_cal_cell` ≥ `tp_cal_base` on both IS and OOS AND the walk-forward wins ≥ 5 of 6 folds → Q6 on that leg (Tier-3 declare proposal with the record); "P&L without prediction" (gate cleared, calibration worse) is a FAIL by doctrine; otherwise INDETERMINATE and the cell waits for the monthly re-sweep.
2. **Measured-move revision** (`RQ-20261007-080`, queued) on the Donchian money legs — its rule is registered; read it when it lands.
3. **Scalps** (`RQ-20261007-004` landed 0/5 on all 7 scalp legs): retired for revision; the scalp family's question is the time stop (`RQ-20261013-407c-08/18`).
4. **Expensive rung:** a revision rule conditioned on the regime head's state (P2 feed) — only after rung 1 confirms at least one leg, because a conditioned rule on a leg where the plain rule fails is noise.

### Q4 — SL "stop waiting"
1. **Momentum-keyed stop and time stop** (`RQ-20261007-042/043`, queued) — read against their registered rules.
2. **Census-keyed giveback cells** (`blocked/RQ-20261014-9807-04`): `giveback_r` ∈ {p25, p50 of the leg's measured giveback}, `giveback_min_mfe_r` ∈ {1.0, p50 of peak}, plus `trail_decay` stall bars from the median `bars_since_peak`. Rule: Path B on `net_r_per_capital_day` with maxDD within 0.35× base, 5 of 6 folds → Tier-3 declare; retire the census-keyed idea for that leg if neither census cell beats the fixed `gb1R_afterMFE1R` cell. Unblocks on a `cells` input on the m20 sweep (build row proposed to the manager).
3. **Expensive rung:** cross-signal stop (regime flip + exhaustion) — only after a census-keyed cell confirms, and only through the regime-selectivity skill's rules.

### Q5 — momentum-turn detector (label study)
1. **Label study** (`blocked/RQ-20261014-9807-05`): on per-trade path rows (harness emits for the 7 real-money legs + live telemetry rows where final), does `bars_since_peak ≥ k` or an ADX fall of ≥ x from its peak predict `remaining_path_r < 0` with a lift over the base rate that clears a permutation null at p < 0.05 on n ≥ 300 trades? Rule: PASS → the signal becomes (a) a Q4 cell and (b) an M23 meta-label feature in the signals catalog; FAIL → retire as a stop trigger, keep as a catalog entry marked `no_lift`.
2. **Lever** (harness `--momentum-stale-*` already exists) only on a PASS.

### Q8 — the destination: the in-trade exit model (row `IN-TRADE-EXIT-MODEL`)

**Framing.** At every bar *t* of an open trade, estimate P(SL first | state_t) as a first-passage problem (outcomes: TP first, SL first, time-out), and exit at bar *t* when E[R | hold, state_t] < R_exit_now − cost. Graded by **net P&L per capital-day vs the fixed bracket** (the headline measure), net of the full cost stack, out of sample, per leg and pooled. **The free null:** for a driftless walk P(SL before TP from open R *x*) = (K − *x*)/(K + 1) (gambler's ruin) and E[R | hold] = *x* exactly, so any exit a policy takes is its model's information speaking. On bars that closed form is *not* a fair null (discrete passage, SL-first on a shared bar, the horizon) — `first_passage.py --self-test` shows a model "beating" it on a pure random walk — so every information claim is graded against a **calibrated distance-only reference** fitted on the same folds, and the policy exits only when the model's E[R | hold] is below the reference's by more than the extra exit cost.

**Why ML-S2 failed, and what is different.** Three exit heads failed offline on price features (`docs/plans/ml-plan-items.yaml` ML-S2: donchian −14.66 R OOS on `RQ-20260927-002`; S2-exit INDETERMINATE on `RQ-20260929-401`, SOL −4.30 / XRP +0.21 / ETH −1.16; XRP multi-fold FAIL `RQ-20261008-900`, 1 of 3 folds, pooled −1.94 R). They were LightGBM heads on a per-trade "does holding pay" target, one leg or family at a time, graded on ~20–120 OOS trades per fold. What Q8 changes: **(1) per-bar labels** — every bar of every trade is an event with a first-passage outcome, so the model learns *when* in a trade, not *which* trade; **(2) a ~3,000-trade corpus** (the committed crypto ledgers re-walked over public candles), pooled because a first-passage event in R is comparable across legs; **(3) a first-passage target with a closed-form null and a calibrated distance-only reference**, so "the model learned where the trade is" cannot pass as information; **(4) a linear model before a GBDT** — on the earlier n the GBDT had room to fit noise; a richer learner is earned by a linear PASS. What is **not** different: price-derived features are still most of the state; flow joins only through Programme 02 Q5.

**The binding gap — per-bar in-trade path data.** Harness `--emit-trades` rows are per-trade (`mfe_r`, a lagged lower bound); live `position_telemetry` is one upserted row per position; MAE is recorded nowhere. Two builds: **`EXIT-PATH-EMIT-OFFLINE`** (Tier-1, the priority — `--emit-paths` in the harnesses with the stop and target in force at every bar, so the leg *as it trades* is captured; it does not wait for live data) and **`EXIT-PATH-TELEMETRY-LIVE`** (Tier-2 proposal — an append-only per-bar history beside the upsert, for live parity and later shadow serving). **Consumers:** the exit-arm bandit `RQ-20261011-9da8-04` and the momentum-turn label study `blocked/RQ-20261014-9807-05` consume the **offline** emit (the bandit needs per-bar states under each ladder arm; 9807-05 needs per-bar ADX/ATR/open_r); 9807-05 reads the live history only as its parity check, never pooled. **Interim, not waiting:** `scripts/research/first_passage.py` re-walks the committed ledgers over public candles with a **fixed bracket** (initial SL at −1 R, TP at K R), which is enough to ask the operator's question of a plain bracket now.

| rung | test | rule (registered on the unit) | unlock / retire | unit |
|---|---|---|---|---|
| 8.1 | **First-passage label census**: P(TP/SL/time-out first) per K ∈ {1, 1.5, 2, 3} R vs K/(K+1); share of SL-first trades that first reached 0.5/0.75/0.9 K ("very close to the TP"); turn-oracle saving (best close before the SL, minus the extra exit cost); bar-level calibration of p0; fixed-bracket net R per capital-day | PASS at K = 2 if n_sl_first ≥ 300 and the oracle saving ≥ 0.25 R/trade; FAIL < 0.10 R | sizes the prize, funds 8.2/8.4; a random walk has headroom too, so it proves nothing about predictability | `RQ-20261014-d6e7-01` (runnable now) |
| 8.2 | **Simple state** (distance to TP/SL in ATR, bars in trade, open R, bars since peak, giveback) vs the calibrated distance-only reference, trade-weighted OOS log-loss, 4 purged time folds | PASS: gain ≥ 0.002 nats, CI > 0, ≥ 3/4 folds, calibration slope 0.7–1.3; FAIL: CI upper < 0.002 | PASS → 8.3 | `RQ-20261014-d6e7-02` (on 8.1 PASS) |
| 8.3 | **Exit-now policy on the simple model** vs holding the bracket, same OOS trades | PASS: ≥ +0.05 R/trade, CI > 0, ≥ 3/4 folds, capital-day guard, p0 sanity control < 5% exits; FAIL: CI upper < 0.05 R | PASS → 8.6 | `RQ-20261014-d6e7-03` (on 8.2 PASS) |
| 8.4 | **Rich state** — momentum in ATR, ADX and its slope, range contraction, close location, ATR-percentile regime — vs the same reference ("momentum suddenly turns") | as 8.2 | PASS → 8.5; runs on 8.1 PASS whatever 8.2 says | `RQ-20261014-d6e7-04` (on 8.1 PASS) |
| 8.5 | **Exit-now policy on the rich model** | as 8.3 | PASS → 8.6 | `RQ-20261014-d6e7-05` (on 8.4 PASS) |
| 8.6 | **Harness-native confirmation**: the passing policy against each real-money leg's *actual* exit (trailing, TP revision, stale), per family, 6-fold walk-forward | PASS: ≥ +0.05 R/trade, CI > 0, ≥ 5/6 folds, maxDD ≤ 1.35× | → exit-refinement P2 gate → observe-only shadow (needs `EXIT-PATH-TELEMETRY-LIVE` for parity) → Tier-3 proposal with the record | `blocked/RQ-20261014-d6e7-06` (on `EXIT-PATH-EMIT-OFFLINE` + 8.3/8.5 PASS) |
| 8.7 | Flow features (funding, OI, taker imbalance) and a GBDT/sequence learner | only after a linear PASS; through Programme 02 Q5 information classes | — | not filed (earned by 8.2/8.4) |

Q4 and Q5 are special cases of Q8 (a stop rule and a turn signal are each "exit when P(SL first) is high"); they stay as written and their verdicts are inputs, not competitors: a 9807-05 PASS signal enters 8.4's state.

### Q6 / Q7 — producer, parity, prop (builds, then one soak each)
Observe-only soak of the declared rule (`target_extension_soak`) on the confirmed leg for 1–2 executed trades (mechanics, not calendar time — `docs/CLAUDE-RULES-CANONICAL.md` § "Promotion evidence"), then the Tier-3 flip with the evidence record; mirror equality by test. Prop: dxtrade REST path first (TP amend plumbed), phone path via the server-computed amend ticket (BUILD B2).

## 4. Backlog — the next 3–4 weeks

| week | research (units) | builds (rows, proposed to the manager) | decision points |
|---|---|---|---|
| **W1** (to 2026-10-21) | **Q8:** `RQ-20261014-d6e7-01` first-passage census (runnable now); on its PASS `d6e7-02` and `d6e7-04` dispatch. `RQ-20261014-9807-01` first census run; `RQ-20261014-9807-03` confirmation; read `RQ-20261007-042/043/080`, `RQ-20261010-419b-01` as they land; disposition the 2026-10-08 PASS rows in the ledger | `GEOM-CELLS-INPUT` (a `cells` input on `m20-exit-lever-sweep.yml`; Tier-1); raise `ML-LEG-CORPUS` to the top of the ML lane (it unblocks 4 units); **`EXIT-PATH-EMIT-OFFLINE`** (Tier-1, `--emit-paths` on the trend + pullback harnesses first) | census baseline → is Q4 or Q3 the second rung per class |
| **W2** (to 10-28) | **Q8:** read `d6e7-02/04`; `d6e7-03/05` (policies) dispatch on their PASS; `RQ-20261014-9807-04` once cells exist; `RQ-20261014-9807-02` once emits are retained; alpaca 1d family-pooled finite-target unit (061's named follow-on) | TP-DOCTRINE B1: draft the declared rule for the first CONFIRMED leg (no flip) | first Tier-3 declare proposal, or an honest "no cell confirmed" |
| **W3** (to 11-04) | **Q8:** `d6e7-06` harness-native confirmation once the path emit lands and a policy passed; `RQ-20261014-9807-05` label study (on the offline path emit); second-leg confirmation on the monthly re-sweep | observe-only soak of the declared rule on the confirmed leg; prop dxtrade TP amend soak | parity read: harness decision == live decision on 1–2 trades |
| **W4** (to 11-11) | census re-read: did giveback move on the flipped leg (population: that leg's closes since the flip; expect `insufficient_n`, say so) | Tier-3 flip PR with the record; GEOM-CENSUS weekly rerun observed | second leg enters Q6; the programme's W5+ plan is re-cut from the measured state |

### 2026-10-16 re-cut — the running backlog (lane `P1-ATM-BACKLOG-1016`, operator: *"a lot of emphasis on trade management today"*)

The tree [`research/programmes/01-active-trade-management.yaml`](../../../research/programmes/01-active-trade-management.yaml) is the machine-read form of this section. Its header says what changed and why. Every runnable question below is a materialised, pre-registered unit, ordered by money at stake. Every follow-on is a node gated on its prerequisite's verdict, registered before that verdict exists.

**Why the re-cut (MEASURED 2026-10-16):**
- `check_tp_doctrine.py --json`: 0 of 54 routings are compliant.
- The fixed predictive-TP screen (RQ-20261015-cab7-01..06) returned INDETERMINATE on ada, xrp_pullback, xrp_4h, the pooled conditioned set and the alpaca 1d family. It FAILED on eth_4h. It was never run on the prop legs.
- Every m20 PASS cell on a real-money or prop leg sat on one IS/OOS split, with no folds and no materiality read. Six of those P1 units were ungradable as registered (RESEARCH-GRADE-PILE). They are closed INDETERMINATE in this PR, with the honest_negative legs their own rules allow.

| money | unit | node | question |
|---|---|---|---|
| bybit_2 | RQ-20261016-009 | P1-Q3-xrp-pb-tpx-confirm | the 6 tp_extend cells that passed twice, 6 calendar folds, ≥ 0.02 R/trade |
| bybit_2 | RQ-20261016-008 | P1-Q3-ada-pb-tpx-confirm | the 5 tp_extend cells that passed twice |
| bybit_2 | RQ-20261016-005 | P1-Q4-eth4h-momentum-confirm | adx20_k0_t2.5 / ms12_a20 / ms12_a25 on the sentinel leg |
| bybit_2 | RQ-20261016-006 | P1-Q4-eth4h-stalldecay-rerun | the operator's a1df-01 question, re-asked without the failed record control |
| bybit_2 | RQ-20261016-015 | P1-Q4-xrp4h-exit-confirm | momentum / giveback / tp_retarget cells over the whole history (68 trades, 4 folds) |
| bybit_2 + prop | RQ-20261016-004 | P1-Q2-solprop-derive | sol_prop's predictive TP (6R reached by 1.9%) |
| bybit_2 + prop | RQ-20261016-011 | P1-Q4-solprop-rrfloor-confirm | rrfloor0.5 at Bybit costs |
| alpaca_live | RQ-20261016-014 | P1-Q2-alpaca-1d-pooled | the 1d family's predictive TP on the longest dukascopy window, gld added |
| alpaca_live | RQ-20261016-016 | P1-Q4-slv1d-ms-confirm | ms8_a20 on slv 1d |
| prop | RQ-20261016-007 | P1-Q2-ethprop-derive | eth_prop's predictive TP (6R reached by 0.9%) |
| prop | RQ-20261016-010 | P1-Q4-ethprop-exit-confirm | 4 exit cells at the PROP cost stack |
| Q8 | RQ-20261016-013 | P1-Q8.4-indet-policy | the decisive money test on the rich state (supersedes d6e7-05) |
| Q8 | RQ-20261016-012 | P1-Q8.2-fail | the registered refinement: rich state at K = 3R |
| soak books | RQ-20261016-017..021 | P1-Q4-*-soak-confirm | gdx / gld / qqq / splg / spy m20 cells, priority 3 |

**Gated follow-ons:**
- Ten nodes are gated, each `after:` its unit: the Q6 declare/parity steps per confirmed leg, the prop EV/survival scoring, the harness-native K* confirmations and the K = 3R policy rung.
- Two ready `needs_authoring` nodes carry row PROP-EXIT-UNITS' prop questions, for research-ops.

**Not authored, with the reason:**
- ief, iwm and scha are below the 39-trade floor on the runner's history.
- A longer-window fixed TP for ada and xrp_pullback cannot reach power.
- The census-keyed stop cells (blocked/RQ-20261014-9807-04) stay blocked. Ledger-derived giveback reads negative on 20–50% of trades, because `mfe_r` is a lagged lower bound (MEASURED in the lane sandbox). They need EXIT-PATH-EMIT-OFFLINE.

**Manager audit input, same day** (`docs/research/programmes/reviews/2026-10-16/01-ATM.md`, PR #18532):
- `RQ-20261007-080` (Donchian measured-move TP revision) is session-graded **PASS** from its committed artifacts. At width_mult 1.0 the pooled result is +24.35 R over 1,439 control trades, with a fold majority at k = 3/4/5 and 46.1% of revisions cap-bound. It improves eth_4h and xrp_4h and worsens both prop legs.
- Its per-leg confirmations (`P1-Q3-eth4h/xrp4h-measured-move-confirm`) are emitted by the replenisher once that grade is on `main`. The verifier refuses a same-PR unlock.
- `9807-02` is retired as superseded by cab7-05.
- The 16 per-leg 1d-equity e35 monthly units are retired: base OOS 4–11, never able to reach 39. The pooled lever `RQ-20261015-1bf3-01` is the powered form.

**Builds filed:**
- ABLATION-TP-CALIBRATION: calibration-first for revision cells.
- QUEUE-GEN-ROSTER-SYNC: the generator minted 7 duplicate keys and never retires off-roster legs. 17 such sweep units were retired in this PR, each with a reason.
- TP-REVISION-RECORD-CONTRACT: `tp_revision_sweep.py`'s records cannot be emitted, so 080's PASS never reached `research/results/`.

**Q8 decision points:** the 8.1 census sets whether the prize funds the model rungs; 8.2/8.4 say whether the state carries information beyond where the trade is; 8.3/8.5 say whether that information pays for its exits. A FAIL at any rung is written back to row `IN-TRADE-EXIT-MODEL` and to `ROADMAP.md` L-ATM with the number; the live-history proposal `EXIT-PATH-TELEMETRY-LIVE` is scheduled only when a policy PASS needs a shadow.

**What this plan does not do.** It changes no config, roster or account (all Tier-3 flips are proposals with records). It does not re-open the entry-time ladder answered `honest_negative` ×6 on 2026-08-10, nor the scalp revision question (0/5 ×7 legs). It does not treat a paper or mirror book as evidence of edge; mirrors carry the real-money verdicts by roster equality. Numbers above marked MEASURED were measured this session from the files named; the 2.0–2.5 R predictive-target figure is INFERRED from the 2026-09-18 MFE distribution and must be re-derived by Q2 before it is used.

### 2026-10-18 drive — the four FAILs read, the starved units fired, the doctrine path per money leg (lane `ACTIVE-MGMT-DRIVE-1018`)

Operator, 2026-10-18 ~06:20Z: active trade management and ML are *"our highest priority"*. State at 06:20Z, MEASURED from `research/queue/` + `research/results/` (re-run, never quote): 21 P1 units — 4 `done`, all FAIL; 17 `queued`, none ever dispatched (the value-ranked dispatcher starved them; lane `DISPATCH-MONEY-FIRST-1018` is fixing the ordering). The 12 priority-1 units were fired by hand on `research-script-run.yml` at 06:20–06:24Z; the 5 priority-3 soak-book units stay with the dispatcher. The tree header in [`01-active-trade-management.yaml`](../../../research/programmes/01-active-trade-management.yaml) carries the same block in machine-adjacent form.

**What each FAIL rules out, and what stays live.**

| unit (node) | rule outcome | rules out | still live → next node |
|---|---|---|---|
| `RQ-20261016-012` (P1-Q8.2-fail) | FAIL: rich state at K = 3 R, −0.00126 nats vs the distance-only reference, CI [−0.00295, +0.00044], 2 of 4 folds +, n_oos 2,192 | a linear per-bar model on price-derived state carrying information beyond *where the trade is*, at a longer horizon, on the fixed-bracket reconstruction | nothing on this corpus; `P1-Q8-k3-policy` moot |
| `RQ-20261016-013` (P1-Q8.4-indet-policy) | FAIL: rich exit-now policy at K = 2 R, policy − bracket CI [−0.0445, +0.0313] R/trade, 1 of 4 folds +, early-exit share 0.79–0.90, 3,926 trades / 27 legs | an exit-now policy on that model paying for its exits | — |
| `RQ-20261016-1fa6-06` | FAIL ×2: HTF legs at K = 3 R, CI [−0.233, +0.002] R/trade, 0 of 4 folds +, n 695 | the same on the pullback_2h + Donchian 4h legs where a truncation costs least | — |
| `RQ-20261017-001` (P1-Q3-eth4h-measured-move-confirm) | FAIL on fold majority (4 of 6; fold 3 by 0.09 R); Δ +15.49 R and maxDD 8.02 vs 12.52 both clear; **net R per capital-day 0.0649 vs 0.0708 (worse)**; **5,810 of 6,318 revisions clamped at the venue cap (92%)** | width 1.0 measured-move on `trend_donchian_eth_4h` as a doctrine-compliant revision — 92% at the cap is the cap under a target's label (clause 1), whatever the P&L | width 0.5 (the 080 eth_4h arm with 57.8 R / DD 6.8 / 50% clamp) against the **new** incumbent: `P1-Q3-eth4h-measured-move-w05-confirm` |

The 8.1 census (`RQ-20261014-d6e7-01`, PASS, oracle saving 0.656 R/trade) still says the prize exists. What the three Q8 FAILs close is the **fixed-bracket linear line**; the honest residual is that the reconstruction (initial SL −1 R, TP K R) is not the bracket any leg trades. `--emit-paths` landed (#18536) but `first_passage.py` has no `--paths` input — build row **`FIRST-PASSAGE-ON-PATHS`**; `blocked/RQ-20261014-d6e7-06` now clears on it (its 8.3/8.5-PASS clause dropped, stated in the unit). A GBDT or sequence learner stays earned-by-a-linear-PASS (8.7).

**Two facts that change how the running units are read.** (1) `#18868` / `#18869` merged at 06:05Z: `trend_donchian_eth_4h` is now `atr_stop_mult 1.5 / trail_mult 6.0`, `ada_pullback_2h` carries `pullback_frac 0.618`. Every arm **A is "the leg as declared"**, so `RQ-20261016-005/-006/-008` run against the new incumbents (017-001 ran against the old). (2) `EXIT-PATH-TELEMETRY-LIVE` is not a proposal: `#18166` is merged and deployed, and the observation is met (7 of 7 closes since the 10-15 deploy have `position_path_history` rows, none after `terminal_at`; direct diag 06:28Z) — row `done`. Q6 parity reads use that table.

**Doctrine read on every Q6 declare (authoring instruction, not a rule change):** the harness's `tp_revisions_clamped / tp_revisions_applied` per arm is read before any declare; a PASS with a clamped share ≥ 0.5 (xrp_4h at width 1.0 was 88% in 080) is forwarded to the manager as *"P&L at the cap, not a prediction"*. The units' registered rules grade P&L / folds / drawdown exactly as written.

**Path to a doctrine-compliant predictive TP, per real-money and prop leg** (guard 06:20Z: 0 of 54 routings compliant; real money 8, prop 6):

| leg (accounts) | entry_tp today | deciding unit(s) now running / next | ETA of the decision |
|---|---|---|---|
| `xrp_pullback_2h` (bybit_2 + mirror) | declared 3 R, reach OK; revision fails | `RQ-20261016-009` (6 tp_extend cells, 6 folds) → `P1-Q6-xrp-pb-declare` | record ~07:30Z 2026-10-18; declare draft same day on PASS |
| `ada_pullback_2h` (bybit_2 + mirror) | declared 4 R; revision fails | `RQ-20261016-008` (5 tp_extend cells vs the **new** incumbent) → `P1-Q6-ada-pb-declare` | same |
| `trend_donchian_xrp_4h` (bybit_2 + mirror) | declared 3 R; revision fails | `RQ-20261017-002` (measured-move w1.0, clamp read required) and `RQ-20261016-015` (stop / retarget cells) → `P1-Q6-xrp4h-*` | same |
| `trend_donchian_eth_4h` (bybit_2 + mirror) | **sentinel 50 R**; cab7-04 FAIL; w1.0 FAIL | `RQ-20261016-005/-006` (stops, not TP) + **new** `P1-Q3-eth4h-measured-move-w05-confirm` (emits at the 05:50Z replenish) | w05 record ~2026-10-19; else route Q8 on paths |
| `trend_donchian_sol_prop` (bybit_2 + 3 prop) | **unreachable 6 R** (reach 1.9%) | `RQ-20261016-004` (K* derive) → `P1-Q2-solprop-confirm-kstar`; `RQ-20261016-011` (rr_floor) | derive record ~07:30Z; K* confirm unit authored same day on PASS |
| `trend_donchian_eth_prop` (3 prop) | **unreachable 6 R** (reach 0.9%) | `RQ-20261016-007` (K* derive) → `P1-Q2-ethprop-confirm-kstar`; `RQ-20261016-010` (exit cells at prop cost) | same |
| `slv_pullback_1d` (alpaca_live + mirror) | sentinel 50 R | `RQ-20261016-014` (pooled 1d K*, 8.7 y) → `P1-Q2-alpaca-1d-confirm-kstar`; `RQ-20261016-016` (ms8_a20 stop) | record ~07:40Z |
| `ief_pullback_1d`, `iaum_pullback_1d` (alpaca_live) | sentinel 50 R | ride the pooled `RQ-20261016-014` (ief below the 39 floor per leg; iaum is the proxy) | same |

Every one of these is Stage 0 → a **held Tier-3 proposal with the record**; nothing here edits config. The standing brief line (`render_daily_brief.py`, "Active trade management") carries the counts from this day on.

**06:50Z — the 12 fired units, read against their rules** (from the run artifacts; the records land under `comms/research/<unit>/<run>/` at the 07:20Z collector and `queue_grade` closes them; MEASURED, re-run before quoting):

| unit | leg | verdict | the number | disposition |
|---|---|---|---|---|
| `RQ-20261016-005` | eth_4h (bybit_2) | **PASS** | M1 ADX-trail (20 / 2.5): 111.37 vs 88.27 R, n 270/262, 5 of 6 folds, DD 16.1 vs 18.1 | no live producer → build `MOMENTUM-LEVERS-LIVE` (Tier-2), then Q6 |
| `RQ-20261016-006` | eth_4h | **PASS** | D trail_decay (stall 10 / tight 1.8): 70.03 vs 61.08 R, n 180/160, 3 of 4, DD 19.4 vs 18.1, capital-day 0.205 vs 0.127 | producer exists → **held Tier-3 PR** |
| `RQ-20261016-015` | xrp_4h (bybit_2) | **PASS** | M2 ADX-trail (25 / 2.5): 17.07 vs 14.30 R, n 68, 4 of 4; **R1 tp_retarget stall_pull_in 16.55 R, 3 of 4** (a TP that moves) | ADX → same build; R1 → needs a `stall_pull_in` rule in `tp_revision.py` |
| `RQ-20261016-016` | slv_1d (alpaca_live) | **PASS** | momentum-stale (8 / ADX 20): 20.73 vs 12.82 R, n 89/69, 3 of 4 (all +), DD 6.4 vs 7.0 | no producer → same build; node `P1-Q6-slv1d-declare` |
| `RQ-20261016-010` | eth_prop (3 prop) | **PASS** | T1 trail 4.5: 122.04 vs 76.02 R, n 1,070/1,085, 6 of 6, DD 21.7 vs 21.2 (prop costs) | prop superset → `P1-Q4-ethprop-ev` (prop_ev_grid) first |
| `RQ-20261016-004` | sol_prop (bybit_2 + prop) | **PASS_NONINFERIOR** | K* = 2.5 R: reach OOS 0.230 (6 R: 0.095), gap 0.001, Δ +0.041 R/trade CI [−0.025, +0.111], n 314 | confirm unit `P1-Q2-solprop-confirm-kstar` authored; then prop cost + EV; then one declare |
| `RQ-20261016-009` | xrp_pb (bybit_2) | FAIL | six tp_extend cells +0.75..+1.75 R / 394 (bar 7.88) | cells retired; route Q8 on paths |
| `RQ-20261016-008` | ada_pb (bybit_2) | FAIL | best cell +0.51 R / 449 (bar 8.98) vs the new incumbent | retired |
| `RQ-20261016-011` | sol_prop | FAIL | rr_floor 0.5: −2.37 R / 400 | retired |
| `RQ-20261017-002` | xrp_4h | FAIL | measured-move w1.0: +2.59 R / 68 but 2 of 4 folds; 91% cap-clamped | retired on xrp_4h |
| `RQ-20261016-014` | alpaca 1d family | INDETERMINATE | K* = 3.5 R: reach 0.278, gap 0.019, Δ +0.003, CI [−0.061, +0.069], n 326 = the whole 8.7 y | **operator decision** (no more data exists) |
| `RQ-20261016-007` | eth_prop | INDETERMINATE | K* = 2.5 R: reach 0.135 (6 R: 0.034), Δ −0.028, CI [−0.066, +0.006], n 870 | **operator decision** |

Two reads that bind the next step: **the ADX-trail family is corroborated across two Donchian 4h legs** (eth M1, xrp M1/M2) and **a TP-revision cell passed on a real-money leg for the first time** (xrp_4h R1) — both unshippable only because the live producer is missing. The build rows carry those, and the coverage matrix now reads `passed_unshipped` on each with the run id.
