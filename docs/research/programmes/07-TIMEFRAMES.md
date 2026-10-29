# Programme 07 — Timeframes: the horizon frontier, decided by cost first

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-18` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `FRONTIER-TIMEFRAMES-1018` (manager session_01VduHYzdaXe27wTDBLSu8ao, operator request 2026-10-18, "Plan now, run in parallel") · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) · roadmap **`L-TIMEFRAMES`** (G1) · theme `timeframes` (weight 1, the floor) · **Tier-1 document: it proposes tests. Every roster, config or param change it leads to is Tier-3 with an evidence record, through the manager.**

Machine tree: [`research/programmes/07-timeframes.yaml`](../../../research/programmes/07-timeframes.yaml). Units: `RQ-20261018-ef5d-01..09` (runnable), `blocked/RQ-20261018-ef5d-10/-11`. Instruments (this lane): `scripts/research/timeframe_breakeven.py`, `scripts/research/harness_stage0.py`. Numbers marked MEASURED were measured in this lane on 2026-10-18 from the file or command named beside them; re-run the command rather than quoting the figure.

## Programme review 2026-10-28 (lane PROGRAMME-REVIEW-20261028) — TRADING track

Population: research units with a result row generated 2026-10-21T19:30Z..2026-10-28T19:30Z (`research_ops_checks.py --kind programme_review --since 7d`, 1,480 units read, 0 unreadable): **445 units, 412 graded** (70 pass, 50 indeterminate, 292 fail), 285 with a programme field and 160 without (live_strategy 70, regime 27, ml_health 21, macro 20, infra 13, new_strategy_prop 8, none 1). This review assigns the 160 by what they ask, not by the field (map section). Every PASS below is a discovery until its confirmation unit passes. **Cost basis:** about 36 of the 70 PASS rows are crypto-harness runs charged 7.5 bps round-trip (MEASURED from each result's argv); only RQ-20261028-001 carried the measured Bybit-linear 11.0 bps. A lever A/B delta is nearly fee-neutral (both arms pay it); an absolute Stage-0 or breadth PASS is not.

**Graded in the window: 14 with `programme: P7`** (3 pass, 8 fail, 3 indeterminate).

**What was learned**
- **Daily crypto long-only Donchian-20 is the robust daily finding.** Pooled over 12 perps it is fold-consistent (`f679-05`, LONG +181.4 R, beats unfiltered B by the materiality bar) and it transfers to basket B (`1b57-15`). The daily D20 failure was an exit-geometry problem: one of a looser 8-ATR trail or a 60-bar time stop makes it fold-consistent (`1b57-13` PASS).
- **D55 does not transfer** (`7c2b-04` FAIL). The intraday cost-gated breakouts at 30m (`7c2b-01`) and 15m (`7c2b-05`, and the maker upper bound `f679-04`) FAIL, consistent with the 10-21 frontier (perps are viable from 15m-30m only at the margin). Re-ask of the daily vol floor (`7c2b-02`): INDETERMINATE.
- All at 7.5 bps. At daily bars the fee is a small share of R per trade, so the cost caveat matters less here than for P3/P5. It is still re-measured before any re-entry case.

**Next 3-4 weeks**

| # | node | decision | on PASS | on FAIL | cost | pre-mortem |
|---|---|---|---|---|---|---|
| 1 | `P7-Q5-confirm` -> the disjoint-SYMBOL check of the 12-perp LONG pass (research-ops authors) | is daily long-only Donchian a new position-trade family for bybit_1 | overlap read vs the 4h trend book, then exit processing (P1) | the LONG filter is a 2020-2026 crypto beta artefact | cpu_light | long-only in a bull-heavy window; the first variant is a bear-window split |
| 2 | `P7-Q6-weekly-etf` | weekly ETF Donchian as one bet with the soak book | — | — | overlap read | — |

**Feeds.** P7 -> P3: a daily long-only crypto leg overlaps the 4h trend legs on direction; the P3 overlap read decides. P7 -> P1: exit processing if it reaches a re-entry case.

## Programme review 2026-10-21 (lane RESEARCH-PROGRAMME-REVIEW-1021)

Population: the eleven ef5d units (RQ-20261018-ef5d-01..-11), graded 2026-10-20.

**Frontier (MEASURED, P7-Q1 closed).** Long arm (ef5d-01, PASS): all 14 (bar x hold) cells at 4h and 1d, holds 1-30 bars, are
cost-viable on >= 3 of the 6 core perps; shortest viable long-arm bar is 4h for every perp and ETF (MES 1d). Short arm (ef5d-02,
PASS): shortest viable bar is **15m for ADA, AVAX, SOL** and **30m for BTC, ETH** (median cost 0.07-0.09 R); 5m only for GDX/SLV.
No perp is viable below 15m, so the 1m discovery arm (blocked/RQ-20260930-505) stays blocked.

**Stage-0 results.** Daily Donchian PASS (ef5d-03: D55 0.42 R/trade n 179, D20 0.27 n 256); weekly Donchian on ETFs PASS (ef5d-05,
LO 0.41 n 312); regime-filtered daily PASS with best arm LONG (ef5d-06: 0.51 n 216 vs unfiltered 0.27); daily pullback FAIL
(ef5d-04); 1h compression breakout FAIL (ef5d-08); 1h sweep reversal FAIL (ef5d-09).
**Instrument error:** ef5d-07 (30m cost-gated, INDETERMINATE) and ef5d-06's VOL50 arm passed `--vol-skip-below-pctl 50/75/90`; the flag
is compared to a 0-1 rank, so those arms measured only warm-up entries. The harnesses now refuse it; re-asked as
RQ-20261021-7c2b-01 (30m) and -02 (daily VOL50/VOL75).

**Closed:** P7-Q3 (daily pullback FAIL; the daily horizon stays open on Donchian), P7-Q8 / P7-Q9 (1h squeeze and 1h sweep
configurations closed; untested variants -- ADX chop gate, 2-bar confirm, 15m -- are low priority after the frontier put 1h
breakouts at the margin).

**Next 3-4 weeks (pre-registered this review):** 7c2b-01 (30m gate re-ask), -02 (daily vol floor re-ask), -03 (LONG filter transfer
to BNB/DOGE/LINK/LTC/BCH/DOT), -04 (D55 transfer to the same six; P7-Q6's overlap read now waits on it), -05 (15m cost-gated
breakout on ADA/AVAX/SOL). ef5d-10/-11 stay blocked on TF-ORB-COST-STACK and TF-IGNITION-HARNESS.

## 0. Operator direction (2026-10-18, relayed by the manager, paraphrased closely)

The **lowest-priority** research theme, but plan it now and get tests into the queue soon. Test different time frames on the frontier end:

- **(a) Longer horizons** — daily bars with holds of several weeks: can large P&L per trade be extracted (trend / momentum / position trading, regime-filtered)?
- **(b) Shorter horizons** — mostly **new** strategies, not refinements: breakout-style entries that anticipate a jump or drop and catch just that wave, where the expected move per trade clears the full fee + slippage stack (fees dominate at short horizons). Different breakout families: volatility-compression breakouts, range / opening breakouts, momentum ignition, liquidity-sweep reversals.
- Build on the prior short-horizon work rather than repeating it.

## 1. End goal and measure

**Goal.** Know, per venue and symbol the books trade, which horizons a trade can pay on net of the full cost stack, and whether any of the two arms' strategy families clears Stage 0 there with fold consistency and breadth across symbols. A pass here is a **lead** for an overlap read against the live legs and then a re-entry case under `MD-PROMOTE-S0-S1`; this programme never changes a roster.

**Measure.** Two numbers per cell, both from committed records:

| measure | population | instrument | baseline (2026-10-18) |
|---|---|---|---|
| **Cost in R per trade and break-even coverage** per (symbol, bar, hold): `cost_r_median` (fee + slippage + funding against a 2.5 × ATR14 stop), `p_mv_ge_2cost` (how often the market's move over the hold is at least twice the round trip), graded viable / marginal / dead | the six Bybit perps (Binance USD-M proxy), 14 Alpaca ETFs, 3 IBKR futures proxies; bars 1m..1w; holds 1..48 bars | `timeframe_breakeven.py --arm long|short` (`RQ-20261018-ef5d-01` / `-02`) | **not measured on `main`.** Smoke this lane (one symbol each, not the registered grid): ETHUSDT 5m, 29 d — cost 10.5 bps, median stop 42 bps, `cost_r` 0.25, marginal at hold 1, dead at 6–48; SPY 1d/1w, 20 y — `cost_r` 0.018 / 0.007, viable at every hold (`scratchpad` runs 2026-10-18, not committed) |
| **Net R per trade, R per capital-day and hold-days** per Stage-0 cell and pooled, net of the full cost stack, 6 calendar folds, breadth over powered cells, Holm reported | per unit: the six perps on 1d (Q3, Q5) or 30m–1h (Q7–Q9); 17 equity/futures symbols on 1w (Q4) | `harness_stage0.py` (every arm's argv is `regime_debt_matrix.build_harness_cmd` on a synthetic cfg, so the cost stack is the harness's own) | **none.** No crypto daily-bar or weekly-bar record exists (`IR-CRYPTO-DAILY-TREND`, re-read 2026-10-18). Smoke: ETHUSDT 1d Donchian-20, 2025-09..2026-10, 3 trades, +3.87 R, mean hold 97 d; SPY 1w Donchian-20 long-only, 2006–2026, 17 trades, +12.9 R, 4/6 folds, p 0.056 — underpowered alone, hence pooled designs |

The headline measure of the research map (net P&L per capital-day, per strategy) is reported on every Stage-0 cell as `net_r_per_capital_day` and `hold_days_mean`, so "large P&L per trade" is read as R per trade **and** the capital-days it took, never off a book.

## 2. What is already known (do not re-run)

| finding | record |
|---|---|
| At taker cost, no ≤1h cell of trend / pullback / squeeze / fade / fvg_range / chop_scalp at live or default params survived a 2021–2024 screen on five perps; the only Stage-A survivors were ict_scalp cells, later voided by the lookahead fix | `RQ-20260930-504` (FAIL, K=90), its 1m arm `blocked/RQ-20260930-505` |
| Maker (post-only) entries do not rescue the causal 15m ict_scalp book | `RQ-20261016-1fa6-07` (FAIL, two passes) |
| 5m–15m trend/pullback/squeeze on alts at taker cost is a dead configuration class (−783 to −878 R); trend at 1h passed 10/13 alts on 3 years **without** folds or multiplicity correction | 2026-10-06 batch `RQ-20261006-005..031`; [idea-family review 2026-10-16 § 16](../idea-family-review-2026-10-16.md) |
| ICT concepts (FVG / order blocks / sweeps) have no independent evidence; retired as an edge source. The failed-breakout **fade** is a different, documented mechanism and stays open | idea-family review § 13; `fade_breakout_4h` is a live shadow leg |
| Regime tests so far were binary skips on 2h–4h legs; hot-vol skips cut trend's payoff | idea-family review § 11, row `IR-VOL-TARGET-SIZING-STAGE0` |
| Crypto time-series momentum lives at 1–4 week horizons (outside, primary); equity/commodity trend at 1–12 months | Liu-Tsyvinski 2021 RFS; Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen (cited in `IR-CRYPTO-DAILY-TREND`) |
| `backtest_orb.py` models fees in points, no slippage/funding, RTH-only; out of every corpus | CLAUDE.md § D1; `TF-ORB-COST-STACK` |
| Every crypto entry is a Market order; no post-only route exists in `src/` | [hyro feasibility memo 2026-09-30 § 2](../hyro-strategy-feasibility-2026-09-30.md) |

## 3. Questions, in dependency order

```
Q1 break-even LONG ──▶ Q3 daily crypto trend/pullback ──┬──▶ Q5 regime-filtered ──▶ Q6 overlap vs live legs ──▶ re-entry case
                   └─▶ Q4 weekly ETF/futures trend ──────┘                               (MD-PROMOTE-S0-S1, holdout confirmation)
Q2 break-even SHORT ─▶ Q7 cost-gated 30m breakout ──┐
                     ─▶ Q8 compression breakout, catch-the-wave exit ──┤──▶ confirm across bars ──▶ soak candidate record (Tier-3 wiring)
                     ─▶ Q9 liquidity-sweep reversal ──┘
                     ─▶ Q10 ORB (TF-ORB-COST-STACK) · Q11 ignition (TF-IGNITION-HARNESS) · Q12 clock (IR-INTRADAY-SEASONALITY-HARNESS)
                     ─▶ Q13 equity intraday bars (TF-EQUITY-INTRADAY-BARS) · Q14 maker-cost frontier (only if Q2 FAILS)
```

| Q | arm | question | why now | unit / node |
|---|---|---|---|---|
| **Q1** | A | At 4h / 1d / 1w bars and holds of 4 h .. 30 weeks, what move per trade clears the full cost stack on every venue/symbol we trade, and how often does the market deliver it? | Decides which long horizons can pay before a strategy is tried; gives the move distribution the trend units' R per trade is read against | `RQ-20261018-ef5d-01` (runnable) → `P7-Q1-frontier-read` |
| **Q2** | B | Same at 1m / 5m / 15m / 30m / 1h bars and holds of 1 min .. 2 days: where is the cost wall, and is any sub-hour horizon viable at taker cost on half the perps? | Fees dominate short horizons; the 2026-10-16 review retired a class on a wall nobody had measured per horizon | `RQ-20261018-ef5d-02` (runnable) → `P7-Q2-frontier-pass` / `-fail` |
| **Q3** | A | Does daily-bar Donchian trend (20 / 55) or the trend-pullback family (frac 0.5 / 0.618) clear Stage 0 pooled across the six perps, 2020–2026, with fold consistency and breadth? | The two real-money families lifted to the horizon the outside evidence names; no crypto daily record exists | `RQ-20261018-ef5d-03` (Donchian), `-04` (pullback) → `P7-Q3-*`, `P7-Q6-daily-*` |
| **Q4** | A | Does weekly-bar Donchian-20 (long-only vs both) clear Stage 0 pooled across 17 equity / futures symbols, ~2006–2026? | Months-long holds on the equity book; a single symbol gives ~17 trades in 20 years, so the design pools | `RQ-20261018-ef5d-05` → `P7-Q4-*`, `P7-Q6-weekly-etf` |
| **Q5** | A | Does a regime filter (ADX ≥ 20, ATR percentile ≥ 50, long-only) raise net R per trade on daily crypto position trades by ≥ 0.10 R vs unfiltered? | The operator's "regime-filtered"; every regime test so far was a skip on 2h–4h legs | `RQ-20261018-ef5d-06` (after `-03`) → `P7-Q5-*` |
| **Q6** | A | For any long-arm PASS: how much of it is the live 1h/2h/4h/1d legs' bet already (same symbols), and what re-entry case follows? | A daily Donchian on ETH overlaps `trend_donchian_eth_4h`; a pass that is one bet twice is not breadth | `P7-Q6-daily-donchian`, `-daily-pullback`, `-weekly-etf` (authored on a PASS) |
| **Q7** | B | Does a vol-percentile gate (≥ 50 / 75 / 90) lift a 30m Donchian breakout over its cost by ≥ 0.05 R per trade vs ungated? | The cost-aware entry condition in harness form: cost is fixed bps, R scales with ATR | `RQ-20261018-ef5d-07` → `P7-Q7-*` |
| **Q8** | B | Does a catch-the-wave exit (fixed 1.5R / 2R + 12-bar time stop) beat trailing the 1h volatility-compression breakout by ≥ 0.05 R per trade? | Squeeze has only ever been run with a trail; the untested variable is the exit geometry | `RQ-20261018-ef5d-08` → `P7-Q8-*` |
| **Q9** | B | Does a sweep-depth floor (pierce ≥ 0.25 ATR; far-side or 1R exit) lift the 1h failed-breakout fade over its cost by ≥ 0.05 R per trade? | The documented reversal mechanism, never run at 1h or with a pierce floor | `RQ-20261018-ef5d-09` → `P7-Q9-*` |
| **Q10** | B | Does an opening-range breakout on crypto perps (00:00 UTC and 13:30 UTC opens, 3 / 6 five-minute bars, flat at session end) clear Stage 0 pooled? | A named breakout family; blocked on the ORB harness's cost stack | `blocked/RQ-20261018-ef5d-10`, row `TF-ORB-COST-STACK` |
| **Q11** | B | Does a momentum-ignition bar (range ≥ 2–3 × ATR, volume z ≥ 2) entered on its close with a 1R stop / 1–1.5R target / 8-bar time stop clear Stage 0 pooled on 15m? | A named breakout family with no harness | `blocked/RQ-20261018-ef5d-11`, row `TF-IGNITION-HARNESS` |
| **Q12** | B | Do the documented UTC time-of-day effects (BTC 21–23 UTC, intraday TSMOM) carry a clock-entry strategy net of cost? | Already filed with a first-step design; not duplicated here | row `IR-INTRADAY-SEASONALITY-HARNESS` (carried) |
| **Q13** | B | Can the equity / futures short arm be measured at power below 1h at all? | Yahoo serves ~60 d at 5m/15m; a data lane is a build | row `TF-EQUITY-INTRADAY-BARS` (carried) |
| **Q14** | B | If no sub-hour horizon is viable at taker cost, which cells flip viable at maker-entry cost with a fill-rate haircut — and is a post-only route the next build? | The short arm's lever is then cost, not entry | `P7-Q14-maker-frontier` (authored only on a Q2 FAIL) |

## 4. Test ladders and the rules registered on the units

All Stage-0 units share one grader (`harness_stage0.py`, thresholds passed as flags and spelled out in each unit's `decision_rule.rule`):

- **Cell**: pass iff n ≥ `n_floor` AND net R > 0 AND ≥ `fold_majority` of 6 calendar folds net > 0; indeterminate iff n < `n_floor` (never FAIL on thin n).
- **Arm**: pass iff pooled n ≥ `pooled_n_floor` (39 for the daily/weekly units, 88 for the sub-hour units — the `RQ-20260930-504` floor) AND pooled net R > 0 AND pooled folds ≥ 4/6 AND at least half the **powered** cells pass (breadth: the pooled edge is not one symbol's); indeterminate iff pooled n is thin, fewer than two cells are powered, or fewer than half the declared cells measured (a fetch or harness fault is recorded per cell, never dropped).
- **Candidate vs baseline** (Q5, Q7, Q8, Q9): a candidate arm must also beat the baseline arm's pooled net R per trade by the unit's materiality bar (0.10 R daily, 0.05 R sub-hour). The baseline arm never carries the verdict.
- **Holm**: one-sided t p-values per cell are Holm-corrected across the arm and **reported**; no unit gates on them.
- **Every arm is fixed before the run.** A PASS from a multi-arm unit is a **lead** (programme 03 rung S0-C): its confirmation is a **transfer** (another bar, another asset class, another family's pool) with no re-selection, named on the tree node; a FAIL closes the configuration on its window, never the family (idea-family review negative-result protocol).
- **Candles**: Binance USD-M (keyless, a proxy for Bybit linear, prices track within a few bps) and Yahoo (`yfinance==1.7.0` on the runner; 1d uncapped, 1h ~730 d, 5m/15m ~60 d → `short_window` frames); every record names its data window and the cost stack it charged. Funding is a directionless magnitude (`execution_costs` P1).

**Break-even grade** (Q1/Q2, `timeframe_breakeven.py`): per (symbol, bar, hold) `viable` iff median `cost_r` ≤ 0.10 AND P(|move| ≥ 2 × cost) ≥ 0.50; `marginal` iff `cost_r` ≤ 0.25; else `dead`. Arm PASS iff a cell is viable on at least half the measured perps; FAIL iff none is viable anywhere; INDETERMINATE iff coverage of the grid is thin. Report-only columns: maker cost (fee 0), prop cost (ETH/SOL under the DXtrade stack).

## 5. Backlog — the next 3–4 weeks

| week | research (units) | builds (rows) | decision points |
|---|---|---|---|
| **W1** (to 2026-10-25) | `ef5d-01` and `-02` land (break-even frontier); `-03/-04/-05` fire once `-01` is measured; `-07/-08/-09` once `-02` is | `TIMEFRAMES-PROGRAMME` (this PR, hold) | the frontier: which horizons are viable, marginal, dead per symbol (`P7-Q1-frontier-read`, `P7-Q2-frontier-*`) |
| **W2** (to 11-01) | `-06` (regime-filtered) after `-03`; the first PASS/FAIL nodes authored from the tree (`P7-Q3-*`, `P7-Q7..Q9-*`) | `TF-ORB-COST-STACK`, `TF-IGNITION-HARNESS` (Tier-1; promote `ef5d-10/-11` when they land) | any long-arm PASS → the overlap read (Q6) before anything else |
| **W3** (to 11-08) | transfer confirmations for any short-arm PASS (15m and 1h / 30m and 4h); the maker-cost frontier (Q14) only if `-02` FAILED | `TF-EQUITY-INTRADAY-BARS` (data lane) | first soak-candidate record, or "no horizon clears" with the records as the reason |
| **W4** (to 11-15) | re-read: did the frontier predict the Stage-0 outcomes (dead horizons failing, viable ones passing)? If not, the break-even thresholds are the finding, re-registered as a new unit, never edited in place | — | weekly programme review re-cuts W5+ |

## 6. Instruments, gaps and what was filed

| instrument / gap | state (2026-10-18) |
|---|---|
| `scripts/research/timeframe_breakeven.py` | **new this lane**; `--self-test` passes; smoke on real ETHUSDT 1d/5m and SPY 1d/1w candles |
| `scripts/research/harness_stage0.py` | **new this lane**; `--self-test` passes (end-to-end on the 5,001-bar fixture, two arms, a planted fetch failure); smoke on ETHUSDT 1d (two arms) and SPY 1w (long-only). Delivers the FIRST STEP of `IR-CRYPTO-DAILY-TREND` (noted on that row) |
| ORB harness cost stack + UTC sessions | row **`TF-ORB-COST-STACK`** (Tier-1), unit `blocked/ef5d-10` |
| momentum-ignition harness | row **`TF-IGNITION-HARNESS`** (Tier-1), unit `blocked/ef5d-11` |
| equity / futures sub-hour candle lane | row **`TF-EQUITY-INTRADAY-BARS`** (Tier-1; Dukascopy coverage of the 17 symbols is UNVERIFIED) |
| `same_symbol_head_to_head.py` on a synthetic (non-roster) leg for Q6 | **not verified this lane** — the Q6 nodes say to file the instrument gap if it cannot take one |
| theme `timeframes` (weight 1) in `research/THEMES.yaml`; milestone `L-TIMEFRAMES` in `docs/roadmap/milestones.yaml` | added this lane; the fair-share test's invariants (prop strictly top, macro at the floor) hold with the new theme tied at the floor |

## 7. What this programme does not do

- It changes no config, roster, account, risk setting or order path. A PASS anywhere is a lead for an overlap read and then a re-entry case built as a new evidence record through the manager; the soak and promotion ladder (`OPERATING-PLAN § 2`) is unchanged.
- It does not retire any horizon or family on one FAIL; the tree's fail nodes name what was not tested and the negative-result protocol decides.
- It does not measure equities below 1h at power until `TF-EQUITY-INTRADAY-BARS` lands, and it does not run ORB or ignition until their harnesses carry the cost stack.
- It does not re-run the ≤1h discovery grid, the maker-entry scalp test or the 5m–15m alt screens; it cites them.
