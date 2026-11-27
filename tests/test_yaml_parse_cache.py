"""VM-CONTROL-1127: instruments.yaml and strategies.yaml are parsed once per file version, not on every call."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

import src.core.profile_loader as pl
from src.web import runtime_status as rs

INSTR = """instruments:
  BTCUSDT: {exchange: bybit, category: linear, tick_size: 0.1}
"""


def _count_safe_load(monkeypatch):
    n = {"c": 0}
    real = yaml.safe_load

    def counting(*a, **k):
        n["c"] += 1
        return real(*a, **k)

    monkeypatch.setattr(yaml, "safe_load", counting)
    return n


def test_instrument_profiles_parse_once_per_file_version(tmp_path, monkeypatch):
    pl._PROFILES_CACHE.clear()
    f = tmp_path / "instruments.yaml"
    f.write_text(INSTR)
    n = _count_safe_load(monkeypatch)
    a = pl.load_instrument_profiles(str(f))
    b = pl.load_instrument_profiles(str(f))
    assert n["c"] == 1 and a == b and a is not b  # each caller gets its own dict
    a.pop("BTCUSDT")
    assert "BTCUSDT" in pl.load_instrument_profiles(str(f))  # a caller's mutation never poisons the cache
    f.write_text(INSTR + "  ETHUSDT: {exchange: bybit, category: linear}\n")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert "ETHUSDT" in pl.load_instrument_profiles(str(f)) and n["c"] == 2  # an edit is read on the next call


def test_missing_instruments_file_still_falls_back(tmp_path):
    pl._PROFILES_CACHE.clear()
    assert "BTCUSDT" in pl.load_instrument_profiles(str(tmp_path / "absent.yaml"))


def test_strategy_names_parse_once_per_file_version(tmp_path, monkeypatch):
    rs._STRATEGY_NAMES_CACHE.clear()
    f = Path(tmp_path / "strategies.yaml")
    f.write_text("strategies:\n  a: {enabled: true}\n  b: {enabled: false}\n")
    n = _count_safe_load(monkeypatch)
    assert rs._read_strategy_names(f) == ["a"] and rs._read_strategy_names(f) == ["a"] and n["c"] == 1
    f.write_text("strategies:\n  a: {enabled: true}\n  b: {enabled: true}\n")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert rs._read_strategy_names(f) == ["a", "b"] and n["c"] == 2
