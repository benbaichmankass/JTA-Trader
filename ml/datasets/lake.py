"""Loader for the market data lake on Hugging Face -- the one call the ML lanes use to read pooled market data.

Row MARKET-DATA-LAKE; design docs/data/market-data-lake.md; dataset ``config/data_universe.yaml::storage.hf_dataset``.

    from ml.datasets import lake
    m = lake.manifest()                                         # every series: source, licence, first/last, rows, gaps
    syms = lake.symbols("crypto", "um_perp", "1h", min_days=365)
    df = lake.load("crypto", "um_perp", "1h", ["BTCUSDT", "ETHUSDT"], start="2022-01-01")
    for sym, df in lake.iter_series("crypto", "um_perp", "1h"):  # streams one file at a time (bounded memory)
        ...
    lake.liquid_mask(df, adv_usd=5e6)                           # point-in-time liquidity floor (rolling, as-of)
    lake.resample(df_1m, "2h")                                  # any other timeframe, same rule as the stored ones
    lake.health()                                               # latest feed health record

STORED TIMEFRAMES  the base is the finest each source publishes (crypto 1m); 5m/15m/1h/4h/1d are DERIVED from it by
scripts/data_lake/resample.py and stored too (columns n_base / complete mark thin or partial bars).

READ PATH  ``hf_hub_download`` into the HF cache (``HF_HOME``; on Kaggle ``/kaggle/working``); a file is fetched once
per revision and re-read from the cache after. ``LAKE_LOCAL_DIR`` points the loader at a local copy instead (a Kaggle
dataset mount, a runner scratch dir, or a test fixture) -- same layout, no network.

PINNING  ``revision=`` takes an HF tag written by ``scripts/data_lake/hf_publish.py manifest`` (``vYYYYMMDD-HHMM``) so a
training run records exactly which data it read (``lake.revision_info()``).

Credentials: a READ token in ``HF_TOKEN`` (the dataset is private). Never logged. Market data only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

DEFAULT_REPO = "bentzbk/jta-market-lake"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_id() -> str:
    if os.environ.get("LAKE_HF_REPO"):
        return os.environ["LAKE_HF_REPO"]
    try:
        import yaml
        cfg = yaml.safe_load((_REPO_ROOT / "config" / "data_universe.yaml").read_text())
        return cfg.get("storage", {}).get("hf_dataset") or DEFAULT_REPO
    except Exception:
        return DEFAULT_REPO


def _local_dir() -> Optional[Path]:
    v = os.environ.get("LAKE_LOCAL_DIR")
    return Path(v) if v else None


def _fetch(path: str, revision: Optional[str] = None) -> Path:
    local = _local_dir()
    if local is not None:
        p = local / path
        if not p.exists():
            raise FileNotFoundError(f"{p} (LAKE_LOCAL_DIR)")
        return p
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(repo_id(), path, repo_type="dataset", revision=revision,
                                token=os.environ.get("HF_TOKEN") or None))


_MANIFEST_CACHE: Dict[Tuple[str, Optional[str]], Dict] = {}


def manifest(revision: Optional[str] = None) -> Dict:
    key = (str(_local_dir() or repo_id()), revision)
    if key not in _MANIFEST_CACHE:
        _MANIFEST_CACHE[key] = json.loads(_fetch("MANIFEST.json", revision).read_text())
    return _MANIFEST_CACHE[key]


def entries(asset_class: str, market: str, tf: str, revision: Optional[str] = None) -> List[Dict]:
    return [e for e in manifest(revision)["files"]
            if e.get("asset_class") == asset_class and e.get("market") == market and e.get("tf") == tf
            and (e.get("rows") or 0) > 0 and (e.get("path") or e.get("partitions"))]


def symbols(asset_class: str, market: str, tf: str, min_days: int = 0, min_rows: int = 0,
            revision: Optional[str] = None) -> List[str]:
    """Symbols with data at (asset_class, market, tf). Includes DELISTED series -- filter by date, not by today."""
    out = []
    for e in entries(asset_class, market, tf, revision):
        span = (pd.Timestamp(e["last"]) - pd.Timestamp(e["first"])).days
        if span >= min_days and int(e["rows"]) >= min_rows:
            out.append(e["symbol"])
    return sorted(out)


def _paths(e: Dict, start=None, end=None) -> List[str]:
    """File paths for a series: one ``path``, or its month/year ``partitions`` overlapping [start, end)."""
    if e.get("partitions"):
        s = pd.Timestamp(start, tz="UTC") if start is not None else None
        t = pd.Timestamp(end, tz="UTC") if end is not None else None
        out = []
        for _, p in sorted(e["partitions"].items()):
            if not p.get("path") or not (p.get("rows") or 0):
                continue
            if s is not None and p.get("last") and pd.Timestamp(p["last"]) < s:
                continue
            if t is not None and p.get("first") and pd.Timestamp(p["first"]) >= t:
                continue
            out.append(p["path"])
        return out
    return [e["path"]]


def _read(e: Dict, start=None, end=None, columns: Optional[Sequence[str]] = None, revision=None) -> pd.DataFrame:
    filters = []
    if start is not None:
        filters.append(("ts", ">=", pd.Timestamp(start, tz="UTC")))
    if end is not None:
        filters.append(("ts", "<", pd.Timestamp(end, tz="UTC")))
    if e.get("tf_col"):  # derived timeframes share one file per partition; select this series' tf
        filters.append((e["tf_col"], "==", e["tf"]))
    frames = [pd.read_parquet(_fetch(p, revision), columns=list(columns) if columns else None, filters=filters or None)
              for p in sorted(set(_paths(e, start, end)))]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=list(columns) if columns else None)
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def resample(df: pd.DataFrame, tf: str, base: str = "1m") -> pd.DataFrame:
    """Same deterministic rule the lake uses to derive its stored higher timeframes (scripts/data_lake/resample.py),
    for a timeframe the lake does not store (e.g. 3m, 2h)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("lake_resample", _REPO_ROOT / "scripts" / "data_lake" / "resample.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.MINUTES.setdefault(tf, int(pd.Timedelta(tf.replace("m", "min")).total_seconds() // 60))
    if "symbol" in df.columns:
        return pd.concat([mod.resample_frame(g.drop(columns="symbol"), base, tf).assign(symbol=s)
                          for s, g in df.groupby("symbol")], ignore_index=True)
    return mod.resample_frame(df, base, tf)


def health(revision: Optional[str] = None) -> Dict:
    """The latest machine-readable health record (scripts/data_lake/validate.py)."""
    return json.loads(_fetch("health/latest.json", revision).read_text())


def load(asset_class: str, market: str, tf: str, syms: Optional[Sequence[str]] = None, start=None, end=None,
         columns: Optional[Sequence[str]] = None, revision: Optional[str] = None) -> pd.DataFrame:
    """Long frame (symbol, ts, ...). ``syms=None`` means every symbol in the manifest -- mind the memory."""
    want = set(syms) if syms else None
    frames = []
    for e in entries(asset_class, market, tf, revision):
        if want is not None and e["symbol"] not in want:
            continue
        df = _read(e, start, end, columns, revision)
        df.insert(0, "symbol", e["symbol"])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def iter_series(asset_class: str, market: str, tf: str, syms: Optional[Sequence[str]] = None, start=None, end=None,
                columns: Optional[Sequence[str]] = None, revision: Optional[str] = None
                ) -> Iterator[Tuple[str, pd.DataFrame]]:
    """Stream one series at a time (bounded memory) -- the shape a pooled trainer over 1,000+ series wants."""
    want = set(syms) if syms else None
    for e in entries(asset_class, market, tf, revision):
        if want is None or e["symbol"] in want:
            yield e["symbol"], _read(e, start, end, columns, revision)


def liquid_mask(df: pd.DataFrame, adv_usd: float = 5e6, window: int = 20, min_price: float = 0.0) -> pd.Series:
    """POINT-IN-TIME liquidity floor: True where the TRAILING ``window``-bar mean dollar volume (excluding the current
    bar) clears ``adv_usd``. Uses ``quote_volume`` when present (crypto), else close*volume. Per symbol when a
    ``symbol`` column exists. A bar never sees its own or later volume, so the floor adds no lookahead."""
    dv = df["quote_volume"] if "quote_volume" in df.columns else df["close"] * df["volume"]
    key = df["symbol"] if "symbol" in df.columns else pd.Series(0, index=df.index)
    adv = dv.groupby(key).transform(lambda s: s.shift(1).rolling(window, min_periods=window).mean())
    m = adv >= adv_usd
    if min_price:
        m &= df["close"].groupby(key).shift(1) >= min_price
    return m.fillna(False)


def revision_info(revision: Optional[str] = None) -> Dict[str, object]:
    """What to record in a training run's metadata so the data it read is reproducible."""
    m = manifest(revision)
    return {"lake_repo": repo_id() if _local_dir() is None else f"local:{_local_dir()}",
            "lake_revision": revision or "main", "manifest_generated_at": m.get("generated_at"),
            "n_files": len(m.get("files", []))}
