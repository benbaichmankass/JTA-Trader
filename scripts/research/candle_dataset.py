#!/usr/bin/env python3
# wiring: .github/workflows/research-candles-kaggle.yml (build + publish), scripts/research/regime_debt_matrix.py::_fetch_csv (read),
#         scripts/research/compute_router.py (coverage), scripts/research/kaggle_run.py + kaggle_unit/kernel_main.py (mount)
"""KAGGLE-CANDLES (2026-11-02): the public price data the exit-lever research units download at run time, as a versioned Kaggle DATASET.

WHY. COMPUTE-PREFER-KAGGLE (#22337) moved 1 of 153 queued units because 81 of them fetch keyless public candles when they run
(``scripts/research/exit_lever_ablation.py`` -> ``regime_debt_matrix._fetch_csv``) and a Kaggle CPU kernel has no internet. This module
builds those candles ONCE on a GitHub runner (which has internet), and the kernel reads them by mount.

SOURCE ORDER (per feed). Binance USD-M crypto: the market data lake on Hugging Face first (``ml/datasets/lake.py``; the SAME archive,
data.binance.vision futures/um, already captured -- nothing is re-downloaded when the lake holds it), then the unit's own network fetch
as the fallback. Yahoo equities/ETFs/futures: the lake does not hold the Yahoo intraday series, so the runner fetches them with the very
function the units call. No data is committed to git: the dataset lives on Kaggle; only a <10 KB coverage record is committed.

READ PATH. ``CANDLE_DATA_ROOT`` (set by kernel_main.py when the dataset is mounted) -> ``serve()`` writes the SAME CSV the network fetch
would have written (``timestamp,open,high,low,close,volume``, last ``days`` days) and returns True; any miss returns False and the caller
falls back to the network. A short or absent feed never errors.

Tier 1 tooling: reads public data, writes a private Kaggle dataset. Gates this adds or changes: none.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DATASET_SLUG = "metis-research-candles"
MANIFEST_NAME = "CANDLES_MANIFEST.json"
COVERAGE_PATH = _REPO / "comms" / "research" / "candle_dataset" / "coverage.json"
CSV_COLS = ["timestamp", "open", "high", "low", "close", "volume"]
#: Bybit interval code (what resolve_feed speaks for crypto) -> (lake stored tf, or None when it must be derived, base tf, target tf)
_LAKE_TF = {"5": ("5m", None), "15": ("15m", None), "60": ("1h", None), "240": ("4h", None), "D": ("1d", None),
            "120": ("1h", "2h")}
FeedKey = Tuple[str, str, str]      # (source, ticker, interval) exactly as regime_debt_matrix.resolve_feed spells them


def feed_id(key: FeedKey) -> str:
    return "__".join(k.replace("/", "-").replace("=", "-") for k in key)


def file_name(key: FeedKey) -> str:
    return f"candles__{feed_id(key)}.csv.gz"


# ── which feeds are needed ──────────────────────────────────────────────────────────────────────────────
_STRATEGIES_CACHE: Dict[Tuple[str, int, int], Dict[str, Any]] = {}


def _strategies() -> Dict[str, Any]:
    """The `strategies:` map of config/strategies.yaml, parsed once per file VERSION (path, mtime_ns, size).

    The dispatcher plans every queue unit and `covers()` calls this per unit: re-parsing the (large) YAML 549 times was
    ~97% of a single-unit dry run's 71 s (PI RQ-DISPATCHER-ONLY-FULL-SCAN, cProfile 2026-11-12). Keyed on the file's
    stat so an edited file is re-read; callers only read the result."""
    import yaml  # noqa: PLC0415
    path = _REPO / "config" / "strategies.yaml"
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    hit = _STRATEGIES_CACHE.get(key)
    if hit is None:
        hit = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("strategies") or {}
        _STRATEGIES_CACHE.clear()
        _STRATEGIES_CACHE[key] = hit
    return hit


def _opt(cmd: List[str], flag: str) -> Optional[str]:
    return cmd[cmd.index(flag) + 1] if flag in cmd and cmd.index(flag) + 1 < len(cmd) else None


def unit_feed(entry: Dict[str, Any], strategies: Optional[Dict[str, Any]] = None) -> Optional[Tuple[FeedKey, int]]:
    """(feed key, days requested) for an exit_lever_ablation unit, else None. The feed is resolved by the harness's own
    ``resolve_feed``, never re-implemented. A unit with ``--data-csv`` or another script is not a fetch and returns None."""
    cmd = (entry.get("run") or {}).get("command")
    if not (isinstance(cmd, list) and any(str(c).endswith("exit_lever_ablation.py") for c in cmd)) or "--data-csv" in cmd:
        return None
    cmd = [str(c) for c in cmd]
    leg = _opt(cmd, "--leg")
    cfg = (strategies if strategies is not None else _strategies()).get(leg or "")
    if not leg or not isinstance(cfg, dict):
        return None
    sym = _opt(cmd, "--symbol") or (cfg.get("symbols") or [None])[0]
    tf = cfg.get("timeframe")
    if not sym or not tf:
        return None
    if _opt(cmd, "--non-crypto-source"):        # the dukascopy lane is a different feed; not published here
        return None
    import regime_debt_matrix as rdm  # noqa: PLC0415
    fd = rdm.resolve_feed(str(sym), str(tf))
    days = _opt(cmd, "--days")
    if days is None:      # the harness default (argparse) -- read it, do not guess
        return None
    return (fd["source"], fd["ticker"], fd["interval"]), int(days)


def needed_feeds(queue_dir: Optional[Path] = None) -> Dict[FeedKey, int]:
    """Every feed a QUEUED exit_lever_ablation unit fetches -> the largest `--days` any of them asks for."""
    import yaml  # noqa: PLC0415
    strategies = _strategies()
    out: Dict[FeedKey, int] = {}
    for p in sorted((queue_dir or _REPO / "research" / "queue").glob("RQ-*.yaml")):
        try:
            e = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(e, dict) or e.get("status") != "queued":
            continue
        uf = unit_feed(e, strategies)
        if uf:
            out[uf[0]] = max(out.get(uf[0], 0), uf[1])
    return out


# ── coverage (the router's view) ────────────────────────────────────────────────────────────────────────
def load_coverage(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or COVERAGE_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def covers(entry: Dict[str, Any], coverage: Optional[Dict[str, Any]] = None,
           strategies: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """(True, why) when the published candle dataset holds every candle this unit would fetch. Checked, never trusted: the feed
    is derived from the unit's own command and must be listed `ok` in the coverage record with `days_built >= --days`."""
    cov = coverage if coverage is not None else load_coverage()
    if not cov.get("feeds"):
        return False, "no candle dataset coverage record (dataset not published yet)"
    uf = unit_feed(entry, strategies)
    if not uf:
        return False, "not an exit_lever_ablation fetch unit"
    key, days = uf
    f = cov["feeds"].get(feed_id(key))
    if not f or f.get("status") != "ok":
        return False, f"feed {feed_id(key)} not in the dataset ({(f or {}).get('error', 'absent')})"
    if int(f.get("days_built", 0)) < days:
        return False, f"feed {feed_id(key)} built for {f.get('days_built')} d < unit --days {days}"
    return True, f"feed {feed_id(key)} published ({f.get('rows')} rows to {f.get('last_ts')})"


# ── build (runs on a GitHub runner: has internet + HF_TOKEN + Kaggle token) ─────────────────────────────
def _write_csv_gz(df, path: Path) -> Dict[str, Any]:
    import pandas as pd  # noqa: PLC0415
    df = df[CSV_COLS].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    raw = df.to_csv(index=False).encode("utf-8")
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(raw)
    return {"rows": int(len(df)), "first_ts": str(df["timestamp"].iloc[0]), "last_ts": str(df["timestamp"].iloc[-1]),
            "sha256_csv": hashlib.sha256(raw).hexdigest(), "bytes_gz": path.stat().st_size}


def _from_lake(key: FeedKey, days: int):
    """Binance candles from the HF lake, shaped like fetch_backtest_candles' CSV. Raises when the lake lacks the series."""
    import pandas as pd  # noqa: PLC0415

    from ml.datasets import lake  # noqa: PLC0415
    source, ticker, interval = key
    if source != "binance" or interval not in _LAKE_TF:
        raise LookupError(f"lake has no {source}/{interval}")
    tf, derive = _LAKE_TF[interval]
    start = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=days + 2)).tz_localize(None)   # lake._read re-localizes: pass naive UTC
    df = lake.load("crypto", "um_perp", tf, [ticker], start=start, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        raise LookupError(f"lake: no {ticker} {tf} rows since {start.date()}")
    df = df.drop(columns="symbol").sort_values("ts")
    if derive:
        df = lake.resample(df, derive, base=tf)
        if "complete" in df.columns and len(df) and not bool(df["complete"].iloc[-1]):
            df = df.iloc[:-1]            # the still-open last bar: the archive fetch never contains it either
    df = df.rename(columns={"ts": "timestamp"})
    return df


def _from_network(key: FeedKey, days: int, out: Path):
    import pandas as pd  # noqa: PLC0415
    import regime_debt_matrix as rdm  # noqa: PLC0415
    source, ticker, interval = key
    rdm._fetch_csv({"source": source, "ticker": ticker, "interval": interval}, days, str(out))
    return pd.read_csv(out)


def build(out_dir: Path, feeds: Dict[FeedKey, int], days_floor: int = 0, use_lake: bool = True) -> Dict[str, Any]:
    """Write one csv.gz per feed + CANDLES_MANIFEST.json. A feed that fails is recorded with its error and the rest continue."""
    import tempfile  # noqa: PLC0415
    out_dir.mkdir(parents=True, exist_ok=True)
    days_all = max([days_floor, *feeds.values()] or [days_floor])
    entries: Dict[str, Any] = {}
    for key in sorted(feeds):
        days_feed = max(days_floor, feeds[key])        # per feed: a 5m feed needs 760 d, a 4h feed 7,300 d; never the global max
        fid, origin, err = feed_id(key), None, None
        df = None
        if use_lake and key[0] == "binance" and os.environ.get("HF_TOKEN"):
            try:
                df, origin = _from_lake(key, days_feed), "lake"
            except Exception as exc:  # allow-silent: recorded in the manifest as lake_error; the network fetch is the fallback
                err = f"lake: {type(exc).__name__}: {str(exc)[:160]}"
                print(f"lake miss {fid}: {err}")
        if df is None:
            try:
                with tempfile.TemporaryDirectory() as td:
                    df, origin = _from_network(key, days_feed, Path(td) / "c.csv"), "network"
            except Exception as exc:  # allow-silent: recorded as status=failed with the reason; the feed is simply not covered
                entries[fid] = {"status": "failed", "source": key[0], "ticker": key[1], "interval": key[2],
                                "error": ((err + " | ") if err else "") + f"network: {type(exc).__name__}: {str(exc)[:200]}"}
                print(f"FAILED {fid}: {entries[fid]['error']}")
                continue
        info = _write_csv_gz(df, out_dir / file_name(key))
        entries[fid] = {"status": "ok", "source": key[0], "ticker": key[1], "interval": key[2], "origin": origin,
                        "days_built": days_feed, "file": file_name(key), **info, **({"lake_error": err} if err else {})}
        print(f"ok {fid}: {info['rows']} rows {info['first_ts'][:10]}..{info['last_ts'][:10]} via {origin}")
    man = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dataset": DATASET_SLUG,
           "days_built": days_all, "feeds": entries,
           "counts": {"ok": sum(e["status"] == "ok" for e in entries.values()), "failed": sum(e["status"] != "ok" for e in entries.values())}}
    (out_dir / MANIFEST_NAME).write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return man


def coverage_record(man: Dict[str, Any]) -> Dict[str, Any]:
    """The small committed record the router reads (no data: ids, row counts, last bars, status)."""
    keep = ("status", "origin", "rows", "first_ts", "last_ts", "days_built", "error", "sha256_csv")
    return {"dataset": man["dataset"], "generated_at": man["generated_at"], "days_built": man["days_built"], "counts": man["counts"],
            "feeds": {k: {a: v[a] for a in keep if a in v} for k, v in sorted(man["feeds"].items())}}


# ── read (runs in the unit: Kaggle kernel or anywhere CANDLE_DATA_ROOT is set) ───────────────────────────
def _find_root(root: Optional[str] = None) -> Optional[Path]:
    r = root or os.environ.get("CANDLE_DATA_ROOT")
    return Path(r) if r and (Path(r) / MANIFEST_NAME).is_file() else None


def serve(key: FeedKey, days: int, out: str, root: Optional[str] = None) -> bool:
    """Write `out` from the published dataset when it holds this feed for >= `days`. False = fall back to the network."""
    import pandas as pd  # noqa: PLC0415
    base = _find_root(root)
    if base is None:
        return False
    try:
        man = json.loads((base / MANIFEST_NAME).read_text(encoding="utf-8"))
        f = man["feeds"].get(feed_id(key))
        if not f or f.get("status") != "ok" or int(f.get("days_built", 0)) < days:
            return False
        p = base / f["file"]
        if not p.is_file():
            p = base / f["file"][:-3]            # Kaggle may extract an uploaded .gz
        if p.is_dir():                           # ...or into a DIRECTORY of that name (seen 2026-11-02, 5e01-02/03/04: IsADirectoryError)
            inner = sorted(q for q in p.iterdir() if q.is_file() and q.suffix in (".csv", ".gz"))
            if not inner:
                return False
            p = inner[0]
        df = pd.read_csv(p)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        df = df[ts >= ts.max() - pd.Timedelta(days=days)]
        if df.empty:
            return False
        df[CSV_COLS].to_csv(out, index=False)
        print(f"candle dataset: served {feed_id(key)} ({len(df)} rows, last {ts.max()}) from {base.name}")
        return True
    except Exception as exc:  # allow-silent: a bad/partial dataset must never fail the unit; it prints why and the network fetch runs
        print(f"candle dataset: {feed_id(key)} not served ({type(exc).__name__}: {str(exc)[:120]}); falling back to the network")
        return False


def reuse_check(dest: Path, coverage_out: Optional[str], max_age_days: float = 3.0) -> int:
    """0 when the PUBLISHED dataset's manifest is readable, has every needed feed `ok` with enough days, and is < max_age_days old
    (the caller then skips the rebuild and the coverage record comes from the published manifest). Non-zero = rebuild."""
    from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: PLC0415
    api = KaggleApi()
    api.authenticate()
    user = api.config_values.get("username", "")
    if not user:
        print("reuse-check: token did not resolve to a Kaggle user")
        return 2
    dest.mkdir(parents=True, exist_ok=True)
    got = None
    try:
        api.dataset_download_file(f"{user}/{DATASET_SLUG}", MANIFEST_NAME, path=str(dest), force=True, quiet=True)
    except Exception as exc:  # allow-silent: any failure means "cannot reuse"; the caller rebuilds
        print(f"reuse-check: manifest download failed ({type(exc).__name__}: {str(exc)[:120].replace(user, '<user>')})")
        return 3
    for q in (dest / MANIFEST_NAME, dest / (MANIFEST_NAME + ".zip")):
        if q.is_file() and q.suffix == ".zip":
            import zipfile  # noqa: PLC0415
            with zipfile.ZipFile(q) as z:
                z.extract(MANIFEST_NAME, dest)
        if (dest / MANIFEST_NAME).is_file():
            got = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
            break
    if not got:
        print("reuse-check: no manifest after download")
        return 4
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(got["generated_at"])).total_seconds() / 86400
    need = needed_feeds()
    missing = [feed_id(k) for k, d in need.items()
               if (got["feeds"].get(feed_id(k)) or {}).get("status") != "ok" or int(got["feeds"][feed_id(k)].get("days_built", 0)) < d]
    print(f"reuse-check: published manifest {age:.2f} d old, {got['counts']}, needed feeds {len(need)}, missing/short {len(missing)} {missing[:5]}")
    if age > max_age_days or missing:
        return 5
    if coverage_out:
        Path(coverage_out).parent.mkdir(parents=True, exist_ok=True)
        Path(coverage_out).write_text(json.dumps(coverage_record(got), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="fetch/derive every needed feed into --out and write the manifest")
    b.add_argument("--out", required=True)
    b.add_argument("--days-floor", type=int, default=0)
    b.add_argument("--no-lake", action="store_true")
    b.add_argument("--coverage-out", default=None, help="also write the small coverage record here")
    sub.add_parser("feeds", help="print the feeds the queued units need")
    r = sub.add_parser("reuse-check", help="exit 0 when the published dataset is fresh and complete (skip the rebuild)")
    r.add_argument("--dest", required=True)
    r.add_argument("--coverage-out", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "reuse-check":
        return reuse_check(Path(a.dest), a.coverage_out)
    feeds = needed_feeds()
    if a.cmd == "feeds":
        print(json.dumps({feed_id(k): v for k, v in sorted(feeds.items())}, indent=1))
        return 0
    man = build(Path(a.out), feeds, a.days_floor, use_lake=not a.no_lake)
    if a.coverage_out:
        Path(a.coverage_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.coverage_out).write_text(json.dumps(coverage_record(man), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(man["counts"]))
    return 0 if man["counts"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
