# Local students for the live trade review and the desk: what exists, the gaps, the build

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**State: SPEC, ON HOLD until after the 2026-11-18 18:00Z weekly reset (operator 2026-11-15 ~15:15Z: build after the reset, aiming at an ML that proves it will not lose money).** Build row: `LTR-LOCAL-STUDENT` (Tier 1 for
stages S0–S1, which only write shadow records). Builds on, and does not replace,
[`ml-claude-distillation-DESIGN.md`](ml-claude-distillation-DESIGN.md) (the `claude_judgments` pipe) and
[`.claude/skills/trading-desk/SKILL.md`](../../.claude/skills/trading-desk/SKILL.md) § 6 stage 4 ("students take over
role by role").

**Gates this adds or changes: none.** S0 and S1 write shadow rows only. Nothing they produce is applied, and nothing
they produce changes which trades reach Claude. Letting a student *apply* an action uses the existing stage-4 rule
(trading-desk § 6: S-shadow → S-advisory → S-drives on net R per capital-day, out of sample, margin 0 vs Claude).
Letting a student *choose which trades wake Claude* (§ 5, S3) changes the LTR trigger, so it is an operator decision
and is not part of this build.

## 0. The request

Operator, 2026-11-15 ~14:35Z (chat), summarised: copy the LTR and the desk-trade flows into our own models, so a
basic version runs locally on VM capacity instead of Claude capacity. Feed them the same structured packets the LTR
already gets, and require a reliable output. Run them alongside the LTR first, use the LTR as the baseline, and measure
against it. Because VM runs cost no Claude usage, run active management as often as possible so every open trade always
has a current decision. This is part of the ML priority of getting every trade stage onto a live ML, given special
attention because the LTR uses a lot of capacity.

## 1. What exists today (MEASURED at `origin/main`, 2026-11-15 ~14:40Z)

| piece | where | measured state |
|---|---|---|
| Review packets (inputs) | `comms/live_review/packets/LR-*.json`, built on the VM by `scripts/ops/live_review_packet.py` | **781 packets**, ~17 KB each, fully structured: `context_v3`, `priced_options`, `mechanics`, `regime`, `cost`, `state`, `features_at_review`, `account_bounds`, `packet_health`, `missing_inputs` |
| LTR decisions (teacher outputs) | `comms/live_review/reviews.jsonl` | **776 rows**, 2026-10-25 → 2026-11-15. Actions: hold 566, flag_mechanics 71, no_recommendation 59, close 38, tighten_sl 25, partial_close 2, other 15. Every row carries `features_at_review`, `options`, `forecast`, `trigger`, `packet_sha` |
| Graded outcomes | `comms/live_review/outcomes.jsonl` (`scripts/ops/live_review_grade.py`) | **666 rows** with `cf_r` (the recommendation's counterfactual R) and `delta_r` vs hold. Non-hold calls: close n=27, mean delta_r **+0.570 R**; tighten_sl n=10, **+0.611 R**; partial_close n=1. **Provenance: counterfactual, `pnl_provenance` mostly `estimated`; no CI computed here.** A signal that the teacher adds value on its rare actions, not an established edge |
| Options table (deterministic) | `scripts/research/live_review_outcomes.py --condition state` | Prices hold / close / tighten etc. from the leg's own Stage-0 history; already in every packet as `priced_options` |
| Rule vs teacher agreement | computed for this spec over the 183 reviews with ≥ 2 priced options and a hold / close / tighten / partial action | A plain rule (take the option with the best `mean_r`; close when the close and hold means are within 0.02 R and close improves the worst case by ≥ 1 R, the operator's tail tie-break) **agrees with the LTR on 138 / 183 (75%)**. Disagreements: rule says tighten where the LTR held, 38; rule says close where the LTR held, 4; LTR closed where the rule held, 2 |
| Desk decisions | `comms/desk/decisions.jsonl` | **213 rows, all `entry_generation`**: no_trade 191, propose_entry 22. The desk's in-trade role IS the LTR (trading-desk § 2), so its in-trade labels are the 776 above. Exit role not live (DESK-17) |
| Distillation dataset | `ml/datasets/families/claude_judgments.py` (CJ-2, built) | Point-in-time join of `reviews.jsonl` + `outcomes.jsonl` + `desk/decisions.jsonl`, with leakage-safe column groups and guard `claude-judgments-guard`. **No model is trained on it**: the § 4.5 student manifests (CJ-5) were never filed |
| In-trade ML, learned from outcomes | `docs/plans/ml-dev-plan.yaml` D7 / D8 | `MLP-D7-ACTION-VALUE`: **7 FAILs** (the state does not predict action value out of fold); Stage B queued today as `RQ-20261115-7e18-01`. `MLP-D7-LABRADOR-1B` (TP extension at 4h check-ins) **serves** on ml_entry, forward +0.0081 R/trade, CI spans 0. `MLP-D8-LABRADOR-2` exit head stuck; exit-now v0 `RQ-20261114-1ae8-01` INDETERMINATE (no gain). Desk-label variant parked on power |
| Cadence today | `config/live_trade_review.yaml` `judgement_cadence` + triggers | Reviews are woken by events: judgement_cadence 179, short_hold 141, daily_floor 81, manual 80, adverse_r 71, giveback 37, r_milestone 35, others. About 20–60 reviews a day (11-08 → 11-15). Each one is a Claude session |

## 2. The gaps

1. **G1: nothing produces a review without Claude.** There is no student runner: no process takes a packet and writes
   a review row. This is the main gap, and the one this build closes first.
2. **G2: no student is trained on the teacher's labels.** The pipe exists (CJ-2); the manifests and the training run
   (CJ-5) do not.
3. **G3: packets exist only when a Claude review is woken.** A student that runs every bar needs a packet every bar for
   every open package, built by the VM. The builder exists; a per-bar schedule does not. A packet built during a
   web-api restart came out empty on 11-15 (row `LTR-PACKET-DURING-RESTART`); a per-bar builder must mark such a packet
   unhealthy and skip it, not review it.
4. **G4: rare actions are thin.** 38 closes, 25 tightens and 2 partials in 776 rows. Plain imitation of those classes
   is underpowered, so the student must use the outcomes (`delta_r`) and the priced options, not only copy the action.
5. **G5: the LTR's forecast has no structured twin.** Each review writes a chart-read `forecast` (thesis, direction,
   target, p_target, invalidation). Feature-based students cannot write that; it is the part of the LTR a local
   student will lack, and the reason S2 exists.
6. **G6: the desk's entry_generation student is too thin to build now.** 213 rows with 22 positives. The ML entry
   models (D3, Foxhound) already play this role from outcome labels. Leave entry generation to D3; revisit at
   DESK-13's n.
7. **G7: no head-to-head grader.** `live_review_grade.py` grades the teacher. Nothing yet grades a student row against
   the teacher row on the same package and the same outcome.

## 3. The build (after the reset)

Each stage writes rows in the **same schema** as `reviews.jsonl` to its own store
`comms/live_review/student_reviews.jsonl`, with `model` set to the student's id, `packet_sha` linking to the packet,
and `shadow: true`. Same schema means the existing grader, the `claude_judgments` family and the dashboard can read
them without new code paths.

### S0: rule student (deterministic, no training)

- `scripts/ops/ltr_student_rule.py`: reads one packet, applies the mechanics checks already in the packet's `mechanics`
  block (→ `flag_mechanics`), then the options rule from § 1 (best mean, tail tie-break, refuse on
  `priced_options_state != ok` → `no_recommendation`). Writes one student row.
- **Runs on the live VM every 5-minute bar for every open package** (a systemd timer, no Claude), after a per-bar
  packet build (G3). The packet is built with the same generator, so the student sees exactly what Claude would.
- Cost: CPU only. Expected agreement with the teacher is about 75% (measured above), and that number is re-measured
  live, never quoted.

### S1: learned student (LightGBM, trained on the trainer VM)

- A manifest under `ml/configs/` on the `claude_judgments` family (`kind: ltr_review`), stage `candidate`.
  Features: `features_at_review`, the priced options' stats (mean, sd, worst per action), trigger event, leg family,
  regime cell. Two heads:
  - **imitation head**: P(teacher action) over {hold, close, tighten_sl, partial_close}.
  - **value head**: predicted `delta_r` vs hold for each action, from `outcomes.jsonl`.
  The decision is the value head's best action, with the imitation head as a tie-break and a confidence. This answers
  G4: rare classes are learned from their outcomes, not only from how often Claude chose them.
- Retrained daily in the existing trainer cycle; served from the registry to the S0 runner, which writes an S1 row
  beside the S0 row on the same packet.
- Pre-registered unit (research queue), registered before the first fit: grouped by package, walk-forward by
  week, net of the full cost stack. PASS if the S1 student's chosen actions match or beat the teacher's mean delta R on
  matched packages within a non-inferiority margin of −0.05 R, with agreement reported per class. FAIL → S1 iterates
  on features; S0 keeps running.

### S2: local language model (measure first; optional)

- To cover G5, a small open-weight model on the trainer VM reads the same packet text and writes the `forecast` block
  plus an action. **Measure before building:** tokens per second on the trainer VM's CPU, wall time per 17 KB packet,
  and whether one review per open package per 15 minutes fits. If it does not fit, S2 is dropped with that measurement
  as the reason. It never calls a paid API (binding: nothing spends Anthropic API credits).

### The grader (G7)

- Extend `live_review_grade.py` with a `--students` mode. For every package with both a teacher row and a student row
  in the same window, it writes:
  - agreement by action class;
  - the student's delta R vs hold, and its delta R vs the teacher's;
  - mean and CI over matched packages.
- The per-bar student also produces decisions where no teacher row exists. Those are graded against hold only.
- Writes `comms/live_review/student_grade.json`, which the Wednesday `/ml-review` reads as a fixed check.

## 4. How the students move up

**Operator decision 2026-11-15 ~15:15Z (chat), binding for this line:** the first local version does **not** have to
beat Claude. It runs at a higher cadence as an urgent check and a fallback, so the bar for it to go live is that it
**proves it will not lose money**: non-inferior to hold, net of the full cost stack, out of sample, on a rule
registered before the run. It then serves as the live baseline that later versions are measured against. The S0 rule
was measured at +0.004 R/decision vs hold, 95% CI [-0.002, +0.009] (n 167 graded reviews, counterfactual) with its
tightens unpriced, so it is not built ahead of the reset; the first live candidate is the S1 model after the reset.

1. **S-shadow**: rows written, nothing applied (only while the no-loss test is being run).
2. **S-drives (fallback)**: the student's calls are applied through `live_review_apply.py` under `MD-TRADE-DESK` at
   its own cadence, beside the LTR, once its pre-registered **no-loss test vs hold** passes per action class (the
   operator's 2026-11-15 bar above). This narrows trading-desk § 6 stage 4's "margin 0 vs Claude" for this line only;
   beating Claude is the bar for the S3 step (§ 5), where the student replaces Claude's wakes, not for running as a
   fallback beside them.

## 5. The capacity payoff, and the one operator decision it needs

- **S0/S1 alone save no Claude usage**: the LTR keeps running at its current cadence, as the operator asked
  ("they'll run both together at first").
- **S3 (not in this build) is the saving.** The student screens every package every bar, and Claude is woken only
  where the student says non-hold, its confidence is low, or a mechanics flag fires. The 4h `judgement_cadence`
  then becomes a teacher-sample on a fraction of packages (the desk's rho dial, trading-desk § 4). This changes which
  trades reach Claude, so it goes to the operator as a decision once S1 has a grade. It is carried on row
  `LTR-LOCAL-STUDENT` as the step after S1's grade, not built here.

## 6. Build rows (after the reset, in order)

| order | id | what | tier | size |
|---|---|---|---|---|
| 1 | `LTR-STUDENT-S0` | `ltr_student_rule.py` + per-bar packet build + VM timer (shadow rows only) + tests | 1 for the script; **2 for the VM timer** (a new timer on the live VM) | one Sonnet lane, about half a day |
| 2 | `LTR-STUDENT-GRADER` | `live_review_grade.py --students` + `student_grade.json` + the `/ml-review` check line | 1 | Sonnet, a few hours |
| 3 | `LTR-STUDENT-S1` | manifest + pre-registered unit + trainer serving to the S0 runner | 1 (shadow) | one Opus design pass + Sonnet build |
| 4 | `LTR-STUDENT-S2-MEASURE` | latency/fit measurement of a local open-weight model on the trainer VM; build only if it fits | 1 | Sonnet, a few hours |

**Done for this spec** = S0 rows observed on the live VM for every open package on consecutive bars, and the grader's
first `student_grade.json` committed with a stated n. **Done for the request** = S1 graded against the teacher, and the
S3 decision put to the operator with that grade.
