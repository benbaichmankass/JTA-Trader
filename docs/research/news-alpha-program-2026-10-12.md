# NEWS-ALPHA program — does news / open-source unstructured data carry standalone edge? (2026-10-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

This is an **index**, not a memo. Each question below is a pre-registered unit under
`research/queue/blocked/` (or a checklist lever row) and is answered there. Program row:
`docs/claude/work/checklist/NEWS-ALPHA-PROGRAM.json` · roadmap **M28** (G6 macro/value sleeve).

## Why it exists

> **Operator, 2026-10-12 (binding, verbatim):** "testing it against trades that were made or would have
> been traded by our strategies is a good first test, but it obviously doesn't tell us anything about if we
> can build new strategies based on the predictive power of news and open-source unstructured data. We need
> to see not just if it correlates with our trades, but if it shows an edge, if it correlates to different
> market movements, if there are other ways to discern a usable correlation from that feed. This is just the
> first sample of signals — there are many types of samples, many types of securities, many market
> conditions. We're far from having exhausted the research needed to make even a first-level retire
> decision; we are not close to retiring this."

So the G1 result (RQ-20261009-902, #17740: news adjustment vs taken-trade net R, IC −0.014, n=634), the G2
result (RQ-20261009-903, #17744: PM-surprise vs consensus, n=68) and the NEWS-HIST-REPLAY offline G1
(RQ-20261012-2a7b-01: title-only sentiment, IC −0.0073, n=1,436) answer **only the overlay questions**.
**Retiring the news layer is off the table.** The question this program asks: does news or open-source
unstructured data carry **standalone** predictive information about returns, volatility or volume — in any
asset class, horizon or regime — and is any of it tradeable **net of the full cost stack**?

## Inventory (what exists, measured 2026-10-12)

| asset | state | used by |
|---|---|---|
| Live news layer `src/news/*` | NewsAPI or keyless RSS (Fed, MarketWatch, CNBC, CoinDesk, Cointelegraph, Decrypt, OilPrice); keyword-lexicon sentiment; items > 120 min dropped | U01 |
| `runtime_logs/news_decisions.jsonl` (live VM) | 13,173 rows 2026-06-11..2026-10-09, one per signal evaluation; keeps top-3 truncated headlines, **no raw headline archive anywhere** | U01 |
| NEWS-HIST-REPLAY GDELT GKG corpus | 1.42 M title-only items 2023-10-01..2026-10-12, built in that session's `/tmp` — **not persisted** (finding, filed on NEWS-ALPHA-CORPUS) | U02–U08, U10 via the corpus lever |
| Kalshi backfill (trainer, off-repo) | hourly yes bid/ask candles, 168 h before close, CPI 60 / NFP 41 / FOMC 27 markets | U09 |
| `pm_snapshots` collector (trainer) | 4×/day since 2026-10-08, 5 Kalshi + 2 Polymarket series | U09 (prospective) |
| `comms/macro/` PIT stores | econ calendar (32,168 forward rows + 9,968 / 12,076 backfill), COT 10,093 rows 1988–2026, valuation | context / controls |
| Crypto signals | scorecards only; no `crypto_snapshots.jsonl` committed | — |
| Price data | daily ETFs via `fetch_macro_candles.py`; crypto intraday via data.binance.vision USDM (runner-reachable; Bybit geoblocks runners); ETF/FX/metal intraday via `fetch_dukascopy_ohlcv.py`; Bybit frames on the trainer | all |
| Harness parts | `horizon_ic_scan.py` (daily, valuation schema only), `econ_event_study.py` (releases), `backtest_xsec_momentum.py` (daily panel), `ml_bakeoff.py`; **no generic intraday feature→target harness** | lever NEWS-ALPHA-HARNESS |
| Regime labels | `wilder_adx` + `regime_label` (src/runtime/regime/detector.py) label any bar series | U03 |

## Sources triaged (frontier-research gates: data · compute · latency · leakage/licence)

| source | verdict | why |
|---|---|---|
| **GDELT 2.0 GKG** (full columns) | **KEPT** → NEWS-ALPHA-CORPUS | free, keyless, 15-min files since 2015-02; ingest time `V2.1DATE` gives a no-lookahead availability stamp; **V2Tone is, per GDELT's documentation as recalled (UNVERIFIED this session — the CORPUS lever confirms it from the codebook and a fixture), computed over the full article text**, so dropping to titles would be a fetch choice, not a source limit; also themes / organisations / GCAM. [GDELT GCAM](https://blog.gdeltproject.org/?p=1044) (primary) |
| **Prediction-market price MOVES** (Kalshi backfill + collector) | **KEPT** → U09 | already on the trainer; derived-only output (third-party terms unread, operator 2026-10-08) |
| **FOMC statement text** (federalreserve.gov) | **KEPT** → NEWS-ALPHA-SRC-FOMC, U11 | free, exactly timed, ~23 years — n not bounded by our corpus |
| **SEC EDGAR 8-K** | **KEPT** → NEWS-ALPHA-SRC-EDGAR, U12 | free (10 req/s fair access); acceptance-datetime field location **not yet confirmed** — verify on a runner first |
| **Wikipedia pageviews** | **KEPT** → NEWS-ALPHA-SRC-WIKI, U13 | free, keyless, 2015-07+; per-article is **daily** only (hourly is project-level / dumps) |
| Common Crawl CC-NEWS | deferred (already filed as PI-20261012-UFJZ63WF-0001) | free, 2016+, but WARC date is crawl time, not publication; >100 TB; the body-bearing option if GKG tone proves too coarse |
| Bigdata.com connector | deferred to the same PI row | licensed body-text corpus; licence/cost is an operator decision, not a default |
| Google Trends | **REJECTED (leakage + access)** | official API is closed alpha; pytrends archived 2025-04-17; samples are renormalised per query so history is not point-in-time reproducible |
| Reddit / crypto social volume | **REJECTED (licence/cost)** | Pushshift public access ended 2023; commercial API priced in the $12k range; LunarCrush/Santiment paid |
| Earnings-call transcripts | **REJECTED (cost)** | no free point-in-time source; revisit only via a licensed corpus |
| GitHub dev activity (GH Archive) | **dropped for wave 1 (budget)** | free and point-in-time, but a weeks-to-months horizon on ~20 coins; a wave-2 candidate if U04 shows any cross-sectional crypto signal |
| X/Twitter | **REJECTED (cost)** | paid API |

Secondary sources for the rejections: [pytrends status](https://dev.to/esteban_ortega/pytrends-is-dead-heres-how-to-get-google-trends-data-in-2026-1a18), [Reddit after Pushshift](https://www.xpoz.ai/blog/tutorials/how-to-get-historical-reddit-data-after-pushshift/), [CC-NEWS](https://blog.commoncrawl.org/blog/news-dataset-available), [EDGAR FTS](https://apify.com/andrew_avina/edgar-fulltext-mcp) (all secondary; the levers re-verify before building).

## The feature family (one family, many signals)

Attention / volume shock (count z vs trailing 30 d, same hour-of-week) · source breadth · tone level, 24 h
change and novelty z · tone dispersion (disagreement) · topic intensities (conflict, central bank,
inflation, energy, trade policy) · event classes (hack/exploit, regulatory/enforcement, listing/ETF, macro
shock) · entity-specific vs macro/topic · cross-asset spillover · PM expectation changes · FOMC text change
and novelty · 8-K item arrivals · pageview attention. Built by NEWS-ALPHA-FEATURES; missing is `null`, never 0.

## Targets and populations

Forward **return, realized vol, |return| and volume** at 15m / 1h / 4h / 1d / 5d (per unit), on crypto20
(Bybit USDT perps; Binance USDM klines as the runner proxy), ETF6 (SPY QQQ TLT GLD USO UUP), the S&P 100
(frozen 2023-10-01 list), with time-series, cross-sectional and event-study designs and an ADX regime split.

## Statistical discipline (binding on every unit)

1. **Registered before any run** — every unit carries its grid, cell count, metric, horizon, population,
   n floor and rule.
2. **Multiple-testing budget: 600 discovery tests for wave 1** (520 registered across 14 units; 80 headroom
   reserved for disclosed pre-run amendments). Discovery survivors are cells with `p ≤ 0.10·r/600` (`r` is the
   cell's p-rank within its unit). This is family-wide Benjamini–Hochberg at q = 0.10, with unrun cells counted
   as p = 1. It is conservative, and each unit can compute it on its own. At each readout BH is re-run over every
   landed p-value.
3. **Sealed holdout 2025-10-01..2026-09-30** (U01, U09 and U11 declare their own, because the window would be
   too thin for them). Each survivor gets **one** confirmatory test there. The wave-1 cap is **20 holdout tests**,
   Holm-adjusted at α = 0.05. Everything is ledgered in `research/news_alpha/TEST-LEDGER.jsonl`, and the harness
   refuses a holdout read for any cell that did not survive discovery.
   ⚠️ **Disclosure:** RQ-20261012-2a7b-01 already computed title-sentiment ICs for BTC/ETH/SOL over 2023-10..2026-10,
   so for those three coins the holdout window was **partly viewed**. That is why every PASS also files a
   **prospective** unit, graded only on data after 2026-10-12.
4. **Point-in-time only.** The availability stamp is GDELT ingest time, never publisher time. Leakage checks L1–L4
   gate each run: a per-row availability assertion, a future-shift comparison, a circular-shift placebo, and a
   phase lock.
5. **Net of the full cost stack.** Any edge claim must survive `src/runtime/execution_costs.resolve_cost_policy`
   (fee + slippage + funding). A cell that holds up in rank but not net of cost is reported as `PASS_RANK_ONLY`,
   which is information and not edge.
6. **Vol and volume are graded separately.** They are tested against HAR-RV and AR(5) baselines with a
   Diebold–Mariano test. A vol PASS is a sizing/risk input (U14), never a direction claim.
7. **A FAIL closes only the configuration that was tested.** Leads (p < 0.05 unadjusted, non-survivors) may seed
   wave 2 only on data the discovery window did not touch.

## Wave 1 units (all `research/queue/blocked/` until their levers land)

| unit | P | question | cells | blocked on |
|---|---|---|---|---|
| RQ-20261012-5bd1-01 | 1 | Does the live news score inform the next 15m–1d move, over **all** evaluations? | 36 | FEATURES (live-log adapter), HARNESS |
| RQ-20261012-5bd1-02 | 1 | Does GDELT attention shock predict crypto vol, \|return\| and volume (1h–1d)? | 36 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-03 | 1 | Does GDELT full-text tone (level, change, novelty) predict crypto returns, by regime? | 72 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-04 | 1 | Cross-sectional crypto20: does a news-shock or tone rank predict 1d/5d returns or vol, net? | 8 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-05 | 2 | Event study by class: hack, regulatory, listing/ETF, macro shock | 32 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-06 | 2 | Do macro/geopolitical topic intensities predict ETF6 vol and returns? | 120 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-07 | 2 | Does tone dispersion predict vol? | 5 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-08 | 2 | Spillover: do macro-topic shocks predict BTC/ETH vol and returns? | 30 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-09 | 1 | **G2 asked standalone:** do PM price MOVES lead TLT/SPY/BTC returns and vol? | 108 | FEATURES (PM adapter), HARNESS |
| RQ-20261012-5bd1-10 | 2 | S&P 100 cross-section: does attention shock predict abnormal volume, vol and returns? | 12 | CORPUS, FEATURES, HARNESS |
| RQ-20261012-5bd1-11 | 2 | Does FOMC statement text change or novelty predict post-statement drift and vol? | 32 | SRC-FOMC, HARNESS |
| RQ-20261012-5bd1-12 | 3 | Do 8-K item arrivals predict abnormal return and vol? | 16 | SRC-EDGAR, HARNESS |
| RQ-20261012-5bd1-13 | 3 | Does Wikipedia pageview attention predict vol, volume and xsec returns? | 12 | SRC-WIKI, HARNESS |
| RQ-20261012-5bd1-14 | 3 | If U02 passes on vol, does news-augmented vol sizing cut book net-R variance? | 1 | requires U02 vol PASS |

**Unblock order** (the shortest path to results): HARNESS + the FEATURES live-log and PM adapters unblock
**U01 and U09**, which need no new collection. CORPUS then unblocks U02–U08 and U10. The three SRC levers
unblock U11–U13.

## Readout

A pipeline item (`origin.ref` NEWS-ALPHA-PROGRAM) comes due when ≥ 5 units have measured records. The readout
applies each unit's rule, re-runs family BH over every landed cell, lists which configurations are closed and
which are open, and writes back to M28.
