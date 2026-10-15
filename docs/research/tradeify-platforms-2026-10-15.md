# Tradeify non-crypto instruments on tradeify_1: what is listed, what we can map (2026-10-15)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-15` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane TRADEIFY-PLATFORMS · measured 2026-10-15 · read-only; no order control touched.

Question (operator 2026-10-09, re-asked 2026-10-15 "Yes"): can our existing strategies trade Tradeify's **non-crypto** instruments?
**Row correction:** `tradeify_1` is Tradeify 247's **DXtrade crypto-CFD** account (`dx.tradeify247.co`), not "the futures account".
The row's guess of "forex and options" is **not supported**: the terminal's watchlist category tabs read `All · Cryptocurrencies · Stocks`
(MEASURED, every probe dump below) and no forex or options symbol was found. The separate Tradeify *futures* brand (Tradovate) was not examined.

## 1. What the tradeify_1 terminal lists (MEASURED through the existing read-only adapter)

Method: `system-actions` → `breakout-login-check account: tradeify_1, apply: instrument-page-dump` (types the query **key by key** into the
watchlist search, dumps the visible leaves, clicks nothing; reused saved session). Positive control first: `ETH` returned ETH/USD, ENA/USD, ETC/USD
with descriptions and `Cryptocurrencies` (#18393).
**Retraction:** the first probe (#18391, `instrument-probe`, `fill()`-typed, 17 symbols) returned empty suggestion rows. The adapter's own notes
(#15472) say `fill()` leaves the suggestion tbody empty, so **those negatives are not evidence**; only the key-by-key dumps below count.

| Terminal symbol | Terminal description | Asset class shown | Source | Our proxy |
|---|---|---|---|---|
| `SILVER/USD` | Silver, Futures priced in USD (synthetic perp via Hyperliquid) | Stocks | #18395 | SLV |
| `XYZ100/USD` | Nasdaq-100 Index priced in USD (synthetic perp via Hyperliquid) | Stocks | #18398 | QQQ |
| `SP500/USD` | S&P 500 Index priced in USD (synthetic perp via Hyperliquid) | Stocks | #18399 | SPY (MES) |
| `USOIL/USD` | Crude Oil (WTI) priced in USD (synthetic perp via Hyperliquid) | Stocks | #18401 | USO (poor proxy: futures-roll ETF) |
| `UKOIL/USD` | Brent Crude Oil priced in USD (synthetic perp via Hyperliquid) | Stocks | #18401 | none in corpus |
| `PAXG/USD` | PAX Gold token vs USD | Cryptocurrencies | #18397 | GLD (not tested; token, 24/7) |
| `CRCL/USD`, `ORCL/USD`, `GOOGL/USD` (seen incidentally) | single stocks (synthetic perp via Hyperliquid) | Stocks | #18400 | none: no single-stock harness evidence |

Not found: a gold *index* perp (query `Gold` returned only PAXG). **Limits:** the search shows only the first ~4 rows per query and matches
symbol/name prefixes (a `synthetic` query returned 0 rows, #18396), so the list above is a **lower bound, not the catalogue**; "not found"
means not seen, not absent. Forex (`EUR`, `GBP`, `XAU`, `XAG`, `US500`, `US100` were only tried with the invalid `fill()` probe): **UNVERIFIED**.

## 2. Costs, leverage, swap, hours: what is and is not known

| field | value | status |
|---|---|---|
| Commission | 0.04% per trade (8 bps round trip) | firm rule page, first-party summary 2026-09-30, `unconfirmed: true` (`config/prop_rulesets/tradeify_247_1step.yaml`) |
| Swap/funding | 0.033% of position value per day | same source; whether it applies to the Hyperliquid synthetics is **unmeasured** |
| Leverage | 2:1 for indices/stocks (5:1 BTC/ETH only); metals/oil not named, strictest reading 2:1 | same source |
| Hours | synthetic perps; hours **unmeasured** | none |
| Spread / bid-ask per instrument | **not obtained**: the dump masks digit runs by design, and the instrument-info panel is reachable only after a watchlist add | gap |

Why the gap: per-instrument terminal specs need the symbol in the watchlist (`add-watchlist-symbol`, a UI mutation) before
`instrument-info-probe` can open its info panel; the lane's brief was READ-ONLY, so it stopped there. Filed as checklist row `TRADEIFY-INSTR-SPECS`.
The units below therefore use the **declared** stack plus a **declared** 3 bps slippage and say so.

## 3. Strategy → instrument mapping, and evidence state

| Our evidence | Maps to | State |
|---|---|---|
| `fade` on SLV 1h, RQ-20261006-031 **PASS** (Stage 0) | SILVER/USD | priced at Alpaca-ETF costs on ~720d only; expectancy +0.05R/trade, win rate ~23%, **max drawdown 19-21R against +6.7..+7.6R total** (research/results/RQ-20261006-031/). At 0.5% risk a 19R drawdown is ~9.5% of the account vs Tradeify's 6% static floor, so survival, not edge, is the open question. No follow-on existed. |
| qqq_trend_long_1d (live Alpaca, n=8); QQQ 1h pullback **FAIL** (RQ-20261006-029) | XYZ100/USD | daily trend leg untested on long history |
| spy_trend_long_1d (n=11), spy_pullback_1h (n=61); SPY squeeze/orb **FAIL** (RQ-...-030/-033) | SP500/USD | live-parameter legs untested on long history |
| uso_trend_1h (n=56, only positive point estimate in RQ-20260928-013, flagged poor proxy); USO 1h pullback **FAIL** (RQ-20261006-032) | USOIL/USD | live leg untested on long history |
| gld_pullback_1h/1d | PAXG/USD only | **no unit**: a token that tracks gold with its own premium/liquidity; no PAXG spread known; revisit after TRADEIFY-INSTR-SPECS |
| tokenized single stocks, forex, options | listed/unverified | **no unit**: no harness evidence on single names; forex and options not seen on this terminal |

## 4. Units authored (hold; the manager merges) and why these five

`RQ-20261015-24ca-01` (lead: SLV fade → SILVER) through `-05` (see `research/queue/`). Each runs the harness at the **live leg's own parameters** on the
trainer's multi-year candles (SLV/SPY/QQQ/USO 1h to 2026-06-18, 8-9 years; verified #18392) with Tradeify's declared costs, then
`prop_ev_grid.py` (5 seeds, `tradeify_247_1step.yaml`, flat 0.5%, `--lev-cap leg=2`, `--no-hedge`). Rule registered before any run: PASS needs
n ≥ 88 and ev > 0 on all seeds and P(net>0) ≥ 0.70 on all seeds. Each unit states the operator's rule: Stage 0, then a soak (live prop trading counts),
then cost fidelity, **plus** prop DD survival; a PASS here moves none of the other three and edits no roster. Routed `compute: needs_vm_data` → trainer
(dry-run router: `RQ-20261015-24ca-01 would_dispatch route=trainer`); the candles are not in `metis-market-data`, so Kaggle-CPU cannot serve them.

Honest expectation, stated before the runs: the SLV fade has +0.05R expectancy and the 8 bps commission alone is a material fraction of that on a ~1% stop,
so a FAIL at Tradeify costs is the likelier outcome. The unit exists to find out cheaply, not to promote.
