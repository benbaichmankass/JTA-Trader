# CF-INSIGHTS — what the counterfactual engine says, 2026-11-23

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane CF-FINISH-BACKFILL-20261123

Gates this adds or changes: none. Research memo; authorises nothing; no config touched.

**Population.** Extended counterfactual backfill, GitHub run 45227696759 (`cfb-20261123w`): 468,525 graded jobs → **396,152 unique trades**
(dedupe key symbol, timeframe, entry_time, side). Backtest-corpus trades re-simulated by `cf_core` at constant money risk (each arm's R is
in its own stop distance, so a wider stop is not more risk). Provenance **ESTIMATED**; CIs are week-block bootstrap. Aggregates:
`comms/research/cf_insights/2026-11-23/` (`insights_run_w.json`, `live_lens_run_w.json`). In-sample discovery: a ranking of where to look.

## 0. Corrections to earlier numbers (read first)

1. **Entry-side arms (+0.6R, 95% improved) were artefacts** — a collapsed risk denominator and signal-bar lookahead. Withdrawn; fixed by <!-- population-ok: withdrawn run-y figure quoted only to retract it -->
   keeping the bracket distances and entering at the bar close (`entry_at_bar_close`, with a test).
2. **The wide-stop effect on trend was mostly an artefact.** In run z (n = 16,546 of 185,000+ unique trend trades), 8.9% of trend trades were stopped on the signal bar by the same
   lookahead and supplied ~83% of the effect. On corrected run w the pooled trend_donchian effect is **+0.024R/trade** (3× stop, 3R TP,
   CI 0.005–0.044; n = 186,912 unique) against the ~0.14R the holdout units were built on. **The seven holdout units cf1a-01..07 are withdrawn
   before merge**; checklist row CF-TRENDDONCHIAN-WIDESTOP-HOLDOUT carries the note.
3. A "limit at 0.25 ATR" fill looks +0.11R on *filled* trades only because the fill selects pullbacks; the honest figure is net per signal:
   **+0.016R** (trend, n = 186,912 unique, fill rate 85% of them), +0.004R squeeze (n = 48,869), −0.003R pullback (n = 60,948). Nothing there.

## 1. Ranked findings (all in-sample, unique trades)

| # | Finding | Population | Effect | Caveat | Testing unit |
|---|---|---|---|---|---|
| 1 | ict_scalp_5m BTC: far stop+TP arm (3× , 6R) | n = 1,392 unique, 137 trades/yr live | +0.215R/trade, CI 0.117–0.307, ≈ +29R/yr | replay mean −0.32R: fidelity of ict_scalp replay is low-trust; 6R is a far target, not a *predictive* TP | none yet (needs a predictive-TP arm) |
| 2 | ict_scalp_eth_15m | live-frequency lens | +0.116R, CI 0.006–0.218, ≈ +17R/yr | same | none |
| 3 | trend_donchian ada/sol 4h | lens | +0.079R / +0.055R, lower bounds > 0 | ≈ 7 / 4 R/yr; below the pooled-power MDE for a single leg | none (family too small) |
| 4 | trend_donchian pooled, eth, BTC | 186,912 | +0.021–0.026R | real but tiny; R1 cost screen 0.05R/trade is larger than the effect | none |

Fade_breakout replay is low-trust (far/mid targets are not replayed), so its large round-trip and arm numbers are not ranked.

## 2. What this means for active management

**Round-trip census (b)** — trades whose MFE ≥ 1R that ended ≤ 0R (unique trades; **outcome-conditioned, so not an edge**):

| Family | Reached ≥1R | Round-tripped | Mean R given back |
|---|---|---|---|
| trend_donchian (186,912) | 45.2% | 19,711 = 23.7% of reached | 1.65R |
| squeeze_breakout (48,869) | 41.7% | 4,332 = 21.4% | 1.45R |
| htf_pullback_trend_2h (60,948) | 50.6% | 12,021 = 39.3% | 2.13R |
| ict_scalp_5m (1,392) | 31.8% | 255 = 58.4% | 4.09R |
| fade_breakout (88,731, low-trust) | 51.6% | 25,350 = 63.8% | 3.77R |

Per-live-leg census is in `insights_run_w.json` (`round_trip_census_by_leg`).

**Banking arms (c)** — the arms exist in the extended set (`runner_50pct_at_1R/2R`, `+be`, stop to 0R/0.5R at 0.5R/1R, giveback rules).
On the round-trippers they recover +0.6 to +0.8R each on trend — a conditioning artefact. **Whole-book, on all trades with MFE**, they are
**−0.001 to −0.009R/trade on trend** (the trades that round-trip are offset by winners cut short), **−0.02 to +0.02R on fade**, and
**+0.07 to +0.13R on ict_scalp_5m** (n = 1,375; low-trust replay). Reading: on the trend family, banking does not pay for itself; the R given
back is real but the same rules also cut the winners that run. The one place banking shows value is the structurally-stopped scalp leg.
Banking arms here keep the *declared* TP on the remainder only where the engine's `partial_at` rule did; they were not graded under
RULE-AM-RISK-ADJUSTED-V1 (R1–R3 per-trade screen not run — not done).

**Wide-stop arms (a)** — no arm in the extended set is a *predictive*-TP arm: `sl*_tp3R/6R` use fixed multiples, `notp`/`trail` arms are
**diagnostic only**. Per the redirect, none is a candidate; the withdrawn units are not re-registered because the effect (finding 2 above) is
too small to power a unit.

**Two-way conditional moves (d)** — not done. The engine can tighten on a stall (giveback/BE arms) but has no *loosen on a pullback while the
trend state holds* arm; that needs a trend-state flag per bar, i.e. the per-bar path emit below.

**Where momentum stops / early exits (LEAVES_R).** Stopped-out trend trades with MFE < 0.5R are post-exit "right" 41.6% of the time (n = 61,333 unique trend stop-outs with MFE < 0.5R)
(price went on in the trade's direction after the stop), and htf_pullback stops at ≥2R MFE leave +2.7R post-exit (84% exited early,
n = 16,177) — the strongest hint that a real predictive/extend-TP on pullback winners is worth a unit. Post-exit verdict is a
descriptive diagnostic, not a graded arm.

## 3. Unblock list (e)

Read from `research/queue/blocked/` (141 units; 15 P1 / structure / exit-path):

| Blocked on | Units | What the CF engine supplies now | Still needs |
|---|---|---|---|
| EXIT-PATH-EMIT-OFFLINE (state `landed_unproven`; `--emit-paths` exists in `backtest_trend.py`) | RQ-20261014-9807-04/-05, RQ-20261011-9da8-04, d6e7-01/-06 | `cf_core` has per-bar paths in memory (open_r, mfe_pre_r, mae_pre_r, bars_held) but does not emit bars_since_peak / ADX / ATR per bar | a parity test on the emit, then `git mv` + queued |
| STRUCTURE-FAMILY-EXPANSION | RQ-20261101-5e01-12..15 | structure arms are NOT in the CF arm set | a per-leg runner over `--structure-exit` (trend, pullback only; ict_scalp harness has no arm) |
| STRUCTURE-START-TP-ARM | RQ-20261104-5e05-01 | — | ~0.25 day flag + parity test |
| ML-STRUCTURE-UNIT-RUNNER | RQ-20261101-5e01-09..11 | — | a runner (checklist row missing — filed below) |
| HARNESS-BE-RANDOM-CONTROL | RQ-20261029-1f39-01 | BE arms (`stopto_0R`, `_be`) exist in CF; matched random trigger control does not | 100 seeded matched-rate triggers per X |
| continuation replay for widen_sl / tp_extend | RQ-20261113-ed2b-02/-04 | `cf_core.simulate` is a continuation replay past the recorded exit, fidelity v2 (mechanics ≥ 80%, price net of slippage) | its fidelity control is registered at 0.05R on ≥ 90%, stricter than RULE_V2 (mechanics 76–87%): not met, so stays blocked |
| harness flags | RQ-20261117-b3aa-06, RQ-20261118-abab-15 | none | owned by their lanes |

Honest read: the CF engine **can supply per-bar path rows and BE/giveback arms now**; it **cannot yet** supply structure-level arms or a
trend-state loosen arm. The largest unblock for effort is a bars_since_peak/ATR/ADX per-bar emit with a parity test.

## 4. Limits

- Corpus is backtest, not live; fidelity of the replay to the harness is 76–87% by RULE_V2 on matched trades, lower on fade/ict_scalp.
- 27,979 non-crypto jobs and 205 live packages remain unpriced (CF-NONCRYPTO-BAR-SOURCE).
- Nothing here is a promotion claim, a mandate, or a config change.
