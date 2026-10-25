"""BRACKET-ADVISOR-SHADOW — the observe-only bracket advisor (phase 0).

Pinned:

1. **Harness equality.** On a seeded 4h series, ``scripts/backtest_trend.py`` run
   WITH the registry's candidate lever produces, per managed bar, the stop it
   tests that bar against. The advisor, fed the live monitor's frame for that bar
   and a package that does NOT declare the lever, must log the same stop in R.
   The negative control: the harness WITHOUT the lever differs on some bars, so
   a match is not vacuous.
2. **Containment.** An exception inside the advisor leaves the monitor verdict,
   the bracket and the history row intact.
3. **Not read by the exit path.** No ``src/`` module outside the history writer
   imports the advisor or names its fields — with the probe shown to find the
   files that legitimately do.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts" / "research"))

import momentum_levers_parity as parity  # noqa: E402

from src.runtime import bracket_advisor as ba  # noqa: E402
from src.runtime import position_path_history as pph  # noqa: E402
from src.runtime import position_telemetry as pt  # noqa: E402
from src.units.db.database import Database  # noqa: E402
from src.units.strategies import trend_donchian as td  # noqa: E402

LEG = "trend_donchian_xrp_4h"
_REAL_RPT = pt.record_position_telemetry


@pytest.fixture(autouse=True)
def _clear_cache():
    ba._cache.clear()
    yield
    ba._cache.clear()


@pytest.fixture(scope="module")
def series() -> pd.DataFrame:
    # The momentum-parity guard's generator (tests/test_momentum_levers_parity.py):
    # breakouts, trends and chop with ADX on both sides of 25, short-weighted.
    rng = np.random.default_rng(20261024)
    n = 4000
    drift = np.repeat(rng.choice([-0.006, -0.003, 0.0, 0.003], size=n // 60 + 1), 60)[:n]
    shock = rng.choice([0.0, -0.05, 0.04], size=n, p=[0.96, 0.025, 0.015])
    close = 1.0 * np.exp(np.cumsum(drift + shock + rng.normal(0.0, 0.012, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    span = np.abs(rng.normal(0.0, 0.008, n)) * close
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
        "open": open_, "high": np.maximum(open_, close) + span,
        "low": np.minimum(open_, close) - span, "close": close, "volume": 1.0})


def _spec() -> dict:
    specs = ba.load_specs()
    assert specs is not None, "the registry must be readable"
    mine = [s for s in specs.get(LEG, []) if s["lever"] == "momentum_trail"]
    assert len(mine) == 1, f"{LEG} must carry exactly one momentum_trail advisor spec"
    return mine[0]


def test_registry_specs_are_supported_and_evidenced():
    specs = ba.load_specs()
    assert specs, "no advisor spec in the registry: the advisor would advise nothing"
    for leg, rows in specs.items():
        for s in rows:
            assert s["lever"] in ba.SUPPORTED_LEVERS, (leg, s)
            assert s.get("version") and s.get("params"), (leg, s)
            assert (_REPO / s["evidence"]).is_file(), (leg, s["evidence"])


def test_advisor_equals_the_harness_with_the_lever_on(series, tmp_path):
    spec = _spec()
    cfg = parity.load_leg(LEG, {})
    assert not any(k in cfg for k in spec["params"]), "the leg declares the lever: nothing to advise"
    on_trades, on_stops = parity.run_harness(
        series, parity.harness_kwargs(dict(cfg, **spec["params"]), symbol="XRPUSDT", leg=LEG),
        tmp_path / "on.jsonl")
    _, off_stops = parity.run_harness(
        series, parity.harness_kwargs(cfg, symbol="XRPUSDT", leg=LEG), tmp_path / "off.jsonl")
    cfg_live = dict(cfg, symbol="XRPUSDT", strategy_label=LEG)
    compared = differs_from_off = 0
    with parity._live_sandbox() as clock:
        for t in on_trades:
            entry_i, exit_i = int(t.entry_index), int(t.exit_index)
            clock.now = parity._epoch(series["timestamp"].iloc[entry_i]) + 4 * 3600 + 1.0
            pkg, _, _, _ = parity.build_live_package(cfg_live, series, t, parity.MONITOR_BASE_LIMIT)
            # The harness's entry/stop, so both sides replay from the same bracket.
            pkg = dict(pkg, entry=float(t.entry), sl=float(t.sl),
                       order_package_id=f"p{entry_i}",
                       meta=dict(pkg["meta"], risk_per_unit=float(t.risk)))
            assert not ba._declared(pkg["meta"], spec)
            for j in range(entry_i + 1, exit_i + 1):
                h_stop = on_stops[entry_i].get(j)
                if h_stop is None:
                    continue
                clock.now = parity._epoch(series["timestamp"].iloc[j]) + 1.0
                frame = parity.live_frame(series, j, parity.MONITOR_BASE_LIMIT)
                out = ba.advise(open_pkg=pkg, meta=pkg["meta"], candles_df=frame,
                                direction=t.direction)
                assert out["advisor_state"] == "computed", out
                assert out["advisor_source"].startswith(f"momentum_trail@{spec['version']}")
                long_ = t.direction == "long"
                want = ((h_stop - t.entry) if long_ else (t.entry - h_stop)) / t.risk
                assert out["advisor_sl_r"] == pytest.approx(want, abs=1e-3), (entry_i, j)
                assert out["advisor_tp_r"] is None
                compared += 1
                off = off_stops.get(entry_i, {}).get(j)
                differs_from_off += off is not None and abs(off - h_stop) > 1e-9
    assert compared >= 100, compared
    assert differs_from_off > 0, "the lever never moved a stop: the equality measured nothing"


def _fixture_pkg(series, n=300):
    """A SHORT opened at bar 240 of the falling stretch, still open at bar 299."""
    frame = series.iloc[:n][["timestamp", "open", "high", "low", "close"]].copy()
    frame["timestamp"] = frame["timestamp"].astype(str)
    entry_ts = frame["timestamp"].iloc[240]
    entry = float(frame["close"].iloc[240])
    meta = {"atr": 0.02, "risk_per_unit": 0.03, "trail_mult": 5.0, "entry_time": entry_ts,
            "timeframe": "4h", "strategy_label": LEG}
    pkg = {"order_package_id": "pkg-x", "strategy_name": LEG, "symbol": "XRPUSDT",
           "direction": "short", "entry": entry, "sl": entry + 0.03, "tp": entry * 0.2,
           "meta": meta}
    return frame, pkg


def test_states_are_distinct(series, tmp_path):
    frame, pkg = _fixture_pkg(series)
    meta = pkg["meta"]
    assert ba.advise(open_pkg=pkg, meta=meta, candles_df=frame, direction="short")[
        "advisor_state"] == "computed"
    ba._cache.clear()
    declared = dict(meta, **_spec()["params"])
    assert ba.advise(open_pkg=pkg, meta=declared, candles_df=frame, direction="short")[
        "advisor_state"] == "declared"
    other = dict(pkg, strategy_name="no_such_leg")
    assert ba.advise(open_pkg=other, meta=dict(meta, strategy_label="no_such_leg"),
                     candles_df=frame, direction="short")["advisor_state"] == "no_lever"
    assert ba.advise(open_pkg=pkg, meta=meta, candles_df=frame, direction="short",
                     registry_path=tmp_path / "missing.json")["advisor_state"] == "registry_unreadable"
    ba._cache.clear()
    assert ba.advise(open_pkg=pkg, meta=dict(meta, trail_vol_tight_mult=1.0), candles_df=frame,
                     direction="short")["advisor_state"] == "unmodelled"
    ba._cache.clear()
    no_time = {k: v for k, v in meta.items() if k != "entry_time"}
    assert ba.advise(open_pkg=pkg, meta=no_time, candles_df=frame, direction="short")[
        "advisor_state"] == "insufficient_data"
    assert set(ba.ADVISOR_STATES) >= {"computed", "declared", "no_lever", "unmodelled",
                                      "insufficient_data", "registry_unreadable", "error"}


def test_one_computation_per_bar(series, monkeypatch):
    frame, pkg = _fixture_pkg(series)
    calls = []
    real = ba._compute
    monkeypatch.setattr(ba, "_compute", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(5):   # five exit-loop passes inside one bar
        ba.advise(open_pkg=pkg, meta=pkg["meta"], candles_df=frame, direction="short")
    assert len(calls) == 1


def test_tp_revision_spec_uses_plan_tp_revision(series, tmp_path):
    import json

    from src.runtime.tp_revision import plan_tp_revision
    frame, pkg = _fixture_pkg(series)
    reg = tmp_path / "matrix.json"
    params = {"rule": "donchian_measured_move", "width_mult": 0.5}
    reg.write_text(json.dumps({"rows": [{"strategy": LEG, "tp_retarget": {
        "status": "passed_unshipped", "advisor": {"lever": "tp_revision", "version": "T/1",
                                                  "params": params}}}]}))
    meta = dict(pkg["meta"], donchian=20)
    out = ba.advise(open_pkg=pkg, meta=meta, candles_df=frame, direction="short",
                    current_price=float(frame["close"].iloc[-1]), registry_path=reg)
    from src.runtime.exit_levers import closed_frame
    rev = plan_tp_revision(leg={**meta, "tp_revision": params}, direction="short",
                           entry=pkg["entry"], risk=meta["risk_per_unit"],
                           bars=closed_frame(frame, meta, {}), entry_time=meta["entry_time"],
                           ref_price=float(frame["close"].iloc[-1]))
    if rev is None:
        assert out["advisor_state"] == "insufficient_data"
    else:
        assert out["advisor_state"] == "computed"
        assert out["advisor_tp_r"] == pytest.approx((pkg["entry"] - rev.tp) / meta["risk_per_unit"],
                                                    abs=1e-4)
        assert out["advisor_source"].startswith("tp_revision@T/1")


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "journal.db")
    Database(path)
    pph._last_prune.clear()
    pph._has_advisor_cols.clear()
    return path


def _history(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM position_path_history")]


def test_an_advisor_exception_leaves_the_monitor_and_bracket_alone(series, db, monkeypatch):
    frame, pkg = _fixture_pkg(series)
    pkg["meta"].update(atr_period=14, donchian=20)
    # The monitor imports the hook by name at call time: route it to the test journal.
    monkeypatch.setattr(pt, "record_position_telemetry",
                        lambda **k: _REAL_RPT(db_path=db, **k))
    baseline = td.monitor({}, frame, dict(pkg))
    rows_ok = _history(db)
    assert rows_ok and rows_ok[-1]["advisor_state"] == "computed"

    def boom(*a, **k):
        raise RuntimeError("advisor exploded")
    monkeypatch.setattr(ba, "_compute", boom)
    ba._cache.clear()
    assert td.monitor({}, frame, dict(pkg)) == baseline
    row = _history(db)[-1]
    assert row["advisor_state"] == "error" and row["advisor_sl_r"] is None
    assert row["sl_r"] == rows_ok[-1]["sl_r"] and row["passes"] == 2

    monkeypatch.setattr(ba, "advise", boom)     # even the wrapper itself raising
    assert td.monitor({}, frame, dict(pkg)) == baseline
    assert _history(db)[-1]["passes"] == 3


def test_history_still_writes_on_a_pre_advisor_table(tmp_path, series):
    path = str(tmp_path / "old.db")
    Database(path)
    with sqlite3.connect(path) as c:   # rebuild the table as it was before this change
        cols = [r[1] for r in c.execute("PRAGMA table_info(position_path_history)")
                if not r[1].startswith("advisor_")]
        c.execute("ALTER TABLE position_path_history RENAME TO pph_new")
        c.execute(f"CREATE TABLE position_path_history AS SELECT {', '.join(cols)} FROM pph_new")
        c.execute("DROP TABLE pph_new")
        c.execute("CREATE UNIQUE INDEX u ON position_path_history(order_package_id, bar_ts)")
    pph._has_advisor_cols.clear()
    frame, pkg = _fixture_pkg(series)
    rec = {"order_package_id": "p", "direction": "short", "entry": pkg["entry"],
           "risk_per_unit": 0.03, "peak_state": "measured"}
    row = pph.build_history_row(rec, window=frame, candles_df=frame,
                                advisor=ba._empty("computed"))
    assert row["advisor_state"] == "computed"
    assert pph.write_history(row, db_path=path) is True   # lands without the new columns
    Database(path)    # the migration adds the four columns
    with sqlite3.connect(path) as c:
        names = {r[1] for r in c.execute("PRAGMA table_info(position_path_history)")}
    assert set(pph.ADVISOR_COLS) <= names


# ---------------------------------------------------------------------------
# Not read by the exit or order path
# ---------------------------------------------------------------------------

#: The only src/ files allowed to name the advisor or its fields: the advisor,
#: its one caller (the telemetry hook), the history writer/reader, the DDL and
#: the diag read route.
_ALLOWED = {
    "src/runtime/bracket_advisor.py",
    "src/runtime/position_telemetry.py",
    "src/runtime/position_path_history.py",
    "src/units/db/database.py",
    "src/web/api/routers/diag.py",
}
_PROBE = re.compile(r"bracket_advisor|advisor_sl_r|advisor_tp_r|advisor_source|advisor_state"
                    r"|ADVISOR_COLS")


def test_no_exit_or_order_path_reads_the_advisor():
    hits = {str(p.relative_to(_REPO)) for p in (_REPO / "src").rglob("*.py")
            if _PROBE.search(p.read_text(errors="ignore"))}
    # The probe must find the files that legitimately name it, or its silence is meaningless.
    assert {"src/runtime/bracket_advisor.py", "src/runtime/position_path_history.py",
            "src/runtime/position_telemetry.py", "src/units/db/database.py"} <= hits
    assert hits <= _ALLOWED, sorted(hits - _ALLOWED)
    # The telemetry hook passes advisor output to the history row ONLY, never back.
    src = (_REPO / "src/runtime/position_telemetry.py").read_text()
    assert src.count("_advisor_fields(") == 2   # its definition and the one call site
    assert re.search(r"advisor=_advisor_fields\(kwargs, candles_df\)\)", src)
