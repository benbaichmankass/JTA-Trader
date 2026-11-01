# ML feature inventory and pooled feature-store plan (2026-11-01)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`../DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ML-FEATURE-INFRA` (dispatched by Manager Session 2026-11-01a) · row `ML-FEATURE-INFRA` · roadmap `L-ML-LIVE`

**Gates this adds or changes: none.** Tier-1 document. It trains nothing, reads no held-out window (ML-BAR-ONE-READ governs the read), changes no config, and leaves ENTRY v1's go-live path as it is. Every gap below is a checklist row or a research/queue unit.

Operator, 2026-11-01, verbatim: *"20 features seems like far far far far too little for the caliber of MLs we are aiming to build - if that's the best we can do, than labelling/features infra needs to get more attention. If it's not the best we can, then why so few?"*

---

## 1. The answer

**It is neither a data limit nor a pure choice. It is an infra limit that looks like a choice.** The data is free, reachable and deep; the 20 is the output of a harness that was written to answer a different question (can a pooled bar-level model clear the point-estimate bar) and had nowhere richer to read from.

What I measured (population stated on each line; method in § 6):

1. **The data exists for the whole universe.** For the 60 frozen perps of `bp2-f4271084b120` the Binance Vision archive lists 1h klines, funding, mark-price klines, premium-index klines and aggTrades for **60 of 60** symbols, first listed month 2020-07 (median) to 2020-10 (latest start). Coverage over the ENTRY development window (2020-07..2025-09, **3,729 symbol-months**): funding 99.6%, premium index 98.0%, aggTrades 97.1%, 5m metrics (open interest, long/short ratios, taker ratio) **71.3%**, order-book depth bands 51.9%, top-of-book 19.3%.
2. **ENTRY already downloads the richest free column set and throws it away.** `scripts/research/ml_decision_entry.py` `_fetch_month` does `df.iloc[:, :6]`, keeping open/high/low/close/volume of the 12 columns Binance ships. The six discarded columns include `taker_buy_volume`, `count` (trade count) and `quote_volume`. I read them from files: BTCUSDT 2020-01 (744 bars), SOLUSDT 2020-09 (401), BTCUSDT 2025-06 (720), DOGEUSDT 2022-03 (744): taker-buy volume and trade count are **non-zero on every bar** (mean taker-buy share 0.47 to 0.50). So taker-flow features are available **for the same 777,861 decision rows at zero extra download cost**.
3. **The rich feature code exists but is not what ENTRY reads.** `ml/datasets/families/market_features.py` declares a **108-column** per-bar schema (funding, OI, order flow, macro, cross-asset, 32 TSFM embedding, 6 forecast, 16 corpus-embedding columns, volatility estimators). It is per-symbol and per-timeframe, built on the trainer, and for the funding/OI and order-flow families populated for **BTC only**. Where a side-stream is absent it writes `0.0` on every row, a collapsed state: "no data" and "value zero" are the same number. ENTRY re-implements 20 OHLCV features inline instead, because the pooled 60-symbol path has no shared store to read.
4. **So the binding constraints are infra:** no archive of the non-OHLCV Binance streams for the 60 symbols, no pooled as-of join, no feature registry shared by train and serve, no serve-parity check for any non-OHLCV family. Section 5 lists each as a row or unit.

**What this does not say.** More features is not more edge. I measured availability, coverage and point-in-time safety, not signal. Whether any family adds held-out edge is the pre-registered ablation `RQ-20261101-fs01-01` (dev folds only). If the ablation shows OHLCV-only is as good, 20 was the right number for that question, and the infra is still worth having because BRACKETS and HOLD/ADJUST/CLOSE need state (positioning, flow) that price alone cannot give them.

---

## 1a. Manager addenda, 2026-11-01 ~10:48Z (operator, verbatim)

> *"we should already have a data feed/features catalog, so I don't know why we need to be so lean just to get an ML off the ground - and if that's just to have the prototype live, then we need to make sure there's a plan for feeding and retraining on more and better data (now, not an unspecified date in the future), with regular reviews from claude to see that it's progerssing correctly. 20 features is a regression equation, not algorithmic trading"*
>
> *"if we're going live then iterating the entry ML, then we're talking about a timeline in hours, not days/weeks"*

**A catalog exists, and it explains the 20.** `docs/reference/signal-catalog.yaml` has 335 inputs; `docs/research/signals-catalog.yaml` has 67 families. Both catalog what the system **reads**, not what is **stored or available**. Three measured consequences:

1. **ENTRY's 20 features are in neither catalog** (grep of `xs_rank_ret24 | ret_168 | btc_vol24 | breadth_up24 | rel_vol` in the 335-input file: **0 matches**). `scripts/research/ml_decision_entry.py` is a standalone harness; `signal-catalog-guard` keys on manifests, strategy modules and config ids, so the harness is invisible to it. That is why ENTRY v1 could be lean without anyone seeing the catalog's other rows.
2. **The catalog's crypto market-structure features are `market_features` columns for BTC/ETH/SOL**, not pooled ones (105 `ml_feature` entries, mapped below). Nothing in the catalog says what the 60-perp universe could be fed.
3. **The per-STORE catalog the operator expects is row `DATA-CATALOG`, dropped in the 2026-10-29 bulk reset as "value unknown".** The operator has now stated its value (quote above). It is **re-opened** by this lane (state `queued`, Tier 1) and its scope is widened to include the Binance Vision streams of § 2a, which are the only stores that can feed ENTRY v2 in hours.

### Catalog → candidacy map (335 inputs; counts from the file, `ml_feature` split read id by id, all 105 assigned)

Readiness classes: **NOW** = history for the 60 perps and a live computation from the 1h klines the ENTRY adapter already reads; **BACKFILL** = history fetchable from the free archive (hours, measured § 7), live path exists or is a small build; **COLLECT** = needs a new live collector or has no history; **NO** = outside operator scope (sizing/risk) or not a market-structure input.

| Catalog group (n) | ENTRY | BRACKETS | HOLD/ADJUST/CLOSE | Readiness |
|---|---|---|---|---|
| ml: OHLCV returns, vol estimators, hour, dow (11) | yes (v1 uses a subset) | yes | context | **NOW** |
| strategy/candle (7) and strategy/derived_indicator (35: ATR, ADX, Donchian, Bollinger, Keltner, squeeze, VWAP, sweeps, FVG, body/wick) | yes, as shape features | yes (ATR/ADX set brackets) | partly (`since_entry_window`, `open_r_mfe`) | **NOW** (pure functions of candles). ~25 of the 35 are price-structure; the rest are strategy-state (`pairs_*`, `bars_elapsed`) |
| ml: cross-asset peer (13) | yes, redefined as pooled cross-sectional ranks | yes | context | **NOW** (the peer pairing is per target symbol; the pooled version is family 4 of § 4) |
| ml: funding and OI (5) | yes | yes | yes | **BACKFILL**: funding 99.6% and OI 71.3% of dev symbol-months (§ 1); live OI exists (`src/runtime/oi_feed.py`, Bybit 5m, point-in-time `known_at`, but **not yet observed on the VM**); no live funding producer |
| strategy/feed `oi_bybit_5m` (1 of 11) | yes | yes | yes | **BACKFILL** live half: the feed exists for the E4 leg's symbol only; 60-symbol scope is a Tier-2 extension |
| ml: order flow (6) | maybe | maybe | maybe | **COLLECT**: BTC only, forward from 2026-06-04; Binance bookDepth (2023+) is the historical proxy |
| ml: macro (7), regime_macro/macro_series (54), valuation (10), event_calendar (20) | weak at 1h–24h | no | no | **BACKFILL**: daily PIT stores in `comms/macro` (COT 10,093 rows 1988→2026-07-17, lag verified); FRED has no caller |
| regime_macro/news (31) | weak | no | event risk only | **COLLECT**: GDELT corpus not persisted (`NEWS-ALPHA-CORPUS` dropped) |
| ml: in-trade path (31: `unrealized_r`, `mfe_r_so_far`, `mae_r_so_far`, `bars_since_peak`, `giveback_r`, `dist_to_stop_atr`, …) | no | no | **yes, the HOLD/ADJUST/CLOSE state** | **BACKFILL/COLLECT**: pure functions exist (`intrabar_features.py`), per-bar path store does not (`DATA-INTRADE-LABEL-STORE` blocked, `PATH-FLOW-JOIN` landed_unproven) |
| ml: forecast fc (6), embeddings (2 patterns = 48 columns) | later | later | later | **COLLECT**: BTC/ETH/SOL shards only; opaque to the leakage test |
| regime_input (32), ml_output (3), crowding (1), cross_asset (6) | as derived context | as derived context | as derived context | **NOW** where computed from candles; the 15 `cell.*` entries are policy cells, not features |
| ml: account/risk context (5), conviction (4), strategy context (8), present flags (3) | **NO** | **NO** | **NO** | Operator scope: no sizing, no risk features, pooled across strategies. Present flags are reused by the new store |

**Why v1 used 20 of them, in one line:** it needed a pooled 60-symbol answer to one question, the `market_features` columns are per-symbol and trainer-resident, and the harness was not governed by the catalog, so it computed the OHLCV subset inline from the Binance klines it was already fetching and dropped the rest of each kline row.

## 1b. Dated plan: ENTRY v2 in hours, then the rest (all times UTC, 2026-11-01 unless stated)

**Rule for the whole plan.** Anything not needing a backfill or a new live collector is in v2. What needs either is a later *increment*, never a blocker. Every increment is its own pre-registered model with a stated variant count (ML-BAR-ONE-READ): **dev folds may be read repeatedly; a forward window is read once per model.**

**Measured physical limits** (§ 7): archive throughput ~20 to 27 files/s at 16 workers; 1h klines + funding + premium for 60 symbols = 3 × 4,500 monthly files, **~3 to 4 min each stream**; 5m metrics = **106,800 daily files, ~70 min**; 1m klines = ~138,000 daily files, ~95 min and ~8 GB; bookDepth = ~84,000 daily files and ~38 GB (bandwidth **not measured**, so not scheduled). Forward evidence accrues at ~31 scored decisions per day (c692-01: 11,240 over 365 days), so a window needs ~10 days to clear the n = 300 floor. The forward window after c692-01's read is 2026-10-01..2026-10-31 (**W1**, expected n ~ 950).

| When (UTC) | Step | Owner row / unit | Physical reason it takes this long |
|---|---|---|---|
| 11:30 | This PR lands: plan, rows, units, registered rules | `ML-FEATURE-INFRA` | — |
| 11:30 → 11:50 | Backfill A starts in parallel: 12-column 1h klines, funding, premium index for 60 symbols | `ML-FS-ARCHIVE` | 3 streams × 4,500 files at ~20 files/s |
| 11:30 → 12:45 | Backfill B: 5m metrics (OI, long/short, taker ratio) for 60 symbols, sorted on read | `ML-FS-ARCHIVE` | 106,800 files at ~25 files/s |
| 11:30 → 13:00 | Harness: feature builders for families 1, 2, 4, 5 (+3 when B lands), leakage self-test (a forward-shifted column is refused), `run-family-ablation` and `run-v2` subcommands | `ML-FS-ENTRY-V2` | Code and tests, not data |
| 13:00 → 14:15 | **Dev-fold ablation**: arms A baseline, B..F one family each, G all of B..F, run as parallel jobs | `RQ-20261101-fs01-01` | 8 arms × 8 folds × 2 sides of LightGBM at c692-01 size; ~60 min wall if arms fan out (INFERRED from c692-05's 60 min per recipe; first run measures it) |
| 14:15 | Registered selection: v2 feature set = baseline + every family ADMITTED by the fs01-01 rule (delta ≥ +0.010 R and positive in ≥ 6 of 8 folds) | rule in fs01-01 | — |
| 12:00 → 14:00 | `HOLDOUT-LOCK` (read-once script that logs every read of the held-out window) and the `ML-BAR-ONE-READ` mechanics (one model per increment, variant count in the record). **Must be in place before 14:30**; v2's read goes through it | `HOLDOUT-LOCK`, `ML-BAR-ONE-READ` (assigned to this lane by the manager, 11:07Z) | Code and a self-test that refuses a second read |
| 14:30 → 15:15 | v2 fit on all data through 2026-09-30 (7-day embargo), tau chosen on dev, then **one read on W1** | `RQ-20261101-fs02-01` | One fit plus a 200-draw random baseline and the three audit benchmarks (time-series momentum, cross-sectional momentum, funding carry; reported beside v2, not gating) (~60 min INFERRED) |
| 15:30 | Verdict written, manager woken. Variants read on W1: **1** (v2). Dev-fold arms are not forward reads | `RQ-20261101-fs02-01` | — |
| 18:00 | Serve-parity verdict per family (Binance-trained vs Bybit-served) from an environment that reaches both venues | `ML-FS-SERVE-PARITY` | Bybit REST is HTTP 403 and Binance fapi HTTP 451 from this sandbox, so it needs the trainer or a runner |
| 2026-11-02 12:00 | BRACKETS re-scored on the v2 feature set | `ML-FS-BRACKETS-HOLD` | Needs v2 features and the c692-01 summary |
| 2026-11-02 18:00 | Held PR for the manager (Tier 2): weekly retrain timer for the live ENTRY model, first scheduled run 2026-11-08 04:00 | `ML-ENTRY-RETRAIN-CADENCE` | Runtime and timer change |
| 2026-11-03 12:00 | HOLD/ADJUST/CLOSE state features (in-trade path families) read from the same store | `ML-FS-BRACKETS-HOLD` | Per-bar path store (`DATA-INTRADE-LABEL-STORE`) |
| 2026-11-04 | Increment v3: add positioning (family 3) if not already admitted; own pre-registered unit, **W2 = 2026-11-01..2026-11-10, earliest read 2026-11-11**, variants stated | `ML-FS-ENTRY-V2` | Forward-window accrual: ~10 days to n = 300 |
| 2026-11-08 (Sun) | First weekly ML review with the four graded lines below | `ML-WEEKLY-REVIEW-LINES` | Existing Sunday `/ml-review` cadence |

**Standing retrain cadence.** Weekly, Sunday 04:00Z, refit the live ENTRY model on all data through the previous day minus embargo, publish the artifact with feature list, sha and data-through date, and write a freshness line the review grades. It is a workflow or timer (Tier 2, held PR), not a promise; the row's `due_by` is 2026-11-02T18:00Z.

**Weekly Claude review.** The existing Sunday `/ml-review` gains four graded lines, each a number with its population, never prose: **(1) data coverage**: per feature family, present share of the last 7 days' decision rows per symbol; **(2) feature count in use**: columns the live model reads versus columns the registry holds; **(3) retrain freshness**: age of the live artifact's data-through date; **(4) live decision-grade versus held-out**: mean net R per decision live over the week next to the registered held-out figure, with n. Landed in this PR as an edit to `.claude/skills/ml-review/SKILL.md`.

## 2. Inventory: every source

**Reading key.** *Depth* is first and last timestamp read from file contents unless marked *listed* (first and last file name in the archive listing; contiguity between them is **not** gap-checked). *Live today* means a collector exists that a served model could read at decision time. *PIT* is point-in-time safety. Backfill cost uses today's HEAD sizes for BTCUSDT (an upper bound for smaller alts); population = 60 frozen perps.

### 2a. Binance Vision USD-M perpetual archive (public, keyless, `data.binance.vision`; reachable from this sandbox, HTTP 200)

| Source | What it measures | Symbols | Depth (first → last) | PIT | Live today? | Backfill cost (60 symbols) |
|---|---|---|---|---|---|---|
| **1h klines, all 12 cols** | OHLCV plus quote volume, trade count, taker-buy base and quote volume | 60/60 | **read**: BTC 2020-01-01 00:00 → 2026-09-30 23:00; SOL 2020-09-14 07:00 → …; **listed** first 2020-07 median, latest start 2020-10, last 2026-09 (monthly; Oct 2026 is in the daily set) | Safe at bar close (`open_time` + 1h). Features may use bar t only after its close | **Partly.** OHLCV: ENTRY v1 adapter spec computes from Bybit 1h klines. **Taker split: not shown to exist on the Bybit kline feed (UNVERIFIED; Bybit REST returned HTTP 403 from here)**; Binance live REST returned **HTTP 451** from here, reachability from the VM unknown | 37.4 KB per symbol-month → **~170 MB** for 75 months (≈ what ENTRY fetches today) |
| **fundingRate** | Settled funding at `calc_time` (8h cadence; `funding_interval_hours` column carries it) | 60/60 | **read**: BTC 2020-01-01 00:00 → 2026-10-31 16:00 (93 rows per month); 11 symbols end early (delisted: OMG, WAVES, BAL, BLZ, FTM 2025-06; DEFI 2025-08; MKR 2025-09; FLM 2025-11; LRC 2026-03; ICX, STORJ 2026-08) | Safe if joined as-of `calc_time` ≤ bar close. Do not use the interval's *predicted* rate | **No.** `ML-PARITY-HARNESS` read: funding features 0% present live (BTC svble head, trainer diag #18883, 2026-10-18; cited, not re-read) | 0.9 KB per month → **~4 MB** |
| **premiumIndexKlines 1h** | Perp-vs-index premium (basis), OHLC. Volume/taker columns are all zero (read: 0 of 720 bars) | 59/60 (XLMUSDT listing call failed once, **not retried**) | **read**: BTC 2020-01-01 → …; listed 2020-07..2020-10 → 2026-09 | Safe at bar close | No | 15.9 KB per month → **~72 MB** |
| **markPriceKlines 1h** | Mark price OHLC | 60/60 | **read** BTC 2020-01; listed → 2026-09 | Safe at bar close | No | ~same as klines, **~170 MB**; low value beyond premium |
| **metrics (5m)** | Open interest (contracts and USD value), top-trader long/short ratio (count and position), account long/short ratio, taker buy/sell volume ratio | 58/60 listed (ETHUSDT call failed once, **not retried**; TRBUSDT listing returned a stray `…-metrics-1993.zip` key) | **read**: BTC 2021-12-01 00:00 → 2026-10-31. **Listed first 2021-12-01 for every symbol** (no metrics before it). Delisted symbols end 2024-07 .. 2026-01 | **Ambiguous:** `create_time` is a snapshot stamp whose window convention is undocumented here. Treat as the end of the 5m window and lag one step (conservative). **Data-quality finding:** BTCUSDT daily files are exactly regular (288 rows, 100% 300 s steps) on the 8 sampled days 2022-06-15, 2023-06-15, 2024-06-15, 2025-06-15, 2026-03-15, 2026-06-15, 2026-06-30, 2026-07-15, but **irregular on the 7 sampled days 2026-08-15, 08-31, 09-01, 09-15, 10-15, 10-30, 10-31** (share of 300 s steps 4% to 23%, gaps up to 20 h; on 2026-10-15 the file is unsorted, `is_monotonic_increasing` False, with 288 distinct stamps). BTCUSDT only, 15 sampled days, not a full scan. A reader must sort and as-of join with a tolerance; the break is between 2026-07-15 and 2026-08-15 | **No** (Bybit/Binance live equivalents unverified) | 11.0 KB per symbol-day → **~1.2 GB** for ~1,780 days |
| **bookDepth** | Bid/ask depth and notional at ±1..5% of mid, ~30 s snapshots (28,560 rows on the day read) | 60/60 | **read**: BTC 2023-01-01 00:06:05 → 23:53:31; **listed first 2023-01-01 for every symbol**; 49 symbols reach 2026-10-31 | Safe per snapshot; resample by last-in-bar | No (our own capture holds BTC only, see 2b) | 454 KB per symbol-day → **~38 GB** for ~1,400 days. Stream-reduce to hourly imbalance and drop the raw |
| **bookTicker** | Top-of-book quotes | 60/60 | **listed 2023-05 → 2024-04 only** (12 months) | Safe | No | 1,982 MB for BTC 2023-05 alone. **Not worth it** |
| **aggTrades** | Every aggregated trade | 59/60 listed | **listed** 2020-07..2020-10 → 2026-10 (BTC monthly set begins 2020-01) | Safe if bucketed by trade time | No | 8.4 MB per BTC-day (6.0 MB SOL). ~0.9 TB if kept; only stream-reduced bar aggregates are worth keeping |
| **klines 1m** | Same 12 columns at 1m | 60/60 (not listed one by one) | 59.6 KB BTC-day; row `DATA-KLINE-ARCHIVE` (dropped 2026-10-29) | Safe | No | ~8 GB zipped for 60 symbols × ~2,300 days (BTC-size upper bound). **Needed for tie-resolved first-passage labels** (`DATA-LABEL-TIES`) |

**Data-quality finding, delisted contracts (full scan, 2026-11-01).** Reading all 4,500 monthly kline files of the 60 symbols (3,235,052 rows; 51 files not found, symbols listed after 2020-07), I flagged every month in which **every bar has volume 0 and one constant close**. **11 of 60 symbols have frozen months**, and they start *before* funding ends: OMGUSDT 20 months from 2025-02, WAVESUSDT 27 from 2024-07, BLZUSDT 21 from 2025-01, FTMUSDT 20 from 2025-02, BALUSDT 17 from 2025-05, DEFIUSDT 13 from 2025-09, MKRUSDT 12 from 2025-10, FLMUSDT 10 from 2025-12, LRCUSDT 6 from 2026-04, ICXUSDT and STORJUSDT 1 (2026-09). Several of these months fall inside the ENTRY development window. ENTRY removes frozen rows only *incidentally*, because 0/0 makes `vol_ratio` NaN (`dropna` at line 305); there is no explicit mask. `scripts/research/vision_streams.py` now flags them in the manifest and `ml_entry_v2.py` masks them explicitly. Why 7 symbols are absent from c692-01's held-out ("53 of 60") I did not verify (it needs the held-out table).

### 2b. Repo-side sources

| Source | What it measures | Symbols | Depth | PIT | Live today? | Backfill cost |
|---|---|---|---|---|---|---|
| `ml/datasets/adapters/bybit_funding_oi.py` + `scripts/ml/fetch_funding_oi.py` | Bybit V5 funding (8h) + OI (1h) side-stream | BTCUSDT on the trainer; ETH/SOL row `FUNDING-OI-DATASETS-ETH-SOL` queued | Trainer store `funding_oi/BTCUSDT` (572 KB), **MEASURED 2026-10-14 by lane DATA-INFRA-PROGRAMME (trainer diag #18108); not re-read by me, no trainer egress** | Designed past-only (as-of join, zscore over 168 bars) | **No live producer** (`ML-PRODUCER-FUNDING` queued). Off-VM guard refuses to run on the live VM | Superseded by the Binance archive for 60 symbols |
| `scripts/ml/orderflow_capture.py` (+ `deploy/trainer/ict-orderflow-capture.service`) | Per-5m-bar OFI, taker buy/sell volume, relative spread, microprice deviation | **BTCUSDT only** | Forward-only from 2026-06-04, **37,722 rows at 2026-10-14** (diag #18108, not re-read); raw book/trades discarded by design | Past-only per bar | Collected on the trainer only; never on the live VM (WS9). Whether it is still running today: **not re-read**; `trainer-capture-watch` is the owner | No history before 2026-06-04 exists in our store; Binance `bookDepth` (2023+) and `aggTrades` are the historical proxy |
| `src/research/intrabar_features.py` | In-trade path state: running MFE/MAE in R, giveback, bars held, distance to stop in ATR, in-trade vol ratio, taker imbalance (last bar and in-trade mean) | Any symbol with candles | Pure functions; the taker features need the `taker_buy_base` column that ENTRY discards | Strictly past-only by construction (path = bars entry+1..t) | Telemetry holds peak_r and giveback only, **no path history** (programme 06 § 2.2). Rows `DATA-INTRADE-LABEL-STORE` (blocked), `PATH-FLOW-JOIN` (landed_unproven) | n/a |
| `market_features` family (108 columns) | Volatility estimators (Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang), funding/OI (5), order flow (6), macro (7), cross-asset peer (16), TSFM embedding (32), forecast (6), corpus embedding (16), plus labels | BTC/ETH/SOL (5m/15m/1h); ADA/AVAX/XRP 15m | Trainer-resident; 4 shards cut at round counts and SPLG 1d with 0 rows (programme 06 § 1, diag #18108) | Side-streams carried as-of, past-only | Per-symbol serving only for the shadow heads; missing side-streams written as `0.0` | Not applicable (not the pooled path) |
| `market_sequences` family | Causal windows over `market_features` for the TCN | as `market_features` | as parent | as parent | No | n/a |
| Macro: `src/…/macro_features.py`, FRED adapters | VIX level/zscore/term slope, DXY, UST10y, 3m-10y slope (7 columns) | Market-wide | FRED adapters have no caller outside tests (programme 06 § 2.1 row 12) | Daily, one-day-lagged by the producer | No | Free |
| `comms/macro/cot_snapshots.jsonl` | CFTC weekly large-speculator positioning, cheap-score percentile | **7 ETF proxies** (GLD, SPY, IEF, UNG, CPER, FXE, …), not crypto | **read**: 10,093 rows, 1988-03-03 → 2026-07-17 | **Verified**: all 10,093 rows carry `observed_at` = report date + 3 days (release lag), 0 rows at lag 0 | Dispatch-only | Committed |
| `comms/macro/valuation_snapshots*.jsonl` | Real yield, credit risk, value scores for GLD/IEF/SLV/SPY/TLT/credit_risk | 6 series | **read**: live file 2026-07-23 → 2026-10-31 (900 rows); backfill 2005-01-01 → 2026-10-24 (10,251 rows) | Stamped `observed_at` | Daily workflow | Committed |
| `comms/macro/econ_calendar_*` | Economic release calendar and surprise inputs | event-level | **read**: live 2026-07-29 → 2026-11-01 (43,152 rows); backfill 1951-02-13 → 2026-07-30 (9,968 rows) | Calendar is known ahead; surprise only after release | Daily workflow | Committed |
| `scripts/macro/crypto_signals_data.py` | Funding extreme, OI, perp-spot basis percentile for BTC/ETH/SOL | BTC/ETH/SOL | Rolling window from the Bybit public API; no committed history found in `comms/macro` | Day-D reading stamped `observed_at` D | Off-VM, dispatch-only | Superseded by the Binance archive |
| Live bar feed (`src/runtime/market_data.py`) | OHLCV for roster symbols | 24 distinct roster symbols | In-memory ≤ 60 s; **not persisted** (programme 06 § 2.1 row 1) | n/a | Yes, for decisions, not for training | n/a |
| Non-crypto 1h bars | Equity, rates, commodity, FX | none at 1h | Row `ML-DATA-XASSET-1H` (queued): no store holds 1h non-crypto bars over 2020-07..2026-09 | n/a | No | Unknown |

---

## 3. What ENTRY's 20 features are, and what they leave out

`FEATURES` (line 258): `ret_1/4/12/24/72/168` (vol-normalised), `vol24`, `vol_ratio`, `atr_pct`, `range_pos_24/168`, `vol_z`, `rsi14`, `hour`, `dow`, plus four cross-sectional (`xs_rank_ret24`, `btc_ret24`, `btc_vol24`, `breadth_up24`) and `rel_vol`. **All 20 are functions of one bar series (OHLCV) and the clock.** They contain no positioning, no flow, no basis, no funding, no trade-count information, no multi-horizon cross-sectional structure beyond one 24-bar rank, and no macro or event context. Funding enters only as a label cost.

## 4. Ranked plan: pooled feature store

One store, one feature registry (name, source, window, lag, venue), one as-of join, read by ENTRY v2, BRACKETS and HOLD/ADJUST/CLOSE. Pooled across all symbols, no sizing and no risk features. Ranked by (expected signal × cheapness × serveability). *Signal rationale is a hypothesis to be tested by the ablation, not a result.*

| Rank | Family (est. new columns) | Why it should carry signal | Leakage risk | Serve path today |
|---|---|---|---|---|
| **1** | **Taker flow from the kline columns** (~12: taker-buy share, its z-score and 4/24/72-bar means, trade count z, average trade size = quote volume ÷ count, quote-volume VWAP − close) | Signed aggressor flow is the cheapest measure of who is paying the spread; trade count and size separate retail from block flow. Already downloaded, 100% of dev rows | **Low.** Same bar close as every other feature. Risk is only a wrong `open_time` vs `close_time` convention | **Open question:** the Bybit kline feed carries no taker split (UNVERIFIED). Needs `ML-FS-SERVE-PARITY` |
| **2** | **Basis and funding** (~8: premium-index close and its z-score, last settled funding, funding z over 21/90 settlements, hours since/to settlement, funding-minus-premium gap) | Crowding and carry. Funding is a trailing byproduct of momentum (see the `market_features` note), so the extremes and the premium–funding gap are the candidate signal | **Low–medium.** Must join on `calc_time` ≤ bar close; the in-interval *predicted* rate is not archived and must not be reconstructed from the future | No live producer. Bybit tickers expose funding and next-funding (UNVERIFIED here); `ML-PRODUCER-FUNDING` |
| **3** | **Positioning (OI and long/short)** (~12: OI change over 1h/4h/24h in value terms, OI z, top-trader and account long/short ratio and their changes, taker long/short ratio, OI-price divergence) | Leverage building into a move vs short covering is the classic continuation/exhaustion split; it is also the state BRACKETS and HOLD/ADJUST/CLOSE most need | **Medium.** `create_time` semantics unverified; lag one 5m step. Irregular/unsorted files since mid-2026. Covers 71.3% of dev symbol-months (none before 2021-12), so the model needs a *present* flag and NaN, not 0 | None. Binance and Bybit OI are different venues' books |
| **4** | **Richer cross-sectional and market context** (~15: xs ranks at 4/24/72/168 bars, dispersion, breadth at several horizons, BTC/ETH-beta residual, correlation to BTC, lead-lag return of the top-10) | Pooled models gain most from relative information; today it is one rank and one breadth number | **Low**, if the reference set is fixed (the c692-04 recipe: context from a frozen reference set, not from whichever symbols happen to be in the table) | Computable from the same live 1h bars |
| **5** | **OHLCV shape and calendar** (~20: realised skew/kurtosis, up/down semivariance, Parkinson/Garman-Klass/Yang-Zhang volatility from `ml/datasets/volatility_estimators.py`, efficiency ratio, bars since the 24/168 extreme, gap, distance to day/week high-low, hour-of-week, hours to funding settlement) | Cheap, no new data, and the estimators already exist in the repo | **Low** | Yes |
| **6** | **Macro and event context** (~10: VIX/DXY/UST from `macro_features.py`, event-proximity from the economic calendar, COT for ETF proxies) | Risk-on/risk-off regime at 1d+ horizons; weaker at 1h–24h decisions | **Medium** — release timestamps and revision handling. COT lag verified at 3 days on all 10,093 rows | Daily workflows exist; FRED has no caller |
| **7** | **Order-book depth and tick flow** (~8: ±1%/±5% depth imbalance, depth/ADV, spread, large-trade share, VPIN) | Only where microstructure drives 4h–24h outcomes; weakest prior at this horizon | **Low** per snapshot; **high cost** (38 GB bookDepth, ~0.9 TB aggTrades unless stream-reduced). Covers 51.9% of dev symbol-months from 2023-01 | BTC capture only, forward since 2026-06-04 |
| **8** | **Learned features** (TSFM embedding 32, forecast 6, corpus embedding 16) | Pretrained representations | **Medium–high** — depends on the pretraining window; opaque to the leakage test | BTC/ETH/SOL shards only |

**HOLD/ADJUST/CLOSE** additionally reads the in-trade path state (`intrabar_features.py`, already pure and past-only) joined to the same store at the position's bar. **BRACKETS** reads families 1–5 at the decision bar.

**Design rules for the store (each is testable):**
1. Missing is **NaN plus a `<family>_present` flag**, never `0.0`. This closes the collapsed state `market_features` writes today.
2. Every as-of join states its lag in the registry and a test refuses a forward-shifted column.
3. One feature function per feature, imported by both the builder and the serve path (parity by construction); `scripts/ml/replay_parity.py` is the check.
4. A delisting mask (volume 0 and constant close) is explicit and counted.
5. Venue is a registry field: a feature trained on Binance and served from Bybit is `venue_mismatch` until `ML-FS-SERVE-PARITY` measures the gap.

## 5. Infra gaps, each a row or unit

| # | Gap | Where it lives | Tier |
|---|---|---|---|
| G1 | No archive of the non-OHLCV Binance streams for the 60 perps; ENTRY drops 6 of 12 kline columns; no explicit delisting mask; metrics reader must sort and tolerate irregular stamps | row `ML-FS-ARCHIVE` (new) | 1 |
| G2 | No pooled feature store, as-of join library, feature registry or leakage test shared by train and serve | row `ML-FS-STORE` (new, depends on G1) | 1 |
| G3 | Serve parity unmeasured: Binance-trained vs Bybit-served volume, taker split, funding, OI; no live collector for funding/OI/taker | row `ML-FS-SERVE-PARITY` (new) | 1 for the measurement; Tier 2 for any live collector it proposes |
| G4 | Does any family add held-out-free (dev-fold) value over the 20? | unit `RQ-20261101-fs01-01` (new, blocked on G1/G2) | 1 |
| G5 | 1m klines for tie-resolved first-passage labels at 60-symbol scale | row `DATA-KLINE-ARCHIVE` (reopened from dropped, scope widened) + `DATA-LABEL-TIES` (queued, consumer) | 1 |
| G6 | In-trade path store for HOLD/ADJUST/CLOSE | existing `DATA-INTRADE-LABEL-STORE` (blocked), `PATH-FLOW-JOIN` (landed_unproven) | 1 |
| G7 | Non-crypto 1h bars | existing `ML-DATA-XASSET-1H` (queued) | 1 |
| G9 | ENTRY v2 in hours; increments with stated variant counts | row `ML-FS-ENTRY-V2`, units `RQ-20261101-fs01-01` (dev ablation) and `RQ-20261101-fs02-01` (one forward read) | 1 |
| G10 | BRACKETS and HOLD/ADJUST/CLOSE on the same store | row `ML-FS-BRACKETS-HOLD` | 1 |
| G11 | Standing retrain cadence | row `ML-ENTRY-RETRAIN-CADENCE` (held PR) | 2 |
| G12 | Weekly Claude review of ML progress | row `ML-WEEKLY-REVIEW-LINES` (landed here) | 1 |
| G13 | Per-store available-feeds catalog | row `DATA-CATALOG` (reopened) | 1 |
| G8 | Forward order-flow capture beyond BTC | decided by the fs01-01 arm `flow_depth`; no row until it shows value | — |

`DATA-DERIV-ARCHIVE` (6 roster symbols) stays; `ML-FS-ARCHIVE` covers the 60-perp universe and the two are not duplicates.

## 6. Method and what I did not verify

- **Read from file contents (this session):** Binance Vision kline, fundingRate, premiumIndex, markPrice, metrics and bookDepth files for BTCUSDT and SOLUSDT, plus the delisted-symbol kline files above; the repo's COT, valuation and economic-calendar JSONL stores in full. Archive listing via the public bucket index for 60 symbols × 8 datasets (480 listings; 2 transient connection errors, XLMUSDT premium index and ETHUSDT metrics, **not retried**).
- **Coverage fractions** (§ 1.1) are first-listed to last-listed month per symbol intersected with the klines months of that symbol inside 2020-07..2025-09. **Contiguity inside the range is assumed, not gap-checked.**
- **Not verified:** any trainer-VM state (no egress; the BTC-only and 37,722-row figures are the 2026-10-14 diag measurement, cited); Bybit REST (HTTP 403 from here) and Binance fapi (HTTP 451 from here), so every "live" claim for a venue feed is UNVERIFIED; why 7 symbols are absent from the held-out; any signal in any feature.
- **Held-out:** nothing in 2025-10-01..2026-09-30 was read as an outcome. File timestamps and spacing were read for sources whose depth is part of the inventory; no price, label or return was computed.

## 7. Measured throughput (2026-11-01, this sandbox, 16 workers)

| Probe | Files | Result |
|---|---|---|
| 1h klines, 2025-06, first 16 universe symbols | 16 | 19.6 files/s, 0.7 MB/s |
| 5m metrics daily, 4 symbols × 8 days | 32 | 24.8 files/s, 0.3 MB/s |
| premium index 1h, 2025-06 | 16 | 26.6 files/s, 0.4 MB/s |

Small files, latency-bound: more workers should raise files/s, bandwidth for the large streams (bookDepth, aggTrades) was **not measured**. Totals in § 1b are file counts divided by these rates and are ESTIMATES until the backfill prints its own.
