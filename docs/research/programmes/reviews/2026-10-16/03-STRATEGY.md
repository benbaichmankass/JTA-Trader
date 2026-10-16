## Programme 03 audit: strategy improvement for the non-prop books (2026-10-16)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../../../DOCUMENT-INDEX.md`](../../../../DOCUMENT-INDEX.md) · manager programme audit 2026-10-16 (input to the backlog lanes and the 2026-10-20 programme review) · **Tier-1: nothing here changes a config, a roster or an order path.**

### 1. Intent
- **Q1 per-leg weight.** Measure each routed leg's net R per capital-day, at Stage 0 and live, per account class.
- **Q2 / Q2-C tune before retire.** Test single entry-axis changes on the real-money legs. Any best-of-k PASS must survive a fresh-window confirmation (rung S0-C) before a Tier-3 proposal.
- **Q3 power.** Grade the underpowered `alpaca_live` 1d legs (`ief`, `slv`, `iaum`) on windows of 10 years or more.
- **Q5 instrument integrity.** Fix the pairs R scale (`PAIRS-R-SCALE`), plus the ORB and `backtester.py` cost stacks. **Q7** is the portfolio question; **Q8** is new families (M22 pairs, M27 scalps).
- **Money and goal:** G1, every real-money leg pulling its weight. The real-money legs are `bybit_2` (5 legs, mirrored on `bybit_portfolio`) and `alpaca_live` (3 legs).

### 2. What has been done
**Q2 / Q2-C (entry axes): answered, honest negative on every confirmation.** All 4 S0-C confirmations failed, so 0 of 4 survived:
- `f0e2-05` `eth_pullback_2h` `adx_min=22` (+10.18R, n=116) → `470a-01` (10-15): **FAIL**. A22 −5.81R against baseline −2.04R, n=106.
- `f0e2-10` `trend_donchian_sol_4h` VH95 (+3.07R, n=75) → `470a-10` (10-15): **FAIL**. 33.45R against 36.95R, n=83.
- `470a-05` `ada_pullback_2h` `pullback_frac=0.618` (+11.76R, n=111, 3 of 4 folds) → `RQ-20261015-4941-01`: **FAIL**. 38.04R against 39.21R, n=114.
- `470a-09` `trend_donchian_eth_4h` `min_confidence=0.7` (+2.50R against a 2.0 bar, n=116) → `RQ-20261015-4941-02`: **FAIL**. +0.81R, and drawdown worse by 0.96R.

Other entry sweeps, all FAIL, dated 10-15:
- `470a-02`: −9.26R.
- `470a-03`: −26.2R.
- `470a-04`: +7.44R, but only 2 of 4 folds.
- `470a-06`: all four arms are identical (n=46). The cooldown never binds on `xrp_4h`.
- `470a-07`: best arm +0.24R.
- `470a-08`: +6.16R, but worse drawdown.

**Q1:**
- The census `470a-11` ran on 10-15 with `no_action_warranted`. Real money: 3 pull weight, 1 drag, 3 underpowered. Prop: both drag. It ran **before** `trend_donchian_sol_prop` joined `bybit_2`, so it is stale.
- Live half, `8bbc-01` / `-02` (10-16), both **BELOW_BACKTEST** on real money:
  - `xrp_pullback_2h`: −8.84R over 16 closes, 3.4th percentile.
  - `ada_pullback_2h`: −7.04R over 15 closes, 4.7th percentile.
  - Both are below the plan's n≥20 threshold.
- `HEADLINE-MEASURE-CAPITAL-DAY` is not built. Three definitions of "capital-day" are in use.

**L-LADDER:**
- `f01d-01` `sol_prop`: PASS, +60.6R, n=394, 6 of 8 folds. It is now on `bybit_2` and `bybit_portfolio`.
- `f01d-02` `eth_prop`: **indeterminate, `control_failed`**. The control arm does not reproduce the committed record (n=1029).

**Q4 lessons:**
- `419b-02` pullback short-side drag: FAIL / NOT_CONFIRMED, n=571.
- `419b-03` trend long/short asymmetry: FAIL, n=1434.
- `72ad-01` (10-15) pullback long-side drag on held-out legs: FAIL / NOT_CONFIRMED, n=725.

**Q7:** `419b-04` returned `no_action_warranted` (n=815).

**Q5 / M22:** the four pairs PASSes (`RQ-20261007-005..008`) are unreadable. `PAIRS-R-SCALE` is still queued and `470a-12` is still blocked.

**Status by question:**
- Answered: Q2 and Q2-C (negative), and Q4 so far.
- Open: Q1 (live half), Q5, Q7, Q8.
- **Never had a unit: Q3** (the 10-year `alpaca_live` window; no queue file names it). **Q6** was answered by `470a-02` / `-03` and is moot, because the source lead failed.

### 3. Queue state
How I attributed units: `roadmap` ∈ {M21, M22, M27, M18, L-LADDER} plus the plan's named IDs.
- **Queued (8):** `470a-11`, `1631-01`, `1631-02`, `8bbc-01`, `8bbc-02`, `f01d-02`, `RQ-20260928-001`, `RQ-20261007-017`. The 8bbc pair and `f01d-02` already have records but still read `queued`.
- **Blocked (4):**
  - `470a-12`: waiting on `PAIRS-R-SCALE`.
  - `1631-03` / `-04`: `backtest_system.py` has no roster entry and no 5m feed for MGC or SLV.
  - `RQ-20261007-032`: its legs are `enabled: false`.
- **Done this week:** 32 or more (f0e2 ×13, 470a ×10, 4941 ×2, 419b ×3, 72ad, f01d-01, 1631?). Every Q2 unit is done.
- **Oldest:** `RQ-20260928-001` (ict_scalp HTF bias) has **never been dispatched**. It is "session-local", so no route runs it, and 6 of its 7 legs are on no roster; only `ict_scalp_mgc_15m` remains, on `ib_paper`.

**Theme `live_strategy` overall:** 92 queued, 14 blocked, 65 done, 8 retired. Of the 92 queued:
- **76 are generated** recurring sweeps: 36 M20 exit-lever, 26 E35 bracket, 14 weekly walk-forward.
- 16 are hand-written.
- The 76 generated units cover 24 real-money legs, 40 paper/mirror/prop legs, and **12 legs on no roster**: `eth_pullback_2h`, `gld_pullback_1h`, `qqq_pullback_1h`, and four ict_scalp variants.
- **10 titles are duplicated.** Two examples: mgc `M20` (`RQ-20261004-656` and `RQ-20261005-005`) and `xrp_4h` `M20` (`RQ-20261009-005` and `RQ-20261010-003`).
- 51 of the 76 have result rows: 43 `wiring_only` (ungraded), 31 `no_action`, 17 `pass`, 8 `indeterminate`.
- Most of these are P1's exit and bracket work mislabelled under the P3 theme.

### 4. Misalignments and problems
1. **The selection-inflation finding is not written down.** All 4 single-window best-of-3 PASSes failed confirmation. The plan still budgets more single-axis sweeps in W3. The pass bar on one window cannot distinguish real levers from noise on these legs.
2. **The grader's FAIL label is misleading.** Every entry-sweep FAIL reads *"declared lever's lines are dead config… strip them (Tier-3)"*. That wording could drive a wrong Tier-3 strip of a working entry param.
3. **Live real money is below backtest on 2 of 4 Bybit legs.** Nothing yet decomposes cost from signal mismatch from regime. `ada`'s baseline also shows decay between windows of equal length: +39.2R (n=114) on 2022–24 against +11.9R (n=111) on 2024–26.
4. **Mirror trade counts differ from live** despite roster equality: 11 against 16 closes for xrp, 9 against 15 for ada. I did not check the cause. Either way, it weakens the Gate-2 demotion read.
5. **Integrity defects:**
   - `f01d-02` has `control_failed`, which blocks `eth_prop`.
   - The pairs R scale is about 775× off, while `pairs_sol_eth` and `pairs_bnb_btc` still run `execution: live` on `bybit_1` paper.
   - The census writes to `comms/` but has no `research/results/` record.
   - 43 generated rows are `wiring_only` and ungraded.
6. **Work aimed at nothing on a roster:** the 12 no-roster generated units, `RQ-20260928-001`, and the whole f0e2 batch. f0e2 mostly swept off-roster legs.
7. **Exit-lever PASSes may not have been acted on.** 17 generated M20 PASS rows exist, including on `ada`, `slv_pullback_1d`, `eth_4h`, `xrp_4h` and `sol_prop`. P1 owns them and I did not check their disposition.
8. **Stale text:**
   - M27 `where` still says "ict_scalp legs live on soak books". The scalp soaks were KILLED on 10-05.
   - M21 `next`, plan § 1 (the pre-promotion census) and the § 5 W1 table are all superseded.
   - `research/programmes/03-*.yaml` does not exist.

### 5. Recommended next 5 days (to Tue 2026-10-20)
1. **[research unit] Stage B for `xrp` / `ada` live-below-backtest (highest money impact, real money).** First step: add an `8bbc-03` unit that runs `leg_replay_emit.py` config-exact over the live trades' bars, compares each live trade against its backtest counterpart, and splits the gap into cost, missed or extra signals, and regime. In the same unit, record the mirror-versus-live close gap.
2. **[build row] Fix `f01d-02`'s control so the `eth_prop` promotion can be decided.** First step: diff `comms/research/RQ-20261015-f01d-02/*/run-manifest.json` (window, feed, n=1029) against `comms/strategy_evidence/trend_donchian_eth_prop.json`, then re-run.
3. **[decision for operator] STOP standalone single-window entry sweeps on real-money legs.** In their place, every sweep pre-registers choose-on-A / confirm-on-B in one unit, or uses 8 folds over about 6 years as f01d did. Mark `xrp_pullback_2h` entry axes exhausted and route it to P1 exits. Also fix the grader's FAIL wording.
4. **[build row] `PAIRS-R-SCALE` fix, then move `470a-12` to the queue.** First step: switch `backtest_pairs.py` to the β frozen at the entry bar, with a self-test asserting mean `cost_r` ≥ 0.01. Until the honest record exists, the operator should consider moving the two paper pairs to shadow. That is paper only, so money impact is low.
5. **[build row] Queue hygiene.** RETIRE the 12 no-roster generated units, the 10 duplicates and `RQ-20260928-001`. Move the M20 and E35 sweeps to the P1 theme. Make the census land a `research/results/` record, and re-run it after the `sol_prop` promotion.
6. **[research unit] Q3:** `ief`, `slv` and `iaum` on a 10-year or longer Yahoo window through `exit_lever_ablation.py`. It has never been authored. Author it as specified in plan § 4.

CONFIDENCE: I verified directly from files on main: verdicts, n and R for every named unit, rosters, soak dispositions, milestone text, unit counts and the duplicates. I inferred, without checking: the cause of the mirror/live count gap, whether the 17 M20 PASSes were dispositioned, and why the census has no `research/results/` record.