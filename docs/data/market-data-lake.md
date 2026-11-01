# Market data lake — the pooled-ML dataset on Hugging Face / Kaggle

> **Doc status:** `live` · category `architecture` · last verified `2026-11-01` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> **Gates this adds or changes:** none on the trade path. It CHANGES one documentation rule: scheduled publication of
> **market-only** data to a **private** Hugging Face dataset is authorised by the operator's 2026-11-01 directive (below);
> the old "every HF publication is operator-driven" rule ([`huggingface-datasets.md`](../integrations/huggingface-datasets.md) § Forbidden,
> [`ai-model-platform.md`](../architecture/ai-model-platform.md) § Forbidden) now applies to OUR data (journal, fills,
> labels joined to our trades), which still never leaves the trainer.

Row `MARKET-DATA-LAKE` · roadmap `L-DATA`, `M14` · lane dispatched by Manager Session 2026-11-01a.

**Operator, 2026-11-01 ~12:38Z:** *"at least the general MLs needs to be training pretty much on as much market data as we
can find for it, and riding on memory and infra from kaggle/HF to create and store the data sets - this has always been the
design mandate"*.

## 1. Audit: what the design said, what was built, why it stalled

**What the design said.** The Hugging Face side of the data platform has been in the canonical docs since 2026-05-10. Datasets
were to be held in a private HF dataset repo, laid out by family, scope and timeframe
([`docs/integrations/huggingface-datasets.md:28-33`](../integrations/huggingface-datasets.md)). Heavy dataset builds were to
run "on Hugging Face / dev machines, not on the Oracle live VM" (`:35-37`, WS9 in
[`docs/AI-TRADERS-ROADMAP.md:53`](../AI-TRADERS-ROADMAP.md)). An "HF publication CLI subcommand" was planned
([`docs/architecture/ai-model-platform.md:79`](../architecture/ai-model-platform.md)). The storage doc even says ML datasets
"already use Hugging Face / OCI Object Storage offload" ([`docs/architecture/oci-block-storage.md:73`](../architecture/oci-block-storage.md)).

**What was built.** MEASURED 2026-11-01 through the HF connector (account `bentzbk`): the account has **one** dataset,
`bentzbk/ict-signals-dataset` (public, last updated 2026-04-27, no market bars), and **zero** market datasets. Private repos
are visible to this credential (the private model `bentzbk/woof_trade_organziation` lists), so a private dataset would have
shown up. `bentzbk/ict-trading-bot-btcusdt-1m` does not exist, even though
[`scripts/hf_upload_large_files.py:13`](../../scripts/hf_upload_large_files.py) is written to create it. That script would also have
created it **public** (`private=False`, `:73`), and it has no CLI or workflow behind it. The only off-VM market store is the
private Kaggle dataset `metis-market-data`. It holds **BTC/ETH/SOL at 15m and 1h only**
([`docs/github-actions-workflows.md`](../github-actions-workflows.md) row `ml-data-export-kaggle.yml`;
[`06-DATA-INFRA.md:99`](../research/programmes/06-DATA-INFRA.md) "Nothing is shared off the trainer except 2 timeframes × 3 symbols").
Every research re-walk re-fetches candles into scratch space. The ETF fetcher being built today hard-codes **31** symbols
(`scripts/ops/fetch_etf_history.py` `ROSTER`+`LIQUID`, branch `claude/etf-history-pipeline`).

**Why it stalled.** I found four causes, each on the record:

1. The HF workflow doc made every publication a manual operator act and forbade auto-publication
   ([`huggingface-datasets.md:22,89`](../integrations/huggingface-datasets.md);
   [`ai-model-platform.md:98`](../architecture/ai-model-platform.md)). No session owned the manual step, so it never happened.
2. The 2026-10-13 Kaggle design kept dataset builds **on the trainer VM** ("builds stay on the VM in v1",
   [`KAGGLE-TRAINING-PIPELINE-DESIGN-2026-10-13.md:33`](../plans/KAGGLE-TRAINING-PIPELINE-DESIGN-2026-10-13.md)). It exported only
   the shards the VM already built, so the export inherited the VM's 3-symbol universe.
3. The data-infra programme scoped its archive to "the 6 crypto roster symbols" (`06-DATA-INFRA.md:173`). It also judged HF to be
   "a model source here, not a market-data source" (`:132`). Both choices sized the data to the trading roster, not to the
   pooled models.
4. Even that archive row, `DATA-KLINE-ARCHIVE`, was **dropped** on 2026-10-29 by a bulk backlog reset whose stated reason was
   "value unknown" ([`docs/claude/work/checklist/DATA-KLINE-ARCHIVE.json`](../claude/work/checklist/DATA-KLINE-ARCHIVE.json)).
   The operator got no heads-up.

So the design mandate was never contradicted. It was quietly narrowed three times and then dropped.

## 2. What this builds

| piece | file | what it does |
|---|---|---|
| universe | [`config/data_universe.yaml`](../../config/data_universe.yaml) | selection RULES, not hand lists (shared with ETF-HISTORY-PIPELINE; data path only, not a gate) |
| crypto | [`scripts/data_lake/binance_vision_lake.py`](../../scripts/data_lake/binance_vision_lake.py) | every Binance USD-M perp, **incl. delisted**, enumerated from the archive's own listing, at the FINEST grain the archive publishes: **1m klines**, every funding event, 5m metrics (OI, long/short, taker ratio); 27 spot majors at 1m. One parquet per symbol per month; every zip sha256-checked; incremental (`--refresh-from` rebuilds only the open month, new months, and daily-built months whose monthly file appeared) |
| process | [`scripts/data_lake/resample.py`](../../scripts/data_lake/resample.py) | 5m/15m/1h/4h/1d DERIVED from the stored 1m by one deterministic rule (left-closed, labelled at open; `n_base` + `complete` columns mark thin/partial bars); never fetched separately |
| validate | [`scripts/data_lake/validate.py`](../../scripts/data_lake/validate.py) | machine-readable health record per series and per feed (§7); one red flag after 3 consecutive failing runs |
| other sources | [`scripts/data_lake/free_sources.py`](../../scripts/data_lake/free_sources.py) | dated universe snapshots (NASDAQ Trader directory: every US-listed security with its ETF flag; Binance archive listings); FRED rates / FX / credit / vol / commodities / monthly macro; Yahoo daily futures fronts; import of the ETF-HISTORY-PIPELINE store |
| publish | [`scripts/data_lake/hf_publish.py`](../../scripts/data_lake/hf_publish.py) | creates the PRIVATE dataset (refuses a public one), add/replace uploads, merges MANIFEST.json, writes the README depth table, tags `vYYYYMMDD-HHMM` |
| loader | [`ml/datasets/lake.py`](../../ml/datasets/lake.py) | `manifest() / symbols() / load() / iter_series() / liquid_mask() / resample() / health() / revision_info()`; reads only the partitions overlapping the requested window; streams from HF (or `LAKE_LOCAL_DIR`: a Kaggle mount, a runner dir) |
| compute | [`.github/workflows/market-data-lake.yml`](../../.github/workflows/market-data-lake.yml) | 22 crypto capture shards + `other` (universe, FRED, COT, CBOE IV, futures, ETF/option stores) + `equities` (Alpaca 1d for every stock/ETF incl. inactive; DoltHub stocks + options weekly) + `manifest` (merge, health, flag) on GitHub runners. **Daily refresh 03:41Z** (cron + `schedule_keeper.py` re-dispatch of a dropped slot), `mode: backfill` / `preflight` by dispatch or label `market-data-lake-request`; the preflight also runs on every PR touching the pipeline. Nothing runs on our VMs and no Claude session is in the loop |

**Layout** (HF dataset `bentzbk/jta-market-lake`, private): `<asset_class>/<market>/<tf>/<SYMBOL>.parquet`. Bars are
stamped at bar OPEN (UTC) and never forward-filled. Gaps are counted in `MANIFEST.json` (`expected_rows`, `missing_bars`,
`gaps`, `largest_gap_bars`) and never patched. Every manifest entry carries source, licence, first/last bar, rows, bytes and
the fetch time.

**Point-in-time rules.**
- **Universe.** Collection is broad and includes delisted names (the Binance archive lists 1,056 UM symbols including
  settled/delisted contracts; LUNAUSDT ends 2022-05-13). Liquidity floors are applied at READ time on a trailing window
  (`lake.liquid_mask`: the mean of the previous `window` bars, excluding the current bar). Filtering by today's liquidity
  would build survivorship bias in.
- **FRED.** Values are the current vintage. Revised series (CPI, payrolls, INDPRO, …) are marked `pit: false`. A PIT macro
  read needs ALFRED vintages (follow-up below).
- **Futures.** The Yahoo `=F` fronts are raw front-month series with roll jumps (`roll: raw_front`).

**Kaggle.** Kaggle kernels are the training compute for the general models. They read the lake either straight from HF (a
kernel with internet on and a read token stored as a Kaggle secret) or from a private Kaggle mirror `metis-market-lake`
mounted at `LAKE_LOCAL_DIR`. Both routes use the same loader and layout. The mirror job is follow-up (d2) below.

## 3. Depth, per asset class

State key:
- **MEASURED-full**: the whole series was counted from the source, this session.
- **MEASURED-census**: the archive listing was counted with no download. Rows are an upper bound: listed months × bars per month.
- **MEASURED-sample**: a part of the series was downloaded and counted.
- **BUILT**: the code is in the PR but has not run yet (it needs the merged workflow and `HF_TOKEN`).
- **GAP**: no free source is wired. The exact source and what it costs are named.

All HF paths are inside the private dataset `bentzbk/jta-market-lake`. The published table is regenerated into its `README.md` / `DEPTH.md` on every run.

### 3.0 Summary (one row per class)

| class | HF path | symbols | first bar | last bar | rows | state |
|---|---|---|---|---|---|---|
| crypto perps | `crypto/um_perp/1m/<SYM>/<YYYY-MM>.parquet` (base) + `crypto/um_perp/{5m,15m,1h,4h,1d}/…` (derived) + `funding/`, `metrics_5m/` | **1,056** (incl. delisted), all at 1m | 2020-01 | 2026-10-31 | 1m ≤ 1,071,000,000 · metrics ≈ 197,000,000 | MEASURED-census + real-data run |
| crypto spot | `crypto/spot/1m/…` + derived | 27 majors at 1m (3,745 listed in the archive) | 2017-07 | 2026-10-31 | 1m ≤ 106,200,000 | MEASURED-census |
| US stocks | `us_equity/alpaca_sip/1d/`, `us_equity/dolthub/1d/` | 6,158 common listed today + delisted (Alpaca inactive); DoltHub symbol table 24,441 | 2011-01-03 (DoltHub) / 2016-01 (Alpaca) | 2026-10-30 | not yet counted | BUILT; DoltHub span MEASURED |
| ETFs | `us_equity/alpaca_sip/1d/` (all), `us_equity/alpaca/{1h,5m}/` (ETF-HISTORY-PIPELINE) | **5,776** ETF-flagged | 2016-01 | — | not yet counted | BUILT |
| options: IV indices | `options/cboe_iv/1d/` | 18 (VIX family, SKEW, OVX, GVZ, single-stock VIX) | **1990-01-02** | 2026-10-30 | 82,373 | MEASURED-full |
| options: IV/HV history | `options/dolthub_iv/1d/` | 2,342 | 2019-02-09 | 2026-10-30 | 1,984,324 | MEASURED-full (count), BUILT (export) |
| options: EOD chains | `options/dolthub_chain/1d/` | 19 underlyings exported (the source covers A…ZWS) | 2019-02-09 | 2026-10-30 | not counted (API timeout) | span MEASURED; BUILT |
| options: own snapshots | `options/alpaca_snapshot/1d/` | 7 (SPY QQQ IWM GLD TLT SLV USO) | accrual starts when ETF-HISTORY-PIPELINE merges | — | 0 | BUILT (accrual) |
| futures: daily fronts | `futures/yahoo_cont/1d/` | 37 roots | — | — | not counted (Yahoo 429 from this sandbox) | BUILT |
| futures: positioning (COT) | `macro/cftc_cot/1w/` | legacy 964 · disaggregated 662 · TFF 149 markets | **1986-01-15** | 2026-10-27 | 525,501 | MEASURED-full |
| FX spot (daily) | `fx/fred/1d/` | 23 (H.10 + broad dollar indices) | 1971-01-04 | 2026-10-23 | 257,747 | MEASURED-full |
| rates / macro | `macro/fred_*/` | 45 | 1919-01-01 (monthly) / 1954-07-01 (daily rates) | 2026-10-30 | 299,661 | MEASURED-full |

### 3.1 Crypto: perps and spot

**Finest available vs stored.** The operator rule is to keep the smallest timeframe, derive the rest, and never downsample
silently. Every size below is **MEASURED**, in one of two ways:
- zipped bytes summed from the archive's own S3 listing (`binance_vision_lake.py --size-census`, all 1,056 perps, 2026-11-01);
- parquet/zip ratios taken from this lane's real-data runs: klines 1.166 (48.9 MB parquet / 41.9 MB zip), derived
  timeframes +33.6% of 1m, metrics 1.45.

| stream (Binance Vision) | finest grain | zipped (all perps) | in the lake | stored? |
|---|---|---|---|---|
| klines (+ derived 5m–1d) | **1m** | 32.17 GB, 24,443 files | ≈ 50.1 GB | **yes**, core |
| metrics | 5m OI, long/short, taker ratio | 6.91 GB, 655,935 daily files | ≈ 10.0 GB | **yes**, core |
| fundingRate | every funding event | 0.02 GB | < 0.1 GB | **yes**, core |
| spot klines, 27 majors (+ derived) | 1m | 3.92 GB | ≈ 6.1 GB | **yes**, core |
| premiumIndexKlines | 1m | 15.02 GB | ≈ 17.5 GB | **yes, if it fits** the measured headroom; the preflight decides |
| markPriceKlines | 1m | 18.31 GB | ≈ 21.4 GB | only if it fits after premium |
| indexPriceKlines | 1m | 19.38 GB | ≈ 22.6 GB | only if it fits after mark |
| bookDepth | depth snapshots, 2023-01+ | **246.0 GB**, 564,793 files | ≥ 246 GB | **does not fit** |
| aggTrades | every trade (aggregated) | **1,154 GB** | — | **does not fit** |
| trades | every trade | **2,149 GB** | — | **does not fit** |

**The storage allowance.** HF documents 100 GB of private storage for a free account and 1 TB for PRO
([storage-limits](https://huggingface.co/docs/hub/storage-limits), read 2026-11-01). This account is **not PRO**, MEASURED
via whoami. The preflight measures the bytes the account's private repos already use (`usedStorage` per repo). It subtracts
those and the core lake's projected 73 GB (`config/data_universe.yaml` `storage.core_projected_bytes`), then enables each
optional stream that still fits, in priority order. At ~0 bytes used, premium (17.5 GB) fits and mark/index do not.

The repo also follows HF's < 100k-files recommendation. A closed year is one file per symbol, the current year is one file
per month, and all derived timeframes share one file per partition. That is ≈ 15k files in January and ≤ 60k in December.
The first run of each new year compacts the previous year automatically and prunes the superseded files.

**Measured depth:**
- Census (2026-11-01, archive listing, no download): 1,056 of 1,056 listed UM symbols have data, 24,443 symbol-months.
  Monthly files run 2020-01 → 2026-09. The open month comes from daily files.
- The real-data pipeline run (capture → resample → validate → manifest) on 0GUSDT + delisted LUNAUSDT:
  - 1,257,605 1m rows, 0 failures. Derived bars: 5m 251,521 · 15m 83,841 · 1h 20,961 · 4h 5,242 · 1d 875.
  - Warnings are real events: LUNA's May-2022 collapse shows as return outliers, and the archive is missing one day of
    0GUSDT 1m (1,440 bars).
- Data-quality facts from ML-FEATURE-INFRA's handoff:
  - Frozen post-delist months are flagged per partition (`frozen`) and kept.
  - Kline files before ~2020-10 have no header; header-row files call the trade count `count`, and both are handled.
  - Metrics daily files since 2026-08 are unsorted, so they are sorted on read. Treat `create_time` as the window END.

### 3.2 US stocks: the full liquid universe, point-in-time

- **Enumeration (MEASURED):** NASDAQ Trader `nasdaqtraded.txt` lists 13,249 non-test US securities, of which 6,158 are common stock by `parse_nasdaqtraded`. A dated snapshot is written every run, so the history of "what was listed when" builds up.
- **Delisted names:** Alpaca `/v2/assets?status=inactive`, fetched in the `equities` job. The count is not yet measured.
- **Bars (BUILT):** Alpaca 1d SIP, split-adjusted, 2016+, for every listed and inactive symbol (`free_sources.py alpaca-daily`).
- **Older daily history:** DoltHub `post-no-preference/stocks`. MEASURED: `ohlcv` runs 2011-01-03 → 2026-10-30, and the `symbol` table holds 24,441 rows; it includes funds, e.g. `ZZZTX`. It is cloned and exported in the `equities` job.
- **Finest grain:** Alpaca serves **1m** bars from 2016. Stored now:
  - **1d for every stock, ETF and delisted name** (`us_equity/alpaca_sip/1d/<SYM>/<YYYY>.parquet`).
  - **1m base** for the ETF-HISTORY-PIPELINE list (~770 symbols with data, including point-in-time S&P 500 members).
    - That lane fetches it and hands each finished chunk to `free_sources.py import-etf`. Each chunk is written as one
      lake file per symbol per year (`us_equity/alpaca/1m/<SYM>/<YYYY>.parquet`) and merged with the lake's existing
      year, so a partial or tail import replaces only the months it supplies and never shrinks history.
    - 5m/15m/30m/1h/4h/1d are derived in the lake (`us_equity/alpaca/derived/`, volume-weighted vwap).
    - The lake is the store of record; the trainer keeps a tail cache.
    - Manifest fragments are uniquely named and folded into MANIFEST.json idempotently by `hf_publish.py manifest`,
      which then deletes them, so two publishers cannot overwrite each other.

  1m for the WHOLE ~12k-symbol universe is ≤ ~470 GB, INFERRED: 12k × 10 y × 252 d × 390 bars × 40 B, an upper bound because thin names print far fewer bars. That is an **operator storage call**, not done silently. 1m for the ~1,000-symbol list is ≤ ~40 GB.
- **Point-in-time:** the liquid universe is chosen at READ time by `lake.liquid_mask` (trailing ADV ≥ $5M, price ≥ $2). It is never chosen at collection.
- **Further corpora:** `CryptoSpartan/stocks_bars_1m` (MEASURED 604,208,214 1m bars, ≥637 tickers, current names only).
- **Gaps:**
  - Intraday (1h/5m) for every stock is an Alpaca pull bounded by request rate, not by cost (same keys). It is filed as PI-20261101-WTFTWTFP-0002.
  - Pre-2011 daily history with delisted names is not covered: CRSP via WRDS is institutional-only, and Norgate Data is a paid subscription (price not verified this session).

### 3.3 ETFs: all US-listed

- **Enumeration (MEASURED):** 5,776 ETF-flagged securities, against the 31 the basket had.
- **Bars:**
  - 1d for all of them in the `equities` job (Alpaca SIP, 2016+).
  - 1h/5m from the ETF-HISTORY-PIPELINE store. Its fetcher still carries a 31-symbol constant; PI-20261101-WTFTWTFP-0002 widens it to the universe snapshot.
- **Gap:** pre-2016 intraday. The free Alpaca SIP history starts in 2016; earlier intraday needs a paid vendor (Polygon/Massive, or Databento equities; prices not verified).

### 3.4 Options

- **CBOE IV indices (MEASURED-full):** 18 of 18 series, 82,373 rows.

  | series | first bar |
  |---|---|
  | VIX, SKEW | 1990-01-02 |
  | VVIX | 2006-03-06 |
  | VIX1Y | 2007-01-03 |
  | VIX6M | 2008-01-02 |
  | VIX3M, OVX, GVZ, VXD | 2009-09-18 |
  | VXN | 2009-09-14 |
  | RVX | 2009-09-16 |
  | VIX9D | 2011-01-04 |
  | VXEEM, VXSLV, VXGDX | 2011-03-16 |
  | VXAZN, VXAPL | 2011-01-07 |
  | VIX1D | 2022-05-13 |

  All end 2026-10-30. `VXXLE` returns an error from CBOE and is dropped.
- **DoltHub `post-no-preference/options`:**
  - `volatility_history` (MEASURED by SQL): 1,984,324 rows, 2,342 symbols, 2019-02-09 → 2026-10-30.
  - `option_chain`: EOD chains with bid/ask/IV/greeks, MEASURED first row 2019-02-09, last row 2026-10-30. The total row count is unmeasured because the SQL API times out on whole-table scans.
  - The runner `dolt clone`s the repo. It exports `volatility_history` in full and `option_chain` for the 19 underlyings in `config/data_universe.yaml`; wider once the clone size is measured.
  - "SPY/XLE" in the brief are covered here.
- **Own accrual:** ETF-HISTORY-PIPELINE's daily chain snapshot (7 underlyings) is imported from the trainer as it accrues. It is 0 days today, because that PR is unmerged.
- **Gaps:**
  - **CBOE sample files:** CBOE DataShop's free samples are single-day downloads behind a web form, not an archive. They are useful for schema checks only, so they are not wired.
  - **Full historical intraday chains / OPRA:** CBOE DataShop Option EOD/Intervals (paid per product and month) or Polygon/Massive Options (paid plan). Prices not verified this session; a quote needs an operator account.

### 3.5 Futures

- **Daily continuous fronts (BUILT):** Yahoo `=F` for 37 roots: equity indices, energy, metals, rates, grains, softs, livestock, the FX majors, VX, and BTC/ETH. These are raw front-month series with roll jumps, for research use in the private store only. Not counted yet: Yahoo returned 429 to this sandbox, and the runner is the measurement.
- **Positioning (COT, MEASURED-full):** 525,501 rows.

  | report | rows | markets | span |
  |---|---|---|---|
  | legacy | 291,531 | 964 | 1986-01-15→2026-10-27 |
  | disaggregated | 186,744 | 662 | 2006-06-13→ |
  | TFF | 47,226 | 149 | 2006-06-13→ |

  `ts` is the Tuesday position date. Release is Friday, so a point-in-time reader lags 3 days (recorded in the manifest).
- **IB historical path:** per-contract MES/MGC/MHG history through the IB gateway, reachable only from the live VM's subnet. Owned by PI-20261101-ETFHIST-0001; it lands as `futures/ibkr/<tf>/<CONTRACT>.parquet`.
- **Gap: intraday continuous futures with proper rolls.** The source is CME DataMine or Databento CME Globex (usage-priced per GB); price not verified.

### 3.6 FX: spot

- **Daily (MEASURED-full):** FRED H.10 noon buying rates plus the broad/AFE/EM dollar indices: 23 series, 257,747 rows, 1971-01-04 → 2026-10-23, public domain.
- **Gaps:**
  - **Intraday:** Dukascopy's public datafeed (free, keyless tick/1m; the tunnel failed from this sandbox and runner reachability is not verified; their terms need reading before bulk use). HistData.com 1m is free, but the download sits behind a per-month web form, so it is not automatable within its terms.

### 3.7 Rates / macro

**FRED (MEASURED-full):** 45 of 46 series, 299,661 rows.

| group | series | rows | from |
|---|---|---|---|
| rates | 20 | 229,689 | 1954-07-01 |
| credit | 5 | 3,929 | **2023-10-31** only: FRED now serves 3 years of ICE BofA |
| vol / financial stress | 6 | 29,941 | 1971 |
| commodities | 3 | 24,366 | 1986 |
| monthly macro | 11 | 11,736 | 1919 |

**Gaps:**
- Long-history credit spreads: ICE data is licensed; Moody's daily `DBAA` / `DAAA` on FRED are now in the config as the free long proxy.
- First-release vintages for the revised series: ALFRED, free and keyless; filed as PI-20261101-WTFTWTFP-0003.

### 3.8 How this was measured

- The FRED, CBOE and COT figures are full downloads from this lane's sandbox, 2026-11-01.
- The crypto figures are the archive listing plus downloaded samples.
- The DoltHub figures are SQL queries against DoltHub's API.
- The NASDAQ Trader counts are a full file parse.
- Sizes: BTCUSDT 1h for 6.8 years is 4.26 MB; COT legacy is 45.8 MB. The full lake is INFERRED at ~20–30 GB, before the DoltHub chain export, whose size is unknown until the clone runs.

## 4. Public datasets on the hubs (evaluated, 2026-11-01)

| dataset | coverage (MEASURED where stated) | licence | PIT | verdict |
|---|---|---|---|---|
| `paperswithbacktest/{Stocks,ETFs,Bonds,Commodities,Forex,Indices,Cryptocurrencies}-Daily-Price`, `Stocks-1Min-Price`, `Stocks-Daily-LiquidUniverse` | card: Stocks-Daily 25.99M rows / 7,764 symbols / 1962-01-02→2026-08-05, refreshed monthly; LiquidUniverse = top-1000 liquid names **per session** (a PIT universe) | `other`; **gated (manual approval)** — terms unread | universe yes (LiquidUniverse); delisting coverage unverified | **not pursued** (operator 2026-11-01: stick to already-accessible sources). Equity history comes from Alpaca on our keys plus ungated corpora |
| `CryptoSpartan/stocks_bars_1m` | MEASURED via parquet metadata: **604,208,214** 1m bars, ≥637 tickers, 2016-01-01→2026-07-07, one 10.9 GB file; has QQQ/AAPL, lacks SPY/GLD/TLT/XLE | card says MIT; the data is scraped from Alpaca, so Alpaca's terms are the binding ones | current names only (survivorship) | **usable now** as an extra 1m equity pretraining corpus (ungated); not for universe-level PIT studies. Import is follow-up (b2) |
| `yadavsaurabh/us-stocks-and-search-trends` | card: 11,636 symbols, 1d/1h/5m/2m/1m CSV, Yahoo-derived | `other` | unknown | Yahoo-derived, so the intraday depth is capped by Yahoo (1h ≈ 730 d, 1m ≈ 30 d); daily may duplicate the paperswithbacktest data; low priority |
| `Salesforce/GiftEvalPretrain`, `autogluon/chronos_datasets` | 4.5M series / 230B points (GIFT); Chronos corpus | Apache-2.0 / other | n/a (not market data) | for time-series **foundation-model** pretraining only, not for market features |
| `zongowo111/v2-crypto-ohlcv-data`, `arthurneuron/crypto-futures-ohlcv-1m` | 46 files; a 2023 snapshot | MIT (re-hosted Binance) | — | **redundant**: our Binance Vision pull is the primary source, full and fresher |

## 5. What is needed from the operator

- **`HF_TOKEN`:** MEASURED by the workflow's `preflight` job on this PR and on every run. It records the role and the
  fine-grained scopes, does a REAL write, and measures private storage in use. The token is never printed. The result is in
  the run artifact `preflight`.
- **What doesn't fit free storage** (the one line, after the first run measures headroom and the equity 1m day):
  - bookDepth: 246 GB.
  - aggTrades / trades: 1.15 TB / 2.15 TB zipped.
  - Mark/index 1m, if premium takes the headroom.
  - Equity 1m for every US symbol: measured from one real session (`free_sources.py measure-equity-1m`, `_measure/equity_1m_day.json`).

  Each against the 100 GB free allowance, with the cheapest free fallback:
  - aggTrades: the traded universe only (≈ 8 symbols).
  - bookDepth: the traded universe only.
  - Older months: private Kaggle datasets (a separate free quota).
- Nothing is bought. The paid gaps in §3 stay in PI-20261101-WTFTWTFP-0006.

`KAGGLE_API_TOKEN` is already used by 9 workflows.

## 6. Follow-ups (filed in `docs/claude/work/PIPELINE.jsonl`)

- (b2) import `CryptoSpartan/stocks_bars_1m` (ungated; Alpaca terms).
- (b3) ETF-HISTORY-PIPELINE reads the universe snapshot (done in its code; wiring pending its PR).
- (c2) ALFRED vintages for the revised FRED series (true PIT macro).
- (d2) a Kaggle read path for the lake.
- (f) paid-gap quotes (PI-20261101-WTFTWTFP-0006).

## 7. Feed automation and health (no Claude in the loop)

| stage | where | what |
|---|---|---|
| capture | every capture job, daily 03:41Z | incremental from the previous `MANIFEST.json`; per-file retries; a failing symbol is recorded and skipped, never halts the shard |
| process | crypto klines jobs | `resample.py` derives 5m/15m/1h/4h/1d from the rebuilt 1m months; per-partition manifest entries |
| validate | every capture job | `validate.py check`: schema, duplicate ts, non-monotonic ts, OHLC sanity, return outliers, missing bars vs the bar calendar (crypto continuous; US equity 1d vs business days less federal holidays, an approximation of the NYSE calendar) |
| merge | `manifest` job | `validate.py merge`: per-feed staleness (newest last bar vs a per-feed limit, e.g. crypto 54 h, FRED 6 d, COT 12 d), consecutive-failure counts carried from the previous record |
| record | HF `health/latest.json` + `health/<ts>.json`; repo `comms/data_lake/health_latest.json` (landed by commit-to-main) | schema `market-data-lake-health/v1`: summary, per-feed states, failing series, `new_flags`, `flag_delivered` |
| flag | `manifest` job | a series or feed failing **3 consecutive runs** raises ONE flag: a comment on the ops-flags PR plus one Telegram message on the operator SYSTEM channel, the same `GhProbe` path research-watchdog uses. It re-arms only after recovery |
| keep-alive | `scripts/ops/schedule_keeper.py` target `market-data-lake.yml` (stale 26 h) + a `dedupe` job | a dropped GitHub cron slot is re-dispatched; a dead run is caught by `claude-run-failure-alert` |

Claude reads the health record in `/health-review` and `/ml-review`. It does not run the feeds.
