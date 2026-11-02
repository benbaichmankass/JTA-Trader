"""Lake -> klines-cache adapter: the seam that lets the pooled ENTRY pipeline (ml_decision_entry / ml_entry_levers) train from the lake.

Row ML-DATA-WIRING. Today's source is the klines12 stream pickles; the harness reads a per-symbol CACHE of ``ts, open, high, low,
close, volume`` pickles (``E.build_table(cache, syms)``). ``build_klines_cache`` writes that identical cache from
``ml.datasets.lake`` with the SAME cleaning the stream path applies (sort, drop duplicate ts, drop flat zero-volume bars, ts >= start),
so nothing downstream changes. Lake ``ts`` is the bar OPEN in UTC, same as the streams' ``open_time``.

``parity`` compares a lake cache with a stream cache on their overlapping window and reports every difference (never raises on a diff).
``dataset_selection`` is the ONE declared place a model's lake query lives: ``ml/datasets/lake_selection.yaml``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ml.datasets import lake

COLS = ["ts", "open", "high", "low", "close", "volume"]
SELECTION_FILE = Path(__file__).resolve().parents[2] / "ml" / "datasets" / "lake_selection.yaml"


def clean(df: pd.DataFrame, start: str, end: Optional[str] = None) -> pd.DataFrame:
    k = df.sort_values("ts").drop_duplicates("ts")
    for c in COLS[1:]:
        k[c] = k[c].astype(float)
    k = k[~((k["volume"] == 0) & (k["high"] == k["low"])) & (k["ts"] >= pd.Timestamp(start, tz="UTC"))]
    if end is not None:
        k = k[k["ts"] < pd.Timestamp(end, tz="UTC")]
    return k[COLS].reset_index(drop=True)


def build_klines_cache(out: Path, syms: Sequence[str], start: str, end: Optional[str] = None, tf: str = "1h",
                       asset_class: str = "crypto", market: str = "um_perp", revision: Optional[str] = None
                       ) -> Tuple[Path, List[str], Dict[str, object]]:
    """Write ``<out>/klines_lake/<sym>.pkl`` for every requested symbol the lake holds. Returns (cache, symbols written, revision_info)."""
    cache = Path(out) / "klines_lake"
    cache.mkdir(parents=True, exist_ok=True)
    have = set(lake.symbols(asset_class, market, tf, revision=revision))
    written = []
    for sym, df in lake.iter_series(asset_class, market, tf, [s for s in syms if s in have], end=end,
                                    columns=COLS, revision=revision):
        k = clean(df, start, end)
        if len(k):
            k.to_pickle(cache / f"{sym}.pkl")
            written.append(sym)
    info = dict(lake.revision_info(revision), asset_class=asset_class, market=market, tf=tf, start=start, end=end,
                symbols_requested=len(syms), symbols_written=len(written),
                symbols_missing=sorted(set(syms) - set(written)))
    return cache, written, info


def parity(stream_cache: Path, lake_cache: Path, syms: Sequence[str], tol: float = 1e-9) -> Dict[str, object]:
    """Row/value parity on the OVERLAPPING window per symbol. ``identical`` is True only when every shared symbol has the same ts set
    and values within ``tol`` on the overlap; otherwise ``diffs`` lists what differs (rows only in one side, max abs value delta)."""
    diffs, per = [], {}
    for s in syms:
        a, b = Path(stream_cache) / f"{s}.pkl", Path(lake_cache) / f"{s}.pkl"
        if not (a.exists() and b.exists()):
            diffs.append({"symbol": s, "issue": "missing_in_" + ("lake" if a.exists() else "stream")})
            continue
        x, y = pd.read_pickle(a), pd.read_pickle(b)
        lo, hi = max(x.ts.min(), y.ts.min()), min(x.ts.max(), y.ts.max())
        x, y = x[(x.ts >= lo) & (x.ts <= hi)].set_index("ts"), y[(y.ts >= lo) & (y.ts <= hi)].set_index("ts")
        only_x, only_y = x.index.difference(y.index), y.index.difference(x.index)
        both = x.index.intersection(y.index)
        dmax = float((x.loc[both, COLS[1:]] - y.loc[both, COLS[1:]]).abs().to_numpy().max()) if len(both) else None
        per[s] = {"overlap_rows": len(both), "only_stream": len(only_x), "only_lake": len(only_y), "max_abs_diff": dmax}
        if not len(both) or len(only_x) or len(only_y) or (dmax is not None and dmax > tol):
            diffs.append({"symbol": s, **per[s]})
    return {"identical": not diffs, "symbols_compared": len(per), "diffs": diffs, "per_symbol": per}


def dataset_selection(model: str) -> Dict[str, object]:
    """The declared lake query for ``model`` (ml/datasets/lake_selection.yaml). KeyError if undeclared."""
    import yaml
    return yaml.safe_load(SELECTION_FILE.read_text())["models"][model]


def freshness(model: str, revision: Optional[str] = None) -> Dict[str, object]:
    """Which lake partition a model last trained on vs what the lake holds now. ``read_state`` is "unknown" (never 0) when the model
    records no training boundary or the model has no wired lake path. Lag is measured on the model's declared symbols."""
    sel = dataset_selection(model)
    if sel.get("same_as"):
        sel = dataset_selection(sel["same_as"])
    if sel.get("status") != "wired":
        return {"model": model, "read_state": "unknown", "why": f"lake path {sel.get('status')}"}
    import json
    art = json.loads((Path(__file__).resolve().parents[2] / sel["artifact"]).read_text())
    trained = art.get("lake_trained_through") or art.get("train_end_exclusive")
    lasts = [pd.Timestamp(e["last"]) for e in lake.entries(sel["asset_class"], sel["market"], sel["tf"], revision)]
    if not trained or not lasts:
        return {"model": model, "read_state": "unknown", "why": "no training boundary recorded or empty lake"}
    lake_last = max(lasts)
    t = pd.Timestamp(trained)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return {"model": model, "read_state": "read", "trained_through": str(t), "lake_last": str(lake_last),
            "lag_days": round((lake_last - t).total_seconds() / 86400, 1),
            "boundary_source": "lake_trained_through" if art.get("lake_trained_through") else "train_end_exclusive (pre-lake artifact)",
            "lake_revision": art.get("lake_revision")}
