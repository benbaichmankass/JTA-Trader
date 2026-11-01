# Historical option / IV data — measured source inventory (2026-11-01)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `ETF-HISTORY-PIPELINE` (Manager Session 2026-11-01a), on operator direction 2026-11-01: *"there's no way we can't find
sources for historical data on publicly traded securities"*. Row `OPTIONS-IV-HISTORY-GAP`. **Buys nothing.**
Gates this adds or changes: none.

## How "reached" was measured

`Reached` = this lane's **sandbox** fetched the URL/API and read the stated fields on 2026-11-01 (a `curl`/`requests` call, stated
HTTP status). `Not reached` = the host answered but needs a key/purchase, or the sandbox could not connect. **"Not reached" is NOT
"does not exist"**: the sandbox sits behind a proxy; a runner may differ. `Vendor page` = figures read off the vendor's own pricing
page through a fetch tool today; not verified by a purchase or a sample. Alpaca/IB depth cannot be measured from a lane sandbox
(keys live in Actions secrets / on the VMs) so it is measured by the probe modes of the workflows below, not asserted here.

## A. Free / open — what we can actually have today

| Source | Depth | Symbols | Fields | Licence / cost | Reached? |
|---|---|---|---|---|---|
| **CBOE delayed-quotes CDN** `cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json` | **current chain only** (no history) | all 7 target underlyings (SPY QQQ IWM GLD TLT SLV USO, each 200 OK, 1.2–5.3 MB) | bid/ask + sizes, **IV, delta/gamma/theta/vega/rho, open interest, volume**, last trade | free, keyless, delayed; terms of use not reviewed | **Reached; captured live** (7/7, 60–474 contracts in the slice, IV coverage 0.78–1.00) |
| **CBOE volatility-index histories** `cdn.cboe.com/api/global/us_indices/daily_prices/<IDX>_History.csv` | VIX 1990→2026-10-30 (9306 rows); VIX9D 2011; VIX3M 2009; VIX6M 2008; VIX1Y 2007; VVIX 2006; SKEW 1990; **GVZ (gold) 2009; OVX (oil) 2009; VXN (QQQ) 2009; RVX (IWM) 2009; VXSLV 2011; VXGDX 2011; VXTLT 2004**; VXEEM/VXEFA/VXEWZ; COR1M/COR3M 2006; VIX1D 2022 | index-level 30-day IV for SPX/NDX/RUT/gold/oil/silver/GDX/TLT/EEM/EFA | OHLC (single column for VVIX, SKEW, GVZ, OVX, VXTLT) | free, keyless | **Reached** (row counts and first/last dates read from the files). VXXLE, TYVIX, PCR returned 403. **Index-level ATM IV only — no strikes, no skew per contract.** |
| **DoltHub `post-no-preference/options`** (HTTP SQL API, no key) | `volatility_history` weekly rows from **2019-02-09 to 2026-10-30**; `option_chain` has SPY on 2026-10-30 (208 rows) | **Only 2 of the 10 symbols tested returned data: SPY, XLE.** QQQ IWM GLD TLT SLV USO GDX IEF returned 0 rows | `option_chain`: date, expiration, strike, call/put, bid, ask, **vol (IV)**, delta, gamma, theta, vega, rho. `volatility_history`: HV and IV current / week / month ago, 52w high/low | open DoltHub data; licence on the repo page not read | **Reached.** **SPY `option_chain` is confirmed present on 2019-03-02, 2020-03-02, 2021-03-01, 2021-09-01, 2023-03-01, 2024-09-02 and 2026-10-30** (a bounded first-date-on-or-after-the-1st query per month; each answer took 1-115 s). Seven other probes (2020-09, 2022-03, 2022-09, 2023-09, 2024-03 and others) hit the public API's `context deadline exceeded`, so **continuity between those dates is NOT established, and neither is per-day density or IV coverage** (one day, 2026-10-30, had 208 SPY rows). Dates are not every weekday early on (2019-03-01 returned 0 rows; 2019-03-02, a Saturday, has data). Aggregate queries all time out. Net: SPY has multi-year contract-level rows with a `vol` (IV) column from 2019 on the evidence above; whether it is complete enough for a priced test needs a full `dolt clone` (size unknown, not attempted). Coverage for our ETFs is thin: **do not plan on it for GLD/TLT/SLV/USO.** A full `dolt clone` would settle depth (size unknown, not attempted). |
| **HuggingFace datasets** (`gauss314/options-IV-SP500` apache-2.0, `smoh/stock_options_trading` MIT, `CodyJiang/nvda-option-chains`) | not read (one CSV each) | single-name / S&P 500 oriented, not our ETFs | unread | open | **Listed, files not downloaded** (API returned file names + licences only). Low prior for our ETFs. |
| **Kaggle** community option archives | not enumerated | unknown | unknown | per-dataset | **Search API answered (200, 85 kB); no dataset was opened.** Named as a lead, not a source. |
| **OCC** volume/OI statistics | — | — | volume/OI only, no prices/IV | free | **Not reached** (`theocc.com` 403 to the sandbox; the `marketdata.theocc.com` query endpoint 400 with the parameters tried). A runner may differ; untested. Volume/OI is not IV, so low value for this gap. |
| **FRED** VIXCLS, GVZCLS, OVXCLS … | same series as CBOE | — | close | free | **Not reached** (connection refused from the sandbox). Redundant with the CBOE files. |
| **Yahoo options** `v7/finance/options` | current chain only, now needs a crumb/auth | — | — | ToS-gray | **Not reached** (401). Also no history. |

## B. Broker APIs we hold accounts with — to be measured by the probe, not asserted

| Source | What it should give | How it gets measured |
|---|---|---|
| **Alpaca options snapshots** (`/v1beta1/options/snapshots/<UND>`, feeds `indicative` / `opra`) | current quotes + IV + greeks; no history | `options-snapshot-capture.yml` `mode: probe` prints, per feed, contract count and how many carry IV |
| **Alpaca historical option bars/trades** (`/v1beta1/options/bars`) | trade-derived bars from about Feb 2024 per Alpaca's docs — **from memory, unverified**; no IV/greeks in history | same probe asks for 3 expired SPY monthlies (2024-03, 2025-03, 2026-03) from 2023-01-01 and prints the earliest bar returned |
| **IB gateway** `reqHistoricalData` with `whatToShow=OPTION_IMPLIED_VOLATILITY` / `HISTORICAL_VOLATILITY` on the underlying | years of underlying 30-day IV history per symbol (all 7 + MES/MGC/MHG options underlyings) — **IB-documented, unmeasured here** | must run on the live VM (only host on the gateway subnet), clientId 450, paced (pipeline row `PI-20261101-ETFHIST-0002`, due 2026-11-03). Expired option contracts are not retrievable from IB; only live ones. |

## C. Paid — priced list for the operator (**nothing bought; prices are vendor-page figures read today, not quotes**)

| Vendor / product | Depth | Fields | Price read today | Reached? |
|---|---|---|---|---|
| **CBOE DataShop — Option EOD Summary** | **Jan 2012 → present**, all OPRA-listed US stocks/ETFs/indices | two snapshots/day (15:45 ET and EOD): bid/ask+size; EOD adds OHLC, volume, VWAP, open interest. **IV and greeks need the optional "Calcs" add-on (15:45 snapshot).** | **no price shown on the page** (cart $0.00 until options chosen; monthly/annual); **has a "Download sample" button** | **Page read AND free sample downloaded 2026-11-01** (anonymous `GET /download/sample/217`, no signup, no payment details; 2.95 MB zip): see sample measurement below |
| **ORATS** (Delayed Data API) | EOD **2007 →**, >5,000 symbols; 1-minute intraday from Aug 2020 (Intraday plans) | bid/ask, **greeks, ORATS smoothed IV/surfaces**, 500+ indicators; no US equity prices | **$199/mo** Delayed (20k requests); $299 Live; $599 Intraday; $899 All-In; **no free trial**, historical samples at ORATS University | Page read (200); API 403 without key |
| **Theta Data** | Value 6 y, Standard 10 y, Pro 14 y | Value: 1-minute intervals; Standard/Pro: tick-level NBBO. **Page does not state IV/greeks included** | **$40 / $80 / $160 per month**; no free tier stated | Page read (200) |
| **Polygon.io (now massive.com)** | not stated | — | **Pricing page read did not show options plans** (footer link `/options` only); not priced | Page redirects (301 to massive.com); options page not read |
| **HistoricalOptionData.com** | not read | EOD | not read | Home page 200, products not read |
| **OptionMetrics (IvyDB) via WRDS** | 1996 → | the academic standard (IV surface, greeks) | institutional/academic licence; not priced | Not reached; no account |

## D. What this means for the gap (stated as a recommendation, not a decision)

1. **Start accruing now, free and keyless: done in code.** `options-snapshot-capture.yml` records the near-the-money, first-3-expiry
   slice of SPY QQQ IWM GLD TLT SLV USO every trading day from **two independent sources** (Alpaca keyed, CBOE keyless; CBOE adds open
   interest and volume). A fresh `capture --source cboe` ran in the sandbox today: 7/7 underlyings, 60–474 contracts, IV coverage
   0.78–1.00. This only builds history **forward**.
2. **For history backward, the free options are index-level only** (CBOE GVZ / OVX / VXN / RVX / VXSLV / VXGDX / VXTLT, 2004–2011 →
   2026): ATM 30-day IV per underlying family, daily. That covers regime/level features for gold, oil, NDX, RUT, silver, GDX and
   long bonds; it cannot price a vertical (no strikes, no skew).
3. **Contract-level backward history is a purchase** (CBOE DataShop 2012 → with the Calcs add-on, or ORATS from 2007 at $199/mo). Cheapest
   next step costs nothing: **download the CBOE DataShop sample** and check whether SPY/GLD/USO ETFs are in it and which fields it
   carries, then decide. ORATS has no trial, so a purchase there is a leap on page claims.
4. **Not established:** DoltHub `option_chain` per-symbol depth; Alpaca historical option-bars depth; IB option-IV depth; the
   Kaggle/HF archives' ETF coverage. Each has a stated measurement above.

## E. Measurement: CBOE DataShop free sample (downloaded 2026-11-01, anonymous)

`UnderlyingOptionsEODCalcs_2023-08-25.zip` (two CSVs, ~7.3 MB each, differing only in how `^SPX` underlying values are reported, plus a readme).
**One trading day (2023-08-25). Four underlyings: `^SPX` (19,366 rows), `SPY` (7,630), `TSLA` (4,238), `^VIX` (1,438).** Of our seven
underlyings **only SPY is present**; QQQ, IWM, GLD, TLT, SLV, USO are absent from the sample (a demo, so this says nothing about the full
product's coverage — the product page says all OPRA-listed US stocks/ETFs/indices).

Columns (33): underlying_symbol, quote_date, root, expiration, strike, option_type, open/high/low/close, trade_volume; at 15:45 ET:
bid/ask + sizes, underlying bid/ask, `implied_underlying_price`, `active_underlying_price`, **`implied_volatility_1545`, delta, gamma,
theta, vega, rho**; at EOD: bid/ask + sizes, underlying bid/ask; `vwap`, `open_interest`, `delivery_code`.
SPY on that day: **29 expiries (2023-08-25 → 2025-12-19), full strike ladder**, IV non-zero on **85% (cgi file) / 91% (no_cgi file)** of
rows (zero = no IV computed), trade_volume > 0 on 3,501 of 7,630 rows, open interest populated. **So the Calcs add-on does carry IV and
greeks at contract level for SPY, on the whole chain, plus open interest — richer than anything free above.** Not measured: the price of
the full history, whether our other ETFs are in it, and any licence restriction on redistribution/ML use (readme points to the product
specification; not read).
