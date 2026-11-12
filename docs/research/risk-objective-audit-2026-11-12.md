# Risk-objective audit — which rules still grade on mean net R alone (2026-11-12)

> **Doc status:** `live` · category `research` · lane `RISK-OBJECTIVE-AUDIT` (Tier-1 doc; its proposals are Tier-3, see
> [`docs/proposals/risk-objective-tier3-proposals-2026-11-12.md`](../proposals/risk-objective-tier3-proposals-2026-11-12.md)).
> **Gates this adds or changes: none.** Nothing here edits a config, mandate, bar or workflow. Provenance of every figure: `MEASURED`
> unless a line says otherwise.

**Objective under audit** (operator 2026-10-29; [`OPERATING-PLAN`](../plans/OPERATING-PLAN-2026-09-21.md) § 2): absolute net P&L
first, in $ and % per account and book; risk reduction is the tie-breaker; a large risk cut for a small P&L cost wins. Its in-trade
form is `RULE-AM-RISK-ADJUSTED-V1` (`scripts/research/am_risk_adjusted.py`).

## 1. Inventory

"Mean-R only" = the pass/fail turns on the sign or size of mean net R (or total net R) with no drawdown, tail or variance term.

| # | Rule / metric | Where | Grades on | Verdict |
|---|---|---|---|---|
| 1 | Stage-0 → Stage-1 and Stage-1 → Stage-2 promotion bar (`MD-PROMOTE-S0-S1`, `MD-PROMOTE-S1-S2`, `RULE-D1-STAGE0-NET-OF-FULL-COST`) | `config/mandates.yaml` `bar:`; `scripts/ops/mandate_resolver.py` | `n>=30`, point-estimate `expectancy>0`, fold majority positive (sign of each fold's mean), holdout positive | **Mean-R only** (point estimate, no CI, no DD, no tail) |
| 2 | Stage-0 fail cut (`MD-S1-CUT-ON-STAGE0-FAIL`, R-CUT-EXPECTANCY/-FOLDS/-N) | same | expectancy ≤ 0, folds not a majority, n < 30 | Mean-R only, but `derisk_only` and demo-floor-protected: harm is bounded |
| 3 | Stage-2 demotion (`MD-DEMOTE-S2-S1`, autoland) | same; `scripts/ops/r4_demotion_gate.py` | last 40 trades as two 20-trade windows, both net R < 0 and < the leg's Stage-0 p10 | **Mean-R only.** A leg can bleed a deep drawdown through winners and recoveries and never fire; a leg can fire on two ordinary bad windows |
| 4 | Exit-lever gate (`RULE-M20-EXIT-LEVER-IS-OOS-GATE`, resolver clauses R-NET-R, R-FOLDS, R-DRAWDOWN, R-LEVERAGE) | `scripts/research/m20_sweep_result.py`, `mandate_resolver.py` ~L2300 | needs `d_net_r > 0` in BOTH windows, fold wins, then a DD *exchange-rate* cap | **Partly risk-aware, but the primary clause is mean-R.** A lever that cuts drawdown a lot for a tiny R cost fails R-NET-R by construction, which is the opposite of the objective |
| 5 | LTR tighten bound (`MD-LTR-*`, `MD-LIVE-TIGHTEN-SL`: `ev_delta_r >= -0.25` and `worst_case_delta_r > 0`) | `config/mandates.yaml` ~L1145, `scripts/research/live_review_outcomes.py` | mean R cost per trade, plus the single worst trade | **Inconsistent with V1**: tolerates 0.25 R/trade where V1 R1 allows 0.05; "worst case" is a sample minimum (n=1 statistic), not a tail mean or book drawdown |
| 6 | LTR hold-vs-option table | `live_review_outcomes.cell_stats` | reports mean, sd, worst, p05, giveback | **Reports risk fields; the apply bound uses only #5** |
| 7 | Desk grade (`desk_grade.py`: `edge_vs_random`, verdict `EDGE` when CI of mean excludes 0) | `scripts/ops/desk_grade.py` | mean net R vs a random-entry baseline, 95% CI of the mean | Variance-aware on the mean; **no DD or weekly tail**; reports `worst` only. Demo/paper only, so no live money rides it |
| 8 | Prop gate (`RULE-P5-GATE-BRK-PER-LEG-V2`, `V3`) | `scripts/research/prop_gate.py` | EV, per-attempt breach probability vs the firm's DD limits, plus (V3) CI lower bound of mean | **Already risk-adjusted. No change proposed** |
| 9 | Active-management graduation (`RULE-AM-RISK-ADJUSTED-V1`) | `am_risk_adjusted.py` | R1–R4 | **The target form.** Screen only until `BOOK-SIM-REAL-SIZER` |
| 10 | Performance-review headline | `.claude/skills/performance-review/SKILL.md` | net $/% per book + "sceptical quant" line per headline leg | Absolute-P&L first, as the objective asks. Book max DD / weekly p5 are not required scoreboard fields (§3) |
| 11 | Research-queue `decision_rule` text | `research/queue/**/*.yaml` | free text per unit | See §2 |

Not audited in depth (named so nobody assumes they were): `MD-ML-OVERLAY-CANARY` (bar compares to a same-rate random arm; I read only its header),
`MD-STRIP-A-ZERO-MEASURED-LEVER`, `MD-DERISK-ONLY-ROSTER-CUT` (both de-risk-only), `MD-SOAK-EXIT-CELL-PATHB`, the ML promotion ladder
(`/ml-review`), and `pairs`/macro sleeve rules.

## 2. Populations and evidence

### 2a. Stage-0 promotion bar over the committed evidence corpus
Population: `comms/strategy_evidence/*.json`, 65 files, 58 parse as records, 54 carry `n_trades_oos`; per-trade series read from each
record's committed `source_run` (net of the full cost stack, harness time-folds, pooled across folds). Trades are treated as
independent (a stated simplification; it flatters the CI).

* **13 of 54** records clear the bar as written (n ≥ 30, expectancy > 0, folds positive in a majority). 2 of the 13 (`e4_oi_shock`,
  `ml_entry`) have no readable per-trade `net_r` in their run file, so their risk figures are **could-not-look**, not zero.
* Of the **11 readable** passers: **9 have a 95% CI lower bound on mean net R ≤ 0**; only `slv_trend_1h` (+0.10) and
  `tqqq_trend_long_1d` (+0.02) clear 0.
* Max drawdown (R) vs total net R, same window: **3 of 11 have DD/net ≥ 0.5**: `trend_donchian_xrp_4h` 1.89 (DD 6.59 vs net +3.48),
  `scha_trend_long_1d` 1.79 (DD 8.31 vs net +4.64), `tlt_pullback_1d` 0.87 (DD 11.02 vs net +12.69); two of them have DD larger than the
  whole net. At the other end: `slv_trend_1h` 0.12, `gld_pullback_1h` 0.23, `tqqq_trend_long_1d` 0.24.
* Largest absolute drawdown: `trend_donchian_eth_4h` 20.70 R (net +44.64 R), `e4_oi_shock` 28.05 R on net +18.79 R over 856 trades
  (expectancy +0.022). At a 1% account risk that is a ~21% / ~28% peak-to-trough in account terms before compounding; at 1.5–2% it is
  worse. Which of these legs trade real money is a `config/accounts.yaml` fact I did not re-derive here; re-parse it, do not quote this.
* Weekly p5 outcome (mean of the worst 5% ISO weeks, R) ranges −1.0 to −3.2 R across the 11; `ada_pullback_2h` −3.20 is the worst.
* Per-trade tail mean (worst 5%) sits at −1.0 to −1.2 R for all 11: the stop is doing its job per trade, so **the risk is in clustering
  (drawdown, weekly tail), which a per-trade mean cannot see**.

Read: the bar admits legs on a point estimate whose interval includes zero and whose drawdown can exceed their entire net. Part of
that is the intended design (Stage 1 is a cheap mechanics soak, and the operator has said edge is decided offline); that is why the
proposals below are conditions on **Stage 2 real money and on sizing**, not on Stage 1.

### 2b. Exit and in-trade classes (what the screen says)
Population: the 7 records in `comms/research/am_risk_adjusted/regrade-2026-10-29.json` (re-read, not re-run; per-trade-R **screen**,
not the book $ simulation of record). **0 of 7 classes pass V1.**

* SL-to-break-even-after-peak on `trend_donchian_eth` (RQ-20261026-ed1c-17): BE075 −0.035 R/trade cost (a gain), DD cut 21.2%; BE10
  −0.021, DD cut 19.8%. R1 and R2 hold, **R3 fails (3 of 6 folds, need 4)**; R4 not evaluated (no control, row
  `HARNESS-BE-RANDOM-CONTROL`). Weekly p5 cut only 3.5%. Under the old R-NET-R gate (`d_net_r>0` in both windows) these two would also be
  judged on mean R first; the point is that a *small-cost / large-DD-cut* lever is exactly the shape V1 was written for and gate #4 cannot express.
* Giving up ≤ 0.05 R per trade is common (R1 true for 4 of 6 partial-close, 3 of 3 tighten, 1 of 2 predictor-gated tighten candidates);
  a ≥ 15% risk cut is rare (3 candidates in the whole re-grade, 2 BE and 1 predictor-gated tighten `UT`, whose R1 cost is 0.053, just over the line).

So replacing mean-R gate #4 by V1 would **not have changed any past verdict** on this corpus. It changes what a future lever is allowed
to be judged on.

### 2c. Research-queue decision rules (heuristic)
Population: 2,214 YAML units under `research/queue/**` that carry a `decision_rule`. Classified by a regex over the rule text
(mean/expectancy/net-R terms vs drawdown/tail/CI/survival terms). **Heuristic, not a parse**: a false "mean-only" is possible where a
rule states risk in prose without those words. Result: 777 mean-only, 1,100 mean+risk, 19 risk-only, 313 neither. Of the 777 mean-only:
665 are `done`, 42 `retired`, **71 still open (50 queued, 21 blocked)**. The open 71 are the only ones a template change could still reach.

## 3. What is already fine
Prop gate (#8) grades on survival against the firm's own limits. The performance review (#10) leads with absolute net P&L per book.
`RULE-AM-RISK-ADJUSTED-V1` exists and is wired. The exit gate already refuses a drawdown worsening. The demotion mandates only remove
exposure.

## 4. Gaps, ranked by money at risk
1. **#1 promotion bar to real money** admits a point-estimate edge with DD up to ≥ net. Largest exposure (`add_risk`).
2. **#4 exit-lever gate** forbids the exact trade the objective prefers.
3. **#5 LTR tighten bound** is 5× looser than V1 on cost and uses a sample minimum for tail.
4. **#3 Stage-2 demotion** cannot see a deep drawdown; its false-fire/false-hold behaviour in drawdown terms is **not measured here**.
5. #6/#7/#10 reporting gaps (no book DD / weekly tail columns), Tier-1 and non-gating.

## 5. Follow-through
Proposals: [`docs/proposals/risk-objective-tier3-proposals-2026-11-12.md`](../proposals/risk-objective-tier3-proposals-2026-11-12.md).
Operator one-off this week: **no demotion lands without the operator looking.** Nothing in this audit changes a demotion path.
Reproduce §2a: `python3 -I` over `comms/strategy_evidence/*.json` with `am_risk_adjusted.weekly_book`/`max_drawdown`/`_tail_mean`
(the fields above are `path_stats.max_drawdown_r`, `net_r_oos`, `folds_positive`, `folds`).
