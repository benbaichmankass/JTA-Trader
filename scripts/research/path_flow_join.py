#!/usr/bin/env python3
# wiring: research/queue/RQ-20261024-09a6-02 (AI-ATM rung A2) via .github/workflows/research-script-run.yml
"""PATH-FLOW-JOIN: point-in-time flow (taker imbalance, settled funding, open interest) joined onto harness path rows,
and the rung-A2 grade: does flow add exit information beyond the price state?

WHY THIS EXISTS (checklist row PATH-FLOW-JOIN; queue unit RQ-20261024-09a6-02; Programme 01 'AI active trade
management -- the merged programme'). Every exit head this repo has failed saw price-derived features only (ML-S2,
d6e7). The harness's `--emit-paths` rows carry price state per bar; this module adds the flow that was knowable at
each bar's CLOSE and nothing later.

THE THREE INPUTS (each with the timestamp of the source observation beside it, so look-ahead is checkable)
  taker_imb     2*taker_buy_base/volume - 1 of bar t (the `src/research/intrabar_features.py` definition, reused
                verbatim), read from the harness's own candle CSV (`fetch_backtest_candles.py --source
                binance_vision` writes taker_buy_base; VERIFIED on a real 4h ETHUSDT CSV 2026-10-25). The 6-bar
                mean is trailing and includes bar t; a gap in the 6 bars makes it missing, not a shorter mean.
  funding       the last SETTLED funding rate with calc_time <= the bar's close (Binance Vision monthly
                fundingRate files). Older than 24h at the join -> missing. The still-open month is not published
                as a monthly file, so the tail of the window is MISSING and reported as such.
  open interest sum_open_interest from the Binance Vision daily `metrics` files (5-minute snapshots), read at the
                last snapshot <= bar close MINUS `--oi-lag-min` (default 5: a snapshot stamped at the close may
                be the period end). History starts 2021-12-01 for ETH/XRP/ADA/SOL (day-probed 2026-10-25), so
                earlier states carry NO OI -- missing, an indicator, never an imputed 0.

NEVER IMPUTE. A missing value stays None in the rows and NaN in the matrix (the `first_passage.Logit` fills NaN
with the TRAIN median, exactly as it does for the price features); the OI columns also carry `has_oi`.

THE GUARD (`refuse_lookahead`): every joined row is checked against the candles it came from. A taker value must
equal the imbalance of the candle stamped with the row's own ts (a column shifted forward in time, i.e. built from
a later bar, is refused), a funding source stamp must be <= the bar close, an OI source stamp <= close - lag.
`join_flow` runs it on every leg before anything is graded.

THE GRADE (`--mode grade`, unit 09a6-02): reuses `first_passage_paths` unchanged -- same trades, label, folds,
trade-cluster bootstrap and calibration slope. Reference = R1 if 09a6-01's own rule (R1 vs R0) PASSES on these
trades, else R0 (`--reference auto`); candidate = reference + the flow block. A leg with any graded flow column
on < 80% of its states is DROPPED AND NAMED; fewer than 600 trades left -> INDETERMINATE. The rule's thresholds
arrive through the run.command and are not changed here. `ex_oi_sensitivity` (reported, NEVER graded) repeats the
fit without the OI columns on every leg whose taker and funding coverage passes.

CLI
  --mode coverage   join + coverage report + guard only (no fit); verdict 'indeterminate' by construction
  --mode grade      the above plus the graded fit
  --self-test       tests/test_path_flow_join.py is the suite; this flag runs it
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from first_passage import TF_MIN  # noqa: E402
from src.research.intrabar_features import _taker_imbalance  # noqa: E402  (the ONE taker-imbalance definition)

VISION = "https://data.binance.vision/data/futures/um"
OI_FIRST_DAY = date(2021, 12, 1)  # day-probed 2026-10-25 on ETHUSDT/XRPUSDT/ADAUSDT/SOLUSDT: no daily metrics file earlier
FUNDING_STALE = pd.Timedelta(hours=24)
OI_STALE = pd.Timedelta(hours=1)
FLOW_COLS = ["taker_imb", "taker_imb_mean6", "funding_last", "funding_chg_entry", "oi_chg_entry", "oi_chg_6bar"]
ROW_FIELDS = ["taker_imb", "taker_imb_src_ts", "taker_imb_mean6", "funding_last", "funding_src_ts",
              "funding_chg_entry", "oi", "oi_src_ts", "oi_chg_6bar", "oi_chg_entry"]
TOL = 1e-9


class LookaheadError(ValueError):
    """A flow column carries information from after the bar it is attached to."""


def parse_ts(x: Any) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


# --------------------------------------------------------------------------- fetch (Binance Vision, keyless)
def _zip_rows(url: str, session=None) -> Optional[List[List[str]]]:
    import csv
    import requests
    get = (session or requests).get
    last: Optional[Exception] = None
    for _ in range(3):
        try:
            r = get(url, timeout=60)
        except requests.RequestException as exc:
            last = exc
            continue
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            last = RuntimeError(f"HTTP {r.status_code}")
            continue
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            with zf.open(zf.namelist()[0]) as fh:
                return list(csv.reader(io.TextIOWrapper(fh, encoding="utf-8")))
    raise RuntimeError(f"{url}: {last}")


def _months(start: pd.Timestamp, end: pd.Timestamp) -> List[Tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch_funding(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Settled funding history: columns ts (UTC, the settlement time) and rate. Months without a file are absent."""
    rows = []
    for y, m in _months(start, end):
        data = _zip_rows(f"{VISION}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{y}-{m:02d}.zip")
        for f in data or []:
            try:
                rows.append((pd.to_datetime(int(f[0]), unit="ms", utc=True), float(f[2])))
            except (ValueError, IndexError):
                continue  # header
    df = pd.DataFrame(rows, columns=["ts", "rate"])
    return df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


def fetch_oi(symbol: str, start: pd.Timestamp, end: pd.Timestamp, workers: int = 16) -> pd.DataFrame:
    """Open-interest snapshots: columns ts (UTC) and oi (sum_open_interest, base units). Days without a file are absent."""
    import requests
    d0 = max(start.date(), OI_FIRST_DAY)
    days = [d0 + timedelta(days=i) for i in range((end.date() - d0).days + 1)]
    sess = requests.Session()

    def one(d: date):
        data = _zip_rows(f"{VISION}/daily/metrics/{symbol}/{symbol}-metrics-{d}.zip", sess)
        out = []
        for f in data or []:
            try:
                out.append((pd.Timestamp(f[0], tz="UTC"), float(f[2])))
            except (ValueError, IndexError):
                continue  # header
        return out

    with ThreadPoolExecutor(workers) as ex:
        parts = list(ex.map(one, days))
    df = pd.DataFrame([r for p in parts for r in p], columns=["ts", "oi"])
    return df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


# --------------------------------------------------------------------------- candles -> taker imbalance
def candle_imbalance(candles: pd.DataFrame, tf_min: int) -> pd.Series:
    """Per-bar taker imbalance on a complete tf grid (a bar the feed lacks is NaN), indexed by bar OPEN time."""
    ts = pd.to_datetime(candles["timestamp"], utc=True)
    if "taker_buy_base" not in candles.columns:
        return pd.Series(np.nan, index=pd.DatetimeIndex(ts).sort_values().unique())
    vals = [_taker_imbalance({"taker_buy_base": tb, "volume": v})
            for tb, v in zip(candles["taker_buy_base"], candles["volume"])]
    s = pd.Series([np.nan if v is None else v for v in vals], index=pd.DatetimeIndex(ts)).sort_index()
    s = s[~s.index.duplicated()]
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq=f"{tf_min}min"))


def _asof(series_ts: np.ndarray, series_val: np.ndarray, at: np.ndarray, stale_ns: int):
    """Last observation with ts <= at (int64 ns). Returns (value, source ts ns); NaN / -1 where none or too stale."""
    idx = np.searchsorted(series_ts, at, side="right") - 1
    ok = idx >= 0
    safe = np.where(ok, idx, 0)
    src = series_ts[safe] if len(series_ts) else np.zeros(len(at), dtype=np.int64)
    ok &= (at - src) <= stale_ns if len(series_ts) else False
    val = np.where(ok, series_val[safe] if len(series_ts) else np.nan, np.nan)
    return val, np.where(ok, src, -1)


def _ns(x: Any) -> np.ndarray:
    """int64 nanoseconds since epoch, whatever datetime unit pandas gave the column (ms/us/ns differ by version)."""
    return pd.DatetimeIndex(x).as_unit("ns").asi8


def _iso(ns: int) -> Optional[str]:
    return None if ns < 0 else str(pd.Timestamp(int(ns), unit="ns", tz="UTC"))


def _nn(x: float) -> Optional[float]:
    return None if x != x else round(float(x), 10)


# --------------------------------------------------------------------------- the join
def join_flow(rows: Sequence[dict], tf_min: int, imb: pd.Series, funding: pd.DataFrame, oi: pd.DataFrame,
              *, oi_lag_min: int = 5, candles: Optional[pd.DataFrame] = None) -> List[dict]:
    """Add the flow_* fields to every path row of ONE leg; refuse the result if any field looks forward.

    Bar t's CLOSE is its open ts + tf. Funding is read at the close, OI at close - oi_lag_min. Entry-relative
    fields read the same sources at the ENTRY bar's close (= the row's ts - bar_offset*tf + tf)."""
    if not rows:
        return []
    tf = pd.Timedelta(minutes=tf_min)
    ts = pd.DatetimeIndex([parse_ts(r["ts"]) for r in rows]).as_unit("ns")
    off = np.array([int(r["bar_offset"]) for r in rows], dtype=np.int64)
    close = _ns(ts + tf)
    entry_close = close - off * tf.value
    lag = pd.Timedelta(minutes=oi_lag_min).value

    cur = imb.reindex(ts).to_numpy(dtype=float)
    mean6 = imb.rolling(6, min_periods=6).mean().reindex(ts).to_numpy(dtype=float)
    f_ts, f_val = _ns(funding["ts"]), funding["rate"].to_numpy(dtype=float)
    o_ts, o_val = _ns(oi["ts"]), oi["oi"].to_numpy(dtype=float)
    f_now, f_src = _asof(f_ts, f_val, close, FUNDING_STALE.value)
    f_ent, _ = _asof(f_ts, f_val, entry_close, FUNDING_STALE.value)
    o_now, o_src = _asof(o_ts, o_val, close - lag, OI_STALE.value)
    o_ent, _ = _asof(o_ts, o_val, entry_close - lag, OI_STALE.value)
    o_6, _ = _asof(o_ts, o_val, close - 6 * tf.value - lag, OI_STALE.value)
    with np.errstate(divide="ignore", invalid="ignore"):
        oi_chg_6 = np.where(o_6 > 0, o_now / o_6 - 1.0, np.nan)
        oi_chg_e = np.where(o_ent > 0, o_now / o_ent - 1.0, np.nan)

    out = []
    for i, r in enumerate(rows):
        n = dict(r)
        has_tk = cur[i] == cur[i]
        n.update({
            "flow_taker_imb": _nn(cur[i]), "flow_taker_imb_src_ts": str(ts[i]) if has_tk else None,
            "flow_taker_imb_mean6": _nn(mean6[i]),
            "flow_funding_last": _nn(f_now[i]), "flow_funding_src_ts": _iso(int(f_src[i])),
            "flow_funding_chg_entry": _nn(f_now[i] - f_ent[i]),
            "flow_oi": _nn(o_now[i]), "flow_oi_src_ts": _iso(int(o_src[i])),
            "flow_oi_chg_6bar": _nn(oi_chg_6[i]), "flow_oi_chg_entry": _nn(oi_chg_e[i])})
        out.append(n)
    refuse_lookahead(out, tf_min, oi_lag_min=oi_lag_min, imb=imb)
    return out


def refuse_lookahead(rows: Sequence[dict], tf_min: int, *, oi_lag_min: int = 5,
                     imb: Optional[pd.Series] = None) -> None:
    """Raise LookaheadError if any flow field carries information from after its bar."""
    tf = pd.Timedelta(minutes=tf_min)
    bad: List[str] = []
    for r in rows:
        ts = parse_ts(r["ts"])
        close = ts + tf
        tk_src = r.get("flow_taker_imb_src_ts")
        if tk_src is not None and parse_ts(tk_src) != ts:
            bad.append(f"{r.get('trade_key')} @ {ts}: taker source stamp {tk_src} is not the bar's own open")
        f_src = r.get("flow_funding_src_ts")
        if f_src is not None and parse_ts(f_src) > close:
            bad.append(f"{r.get('trade_key')} @ {ts}: funding source {f_src} is after the bar close {close}")
        o_src = r.get("flow_oi_src_ts")
        if o_src is not None and parse_ts(o_src) > close - pd.Timedelta(minutes=oi_lag_min):
            bad.append(f"{r.get('trade_key')} @ {ts}: OI source {o_src} is after close - lag")
        if imb is not None:
            for col, ref in (("flow_taker_imb", imb.get(ts, np.nan)),
                             ("flow_taker_imb_mean6", imb.rolling(6, min_periods=6).mean().get(ts, np.nan))):
                v = r.get(col)
                if v is not None and not (ref == ref and abs(float(v) - float(ref)) <= 1e-8):
                    bad.append(f"{r.get('trade_key')} @ {ts}: {col}={v} != the source candle's {ref} "
                               "(a shifted column, or one not built from this bar)")
        if len(bad) >= 5:
            break
    if bad:
        raise LookaheadError("flow column refused (look-ahead): " + "; ".join(bad[:5]))


# --------------------------------------------------------------------------- coverage
def coverage(leg: str, rows: Sequence[dict]) -> Dict[str, Any]:
    """Share of pre-exit STATES (the exit row is never an event) carrying each flow column, per input."""
    st = [r for r in rows if not r.get("is_exit")]
    n = len(st)
    rep: Dict[str, Any] = {"leg": leg, "n_states": n, "n_trades": len({r["trade_key"] for r in rows})}
    if not n:
        return {**rep, "share": {c: None for c in FLOW_COLS}, "window": None}
    rep["share"] = {c: round(sum(r.get(f"flow_{c}") is not None for r in st) / n, 4) for c in FLOW_COLS}
    ts = sorted(parse_ts(r["ts"]) for r in st)
    rep["window"] = [str(ts[0]), str(ts[-1])]
    rep["input_share"] = {"taker": rep["share"]["taker_imb"], "funding": rep["share"]["funding_last"],
                          "open_interest": rep["share"]["oi_chg_6bar"]}
    return rep


def legs_failing(cov: Sequence[Dict[str, Any]], min_share: float, cols: Sequence[str] = tuple(FLOW_COLS)):
    """Legs with any listed flow column on < min_share of states: {leg: {col: share}}."""
    out = {}
    for c in cov:
        low = {k: v for k, v in (c.get("share") or {}).items() if k in cols and (v is None or v < min_share)}
        if low or not c.get("n_states"):
            out[c["leg"]] = low
    return out


# --------------------------------------------------------------------------- grade
def flow_matrix(rows_sorted: Sequence[dict], n: int, with_oi: bool = True) -> np.ndarray:
    """n x k flow block for the first n (pre-exit) rows of one trade; None -> NaN; OI carries has_oi."""
    def col(c: str) -> np.ndarray:
        return np.array([np.nan if r.get(f"flow_{c}") is None else float(r[f"flow_{c}"]) for r in rows_sorted[:n]])
    cols = [col("taker_imb"), col("taker_imb_mean6"), col("funding_last"), col("funding_chg_entry")]
    if with_oi:
        oi6, oie = col("oi_chg_6bar"), col("oi_chg_entry")
        cols += [oie, oi6, (np.isfinite(oi6) & np.isfinite(oie)).astype(float)]
    return np.column_stack(cols)


def grade_corpus(corpus: Sequence[Tuple[str, List[dict], List[dict], Optional[str]]], a: argparse.Namespace,
                 failed: Optional[List[dict]] = None, runs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """corpus rows already carry flow_* fields. Returns the script_run-shaped verdict record."""
    import first_passage_paths as fpp
    failed = list(failed or [])
    trades, reports, cov = [], [], []
    for leg, prow, trow, tf in corpus:
        ts, rep = fpp.build_trades(leg, prow, trow, tf)
        if rep["state"] == "included" and ts and ts[0]["tfm"] is None:
            rep["state"] = "timeframe_unresolved"
        reports.append(rep)
        cov.append(coverage(leg, prow))
        if rep["state"] == "included":
            by_key: Dict[str, List[dict]] = {}
            for r in prow:
                by_key.setdefault(r["trade_key"], []).append(r)
            for t in ts:
                t["_flow_rows"] = sorted(by_key[t["trade_key"]], key=lambda r: r["bar_offset"])
            trades.extend(ts)
    parity_ok = not failed and bool(reports) and all(r["state"] == "included" for r in reports)
    dropped = legs_failing(cov, a.min_coverage)
    meas: Dict[str, Any] = {"legs": reports, "coverage": cov, "failed_or_skipped": failed, "runs": runs or {},
                            "legs_dropped_low_coverage": dropped, "min_coverage": a.min_coverage}
    verdict, why = "indeterminate", "no trades in the corpus"
    kept = [t for t in trades if t["leg"] not in dropped]
    if trades and a.mode == "grade":
        def fit_block(tr: List[dict], with_oi: bool) -> Tuple[str, Dict[str, Any], Dict[str, Any], str]:
            legs_ = sorted({t["leg"] for t in tr})
            ev = [fpp.events(t, legs_) for t in tr]
            base = fpp.fit_info(tr, ev, fpp.calendar_folds(tr, a.n_folds), n_boot=a.n_boot)
            ref_v, _ = fpp.verdict_info(base, min_gain=a.min_gain_nats, min_folds=a.min_folds, min_n=a.min_n,
                                        slope_lo=0.7, slope_hi=1.3, parity_ok=parity_ok)
            ref = a.reference if a.reference != "auto" else ("R1" if ref_v == "pass" else "R0")
            key = "X1" if ref == "R1" else "X0"
            e2 = []
            for t, e in zip(tr, ev):
                if not e["n"]:
                    e2.append(e)
                    continue
                e2.append({**e, "X0": e[key], "X1": np.c_[e[key], flow_matrix(t["_flow_rows"], e["n"], with_oi)]})
            fe = fpp.fit_info(tr, e2, fpp.calendar_folds(tr, a.n_folds), n_boot=a.n_boot)
            return ref, base, fe, ref_v

        if kept and len(kept) >= a.min_n:
            ref, base, fe, ref_v = fit_block(kept, True)
            meas["reference"] = {"chosen": ref, "rule": "R1 if 09a6-01's own rule passes on these trades, else R0",
                                 "price_state_verdict_09a6_01_rule": ref_v,
                                 "price_state_gain_nats": base["mean_gain_nats"], "price_state_ci95": base["ci95"]}
            meas["flow_info"] = fpp._strip(fe)
            meas["flow_info"]["features"] = {"reference": ref, "flow": ["taker_imb", "taker_imb_mean6", "funding_last",
                                                                        "funding_chg_entry", "oi_chg_entry",
                                                                        "oi_chg_6bar", "has_oi"]}
            verdict, why = fpp.verdict_info(fe, min_gain=a.min_gain_nats, min_folds=a.min_folds, min_n=a.min_n,
                                            slope_lo=0.7, slope_hi=1.3, parity_ok=parity_ok)
            why = f"flow vs {ref}: {why}; legs dropped for coverage < {a.min_coverage:.0%}: {sorted(dropped)}"
        else:
            verdict = "indeterminate"
            why = (f"{len(kept)} trades remain after dropping legs {sorted(dropped)} for a flow column on "
                   f"< {a.min_coverage:.0%} of states; the rule needs >= {a.min_n}")
        # sensitivity: legs whose taker + funding coverage passes, OI columns removed. Reported, NEVER graded --
        # computed even when the graded rule is INDETERMINATE so the run still says what the OI-free flow block does.
        ok_legs = {c["leg"] for c in cov} - set(legs_failing(cov, a.min_coverage, ["taker_imb", "taker_imb_mean6",
                                                                                   "funding_last", "funding_chg_entry"]))
        sens_tr = [t for t in trades if t["leg"] in ok_legs]
        if sens_tr and len(sens_tr) >= 2 * a.n_folds:
            ref_s, _base_s, se, _ = fit_block(sens_tr, False)
            meas["ex_oi_sensitivity"] = {"graded": False, "reference": ref_s, "legs": sorted(ok_legs),
                                         "n_trades": len(sens_tr), **{k: se[k] for k in (
                                             "n_oos_trades", "mean_gain_nats", "ci95", "folds_positive",
                                             "calibration_slope_r1")}}
    elif trades:
        why = "coverage mode is descriptive; no registered rule grades it"
    n_tr = len(kept)
    pop = (f"{len(trades)} trades on {sum(r['state'] == 'included' for r in reports)} parity-included legs, "
           f"{n_tr} after the coverage drop ({sorted(dropped)} dropped); flow = taker imbalance (candle CSV), last "
           "settled funding (Binance Vision), open interest (Binance Vision metrics, 2021-12-01 onward); as traded "
           "(harness paths), net of the harness's venue-aware cost stack, 6 purged calendar folds by entry")
    return {"verdict": verdict, "read_state": "measured" if trades else "unmeasured", "population": pop, "n": n_tr,
            "measurement": meas, "note": f"path_flow_join/{a.mode}: {why}"}


# --------------------------------------------------------------------------- driver
def run(a: argparse.Namespace, fetchers=None) -> Dict[str, Any]:
    """Harness paths -> join -> guard -> coverage (-> grade). `fetchers` = (funding_fn, oi_fn) for tests."""
    import tempfile

    import first_passage_paths as fpp
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    legs = [s.strip() for s in a.harness_legs.split(",") if s.strip()]
    wd = Path(tempfile.mkdtemp(prefix="path_flow_join_", dir=str(out)))
    corpus, failed, runs = fpp.run_harness_legs(legs, days=a.days, start=a.start, end=a.end, wd=wd, data_csv=a.data_csv)
    f_fn, o_fn = fetchers or (fetch_funding, fetch_oi)
    joined, sources = [], {}
    span: Dict[str, List[pd.Timestamp]] = {}  # per symbol, the widest window any leg needs: each source is fetched once
    for leg, prow, trow, tf in corpus:
        sym = (trow[0].get("symbol") if trow else None) or (prow[0].get("symbol") if prow else None)
        ts = [parse_ts(r["ts"]) for r in prow]
        w = span.setdefault(sym, [min(ts), max(ts)])
        w[0], w[1] = min(w[0], min(ts)), max(w[1], max(ts))
    fetched: Dict[str, Any] = {}
    for leg, prow, trow, tf in corpus:
        sym = (trow[0].get("symbol") if trow else None) or (prow[0].get("symbol") if prow else None)
        csv = a.data_csv or str(wd / f"{leg}__data.csv")
        candles = pd.read_csv(csv)
        tfm = TF_MIN[tf]
        imb = candle_imbalance(candles, tfm)
        lo, hi = span[sym][0] - pd.Timedelta(days=2), span[sym][1] + pd.Timedelta(minutes=tfm)
        try:
            if sym not in fetched:
                fetched[sym] = (f_fn(sym, lo, hi), o_fn(sym, lo, hi))
            fund, oi = fetched[sym]
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as a failed leg with its error and the verdict goes INDETERMINATE; a source outage is never read as zero flow
            failed.append({"leg": leg, "reason": "flow_fetch_failed", "error": str(exc)[:400]})
            continue
        rows = join_flow(prow, tfm, imb, fund, oi, oi_lag_min=a.oi_lag_min)
        with open(out / f"{leg}__flow_paths.jsonl", "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, default=str) + "\n")
        sources[leg] = {"symbol": sym, "n_funding": len(fund), "n_oi": len(oi), "has_taker_column":
                        "taker_buy_base" in candles.columns}
        joined.append((leg, rows, trow, tf))
    v = grade_corpus([(lg, rows, trow, tf) for lg, rows, trow, tf in joined], a, failed, runs)
    v["measurement"]["flow_sources"] = sources
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    return v


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--harness-legs", required=False)
    ap.add_argument("--days", type=int, default=2330)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--data-csv", default=None)
    ap.add_argument("--mode", choices=("coverage", "grade"), default="grade")
    ap.add_argument("--reference", choices=("auto", "R0", "R1"), default="auto")
    ap.add_argument("--min-coverage", type=float, default=0.8)
    ap.add_argument("--oi-lag-min", type=int, default=5)
    ap.add_argument("--min-gain-nats", type=float, default=0.002)
    ap.add_argument("--min-folds", type=int, default=4)
    ap.add_argument("--min-n", type=int, default=600)
    ap.add_argument("--n-folds", type=int, default=6)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--self-test", action="store_true")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    if a.self_test:
        import subprocess
        return subprocess.call([sys.executable, "-m", "pytest", "-q", str(REPO / "tests" / "test_path_flow_join.py")])
    if not a.harness_legs:
        print("ERROR: --harness-legs is required", file=sys.stderr)
        return 2
    v = run(a)
    print(json.dumps({k: v[k] for k in ("verdict", "n", "note")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
