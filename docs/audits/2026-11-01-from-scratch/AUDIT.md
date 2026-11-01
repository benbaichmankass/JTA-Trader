# From-scratch audit, 2026-11-01: the system has no edge, and its method could not have found one

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Lane `SYSTEM-AUDIT-FROM-SCRATCH` (session_01AFoLuHh8ox2kJKo8Gaf5wr), dispatched by Manager Session 2026-11-01a (session_01AFoLuJ1apgy8sfngu4WyNH). Measured 2026-11-01 ~08:20–08:45Z. Checklist row [`SYSTEM-AUDIT-FROM-SCRATCH`](../../claude/work/checklist/SYSTEM-AUDIT-FROM-SCRATCH.json). Tier 1, analysis only: nothing in config, strategies, rosters or the order path was changed.

**Gates this adds or changes:** none. The doc *proposes* changes. Several of them remove gates or process. None is filed or applied: the operator picks a plan at Thursday planning, or sooner.

**Operator, 2026-11-01 ~08:00Z, verbatim (the question this answers):** *"I do want a lane now to do a very harsh audit of our system and say, if I was creating this from scratch today, this is how I would build it."*

---

## 0. Verdict in ten lines

1. **Nothing makes money.** Real money: **496 closed trades since 2026-05-09, profit factor 0.64, 26% wins, net −$131.** Remove the 318 `vwap` scalps and it is still PF **0.70** over 178 trades. Prop: all 3 live accounts are below their starting size (−2.0%, −2.4%, −3.2%). The mirror book: PF **0.57** over 154 trades. Paper: PF **0.97** over 1,655 trades.
2. **Before costs the real book is about flat (≈ −$41 gross). The estimated fees and funding (≈ $90) are the loss.** That is what zero edge plus trading costs looks like. It does not look like a good strategy with bad plumbing.
3. **The research method selects noise.** In October alone 1,281 queue units ran, and 281 units ever PASSED. The PASS rule is mostly "net R > 0 with n ≥ 39". **The repo's own trial ledger (2026-10-30) finds 0 of 28 Stage-0 passes survive a multiple-testing haircut (DSR + BHY), and that includes all 6 legs on real money.** The ledger is `report_only` by decision. **All 21 confirmatory re-runs FAILED.**
4. **The ideas have no reason to work.** 147 of the 149 harness-dispatch units (98.7%) run retail chart-pattern harnesses (pullback, Donchian trend, squeeze, FVG, fade, chop, ORB, ICT). Most other strategy units tweak exit and entry levers on those same legs. The families with a documented economic payer were never actually tested: funding carry has 0 measured results (`producer_failed` ×2, queued 33 days); cross-sectional momentum has 1 wiring-only run; TSMOM has 0.
5. **ML has changed nothing.** 98 models are registered: 63 regime classifiers and 0 trade-decision models in production. The only order-changing model, an exit head, closed 11 trades (5 real-money, net −$1.13).
6. **Process eats the effort.** October on `main`: **3,052 commits to `docs/claude/work/` vs 284 to `src/`, a ratio of 10.7 : 1.** The 2026-09-21 reset was written to fix a ratio of 7.1 : 1, so it has got worse. The repo carries 120 CI guards, 192 workflows, 643 KB of skills, 1,169 checklist rows (334 `landed_unproven`), and 15 research SLOs that all measure volume (none measures discoveries).
7. **The prompts measure activity, not money.** The 66 KB manager skill never mentions net P&L. The brief has no P&L line. Weekly audits grade their "calls" (8 hit / 0 miss on 10-28) while the book loses. The 09-21 plan opened on −0.3231R/trade. Six weeks later it is −0.333R/trade, and no document says the plan failed.
8. **Graded, but the grade never acts.** The real-money legs and Stage-0 promotions are graded and nothing changes. ML has no continuous decision-value grader. 9 graders exist that never run, against 9 scheduled (§ 1f). **Earlier audits graded the plumbing.** 09-29, 10-04 and 10-29 ranked reconciler labels, phone executors and TP-guard compliance. The 10-29 audit *had* the 0-of-31 DSR finding and filed it at #4 as "re-rank a queued row".
9. **From scratch, I would trade fewer, better-founded things**: delta-neutral funding carry, vol-targeted trend across a diversified set, cross-sectional crypto momentum/carry. One research protocol: a locked holdout, every trial counted, a DSR gate. One pooled market-label entry model before any bracket or management model. Process cut to about a tenth.
10. **Keep** the execution plumbing, journal, provenance, cost module, trial ledger and data pulls. **Stop** the generated lever units, the volume SLOs, real money on legs that fail the haircut (Tier-3: the operator's call), new guards and judgement-desk work on legs with no edge. The first checkpoint is day 14 (§ 7).

---

## 1. Outcomes, measured first (before reading any plan)

Every number names its population and source. Reproduction is in § 10. Dollar figures are aggregates the public `/api/bot/performance` already publishes. No balances or account numbers appear here.

### 1a. Realized P&L per book

Population: the `trades` journal, all 6,816 rows, read 2026-11-01 ~08:20Z through `/api/diag/journal?table=trades` (7 pages, `total_rows_state: counted`). The aggregates below are over `status = closed AND pnl IS NOT NULL` (2,305 rows; 159 closed rows have null P&L and are excluded). Books are split by `account_class`, plus the mirror accounts `bybit_portfolio` and `alpaca_portfolio`.

| book | n closed | PF ($) | win % | net | by month (PF) |
|---|--:|--:|--:|--:|---|
| **Real money** (`bybit_2`, `alpaca_live`) | 496 | **0.64** | 26.4 | −$131 | May 0.51 (n 349) · Jun 4.78 (23) · Jul 0.67 (37) · Aug 1.74 (31) · **Sep 0.01 (31)** · Oct 0.54 (25) |
| Real money ex-`vwap` | 178 | 0.70 | — | −$81 | since 2026-06-01: n 147, PF 0.70 |
| **Mirror** (Stage-2 paper twin) | 154 | **0.57** | 28.6 | — (paper notional) | Jul 0.72 · Aug 1.37 · **Sep 0.06** · Oct 0.66 |
| **Paper** (soak + floor) | 1,655 | 0.97 | 41.8 | — (paper notional) | May 0.40 · Jun 0.59 · Jul 0.50 · Aug 2.94 · Sep 0.42 · **Oct 0.16** |
| **Prop** (3 live accounts) | 51 priced closes (+13 closed unpriced) | 0.81 | — | all 3 below account size: −2.0%, −2.4%, −3.2% | `/api/bot/prop/fills` (208 rows) + `/api/bot/prop/overview` vs `config/accounts.yaml::account_size_usd` |

- **Cross-check against the API.** The real-money block of `/api/bot/performance?window=all` reads n=472, PF 0.596, totalPnl −$146.04, expectancy **−0.333R** (it excludes reduce legs and some reconciler rows, which is why its n differs from my 496). Both populations say the same thing.
- **R is not trustworthy as a yardstick here.** The API marks 407 of 472 real-money trades `rProvenance: unverified`, and 318 take R from the stored (often trailed) stop. My own R off the journal's stored stop gave the wrong sign for whole months (paper Sep: +341R on a −$18.9k month). **So this audit grades on profit factor and $, which need no stop.** That the system cannot measure its own R is itself cause C4.
- **Costs.** Real-money estimated fees plus funding are **$90.04** against net −$131.37, so gross ≈ **−$41**. Of 488 real rows with fee fields, `cost_source = estimate` on **485** and `broker` on **3**. The system does not measure its realized cost.

### 1b. Legs that reached real money, and how many are net positive there

**16 strategy names** have closed real-money trades (17 including `orphan_adopt`, which is not a strategy). **5 are net positive**: `trend_donchian` (PF 2.21, n 15), `htf_pullback_trend_2h` (2.98, n 8), `trend_donchian_eth_4h` (1.26, n 19), `fade_breakout_4h` (1.24, n 9) and `tlt_pullback_1h` (n 1). Every one has n ≤ 19, which is too few to tell from luck (the trial ledger in § 1c agrees). The two largest current real-money legs are negative: `xrp_pullback_2h` PF 0.20 (n 20) and `ada_pullback_2h` PF 0.65 (n 18).

Mechanics on the real book, over 2,094 real-money attempt rows: 514 closed, 1,102 `rejected` (risk refusals and the like), 356 `exchange_rejected`, 119 `orphaned`. Of the 514 real closes, **138 (26.8%)** have no TP / SL / strategy-close reason (reconciler, backfill, orphan, netting). These are real defects, but they move little money. Earlier audits spent most of their pages here.

### 1c. Research throughput and yield

Population: `research/queue/RQ-*.yaml`, 1,684 units parsed: 1,382 done, 251 queued, 51 retired. Of the done units, 1,281 are dated October.

| verdict (done units) | n | share |
|---|--:|--:|
| fail | 756 | 55% |
| **pass** | **281** | 20% |
| indeterminate | 190 | 14% |
| ungraded | 147 | 11% |
| no_action_warranted | 8 | 1% |

- **By theme:** `new_strategy_prop` 479 units (93 pass); `live_strategy` 404 (91 pass); `regime` 181 (38); `ml_health` 139 (31); `macro` 98 (**13 pass, 84 fail**, and these are the only family graded on a t-stat bar of |t| ≥ 2.4); `timeframes` 35; `infra` 7.
- **Did passes hold up?** All **21 of 21** "Stage-0 confirmatory re-run" units FAILED. "Re-validation at power" went 15 pass / 3 fail. Holdout re-runs went 8 pass / 3 no-action, but those test *exit levers* on legs that themselves fail the haircut.
- **The trial ledger is the decisive number.** `comms/research/RQ-20261016-6013-01/41103441836/trial_ledger.json` (generated 2026-10-30 by `scripts/research/trial_ledger.py`) counts configs tried per family: **trend 1,388, pullback 1,355**, ict_scalp 60, fvg_range 9, squeeze 18. Of the 28 evidence records that pass Stage 0, **0 survive "DSR > 0.95 AND BHY-haircut expectancy > 0"**. Only 3 survive even Bonferroni. The six real-money legs score DSR 0.04 to 0.39 (bar 0.95):

  | real-money leg | configs tried | effective N | DSR |
  |---|--:|--:|--:|
  | ada_pullback_2h | 247 | 38 | 0.39 |
  | trend_donchian_sol_prop | 140 | 35 | 0.36 |
  | trend_donchian_eth_4h | 168 | 43 | 0.30 |
  | iaum_pullback_1d | 43 | 24 | 0.24 |
  | trend_donchian_xrp_4h | 169 | 51 | 0.06 |
  | xrp_pullback_2h | 191 | 37 | 0.04 |

  The ledger is `report_only` by operator decision on 2026-10-16 ("Measure first (Recommended)"). Two weeks later, measuring has not led to any decision.
- **Baseline harness cells look like noise.** Over 128 single-symbol Stage-0 harness cells with n ≥ 39 (pullback / squeeze / trend / fvg / fade / chop / pairs / orb, from `research/results/*/*.jsonl`), the median net expectancy is −0.018R/trade and the mean is −0.035R. A rough z (taking per-trade SD as 1.0R or 1.5R) puts 4 to 13 cells above z = 2, where ~3 are expected by chance alone, and 26 to 31 below z = −2. **Some signal may exist in the tail, but those cells are correlated, and the system's own PASS bar (point estimate > 0) cannot tell that tail from the 47 positive cells around it.**

### 1d. ML

Population: `/api/bot/ml/registry` (mirror age 22 s, 98 rows) and close reasons in the journal.

- **98 models registered.** Target stage: candidate 74, shadow 20, advisory 3, research_only 1. Family: LightGBM classification 66, LightGBM regression 11, baselines 14, HMM 5, TCN 1, SSL encoder 1. **63 are regime classifiers.**
- **The 3 "LIVE" advisory models** (BTC/SOL 15m regime fc-pcv v2, MES 5m regime v2) have `linked_strategies: []`. The P_win entry head is observe-only by construction (`src/runtime/entry_head_pwin.py`).
- **Models that changed an order:** an exit head closed **11 trades** (`exit_reason = exit_head`: 5 real-money, net −$1.13; 6 paper). I found no other order-changing model in the close reasons. **Models that changed P&L by a measurable amount: 0.**
- Evaluation is log-loss or macro-F1 against a class prior (e.g. `RQ-20261015-eda2-01`, `RQ-20261027-b376-01`), not decision value net of cost. The ML programme (2026-10-28 § 0) itself records that the linear in-trade model PASSES on log-loss and FAILS on money (`RQ-20261024-09a6-01` vs `d6e7-06`).

### 1e. Spend and effort vs output

- **Claude usage.** Spend is recorded on 249 of 1,169 checklist rows, totalling $3,688 at API-equivalent prices. Plan usage is the real constraint (canonical § "Nothing spends Anthropic API credits"), so this is a lower bound used for comparison, not cash. The most expensive rows are governance: `B1` guard inversion $435, `B2` mirror invariant $229, `E13` ID collision check $88, `A8` backlog rescue $76.
- **Commits on `main`, 2026-10-01 → 11-01** (5,719 total): `docs/claude/work/` 3,052 · `comms/` 1,448 · `research/queue/` 913 · `scripts/ci/` 119 · `.claude/skills/` 121 · **`src/` 284** · `src/units/strategies/` 23 · `config/strategies.yaml` 26.
- **Rule and process surface:** canonical rules 154 KB, architecture 286 KB, operating plan 64 KB, skills 643 KB (manager 66 KB, performance-review 68 KB), 1,348 docs (20.7 MB of markdown) against 216,552 lines of Python in `src/`.
- **Output:** no leg survives the haircut, the real book has PF 0.64, and no model has changed P&L.

### 1f. The grading test (added at the manager's request, 2026-11-01 ~08:25Z)

The question, relayed from the operator (*"we can't build models if we're not actually grading them"*): for every model, strategy decision and forecast, is it graded **continuously on its own decision value** (forecasts on first passage within their horizon), and **does the grade feed back into what is built next?**

**Population and method.** 28 tracked `.py` files under `scripts/` and `src/` with grade, grader or scor(e/ing) in the name, excluding tests. For each I grepped `.github/workflows/*.yml` (and checked for `schedule:`), `deploy/*` units and every tracked `*.sh` for a caller. I also took the last commit date of each grader's output store on `origin/main`. **The limit:** a VM cron that calls a script by a path not in the repo would not show up here. Inside the repo the probe can find a positive: `queue_grade` turns up in `research-queue-grade.yml` and in `deploy_pull_restart.sh`.

| what is decided | grader | runs? (schedule · output) | graded on decision value? | feeds what gets built? | money at stake |
|---|---|---|---|---|---|
| **Real-money strategy legs** (6 production) | `performance-review` → `comms/claude_strategy_scores.jsonl` (4,388 lines, last commit 11-01); `r4-demotion-gate.yml` (cron) | **yes** | per-trade grades, yes. Demotion needs n ≥ 40 live trades, so it returns `abstain_thin` on 6/6 (10-29 audit) | **no**: all 6 legs still on real money at PF 0.20–1.26 | **highest**: the real book |
| **Stage-0 promotions** | `trial_ledger.py` (last commit 10-31) | **yes** | yes (DSR + BHY) | **no**: `report_only` by decision, 0/28 survive and nothing changed | every leg on any roster |
| **Research units** | `queue_grade.py` (`research-queue-grade.yml`, cron) | **yes** | on a point-estimate bar (C2), not on significance | yes, but it feeds more lever units (C5) | indirect |
| **Live trade reviews** (in-trade advice) | `live_review_grade.py` (`live-review-rows-mirror.yml`, cron) → `comms/live_review/outcomes.jsonl` (158 rows, 10-31) | **yes** | **18 of 158 priced** (140 `no_path_change`). The 18 priced read **+15.15R, 17 of 18 positive**, as counterfactual replays | **no**: the earlier audit found the reviews unapplied, and nothing promotes a class that prices positive | small today. **This is the only positive number this audit found. It is worth a pre-registered test on a disjoint window before anyone reads it as edge (n = 18; counterfactual, not realised).** |
| **Desk decisions** | `claude_role_grade.py` (`desk-decisions-mirror.yml`, cron) → `comms/desk/role_grade.json` | **yes** | n = 6 priced. Brier **0.297 vs 0.25 coin-flip reference** (skill −0.19). Verdict INDETERMINATE | no | small |
| **Closed-trade order packages** | `score_order_packages.py` (`grade-closed-trades.yml`, cron); `counterfactual_grader.py` (cron) | **yes** | yes for the counterfactual | not traced | small |
| **Closed-trade Claude scores** | `comms/claude_trade_scores.jsonl` | **dead store**: 1 line, last commit 10-01 | — | — | — |
| **ML models** (98 registered; 3 advisory, 20 shadow) | no scheduled grader of *served* predictions on decision value was found. Registry metrics are offline log-loss/F1 | **no continuous decision-value grade** | no | no | the whole ML track (§ 1d) |
| **Forecasts** (desk AM judgement, regime heads) | `desk_am_judgement_grade.py` | **never run**: no workflow, no unit, no caller (the operator's example, row `FORECAST-GRADE-FIRST-PASSAGE`) | first-passage logic exists | no | every forecast-driven decision |

**Graders that exist and never run** (no workflow, no `deploy/` unit, no `*.sh` caller, no importer): `desk_am_judgement_grade.py`, `exit_head_final_fold_grade.py`, `grade_closed_trades_from_diag.py`, `blind_grade.py`, `check_claude_grade_loop.py`, `regrade_vs_control.py`, `am_class_regrade.py`, `qtm1_grade.py`, `regrade_wiring_only_results.py`. `p1_costnet_grade.py` runs only from a manual `.sh`; `net_r_regrade.py` only as an on-demand system-action. **9 never run plus 2 manual-only, against 9 scheduled.**

**Ranked by money.** (1) The real-money legs and Stage-0 promotions *are* graded, and the grade does not act. That is a feedback gap, not a grading gap, and it is the most expensive one (C2, C4). (2) ML has no continuous decision-value grade at all, so no model can earn its way in or out. (3) Forecast graders are written and never scheduled. (4) The LTR grade prices only 11% of its rows. Its priced slice is the one positive signal found, and nothing acts on it either.

**The outcomes are the verdict.** Six months and thousands of commits have not produced one strategy with evidence of edge, and the live record agrees.

---

## 2. Earlier audits and reviews, treated as suspects

| doc | what it ranked first | was the call right? | how it was lenient |
|---|---|---|---|
| `docs/audits/system-audit-2026-09-29.md` (E75, $270 budget) | Alpaca naked re-arm; reconciler mislabels; grading hop stopped | correct as plumbing | **never stated the P&L verdict.** 94 findings, "0 critical", and not one about edge |
| `docs/audits/system-audit-2026-10-04.md` | breakout_1 $2 under its DD floor; prop executor alerts | correct as ops | **same: money at risk from mechanics, none from the strategies themselves** |
| `docs/plans/OPERATING-PLAN-2026-09-21.md` § 1 | −0.3231R real money; "research terminates in a memo" | the diagnosis of throughput was right | **its cure, more research throughput, worked as designed (1,281 units in October) and yielded nothing.** It assumed a backtest pass is evidence. It never asked whether the hypotheses were any good |
| `docs/reviews/2026-10-28-weekly-audit.md` | controls blind; registers growing | its trend analysis is honest | **grades its own calls "8 hit / 0 miss" on process items.** No P&L series anywhere in it |
| `docs/reviews/2026-10-29-system-conformance-audit.md` | prop survival gate is a form check; demotion can't fire | **closest to right**: "every gate is mean-R with no $ term"; "0 of 31 Stage-0 passes survive DSR + BHY" | **it had the finding that invalidates the whole roster and ranked it #4, closing it as "re-rank a queued row".** It explicitly scoped out the question of whether any edge exists |

**The pattern.** Every audit was asked "is the system working as designed?" and none was asked "is the design making money?". Each therefore produced a long list of real, small defects. Those lists read as "on the right track, fix A, B and C", because a long defect list implies the frame around it is sound.

---

## 3. Causes, ranked by money

Each cause comes with a count. Ordering is by how much of the loss it explains and how much it stops future learning.

### C1. No economic hypothesis behind the strategies (explains the gross ≈ 0)

- **Where the ideas come from.** ICT/SMC concepts (FVG, killzones, turtle soup), VWAP crosses, Donchian breakouts, ATR pullbacks and squeezes, on crypto perps at 5m–4h. None of these comes with an answer to *who is paying you, and why*. The academic evidence on technical rules after data-snooping correction is mostly negative (ACAD: Sullivan, Timmermann & White 1999, *J. Finance*; Bajgrowicz & Scaillet 2012, *JFE*).
- **The count.** Of the 149 units that dispatch a harness (`run.inputs.harness`): pullback 52, trend 37, squeeze 33, fvg_range 6, fade 6, pairs 5, chop_scalp 5, orb 2, ict_scalp 1, **xsec_momentum 1 (wiring-only result), funding_carry 1 (2 × `producer_failed`, never measured)**. TSMOM and vol-target have 0 dispatched units. Across all 1,684 unit files, a text match finds pullback in 151 and trend in 106, against funding carry in 1. The harnesses for the families with a documented payer (`scripts/backtest_funding_carry.py`, `backtest_xsec_momentum.py`, `backtest_tsmom.py`, `backtest_vol_target.py`) **exist and were never used.**
- **The live result matches the hypothesis quality.** The real book is gross ≈ flat, then net negative by its costs (§ 1a).

### C2. A research method that turns noise into "PASS" (explains why the roster is full of losers)

- **Decision rules.** The template Stage-0 rule is `PASS IF net_total_r > 0 AND n_trades >= 39`. Lever units pass if `net_r(C) > net_r(A)` by ≥ 0.02R × n plus fold counts. Of the decision rules, **6 of 1,429** mention $ or % return (10-29 audit). With no significance bar, about half of zero-edge cells pass before costs.
- **The number of tries is enormous.** About 2,750 configs were tried in the trend and pullback families alone (trial ledger). Then come "lever transfers" (a lever that passed on one leg is generated onto the others), 96 "Programme 01 Q9 runway fill" units, and 70 "Breakout prop fit" units. **Each family is searched until something passes, and that is what goes to real money.**
- **Policy amplifies it.** Operating plan § 3, operator 2026-09-27: *"our default is never to just kill ideas because of one bad pass ... always strive for refinement."* That is a sound instinct for an idea with a mechanism. Applied to a chart pattern with none, it guarantees a false positive in the end.
- **The evidence it is noise.** 0/28 survive DSR + BHY. 21/21 confirmatory re-runs fail. Paper PF swings from 2.94 in August to 0.16 in October, and the `pairs_sol_eth_a/b` siblings read PF 0.61 vs 2.24 on n ≈ 186 each. One history, re-sliced.
- **There is no locked holdout.** The confirmatory unit says so itself: *"this re-run measures the same instrument over a trailing window that has moved only by the days since the first pass; it confirms reproducibility, not out-of-sample generality"* (`RQ-20261011-1fce-01`). The harness has no window input.

### C3. Costs: under-charged in research, unmeasured live, maximised by the timeframe

- **Live:** estimated costs of ≈ $90 turned gross −$41 into net −$131 (§ 1a). 485 of 488 real-money cost rows are estimates.
- **Research:** of 1,221 result rows since 10-15, 87 ran at 0 fee, 719 carry no fee flag, 396 ran at 7.5 bps vs the measured 11.0, and funding is a flat 1 bps / 8h rather than the settled series (10-29 audit #10; not re-measured here).
- **Timeframe:** the largest real-money leg ever, `vwap`, was 318 five-minute scalps at PF 0.49. On a small book, short holding periods multiply a fixed cost per trade.

### C4. The yardstick is broken

- R comes from a trailed stop on most trades (API: 318 of 472 storedStop; 407 unverified). Gates and demotions are in mean R with no $ term (10-29 audit #3).
- Demotion needs 40 live trades, which takes 13 to 261 weeks per leg (10-29 audit #2). So **losing legs cannot be demoted by the mechanism meant to do it**, and the asymmetric CI guard (operating plan § 1) means nothing blocks adding legs.

### C5. Process overhead crowds out research

- **Effort:** a commit ratio of 10.7 : 1 (registers : src) in October. 120 guards. 192 workflows. 1,169 checklist rows, 334 of them `landed_unproven`. Pipeline due items 253 → 510 in one week (10-28 audit C6).
- **The research loop's own SLOs reward volume.** All 15 of `scripts/research/research_slo.yaml` measure supply, fires, lands, latency or age (`runnable_floor`, `fires_24h ≥ 24`, `lands_24h ≥ 12`, `authoring_supply_ratio_7d`, `theme_share_min_ratio` …). **Not one measures a finding that survives.** The manager skill requires a same-day AUTHORING lane whenever supply breaches. The system has been told, in binding text, to make more tests.
- Most of that throughput is generated: 1,133 research batch-land commits and 842 research-queue stamp commits in October.

### C6. Prompts that produce reassuring summaries

- `manager/SKILL.md` (66 KB) mentions "net P&L" or "profit factor" **0** times; `performance-review` (68 KB) 0; `weekly-audit` 0; `programme-review` 0.
- The daily brief's six fixed sections (*what came due · taken under mandate · decisions · what moved · what is running · spend*) have **no P&L section**. "What moved" counts activity.
- Reviews open by grading their prior *calls*. A call like "file X" or "fix the guard" is easy to hit. So a review can score 8/0 while the book has PF 0.01 for the month (September).
- Audits are scoped as conformance ("does it match the design spec") and are told to rank by "money at risk", which reads as *mechanical* risk. **The question "would a sceptical quant believe any of these legs has edge?" is in no prompt.**

### C7. Mechanics drag (real, small, over-weighted so far)

26.8% of real closes are not TP / SL / strategy-close. There are 356 exchange rejections and 119 orphans on real money. Prop runs through browser/phone UI automation (13 of 64 prop closes unpriced; executor latches). These need fixing, but at PF 0.64 a perfect pipeline still loses money.

### C8. The book is spread too thin to learn anything live

57 legs (`config/strategies.yaml`, 10-29 audit) across 11 live accounts produce about 25–37 real-money closes a month. No leg can reach significance live in a year. The ML corpus of strategy trades is 2,627 trades (ML programme § 0). That is small, and it is conditioned on entries with no edge.

---

## 4. The ML direction (row ML-DECISION-MODELS), critiqued

Lane ML-DECISION-MODELS's `DIAGNOSIS.md` **had not landed on `main` at 2026-11-01 ~08:50Z** (`git ls-tree origin/main` shows no such file). Its row has landed (`state: queued`, updated 07:45Z), carrying the operator's decision and the manager's diagnosis to test. So this section critiques the direction as that row and the dispatch state it: *three market-context decision models (entry / brackets / manage), pooled across symbols, trained on any useful data, no sizing.*

- **What is right about it.** Pooling across symbols on *market* labels (forward returns, MFE/MAE quantiles) instead of strategy-trade labels moves n from about 2.6k trades to millions of bar-observations. It breaks the dependency on legs with no edge. This is the most important correction in the ML plan to date.
- **The entry model is the alpha model, so build it first and judge it as a strategy.** A bracket or management model cannot create edge from an entry that has none. The ML programme's "0.756 R/trade hindsight oracle" is a ceiling no causal policy approaches. The order should be entry → (only if entry clears) brackets → manage.
- **Labels and metric.** Train on cost-adjusted forward return over a fixed horizon (or triple-barrier, PRAC: López de Prado 2018, *AFML* ch. 3). Score on **decision value**: the net-of-cost P&L of acting on the model's top-k vs a vol-targeted equal-weight baseline, under purged and embargoed CV (AFML ch. 7). Never score on log-loss alone. The repo has already shown that log-loss passes and money fails (§ 1d).
- **The danger: three models multiply the forking paths.** Each model family × feature set × horizon is a trial. Without the protocol in § 5b (a locked holdout and every trial in the ledger, gated by DSR), the ML track will reproduce C2 exactly, with fancier tools. **The trial ledger must cover ML experiments before the first entry-model result is read.**
- **The live bar the operator chose on 2026-11-01** (row `ML-DECISION-MODELS` note on `main`, popup answers verbatim) is a held-out mean net R per decision **"Point estimate >= 0"**, no CI bound, and **"Straight to real money"**, so that the model *"needs to prove that it won't lose money"*. This is the operator's decision, and this audit does not dispute it. The arithmetic of what that bar can and cannot show belongs in front of them, though:
  - A model with **zero** true edge clears "point estimate ≥ 0" about half the time before costs. If k model variants are each read against the bar, the chance that at least one clears it is 1 − 0.5^k: **97% at k = 5, 99.9% at k = 10.** This is mechanism C2 (§ 3).
  - A point estimate cannot show "won't lose money". With n = 1,000 held-out decisions and a per-decision SD of 1R, the standard error is about 0.03R. A model that truly loses 0.03R per decision still clears the bar about 16% of the time.
  - **The proposal keeps the operator's bar and closes the loophole.** Register **one** model per question before the holdout is read, read the holdout **once** (§ 5b), and report the trial count beside the point estimate. Whether to add a CI bound stays the operator's preference (Tier-3). This is listed as proposal `ML-BAR-ONE-READ` in § 8; it is not applied.
- **The baseline it must beat is not "the leg as traded"** (that bar is too low, PF 0.64). It must beat simple factor portfolios on the same universe: TSMOM vol-targeted, cross-sectional momentum, funding carry. If a gradient-boosted pooled model cannot beat 12-1 momentum net of cost, it is not adding value.

---

## 5. From scratch: what a competent small quant team would build today

### 5a. What to trade, and why an edge can exist there for a small book

Constraints: small capital (one real crypto account, prop accounts of $5k–$10k nominal, paper elsewhere), retail-level fees (≈ 11 bps measured taker on Bybit per the 10-29 audit), no colocation, plan-limited compute, and an operator who wants absolute net P&L.

A small book cannot win on speed or microstructure. It *can* harvest premia that large players leave because of capacity limits, mandates or balance-sheet cost, and it can hold through drawdowns that institutions cannot. The candidates, in order of evidence:

1. **Perp funding / basis carry, delta-neutral** (spot long + perp short when funding is positive, rotated across the top-N coins by funding). *Payer:* leveraged longs pay for leverage; the premium exists because arbitrage capital is balance-sheet constrained. ACAD: Schmeling, Schrimpf & Todorov, "Crypto Carry" (BIS WP 1087, 2023); He, Manela, Ross & von Wachter, "Fundamentals of Perpetual Futures" (2022). Risks: carry compression, exchange/counterparty risk, liquidation of the short leg in squeezes. **The harness exists (`scripts/backtest_funding_carry.py`) and has never produced a measured result.**
2. **Time-series momentum with volatility targeting** across a *diversified* set (crypto majors plus equity-index, rates, metals and energy micros that IB/Alpaca already reach). *Payer:* slow-moving capital and under-reaction; a 100+ year record across asset classes. ACAD: Moskowitz, Ooi & Pedersen 2012 (*JFE*); Hurst, Ooi & Pedersen 2017 (*JPM*, "A Century of Evidence on Trend-Following"). Crypto-specific: Liu & Tsyvinski 2021 (*RFS*, "Risks and Returns of Cryptocurrency"). The existing `trend_donchian` family is a rough single-asset version of this. It is the one family with a plausible payer, so it should be rebuilt as a vol-targeted *portfolio*, not dozens of per-symbol legs with tuned exits.
3. **Cross-sectional crypto momentum and size/carry factors.** ACAD: Liu, Tsyvinski & Wu 2022 (*J. Finance*, "Common Risk Factors in Cryptocurrency"). Weekly rebalance, so costs are manageable. The harness exists (`backtest_xsec_momentum.py`), with 1 wiring-only run.
4. **Event / macro: keep it small.** The macro family is the only one the repo tested with a proper t-bar, and it went 84 fail / 13 pass. Drop it as an alpha source unless a specific mechanism comes up.
5. **Prop accounts: treat as an option-pricing problem.** A prop challenge is a call option on a funded account with a knock-out at the DD limit. The EV depends on the firm's rules more than on the strategy (`comms/prop_survival/` already models it). **Only a strategy that is already positive EV elsewhere belongs there.** Today none is (10-29 audit #1: `p_breach 0.934` passed the gate). Pause new prop spend until a carry or trend portfolio clears § 5b.

**What not to trade:** discretionary-pattern intraday scalps (ICT, VWAP, FVG) on crypto at retail fees. The repo's own 318-trade real-money VWAP record (PF 0.49) and the academic data-snooping literature agree.

### 5b. The research method

1. **Hypothesis register first.** Each idea states its mechanism (who pays, and why it persists), its expected sign and magnitude, and a *small* pre-declared parameter set (≤ 10 configs). No mechanism, no unit.
2. **One data snapshot and a locked holdout.** Discovery runs to 2024-06-30. Holdout runs 2024-07-01 → today, and is **read once per hypothesis, by a script that refuses a second read** (it logs who read it and when). This is the missing instrument behind C2.
3. **Every trial is counted, automatically.** `trial_ledger.py` already exists. Make it the gate rather than a report: a candidate advances only at **DSR > 0.95 on discovery, with N = all trials in its family**, then a holdout net Sharpe > 0 with the same sign (PRAC/ACAD: Bailey & López de Prado 2014, "The Deflated Sharpe Ratio"; Harvey, Liu & Zhu 2016, *RFS*, "…and the Cross-Section of Expected Returns"; McLean & Pontiff 2016, *J. Finance*, on decay after publication). *(This turns a `report_only` instrument into a promotion bar, a change to gates that needs the operator's permission. It is proposed, not applied.)*
4. **Evaluate at the portfolio level, net of measured costs:** broker-settled funding series, measured fees and slippage, and $ and % return. R only as a per-trade diagnostic.
5. **Kill means kill.** A hypothesis that fails its holdout is closed. Refinement is allowed only when it comes with a new mechanism, and it counts as a new trial.
6. **Live is for mechanics and cost only** (this part of the current ladder is right). Size is set by the portfolio's vol target, not leg by leg.

### 5c. ML architecture (fits the 2026-11-01 direction)

- **M1, entry / allocation model (build first).** Pooled across symbols. Features are point-in-time market state: returns over several horizons, realised vol, funding, OI, basis, cross-sectional ranks and calendar. The label is the cost-adjusted forward return over a fixed horizon (or triple-barrier). It outputs a score per (symbol, time). The decision is to go long the top-k / short the bottom-k, or to gate the factor portfolios from § 5a. The baseline to beat is 12-1 momentum, vol-targeted trend and funding carry on the same universe.
- **M2, brackets** (only after M1 clears): quantile regression of MFE/MAE over the hold horizon, which sets SL/TP as a predicted distribution. This satisfies the TP doctrine with a real prediction.
- **M3, manage** (only after M2): a hazard model of remaining return per bar of an open position, scored against a matched random-intervention control (already designed as B4 in the ML programme).
- **No sizing model.** Sizing is the portfolio vol target.
- **One bench, one ledger.** Purged/embargoed CV and the § 5b holdout. Every model × feature × horizon is a trial in the ledger.

### 5d. Minimum process and infrastructure

- **Rules:** one page. Money-path safety (no third gate, the daily DD switch, no halting), the research protocol of § 5b, and honesty about merged / deployed / observed.
- **Guards:** keep the ones that protect money (order path, account mode, roster equality, cost-model single owner, doc index). Target about 15–20, down from 120. Each is kept only if it has fired on a real defect in the last 90 days.
- **One scoreboard**, read first in every review and brief: net $ and % per book (week / month / inception), live-vs-backtest per leg, trials run, survivors after the haircut, and measured cost per trade.
- **Agents:** one manager plus 2–3 research lanes, each owning a *hypothesis*, not a register. Reviews are monthly, with P&L first.

---

## 6. KEEP / STOP / START

**KEEP (it works, with numbers where they exist)**
- Execution and journal plumbing on Bybit and Alpaca: 514 real closes recorded, with provenance classes (`src/runtime/provenance.py`), the public performance API and the journal paging API (every number in § 1 came from them in under 10 minutes).
- `scripts/research/trial_ledger.py`: the single most useful research artifact in the repo. It is the instrument that told the truth.
- The cost module (`execution_costs.py` and the resolver work), the funding/OI pulls (`scripts/ops/fetch_bybit_funding.py`, `ml/datasets/adapters/bybit_funding_oi.py`) and the backtest corpus fetchers.
- The ladder's principle that edge is decided offline and live is for mechanics only.
- The daily DD switch; no-halting; the two execution gates.
- The unused economic-family harnesses: `backtest_funding_carry.py`, `backtest_tsmom.py`, `backtest_xsec_momentum.py`, `backtest_vol_target.py`.

**STOP**
- Generated lever-transfer and "runway fill" units (`queue_replenish`-style authoring to meet a floor) and the 15 volume-based research SLOs, including the "authoring lane when supply breaches" rule.
- Real money on legs that fail the haircut. All 6 production legs score DSR ≤ 0.39 (**Tier-3, the operator decides**; the proposal is to move them to the demo floor per operating plan § 2 "Three strategy statuses", which the existing ladder already allows).
- New guards, registers and process docs. Desk/LTR judgement work on legs with no measured edge. Regime classifiers scored on log-loss.
- New prop challenge spend until a strategy clears § 5b.
- Intraday ICT/VWAP/FVG scalps as candidates for real money.

**START**
- The scoreboard (§ 5d) as section 1 of the daily brief and every review.
- The locked holdout plus the trial-ledger gate (§ 5b).
- Three hypothesis tests with a payer: funding carry, vol-targeted TSMOM portfolio, cross-sectional momentum.
- The M1 pooled entry model, benched against those three.
- Measured costs: broker-sourced fee and funding on every real trade (485 of 488 are estimates today).

---

## 7. Plan with checkpoints

### Two weeks (to 2026-11-15)

| day | deliverable | measurable checkpoint |
|---|---|---|
| 1–3 | **Scoreboard** (one script, one API route, brief section 1) | brief shows net $/% per book and trials vs survivors; numbers match § 1 within rounding |
| 1–3 | **Holdout lock**: discovery ≤ 2024-06-30, holdout read-once script | a second read of any holdout is refused and logged (self-test) |
| 2–5 | **Fix `backtest_funding_carry.py`** (2 `producer_failed`) and run it on the top 10 perps by OI, on settled funding, measured fees | a measured result with net annualised return, Sharpe, worst month and turnover, on discovery |
| 3–7 | **TSMOM vol-targeted portfolio** on 20 crypto perps plus available micros | portfolio-level net Sharpe on discovery, with trial count ≤ 10 |
| 5–10 | **Cross-sectional crypto momentum**, weekly | same reporting |
| 7–10 | **Trial ledger as gate (proposed)**: DSR with N = family trials | the ledger grades the three new hypotheses, and its counts include them |
| 10–14 | **Process cut list** drafted (guards with no fire in 90 d, SLOs, generated authoring) | a list with fire counts per guard, for the operator to approve |
| **14** | **Checkpoint A** | the 3 hypotheses each have a discovery verdict under § 5b; the operator decides on the 6 production legs with their DSR in hand; real-money cost rows from day 15 are broker-sourced |

### Six weeks (to 2026-12-13)

| week | deliverable | checkpoint |
|---|---|---|
| 3 | Holdout read, once, for any hypothesis with discovery DSR > 0.95 | pass/fail recorded; a fail is closed |
| 3–4 | M1 pooled entry model v1 on the same bench | beats the best of {TSMOM, xsec, carry} net of cost on discovery, or is closed |
| 4–5 | A survivor goes to Stage 1 (mechanics: 1–2 clean trades per the soak rule) | clean trades observed |
| 5–6 | A survivor goes to Stage 2 at vol-targeted small size, if the operator approves (Tier-3) | live cost per trade within 20% of modelled |
| **6** | **Checkpoint B** | the real-money book holds only strategies that passed § 5b; the scoreboard shows inception-to-date by book; process surface measurably reduced (guards, rows, commits to registers : src below 2 : 1) |

**What failure looks like, stated up front.** If none of the three economic families clears the holdout, **the honest conclusion is that this book should not trade directionally at retail cost**, and the right move is to stop paying for live real-money trading rather than search harder. That outcome is possible, and a plan that cannot reach it is the C2 failure again.

---

## 8. Proposed rows and units (NOT filed; the operator picks at planning)

| proposed id | kind | tier | what | closes when |
|---|---|---|---|---|
| `SCOREBOARD-PNL-FIRST` | row | 1 | net $/% per book, trials vs survivors, measured cost/trade; brief § 1 and review opener | brief shows it and matches § 1 |
| `HOLDOUT-LOCK` | row | 1 | discovery/holdout split; read-once script with log | self-test refuses a second read |
| `TRIAL-LEDGER-AS-GATE` | row | 3 (gate change: operator permission) | DSR > 0.95 with family N, plus holdout sign, as the Stage-0 bar | operator decision recorded |
| `FUNDING-CARRY-HARNESS-FIX` | row + unit | 1 | fix the `producer_failed` harness; settled funding; measured fees | measured discovery result |
| `RQ-TSMOM-PORTFOLIO-DISCOVERY` | unit | 1 | vol-targeted TSMOM portfolio, ≤ 10 configs, pre-registered | graded on discovery |
| `RQ-XSEC-MOM-DISCOVERY` | unit | 1 | weekly cross-sectional momentum | graded on discovery |
| `PROD-LEGS-DSR-DECISION` | row | 3 | move the 6 production legs (DSR ≤ 0.39) to the demo floor | operator yes/no recorded |
| `RESEARCH-SLO-YIELD` | row | 1 (removing volume SLOs reduces process, but the operator approved those SLOs, so ask) | replace the 15 volume SLOs with 2: survivors per month, and trials per survivor | YAML changed with the operator's OK |
| `STOP-GENERATED-AUTHORING` | row | 1 (operator OK, since it reverses a binding rule) | stop floor-driven generated units and lever transfers | dispatcher fires only hypothesis-register units |
| `GUARD-PRUNE` | row | 1 | list every guard with fires in 90 d; propose deletions | operator-approved list applied |
| `COST-BROKER-SOURCED` | row | 2 | broker-sourced fee and funding per real trade | ≥ 95% of new real rows `cost_source = broker` |
| `ML-M1-POOLED-ENTRY` | row (coordinate with ML-DECISION-MODELS) | 1 | pooled market-label entry model, benched vs the 3 factor portfolios, every trial in the ledger | beats the best baseline on discovery, or is closed |
| `PROP-SPEND-PAUSE` | row | 3 | no new challenge purchases until a strategy clears § 5b | operator decision recorded |
| `ML-BAR-ONE-READ` | row | 3 (operator preference) | keep the 2026-11-01 "point estimate ≥ 0" bar, but on ONE pre-registered model per question, holdout read once, trial count reported beside it; optional CI bound is the operator's call | operator decision recorded on `ML-DECISION-MODELS` |
| `GRADE-EVERYTHING-CONTINUOUSLY` | row | 1 (schedules) / 3 (grade → action) | schedule the 9 never-run graders that still matter (first `desk_am_judgement_grade`, `exit_head_final_fold_grade`); add a served-prediction decision-value grader for every shadow/advisory model; make each grade name the action it drives (demote, promote, retire) | every model, decision class and forecast has a scheduled grader with output newer than 7 days, checked by the scoreboard |
| `LTR-CLOSE-CLASS-TEST` | unit | 1 | pre-registered disjoint-window test of the LTR `close` recommendation class (18 priced, +15.15R counterfactual) | graded on a window it was not found on |
| `PROMPTS-PNL-FIRST` | row | 1 | manager, review and audit skills open with the scoreboard and the question "would a sceptical quant believe this leg has edge?"; remove call-hit self-grading as a headline | skills edited; next review opens with P&L |

---

## 9. Limits of this audit (what I did not establish)

- **Prop P&L** is measured as equity vs `account_size_usd`. Challenge fees paid are not included, so the true prop result is worse.
- **Paper $** is at paper notional and is not comparable across accounts. Only PF and win rate are used for paper.
- **The baseline-cell z-scores** (§ 1c) assume a per-trade SD of 1.0–1.5R. The harness records do not store the SD.
- **Entry-side ML vetoes** (regime gating of intents) were not measured against order outcomes. Only close reasons were checked for model-driven actions.
- **The 10-29 audit's cost-stack row counts** (C3) were cited, not re-measured.
- **The ACAD/PRAC citations are from the lane's knowledge and were not re-fetched this session.** Each is a well-known published paper. Check a specific figure before quoting it.
- **The `ML-DECISION-MODELS` diagnosis had not landed.** § 4 critiques the direction as dispatched, not that lane's document.

## 10. Reproduction

```bash
# real-money / paper / mirror aggregates (public route, no token)
curl -sS https://ict-bot.duckdns.org/api/bot/performance?window=all
# the full trades journal, paged (needs DIAG_READ_TOKEN)
for o in 0 1000 2000 3000 4000 5000 6000; do
  scripts/ops/diag_fetch.sh "journal?table=trades&limit=1000&offset=$o&envelope=true"; done
# prop
curl -sS "https://ict-bot.duckdns.org/api/bot/prop/fills?limit=500"; curl -sS https://ict-bot.duckdns.org/api/bot/prop/overview
# ML registry
curl -sS https://ict-bot.duckdns.org/api/bot/ml/registry
# trial ledger (in repo)
python3 -c "import json;print(json.load(open('comms/research/RQ-20261016-6013-01/41103441836/trial_ledger.json'))['summary'])"
# research verdicts: parse research/queue/RQ-*.yaml grading.verdict, grouped by theme
# effort: git log origin/main --since=2026-10-01 --format=%h -- <path> | wc -l   (needs a fetch deeper than the default 50 commits)
```
