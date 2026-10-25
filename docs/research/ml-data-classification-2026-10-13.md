# ML data classification — MARKET vs OURS (2026-10-13)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-13` (columns of the three 15m shards MEASURED on the trainer; everything else read from builder source, not from a shard) · lane `ML-DATA-OFF-TRAINER` · checklist row `ML-DATA-OFF-TRAINER`

**Question (operator, 2026-10-13 ~15:50Z):** is the ML data only market data, or does it contain OUR trading data (trades, fills, order packages, signals, account/PnL, labels derived from our own outcomes)? If market only, a public dataset is acceptable.

**Verdict.** The shards the queued ML/frontier units read are **MARKET only**. The families that hold OURS are separate, are read by no queued unit, and stay on the trainer. Everything published is **private** (Kaggle private datasets cost nothing), because "market" here is not the same as "free to redistribute": the macro block comes from third-party feeds.

## What was measured (not inferred)

`trainer-vm-diag` issue #17882, 2026-10-13 15:52Z, `datasets-out/market_features/{BTC,ETH,SOL}USDT/15m/v002/data.jsonl`:

| shard | rows | bytes | first ts | last ts | mtime |
|---|---|---|---|---|---|
| BTCUSDT 15m | 150,976 | 400 MB | 2021-10-13 | **2026-02-01** | 2026-10-13 05:22Z |
| ETHUSDT 15m | 175,272 | 449 MB | 2021-10-13 | 2026-10-12 | 2026-10-13 05:39Z |
| SOLUSDT 15m | 63,976 | 169 MB | 2021-10-15 | **2023-08-12** | 2026-10-13 05:44Z |

Each shard has the same 130-odd columns. Every one is on the list below; **none** names a trade, fill, order, account, balance, signal, strategy or PnL. (`order_imbalance` is the per-bar taker buy/sell volume imbalance from the public trade feed. `scripts/research/market_data_export.py` refuses any column that matches an OURS pattern, and a self-test proves `order_imbalance` passes while `pnl`, `order_package_id`, `account_id` do not.)

Columns, grouped by source: bar features (`log_return`, `rolling_log_return_vol`, `vol_bucket`, `hour_of_day`, `dayofweek`, `log_return_lag_*`, four range-based vol estimators) from Bybit public klines · labels (`regime_label`, `trend_regime_label`, `direction_label`, `forward_log_return*`) from FORWARD market returns/vol, not from any outcome of ours · funding/OI (`funding_rate*`, `open_interest_change*`) from Bybit public · order flow (`ofi*`, `vpin`, `order_imbalance`, `rel_spread_mean`, `microprice_dev`) captured from Bybit public order book + trades · macro (`vix_*`, `dxy_*`, `ust*`) from third-party feeds · peer-asset (`xa_*`) from the other symbols' bars · embeddings/forecasts (`tsfm_emb_*`, `fc_*`) from a frozen pretrained model run on the close series · `corpus_emb_*` from the public macro corpus encoder.

## Per family

| family | source (builder docstring / shell) | tag | verdict |
|---|---|---|---|
| `market_raw` crypto (Bybit) | Bybit V5 public klines (`bybit_v5_offvm` adapter) | MARKET | **export (private)**: BTC/ETH/SOL 15m + 1h |
| `market_features` crypto | `market_raw` + the side-streams above | MARKET | **export (private)**: BTC/ETH/SOL 15m + 1h. This is the only family the queued units read |
| `market_raw`/`market_features` MES, ETFs (GLD, SPY, …) | yfinance / IBKR | MARKET, third-party licence | keep off the export; private only if ever added |
| `forecasts`, `cross_asset`, `corpus_panel`, `corpus_embeddings` | model outputs and public series over market data | MARKET | not exported yet (no queued unit reads them); allowed later by adding paths to `ALLOW` |
| `market_sequences` | causal windows over `market_features` | MARKET | not exported (derivable from the export) |
| `setup_candidates` | CUSUM events on `market_raw`, labelled by triple-barrier on bars; synthetic fills | MARKET-derived (no outcomes of ours) | not exported (no queued unit) |
| `exit_candidates` | "(synthetic **or real**) trade" in-trade bars | **UNVERIFIED — may contain real trades** | not exported; treat as OURS until a read of its `real` path says otherwise |
| `trade_outcomes`, `setup_labels`, `setup_labels_audit` | `trade_journal.db` (+ `signal_audit.jsonl`) | **OURS** | never leaves the trainer |
| `conviction_meta` | `trades` JOIN `order_packages`, realized `pnl` | **OURS** | never leaves the trainer |
| `execution_quality`, `account_context` | `trade_journal.db`, `config/accounts.yaml` | **OURS** | never leaves the trainer |
| `backtest_results` | journal table (historical, FABRICATED zeros) | OURS | never leaves the trainer |
| `review_journal` | `comms/` health-review answers | OURS | never leaves the trainer |

Not classified in this pass: `RQ-20261009-903` (`pm_surprise_eval.py`) and `RQ-20261012-904` (`wepe_g3_ledger.py`) read prediction-market data, not ML shards. They stay on the trainer route; nothing about them is published.

## What is and is not approved

* **Approved by the operator's message (recorded as `operator_decision`):** exporting MARKET data to a Kaggle dataset and making it readable from GitHub runners. Done as **private**.
* **Not approved, not done:** publishing anything OURS in any form; making any dataset public. A public release would also redistribute third-party macro series (VIX/DXY/UST), which is a licence question this lane did not settle.
* `scripts/research/market_data_export.py::ALLOW` is the single list of shippable paths. Widening it is a reviewed edit, and the router reads the same list.

## Freshness / integrity finding (a bug, not a classification)

MEASURED (trainer, 2026-10-13 ~16:10Z, issue #17894): the **BTC and SOL 15m `market_raw` `data.jsonl` files are shorter than their own metadata says.**

| shard | rows in data.jsonl | last ts | metadata.json row_count | metadata generated_at | data.jsonl mtime |
|---|---|---|---|---|---|
| BTC 15m `market_raw` | **151,000** | 2026-02-01T21:45Z | 175,296 | 2026-10-13 00:44Z | 05:18Z |
| SOL 15m `market_raw` | **64,000** | 2023-08-12T15:45Z | 175,104 | 2026-10-13 00:59Z | 05:42Z |
| ETH 15m `market_raw` | 175,296 | 2026-10-12T23:45Z | 175,296 | 05:36Z | 05:36Z (consistent) |

The two counts are round numbers, and the file was rewritten ~4.5 h after the metadata was stamped, so a second writer replaced a whole file with a prefix of it. `market_features` and `forecasts` for BTC/SOL were then rebuilt from the cut file at 05:18–05:44Z, which is why they end on the same dates. The 05:18Z BTC and 05:42Z SOL times fall in the `ict-trainer-catchup` hour (busy fraction 1.96 at 05Z in `trainer-workload-2026-10-13.md`); **that is a correlation, not a cause**: the writer was not identified. Every BTC/SOL regime unit and the BTC/SOL regime-head training read cut data, which is why `RQ-20261012-75b2-22` found `n_test_rows=0`.

What this lane did about it: `scripts/research/market_data_export.py` compares each `market_raw` shard with its own metadata and each `market_features` shard with its raw's `row_count`, **withholds** any shard that disagrees (listed under `MANIFEST.withheld` with the reason), and records `last_ts`/`stale_days` for the rest. So the first export ships ETH and withholds BTC/SOL 15m; units that read a withheld shard fail closed with the reason (`published_data.py fetch`, exit 7) rather than run on a cut file. Finding the writer and repairing the shards is checklist row `ML-SHARD-TRUNCATED`.
