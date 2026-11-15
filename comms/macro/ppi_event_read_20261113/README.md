# PPI pre-event read — 2026-11-13 (US PPI, 13:30Z)

Work item: `PPI-EVENT-DESK-20261113` (operator ask, relayed by the manager 06:50Z). Read-only research; no order, no config change.
Gates this adds or changes: none.

## Inputs (provenance)

- **Surprises:** `ppi_surprises.json`. Source: the Bigdata.com economic calendar (US, inflation), pulled 2026-11-13 ~07:00Z. Surprise = actual − consensus, in pp.
  - 23 releases from 2024-10-11 to 2026-10-15 (2026-01-14 appeared twice; the copy with null surprises was dropped).
  - The repo's own `econ_calendar_snapshots.jsonl` carries consensus for only 4 PPI releases (2026-07..10), too few to use.
- **Bars:** hourly OHLC already committed under `comms/research/RQ-2026101[8]/22/26-*/data/*_60.csv`.
  - ETFs and CME micros: 2024-10-21 .. 2026-10-16.
  - Crypto: 2020 .. 2026-10-22/26.
  - Not re-fetched: from the cloud container Yahoo answers 429 and Bybit 403.
- **Cost:** a flat ESTIMATED round trip per symbol (2–6 bps ETFs/micros, 12–14 bps crypto). This is not the repo cost stack. Every net number here is ESTIMATED.
- **Script:** `scripts/research/ppi_event_read.py ppi_surprises.json result.json` regenerates `result.json` byte-identically.

## Measures (per symbol, n = 23 ETF/micro releases, 24 crypto)

1. **Reaction:** prior close → close of the first bar starting at or after the release time.
   - ETFs: the 12:30/13:30Z releases are pre-market, so the first bar is the RTH open bar (median 1.5 h after the release) and includes the overnight move.
   - 24h venues (MGC, MHG, crypto): the release-hour bar.
2. **Vol ratio:** median |reaction| ÷ median |same-measure| on non-event weekdays at the same clock hours.
3. **IC:** Spearman(surprise, reaction).
4. **Tradable continuation:** enter at the close of that first bar, exit +4 h or +24 h.
   - *follow* = trade in the first-bar reaction's direction; *fade* = the opposite; *surprise-signed* = trade in the sign of the core MoM surprise (n = 20 non-zero).
   - All net of the ESTIMATED cost.

## Results

| sym | vol ratio | IC hl→react | IC core→react | follow 24h net bps (t) | surprise-signed 24h gross (n=20) |
|---|---|---|---|---|---|
| GLD | 1.01 | −0.52 | −0.59 | +50 (1.06) | −74 |
| GDX | 1.35 | −0.46 | −0.58 | +145 (2.28) | −140 |
| IAUM | 0.98 | −0.52 | −0.59 | +49 (1.04) | −74 |
| SLV | 0.87 | −0.17 | −0.28 | +146 (1.40) | −222 |
| TLT | 1.06 | +0.02 | +0.04 | −14 (−0.71) | −43 |
| QQQ | 1.07 | −0.13 | −0.08 | −1 (−0.02) | −64 |
| SPY | 0.92 | −0.20 | −0.16 | −3 (−0.13) | −56 |
| USO | 1.05 | +0.53 | +0.57 | −92 (−1.50) | −35 |
| MGC | 1.78 | −0.40 | −0.34 | +68 (1.41) | −70 |
| MHG | 1.39 | −0.47 | −0.40 | +13 (0.34) | −54 |
| BTC | 1.26 | −0.49 | −0.32 | −26 (−0.78) | −51 |
| ETH | 1.28 | −0.64 | −0.47 | −12 (−0.17) | −96 |
| SOL | 1.14 | −0.67 | −0.51 | −110 (−1.62) | −83 |
| XRP | 1.27 | −0.59 | −0.46 | +199 (1.70) | −114 |
| ADA | 1.59 | −0.59 | −0.45 | −52 (−0.50) | −85 |

Full table, including 4 h horizons and fade arms, in `result.json`.

## What the evidence says

- **Direction (measured, n = 23–24):** a hot PPI print moves gold, gold miners, copper and crypto DOWN, and oil UP, in the release bar.
  - Spearman |IC| is 0.46–0.67 on the headline MoM surprise for metals and crypto. For n = 23, r = −0.59 gives t ≈ −3.4.
  - TLT and equity ETFs show no reliable reaction sign (|IC| ≤ 0.2).
  - That move is over by the time an hourly bot can act on it.
- **No tradable setup clears the bar.** Of the 60 continuation arms (15 symbols × follow/fade × 2 horizons), one has |t| > 2: GDX follow 24 h, t = 2.28, n = 23. Its mirror (fade, t = −2.40) is the same test.
  - With ~3 expected false positives at |t| > 2 across 60 looks, and no rule registered before the run, this is a LEAD, not evidence.
- **Surprise-signed entries after the first hour lose on every symbol** (gross −10 to −222 bps at 24 h, n = 20). The released information is priced inside the first bar.
  - "Buy the hot print in oil / sell it in gold, an hour late" has no edge here.
  - That is one cross-asset pattern on 20 dates, not 15 independent results.

## Recommendation

**No trade around the release.** Nothing here clears a rule registered before the run (OPERATING-PLAN § 2). The one candidate (GDX 24 h follow) goes to a pre-registered unit instead, with its rule fixed now:
- Population: PPI and CPI releases on the full available history.
- Rule: PASS iff net mean > 0 with a 95% CI lower bound > 0 at n ≥ 30.

## Exposure of the open book (live `/api/bot/positions?include_paper=true`, 2026-11-13 ~07:15Z)

21 positions, 1 real money; prop has no position telemetry.
- **The book is one-sided:** every metals position is short, every crypto position is short, plus a USO long and TQQQ/QLD shorts. It gains on a HOT print and loses on a COLD one.
- Today's consensus: headline MoM 0.4, headline YoY 6.6, core MoM 0.3, core YoY 5.0 (prior core YoY 5.0, prior headline MoM 1.3).
- Event move in R = (median |reaction|, or 2× median) ÷ stop distance.

| position | side | 1× / 2× median event move (R) | R to stop | adverse on |
|---|---|---|---|---|
| ib_paper TLT tlt_pullback_1d | long | 0.18 / 0.37 | **0.18** | either (no reliable sign) |
| alpaca_paper TLT tlt_pullback_1d | long | 0.19 / 0.38 | **0.32** | either |
| ib_paper MHG mhg_pullback_1d | short | 1.08 / 2.16 | 1.40 | cold |
| alpaca_paper SLV slv_trend_1h | short | 0.87 / 1.75 | 1.06 | cold |
| alpaca_paper USO uso_trend_1h | long | 0.68 / 1.35 | 1.29 | cold |
| alpaca_paper TQQQ / QLD ml_entry | short | 0.49 / 0.97, 0.48 / 0.95 | 0.70 / 0.87 | cold (weak sign) |
| bybit_1 SOL / BTC / ETH_prop / ADA_4h | short | ≤ 0.21 / ≤ 0.42 | 0.43–0.69 | cold |
| **bybit_2 ADAUSDT ada_pullback_2h (real money)** + its mirror | short | 0.23 / 0.47 | 2.34 | cold — a 2× move leaves ~1.9R of room |

- **Most exposed:**
  - the two TLT longs: the stop sits within one median event move;
  - MHG and SLV shorts: a 2× cold move exceeds the stop distance;
  - the bybit_1 crypto shorts: about 0.4R of room on a 2× cold move.
- **The real-money ADA short is not at risk from a typical PPI hour.**
- No real-money action is proposed. Paper legs keep their brackets: the floor exists to collect exactly this data.
