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

FROZEN MONTHS FROM KAGGLE (row HF-LAKE-KAGGLE-LOADER)  when the private Kaggle mirror ``metis-market-lake-pNNN`` is mounted
(``/kaggle/input/datasets/<user>/...`` or ``LAKE_MIRROR_DIR``), a frozen partition (closed month) is read from the mirror, hash-verified
against its per-member SHA-256, and only the hot tail (open + previous month, or any month the mirror lacks) comes from HF. If the HF
MANIFEST cannot be read, the manifest is synthesized from the mirror (derived timeframes are rebuilt on read). See ml/datasets/lake_mirror.py.

READ STATE  an unreadable source is never an empty frame. ``load``/``iter_series`` raise ``LakeReadError`` when a needed partition cannot be
read (``on_unreadable="state"`` returns what was readable instead). Every frame carries ``df.attrs["lake_read"]`` and ``symbols()`` returns a
list with ``.read_state``: ``ok`` | ``partial`` (e.g. mirror-only manifest, hot tail not listed) | ``could_not_look``.

Credentials: a READ token in ``HF_TOKEN`` (the dataset is private). Never logged. Market data only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

from ml.datasets import lake_mirror

DEFAULT_REPO = "bentzbk/jta-market-lake"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class LakeReadError(Exception):
    """A needed lake source could not be read (read-state ``could_not_look``). ``.state`` carries the structured detail."""

    def __init__(self, msg: str, state: Optional[Dict] = None):
        super().__init__(msg)
        self.state = state or {}


class ReadList(list):
    """A list (e.g. of symbols) that also says whether the look was complete: ``.read_state`` ok | partial | could_not_look."""
    read_state: str = "ok"
    read_detail: Optional[Dict] = None


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
_MANIFEST_STATE: Dict[Tuple[str, Optional[str]], Dict] = {}


def manifest(revision: Optional[str] = None) -> Dict:
    key = (str(_local_dir() or repo_id()), revision)
    if key not in _MANIFEST_CACHE:
        try:
            _MANIFEST_CACHE[key] = json.loads(_fetch("MANIFEST.json", revision).read_text())
            _MANIFEST_STATE[key] = {"state": "ok", "source": "local" if _local_dir() is not None else "hf"}
        except Exception as e:  # noqa: BLE001  -- narrowed below: only the mirror fallback swallows, and it says so
            if _local_dir() is not None or not lake_mirror.available():
                raise
            ents = lake_mirror.synth_entries()
            if not ents:
                raise LakeReadError("HF MANIFEST unreadable and the Kaggle mirror holds no listable partitions",
                                    {"state": "could_not_look", "hf_error": str(e)[:200], "mirror": lake_mirror.describe()}) from e
            _MANIFEST_CACHE[key] = {"generated_at": None, "files": ents, "synthetic": "kaggle_mirror"}
            _MANIFEST_STATE[key] = {"state": "partial", "source": "kaggle_mirror_only", "hf_error": str(e)[:200],
                                    "hot_tail": "could_not_look",
                                    "note": "frozen months listed from the mirror; the hot tail (open + previous month) is not listed",
                                    "mirror": lake_mirror.describe()}
    return _MANIFEST_CACHE[key]


def read_state(revision: Optional[str] = None) -> Dict:
    """How the manifest was obtained: ``state`` ok | partial, ``source`` hf | local | kaggle_mirror_only (+ detail)."""
    manifest(revision)
    return dict(_MANIFEST_STATE[(str(_local_dir() or repo_id()), revision)])


def entries(asset_class: str, market: str, tf: str, revision: Optional[str] = None) -> List[Dict]:
    return [e for e in manifest(revision)["files"]
            if e.get("asset_class") == asset_class and e.get("market") == market and e.get("tf") == tf
            and (e.get("rows") or 0) > 0 and (e.get("path") or e.get("partitions"))]


def symbols(asset_class: str, market: str, tf: str, min_days: int = 0, min_rows: int = 0,
            revision: Optional[str] = None) -> List[str]:
    """Symbols with data at (asset_class, market, tf). Includes DELISTED series -- filter by date, not by today."""
    out = ReadList()
    for e in entries(asset_class, market, tf, revision):
        span = (pd.Timestamp(e["last"]) - pd.Timestamp(e["first"])).days
        if span >= min_days and int(e["rows"]) >= min_rows:
            out.append(e["symbol"])
    out.sort()
    st = read_state(revision)
    out.read_state, out.read_detail = st["state"], st
    return out


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


class _ReadLog:
    """What one read touched: where each partition came from, and every partition that could not be read."""

    def __init__(self) -> None:
        self.mirror = 0
        self.hf = 0
        self.selected = 0   # partitions the request selected from the manifest (0 with state ok = the window holds no data)
        self.unreadable: List[Dict] = []

    def state(self) -> Dict:
        return {"state": "ok" if not self.unreadable else ("could_not_look" if not (self.mirror or self.hf) else "partial"),
                "from_kaggle_mirror": self.mirror, "from_hf_or_local": self.hf, "partitions_selected": self.selected, "could_not_look": self.unreadable[:20],
                "n_could_not_look": len(self.unreadable)}


def _fetch_partition(path: str, revision: Optional[str], log: _ReadLog) -> Optional[Path]:
    """A frozen partition from the Kaggle mirror when it holds it (verified), else HF / LAKE_LOCAL_DIR. None = could not look (logged)."""
    why = None
    if _local_dir() is None and lake_mirror.available() and path in lake_mirror.index()[0] and lake_mirror.is_frozen_name(path):
        try:
            p = lake_mirror.fetch(path)
            log.mirror += 1
            return p
        except Exception as ex:  # noqa: BLE001  -- the failure is recorded; HF is tried next
            why = f"mirror: {str(ex)[:160]}"
    try:
        p = _fetch(path, revision)
        log.hf += 1
        return p
    except Exception as ex:  # noqa: BLE001  -- recorded as could_not_look, never turned into an empty frame
        log.unreadable.append({"path": path, "why": (why + "; " if why else "") + f"{type(ex).__name__}: {str(ex)[:160]}"})
        return None


def frozen_end(now=None) -> str:
    """First day of the oldest NON-frozen month (``YYYY-MM-01``): an ``end=`` that keeps a read inside the immutable, mirrored history."""
    now = now or pd.Timestamp.now(tz="UTC")
    idx = now.year * 12 + now.month - 1 - 1  # open month and the previous one are the hot tail
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}-01"


def _flag_unlisted_tail(e: Dict, start, end, log: _ReadLog) -> None:
    """Mirror-only manifest: the HF listing was unreadable, so every month after the last listed one is UNKNOWN, not absent. A window that
    reaches past it gets an explicit could_not_look entry instead of silently returning fewer rows."""
    last_month = max(e["partitions"])  # YYYY-MM (the mirror holds monthly partitions)
    if last_month < (lake_mirror.last_month() or last_month):
        return  # the series stopped before the copy reached its end (delisted): nothing is known to be missing after it
    tail_from = pd.Timestamp(last_month + "-01", tz="UTC") + pd.offsets.MonthBegin(1)
    s = pd.Timestamp(start, tz="UTC") if start is not None else None
    t = pd.Timestamp(end, tz="UTC") if end is not None else pd.Timestamp.now(tz="UTC")
    if t > tail_from and (s is None or s < t):
        log.unreadable.append({"path": f"crypto/{e['market']}/{e['tf'] if not e.get('derive_in_loader') else e['derived_from']}/{e['symbol']}/"
                                       f"{tail_from.strftime('%Y-%m')}..", "why": "months after the last mirrored one are not listed: HF MANIFEST "
                                       f"unreadable (mirror-only). Pass end<={frozen_end()} or on_unreadable='state'"})


def _read(e: Dict, start=None, end=None, columns: Optional[Sequence[str]] = None, revision=None,
          log: Optional[_ReadLog] = None) -> pd.DataFrame:
    log = log if log is not None else _ReadLog()
    derive = bool(e.get("derive_in_loader"))
    filters = []
    if start is not None:
        filters.append(("ts", ">=", pd.Timestamp(start, tz="UTC")))
    if end is not None:
        filters.append(("ts", "<", pd.Timestamp(end, tz="UTC")))
    if e.get("tf_col"):  # derived timeframes share one file per partition; select this series' tf
        filters.append((e["tf_col"], "==", e["tf"]))
    # a loader-derived timeframe reads whole base months (a bar never straddles a month) and filters after resampling
    pq_filters = None if derive else (filters or None)
    pq_cols = None if derive else (list(columns) if columns else None)
    frames = []
    if e.get("synthetic"):  # manifest rebuilt from the mirror alone: months after the last listed one were never looked at
        _flag_unlisted_tail(e, start, end, log)
    for path in sorted(set(_paths(e, start, end))):
        fp = _fetch_partition(path, revision, log)
        if fp is not None:
            frames.append(pd.read_parquet(fp, columns=pq_cols, filters=pq_filters))
    n_paths = len(set(_paths(e, start, end)))
    frames = [f for f in frames if len(f)]
    if not frames:
        df = pd.DataFrame(columns=list(columns) if columns else None)
    else:
        df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        if derive:
            df = resample(df, e["tf"], base=e["derived_from"])
            if start is not None:
                df = df[df["ts"] >= pd.Timestamp(start, tz="UTC")]
            if end is not None:
                df = df[df["ts"] < pd.Timestamp(end, tz="UTC")]
            df = df.reset_index(drop=True)
            if columns:
                df = df[[c for c in columns if c in df.columns]]
    log.selected += n_paths
    df.attrs["lake_read"] = log.state()
    return df


def _check(log: _ReadLog, on_unreadable: str, what: str) -> None:
    if log.unreadable and on_unreadable == "raise":
        raise LakeReadError(f"{what}: {len(log.unreadable)} partition(s) could not be read "
                            f"(first: {log.unreadable[0]['path']}: {log.unreadable[0]['why']})", log.state())


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
         columns: Optional[Sequence[str]] = None, revision: Optional[str] = None, on_unreadable: str = "raise") -> pd.DataFrame:
    """Long frame (symbol, ts, ...). ``syms=None`` means every symbol in the manifest -- mind the memory.

    A partition that cannot be read raises ``LakeReadError`` (``on_unreadable="state"`` returns the rest). ``df.attrs["lake_read"]`` always
    says where the data came from and what could not be looked at."""
    want = set(syms) if syms else None
    log = _ReadLog()
    frames = []
    seen = set()
    for e in entries(asset_class, market, tf, revision):
        if want is not None and e["symbol"] not in want:
            continue
        seen.add(e["symbol"])
        df = _read(e, start, end, columns, revision, log)
        df.insert(0, "symbol", e["symbol"])
        frames.append(df)
    for sym in sorted((want or set()) - seen):  # asked for, not listed: unknown, never a silent absence
        log.unreadable.append({"path": f"{asset_class}/{market}/{tf}/{sym}", "why": "symbol not in the manifest for this (asset, market, tf)"})
    _check(log, on_unreadable, f"lake.load({asset_class}/{market}/{tf})")
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out.attrs["lake_read"] = log.state()
    return out


def iter_series(asset_class: str, market: str, tf: str, syms: Optional[Sequence[str]] = None, start=None, end=None,
                columns: Optional[Sequence[str]] = None, revision: Optional[str] = None, on_unreadable: str = "raise"
                ) -> Iterator[Tuple[str, pd.DataFrame]]:
    """Stream one series at a time (bounded memory) -- the shape a pooled trainer over 1,000+ series wants."""
    want = set(syms) if syms else None
    for e in entries(asset_class, market, tf, revision):
        if want is None or e["symbol"] in want:
            log = _ReadLog()
            df = _read(e, start, end, columns, revision, log)
            _check(log, on_unreadable, f"lake.iter_series({e['symbol']})")
            yield e["symbol"], df


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
            "n_files": len(m.get("files", [])), "manifest_state": read_state(revision),
            "frozen_source": "kaggle_mirror" if (_local_dir() is None and lake_mirror.available()) else "hf",
            "mirror_plan_ids": lake_mirror.describe()["plan_ids"] if lake_mirror.available() else []}
