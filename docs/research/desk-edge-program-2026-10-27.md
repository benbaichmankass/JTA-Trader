# DESK-EDGE-PROGRAM — a methodical program for finding a desk entry edge that beats the random-geometry baseline

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-EDGE-PROGRAM` (Tier 1, research), dispatched by Manager Session 2026-10-27a. Checklist row `docs/claude/work/checklist/DESK-EDGE-PROGRAM.json` (roadmap `L-DESK`).
Operator, chat 2026-10-27 ~16:00Z, verbatim: *"It's only about finding an edge that passes the baseline, and what we need to focus on is making sure that we're creating robust testing to understand what we need to do to get that edge, and not just making a few random guesses here and there, and then running like days of tests. ... there's no way that we can't get an edge out of this. We just need to figure out what we're doing wrong and then fix that, and we need to find a way to test that thoroughly so that we can optimize methodically."* Popups the same minute: method **"Diagnose-then-iterate harness (Recommended)"**; judged-2 (`RQ-20261027-e72b-01`) **"Pause it (Recommended)"**.

**This section (§ 3, the information-ceiling design and verdict rule) was committed before the ceiling was run.** Results are in § 4 and were appended after.

## 1. The question and the one statistic

The desk's entry generation passes Stage 0 only if its entries beat **a random entry with the same bracket, on the same symbol, in the same fold, net of the full cost stack**: S3 in `scripts/research/desk_gen_replay_driver.py` (`random_baseline`, `cluster_stats`; units `RQ-20261026-e535-03/-04`). Judged-1 (1,498 packets, 732 fills) scored **S3 = +0.006 R, CI [-0.19, +0.19]**; its S1 of +0.16 R was the short drift of the window (723 of 732 shorts) — `docs/research/desk-18c-edge-optimization-2026-10-27.md` (PR #20626). Every number in this program is S3 or a quantity that predicts S3. Nothing here re-implements S1/S2/S3: the harness imports the driver.

## 2. The method: diagnose, then iterate (the decision tree)

```
 (1) INFORMATION CEILING  token-free, run first                         scripts/research/desk_edge_ceiling.py
     Fit learners to pick entries from (P) packet contents only, (P+) packet + information the packet lacks.
     Walk-forward, S3 scoring, family-corrected CIs, planted + null controls.
          |
          +-- instrument invalid (controls fail) ...........  fix the harness; nothing below runs
          +-- P present, judge absent ......................  BOTTLENECK = JUDGE      -> (2)/(3) over judge levers
          +-- P absent, P+ present .........................  BOTTLENECK = PACKET     -> change the packet; the fitted
          |                                                                               model is itself a FREE candidate
          +-- P absent, P+ absent ..........................  no edge in reachable info -> acquire new information
          |                                                     (named in § 4) before ANY further judge spend
          +-- inconclusive .................................  more information per $: dense labels, not judge runs
 (2) LEVER GRID  ranked by expected information per dollar (§ 6)
 (3) CHEAP DEV LOOP  ~100 stratified packets, forced-rank elicitation, sequential kill, LOCKED HOLDOUT (§ 5)
 (4) FULL REGISTERED RUN  only for a variant that wins on the holdout; that run is the Stage-0 evidence record
```

Three windows, fixed now and never moved (registered in `scripts/research/desk_edge_devloop.py`):

| window | dates (cutoffs) | who may look |
|---|---|---|
| **DEV** | 2025-11-01 .. 2026-09-15 (judged-1's window) | the ceiling, every dev variant, any number of looks (all counted) |
| **HOLDOUT (locked)** | 2025-05-01 .. 2025-10-25 | only a variant promoted from dev under § 5.3, one look each; the packet builder refuses it otherwise |
| **FULL RUN** | 2023-11-01 .. 2025-04-30 | only a variant that PASSED the holdout, under its own registered unit |

`RQ-20261027-e72b-01` (judged-2, C1, paused) registered the window 2024-11-01 .. 2025-10-25, which overlaps HOLDOUT and FULL RUN. It has not run; **if it is resumed it must enter as a dev variant (C1) of this program**, not as a direct full run, or the holdout is spent on an unscreened candidate. That unit is on PR #20626 and is not edited here; the manager decides.

## 3. The information ceiling — design and PRE-REGISTERED verdict rule

**Question.** Can any fitted model, given what a scan packet contains, choose entries whose S3 is > 0 out of sample? If a model cannot, the judge cannot be expected to either (it sees the same packet) and the bottleneck is the packet. If a model can and the judge does not, the bottleneck is the judge.

**Population.** Every 2-hour bar close in the DEV window (3,816) plus every judged-1 cutoff (1,498, rebuilt byte-identically: packet id and sha asserted). At each cutoff, six symbols x {long, short} x 7 market-entry geometries: the driver's six `REFERENCE_GEOMETRIES` and `GJ` (stop 1.25 ATR, target 2.0 R, 48 bars; judged-1's median bracket: stop median 1.22 ATR, R:R median 2.0, horizon 48 in all 732). An action is kept when the driver's engine fills it.

**Label.** `y = net_r(action) - mean net_r of 2,000 random entries with the same geometry, same symbol, same side, same fold` (the driver's `transplant` and `random_baseline`). The mean of `y` over a selected set IS S3; a selected set is scored with the driver's `cluster_stats` (rows `{week, net_r, days, diff}`, weekly-cluster bootstrap).

**Feature tiers.**
- **P (packet only)** — what the judge saw: per-symbol atr %, `htf_trend`, swing distances (side-signed as room ahead / behind), session; the base-rate rows (mean, sd, p10, p50, p90 at h4/h12/h48 for the action's side, the opposite side's means, the cost); cross-sectional summaries of those (rank of the symbol's base rate among the six, number trending, relative atr); the action's side and geometry.
- **P+ (packet + missing information)** — P plus, all at or before the cutoff: returns over 1/4/12/24/72/168/336 bars in ATR (side-signed), range position over 24/168/720 bars, volatility percentile and ATR change, 24h volume z-score and taker-buy share over 1/4/24 bars (Binance Vision spot), BTC returns and the six-symbol cross-sectional ranks, hour and weekday, symbol identity, and perp funding (Binance Vision USD-M settlements, last and 3-day mean, side-signed). Each group is also added to P alone (ablation), so a P+ result names the information that carries it.

**Learners.** Ridge regression on `y`; logistic regression on `y > 0`; LightGBM regressor (300 trees, 15 leaves, min 400 per leaf). Fixed hyper-parameters, no tuning on test folds.

**Walk-forward.** The driver's four folds of the DEV window. Test fold k in {2, 3, 4}; train on folds < k with a 96-hour embargo before fold k's first cutoff (the longest horizon), so no training label overlaps a test cutoff.

**Selection policy (the desk-like one).** Per test cutoff, the best action per symbol, the top 2 symbols; act on the 34% of cutoffs with the highest best prediction (judged-1 acted on 506 of 1,498 packets = 34%). This ranks predictions only; no label is read.

**Statistics.** Policy S3 with the driver's 95% weekly-cluster CI, and a family-corrected CI at alpha 0.05 / 6 (3 learners x 2 tiers); weekly rank IC (Spearman of prediction vs `y` over every test action of a week; mean over weeks, bootstrap CI at the same corrected level); policy S3 per test fold.

**Verdict per tier (registered; constants in `desk_edge_ceiling.py`).**
- **present** — some learner has policy S3 > 0 with the corrected CI lower bound > 0, AND weekly IC with the corrected lower bound > 0, AND policy S3 > 0 in >= 2 of the 3 test folds.
- **absent** — every learner's corrected S3 upper bound is < **+0.10 R** (the smallest S3 this program treats as a useful edge: about half the round-trip cost the packets show, `br_h48_cost`).
- **inconclusive** — otherwise.

**Controls (the probe must find a positive before a negative counts — RULE ONE).** On P+ with ridge and GBDT: (a) **planted signal** — a column `y + N(0, (2 sd_y)^2)` appended; it must read `present`; (b) **shuffled labels** — training labels permuted within week; it must NOT read `present`. If either fails, the branch is `instrument_invalid` and no verdict is used.

**The judge on the same packets.** The judged-1 fills whose packets fall in test folds 2-4 (the DESK-18C per-proposal records, which are the driver's own score loop) are scored with the same `cluster_stats`, beside the models' picks restricted to the judged-1 cutoffs of those folds.

**Decision branch (registered).** `instrument_invalid` if a control fails; else `bottleneck_judge` if P is present and the judge's S3 CI lower bound is not > 0; `bottleneck_packet_information` if P is not present and P+ is; `information_and_judge_both_find_edge` if P is present and so is the judge; `no_edge_in_reachable_information` if P and P+ are both absent; `inconclusive` otherwise.

**What it cannot say.** It bounds what THESE learners extract with THESE features at THESE geometries; an `absent` is not a proof that no edge exists at other horizons, other entry types (limit/stop), or with data outside the list. It uses spot candles (the desk's venue is the Bybit perp), as the driver does.

## 4. The information-ceiling result

### 4.1 DEV window (the § 3 run) — registered verdict: **inconclusive / inconclusive, instrument valid**

Evidence record: `comms/research/desk_edge/ceiling-dev/ceiling.json` (`desk_edge_ceiling.py build` then `run`; candles Binance Vision spot 1h fetched 2026-10-27 through the driver's `fetch_market`, funding Binance Vision USD-M). **Population:** 4,535 packets (3,816 two-hourly + 1,498 judged-1 cutoffs, 779 shared; every judged-1 packet id reproduced), 380,940 filled actions (4,535 x 84: every action filled), 284,508 of them in test folds 2-4 = 35 ISO weeks. All numbers MEASURED there unless marked.

| | ridge | logit | GBDT |
|---|---|---|---|
| **P** policy S3 (95% CI) | +0.023 [-0.09, +0.15] | +0.028 [-0.07, +0.14] | -0.041 [-0.36, +0.33] |
| **P** weekly rank IC (corrected CI) | +0.104 [+0.02, +0.19] | +0.069 [-0.01, +0.15] | +0.052 [-0.06, +0.16] |
| **P+** policy S3 | -0.016 [-0.11, +0.08] | +0.012 [-0.07, +0.09] | +0.078 [-0.27, +0.53] |
| **P+** weekly rank IC | +0.094 [+0.01, +0.18] | +0.074 [-0.01, +0.15] | +0.079 [-0.01, +0.17] |
| policy picks / long share (P+) | 2,304 / 84% | 2,304 / 73% | 2,304 / 90% |

- **Labels check:** every test action, unselected: S3 -0.0005 [-0.030, +0.028] (n 284,508): `y` is centred, as it must be.
- **Controls:** planted signal `present` (S3 +1.60 ridge, +1.91 GBDT); shuffled labels `inconclusive` (S3 +0.011 / -0.011). **Instrument valid.**
- **Ablation (P plus ONE group; policy S3 ridge / GBDT):** returns +0.037 / +0.070 · range +0.037 / -0.026 · volatility +0.019 / +0.065 · volume & taker flow +0.034 / +0.024 · BTC cross-asset +0.043 / +0.028 · calendar +0.021 / +0.015 · symbol identity -0.029 / -0.016 · funding +0.025 / +0.042. No group moves S3 past +0.07; every interval spans zero.
- **The judge on the same packets** (judged-1 fills in folds 2-4, the driver's own score loop): S3 **+0.050 [-0.23, +0.30]**, n 513, 0.2% long. Models on those cutoffs: -0.08 to +0.08, n 762, 71-94% long. **The judge and the models choose opposite directions and neither beats a random entry.**
- **Why the rank IC is not evidence of a usable edge (post-hoc diagnosis, not a registered test).** Ridge on P has IC +0.10 but its mean `y` by prediction decile is flat (-0.054 to +0.029 across the ten deciles; `diag2` in § 8). The rank correlation comes from the SHAPE of `y` (how often a bracket times out and pays only its cost, which tracks volatility), not from its mean. A screen on rank IC would promote variants that cannot earn S3. **The dev loop therefore screens on a mean statistic (§ 5.2), not on rank IC.**
- **Registered branch: `inconclusive`.** Neither tier is `present`, and neither is `absent`: no corrected S3 upper bound is below +0.10 R. The reason is resolution, not noise in the method: **35 out-of-sample weeks give a corrected S3 interval about +-0.2 R wide, and the weeks, not the packets, set it** (judged-1: 732 fills in 33 weeks, design effect 2.25, CI +-0.19). Another 1,500-packet judge run on one 10-month window cannot resolve a +0.10 R edge either. This is the single most important methodological finding of the lane: **edge research on this desk has to buy WEEKS (history), and only a token-free instrument can buy them cheaply.**

### 4.2 EXTENDED ERA — registered here BEFORE the run

Same harness, features, learners, policy, controls and verdict definitions as § 3, with these changes only (constants `ERA_*` in `desk_edge_ceiling.py`, `build --era`):
- **Cutoffs:** a 4-hour grid over **2021-01-15 .. 2023-10-25** (six half-year folds 1-6) plus the 4-hour grid of the DEV window and every judged-1 cutoff (DEV folds = era folds 7-10). Nothing in HOLDOUT (2025-05-01 .. 2025-10-25) or FULL RUN (2023-11-01 .. 2025-04-30) is read as a cutoff: `build --era` calls `desk_edge_devloop.assert_not_locked` on every cutoff. The 2023-10-25 end leaves the 96-bar horizon inside October.
- **Random-entry pool per fold** = every eligible cutoff of that fold's window (half-year folds; the driver's folds for 7-10).
- **Walk-forward:** test folds **3-10** (8 folds, about 190 weeks), train on every earlier fold minus the 96-hour embargo; DEV folds are trained on all six era folds and the earlier DEV folds.
- **Family:** both ceiling runs, 12 configurations: corrected alpha **0.05 / 12**. **`present` needs S3 > 0 in >= 5 of the 8 test folds** (2 of 3, scaled). `absent` and `inconclusive` as in § 3, at +0.10 R.
- **Population limits, stated before the run:** six symbols only (the driver's registered universe); 2021-2023 includes the 2021 bubble and the 2022 crash, so a regime-specific learner can win one era and lose another; that is what the fold clause is for.

## 5. The dev loop, the locked holdout and the pre-registered promotion rule

*(written before any dev run; see below)*

## 6. The lever grid, ranked by expected information per dollar

## 7. Budget

## 8. What was not verified
