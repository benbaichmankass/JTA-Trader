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
| crypto | [`scripts/data_lake/binance_vision_lake.py`](../../scripts/data_lake/binance_vision_lake.py) | every Binance USD-M perp, **incl. delisted**, enumerated from the archive's own listing; 1d/1h/15m/5m all, 1m majors; spot majors; every monthly zip sha256-checked against Binance's `.CHECKSUM`; daily tail for the current month |
| other sources | [`scripts/data_lake/free_sources.py`](../../scripts/data_lake/free_sources.py) | dated universe snapshots (NASDAQ Trader directory: every US-listed security with its ETF flag; Binance archive listings); FRED rates / FX / credit / vol / commodities / monthly macro; Yahoo daily futures fronts; import of the ETF-HISTORY-PIPELINE store |
| publish | [`scripts/data_lake/hf_publish.py`](../../scripts/data_lake/hf_publish.py) | creates the PRIVATE dataset (refuses a public one), add/replace uploads, merges MANIFEST.json, writes the README depth table, tags `vYYYYMMDD-HHMM` |
| loader | [`ml/datasets/lake.py`](../../ml/datasets/lake.py) | `manifest() / symbols() / load() / iter_series() / liquid_mask() / revision_info()`; streams from HF (or `LAKE_LOCAL_DIR`: a Kaggle mount, a runner dir) |
| compute | [`.github/workflows/market-data-lake.yml`](../../.github/workflows/market-data-lake.yml) | 20 crypto shards + one "other" job on GitHub runners, weekly Sun 03:23Z + dispatch + label `market-data-lake-request`; nothing runs on our VMs |

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

## 3. Depth tables (MEASURED)

### 3a. Measured in this lane's sandbox, 2026-11-01

`binance_vision_lake.py` and `free_sources.py` ran against the live sources. This is a sample, not the full lake.

| asset class | market | tf | series ok / total | rows | earliest first bar | latest last bar | median span (days) | missing bars | bytes |
|---|---|---|---|---|---|---|---|---|---|
| crypto | um_perp | 1h | 3 / 3 (BTCUSDT, LUNAUSDT delisted, 0GUSDT new) | 80,841 | 2020-01-01 | 2026-10-31 | 469 | 168 | 5,432,936 |
| crypto | um_perp | 1d | 53 / 53 (shard 0 of 20, ≈5% of the 1,056 listed) | 28,374 | — | 2026-10-31 | — | — | — |
| fx | fred | 1d | 23 / 23 | 257,747 | 1971-01-04 | 2026-10-23 | 16,730 | 0 | 3,382,672 |
| macro | fred_rates | 1d | 20 / 20 | 229,689 | 1954-07-01 | 2026-10-30 | 18,153 | 0 | 2,415,781 |
| macro | fred_credit | 1d | 5 / 5 | 3,929 | **2023-10-31** | 2026-10-29 | 1,094 | 0 | 49,026 |
| macro | fred_vol_risk | 1d | 6 / 6 | 29,941 | 1971-01-08 | 2026-10-29 | 11,984 | 0 | 378,474 |
| macro | fred_commodities | 1d | 3 / 4 | 24,366 | 1986-01-02 | 2026-10-27 | 14,405 | 0 | 307,169 |
| macro | fred_monthly | 1mo | 11 / 11 | 11,736 | 1919-01-01 | 2026-10-24 | 25,445 | 0 | 179,270 |

Notes. BTCUSDT 1h has 59,880 rows. All 111 monthly checksums were ok, with 24 bars missing (one day absent from the archive,
the same day as in 0GUSDT). The FRED credit spreads (ICE BofA) now serve only the last 3 years on FRED, a licence change at the
source. Longer history needs another source. `GOLDAMGBD228NLBM` was removed because FRED discontinued it; gold comes from `GC=F`.

**Universe counts (MEASURED 2026-11-01).** NASDAQ Trader `nasdaqtraded.txt` lists 13,249 US-listed non-test securities:
**5,776 ETF-flagged** and 6,158 common stocks by the filter in `parse_nasdaqtraded`. The Binance archive lists **1,056** UM
symbols and **3,745** spot symbols. The old basket was 31 ETFs, so the ETF universe is ~186× larger.

**Throughput (MEASURED).** 53 perps at 1d took 68 s at `--parallel 8`. BTCUSDT 1h (111 monthly zips) took 21 s. The full
1,056 symbols are ≈23 min per timeframe per runner, which is why 1h/15m/5m are sharded 2/4/6 ways.

**Size (INFERRED from the measured files).** BTCUSDT 1h for 6.8 years is 4.26 MB in zstd parquet. The 1,056 perps are mostly
short-lived, so the full lake is ≈1 GB at 1h, ≈3–4 GB at 15m, ≈10 GB at 5m and ≈4–5 GB for 1m on the 20 majors, about
**20 GB** in total. HF private-storage limits for this (free, non-PRO) account are **not verified**. The first full run's
`MANIFEST.json` byte totals are the measurement.

### 3b. The published lake

The table is generated into the HF dataset's `README.md` / `DEPTH.md` by every `market-data-lake` run, and posted on the
triggering issue. It is copied here when the first run lands. *Not yet run: needs the workflow merged and `HF_TOKEN`
(write) — §5.*

## 4. Public datasets on the hubs (evaluated, 2026-11-01)

| dataset | coverage (MEASURED where stated) | licence | PIT | verdict |
|---|---|---|---|---|
| `paperswithbacktest/{Stocks,ETFs,Bonds,Commodities,Forex,Indices,Cryptocurrencies}-Daily-Price`, `Stocks-1Min-Price`, `Stocks-Daily-LiquidUniverse` | card: Stocks-Daily 25.99M rows / 7,764 symbols / 1962-01-02→2026-08-05, refreshed monthly; LiquidUniverse = top-1000 liquid names **per session** (a PIT universe) | `other`; **gated (manual approval)** — terms unread | universe yes (LiquidUniverse); delisting coverage unverified | **highest-value candidate.** Needs the operator to click "request access" on HF as `bentzbk` (§5). Then read the terms and the delisting coverage before use |
| `CryptoSpartan/stocks_bars_1m` | MEASURED via parquet metadata: **604,208,214** 1m bars, ≥637 tickers, 2016-01-01→2026-07-07, one 10.9 GB file; has QQQ/AAPL, lacks SPY/GLD/TLT/XLE | card says MIT; the data is scraped from Alpaca, so Alpaca's terms are the binding ones | current names only (survivorship) | **usable now** as an extra 1m equity pretraining corpus (ungated); not for universe-level PIT studies. Import is follow-up (b2) |
| `yadavsaurabh/us-stocks-and-search-trends` | card: 11,636 symbols, 1d/1h/5m/2m/1m CSV, Yahoo-derived | `other` | unknown | Yahoo-derived, so the intraday depth is capped by Yahoo (1h ≈ 730 d, 1m ≈ 30 d); daily may duplicate the paperswithbacktest data; low priority |
| `Salesforce/GiftEvalPretrain`, `autogluon/chronos_datasets` | 4.5M series / 230B points (GIFT); Chronos corpus | Apache-2.0 / other | n/a (not market data) | for time-series **foundation-model** pretraining only, not for market features |
| `zongowo111/v2-crypto-ohlcv-data`, `arthurneuron/crypto-futures-ohlcv-1m` | 46 files; a 2023 snapshot | MIT (re-hosted Binance) | — | **redundant**: our Binance Vision pull is the primary source, full and fresher |

## 5. What is needed from the operator (credentials only)

1. **`HF_TOKEN`** must be a **WRITE** token for the `bentzbk` account, stored as the Actions repo secret `HF_TOKEN`. The secret
   name is already referenced by `hf-cron.yml`, but whether it is set, and with what role, is **not verified**: a session cannot
   read secrets. The workflow's `preflight` job reports both on the first run. If it is missing or read-only, the operator
   creates a token at huggingface.co → Settings → Access Tokens with "Write" (or fine-grained write on `bentzbk/jta-market-lake`)
   and pastes it into GitHub → Settings → Secrets → Actions → `HF_TOKEN`.
2. **HF gated access**: request access to the `paperswithbacktest/*` datasets while signed in as `bentzbk` (one click per
   dataset on its HF page). Nothing else is needed. The import is filed and runs once access is granted.

`KAGGLE_API_TOKEN` is already in use by 9 workflows; nothing is needed there.

## 6. Follow-ups (filed in `docs/claude/work/PIPELINE.jsonl`)

- (b2) import `CryptoSpartan/stocks_bars_1m` into `us_equity/alpaca_1m_ext/1m/` (ungated; Alpaca terms).
- (b3) broad Alpaca daily + 1h pull for every ETF in the universe snapshot (ETF-HISTORY-PIPELINE's fetcher reading
  `universe/us_equity/<date>.csv` instead of its 31-symbol constant), plus inactive assets for delisted names.
- (c2) ALFRED vintages for the revised FRED series (true PIT macro).
- (d2) Kaggle mirror `metis-market-lake`, or a Kaggle-secret HF read path, so Kaggle kernels read the lake.
- (e) after access is granted: the `paperswithbacktest/*` import, with its terms read first.
