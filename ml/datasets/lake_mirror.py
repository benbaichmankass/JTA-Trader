"""Read path for the FROZEN months of the market lake from the private Kaggle mirror (row HF-LAKE-KAGGLE-LOADER).

WHY  HF private storage is at its cap, so the frozen crypto history (closed months, never rewritten) was copied to 11 private Kaggle
datasets ``metis-market-lake-p000..p010`` (row HF-LAKE-STORAGE-403). ``ml.datasets.lake`` resolves a frozen partition here first and
falls back to HF for anything the mirror does not hold (the hot tail: the open and previous month, plus any month that closed after
the copy).

MIRROR LAYOUT (written by scripts/data_lake/kaggle_pilot.py ``copy-part``; it is NOT the lake layout)::

    <dataset>/MANIFEST.json                     {"files": [{"path": "<shard>.tar", "sha256", "bytes", "members": [
                                                  {"path": "crypto/um_perp/1m/BTCUSDT/2022-01.parquet", "bytes", "sha256"}]}]}
    <dataset>/<shard>/<member path>             Kaggle auto-unpacks ``<shard>.tar`` into a folder named after it (observed
                                                2026-11-05). A mount that kept the tar is read by extracting the one member.

On Kaggle the datasets mount at ``/kaggle/input/datasets/<user>/<slug>/`` (or ``/kaggle/input/<slug>/``). ``LAKE_MIRROR_DIR`` points
at a dataset folder or at a folder holding several, for a runner copy or a test fixture.

INTEGRITY  every member is re-hashed against its per-member SHA-256 the first time it is read in a process. A member that is missing
or fails the hash is NOT returned: the caller gets an explicit ``could_not_look`` entry, never an empty frame that reads as "no data".

DERIVED TIMEFRAMES  the mirror holds the 1m base only (the plan excludes derived tfs: ``resample.py`` reconstructs them). When the HF
MANIFEST is unreadable the loader synthesizes manifest entries from the mirror, and lists 5m/15m/1h/4h/1d for every 1m series, derived
on read with the lake's own deterministic rule.

Nothing here reads a credential. Market data only.
"""
from __future__ import annotations

import calendar
import glob
import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import pandas as pd

DATASET_GLOBS = ("/kaggle/input/datasets/*/metis-market-lake-p[0-9][0-9][0-9]",
                 "/kaggle/input/metis-market-lake-p[0-9][0-9][0-9]")
DERIVED_TFS = ("5m", "15m", "1h", "4h", "1d")
_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
# per-day upper bound on rows, used ONLY to give synthesized entries a non-zero ``rows`` (ESTIMATED, never MEASURED)
_ROWS_PER_DAY = {"funding": 24, "metrics_5m": 288}


class Member(NamedTuple):
    path: str          # lake path, e.g. crypto/um_perp/1m/BTCUSDT/2022-01.parquet
    dataset: str       # dataset directory
    shard: str         # shard folder / tar stem
    sha256: str
    nbytes: int


class MirrorError(Exception):
    """A mirror member could not be read or failed its checksum."""


def is_frozen_name(rel: str, now=None) -> bool:
    """Same rule the copy used (scripts/data_lake/kaggle_pilot.py): a closed YYYY-MM at least 2 full months old, or a closed year."""
    now = now or pd.Timestamp.now(tz="UTC")
    stem = Path(rel).stem
    if len(stem) == 4 and stem.isdigit():
        return int(stem) < now.year
    if len(stem) == 7 and stem[4] == "-":
        idx = int(stem[:4]) * 12 + int(stem[5:]) - 1
        return idx <= (now.year * 12 + now.month - 1) - 2
    return False


def dataset_dirs() -> List[Path]:
    """Mounted mirror datasets (those holding a MANIFEST.json), sorted by name. Empty when no mirror is mounted."""
    env = os.environ.get("LAKE_MIRROR_DIR")
    cands: List[str] = []
    if env:
        cands = [env] if (Path(env) / "MANIFEST.json").is_file() else sorted(glob.glob(os.path.join(env, "metis-market-lake-p*"))
                                                                              + glob.glob(os.path.join(env, "*", "metis-market-lake-p*")))
    else:
        for g in DATASET_GLOBS:
            cands += sorted(glob.glob(g))
    return [Path(c) for c in cands if (Path(c) / "MANIFEST.json").is_file()]


_INDEX_CACHE: Dict[Tuple[str, ...], Tuple[Dict[str, Member], List[Dict], List[Dict]]] = {}


def index() -> Tuple[Dict[str, Member], List[Dict], List[Dict]]:
    """(members by lake path, dataset infos, problems). A dataset whose MANIFEST.json cannot be parsed is a problem entry, not a silent skip."""
    dirs = dataset_dirs()
    key = tuple(str(d) for d in dirs)
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    members: Dict[str, Member] = {}
    infos: List[Dict] = []
    problems: List[Dict] = []
    for d in dirs:
        try:
            man = json.loads((d / "MANIFEST.json").read_text())
        except Exception as e:  # noqa: BLE001  -- recorded, not hidden
            problems.append({"dataset": d.name, "why": f"MANIFEST.json unreadable: {str(e)[:120]}"})
            continue
        n = 0
        for f in man.get("files", []):
            shard = Path(f["path"]).stem
            for m in f.get("members", []):
                members[m["path"]] = Member(m["path"], str(d), shard, m.get("sha256", ""), int(m.get("bytes") or 0))
                n += 1
        infos.append({"dataset": d.name, "part": man.get("part"), "plan_id": man.get("plan_id"), "members": n,
                      "expected_partitions": man.get("expected_partitions"), "n_partitions": man.get("n_partitions")})
    _INDEX_CACHE[key] = (members, infos, problems)
    return _INDEX_CACHE[key]


def available() -> bool:
    return bool(index()[0])


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_VERIFIED: Dict[str, str] = {}
_CACHE_DIR: Optional[Path] = None


def _cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        _CACHE_DIR = Path(os.environ.get("LAKE_MIRROR_CACHE") or tempfile.mkdtemp(prefix="lake-mirror-"))
    return _CACHE_DIR


def fetch(lake_path: str, verify: Optional[bool] = None) -> Path:
    """Local path of a frozen member, hash-verified once per process. Raises MirrorError when it is absent or fails the hash."""
    members = index()[0]
    m = members.get(lake_path)
    if m is None:
        raise MirrorError(f"{lake_path}: not in the mirror")
    if verify is None:
        verify = os.environ.get("LAKE_MIRROR_VERIFY", "1") != "0"
    if lake_path in _VERIFIED:
        return Path(_VERIFIED[lake_path])
    base = Path(m.dataset)
    p = base / m.shard / lake_path
    if not p.is_file():
        tar = base / f"{m.shard}.tar"
        if not tar.is_file():
            raise MirrorError(f"{lake_path}: shard {m.shard} not mounted in {base.name}")
        out = _cache_dir() / "x" / m.shard
        out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar) as tf:
            member = tf.getmember(lake_path)
            if hasattr(tarfile, "data_filter"):
                tf.extract(member, out, filter="data")
            else:
                tf.extract(member, out)
        p = out / lake_path
    if verify and m.sha256:
        if p.stat().st_size != m.nbytes or _sha256(p) != m.sha256:
            raise MirrorError(f"{lake_path}: size/SHA-256 mismatch against {base.name}/MANIFEST.json")
    _VERIFIED[lake_path] = str(p)
    return p


def _month_bounds(stem: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    y, mo = int(stem[:4]), int(stem[5:7])
    first = pd.Timestamp(year=y, month=mo, day=1, tz="UTC")
    return first, first + pd.Timedelta(days=calendar.monthrange(y, mo)[1]) - pd.Timedelta(minutes=1)


def synth_entries() -> List[Dict]:
    """Manifest entries rebuilt from the mirror alone (used when the HF MANIFEST cannot be read). ``rows`` is an ESTIMATED upper bound
    (days x bars/day), flagged ``rows_provenance``; first/last are the month bounds, not the first/last bar."""
    groups: Dict[Tuple[str, str, str], Dict[str, Dict]] = {}
    for path in index()[0]:
        parts = path.split("/")
        if len(parts) != 5 or not parts[4].endswith(".parquet") or len(parts[4]) != len("YYYY-MM.parquet"):
            continue
        asset, market, label, sym, fn = parts
        stem = fn[:-len(".parquet")]
        first, last = _month_bounds(stem)
        days = (last - first).days + 1
        rows = days * _ROWS_PER_DAY.get(label, 1440)
        groups.setdefault((asset, market, label, sym), {})[stem] = {"path": path, "rows": rows, "first": first.isoformat(),
                                                                    "last": last.isoformat(), "src": "kaggle_mirror"}
    out: List[Dict] = []
    for (asset, market, label, sym), parts_ in sorted(groups.items()):
        ks = sorted(parts_)
        base = {"asset_class": asset, "market": market, "symbol": sym, "partitions": parts_, "n_partitions": len(ks),
                "first": parts_[ks[0]]["first"], "last": parts_[ks[-1]]["last"], "source": "kaggle_mirror",
                "synthetic": True, "rows_provenance": "ESTIMATED"}
        out.append({**base, "tf": label, "rows": sum(p["rows"] for p in parts_.values())})
        if label == "1m":
            for tf in DERIVED_TFS:
                k = _TF_MINUTES[tf]
                out.append({**base, "tf": tf, "derive_in_loader": True, "derived_from": "1m",
                            "rows": sum(p["rows"] // k for p in parts_.values())})
    return out


def last_month() -> Optional[str]:
    """Newest ``YYYY-MM`` partition held anywhere in the mirror (how far the copy reached)."""
    months = [Path(p).stem for p in index()[0] if len(Path(p).stem) == 7]
    return max(months) if months else None


def describe() -> Dict:
    members, infos, problems = index()
    return {"datasets": len(infos), "members": len(members), "problems": problems, "plan_ids": sorted({i["plan_id"] for i in infos if i.get("plan_id")}),
            "mounted": [i["dataset"] for i in infos], "last_month": last_month()}
