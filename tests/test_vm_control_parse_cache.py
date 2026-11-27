"""VM-CONTROL-1127: the instruments loader and the runtime-status strategy-name read go through the shared parse memo.

py-spy on the live VM (2026-11-27) caught the trader and web-api inside ``yaml.safe_load`` in both places; the shared
memo (src/utils/yaml_parse_cache, tested in tests/test_yaml_parse_cache.py) owns copy-per-caller and edit detection.
"""
from __future__ import annotations

from pathlib import Path

from src.core import profile_loader as pl
from src.utils import yaml_parse_cache as ypc
from src.web import runtime_status as rs

INSTR = "instruments:\n  BTCUSDT: {exchange: bybit, category: linear, tick_size: 0.1}\n"


def test_instrument_profiles_parse_once_and_see_an_edit(tmp_path):
    ypc.clear()
    f = tmp_path / "instruments.yaml"
    f.write_text(INSTR)
    a = pl.load_instrument_profiles(str(f))
    b = pl.load_instrument_profiles(str(f))
    assert a == b and a is not b
    assert ypc.stats()["misses"] == 1 and ypc.stats()["hits"] >= 1
    f.write_text(INSTR + "  ETHUSDT: {exchange: bybit, category: linear}\n")
    assert "ETHUSDT" in pl.load_instrument_profiles(str(f))  # file re-read every call: an edit is seen at once


def test_missing_instruments_file_still_falls_back(tmp_path):
    assert "BTCUSDT" in pl.load_instrument_profiles(str(tmp_path / "absent.yaml"))


def test_strategy_names_parse_once_and_see_an_edit(tmp_path):
    ypc.clear()
    f = Path(tmp_path / "strategies.yaml")
    f.write_text("strategies:\n  a: {enabled: true}\n  b: {enabled: false}\n")
    assert rs._read_strategy_names(f) == ["a"] and rs._read_strategy_names(f) == ["a"]
    assert ypc.stats()["misses"] == 1
    f.write_text("strategies:\n  a: {enabled: true}\n  b: {enabled: true}\n")
    assert rs._read_strategy_names(f) == ["a", "b"]
