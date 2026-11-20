"""Every harness CLI and raw-loading driver must replay at the LEG's timeframe; the resolver never returns a
COARSER file than asked for.

WHY (PI-20261119-RIMARY13-0002, ML-PRIMARY-14, 2026-11-20). PR #27491 fixed four exit-head drivers that dropped
``Resolution.resample``. The audit of the remaining callers found the same defect one level up and one below:

* every harness CLI (trend, pullback, fade, squeeze, fvg_range, chop_scalp, funding_carry) resolved
  ``--symbol/--timeframe`` and aggregated ONLY on an explicit ``--resample`` -- a ``--timeframe 1h`` call on the
  trainer (ETH/SOL/XRP/... have only 5m files, BTC only 15m) replayed on sub-hourly bars while the provenance
  line printed "(resampled to 1h)";
* ict_scalp / orb CLIs and the ict_scalp panel / exit-sweep drivers load the resolved file raw;
* ``m20_fleet_exit_sweep._resolve_one`` read ``TF_MINUTES.get(tf, 60)`` over a table without 1m/3m/30m, so a 1m
  leg resolved to ``BTCUSDT_15m.csv`` with ``resample='1m'`` (an upsample) and a 30m leg could take a 1h file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CLI_WITH_RESAMPLE_FLAG = ("chop_scalp", "fade", "funding_carry", "fvg_range", "pullback", "squeeze", "trend")
RAW_LOADERS = (
    "scripts/backtest_ict_scalp.py",
    "scripts/backtest_orb.py",
    "scripts/research/m27/ict_scalp_exit_sweep.py",
    "scripts/research/build_backtest_panel.py",
)


def _touch(d: Path, *names: str) -> None:
    for n in names:
        (d / n).write_text("timestamp,open,high,low,close,volume\n")


# --- the resolver -------------------------------------------------------------------------------------------

def test_a_1m_leg_never_resolves_to_a_coarser_file(tmp_path):
    from m20_fleet_exit_sweep import resolve_data
    _touch(tmp_path, "BTCUSDT_15m.csv")
    path, _proxy, resample = resolve_data("BTCUSDT", "1m", tmp_path)
    assert path is None and resample is None, (path, resample)
    # POSITIVE CONTROL: a native 1m file still resolves, natively.
    _touch(tmp_path, "BTCUSDT_1m.csv")
    path, _proxy, resample = resolve_data("BTCUSDT", "1m", tmp_path)
    assert path.endswith("BTCUSDT_1m.csv") and resample is None


def test_a_30m_leg_does_not_take_a_1h_file_but_does_take_a_5m_one(tmp_path):
    from m20_fleet_exit_sweep import resolve_data
    _touch(tmp_path, "SOLUSDT_1h.csv")
    assert resolve_data("SOLUSDT", "30m", tmp_path)[0] is None
    _touch(tmp_path, "SOLUSDT_5m.csv")
    path, _proxy, resample = resolve_data("SOLUSDT", "30m", tmp_path)
    assert path.endswith("SOLUSDT_5m.csv") and resample == "30m"


def test_existing_resolutions_do_not_move(tmp_path):
    """The trainer's crypto layout (trainer-vm-diag #27238): every 1h/4h/15m resolution is what it was."""
    from m20_fleet_exit_sweep import resolve_data
    _touch(tmp_path, "BTCUSDT_15m.csv", "ETHUSDT_5m.csv", "ETHUSDT_15m.csv", "XRPUSDT_5m.csv",
           "backtest_BTCUSDT_5m.csv")
    got = {(s, t): (Path(p).name if p else None, r) for s, t in
           [("BTCUSDT", "1h"), ("BTCUSDT", "4h"), ("BTCUSDT", "5m"), ("BTCUSDT", "15m"), ("ETHUSDT", "1h"),
            ("ETHUSDT", "15m"), ("XRPUSDT", "15m")]
           for p, _x, r in [resolve_data(s, t, tmp_path)]}
    assert got == {
        ("BTCUSDT", "1h"): ("BTCUSDT_15m.csv", "1h"), ("BTCUSDT", "4h"): ("BTCUSDT_15m.csv", "4h"),
        ("BTCUSDT", "5m"): ("backtest_BTCUSDT_5m.csv", None), ("BTCUSDT", "15m"): ("BTCUSDT_15m.csv", None),
        ("ETHUSDT", "1h"): ("ETHUSDT_5m.csv", "1h"), ("ETHUSDT", "15m"): ("ETHUSDT_15m.csv", None),
        ("XRPUSDT", "15m"): ("XRPUSDT_5m.csv", "15m"),
    }


def test_tf_minutes_parses_tokens_outside_the_table():
    from m20_fleet_exit_sweep import _tf_minutes
    assert [_tf_minutes(t) for t in ("1m", "30m", "1h", "12h", "1d", "1w", "3d")] == [1, 30, 60, 720, 1440,
                                                                                      10080, 4320]
    assert _tf_minutes("garbage") == 60  # the historical default, kept only for an unparseable token


# --- the helpers --------------------------------------------------------------------------------------------

def test_effective_resample_explicit_wins_then_the_resolver():
    from scripts.ops import backtest_data_source as ds
    res = ds.Resolution(ds.RESOLVED, "x.csv", symbol="ETHUSDT", timeframe="1h", resample="1h")
    assert ds.effective_resample(res, None) == "1h"
    assert ds.effective_resample(res, "4h") == "4h"
    explicit = ds.Resolution(ds.EXPLICIT, "x.csv", symbol="ETHUSDT", timeframe="1h")
    assert ds.effective_resample(explicit, None) is None, "an explicit --data file is never resampled implicitly"


@pytest.mark.parametrize("tz", ["UTC", None])
def test_resample_open_stamped_matches_a_native_coarser_file(tz):
    from scripts.ops import backtest_data_source as ds
    ts = pd.date_range("2026-01-01", periods=24, freq="5min", tz=tz)
    px = pd.Series(range(24), dtype=float) + 100.0
    df = pd.DataFrame({"timestamp": ts, "open": px, "high": px + 1, "low": px - 1, "close": px + 0.5,
                       "volume": 1.0})
    out = ds.resample_open_stamped(df, "1h")
    assert len(out) == 2
    first = out.iloc[0]
    assert pd.Timestamp(first["timestamp"]) == ts[0], "open-stamped: the hour is labelled by its first 5m bar"
    assert (first["open"], first["high"], first["low"], first["close"], first["volume"]) == (100.0, 112.0, 99.0,
                                                                                             111.5, 12.0)
    assert (out["timestamp"].dt.tz is None) == (tz is None), "a loader's tz choice is kept"
    assert ds.resample_open_stamped(df, None) is df


# --- the callers --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", CLI_WITH_RESAMPLE_FLAG)
def test_every_resample_flag_cli_applies_the_resolvers_rule(name):
    src = (REPO / "scripts" / f"backtest_{name}.py").read_text()
    assert ".resample = _backtest_data_source.effective_resample(_src, " in src, name


@pytest.mark.parametrize("rel", RAW_LOADERS)
def test_every_raw_loader_aggregates_to_the_resolved_grain(rel):
    src = (REPO / rel).read_text()
    assert "_backtest_data_source.resample_open_stamped(df, " in src, rel


def test_intrabar_panel_forwards_the_resolvers_rule_to_its_adapter():
    src = (REPO / "scripts/research/build_intrabar_exit_panel.py").read_text()
    assert '"resample": _src.resample' in src


def test_backtest_trend_cli_aggregates_a_resolved_5m_file_to_the_leg_timeframe(monkeypatch):
    """Functional: the CLI, given only --symbol/--timeframe 1h and a resolver that picked a 5m file, calls its
    own _resample with '1h'. Stops at the resample (sentinel) so no data is read."""
    import scripts.backtest_trend as bt
    ds = bt._backtest_data_source

    def fake_resolve(symbol, timeframe, data_arg, **_k):
        return ds.Resolution(ds.RESOLVED, "/nonexistent/ETHUSDT_5m.csv", symbol=symbol, timeframe=timeframe,
                             resample="1h")

    seen = []

    def fake_load(path):
        return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=3, freq="5min", tz="UTC"),
                             "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})

    def fake_resample(df, rule):
        seen.append(rule)
        raise RuntimeError("sentinel: stop after the resample decision")

    monkeypatch.setattr(ds, "resolve_or_refuse", fake_resolve)
    monkeypatch.setattr(bt, "_load_candles", fake_load)
    monkeypatch.setattr(bt, "_resample", fake_resample)
    rc = bt.main(["backtest_trend.py", "--symbol", "ETHUSDT", "--timeframe", "1h"])  # main parses argv[1:]
    assert seen == ["1h"], seen
    assert rc != 0  # the sentinel surfaces as a load failure, never as a result
