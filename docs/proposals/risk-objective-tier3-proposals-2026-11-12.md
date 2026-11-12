# Tier-3 proposals — risk-adjusted forms for mean-R-only rules (2026-11-12)

> **Doc status:** `unknown` · category `unknown` · last verified `never` · lane `RISK-OBJECTIVE-AUDIT` · evidence: [`docs/research/risk-objective-audit-2026-11-12.md`](../research/risk-objective-audit-2026-11-12.md)
>
> **Gates this adds or changes:** P1 changes a promotion bar (adds a clause to `MD-PROMOTE-S1-S2` only). P2 changes the exit-lever
> gate's primary clause. P3 changes an LTR auto-mandate bound. P4 is a research-template change. P5 is a reporting change (no gate).
> **Every one needs the operator's explicit permission; none is applied by this lane.** Ambiguity is read as *less*. Nothing here
> touches a demotion path (operator one-off this week: no demotion lands without the operator looking).

All proposals follow the objective: net P&L stays the first test; the new term only bites when it is cheap to satisfy or large to
violate. `RULE-AM-RISK-ADJUSTED-V1` thresholds are reused so no new number is invented.

| ID | Proposal | Replaces | Evidence on the current corpus | Cost if wrong | clears_when (machine-checkable) · owner |
|---|---|---|---|---|---|
| **P1** | Add to the **Stage-1 → Stage-2 (real money) bar only**: (a) Stage-0 `max_drawdown_r` ≤ `K` × `net_r_oos` (propose `K = 1.0`, i.e. a drawdown no larger than the whole net) and (b) report CI lower bound of mean net R beside the pass, **reported, not a clause**. Stage-0→Stage-1 stays as is. | the bare `expectancy_gt: 0` for `MD-PROMOTE-S1-S2` | 13 of 54 records pass today; of 11 readable, 2 have DD > net (`xrp_4h`, `scha_trend_long_1d`) and would be held back by (a); 9 of 11 have CI lower bound ≤ 0 (so (b) would be a column, not a clause, or it would block 9 of 11). `K=1.0` is a screen; `K` is the operator's choice. | A true-edge leg held a little longer in Stage 1 (cheap) | once the operator grants P1 and the clause (named `R-DD-VS-NET` in the change) is implemented, `scripts/ops/mandate_resolver.py` REFUSEs `xrp_4h` and `scha_trend_long_1d` on it and passes the other 9 readable (a test over `comms/strategy_evidence/` asserts this) · **owner: AM-TRADING** |
| **P2** | Replace `R-NET-R` (`d_net_r > 0` in both windows) in the exit-lever gate by **R1–R4 of `RULE-AM-RISK-ADJUSTED-V1`**; keep R-FOLDS, R-DRAWDOWN, R-LEVERAGE. Stays a screen until `BOOK-SIM-REAL-SIZER` lands, per V1. | `R-NET-R` | Re-grade of 7 records (screen): 0 pass either way, **no past verdict changes**. The shape it newly admits (BE075: −0.035 R cost, DD cut 21%) fails V1's R3 (3/6 folds) and R4 (no control), so it is *not* graduated by P2. | None on live: every in-trade class stays advice-only | `RQ-20261029-1f39-01` unblocked and graded under V1 · rows `HARNESS-BE-RANDOM-CONTROL`, `BOOK-SIM-REAL-SIZER` · **owner: AM-TRADING** |
| **P3** | Align the LTR tighten auto-bound with V1: `ev_delta_r >= -0.05` (was `-0.25`) **or** (`ev_delta_r >= -0.25` and a measured ≥ 15% cut in the cell's weekly-p5 / drawdown), and replace `worst_case_delta_r > 0` (a single-trade minimum) by `p05_r` delta > 0 where the cell is `measured`. | `MD-LTR-*` / `MD-LIVE-TIGHTEN-SL` bound | Tighten classes in the re-grade: R1 holds for 3 of 3 (f08c) and 1 of 2 (9a7e) candidates; risk cut ≥ 15% in 1 of 5 (`UT`, cost 0.053, so it misses the 0.05 line). The bound as written would admit tightening V1 rejects. | Fewer auto-tightens while the screen is a screen | `check_mandates` passes with the new bound; `live_review_outcomes` cell carries `p05_r` delta · **owner: AM-TRADING** (mandate edit is the operator's to grant) |
| **P4** | Registration template: units whose `decision_rule` grades an exit/in-trade class must register V1; entry/strategy units must *state* DD and weekly-p5 beside net R. No new pass clause for strategy units. | free-text mean-only rules | 71 open units (50 queued, 21 blocked) have a mean-only rule by a regex heuristic (not a parse); 665 done units unaffected. | Minor template friction | `scripts/research/` lint reports 0 open mean-only exit-class units · **owner: research-ops** |
| **P5** *(Tier-1, can land without Tier-3 approval, listed for completeness)* | Add book max DD and weekly p5 columns to the performance-review Scoreboard and the desk-grade verdict. Reporting only. | none | §2a shows the risk lives in clustering, which per-trade means hide. | None | review JSON carries `book_max_dd_r` / `weekly_p5_r` with a read-state · **owner: perf-review lane** |

## What this lane did not propose, and why
* **A drawdown trigger for Stage-2 demotion (`MD-DEMOTE-S2-S1`).** The audit shows it is mean-R-only, but I did not measure how often a
  DD trigger would false-fire against Stage-0 bootstrap windows, so there is no evidence to propose a number, and a demotion cannot land
  this week without the operator looking in any case. Filed as the open question: *what 40-trade-window drawdown quantile of the leg's own
  Stage-0 series would have fired on a leg later shown net-negative?* clears_when: a committed bootstrap record under
  `comms/research/` for the legs with n ≥ 40; owner AM-TRADING.
* **Any change to the prop gate** (already risk-adjusted).
* **Any ratio objective** (Sharpe/Calmar as a bar). The operator said ratios are not the objective; P1 uses DD vs net as a screen
  because it is the one pair the corpus already carries (`path_stats`), not as a target.
