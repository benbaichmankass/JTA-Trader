"""Loader reads FROZEN months from the private Kaggle mirror and the hot tail from HF (row HF-LAKE-KAGGLE-LOADER).

Planted/clean pairs: a clean mirror loads and verifies; the same mirror with one member corrupted, one missing, or the hot tail
unreachable yields an explicit could_not_look, never an empty frame that reads as "no data"."""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pandas as pd
import pytest

from ml.datasets import lake, lake_mirror


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _member(root: Path, rel: str, month: str, start_val: float = 1.0) -> dict:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = pd.date_range(f"{month}-01", periods=2 * 24 * 60, freq="1min", tz="UTC")  # two days of 1m bars
    pd.DataFrame({"ts": ts, "open": start_val, "high": start_val + 1, "low": start_val - 0.5, "close": start_val + 0.5,
                  "volume": 1.0}).to_parquet(p)
    return {"path": rel, "bytes": p.stat().st_size, "sha256": _sha(p)}


def _mirror(tmp_path: Path, tar: bool = False) -> Path:
    ds = tmp_path / "metis-market-lake-p001"
    shard = ds / "p001-b000-000"
    members = [_member(shard, f"crypto/um_perp/1m/AAAUSDT/{m}.parquet", m) for m in ("2025-01", "2025-02")]
    members.append(_member(shard, "crypto/um_perp/1m/BBBUSDT/2025-01.parquet", "2025-01", 5.0))
    if tar:
        with tarfile.open(ds / "p001-b000-000.tar", "w") as tf:
            for m in members:
                tf.add(shard / m["path"], arcname=m["path"])
        import shutil
        shutil.rmtree(shard)
    (ds / "MANIFEST.json").write_text(json.dumps({"part": "p001", "plan_id": "plan1", "files": [
        {"path": "p001-b000-000.tar", "members": members, "n_partitions": len(members)}]}))
    return ds


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("LAKE_LOCAL_DIR", raising=False)
    monkeypatch.delenv("LAKE_MIRROR_DIR", raising=False)
    lake._MANIFEST_CACHE.clear()
    lake._MANIFEST_STATE.clear()
    lake_mirror._INDEX_CACHE.clear()
    lake_mirror._VERIFIED.clear()
    yield


def _hf_down(monkeypatch):
    def boom(path, revision=None):
        raise OSError("403 Private repository storage limit reached")
    monkeypatch.setattr(lake, "_fetch", boom)


def test_clean_mirror_lists_and_loads_with_hf_down(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_MIRROR_DIR", str(_mirror(tmp_path)))
    _hf_down(monkeypatch)
    syms = lake.symbols("crypto", "um_perp", "1h")
    assert list(syms) == ["AAAUSDT", "BBBUSDT"]
    assert syms.read_state == "partial" and syms.read_detail["hot_tail"] == "could_not_look"   # honest: tail not listed
    df = lake.load("crypto", "um_perp", "1h", ["AAAUSDT"], start="2025-01-01", end="2025-01-02")
    assert len(df) == 24 and df["complete"].all() and df.attrs["lake_read"]["state"] == "ok"
    assert df.attrs["lake_read"]["from_kaggle_mirror"] == 1
    m1 = lake.load("crypto", "um_perp", "1m", ["BBBUSDT"], end="2025-03-01")
    assert len(m1) == 2 * 24 * 60 and (m1["open"] == 5.0).all()


def test_planted_window_into_the_hot_tail_is_not_a_silent_short_frame(tmp_path, monkeypatch):
    """HF manifest unreadable + a window that reaches past the last mirrored month: the months after it are UNKNOWN. Without the flag this
    returned the mirrored rows with state ok (fewer rows, no signal) -- found by the local kernel rehearsal."""
    monkeypatch.setenv("LAKE_MIRROR_DIR", str(_mirror(tmp_path)))
    _hf_down(monkeypatch)
    with pytest.raises(lake.LakeReadError, match="not listed"):
        lake.load("crypto", "um_perp", "1h", ["AAAUSDT"], start="2025-01-01")            # open-ended: reaches the tail
    df = lake.load("crypto", "um_perp", "1h", ["AAAUSDT"], start="2025-01-01", on_unreadable="state")
    assert len(df) and df.attrs["lake_read"]["state"] == "partial" and df.attrs["lake_read"]["n_could_not_look"] == 1
    clean = lake.load("crypto", "um_perp", "1h", ["AAAUSDT"], start="2025-01-01", end="2025-03-01")   # twin: ends at the last mirrored month
    assert clean.attrs["lake_read"]["state"] == "ok"


def test_tar_layout_is_read_by_extracting_the_member(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_MIRROR_DIR", str(_mirror(tmp_path, tar=True)))
    monkeypatch.setenv("LAKE_MIRROR_CACHE", str(tmp_path / "cache"))
    _hf_down(monkeypatch)
    assert len(lake.load("crypto", "um_perp", "1m", ["AAAUSDT"], start="2025-02-01", end="2025-03-01")) == 2 * 24 * 60


def test_planted_corrupt_member_is_could_not_look_not_empty(tmp_path, monkeypatch):
    ds = _mirror(tmp_path)
    (ds / "p001-b000-000" / "crypto/um_perp/1m/AAAUSDT/2025-02.parquet").write_bytes(b"planted")
    monkeypatch.setenv("LAKE_MIRROR_DIR", str(ds))
    _hf_down(monkeypatch)
    with pytest.raises(lake.LakeReadError) as ei:
        lake.load("crypto", "um_perp", "1m", ["AAAUSDT"], end="2025-03-01")
    assert ei.value.state["n_could_not_look"] == 1 and "mismatch" in ei.value.state["could_not_look"][0]["why"]
    part = lake.load("crypto", "um_perp", "1m", ["AAAUSDT"], end="2025-03-01", on_unreadable="state")
    assert len(part) == 2 * 24 * 60                       # January still read, and flagged partial
    assert part.attrs["lake_read"]["state"] == "partial"
    # the clean twin of the same call has no unreadable entries
    ok = lake.load("crypto", "um_perp", "1m", ["BBBUSDT"], end="2025-03-01")
    assert ok.attrs["lake_read"]["n_could_not_look"] == 0


def test_planted_missing_member_and_nothing_readable(tmp_path, monkeypatch):
    ds = _mirror(tmp_path)
    for f in (ds / "p001-b000-000" / "crypto/um_perp/1m/BBBUSDT").iterdir():
        f.unlink()
    monkeypatch.setenv("LAKE_MIRROR_DIR", str(ds))
    _hf_down(monkeypatch)
    with pytest.raises(lake.LakeReadError) as ei:
        lake.load("crypto", "um_perp", "1m", ["BBBUSDT"], end="2025-03-01")
    assert ei.value.state["state"] == "could_not_look"
    df = lake.load("crypto", "um_perp", "1m", ["BBBUSDT"], end="2025-03-01", on_unreadable="state")
    assert df.empty and df.attrs["lake_read"]["state"] == "could_not_look"   # empty AND flagged, distinguishable from no data


def test_hot_tail_comes_from_hf_and_frozen_from_mirror(tmp_path, monkeypatch):
    ds = _mirror(tmp_path)
    monkeypatch.setenv("LAKE_MIRROR_DIR", str(ds))
    now = pd.Timestamp.now(tz="UTC")
    hot = now.strftime("%Y-%m")
    hf = tmp_path / "hf"
    hot_rel = f"crypto/um_perp/1m/AAAUSDT/{hot}.parquet"
    _member(hf, hot_rel, hot, 9.0)
    frozen_rel = "crypto/um_perp/1m/AAAUSDT/2025-01.parquet"
    full = {"files": [{"asset_class": "crypto", "market": "um_perp", "tf": "1m", "symbol": "AAAUSDT", "rows": 99, "first": "2025-01-01",
                       "last": hot + "-02", "partitions": {
                           "2025-01": {"path": frozen_rel, "rows": 2880, "first": "2025-01-01", "last": "2025-01-02"},
                           hot: {"path": hot_rel, "rows": 2880, "first": hot + "-01", "last": hot + "-02"}}}]}
    fetched = []

    def fake_fetch(path, revision=None):
        fetched.append(path)
        if path == "MANIFEST.json":
            f = tmp_path / "M.json"
            f.write_text(json.dumps(full))
            return f
        return hf / path
    monkeypatch.setattr(lake, "_fetch", fake_fetch)
    df = lake.load("crypto", "um_perp", "1m", ["AAAUSDT"])
    assert lake.read_state()["source"] == "hf"
    assert set(df["open"]) == {1.0, 9.0}
    assert frozen_rel not in fetched and hot_rel in fetched          # the frozen month never touched HF
    assert df.attrs["lake_read"]["from_kaggle_mirror"] == 1 and df.attrs["lake_read"]["from_hf_or_local"] == 1


def test_no_mirror_and_hf_down_still_raises_as_before(monkeypatch):
    _hf_down(monkeypatch)
    with pytest.raises(OSError):
        lake.symbols("crypto", "um_perp", "1h")


def test_is_frozen_name_matches_the_copy_rule():
    now = pd.Timestamp("2026-11-12", tz="UTC")
    assert lake_mirror.is_frozen_name("a/2026-09.parquet", now) and not lake_mirror.is_frozen_name("a/2026-10.parquet", now)
    assert lake_mirror.is_frozen_name("a/2025.parquet", now) and not lake_mirror.is_frozen_name("a/2026.parquet", now)
