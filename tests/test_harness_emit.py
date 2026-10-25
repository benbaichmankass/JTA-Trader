"""EXIT-PATH-EMIT-OFFLINE + METALABEL-EMIT-FEATURES: the opt-in harness emits.

Three properties per harness (scripts/backtest_trend.py, scripts/backtest_pullback.py):

1. **Flag-off is byte-identical.** Without --emit-paths / --emit-features the
   --emit-trades file carries no new key, and turning the flags ON changes
   neither the summary nor any existing key of any trade row.
2. **Path parity** (the row's DONE-WHEN check): per trade, max(peak_r over its
   path rows) == the trade row's mfe_r, max(mae_r) == the trade row's mae_r,
   the last row is the exit bar with the trade's exit_reason, and the rows are
   contiguous from the bar after entry. Checked across exit-lever arms, so a
   ``break`` the recorder fails to see shows up as a missing final row.
3. **Decision features** are present on every row and non-null once warm.
"""
import importlib.util
import json
import os
import sys
from collections import defaultdict

import pytest

pd = pytest.importorskip("pandas")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bt_trend = _load("_bt_trend_emit", "scripts/backtest_trend.py")
bt_pull = _load("_bt_pull_emit", "scripts/backtest_pullback.py")

NEW_KEYS = {"mae_r", "features_schema", "f_adx_14", "f_regime", "f_atr_pct",
            "f_atr_pctl", "f_atr_pctl_bucket", "f_regime_cell", "f_rlr_vol_20",
            "f_ret_20", "f_hour_utc", "f_dow_utc"}


def _candles(rule):
    df = pd.read_csv(os.path.join(_REPO, "data/backtest_candles.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return (df.set_index("timestamp").resample(rule, label="right", closed="right")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna().reset_index())


TREND = dict(donchian=20, atr_period=14, atr_stop_mult=2.5, trail_mult=3.0,
             timeout_bars=200, cooldown_bars=1, timeframe="5min", symbol="BTCUSDT")
PULL = dict(trend_lookback=40, pullback_lookback=5, pullback_frac=0.5,
            atr_period=14, atr_stop_mult=2.0, trail_mult=3.0, timeout_bars=100,
            cooldown_bars=1, timeframe="5min", symbol="BTCUSDT")

HARNESSES = [
    pytest.param(bt_trend, TREND, id="trend"),
    pytest.param(bt_pull, PULL, id="pullback"),
]
ARMS = [
    pytest.param({}, id="default"),
    pytest.param(dict(tp_cap_pct=0.01), id="capped_tp"),
    pytest.param(dict(giveback_min_mfe_r=1.0), id="giveback"),
    pytest.param(dict(stale_exit_bars=10), id="stale"),
]


@pytest.fixture(scope="module")
def frame():
    return _candles("5min")


def _rows(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _run(mod, base, df, tmp_path, tag, **kw):
    trades = str(tmp_path / f"{tag}_trades.jsonl")
    summary = mod.run_backtest(df.copy(), emit_path=trades, **base, **kw)
    return summary, trades


@pytest.mark.parametrize("mod,base", HARNESSES)
def test_flag_off_is_byte_identical(mod, base, frame, tmp_path):
    off_sum, off_path = _run(mod, base, frame, tmp_path, "off")
    on_sum, on_path = _run(mod, base, frame, tmp_path, "on",
                           emit_paths_path=str(tmp_path / "paths.jsonl"),
                           emit_features=True)
    assert json.dumps(off_sum, default=str) == json.dumps(on_sum, default=str)
    off_rows, on_rows = _rows(off_path), _rows(on_path)
    assert off_rows, "positive control: the fixture must produce trades"
    assert len(off_rows) == len(on_rows)
    for a, b in zip(off_rows, on_rows):
        assert not (set(a) & NEW_KEYS), "a flag-off row grew a new key"
        assert set(b) - set(a) == NEW_KEYS
        # Existing keys: same values AND same order, so a flag-off reader's
        # serialisation of the old keys is unchanged.
        assert json.dumps({k: b[k] for k in a}) == json.dumps(a)
    # A second flag-off run is the same bytes (the recorder leaves no state).
    _, off2 = _run(mod, base, frame, tmp_path, "off2")
    with open(off_path, "rb") as f1, open(off2, "rb") as f2:
        assert f1.read() == f2.read()


@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize("mod,base", HARNESSES)
def test_path_parity(mod, base, arm, frame, tmp_path):
    paths = str(tmp_path / "paths.jsonl")
    _, trades_path = _run(mod, base, frame, tmp_path, "p", emit_paths_path=paths, **arm)
    trades = _rows(trades_path)
    assert trades, "positive control: the fixture must produce trades"
    by_key = defaultdict(list)
    for r in _rows(paths):
        by_key[r["trade_key"]].append(r)
    for t in trades:
        key = f'{t["strategy"]}|{t["symbol"]}|{t["entry_time"]}|{t["direction"]}'
        rows = by_key.pop(key)
        assert [r["bar_offset"] for r in rows] == list(range(1, len(rows) + 1))
        assert round(max(r["peak_r"] for r in rows), 3) == t["mfe_r"]
        assert round(max(r["mae_r"] for r in rows), 3) == t["mae_r"]
        assert rows[-1]["is_exit"] and rows[-1]["exit_reason"] == t["exit_reason"]
        assert not any(r["is_exit"] for r in rows[:-1])
        # The exit row's open_r is the realised raw R (before bank/weighting,
        # neither armed here) -- the path ends where the trade ends.
        assert rows[-1]["open_r"] == pytest.approx(t["gross_r"], abs=1e-3)
        # Every row's stop is the level it was tested against; a stop exit
        # fills at it, so the exit row's open_r sits on the stop.
        if t["exit_reason"] in ("stop", "trail_stop"):
            assert rows[-1]["open_r"] == pytest.approx(rows[-1]["stop_r"], abs=1e-3)
        for r in rows:
            assert r["peak_r"] >= 0.0 and r["mae_r"] >= 0.0
            assert r["dist_to_stop_r"] == pytest.approx(r["c_r"] - r["stop_r"], abs=2e-4)
    assert not by_key, "path rows for a trade that has no trade row"


@pytest.mark.parametrize("mod,base", HARNESSES)
def test_decision_features_present(mod, base, frame, tmp_path):
    _, trades_path = _run(mod, base, frame, tmp_path, "f", emit_features=True)
    rows = _rows(trades_path)
    assert rows
    for r in rows:
        assert r["features_schema"] == "harness_decision_v1"
        assert 0 <= r["f_hour_utc"] <= 23 and 0 <= r["f_dow_utc"] <= 6
        assert r["f_regime"] in ("chop", "transitional", "trending", "unknown")
    warm = [r for r in rows if r["f_atr_pctl"] is not None]
    # The ATR percentile is null EXACTLY until its 200-bar window fills (an
    # honest could-not-look, never a 0). On an evidence run the window is a
    # few hundred bars of a multi-year history; on this short fixture it is
    # a visible share, so pin the boundary rather than a ratio.
    cutoff = str(frame["timestamp"].iloc[199])
    assert warm, "positive control: some trades must enter after warm-up"
    for r in rows:
        assert (r["f_atr_pctl"] is not None) == (r["entry_time"] >= cutoff)
    for r in warm:
        assert r["f_atr_pctl_bucket"] in ("low", "mid", "high")
        assert r["f_regime_cell"] == f'{r["f_regime"]}|{r["f_atr_pctl_bucket"]}' \
            or r["f_regime"] == "unknown"
        assert r["f_adx_14"] is not None and r["f_rlr_vol_20"] is not None


def test_cli_flags_wired():
    """The flags reach run_backtest from the CLI (not only the Python API)."""
    import inspect
    for mod in (bt_trend, bt_pull):
        src = inspect.getsource(mod.main)
        assert "emit_paths_path=args.emit_paths" in src
        assert "emit_features=args.emit_features" in src


def test_evidence_builder_opt_in_argv():
    """research_emits appends the flags for trend/pullback only; off = same argv."""
    sys.path.insert(0, os.path.join(_REPO, "scripts", "research"))
    rdm = _load("_rdm_emit", "scripts/research/regime_debt_matrix.py")
    cfgs = {
        "trend": {"symbols": ["BTCUSDT"], "timeframe": "4h", "donchian": 20},
        "pullback": {"symbols": ["ETHUSDT"], "timeframe": "2h", "trend_lookback": 40,
                     "pullback_lookback": 5, "pullback_frac": 0.5},
    }
    for harness, cfg in cfgs.items():
        assert rdm.classify(cfg) == harness
        args = ("x", cfg, harness, "d.csv", "4h", "w/x__trades.jsonl", "w/x__bt.json")
        off, f_off, o_off = rdm.build_harness_cmd(*args)
        on, f_on, o_on = rdm.build_harness_cmd(*args, research_emits=True)
        assert (f_off, o_off) == (f_on, o_on)
        assert on[:len(off)] == off
        assert on[len(off):] == ["--emit-features", "--emit-paths", "w/x__paths.jsonl"]
