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

### 2b. TRADEIFY-INSTR-SPECS attempt, 2026-10-15 ~20:08-20:16Z (the UNMEASURED cells below are superseded by 2c where it measured them) (lane TRADEIFY-INSTR-SPECS; operator "Yes, add and read" ~19:50Z)

**Watchlist adds: DONE and verified (MEASURED).** One `add-watchlist-symbol` run per symbol, each verified by the adapter: exactly one
suggestion row resolved, one click on its Symbol cell, Escape, **no order form and no dialog before or after, only that symbol added, nothing removed**,
one-click trading read OFF every time. Terminal watchlist after the last add: ETH, SOL, XRP (pre-existing) + the four below.

| Terminal symbol | Terminal description (from the resolved row) | Asset class | Dry run | Armed add (run) | Issue |
|---|---|---|---|---|---|
| `SILVER/USD` | Silver Futures priced in USD (synthetic perp via Hyperliquid) | Stocks | #18427 (38799454154) | 38799609093 | #18428 |
| `XYZ100/USD` | Nasdaq-100 Index priced in USD (synthetic perp via Hyperliquid) | Stocks | n/a | 38799769017 | #18430 |
| `SP500/USD` | S&P 500 Index priced in USD (synthetic perp via Hyperliquid) | Stocks | n/a | 38799959539 | #18432 |
| `USOIL/USD` | Crude Oil (WTI) priced in USD (synthetic perp via Hyperliquid) | Stocks | n/a | 38800165762 | #18433 |

(Only SILVER had a separate dry run; the other three went straight to the armed mode, whose own guard refuses unless exactly one row matches.)

**Info-panel read: NOT OBTAINED.** `instrument-info-dry` over all four (#18434, run 38800387543) resolved all four watchlist Symbol cells as clean
(1 row each, no control in the cell, not in an order panel) and read one-click OFF, no dialogs, but **refused**: `0 visible instrument_info_button
(need exactly 1)`, and `working_orders: 0 widget_menu_ORDERS (need exactly 1)`. Cause, from the code and the dump: `probe_instrument_info`
(`src/prop/platform/dxtrade.py`) finds the info button as the control beside a `symbol_input` in a symbol-linked widget header (the breakout_1 layout,
#14551), and its flat guard needs an Orders widget. tradeify_1's workspace holds only a Watchlist widget and a Positions widget (`widget_menu_WATCHLIST`,
`widget_menu_POSITIONS`), so neither exists. No click was made, so nothing was left changed (watchlist diff: none).

| field (per instrument) | status | why |
|---|---|---|
| spread / bid-ask at read time | **UNMEASURED** | the info panel is unreachable (above); the watchlist row does carry Bid/Ask columns, but the public dump masks digit runs by design, so no existing read-only mode can return a number |
| swap long / short, leverage / margin, contract size, min quantity and step, trading hours, commission | **UNMEASURED** | info panel unreachable |
| firm-declared figures | unchanged, `unconfirmed: true` | section 2 table above |

**Re-pricing: none done, none warranted.** There is no measured cost that differs from the declared stack (8 bps commission round trip + 3 bps declared slippage
+ 0.033%/day swap), so RQ-20261015-24ca-01..05 are untouched. Note: `-01` had already run (verdict `fail`, last_dispatched 17:57Z) and `-02` was dispatched at 19:14Z
before this lane started, so re-costing them would not have been a pre-run edit in any case.

**What would obtain the numbers (a build, not a re-run; Tier-2, needs the manager/operator):** the existing modes cannot, and each way forward touches more
than the "watchlist + info panel only" the operator approved. (a) A new read-only adapter mode that dumps the watchlist row's hover/context controls to find
how this terminal opens its instrument info, plus a numeric-safe emit (spread as bps of mid, swap/leverage as named fields, not masked digit runs); or
(b) add a symbol-linked widget (a UI mutation not yet approved) so the existing probe's locator applies. Either needs a code PR before a run.


### 2c. TRADEIFY-INSTR-SPECS MEASURED, 2026-10-15 21:10-21:17Z (after #18438 merged; supersedes the UNMEASURED cells in 2b)

Two existing readers were extended (#18438), no widget was added: `quote-spread` (the executor's own `read_quote` off the watchlist) and the REST probe
(`velotrade-api-probe`, `account: tradeify_1`). Flat before the REST login: `instrument-info-dry` #18450 (run 38808197277, 21:13:55Z) read margin used 0.0 and an empty
Positions table; the REST portfolio then read positions 0, orders 0.

| field | SILVER/USD | XYZ100/USD | SP500/USD | USOIL/USD | ETH/USD (control) | source / status |
|---|---|---|---|---|---|---|
| quoted spread, bps of mid (median of 3 reads ~1 s apart; min-max) | 1.74 (1.74-1.74) | 1.00 (0.34-1.00) | 0.13 (0.13-0.13) | 1.04 (1.04-2.08) | 0.0 (0.0-0.0) | MEASURED, #18448 run 38807791311, 21:10:49-21:11:13Z, **one snapshot**; excludes slippage and impact |
| mid at read | 57.4 | 29,876 | 7,738 | 96.2 | 2,455 | MEASURED, same run |
| margin rate (flat) | 0.2 | **0.5** | **0.5** | 0.2 | 0.2 | MEASURED, account-scoped view: SILVER/USOIL/ETH in #18452 run 38808598907; XYZ100/SP500 in the re-run #18461 run 38812053334 (21:44:21-37Z, after #18454, no 429s). Leverage is **INFERRED** as 1/marginRate: 5:1 for SILVER, USOIL, ETH; **2:1 for XYZ100 and SP500** |
| min order / increment (units) | 0.01 / 0.01 | 0.01 / 0.01 | 0.01 / 0.01 | 0.01 / 0.01 | 0.01 / 0.01 | MEASURED (XYZ100, SP500: re-run #18461) |
| lot size / multiplier | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | MEASURED (global instrument view) |
| price increment | 0.001 | 0.01 | 0.001 | 0.01 | 0.001 | MEASURED |
| trading status | FULL | FULL | FULL | FULL | FULL | MEASURED (XYZ100, SP500: re-run #18461) |
| trading hours | open and close at 00:00Z every day Mon-Sun, i.e. continuous 24x7 in the schedule | same | same | same | same | MEASURED schedule; "continuous" and "no holiday gaps" are **INFERRED** (the row lists no holidays) |
| swap long / short, financing | **no field in the instrument row** | no field | no field | no field | no field | **NOT OBTAINABLE over REST**: the row's keys are assetClass, currency, description, firstCurrency, instrumentTreePath, lotSize, multiplier, pipSize, priceIncrement, quantityIncrement, symbol, tradingHours, type, version (global) and account, assetClass, marginRate, maxOrderSize, minOrderSize, minOrderSizeIncrement, symbol, tradingStatus, type (account). The 0.033%/day figure stays firm-declared, unconfirmed |
| commission | no field | no field | no field | no field | no field | NOT OBTAINABLE over REST; 0.04%/side stays firm-declared, unconfirmed |

Notes that change how to read the table:
- The REST symbols are the slashed form (`SILVER/USD`); the unslashed `SILVERUSD` returns no row. The probe tried both.
- ETH reads 0.0 bps in all three reads (bid equals ask). The four others read non-zero, so the parser does distinguish, but treat ETH's zero as "the watchlist showed equal bid and ask at that moment", not as a cost.
- The first REST run (#18452) hit HTTP 429 on 15 of its 40 GETs (back to back), which left XYZ100 and SP500 without the account-scoped margin rate and minimum order size. #18454 added a GET-only 1/2/4 s retry and a 0.3 s pace; the re-run #18461 (flat verified first by #18460, run 38811858513, margin used 0.0 and no working orders; REST portfolio positions 0, orders 0) returned both with no 429. Not a refusal of the instruments: their global rows came back.
- A first dispatch (#18451, run 38808388790) used the wrong issue key (`account_id:`; the key is `account:`) and so probed velotrade_1 instead: read-only, positions 0 and orders 0, nothing placed. It adds no tradeify_1 evidence.

**Versus the declared stack the units use** (8 bps commission round trip + 3 bps declared slippage + 0.033%/day swap, `--lev-cap leg=2`):
- Spread: measured 0.13-1.74 bps at one snapshot, below the 3 bps declared slippage, so the declared figure still covers the quoted spread. A single snapshot says nothing about off-hours widening or fill slippage, so it is **not** grounds to lower the 3 bps.
- Leverage: SILVER and USOIL show marginRate 0.2 (5:1 inferred), against the `2` the units cap them at (the firm page named 2:1 for indices and stocks and left metals and oil unnamed). That cap is part of each unit's pre-registered rule, not a cost input, so it was not touched; `RQ-20261015-ca42-01` (2d) tests SILVER and USOIL at 5. XYZ100 and SP500 show marginRate 0.5 (2:1 inferred), which **matches the cap of 2 the index units already use** (-02, -03, -04), so no index unit needs a leverage change.
- Commission and swap: unmeasured (no field in the REST row), so the declared values stand; accepted as firm-declared and UNCONFIRMED by the manager (2d).
- **No unit was edited.** RQ-20261015-24ca-01..05 are unchanged.

### 2d. Manager decisions on 2c (2026-10-15 21:20Z) and the follow-up unit

- Swap (0.033%/day) and commission (0.04%/side) are **ACCEPTED as firm-declared and flagged UNCONFIRMED** in every cost table: no data source for them exists from tradeify_1 (the REST row has no such field; the info panel cannot be opened).
- The leverage-cap question is a data task, not an operator preference. `RQ-20261015-24ca-01..05` stay untouched. One new pre-registered unit, **`RQ-20261015-ca42-01`**, re-runs the SILVER fade and the USOIL trend at `--lev-cap 5` (marginRate 0.2; 5:1 is **INFERRED** as 1/marginRate), with its rule written before the run, including a registered cap-binding reading (identical ev and p to the second decimal at cap 5 and cap 2 means the cap cannot be what decides the verdict). Only the SILVER row is auto-graded; the USOIL leg writes its own verdict under `uso/` and is read by hand under the same criteria, because the grader reads one `verdict.json` per run.
- Context for reading it: `-01` already graded FAIL at cap 2 (ev -15.7 to -27.4 per life, p_net_positive about 0.15, n=518), so a leverage change only matters if the cap actually bit.

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
