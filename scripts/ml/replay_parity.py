#!/usr/bin/env python3
"""Replay-parity harness (ML plan P0 / ML-PRODUCERS M0): TRAIN row vs LIVE row
on IDENTICAL bars, per feature.

``_feature_parity_probe.py`` compares *distributions* (training dataset vs the
logged live rows) — different bars, so a gap can be sampling. This harness
removes that excuse. For the same N closed bars it builds

* the TRAIN row  — ``MarketFeaturesBuilder.iter_rows`` over a ``market_raw``
  dir (+ the optional funding/OI side-stream), the exact offline builder; and
* the LIVE row   — ``regime_shadow.feature_row_for_predictor`` fed the trailing
  candle window a bar-close tick would have held, exactly as the live scorer
  calls it (no side-stream: the live builder has no funding producer),

then reports, per feature the head selects (``trainer_config.feature_columns``
of its manifest):

``live_present_pct``  share of bars where the live row carries the key at all
                      (``None`` / missing = absent: the model sees NaN);
``live_nondefault_pct`` share where it is present AND non-zero / non-null
                      (the builder fills ``0.0`` when it has no side-stream, so
                      "present" alone cannot tell a producer from a default);
``train_nondefault_pct`` the same on the train row — a feature that is default
                      on BOTH sides carries no signal and is not a parity bug;
``max_abs_diff``      max |train - live| over bars where both sides have it;
``verdict``           ``OK`` · ``ABSENT_LIVE`` (never in the live row) ·
                      ``DEFAULT_LIVE`` (present but pinned to the default while
                      train is not) · ``DRIFT`` (values differ > tol) ·
                      ``NO_SIGNAL`` (default on both sides) · ``NO_PAIRS``.

A head's verdict is the worst feature verdict. Read-only; never touches the
order path or the registry. Trainer-side it is meant to run through the
``trainer-vm-diag`` relay (no inline ``python -c``); everything the core needs
is pure so it is unit-tested without a trainer.

  python scripts/ml/replay_parity.py --model-id btc-regime-1h-lgbm-funding-svble-v1 \
      --symbol BTCUSDT --timeframe 1h --market-raw datasets-out/market_raw/BTCUSDT/1h/<ver> \
      --funding-oi datasets-out/funding_oi/BTCUSDT/<ver> --bars 600
"""
# wiring: manual-only - run on demand through trainer-vm-diag (cmd: python3 scripts/ml/replay_parity.py ...); an investigation tool, not a scheduled job
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# tolerance below which a numeric difference is float-order noise
DEFAULT_TOL = 1e-9
# live fetch window the scorer holds per tick (monitor/scorer fetch ~200 bars)
LIVE_WINDOW_BARS = 200

_VERDICT_RANK = {"OK": 0, "NO_SIGNAL": 0, "NO_PAIRS": 1, "DEFAULT_LIVE": 2,
                 "DRIFT": 3, "ABSENT_LIVE": 4}


def _finite(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _is_present(v: Any) -> bool:
    if v is None or v == "":
        return False
    if isinstance(v, float) and not math.isfinite(v):
        return False
    return True


def _is_nondefault(v: Any, categorical: bool) -> bool:
    if not _is_present(v):
        return False
    if categorical:
        return True
    f = _finite(v)
    return f is not None and f != 0.0


def compare_features(
    train_by_ts: Mapping[str, Mapping[str, Any]],
    live_by_ts: Mapping[str, Mapping[str, Any]],
    features: Sequence[str],
    categorical: Iterable[str] = (),
    tol: float = DEFAULT_TOL,
) -> Dict[str, Any]:
    """Per-feature agreement of two row sets keyed by bar timestamp.

    ``live_by_ts`` may omit a ts (the live builder refused that bar); such
    bars count against ``live_rows`` coverage, not against a feature.
    """
    cats = set(categorical)
    ts_both = sorted(set(train_by_ts) & set(live_by_ts))
    out: Dict[str, Any] = {
        "train_rows": len(train_by_ts),
        "live_rows": len(live_by_ts),
        "paired_bars": len(ts_both),
        "features": {},
    }
    worst = "OK"
    for f in features:
        is_cat = f in cats
        n = len(ts_both)
        lp = sum(1 for t in ts_both if _is_present(live_by_ts[t].get(f)))
        tp = sum(1 for t in ts_both if _is_present(train_by_ts[t].get(f)))
        lnd = sum(1 for t in ts_both if _is_nondefault(live_by_ts[t].get(f), is_cat))
        tnd = sum(1 for t in ts_both if _is_nondefault(train_by_ts[t].get(f), is_cat))
        max_diff: Optional[float] = None
        n_mismatch = 0
        n_cmp = 0
        for t in ts_both:
            a, b = train_by_ts[t].get(f), live_by_ts[t].get(f)
            if not (_is_present(a) and _is_present(b)):
                continue
            n_cmp += 1
            if is_cat:
                if str(a) != str(b):
                    n_mismatch += 1
                continue
            fa, fb = _finite(a), _finite(b)
            if fa is None or fb is None:
                continue
            d = abs(fa - fb)
            max_diff = d if max_diff is None else max(max_diff, d)
        pct = lambda k: round(100.0 * k / n, 2) if n else None  # noqa: E731
        if n == 0:
            verdict = "NO_PAIRS"
        elif lp == 0 and tp > 0:
            verdict = "ABSENT_LIVE"
        elif tnd == 0 and lnd == 0:
            verdict = "NO_SIGNAL"
        elif tnd > 0 and lnd == 0:
            verdict = "DEFAULT_LIVE"
        elif (is_cat and n_mismatch) or (max_diff is not None and max_diff > tol):
            verdict = "DRIFT"
        elif lp < tp:
            verdict = "ABSENT_LIVE"
        else:
            verdict = "OK"
        out["features"][f] = {
            "categorical": is_cat,
            "live_present_pct": pct(lp),
            "train_present_pct": pct(tp),
            "live_nondefault_pct": pct(lnd),
            "train_nondefault_pct": pct(tnd),
            "n_compared": n_cmp,
            "max_abs_diff": max_diff,
            "n_categorical_mismatch": n_mismatch if is_cat else None,
            "verdict": verdict,
        }
        if _VERDICT_RANK[verdict] > _VERDICT_RANK[worst]:
            worst = verdict
    out["head_verdict"] = worst
    out["drifting_features"] = sorted(
        f for f, r in out["features"].items()
        if _VERDICT_RANK[r["verdict"]] >= _VERDICT_RANK["DEFAULT_LIVE"])
    return out


def infer_regime_spec(train_rows: Sequence[Mapping[str, Any]], *, symbol: str,
                      timeframe: str, vol_window_n: int,
                      vol_feature_column: str) -> Dict[str, Any]:
    """Frozen-edge stand-in rebuilt from the train rows themselves.

    The builder buckets ``vol_feature_column`` at sample quantiles with
    ``value <= cut``, so the upper edge of bucket ``i`` is the max vol seen in
    it. Exact when the whole build is replayed (this harness always replays
    the whole file); a registry-frozen spec can be passed instead.
    """
    by: Dict[str, List[float]] = {}
    for r in train_rows:
        b, v = r.get("vol_bucket"), _finite(r.get(vol_feature_column))
        if b is not None and v is not None:
            by.setdefault(str(b), []).append(v)
    labels = sorted(by)
    edges = [max(by[lb]) for lb in labels[:-1]]
    return {"symbol": symbol, "timeframe": timeframe, "vol_window_n": vol_window_n,
            "vol_bucket_labels": labels, "vol_bucket_edges": edges,
            "feature_column": "vol_bucket", "vol_feature_column": vol_feature_column}


def live_rows_for_bars(raw_rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any],
                       ts_keys: Iterable[str], *, symbol: str, timeframe: str,
                       window_bars: int = LIVE_WINDOW_BARS) -> Dict[str, Dict[str, Any]]:
    """Run the LIVE builder on the trailing window ending at each requested bar."""
    import pandas as pd  # noqa: PLC0415

    from src.runtime.regime_shadow import (  # noqa: PLC0415
        closes_from_candles, feature_row_for_predictor)

    raw = sorted(raw_rows, key=lambda r: str(r.get("ts", "")))
    idx = {str(r["ts"]): i for i, r in enumerate(raw)}
    stub = SimpleNamespace(wrapped=SimpleNamespace(regime_spec=dict(spec)))
    df_all = pd.DataFrame({
        "timestamp": pd.to_datetime([r["ts"] for r in raw], utc=True),
        "open": [float(r["open"]) for r in raw],
        "high": [float(r["high"]) for r in raw],
        "low": [float(r["low"]) for r in raw],
        "close": [float(r["close"]) for r in raw],
        "volume": [float(r.get("volume", 0.0) or 0.0) for r in raw],
    })
    out: Dict[str, Dict[str, Any]] = {}
    for ts in ts_keys:
        i = idx.get(str(ts))
        if i is None:
            continue
        df = df_all.iloc[max(0, i + 1 - window_bars): i + 1].reset_index(drop=True)
        row = feature_row_for_predictor(
            stub, {}, closes=closes_from_candles(df), symbol=symbol,
            timeframe=timeframe, candles_df=df)
        if row is not None:
            out[str(ts)] = dict(row)
    return out


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_parity(*, market_raw: Path, features: Sequence[str], categorical: Iterable[str],
               symbol: str, timeframe: str, vol_window_n: int = 20,
               vol_feature_column: str = "rolling_log_return_vol",
               funding_oi: Optional[Path] = None, funding_window_n: int = 168,
               vol_threshold: float = 0.005, trend_threshold: float = 0.01,
               bars: int = 500, spec: Optional[Mapping[str, Any]] = None,
               tol: float = DEFAULT_TOL) -> Dict[str, Any]:
    """Build both sides over the last ``bars`` train-eligible bars and compare."""
    from ml.datasets.families.market_features import MarketFeaturesBuilder  # noqa: PLC0415

    kw: Dict[str, Any] = dict(
        market_raw_path=market_raw, vol_window_n=vol_window_n,
        vol_threshold=vol_threshold, trend_threshold=trend_threshold,
        funding_window_n=funding_window_n)
    if funding_oi is not None:
        kw["funding_oi_path"] = funding_oi
    train_all = list(MarketFeaturesBuilder().iter_rows(**kw))
    train_rows = train_all[-bars:] if bars else train_all
    train_by_ts = {str(r["ts"]): r for r in train_rows}
    spec_source = "caller" if spec is not None else "inferred_from_train"
    if spec is None:
        spec = infer_regime_spec(train_all, symbol=symbol, timeframe=timeframe,
                                 vol_window_n=vol_window_n,
                                 vol_feature_column=vol_feature_column)
    raw = _load_jsonl(Path(market_raw) / "data.jsonl")
    live_by_ts = live_rows_for_bars(raw, spec, train_by_ts, symbol=symbol,
                                    timeframe=timeframe)
    rep = compare_features(train_by_ts, live_by_ts, features, categorical, tol)
    rep.update({"symbol": symbol, "timeframe": timeframe, "tol": tol,
                "funding_side_stream": str(funding_oi) if funding_oi else None,
                "spec_source": spec_source})
    return rep


def _manifest(model_id: str) -> Dict[str, Any]:
    import yaml  # noqa: PLC0415

    p = _REPO_ROOT / "ml" / "configs" / f"{model_id}.yaml"
    if not p.is_file():
        raise SystemExit(f"no manifest at {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _print(rep: Mapping[str, Any], model_id: str) -> None:
    print(f"== replay parity: {model_id} ({rep['symbol']}/{rep['timeframe']}) ==")
    print(f"  train_rows={rep['train_rows']} live_rows={rep['live_rows']} "
          f"paired_bars={rep['paired_bars']} tol={rep['tol']}")
    hdr = f"  {'feature':28s} {'verdict':13s} live_pres% live_nondef% train_nondef% max_abs_diff"
    print(hdr)
    for f, r in rep["features"].items():
        print(f"  {f:28s} {r['verdict']:13s} {r['live_present_pct']!s:>9} "
              f"{r['live_nondefault_pct']!s:>11} {r['train_nondefault_pct']!s:>12} "
              f"{r['max_abs_diff']}")
    print(f"HEAD_VERDICT {rep['head_verdict']}  drifting={rep['drifting_features']}")
    print("REPLAY_PARITY_DONE")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", required=True)
    ap.add_argument("--market-raw", required=True, type=Path,
                    help="market_raw dataset dir holding data.jsonl")
    ap.add_argument("--funding-oi", type=Path, default=None,
                    help="funding/OI side-stream dir (the TRAIN side only)")
    ap.add_argument("--bars", type=int, default=500)
    ap.add_argument("--vol-threshold", type=float, default=0.005)
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL)
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args(argv)

    m = _manifest(a.model_id)
    tc = m.get("trainer_config") or {}
    features = list(tc.get("feature_columns") or [])
    if not features:
        raise SystemExit(f"{a.model_id}: manifest declares no feature_columns")
    rep = run_parity(
        market_raw=a.market_raw, features=features,
        categorical=tc.get("categorical_columns") or [], symbol=a.symbol,
        timeframe=a.timeframe, vol_window_n=int(tc.get("vol_window_n") or 20),
        vol_feature_column=str(tc.get("vol_feature_column") or "rolling_log_return_vol"),
        funding_oi=a.funding_oi, vol_threshold=a.vol_threshold, bars=a.bars, tol=a.tol)
    _print(rep, a.model_id)
    if a.json_out:
        a.json_out.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
