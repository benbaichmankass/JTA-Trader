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
- **Holding period is an axis (amendment, still before the run; operator popup ~16:10Z relayed by the manager: *"Yes, holding period is a lever (Recommended)"*).** The live `claude_desk` leg is capped at a 60-minute hold (DESK-18E, PR #20662); judged-1 held 48 bars. The era action set adds three short holds on the 1h grid: `H1a` (stop 0.5 ATR, 1.0 R, **1 bar = 60 min**), `H1b` (1.0 ATR, 1.0 R, 1 bar), `H4` (0.75 ATR, 1.5 R, 4 bars), beside the 12/24/48/96-bar geometries. Every action records its cost in R. **Per horizon** the run reports each learner's policy restricted to that horizon, the unselected mean net R and the mean cost in R, and labels the horizon `no_extractable_s3` (every corrected S3 upper bound < +0.10 R: no judge spend on it), `candidate` (best point S3 > 0 and not excluded) or `not_excluded`. A 1-bar hold on 1h bars resolves the stop/target order inside one bar by the driver's stop-first rule; a 5-minute-bar replay is the finer instrument and is not built here.
- **Population limits, stated before the run:** six symbols only (the driver's registered universe); 2021-2023 includes the 2021 bubble and the 2022 crash, so a regime-specific learner can win one era and lose another; that is what the fold clause is for.

### 4.3 The dev-loop pilot: V1 (the current judge) — registered verdict **SCREEN_FAIL**, and why

Unit `RQ-20261027-fe57-01`, registered (commit ee847dfa) before any packet was judged. Judged by 10 Sonnet plan subagents x 10 packets (no API credits), each limited to reading its own batch file and writing its own output. Evidence: `comms/research/desk_edge/dev-1/V1/` (`ranks.jsonl`, `verdict.json`, `rejected/`). The lane scored it with the unit's own command; the dispatcher's run after merge is the registered landing.

- **Intake and audit (MEASURED from the subagent transcripts):** 3 of the first 10 batches (b03, b04, b09) broke the isolation rule: they used Bash and produced their scores with a script (b03 and b04 said so: "0.2 x h48 mean_r [+ 0.1 x h12]"). They were **rejected and re-judged** with the same protocol and a stricter instruction. The rejected files are kept. All 13 transcripts touch only their own batch file and output; **none read the mask key**. Final intake: 100 of 100 packets, 1,200 valid cells, 0 refused.
- **Result:** mean SEL by look (25 / 50 / 75 / 100 packets): -0.058, -0.015, +0.033, **+0.044**, one-sided 80% lower bound -0.059: **SCREEN_FAIL** (needs >= +0.10 and > 0). Top-pick S3 +0.161 [-0.18, +0.48], n 100. Not killed early: no look had an upper bound below +0.10, because at this n the screen can only kill a clearly bad variant (§ 5.3, stated).
- **The finding that matters (MEASURED, post-hoc):** regressing each batch's 120 cell scores on that cell's own base-rate means (h4, h12, h48) gives **R^2 = 1.00 in 5 of the 7 compliant first-pass batches** (0.90-0.99 in the rest, and in the three strict re-runs). Typical fit: score = 0.10-0.20 x h12 mean + 0.10-0.22 x h48 mean. Asked to rank cells, **the judge is a linear base-rate rule.** It ignores swing distances, trend, ATR and session, which matches judged-1's theses (731 of 732 cite the base-rate rows).
- **So the judge can be priced for free:** `desk_edge_devloop.py emulate` applies that rule to all 4,535 built DEV packets (`comms/research/desk_edge/dev-1/base-rate-emulator.json`): SEL **-0.027 [-0.135, +0.079]** (h12+h48), -0.015 [-0.124, +0.092] (h48), -0.035 [-0.142, +0.071] (all three); top-pick S3 -0.050 [-0.17, +0.07]; 47 weeks. **Every upper bound is below +0.10: the current judge's way of choosing is EXCLUDED as a useful edge on the DEV window**, at a resolution judged-1 could not reach. MEASURED sd of SEL per packet: 1.17 R (it re-prices § 5.3: the SE at 100 packets in ~44 weeks is about 0.12-0.15 R).
- **Spend:** 13 subagent runs x about 172k tokens (MEASURED by the harness) = about 2.2M input tokens: **about $7 API-equivalent** at Sonnet list price (INFERRED), on the plan.
- **Consequence for the program (DECIDED by the § 2 tree, given § 4.1 and this):** more judge spend on the current brief and packet is not justified: the judge reproduces a rule that the ceiling and the emulator both price at about zero. A judge variant earns dev spend only if it is built to use information the base rates do not carry, and only after the token-free ceiling shows that information exists (§ 4.2, § 6).

## 5. The dev loop, the locked holdout and the pre-registered promotion rule

Registered here before any dev run; every constant is in `scripts/research/desk_edge_devloop.py` and changes only by a new registration, never after a result.

### 5.1 The dev sample

`desk_edge_devloop.py sample`: **100 judged-1 packets**, balanced over fold (4) x session of the cutoff (4) x BTC 168-hour return sign (2) = 32 strata (3-4 each, MEASURED on the first build: 32 strata, min 3, max 4), in a seeded round-robin order so that the first 25, 50 and 75 are themselves near-balanced. Every packet is rebuilt from the candles and its id asserted. Using judged-1 packets means the current judge's own decisions on them are already paid for, and every variant is scored on the same 100 packets (paired by construction).

### 5.2 What a variant is asked, and the screen statistic

A dev variant is a (brief, packet, model, reasoning setup) tuple. On each dev packet the judge first **scores all 12 (asset, side) cells** with its expected net R in excess of a random-time entry of the fixed dev bracket GJ (market, stop 1.25 ATR, target 2.0 R, 48 bars), then may propose as usual (`RANK_ADDENDUM`). Every cell has a label (`y`, the ceiling's construction: the driver's engine and random baseline), so 100 packets give 1,200 labelled judgements instead of about 50 fills.

**Screen statistic: SEL** = per packet, mean `y` of the 2 highest-scored cells minus mean `y` of all its labelled cells; averaged per ISO week, weeks resampled. Its expectation is the S3 of a top-2 desk; the subtraction removes the packet's common shock. **Rank IC is NOT used** (§ 4.1: IC +0.10 with a flat decile curve). The **top-pick S3** (one best cell per packet, if its score > 0, through the driver's `cluster_stats`) is reported beside it.

**`SEL_USEFUL` = +0.10 R**, the same useful-edge line as the ceiling.

### 5.3 Sequential stopping and the promotion rule (dev -> holdout)

Looks after **25, 50, 75 and 100** packets of the sample order.
- **kill** at any look if the one-sided upper bound of mean SEL at alpha **0.05 / 4** is below +0.10 R: the variant stops and its remaining packets are not judged (the saving).
- **promote** at the last look if mean SEL >= **+0.10 R** AND its one-sided **80%** lower bound > 0. Dev is a SCREEN, deliberately permissive; the holdout is the TEST.
- **screen_fail** otherwise.
- At most **2** promoted variants per batch go on, highest SEL first.

**Power, stated (INFERRED from judged-1's sd of `y`, about 1.6, and its design effect, about 2):** at 100 packets the SE of mean SEL is roughly 0.15-0.2 R. A variant whose true SEL is +0.20 is promoted about 60-75% of the time; a null variant about 15-25%. Dev cannot certify anything; it ranks.

### 5.4 The locked holdout (one look per promoted variant)

- **Window 2025-05-01 .. 2025-10-25**, schedule `make_schedule(seed 20261101, 4-hour gap)`, **300 packets** per promoted variant. `desk_edge_devloop.py holdout` refuses to build a holdout packet unless a committed promotion record says `dev_decision: promote` (`assert_not_locked`; tested).
- **PASS** if the weekly mean SEL's one-sided lower bound at alpha **0.05 / H** is > 0, where **H = the number of variants EVER sent to the holdout** (the correction for every variant tried that got this far; dev looks are corrected inside the screen), AND the top-pick S3 (driver statistic) >= **+0.05 R**. FAIL otherwise. No re-look, no re-cut, no second seed on the holdout.
- The holdout window is before the judge's knowledge cutoff, like every replay window (the mask is the defence; the label on any PASS says so).

### 5.5 The full registered run (the Stage-0 evidence record)

Only a variant that PASSED the holdout. **Window 2023-11-01 .. 2025-04-30** (never read by anything before this; `assert_not_locked` refuses it without a holdout PASS). It is registered as its own `research/queue` unit before it runs, with the e535 rule shape: n by power from the holdout's measured sd and effect, S1, S2 and S3 each > 0 with CI lower bound > 0, >= 3 of 4 folds positive, mean > 0 after dropping the 3 best weeks, the driver's engine, costs and baseline unchanged. That record, plus the forward-shadow set (`RQ-20261027-e72b-02`) and Gate 1, is what real money needs; nothing here shortens Gate 1 or `MD-PROMOTE-S1-S2`.

### 5.6 Cost per variant (API-equivalent dollars on the plan; no API credits are spent)

Judging runs only in plan sessions (canonical § "Nothing spends Anthropic API credits"). MEASURED anchors: $0.0688 per packet for a stateless call (judged-1, $103.14 / 1,498), $0.337 per packet for a session carrying ~290k tokens of context (the DESK-18B pilot). A rank reply is about 12 cells longer than a proposal. INFERRED: **$0.05-$0.10 per packet** for a repo-less subagent that sees only the protocol and its packets. So a dev variant is **$5-10** (less if killed at a look), a holdout look **$15-30**, a full run **$100-300** depending on n. Self-consistency with k samples multiplies by k; an Opus judge by about 1.7 (list-price ratio, INFERRED).

## 6. The operator's redirect (2026-10-27 ~16:40Z): a BIGGER edge, shorter bars, the hold rule

Relayed by the manager, verbatim: *"we need a bigger edge, like an edge that needs more than 35 weeks to prove that it's statistically significant isn't a strong enough edge, so we do need to think about ways of refining and optimizing to improve it, not just reconstructing testing to make it look better. ... maybe we can raise the cap for from 60 minutes for like cases where ... if the trade started within 60 minutes, then it can continue going ... maybe it needs to be looking at shorter time frames ... 30-second bars and trades that last ... up to half an hour."*

### 6.1 The bar (registered now, before any further variant)

- **TARGET: S3 >= +0.25 R on the DEV window alone**, with its 95% weekly-cluster CI lower bound > 0. That is what about 35-45 DEV weeks resolve on their own (§ 4.1: about +-0.2 R). `desk_edge_devloop.SEL_USEFUL` = **+0.25** for every variant after V1 (V1 was registered and run at +0.10, and keeps that rule).
- **For a hold whose cost is a large share of its move, S3 is not enough: S1 > 0 is also required at the stated cost scenario.** A random entry pays the full round trip, so at a 30-minute taker hold a variant can have S3 +0.25 and still lose money (§ 6.3: cost about 0.29 R of a 1-sd stop).
- **The extended-era run (§ 4.2) is now ONLY a ceiling DIAGNOSTIC and a robustness check** for a variant that already clears the bar on DEV. It was registered and started before this direction, so it is finished and reported as a diagnostic. **It is never used to make a small edge significant.**

### 6.2 Data we HAVE for shorter timeframes (MEASURED from this container, 2026-10-27)

| source | what | reachable | note |
|---|---|---|---|
| Binance Vision USD-M perp klines | 1m, monthly and daily files | yes (fetched 2026-06..09, six symbols, 24 files, 39 MB) | perp, not spot: closer to the desk's venue than the driver's spot candles |
| Binance Vision spot klines | **1s**, monthly | yes (HTTP 206 on 2026-08) | sub-minute bars without building them |
| Binance Vision USD-M aggTrades | every aggregated trade, daily | yes (2026-09-01) | builds 30s bars, signed order flow, trade imbalance |
| Binance Vision USD-M bookTicker | top of book | **2024-03 yes, 2026-09 no (404)** | historical spread only for older periods |
| **Bybit public trade dumps** (`public.bybit.com/trading/<SYM>/`) | every trade on the desk's own venue, daily csv.gz | yes (BTCUSDT 2026-09-01 = 70 MB) | the honest source for Bybit sub-minute bars and flow; large (~2 GB/symbol/month for BTC) |
| Bybit REST API (`api.bybit.com`) | klines, order book | **no: HTTP 403** from this container | matches the scan builder's note (geo-blocked from a session) |

What sub-minute research would take: 30s bars from Bybit trade dumps for six symbols over the DEV window is roughly 10 GB/symbol to download and reduce to bars (INFERRED from one day's size), so a runner job with streaming reduction, not a session. **1m perp bars are enough to start** and cost minutes.

### 6.3 Cost per horizon (MEASURED: `scripts/research/desk_edge_levers.py costs`, `comms/research/desk_edge/levers/cost-per-horizon.json`)

Cost as a fraction of the 1-sd move at that hold (= cost in R for a stop of 1 sd). Population: Binance USD-M perp 1m klines, 2026-06-01..2026-09-30, six symbols, non-overlapping returns, median over symbols.

| hold | 1-sd move | median abs move | repo stack 10.5 bps | Bybit VIP0 taker 14 bps | maker in / taker out 9 bps | maker both 4 bps |
|---|---|---|---|---|---|---|
| 1 min | 9.2 bps | 3.8 | **1.14** | **1.52** | 0.98 | 0.43 |
| 5 min | 20.8 | 8.3 | 0.50 | 0.67 | 0.43 | 0.19 |
| 15 min | 34.4 | 14.1 | 0.31 | 0.41 | 0.26 | 0.12 |
| 30 min | 49.1 | 19.7 | 0.21 | 0.29 | 0.18 | 0.08 |
| 60 min | 68.3 | 27.9 | 0.15 | 0.21 | 0.13 | 0.06 |
| 4 h | 128 | 55 | 0.08 | 0.11 | 0.07 | 0.03 |
| 12 h | 205 | 108 | 0.06 | 0.07 | 0.05 | 0.02 |
| 48 h | 520 | 269 | 0.03 | 0.04 | 0.03 | 0.02 |

- **Where cost kills:** at 1-5 minutes a taker round trip costs 0.5-1.5 R of a 1-sd bracket; no plausible timing edge clears that. At 15-30 minutes taker costs 0.3-0.4 R: a variant would need S3 of about +0.55 to +0.65 to reach the +0.25 bar in S1.
- **Where maker execution rescues it:** maker on both sides cuts 30-minute cost from 0.29 R to 0.08 R and 15-minute cost from 0.41 R to 0.12 R. That is the single largest MEASURED lever on S1 for short holds, before fill probability and adverse selection (not measured: a limit that fills is more often a limit the market ran through).
- **Flag (say something):** the replay charges **7.5 bps fee + 3 bps slippage** round trip (`execution_costs.DEFAULT_FEE_BPS_ROUNDTRIP`, `PERP_SLIPPAGE_BPS_ROUNDTRIP`) for every crypto perp. Bybit's published VIP0 linear taker fee is 0.055% per side = **11 bps round trip in fees alone** (INFERRED from the public schedule; the account's real tier was NOT read). If the desk pays VIP0 taker, every replay in this repo under-charges cost by about 3.5 bps a round trip: negligible at 48 h (0.007 R), material at 30-60 min (0.05-0.07 R). Filed for the manager in § 8.

### 6.4 The levers, ranked by estimated added edge x probability (DEV, MEASURED where stated; `comms/research/desk_edge/levers/levers-dev-ridge.json`, ridge on P+, test folds 2-4, 35 weeks; post-hoc looks, 24 lines)

| rank | lever | measured on DEV | estimated added edge | P(real, judgement) | next step (token-free first) |
|---|---|---|---|---|---|
| 1 | **Execution cost: maker / limit entries** | not an S3 lever (the baseline pays the same cost); S1 gain = cost saved: +0.21 R at 30 min, +0.15 R at 60 min, +0.08 R at 4 h, +0.02 R at 48 h (§ 6.3) | +0.1 to +0.2 R **S1** at <= 60-min holds, after adverse selection about half of it | 0.7 | limit-entry geometries in the action set (the driver already simulates `limit` fills); a 1m-bar version for <= 60 min |
| 2 | **Shorter bars and holds (1m bars, 5-30 min holds) + event / flow windows** | not yet measured; cost table above says taker S3 must be +0.3 to +0.7 R before S1 is positive | unknown; the one place a large edge is plausible (order-flow imbalance, liquidation cascades: DESK-27-LIVE-FLOW) | 0.2 | build the 1m-bar ceiling on Binance perp 1m + aggTrades flow (`RQ-20261027-fe57-02`) |
| 3 | **Hold rule: enter within 60 min, run to H** | partly measurable now: the era run's per-horizon table covers 1, 4, 12, 24, 48, 96 bars on the same decisions (§ 4.4 when it lands); on DEV unselected S1 rises from -0.15 R (12 bars) to -0.055 R (96 bars) because cost falls with the hold | at the 1h bar it changes S1 by +0.05 to +0.10 R via cost; S3 about 0 at every hold so far | 0.5 (on S1), 0.1 (on S3) | 1m-bar ceiling with H in {60, 120, 240, 480} min vs a hard 60-min cap (`fe57-02`) |
| 4 | **Session / event window** | top 5% picks in 07-13 UTC: S3 +0.153 [-0.15, +0.49]; other windows -0.05 to -0.09 | +0.15 if real | 0.15 (one of 4 windows, post-hoc) | test on the era folds and the 1m ceiling, registered |
| 5 | **Fade the model's most confident tail** | top 1%: S3 **-0.244** [-0.39, +0.07]; top 0.2%: **-0.400 [-0.59, -0.27]** (n 570): the model's most confident picks are reliably WRONG | +0.25 to +0.40 if the reversal is real | 0.15 (found by looking; extreme momentum reverting is plausible) | registered test on era folds 3-6, which this model has not been scored on (`RQ-20261027-fe57-03`) |
| 6 | **Asymmetric geometry (target vs stop)** | S3 about 0 at every geometry (-0.013 to +0.007 unselected); unselected S1 best at 2 ATR / 3 R / 96 bars (-0.055) | via cost only (S1) | 0.6 on S1, ~0 on S3 | none beyond rank 3 |
| 7 | **Selectivity: abstain unless confident** | as built it HURTS (rank 5); top 20% / 5%: -0.016 / -0.009 | <= 0 as built | - | only through rank 5 |
| 8 | **Direction-neutral pairs (best long + best short)** | all: -0.006 [-0.05, +0.04]; top 5%: -0.074 [-0.22, +0.10] | ~0 | 0.05 | none |
| 9 | **Judge levers (brief, Sonnet vs Opus, self-consistency)** | V1 is a linear base-rate rule; the rule is excluded (§ 4.3) | only on information the base rates lack | 0.05 until rank 2 or 5 finds information | none until then |

**Reading of the table (DECIDED by the § 2 tree):** no lever measured so far gives S3 near +0.25 on DEV. The two that could (rank 2, rank 5) are unmeasured or post-hoc; the largest MEASURED lever (rank 1) moves S1, not S3. **No judge spend until a token-free lever clears the bar.**

## 7. Budget

- **Spent in this lane (API-equivalent on the plan; no API credits):** ceiling, emulator, levers and cost table **$0** (CPU); V1 pilot about **$7** (13 subagent runs x ~172k tokens, 3 of them rejected re-runs). Lane ceiling $25.
- **Next (all token-free):** `fe57-02` 1m-bar ceiling (build about a day of lane work; runner CPU), `fe57-03` fade test (CPU, about 1 h on a runner: it rebuilds the era packets). Judge spend resumes only for a variant built on information a token-free test found: then dev $5-10 per variant, holdout $15-30, full run $100-300.

## 8. What was not verified

- The account's real Bybit fee tier (the cost table carries both the repo stack and VIP0); fill probability and adverse selection of maker entries.
- That the extended-era DEV folds equal the driver's folds to the bar (the era fold windows are rebuilt from the driver's arithmetic with a ceiling at the second).
- The judge's behaviour beyond Sonnet: the base-rate-rule finding is for the Sonnet subagent setup only.
- Whether V1's subagents, which had file tools, are representative of a tool-less API judge: their transcripts show no foreign reads, but the 3 rejected batches show the setup invites shortcuts.
- The lever table's lines are 24 post-hoc looks on one learner (ridge); none is evidence until a registered test.
