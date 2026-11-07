# Per-model data-coverage audit (row ML-DATA-WIRING, lane 2026-11-05)

> **Doc status:** `unknown` · category `lookup` · last verified `2026-11-05` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Gates this adds or changes:** none (report-style coverage; not a CI refusal, not a promotion input).

**Projection, no new store.** Rows come from the registry's own definition of "a model": `ml/configs/*.yaml` (73 `*.yaml` manifests, dataset `family` +
`timeframe` read from each, 2026-11-05) and `ml/served/*` (3 served artifacts), joined with the lake's declared per-model query
[`ml/datasets/lake_selection.yaml`](../../ml/datasets/lake_selection.yaml) and the lake coverage table in
[`market-data-lake.md`](market-data-lake.md) § 3.0. The lake MANIFEST itself (rows/symbols/span per path) is read by the
[`lake-parity`](../../.github/workflows/lake-parity.yml) run, which holds `HF_TOKEN`; its numbers are in § 4. **Every lake-coverage cell
below inherits the state of the §3.0 table (MEASURED / BUILT / INFERRED); none was re-read from the MANIFEST in this document.**
The trainer-VM registry (`python -m ml list-models`) was not read here: manifests are the population, not the trained-and-registered set.

## 1. Population and the one-line finding

| family (manifest `dataset.family`) | manifests | what it trains on today | lake serves it? |
|---|---|---|---|
| `market_features` crypto BTC/ETH/SOL, tf 5m/15m/1h | 44 (BTC 28 · ETH 11 · SOL 5; direction heads included in BTC/ETH counts) | `market_raw` via `adapters/bybit_offvm` (+ funding/OI via `bybit_funding_oi`, orderflow via the trainer's own capture) | **Bars: yes, in principle** (crypto/um_perp 1m→5m/15m/1h, all perps incl. delisted, 2020-01→). **No adapter** (status `planned`). Funding/OI: lake holds `funding/` + `metrics_5m/`, no adapter. Orderflow (ofi, microprice, spread): NOT in the lake |
| `market_features` MES, tf 5m/15m/1d | 8 | `market_raw` via `adapters/ibkr_offvm` (runs on the live VM; one IB session per username) and `yfinance_offvm` | **No for 5m/15m**: lake futures are `futures/yahoo_cont/1d` fronts only (37 roots; MES 1d only). 5m/15m MES must stay on IBKR or come from a new source. 1d: yes if MES/ES front is among the 37 roots (UNVERIFIED) |
| `conviction_meta` | 3 | our `trade_outcomes` + `setup_candidates` journal/backtest rows | Labels never leave our stores. Market features could join from the lake (BTC/ETH/SOL bars); no join built |
| `setup_candidates` | 11 | our setup rows + backtest/siglog/p2pool corpora | same as above; a bar-feature join, no new data kind |
| `trade_outcomes`, `exit_candidates`, `execution_quality`, `account_context`, `setup_labels_audit` | 6 (1+1+2+1+1) | our journal / broker fills / account state | **Not a lake question**: these are OUR decisions and fills. The lake can only add market context columns |
| served `ml_decision_entry_v1/v2` (ENTRY) | 2 | Binance Vision klines12 streams (60-perp bp2 universe, 1h) | **Wired.** `build-table --source lake` exists (this row, PR #pending/merged: see § 4 for parity) |
| served `ml_entry_tp_revision_v1` | 1 | same feature recipe as ENTRY plus open-position state (bars_held, open_r, mfe_r, mae_r) | Bars from the lake via the ENTRY table builder; position-state columns come from replay, not data. **No lake path declared** (not in `lake_selection.yaml`) |

Sum check (MEASURED 2026-11-05, `ml/configs/*.yaml`): market_features 53 = btc 28 + eth 11 + sol 5 + mes 8 + 1 `baseline-regime-classifier` (1h, family market_features, symbol-agnostic baseline, counted with crypto for adapter purposes); setup_candidates 11; conviction_meta 3; the five journal families 6; total 53 + 11 + 3 + 6 = 73. Two further files carry the `.disabled` suffix and are excluded. The 3 served artifacts are counted separately. Re-derive with § 6 rather than quoting.

## 2. Data-starved models (a lake dataset exists that the model does not read)

"Starved" = the lake holds strictly more of the model's own data kind (more symbols, more history, more tf) than the model reads, or holds a
feature stream it lacks. Expected gain is **unmeasured** for every row; "more data" is a lever on the map, tested one factor at a time, with a
rule registered before the run (checklist rows below carry the owner and due date).

| # | model group | reads today | lake holds beyond that | lever (one factor) | row |
|---|---|---|---|---|---|
| S1 | ENTRY v1/v2 (served, advisory) | 60 perps, 1h, 2020-07→2026-09 (bp2 universe) | the full as-of perp universe (1,056 symbols incl. delisted) and 1m base; metrics_5m (OI, long/short, taker ratio) beyond what klines12 carries | **universe widening** (lever ML-ENTRY-UNIVERSE); then metrics_5m as a feature stream | lever `ML-ENTRY-UNIVERSE` (named in COST-PER-SYMBOL-SPREAD and two pipeline items; NO row of its own: gap, see handoff) |
| S2 | BTC/ETH/SOL regime + direction (44 manifests; 45 with the baseline) | one symbol each from `market_raw` Bybit pulls (limited depth; trainer-side capture) | Binance 1m→5m/15m/1h from 2020-01 for every symbol; funding history; metrics_5m | **lake adapter for `market_features`**, then pooled-symbol training (symbol count one factor, history depth another) | `ML-LAKE-ADAPTER-REGIME` |
| S3 | MES regime (8) | IBKR/yfinance intraday pulls (limited by IBKR pacing and the one-session rule) | nothing intraday for MES; 1d fronts + COT positioning + CBOE IV/VIX family + FRED macro/rates are in the lake | a 1d/macro-context feature join (`mes-regime-5m-lgbm-macro-v1` already uses macro); **intraday depth is a SOURCE gap, not a wiring gap** | `ML-LAKE-ADAPTER-MES` |
| S4 | conviction_meta (3), setup_candidates (11) | our journal rows only (small n) | bar features at signal time for every rowed symbol; cross-symbol context | market-feature join from the lake; **labels stay ours**, so n does not grow | `ML-LAKE-ADAPTER-CONVICTION` |
| S5 | ml_entry_tp_revision_v1 (served) | ENTRY recipe bars | inherits S1 | none until S1 settles; no lake path declared | covered by `ML-ENTRY-UNIVERSE` |

**Not starved by the lake:** `trade_outcomes`, `exit_candidates` (exit-policy-v1, 5m), `execution_quality` (+ mes), `account_context`,
`setup_labels_audit`: their scarcity is OUR trade count, which no market-data lake relieves (stated, not a gap).

## 3. Gaps the lake itself has for these models (from §3.0)

1. **No intraday for futures (MES 5m/15m).** Source gap; lake has daily fronts only.
2. **Orderflow / L2 features** (`ofi`, `microprice_dev`, spread; `market_features` orderflow columns) are not in the lake (own capture only).
3. **No lake adapter for `market_features`**: the largest manifest group (53 of 73) cannot be built from the lake today.
4. **No recorded `lake_revision` / `lake_trained_through` in any served artifact**, so `lake_klines.freshness()` reads `train_end_exclusive`
   (pre-lake). Fixed only by a retrain, which is its own unit (not this lane).
5. **Stocks / ETFs: no ML model reads them at all.** Equity legs run on rules, not ML; the lake's `us_equity` 1d (6,158 listed + delisted) and
   ETF 5m/1h are unused by any manifest. Not a wiring gap; it is the absence of an equity ML family. Filed as a note on `ML-LAKE-ADAPTER-REGIME`'s successor.

## 4. Real-lake measurement (HF_TOKEN runner)

PARITY_PLACEHOLDER

## 5. Adapter plan (build vs plan)

| family | adapter | size | state this lane |
|---|---|---|---|
| ml_entry / ml_entry_v2 | `ml/datasets/lake_klines.py::build_klines_cache` | done | wired, parity-tested on synthetic; real parity § 4 |
| regime_btc_eth(+sol) | new `ml/datasets/adapters/lake_bars.py` registered in `adapters/registry.py` returning `market_raw` rows from `lake.load` (+ funding/metrics_5m join), same row schema as `bybit_offvm` | medium: schema parity with `market_raw` (ts, symbol, o/h/l/c/v, source) plus the `source` field and per-tf resample rule; its own parity test | planned: row `ML-LAKE-ADAPTER-REGIME` |
| regime_mes | none for 5m/15m (source gap). 1d: same adapter once § 4 confirms the MES/ES root | blocked on a source | planned: row `ML-LAKE-ADAPTER-MES` |
| conviction_meta / setup_candidates | feature join `lake.load` at `signal_ts` (as-of, no lookahead) | small once the regime adapter exists | planned: row `ML-LAKE-ADAPTER-CONVICTION` |

The regime adapter was judged **not small** (it must reproduce `market_raw`'s schema and be proven row-for-row against the Bybit pulls the
44 existing manifests were trained on, otherwise a "wired" regime model silently trains on a different series), so it is planned with a row, not
built here. No retrain of a live-serving model is done or implied.

## 6. Re-derive

```
python3 - <<'PY'
import yaml,glob,collections
c=collections.Counter()
for p in glob.glob('ml/configs/*.yaml'):
    d=yaml.safe_load(open(p)); c[(d['dataset']['family'],d['dataset'].get('timeframe'))]+=1
print(sorted(c.items()))
PY
```
