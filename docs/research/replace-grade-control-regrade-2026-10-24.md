# Replace-grade control re-grade (REPLACE-GRADE-CONTROL-REGRADE, 2026-10-24)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `REPLACE-GRADE-CONTROL-REGRADE` (Tier 1, Sonnet). No `src/` or `config/` file is touched. **MEASURED** = read from a committed result or the code; **INFERRED** = my reading.

## Answer

**No verdict changes. All 12 graded exit-lever `replace` units whose rule names an unconditional control stay FAIL when the control clause is enforced (0 flips of 12).** The control clause was never the binding clause: no candidate in any of the 12 passed the incumbent-comparison clauses to begin with, and every best candidate beat its control by +3.2 R or more. So the grader defect (found by EXIT-GIVEBACK-PREDICTOR-GATE) did not corrupt any past verdict. It did leave one live exposure: see § 4.

## 1. Population and search (MEASURED)

| Step | Count | How |
|---|---|---|
| Queue units, any status | 1266 YAML files under `research/queue/**` | glob |
| ... whose `run.command` calls `exit_lever_ablation.py` | 364 | substring on the command |
| ... with `--grade replace` | 182 (`--vs-control` present in none before #19871) | argv after `--grade` |
| ... that have a landed result under `research/results/<id>/` | **163** (140 fail, 22 pass, 1 indeterminate by queue `grading.verdict`) | glob `*.jsonl` |
| ... whose `decision_rule.rule`/`statistic` names a control arm (regex `control\|unconditional\|random\|same action\|every trade\|matched`) | **13**; 12 after dropping `RQ-20261015-a1df-01` (its "positive control" is the reproduce-the-committed-record check, already enforced by `check_control`, not a vs-arm clause) | text search |
| ... the other 150 | their only `net_r(C) > net_r(X)` comparison is against the baseline arm (147 vs `A`, 3 vs `S3` = bea9-01/-02/-04, where S3 is the incumbent): **no control clause to enforce** | regex on `net_r(..) > net_r(..)` |

**The search finds eba2-07 as a positive control:** `RQ-20261022-eba2-07` is in the 13 (its rule: "net_r(C) > net_r(its unconditional control, UB for MB, UT for MT)"), as is its sibling eba2-08. The first, looser regex (adding `baseline`) matched 182 of 182 and was discarded: a probe that matches everything is not a probe. Limits: a control clause worded without any of those terms and without a `net_r(..) > net_r(..)` comparison would be missed; I read the `vs`/`beats` word hits in the other 150 and found none.

## 2. Method

`scripts/research/regrade_vs_control.py` (new). Each landed artifact carries `measurement.arms` (n, net R, max drawdown, per-fold net R), so no backtest is re-run. For each unit it rebuilds the grade parameters from the unit's own `run.command` (`--baseline`, `--fold-majority`, `--n-floor`, `--dd-tol-frac`, `--delta-r-per-trade`, `--folds`), then calls `exit_lever_ablation.grade_replace` twice: (1) with no controls, every non-baseline arm a candidate, which **must reproduce the stored verdict and label** (it did, 13 of 13); (2) with `vs_controls` set from the rule text and the control arms removed from the candidate set, which is what `--vs-control` does. Candidate-to-control pairs: b7e1-04/-05/-06/-07 all candidates vs `UT15`; b7e1-10 vs `UT20`; 1d5c-01..04 vs `UT`; eba2-07/-08 `MB`->`UB`, `MT`->`UT`; b7e1-08 reads "net_r(C) > net_r(UB25/UB33/UB50)", graded as all three, with a matched-pair sensitivity (`BG25`->`UB25` etc.).

## 3. Table

Best candidate = highest net R vs the incumbent `A` (all candidates in the artifact are in `regrade.json` output of the script). "Control margin" = net R of that candidate minus its control. Old and new verdict are both `fail` in every row; the reproduction check passed in every row.

| Unit | Leg | n(A) | Best cand | dR vs A | folds >= A | Control margin | Old | New | Flip |
|---|---|---|---|---|---|---|---|---|---|
| RQ-20261022-b7e1-04 | ada_pullback_2h | 402 | E20 | -10.51 | 3/6 | UT15 +12.9 | fail | fail | no |
| RQ-20261022-b7e1-05 | xrp_pullback_2h | 394 | E30 | -3.93 | 2/6 | UT15 +7.7 | fail | fail | no |
| RQ-20261022-b7e1-06 | ada_pullback_2h | 402 | V80 | -0.62 | 4/6 | UT15 +22.8 | fail | fail | no |
| RQ-20261022-b7e1-07 | ada_pullback_2h | 402 | C75 | -1.60 | 3/6 | UT15 +21.8 | fail | fail | no |
| RQ-20261022-b7e1-08 | ada_pullback_2h | 402 | BG25 | -9.11 | 0/6 | UB25 +7.0, UB33 +12.2, UB50 +23.1 | fail | fail | no |
| RQ-20261022-b7e1-08 (matched pairs) | ada_pullback_2h | 402 | BG25 | -9.11 | 0/6 | UB25 +7.0 | fail | fail | no |
| RQ-20261022-b7e1-10 | trend_donchian_eth_prop | 1085 | PL25 | -3.88 | 3/6 | UT20 +27.9 | fail | fail | no |
| RQ-20261022-eba2-07 | ada_pullback_2h | 402 | MT | +4.59 | 4/6 | UT +25.8 | fail | fail | no |
| RQ-20261022-eba2-08 | xrp_pullback_2h | 394 | MT | -9.92 | 2/6 | UT +16.1 | fail | fail | no |
| RQ-20261023-1d5c-01 | trend_donchian_xrp_4h | 68 | E30 | +0.58 | 5/6 | UT +3.2 | fail | fail | no |
| RQ-20261023-1d5c-02 | trend_donchian_sol_4h | 267 | E20 | +2.25 | 3/6 | UT +20.6 | fail | fail | no |
| RQ-20261023-1d5c-03 | trend_donchian_eth_4h | 275 | E20 | -28.04 | 1/6 | UT +20.6 | fail | fail | no |
| RQ-20261023-1d5c-04 | trend_donchian_sol_prop | 403 | C75 | +3.16 | 6/6 | UT +21.8 | fail | fail | no |

Reading: in every row the unconditional control is far *worse* than the incumbent (that is why the controls exist), so a candidate that beats `A` almost always beats its control; the clause removes a candidate only if it was about to pass. None was. The closest rows fail on materiality, not on controls: 1d5c-04 `C75` is +3.16 R in 6/6 folds but the bar is 0.02 R x 403 = 8.06 R; 1d5c-01 `E30` is +0.58 against a 1.36 R bar; eba2-07 `MT` is +4.59 in 4/6 folds against an 8.04 R bar and a 5-fold rule.

Two things this table cannot tell you. (a) `--vs-control` additionally requires the candidate to beat the control in >= `--fold-majority` folds; the b7e1/1d5c/eba2 rule text states only a net-R contrast, so the flag is slightly *stricter* than the registered clause. Irrelevant here (no candidate reached the contrast), but a future unit that wants the registered, net-only clause should say so. (b) Adding a conjunct to a pass condition can only turn a PASS into a FAIL, never the reverse, so a FAIL->PASS flip was impossible by construction for these 12; the "lead" branch of the task did not arise and no confirmation unit was registered.

## 4. What this leaves open

1. **The exposure moved forward, not back.** 10 queued units, `RQ-20261024-0142-01..10`, state a "matching UNGATED control" (`UT`, `UT20`/`UT30`, `UTL`/`UTM`, `UT15`/`UT35`/`UT40`) in the rule but carry no `--vs-control` in `run.command` (MEASURED: `grep -L -- --vs-control`), so they will be graded without the clause. `RQ-20261024-9a7e-01..04` do pass the flag. Filed as pipeline item `PI-20261024-HF1S5YZE-0001` and **fixed in this PR**: `--vs-control CAND=CTRL` added to all ten, pairs taken from the arms' identical action parameters (-02, -04, -06, -10 have two controls, e.g. -02 `C75M20=UT20`, `C75M30=UT30`); `dispatch_queue.py` dry run says `would_dispatch` for all ten; item closed `done`. Units 0142-11..17 and -26 have no control arm and need nothing.
2. **22 PASS verdicts are untouched** (queue `grading.verdict`, same 163): none of their rules names a control arm, so there is nothing to enforce. That is a registration choice, not a grader bug, and this lane does not reopen it. No PASS->FAIL occurred, so no downstream-decision pipeline item was needed for this reason.
3. Nothing is retired. Every FAIL stays on the record (operator rule, 2026-10-22).

## 5. Reproduce

`python3 scripts/research/regrade_vs_control.py --out <path>` (reads `research/` only; prints old verdict, reproduction flag, new verdict, per-unit pass sets).
