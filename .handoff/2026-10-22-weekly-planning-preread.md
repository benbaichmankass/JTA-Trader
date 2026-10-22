# Weekly planning pre-read 2026-10-22 — review walk-through + week plan

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Pre-read for the Thursday 2026-10-22 walk-through and weekly planning. It is Tier 1 and read-only: no config, src or queue
> change. Repo state read: branch `mgr/weekly-planning-1022` from `main` `9df24ab26` (the manager added `ba8039227`, usage readings only, during this lane), scripts re-run 2026-10-22 ~06:20Z.
> **Labels used:** *MEASURED (re-run today)* = a script I ran this session. *Cited* = a number from a named review doc that I did
> not re-derive. *Manager-verified* = an overnight fact the manager established and handed to this lane. *(reading)* = my
> interpretation, not a measurement. Merged ≠ deployed ≠ observed is stated per item.

## Overnight facts (manager-verified, stated as given)

| item | merged | deployed | observed |
|---|---|---|---|
| Global position cap retired (#19375) | yes | yes | — |
| ADA position closed on bybit_2 / bybit_portfolio / bybit_1 (operator decision) | n/a | n/a | closed. `ada_pullback_2h` **stays on all three rosters** in `config/accounts.yaml` (MEASURED today); only the position was closed |
| breakout_2 `risk_pct` 0.005 → 0.0035 | yes | yes | **not yet observed** on a ticket |
| `PROMOREADY_OOS_EDGE=on` | yes (#19402) | yes | **observed**: 04:00Z sweep succeeded with no OOM. Heads blocked on oos_edge went from 21/24 to 4/23, and the 4 left are baselines. 0 promote / 0 demote |
| Drift-scan fix (#19376) | yes | — | observation is pending on the next scan |
| Exits lane: TP-lever crash fix #19423, level-trail lever + Q11 script #19431, chain verdicts #19427, 10 new exit units #19425 / #19442 | yes (all five commits are on `main`, checked by subject) | n/a (research tooling) | units not yet graded |

---

## (a) Performance

**Source:** `docs/reviews/2026-10-21-weekly-walkthrough.md` § PERFORMANCE (row `PERF-REVIEW-PREP-20261021`, `landed_unproven`).
It was observed on the live read-only API around 17:00Z on 2026-10-21. All figures below are *cited*, except the TP-doctrine
counts, which I re-ran. That brief pools mirror R with paper R, because the journal files the mirrors as `paper`. R is ESTIMATED,
and peak R is a lower bound on MFE, so the true giveback is at least what is shown.

### Net R per capital-day (R/cap-day = Σ realised R ÷ Σ hold-days, over R-graded closes only)

| window | class | R-graded n / closes | R/cap-day | read |
|---|---|--:|--:|---|
| W30 (closed ≥ 09-21) | real_money (`bybit_2` + `alpaca_live`) | 5 / 23 | −0.073 | insufficient_n |
| W30 | paper+mirror | 131 / 405 | +0.061 | — |
| W7 (closed ≥ 10-14) | real_money | 2 / 3 | −0.386 | insufficient_n |
| W7 | paper+mirror | 15 / 52 | +0.029 | — |
| 90-day | real_money | 11 / — | +0.010 | insufficient_n |
| 90-day | paper+mirror | 328 / — | +0.094 | — |

- Telemetry R covers only 32% of the W30 paper+mirror closes (131 of 405). So R describes the joined minority of trades.
- Paper $ is not a decision number. A single mis-valued leg, `ict_scalp_mgc_15m` on `ib_paper`, carries 56% of the W30 paper+mirror
  net loss. Both of its large losses are ESTIMATED, and it also has 7 closes stored with PnL `0` that is `unverified`.
  Filed: `PI-20261021-4ZLRFEV1-0002`.
- **Live vs backtest** (whole history per book, real-money rows): `bybit_2` `xrp_pullback_2h` n=17, −9.92R, 2.2nd percentile of
  its backtest band, and `ada_pullback_2h` n=15, −6.91R, 3.3rd percentile — both **BELOW_BACKTEST**, filed as a fidelity/regime
  investigation (`PI-20261021-4ZLRFEV1-0001`), not a demotion. `trend_donchian_eth_4h` n=14, +8.36R, CONSISTENT.

### Giveback (giveback = peak R − realised R; share = Σ giveback ÷ Σ peak)

| class | window | R-graded n | mean giveback R | share of peak | peak ≥ 1R, then closed ≤ 0 |
|---|---|--:|--:|--:|--:|
| paper+mirror | W30 | 131 | 0.99 | 85.5% | 15.3% of 59 |
| paper+mirror | 90-day | 328 | 0.99 | 87.3% | 14.1% of 149 |
| real_money | W30 | 5 | 1.02 | 120.8% | 1 of 2 |
| real_money | 90-day | 11 | 0.96 | 97.9% | 1 of 3 |

(reading) On the paper+mirror book (90-day, n=328), trades keep about 13% of their peak R. The share is flat week over week, so the
giveback looks structural to the exit path rather than the result of one bad week.

### TP-doctrine compliance — MEASURED (re-run today)

I ran `python3 scripts/ci/check_tp_doctrine.py` on 2026-10-22 at `9df24ab26`; it exited with rc=0 (ratchet). It covers 54 routings
across 26 distinct legs in every account in `config/accounts.yaml`. This reads the merged repo config, not the live VM.

| class | routings | entry_tp FAIL | tp_revision FAIL | compliant |
|---|--:|--:|--:|--:|
| real_money | 8 | 5 | 7 | 0 |
| prop | 6 | 6 | 6 | 0 |
| mirror | 7 | 4 | 6 | 0 |
| paper | 33 | 21 | 32 | 0 |
| **all (sum)** | **54** | **36** | **51** | **0** |

- TP-REACH-FLOOR (10%), over the 28 routings that declare a target: below the floor 10, reachable 9, unmeasured 9.
- The counts are identical to the 2026-10-21 run. **0 of 54 routings are compliant.**

### Grades

- **Not done this week:** per-decision A–F grading, the M13 insights cross-check and the prop `trade_quality_review.py`. The 10-21
  brief deliberately covered numbers only (its §5).
- Every per-leg real-money row in W30 has R-n ≤ 1, so `insufficient_n`.
- One paper+mirror leg reaches R-n ≥ 10: `ict_scalp_avax_5m`. It has n=19, +5.94 R/cap-day and a 64% giveback share. It is paper
  only, and the point is to understand it, not to promote it.

## (b) ML + frontier

**Sources:** the 10-21 walk-through §§1–5 (*cited*), plus `ml_plan_status.py --diversity`, which I re-ran today (*MEASURED*).

**Registry.** 97 registered models: 3 advisory, 21 shadow, 72 candidate, 1 research_only.
**Trainer.** The 10-21 cycle finished `rc=0`. Datasets were 120 ok / 0 failed over 24 h.

**Readiness.** `PROMOREADY_OOS_EDGE` is now on and observed (see the overnight table). The 10-22 sweep proposed 0 promote / 0 demote.
(reading) With oos_edge now measured, "hold" is a real verdict for 19 of 23 heads, no longer a missing-data default.

**Diversity (MEASURED today).**
- gbdt is **76 of 97** registered models (78%). That is reported as `MANIFEST-CONCENTRATION`, not as a failure, and is unchanged since 10-21.
- Plan items: 76, of which 54 are open and 6 flagged.
- The 6 flags are `CLOSED-OPEN`: ML-F3P, F19, F20, F21, F26 and ML-V3. Each is a row still marked open whose unit or row is done; this is book-keeping owed.
- 3 open items carry no family tag: ML-N1, ML-V1 and ML-D3.

**Non-gbdt families.** Every non-gbdt family is still at INDETERMINATE or FAIL. None has produced a decisive positive.
- `linear_logit` FAIL: ff8f-03, 1h, n 72,000 OOS.
- `conformal` FAIL: 65ff-25 config only.
- TabICL ≈ LightGBM: ff8f-02. The TabPFN arm errored because the CPU path refuses more than 5,000 samples.

**Blockers raised by the ML lane.**
- `FRONTIER-LEVER-TSFM` is now rank 2 in the checklist queue. `FRONTIER-LEVER-SEQUENCE-LEARNER` has gated units 9da8-01 and ff8f-04
  across ≥ 2 scans.
- There is a Tier-2 ask for the TabPFN CPU-large-dataset env on the trainer.

**Frontier candidates** (proposed, not queued): `Timestral-209M` as a TSFM arm for 9da8-01 (licence not read); TabICLv2 (check
whether the trainer's `tabicl 2.2.0` is v2); TabPFN-3 (one secondary source only).

**Still overdue:** the MES advisory margin re-date. It was 4.26 pts on 10-21 (n_eval 9,353), which sits between the refine and
clear thresholds.

## (c) Week + roadmap review — `python3 scripts/ops/roadmap_map.py --report` (MEASURED today)

Population: the 29 milestones across goals G1–G7.

**Clean:** orphan live rows, orphan open queue units and dangling refs are all 0.

**Overdue: 15 of 29** milestones read `reviewed` **OVERDUE**, every one last reviewed 2026-10-11 — G1 5 (L-LADDER, M18, M24,
M16, M15) · G2 1 (L-PROP) · G3 1 (M39) · G4 5 (M25, M26, M14, M9, M41) · G5 2 (M40, L-OPS) · G6 1 (M36).

(reading) The weekly roadmap pass did not run in the week of 10-12 or 10-19.

**Largest open-unit loads:** L-ATM 50, L-LADDER 43, M28 29, L-REGIME 18. **Largest live-row loads:** L-OPS 80, L-LADDER 63,
L-PROP 54. (reading) The work is concentrated in process and ladder rows rather than in edge.

**Programme review 2026-10-21** (`docs/research/programmes/01-ACTIVE-TRADE-MANAGEMENT.md` and siblings; PR #19344, *held*):
- Programme 01 graded 122 units in the window (23 pass, 95 fail, 2 indeterminate, 2 ungraded). Lesson: the levers that confirm are
  momentum/stall-keyed trails and TP pull-ins, not fixed brackets.
- The exits lane's overnight notes on that file are newer and take precedence: the ADX declares are no longer build-gated
  (`momentum_levers.py`, #18921 merged 10-18; deployment not checked); the eth_4h ADX trail is superseded; slv_1d momentum-stale is
  parameter-fragile; 10 Q9 PASS discoveries have no confirmation unit (`PI-20261021-IGHT1021-0001`).

**Weekly audit 2026-10-19** (*cited*):
- 9 invariants: 8 pass, 0 fail, 1 not measured; the prop accounts are invisible to the suite (F2).
- 253 due pipeline items (the same set read 63 on 10-14); 72 of 188 `landed_unproven` rows past `due_by`; 23 unrouted, oldest 24 d.
- Deep-pass verdict: the follow-through system has no single liveness mechanism (D1). The decision asked of the operator is recorded
  on row `AUD-20261019-DESIGN-WORK-LIVENESS`.

## (d) Pending Tier-3 decisions held for the operator

| # | decision | evidence (verified this session unless marked) | recommended answer (reading) |
|---|---|---|---|
| 1 | **#19403: move `ief_pullback_1d` to paper** (off `alpaca_live` + `alpaca_portfolio`) | See the notes below the table | **Yes, conditionally.** First confirm whether trade 4195 is still open: the change should not leave a mirror-only position unaccounted. |
| 2 | **`trend_donchian_xrp_4h` trail_adx_below 25 / tight 2.5** on bybit_2 + bybit_portfolio + bybit_1 | See the notes below the table | **Yes.** This is a pre-registered confirm rule that the candidate passed on all 4 folds, it reduces drawdown, and it adds no TP mover. Ship it under the data-backed Tier-3 authorization. |
| 3 | **TP declare `PI-20261018-ACAKSTAR-0001`**: alpaca 1d pullback family `tp_r` 3.5, replacing the 50 R sentinel | Checklist `TP-DECLARE-ALPACA-PB1D` (queue rank 4). RQ-20261016-014 is INDETERMINATE over the whole family history (n 326, n_oos 133). K*=3.5R reaches 27.8% of OOS trades. The OOS delta vs the sentinel is +0.003 R/trade, CI [−0.061, +0.069]. No longer window exists, so the item calls this a **preference**, not a data gap. | **Yes.** It gives a calibrated, reachable TP at a cost of at most ~0.06 R/trade, and the doctrine forbids the sentinel. |
| 4 | **TP declare `PI-20261018-ROPKSTAR-0001`**: `trend_donchian_eth_prop` `tp_r` 2.5, replacing 6R | RQ-20261016-007 is INDETERMINATE (n 870, OOS 348). K*=2.5R reaches 13.5% of OOS trades. OOS delta −0.028 R/trade, CI [−0.066, +0.006]. A YES still routes through the prop-cost ablation and the per-firm prop_ev_grid (checklist `TP-ETHPROP-2P5`, rank 5). | **Yes to pursue; no to declaring now.** Run the prop ablation first, because prop legs clear a superset of the ladder. |
| 5 | **bybit_1 margin** | **Source not found.** No checklist row or pipeline item since 10-19 names a bybit_1 margin issue (searched `margin` × `bybit_1`). | Ask the manager for the record before this is put to the operator. |
| 6 | **`PI-20261018-WCDIDFTE-0002`: `eth_prop` Stage-2 standing** | Under closed bars the leg passes RULE-D1 (+9.32R, n=163). Under decision_bar=forming, which is what the live builder trades, it **fails**: −9.45R, n=250, same window, Binance 1m proxy at the Bybit cost stack. The pre-registered holdout did not select closed. This is the same decision shape as xrp_pullback_2h (`PI-20260929-VOLSKIP-SIGNAL-0003`), and `DECISION-BAR-MATCH` (rank 3, Tier 3) owns it. | Do not count a closed-bar record as evidence for a leg that trades the forming bar. Fold this into DECISION-BAR-MATCH as one clause covering both legs. (reading) The leg runs on prop money today. |

**Notes on #1 (#19403, `ief_pullback_1d` to paper):**
- #19403 is **not on `main`**: no commit subject names it. `ief_pullback_1d` is on both `alpaca_live` and `alpaca_portfolio` today (MEASURED).
- `PI-20261022-R3DFW7IK-0002` calls ief a "retention case already with the manager/operator".
- The IEF live-vs-backtest reading is INSUFFICIENT_N (n=1, −0.48R; cited).
- **Open IEF position question:** trade **4195** is an `alpaca_portfolio` IEF **short** (152 units). It was excluded from the
  Gate-2 mirror window by the 2026-10-05 decision "Let them run, exclude" (row `MIRROR-LEGACY-SHORTS`).
- I did **not** establish whether 4195 is still open.
- Moving ief off `alpaca_portfolio` changes what happens to that excluded legacy short.

**Notes on #2 (xrp_4h ADX trail):**
- Source: `research/results/RQ-20261016-015/39103752013.jsonl`, rule `RULE-P1-Q4-XRP4H-EXIT-CONFIRM` (registered 10-16). Read in full;
  verdict `pass`.
- Population: n=68 trades, XRPUSDT 4h, 2020-07-01..2026-10-15, net of fees, slippage and funding.
- Arm M2 (`--trail-adx-below 25 --trail-adx-tight-mult 2.5`) against incumbent A:

| | net R | max DD R | fold net R |
|---|--:|--:|---|
| M2 | **17.07** | 4.15 | 8.45 / −0.67 / 0.59 / 8.71 |
| A (incumbent) | 14.30 | 4.57 | 7.75 / −1.20 / 0.16 / 7.60 |

- M2 matches or beats the incumbent in 4 of 4 folds.
- Caveats: feed is **Binance**, not Bybit; harness runs `--side-filter short`; `reach_ge_6r` is 0.0, so this does **not** fix TP
  compliance; `data_fingerprint` is `not_established`.

---

## (e) Candidate priorities for the week — OPEN QUESTIONS, not decisions

**E1. The ranked checklist queue** (`checklist.py queue`, MEASURED today; 167 rows listed, 8 ranked).

| rank | row | tier |
|--:|---|--:|
| 2 | FRONTIER-LEVER-TSFM | 1 |
| 3 | DECISION-BAR-MATCH | 3 |
| 4 | FRONTIER-LEVER-TABULAR | 1 |
| 4 | TP-DECLARE-ALPACA-PB1D | 3 |
| 5 | FRONTIER-LEVER-HARNESS-COSTS | 1 |
| 5 | TP-ETHPROP-2P5 | 3 |
| 6 | FRONTIER-LEVER-LEADLAG | 1 |
| 7 | PROP-GATE-ADA-XRP | 1 |

- **Rank 1 is empty**, and ranks 4 and 5 are each shared by two rows.
- *Q:* should the ranks be re-cut so the exits/giveback work and DECISION-BAR-MATCH sit above the frontier levers?

**E2. Exits / giveback (standing priority).**
- Giveback share is 85–87% on paper+mirror (n=131 W30, n=328 90-day).
- Q8's in-trade exit model is the stated destination. Q10 (level-trail) units are registered; Q11 (path-metric giveback) is unblocked.
- *Q:* is this week's exit goal (a) to ship the confirmed declares (xrp_4h ADX), (b) to write confirmation units for the 10 Q9 PASS
  discoveries, or (c) to build the replace-on-holdout grade? These three compete for the same lane.

**E3. ML starved themes.**
- The research SLO `theme_share_min_ratio` is 0.31 against a floor of 0.5.
- `PI-20261022-R3DFW7IK-0002` says `ml_health` and `infra` hold **0 runnable units**.
- *Q:* author ml_health/infra units this week, or accept the gap while TSFM and the sequence-learner levers are built?

**E4. Prop gate parity.**
- `PROP-GATE-ADA-XRP` is queued at rank 7. It notes that the gate has never been run for `ada_pullback_2h`, `xrp_pullback_2h` and
  `trend_donchian_xrp_4h`, and that the grandfathered eth/sol_prop records carry high p_breach that nobody has read.
- `PROP-GATE-PARITY` is `landed_unproven`: `trend_donchian_sol_prop` fails the per-leg gate on tradeify_1 and velotrade_1; the
  grandfather clause lapses 2026-11-07 (eth) / 2026-12-11 (sol); the gate does not check ruleset against the adding account.
- *Q:* move it up, now that the breakout_2 risk cut and the eth_prop decision above both touch prop?

**E5. Research SLO breaches.** `scripts/research/research_slo.py`, MEASURED 2026-10-22 06:19Z: **6 not ok of 16**.

| SLO | value | target |
|---|--:|--:|
| runnable_floor | 30 | ≥ 46 |
| authoring_supply_ratio_7d | 0.87 | ≥ 1 |
| theme_share_min_ratio | 0.31 | ≥ 0.5 |
| blocked_over_age | 11 | ≤ 10 |
| research_ops_not_run | 4 | ≤ 2 |
| hold_pr_wait_h | could not look | — |

- Throughput is healthy: fires_24h 57, lands_24h 59, grade latency p50 0 d and p90 2 d.
- Step E.0 drafted 0 of 23 ready nodes, because the head of the authoring queue needs instruments.
- *Q:* is the authoring deficit a lever-build problem (my reading) and not an authoring-lane problem? If so, a build lane is the
  disposition.

**E6. Stale in-flight rows.** `updated_at` read today; all are ≥ 4 days untouched.

| row | state | last update |
|---|---|---|
| PERF-FOLLOWUP-2026W41 | in_flight | 10-15 |
| PERF-FOLLOWUP-2026W42 | in_flight | 10-15; PRs #18175/#18176 |
| WEEKLY-PLANNING | in_flight | 10-15; observation due 10-14 |
| RESEARCH-CONFIRM-FRESH-WINDOW | in_flight | 10-16 |
| MANAGER-PACING-STRUCTURAL | in_flight | 10-18 |
| TIER3-PACKETS-1018 | in_flight | 10-18; `prs: []` |

- TIER3-PACKETS-1018 has no PR for RQ-20261018-002 (ada VH95) or -007 (eth_4h MM05 TP).
- *Q:* close, re-dispatch or kill each one, with a stated terminal reason?

**E7. Stale automation PRs and an unlanded results batch.**
- Per the manager, automation PRs #19030–#19189 and #19358 are stale, and results batch #18963's files are not on `main`.
- I confirmed that neither #18963 nor #19358 appears in any commit subject on `main`. I did **not** enumerate the PR range.
- *Q:* rebase-and-land #18963 (results that nobody can grade otherwise), close the rest?

## Gaps in this pre-read (said plainly)

- No live API pull this session: the performance numbers are the 10-21 ~17:00Z observation, not today's.
- Not established: bybit_1 margin (no source found); trade 4195 open/closed; the #19030–#19189 PR range; per-decision grades.
- `research_slo.py` printed `alert: change delivered: None file: None`. It wrote no health file in this tree, and `git status` was
  clean before I wrote this doc.
