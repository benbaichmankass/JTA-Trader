# In-trade path measures and giveback — measurement, outside research, pre-registered levers (2026-10-22)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `EXIT-PATH-METRICS-W43` (checklist row of the same name). One question: which in-trade path measures predict giveback early enough to act on, and which exit levers should be pre-registered from them? Operator idea: IDEAS.md 2026-10-21, "surf the volatility instead of holding through it".

## 1. What was measured

Tool: `scripts/research/path_state_giveback.py` (new; reuses `path_metric_giveback.py`'s harness runner and models; tests `tests/test_path_state_giveback.py`). Rung 1 (RQ-20261022-007) reads each trade **once** at bar 6; a lever acts on a **state**, so this reads every (trade, bar) where the trade has reached peak ≥ 1.0 R and is not on its exit bar.

- **Population:** 958 harness trades (18,770 states) on `xrp_pullback_2h`, `ada_pullback_2h`, `trend_donchian_eth_4h`, `trend_donchian_eth_prop`, `trend_donchian_sol_prop`, 2020-07-01 .. 2026-10-15 23:59, config-exact `--emit-paths`, the harness's venue-aware cost stack (the same for every arm). Trades with a state: xrp_pb 145 of 394, ada_pb 170 of 402, eth_4h 117 of 275, eth_prop 373 of 1085, sol_prop 171 of 403.
- **Label:** `exit_r <= open_r_t − X` on the trade's own harness exit (truncation-honest), X = R "given back from here".
- **Features (bars ≤ t only, window w = 6):** efficiency ratio, choppiness index, realised-vol ratio (last w bar-moves vs the first w after entry), ATR-vs-entry ratio, distance below peak in ATR, share of peak given back. Baseline: open R, peak R, bars since peak, bars in trade.
- **Grading:** 6 calendar folds by entry time, leave-one-fold-out logistic; out-of-sample log-loss and AUC; per-feature univariate AUC and fold agreement.
- **Not registered.** This was a discovery read of three X values; it is cited as such by the units. Re-run: `python3 scripts/research/path_state_giveback.py --leg … --window 6 --min-peak 1.0 --x 1.5 --folds 6 --fold-majority 4 --stop-room-control …`.

### Results (pooled, 958 trades / 18,770 states)

| X | base rate | baseline | + path features | ll gain, folds won | verdict at the 0.01 / 4-of-6 bar |
|---|---|---|---|---|---|
| 1.0 | 17.6% | AUC 0.412 (fold-unstable) | 0.536 | +0.0002, 3/6 | fail |
| 1.5 | 8.2% | AUC 0.536 | 0.679 | **+0.0115, 5/6** | pass (not registered) |
| 1.5, **+ room-to-stop in the baseline** | 8.2% | AUC 0.784 | 0.778 | **+0.0022, 3/6** | **fail** |

**The pooled pass is stop-room mechanics.** `dist_to_stop_r` (room left before the stop in force) alone has pooled AUC 0.81 at X = 1.5 and 6/6 folds on the same side; once it is controlled the path features add nothing (−0.0006 AUC). The features that looked strongest uncontrolled — `dist_atr_t` 0.428 and `dd_frac_t` 0.422 (6/6 folds each, below 0.5: the further below the peak, the *less* further giveback) — are the same fact: a trade already near its stop has no room to fall another 1.5 R. Per leg with the control, X = 1.5: ada_pb +0.0087 (5/6 folds, under the 0.01 bar), xrp_pb −0.0077 (2/6), eth_4h −0.0292 (2/6). On the two prop legs **no state gives back ≥ 1.5 R from here** (base rate 0.0), and at X = 1.0 the base rate is 2.5% (eth) and 10.8% (sol) with baseline AUC ≈ 0.85 before any path feature (the baseline already explains it).

### Which features have any signal, and which sign

- **Efficiency ratio flips sign by leg family.** Lower ER → more giveback on ada_pb (AUC 0.438, 6/6 folds at X = 1.0) and xrp_pb (0.472, 5/6); **higher** ER → more giveback on the prop legs (eth_prop 0.701, 6/6; sol_prop 0.619, 5/6) — a one-directional run reverses. A single pooled ER gate would be wrong for half the legs; the lever units declare direction per leg, and the prop unit tests both directions.
- **ATR-vs-entry ratio** pooled X = 1.5: AUC 0.459, 6/6 folds (higher ATR vs entry → less further giveback), but it does not survive the stop-room control pooled.
- **Choppiness** is weak (ada_pb 0.545, 5/6; elsewhere 0.39–0.51). **Realised-vol ratio** is near 0.5 everywhere.
- **Early enough to act?** Median bars from a positive state to the exit: 22 (X = 1.0) and 25 (X = 1.5) bars pooled, 25–30 on the 2h pullbacks, 5–10 on the 4h/prop legs — enough lead on the pullback legs, thin on the others.

### Screen: a full exit at the first flagged state (NOT a lever grade)

Mean (open R at the flag − the trade's own exit R), first state per trade satisfying a training-fold-median split on each feature in its hypothesised direction. Every pullback/trend row is **negative**: exiting outright at the first flagged state loses against the declared exit (ada_pb −0.48 to −0.61 R per trade against −0.57 for the first-state baseline; eth_4h −0.58 to −0.95 against −0.73; xrp_pb −0.23 to −0.32 against −0.25). Only `trend_donchian_sol_prop` is ≈ 0 (+0.06 with ER against −0.02). This is consistent with the 2026-10-22 failures of the fixed bank, level-triggered tightening and the 1R giveback stop: the declared wide trail earns its R in the right tail, so the units below **tighten or partially bank, never exit outright**, except the time-in-chop stop, which is graded on its own.

## 2. Outside research (what could be verified this session)

Thin, and said so. Searches this session returned secondary sources only; nothing below was read as a primary paper.

- **Chandelier Exit** — Charles Le Beau, popularised by Alexander Elder; trailing stop 3 ATR below the highest high over a 22-bar lookback ([StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit), fetched). Source of the 3.0 × ATR tight multiple in the ATR-contraction unit and of "ATR trail = volatility-adaptive" as practitioner default. Adaptive-multiplier variants circulate on TradingView ([example](https://id.tradingview.com/script/S4WGeup3-Adaptive-Chandelier-Exit-MAB/)) as indicator descriptions with no backtest evidence.
- **Efficiency-ratio trails (Kaufman) and Kase DevStop:** a search returned **no usable source** for either; the StockCharts KAMA page fetch failed. They are used here by name only for the efficiency-ratio definition already in `path_metric_giveback.py`; nothing is claimed about their published performance. Open item for a later scan.
- **Stop-loss overlays on momentum:** Han, Zhou and Zhu, "Taming Momentum Crashes: A Simple Stop-Loss Strategy" (SSRN) reports a 10% stop cutting the worst monthly loss of equal-weighted momentum from about −49.8% to about −11.3% over 1926–2011, with figures varying by version; commentators note the results are gross of transaction costs and that stops raise turnover ([Alpha Architect](https://alphaarchitect.com/2016/08/taming-the-momentum-roller-coaster-fact-or-fiction/), [Quantpedia summary](https://quantpedia.com/three-methods-to-fix-momentum-crashes/)). Equity momentum, monthly, gross — an analogy for tail control, not evidence for these crypto legs. Volatility scaling of momentum is reported to reduce crashes (Hanauer & Windmueller, via the Quantpedia page) with a look-ahead-bias critique cited in a Springer paper; again equities.
- **No source found** that tests a volatility-adaptive trail plus scale-out for profit giveback; the search itself said such a combination "appears to lack a published empirical test". The lever units are therefore original tests, graded at our cost stack.

## 3. Pre-registered units (10; none duplicates RQ-20261022-eba2-*)

Read first: eba2-01 (Q11 transfer, k = 6), -02 (prop, k = 12), -03 (R-armed tight trail), -04 (vol-controlled label), -05/-06 (fractional giveback exit), -07/-08 (metric-triggered bank/trail), -09..-11 (swing trail variants), -12..-14 (far-rung bank), -15 (ADX). The b7e1 units differ by design: per-bar **state** (not bar-6), stop-room control, **feature-gated** tighten/bank/stop with an **ungated control arm** in the same unit, and a prop unit with both ER directions.

Runnable now (dry run `python3 scripts/research/dispatch_queue.py`, MEASURED this session): **b7e1-01, -02, -03 `would_dispatch`**, route runner / github_runner.

| unit | arm family | leg(s) | bar |
|---|---|---|---|
| RQ-20261022-b7e1-01 | rung 1e transfer, w6, X 1.5 | eth/sol/avax pullback_2h, sol/ada/avax donchian 4h | ll gain ≥ 0.01, ≥ 4/6 folds, stop room controlled |
| -02 | rung 1e window variant, w12 | xrp/ada pullback_2h, eth_4h | same |
| -03 | rung 1e prop, w12, X 1.0 | eth/sol prop | same; INDETERMINATE possible |
| -04, -05 (blocked) | R-triggered tight trail gated on **efficiency ratio < 0.20/0.30/0.40** (peak ≥ 1.5 R → 2.5 × ATR) | ada_pb, xrp_pb | beat A and ungated UT15; Path B |
| -06 (blocked) | **ATR-contraction** (≤ 0.9/0.8/0.7 of entry ATR) tight trail, 3.0 × ATR (Chandelier multiple) | ada_pb | beat A and UT15 |
| -07 (blocked) | **choppiness-gated** tight trail (> 0.55/0.65/0.75) | ada_pb | beat A and UT15 |
| -08 (blocked) | **split/partial exit gated on ER < 0.30** (25/33/50% at +2.0 R) | ada_pb | beat A and the same bank ungated |
| -09 (blocked) | **time-in-chop stop** (6/10/14 bars of ER < 0.25, peak ≥ 1 R, open ≤ ½ peak) | ada_pb | beat A; Path B reported |
| -10 (blocked) | ER-gated tight trail **both directions** (> 0.60/0.70 and < 0.25/0.35, peak ≥ 2 R → 2.5 × ATR), TP 6 R untouched | eth_prop | beat A and UT20; then the prop EV/survival gate |

- **Bar:** replace grade, 6 calendar folds, ≥ 5 of 6, maxDD ≤ 1.35 × A, ≥ 0.02 R/trade materiality, 39-trade floor. **The zero-materiality TP-compliance bar does not apply**: no arm changes a TP (each unit says so). Prop unit: prop EV/survival against the firm DD limits is a further gate; prop legs clear a superset.
- **Why blocked:** the harness has no path-state gate (only R-armed, stall-armed, ATR-percentile and ADX). Build row `PATHSTATE-TRAIL-GATE` carries the flag contract; `requires` nothing else. Units sit in `research/queue/blocked/` with `blocked_on` naming it.
- **Priors, stated:** the measurement gives weak support for ER/chop/ATR gates (they fail once stop room is controlled) and none for outright exits. Confidence is set to 0.1 on every unit; rung 1e (b7e1-01..03) is the cheap first read and the build row says to drop the failed-feature arms if all three fail. Each unit names its variants (first-test fail ≠ dead idea).
- **Programme nodes:** `P1-Q13-pathstate-{transfer,w12,prop}` and `P1-Q14-*` in `research/programmes/01-active-trade-management.yaml`; roadmap ref `L-ATM` on all.

## 4. What this does and does not establish

Established (measured, harness paths, not live): at the per-state level, room to the stop explains the pooled "predictable giveback"; the efficiency ratio's direction differs between pullback and prop legs; acting outright on a flagged state loses against the declared exit on every pullback/trend leg. **Not established:** that any path state predicts giveback beyond stop room (units b7e1-01..03 decide it); that any lever pays (nothing in this PR is graded); anything about live trades — harness paths only, and every harness peak is a lower bound on live peaks. Merged ≠ deployed ≠ observed: this PR adds research tooling and units; nothing is deployed and nothing has run through the queue.
