"""PI-20261029-XME2GXW7-0003: Binance SPOT candles as a labelled perp PROXY for the overlay holdout (RQ-20261029-5785-05)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _fbc():
    return _load("fbc_spot_t", "scripts/ops/fetch_backtest_candles.py")


def test_vision_market_selects_archive(monkeypatch):
    fbc = _fbc()
    urls: list[str] = []
    monkeypatch.setattr(fbc, "_download_vision_zip", lambda url: urls.append(url) or [])
    fbc.fetch_klines_binance_vision("ETHUSDT", "240", 1514764800000, 1517443200000, market="spot")
    assert urls and all(u.startswith("https://data.binance.vision/data/spot/") for u in urls)
    urls.clear()
    fbc.fetch_klines_binance_vision("ETHUSDT", "240", 1514764800000, 1517443200000)
    assert urls and all(u.startswith("https://data.binance.vision/data/futures/um/") for u in urls)


def test_unknown_market_refused():
    with pytest.raises(ValueError):
        _fbc().fetch_klines_binance_vision("ETHUSDT", "240", 0, 1, market="coinm")


def test_spot_never_rides_the_auto_chain():
    with pytest.raises(SystemExit):
        _fbc().main(["x", "--symbol", "ETHUSDT", "--vision-market", "spot", "--source", "auto"])


def test_build_corpus_spot_feeds_the_proxy_csv(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "scripts" / "research"))
    m = _load("mlo_spot_t", "scripts/research/ml_overlay_noninferior.py")
    import path_metric_giveback as pmg
    seen = {}

    def fake_fetch(leg, base, *, start, end, csv):
        seen["fetch"] = (leg, start, end, str(csv))
        return {"source": "binance_spot_proxy", "ticker": "ETHUSDT"}

    def fake_run(leg, base, *, days, start, end, wd, data_csv, non_crypto_source):
        seen["data_csv"] = data_csv
        return [], {"feed": {"source": "explicit --data-csv"}, "argv": [], "bt": {}}

    monkeypatch.setattr(m, "fetch_spot_proxy_csv", fake_fetch)
    monkeypatch.setattr(pmg, "run_leg_paths", fake_run)
    _o, runs = m.build_corpus(["trend_donchian_eth_4h"], start="2017-09-01", end="2019-11-30", days=3500,
                              wd=tmp_path, market="spot")
    assert seen["data_csv"] == str(tmp_path / "trend_donchian_eth_4h__data.csv") == seen["fetch"][3]
    assert runs["trend_donchian_eth_4h"]["feed"]["source"] == "binance_spot_proxy"
