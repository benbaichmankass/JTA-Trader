# 06 — Data infrastructure: ingest, process, label, learn

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-14` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `DATA-INFRA-PROGRAMME` (manager session_01VduHYzdaXe27wTDBLSu8ao, operator directive 2026-10-14 ~21:35Z) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) · roadmap **`L-DATA`** (G4) · **Tier-1 document: it changes no config, timer, roster or order path. Every Tier-2 build below is a checklist row for a later build lane.**

> **What this is.** The data half under programmes 01 (active trade management) and 02 (AI trader): what the ML stack must be fed to learn, what exists today (MEASURED), the gap, and the build plan. It is a plan, not a third category of work: **the work is the rows and units it names** (§ 7). Where this document and a row or unit disagree, the row or unit wins and this document is fixed.

---

## 0. Operator direction (2026-10-14 ~21:35Z, verbatim, relayed by the manager)

> "Ok, we may need a specific roadmap milestone or sub-work-plan for data infra - of that's the blocker, then we need to renovate the infra to make sure we're ingesting enough of the vast open source data resources, processing, labeling, and learning from that data so that our mls can actually learn and improve"

Trigger: row `IN-TRADE-EXIT-MODEL` (the north-star exit model: P(SL before TP | trade state at bar t) plus an exit-now policy) is blocked on data. Division of labour, agreed by construction: **the IN-TRADE-EXIT-MODEL lane owns the exit model and its research script; this programme owns the data plumbing under it** — the archives, the label library, the stores and their integrity. Rows that lane already filed are named here, never re-filed (§ 7).

## 1. End goal and measure

**End goal.** Every model in programmes 01–05 learns from (a) enough history at a fine enough grain that its label is a measurement, not a convention, (b) every information class the open-source world offers for free, and (c) features computed the same way at train and at serve time.

**Measures** (re-measure each weekly pass; do not quote forward):

| measure | how | baseline (MEASURED 2026-10-14) |
|---|---|---|
| Finest persisted, refreshed grain per crypto roster symbol | trainer `datasets-out/market_raw/<SYM>/<tf>/v002` (diag #18108) | **5m** (BTC/ETH/SOL), 15m (ADA/AVAX/XRP). The only 1m history: BTC `v001` 3,237,924 rows / 572 MB JSONL and MES `v001` 434,296 rows, **neither refreshed by the nightly build** (its script has no `1m` reference) |
| Market shards whole (rows == expected) | row count vs metadata / calendar | **4 v002 shards cut at round counts**: BTC 5m 157,000 (last close 29,923 — a 2023 price), SOL 5m 135,000, SOL 15m 64,000, ADA 15m 158,000; SPLG 1d **0 rows**. ETH 5m whole at 525,888 (diag #18108) |
| Information classes with history beyond BTC | per class, symbols with ≥ 1 y of history | funding/OI: **BTC only** (`funding_oi/BTCUSDT`, 572 KB); order flow: **BTC 5m only, forward from 2026-06-04** (37,722 rows); news: GDELT corpus **not persisted** (NEWS-ALPHA-CORPUS); macro: FRED adapters with **no caller** |
| First-passage labels that are measurements | share of SL/TP ties resolved by finer data, not the SL-first rule | **0%**: every barrier labeller resolves a bar touching both levels as SL-first (`ml/datasets/labeling/triple_barrier.py:140-209`, `src/research/triple_barrier.py`); no 1m resolution anywhere |
| Train/serve feature parity verified | `scripts/ml/replay_parity.py` run read | **0 runs read** (`ML-PARITY-HARNESS` landed_unproven) |

## 2. What exists today (MEASURED from code, config and the trainer diag, 2026-10-14)

### 2.1 Ingest

| # | path | source → symbols × grain | depth / cadence | lands |
|---|---|---|---|---|
| 1 | live tick (`src/main.py:_resolve_tick_symbols` → `src/runtime/market_data.py`) | Bybit, Alpaca (`iex` default), IB, OANDA → 24 distinct symbols in `config/accounts.yaml` | 200 bars/strategy, every tick | **not persisted** (≤ 60 s in-memory cache; no candle table exists — `CREATE TABLE … candle|ohlcv|kline|bar` matches 0) |
| 2 | `scripts/ops/build_trainer_datasets.sh` → `market_raw` (`ml/datasets/adapters/bybit_offvm.py`) | Bybit V5 → BTC/ETH/SOL 5m+15m+1h, ADA/AVAX/XRP 15m | rolling 5 y, daily (`ict-trainer.timer` 00:30Z) | trainer `datasets-out/market_raw` (1.2 GB) |
| 3 | same, `yfinance_offvm` | Yahoo → MES 5m (58 d) + 1d; 11 ETFs 1d from 2015 | daily | trainer `market_raw` |
| 4 | `scripts/ml/fetch_funding_oi.py` | Bybit → BTCUSDT funding 8h, OI 1h | 5 y, daily | trainer `funding_oi/BTCUSDT` |
| 5 | `scripts/ml/orderflow_capture.py` (always-on service) | Bybit book depth 5 + trades, polled 2 s → BTCUSDT | forward only | trainer `market_microstructure/BTCUSDT/5m` — **raw book and trades discarded** |
| 6 | `scripts/ops/refresh_candle_history.py` | Bybit → SOL/XRP/ETH 15m CSV | 03:20Z daily | trainer `data/*.csv` |
| 7 | `pull_mes_ibkr_history.sh` | IB → MES 5m/15m, 365 d | 23:30Z | live VM `/data/bot-data/ibkr_datasets` |
| 8 | news live (`src/news/`) | 7 RSS feeds + NewsAPI | per tick | decisions only (`news_decisions.jsonl`) |
| 9 | `scripts/research/news_hist_fetch.py` | GDELT GKG 2.0 | from 2015; **not scheduled** | scratch only (NEWS-HIST-REPLAY corpus lost) |
| 10 | `scripts/macro/pm_snapshot_collect.py` | Kalshi + Polymarket, 4 markets | 4×/day | trainer `pm_snapshots/` |
| 11 | `econ-calendar-produce.yml`, `macro-valuation-snapshot.yml` | FMP/FXStreet; Stooq | daily | `comms/macro/` (committed) |
| 12 | COT, crypto-signals, EIA/Open-Meteo, **FRED** adapters | CFTC, Bybit, EIA, FRED | dispatch-only; **FRED has no caller outside tests** | runner / `comms/macro` |
| 13 | `fetch_binance_vision.py`, `fetch_backtest_candles.py`, `fetch_qashdev_btc_archive.py` | Binance Vision → **5m** any symbol | per research run | **runner scratch, re-fetched every run** |
| 14 | `ml-data-export-kaggle.yml` | trainer rsync → BTC/ETH/SOL 15m + 1h | daily 06:40Z | private Kaggle `metis-market-data` (market-only; integrity-withholding) |
| 15 | HF: `scripts/hf_upload_large_files.py`, `hf-cron.yml` | manual | — | HF dataset `bentzbk/ict-trading-bot-btcusdt-1m` (manual, source CSV not in repo) |

Verified absent (grep over `src scripts ml config .github deploy`, positive controls `data\.binance\.vision` → 10 files, `fetch_order_book` → hits): coinglass, glassnode, cryptoquant, deribit, tardis, kaiko, polygon.io, databento, IB tick/depth requests, persisted websocket streams, social media, any persisted tick data.

### 2.2 Process and label

| what | grain | label | locator |
|---|---|---|---|
| `market_features` (96 manifests target `regime_label`) | per bar | forward-window vol > threshold; `trend_regime_label` (forward efficiency ratio); `direction_label` | `ml/datasets/families/market_features.py:142-146`; **7.9 GB of 9.6 GB** of `datasets-out`, versions v001..v901 incl. one-offs |
| `setup_candidates` | per event | triple barrier pt = sl = 1.0 × vol, 10 bars, **SL wins ties** | `label_version triple-barrier-v1`; nightly only with `ICT_BUILD_XSYM=1` |
| `exit_candidates` | per in-trade bar | `should_hold` triple barrier β = 2, 10 bars | manual, `ml/configs/exit-policy-v1.yaml` (ETH 5m) |
| `exit_head` (M20 E0, `scripts/ml/build_exit_head_dataset.py`) | **per (trade, bar)** | `holding_pays = final_R − mark_R(t) ≥ 0.25` — a truncation observable, **no barrier re-simulation** | trainer `exit_head/`: **165k path rows** (5m ict_scalp 70,891; 1h donchian 34,919; 2h pullback 30,512; 15m ict_scalp 28,683; live rows 3–803 per family) |
| `build_intrabar_exit_panel.py` (M30×M20) | per (trade, bar) | triple barrier + time stop from bar t | research panel, candles fetched per run |
| trade_outcomes / setup_labels / conviction_meta / review_journal | per trade | `won`, `r_multiple`, grades | OURS data, never leaves the trainer (`ml-data-classification-2026-10-13.md`) |
| harness `--emit-trades` | per trade | `net_r`, `mfe_r` (lagged lower bound); **`mae_r` only in ict_scalp's nested `meta`** | `scripts/backtest_trend.py:1016-1083` etc. |
| live `position_telemetry` | one upserted row per position | peak_r, giveback_r, bars_since_peak; **no MAE, no history** | `src/runtime/position_telemetry.py:248-283` |

**Correction to the trigger's premise (field beats comment).** "No per-bar in-trade path exists anywhere" is too strong: 165k per-(trade, bar) rows exist on the trainer under `exit_head/`, and two research builders re-walk paths from candles. What is true: none of them is **persisted at a grain finer than the leg's own bar**, none carries the **stop and target in force** at each bar, none is **first-passage-labelled with ties resolved**, and none is reachable off the trainer (OURS-classified). Those four gaps are what this programme closes; the harness-native path emit is the exit lane's row (`EXIT-PATH-EMIT-OFFLINE`).

**An alignment finding the exit lane needs (MEASURED this session, one leg).** The committed ledgers' `entry_time` is the **open-time label of the entry bar** (entry fills at that bar's close). On `trend_donchian_xrp_4h` (1460 d ledger, 44 trades with a pre-exit window), walking Binance 1m from `entry_time` breaches the initial SL strictly before the exit bar on **27/44** trades; walking from `entry_time + 1 bar` on **0/44**. A re-walk that starts at `entry_time` reads 4 h of pre-entry price on a 4h leg. `scripts/research/intrabar_label_fidelity.py` uses offset 1 and reports both offsets per leg as its control; `scripts/research/first_passage.py` (PR #18104, unmerged) should be checked against the same control before its units run.

### 2.3 Storage and compute (MEASURED unless marked)

| resource | state |
|---|---|
| trainer disk | 97 GB root, **42 GB used, 56 GB free** (diag #18107). `scripts/ops/trainer_dataset_gc.py`'s docstring ("45 GB at 86%") predates the 2026-09-29 resize (TRAINER-DISK) — stale prose |
| OCI block storage | **194 of 200 GB free-tier tenancy used** (TRAINER-DISK note, 2026-09-29) — growing OCI disk is no longer free |
| trainer CPU | 1 OCPU / 6 GB, saturated (drift retrain 63.7% of service CPU; 02 § 2) |
| runner | 4 vCPU / 16 GB / 6 h, free; reaches `data.binance.vision` (INFERRED from committed fetchers; this sandbox reached it, measured) |
| Kaggle | private `metis-market-data`; kernel mount verified 20/20 files; **runner download 404s** (ML-DATA-RUNNER-FETCH) |
| storage format | JSONL throughout `datasets-out` (BTC 1m: 572 MB for 3.24M rows ≈ 177 B/row) |

## 3. The gaps, ranked (each with its number)

1. **No refreshed sub-5m archive, so first-passage labels on fine-grained legs are conventions.** Finest refreshed grain 5m; 1m only as a stale BTC/MES v001; every labeller resolves ties SL-first. *How much that matters is Q1's measurement* (§ 4) — not assumed.
2. **Shards are silently cut.** 4 of the crypto v002 `market_raw` shards end at round counts with 2023 prices (BTC 5m 157,000 vs ETH 5m 525,888 over the same window); SPLG 1d is empty. Every 5m BTC/SOL unit and every ADA 15m unit reads a truncated history.
3. **Information classes stop at BTC.** Funding/OI and order flow exist for BTC only (flow forward-only since 2026-06-04, raw discarded); ETH/SOL/ADA/AVAX/XRP have neither, though Binance Vision publishes all of it free (§ 5).
4. **Nothing is shared off the trainer except 2 timeframes × 3 symbols.** Research reruns re-fetch candles to scratch; GDELT was fetched and lost; HF holds one manual file.
5. **No catalog of the stores.** Nobody could say, before this audit, that a 572 MB BTC 1m file sits stale on the trainer or that four shards are cut — the signals catalog covers what is *read*, not what is *stored*.

## 4. Questions in dependency order

| Q | question | test / build | rule (on the unit) | unlocks | carried by |
|---|---|---|---|---|---|
| **Q1** | Is the SL-first tie convention a material label error, per family? | 1m re-walk of the committed ledgers, fixed bracket K ∈ {1,2,3} R | NEEDED if mislabel share ≥ 2% on any eligible family at any K; NOT_NEEDED if < 0.5% everywhere | sets the priority of the 1m archive and the tie-aware label library | **`RQ-20261014-da7a-01`** (queued, cpu_long) |
| **Q2** | Archives: persist 1m klines + perp metrics + funding for every crypto roster symbol, whole and checked | build | done when manifest row counts equal the calendar minus a gap ledger | Q3, Q4, Q5, the exit lane's re-walks without re-fetch | **`DATA-KLINE-ARCHIVE`**, **`DATA-DERIV-ARCHIVE`** (rows) |
| **Q3** | Is Binance UM 1m an adequate proxy for Bybit linear for first-passage labels? | label agreement Binance vs Bybit 1m on the same trades | PASS if label agreement ≥ 98% per family | whether the free archive can label our venue's trades | **`blocked/RQ-20261014-da7a-02`** (on DATA-KLINE-ARCHIVE) |
| **Q4** | Tie-aware, versioned labels | label library emits `tie_ambiguous` + 1m resolution; per-bar first-passage label family persisted | build | IN-TRADE-EXIT-MODEL training rows; M23 meta-labels | **`DATA-LABEL-TIES`**, **`DATA-INTRADE-LABEL-STORE`** (rows) |
| **Q5** | Do the new information classes carry information for our heads? | OI change, taker buy/sell imbalance, top-trader long/short as features for giveback (Q3.1 of 02) and the 1h regime heads | PASS if paired log-loss improvement CI < 0 on ≥ 2 of 3 symbols | Q5 of programme 02 beyond BTC | **`blocked/RQ-20261014-da7a-03`** (on DATA-DERIV-ARCHIVE) |
| **Q6** | Stores whole and catalogued | data catalog + integrity check over the trainer listing; extend ML-SHARD-TRUNCATED to the 5m/ADA shards | build | every unit's population statement | **`DATA-CATALOG`** (row); `ML-SHARD-TRUNCATED` (note added) |
| **Q7** | Format and placement: Parquet + GC, and where the archive lives off the trainer | measured sizes → placement decision | build (Tier-2: deletes on the trainer) | headroom for Q2 without new OCI spend | **`DATA-STORE-PARQUET-GC`** (row) |
| Q8 | Serve parity | already carried | — | — | `ML-PARITY-HARNESS`, `ML-PRODUCER-FUNDING` (not re-filed) |

## 5. Open-source and free sources, ranked by what they unblock

Sizes MEASURED by HEAD request from this sandbox on 2026-10-14 (BTCUSDT, 2026-10-01 daily file unless noted). Licence column states what the source publishes; **"no open licence" means the data may be used internally but must not be re-published** — so it goes to private stores only (private Kaggle dataset, trainer), never a public release asset.

| rank | source | what | size | licence / cost | unblocks |
|---|---|---|---|---|---|
| **A1** | Binance Vision `data/futures/um/{daily,monthly}/klines/<SYM>/1m` | USD-M perp 1m OHLCV, since listing (2019+) | 61.8 KB/day ≈ **22.6 MB/yr/symbol** zipped → 6 symbols × 6 y ≈ 0.8 GB | free; Binance Terms of Use, no open-data licence | (a) per-bar paths at 1m, tie resolution (Q1, Q4) |
| A2 | Bybit V5 public klines (`interval=1`) | our venue's 1m | REST, paged 1,000 rows (the page size behind gap 2's round counts — INFERRED) | free; Bybit ToU | (a) venue-fidelity check (Q3) |
| A3 | Binance Vision `aggTrades` / Bybit `public.bybit.com/trading` | tick-level trades | **15.1 MB/day** (Binance) / **54.8 MB/day** (Bybit) BTC | free; exchange ToU | (a)+(c) 1m signed-volume bars derived once, raw not kept (≈ 5.5 GB/yr/symbol raw is too large to keep) |
| **B1** | Binance Vision `futures/um/daily/metrics` | 5m OI, OI value, top-trader and global long/short ratios, taker buy/sell volume | **11.6 KB/day** ≈ 4 MB/yr/symbol | free; Binance ToU | (b) regime and meta-label heads for every symbol, not just BTC (Q5) |
| B2 | Binance Vision `futures/um/monthly/fundingRate` | funding history | 0.9 KB/month | free; Binance ToU | (b) funding features ETH/SOL/ADA/AVAX/XRP (FUNDING-OI-DATASETS-ETH-SOL's source) |
| B3 | Binance Vision `futures/um/daily/bookDepth` | depth % bands snapshot | 0.56 MB/day ≈ 205 MB/yr/symbol | free; Binance ToU | (b)/(c) liquidity regime |
| B4 | FRED (`fredgraph.csv`, reachable: DGS10 200 OK, 269 KB) | rates, curve, VIX, dollar | KB | public domain for most series; some series third-party-copyrighted (check per series) | (b) macro regime context; adapters exist, no caller |
| B5 | Alpaca historical (IEX feed free) | US equities/ETF bars incl. minute | — | free with an account; SIP history paid; no redistribution | (b) equity legs' paths (alpaca_live) |
| C1 | GDELT 2.0 GKG | global news themes and tone, 15-min files | ~40 MB/day gz (NEWS-HIST-REPLAY, measured there) ≈ 44 GB/3 y | free, unrestricted with citation | (c) news class — **owned by NEWS-ALPHA-CORPUS**, not re-filed |
| C2 | Kalshi/Polymarket public APIs | event probabilities | small | free; ToU | (c) already collected forward (PM-COLLECTOR) |
| C3 | CFTC COT, EIA | positioning, energy | small | public domain (US gov) | (c) macro sleeve (P4) |
| C4 | Hugging Face datasets | labelled financial-news sentiment (e.g. `zeroshot/twitter-financial-news-sentiment`, 6,075 downloads); **no maintained crypto 1m or crypto order-book dataset found** (`search hf://datasets "crypto 1m klines"` → 0) | — | per dataset card | (c) NLP head pre-training only; HF is a model source here, not a market-data source |
| — | Bybit order-book archive (`quote-saver.bycsi.com`) | L2 500-level snapshots | — | **UNVERIFIED**: the URL pattern tried returned 404 | (c) — not relied on |

## 6. Target architecture

```
 INGEST (free, public, idempotent, gap-ledgered)          STORE (versioned, whole, catalogued)
 Binance Vision 1m klines ─┐                              trainer  datasets-out/archive/<class>/<SYM>/<YYYY-MM>.parquet
 Binance Vision metrics    ├─► runner fetch (no creds) ──►         + MANIFEST (sha256, rows, expected rows, first/last ts)
 Binance Vision funding    │   or trainer timer (Tier-2)  private Kaggle dataset (market-only copy; ML-DATA-OFF-TRAINER)
 Bybit V5 1m (venue check) ┘                              docs/reference/data-catalog.yaml (every store, licence, owner)
 GDELT / FRED / COT / PM ──► their owners' rows                         │
                                                                        ▼
 PROCESS                                   LABEL (versioned code, one library)
 1m → leg-grain bars (same resample        triple_barrier: SL/TP/time + tie_ambiguous flag, ties resolved on 1m
 convention as the harness: open-time      first-passage per in-trade bar from (EXIT-PATH-EMIT-OFFLINE path rows
 labelled), signed volume from aggTrades   × the 1m archive) → label family `intrade_first_passage`
        │                                                   │
        ▼                                                   ▼
 FEATURE / DATASET STORE ─────────────────► TRAIN (runner / Kaggle CPU+GPU / trainer idle windows)
 market_features (+ deriv metrics for every symbol)          │
 exit_head / intrade rows                                    ▼
        ▲                                   SERVE PARITY: replay_parity.py — train row == live row on the same bars
        └──────── live producers (Tier-2) ◀─ before any head reads a new column live (ML-PARITY-HARNESS, ML-PRODUCER-*)
```

**Placement rules.** (1) Market data is public-sourced and market-only, so it may live on the runner and in the private Kaggle dataset; OURS data (journal, fills, labels joined to our trades) stays on the trainer. (2) Fetch is a runner job wherever possible (free, no credentials, no trainer CPU); only the forward append that must sit beside the trainer's builders is a trainer timer (Tier-2). (3) Archive at 1m and derive coarser grains; never keep raw ticks (A3) — keep the 1m bars derived from them. (4) Every store has a manifest with an expected row count, so "cut short" is a number, not a surprise.

**Budget (INFERRED from the measured per-day sizes):** 1m klines 6 symbols × 6 y ≈ 0.8 GB zipped / ~1.5 GB Parquet; metrics + funding ≈ 0.2 GB; 1m signed-volume bars ≈ 1 GB. ≈ 3 GB total — fits the trainer's 56 GB free and a private Kaggle dataset; it does **not** need new OCI storage. The JSONL → Parquet move of `market_features` (7.9 GB) is the larger lever on headroom.

## 7. Backlog — W1..W4 (W1 = 2026-10-14..20)

Owned elsewhere and **not re-filed**: `EXIT-PATH-EMIT-OFFLINE` and `EXIT-PATH-TELEMETRY-LIVE` (IN-TRADE-EXIT-MODEL lane, PR #18104, unmerged at filing), `METALABEL-EMIT-FEATURES` (mae_r on every emit; AI-trader lane), `FUNDING-OI-DATASETS-ETH-SOL` (dataset join; B2 is its source), `NEWS-ALPHA-CORPUS` (GDELT), `ML-DATA-RUNNER-FETCH` (runner read of the Kaggle dataset), `ML-SHARD-TRUNCATED` (repair; new evidence added as a note), `ML-PARITY-HARNESS` / `ML-PRODUCER-FUNDING` (serve parity).

### W1 (Oct 14–20) — measure the label error, specify the archive

| # | item | kind | compute / tier | status |
|---|---|---|---|---|
| 1 | `RQ-20261014-da7a-01` intrabar label fidelity *(new)* | Q1 | cpu_long runner | queued |
| 2 | `DATA-CATALOG` *(new row)*: `docs/reference/data-catalog.yaml` + `scripts/ops/data_catalog_check.py` over a trainer listing (expected rows, empty, stale, version sprawl) | Q6 | Tier-1 | queued |
| 3 | `ML-SHARD-TRUNCATED` note: the 5m/ADA/SPLG evidence | Q6 | — | noted |
| 4 | `DATA-KLINE-ARCHIVE` *(new row)*: runner-side one-shot backfill of Binance UM 1m for the 6 crypto roster symbols into Parquet + manifest, published to the private Kaggle dataset | Q2 | Tier-1 runner; Tier-2 for a trainer forward-append timer | queued |

### W2 (Oct 21–27) — archives land, venue check

| # | item | kind | compute / tier |
|---|---|---|---|
| 5 | `DATA-DERIV-ARCHIVE` *(new row)*: Binance UM metrics + fundingRate (+ bookDepth) for the 6 symbols, same manifest contract | Q2 | Tier-1 runner |
| 6 | `RQ-20261014-da7a-02` Binance vs Bybit 1m label agreement *(new, blocked)* | Q3 | cpu_long |
| 7 | `DATA-LABEL-TIES` *(new row)*: `tie_ambiguous` column + optional 1m tie resolution in both triple-barrier libraries, label_version bump, existing outputs byte-identical by default | Q4 | Tier-1 (offline labelling code) |

### W3 (Oct 28–Nov 3) — labels and information

| # | item | kind | compute / tier |
|---|---|---|---|
| 8 | `DATA-INTRADE-LABEL-STORE` *(new row, blocked on EXIT-PATH-EMIT-OFFLINE + DATA-KLINE-ARCHIVE)*: persist per-bar first-passage labels as a dataset family the exit model and M23 read | Q4 | Tier-1 builder; trainer placement |
| 9 | `RQ-20261014-da7a-03` derivatives-metrics information lift *(new, blocked)* | Q5 | auto (published data) |
| 10 | `DATA-STORE-PARQUET-GC` *(new row)*: `market_features` JSONL → Parquet, GC of one-off versions, docstring fix in `trainer_dataset_gc.py` | Q7 | **Tier-2** (trainer deletes) |

### W4 (Nov 4–10) — read, write back, re-plan

| # | item |
|---|---|
| 11 | Read da7a-01..03 against their rules; if Q1 = NOT_NEEDED, demote the 1m archive from *label prerequisite* to *information source* and say so on the rows |
| 12 | Forward-append timers proposed (Tier-2) only for stores whose W2/W3 consumer exists |
| 13 | Weekly roadmap pass: `L-DATA` `where` re-measured with the five § 1 measures |

**What would change this backlog:** Q1 NEEDED on the 4h/2h real-money families (pull #8 forward, ahead of everything but #1); Q3 FAIL (Bybit 1m becomes the label source and Binance only the information source); the exit lane's harness path emit landing early (pull #8 to W2).

## 8. What this programme does not do, and what it did not verify

- It changes no config, timer, roster or service. Every trainer timer and every delete is a Tier-2 row for a build lane with one operator OK.
- **Not verified:** that a GitHub runner reaches `data.binance.vision` (committed fetchers say so; only this sandbox was measured); Kaggle private-dataset size limits; HF private-storage limits; per-series FRED licences; the Bybit order-book archive URL; the cause of the round-count truncations (page-limit is INFERRED); the live VM's own disk.
- The § 2.2 alignment finding is measured on **one leg, n = 44**. `RQ-20261014-da7a-01` reports the control on every leg; until it lands, treat it as one leg's fact.
- The sandbox smoke of da7a-01 on `trend_donchian_xrp_4h` (n = 46) found **0** bar-level ties at K = 1, 2, 3 — one 4h leg says nothing about the 5m/15m legs, where ties are likelier. The committed record is the verdict, not that read.
