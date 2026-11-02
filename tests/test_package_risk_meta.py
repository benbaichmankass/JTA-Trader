"""ML-ENTRY-RISK-META: ml_entry / claude_desk packages carry risk_per_unit + entry_time, so position telemetry
yields a numeric open_r (it was None -> peak_state no_risk); the backfill action fixes the already-open ones."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.runtime import position_telemetry as pt
from src.units.strategies import claude_desk as cd
from src.units.strategies import ml_entry as M
from tests.test_claude_desk_leg import _row
from tests.test_ml_entry_adapter import _frame, _model, _refs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import backfill_package_risk_meta as bf  # noqa: E402


def _open_r(pkg, price, direction):
    window = pd.DataFrame({"high": [price], "low": [price], "close": [price]})
    rec = pt.build_record(open_pkg={"order_package_id": "pkg-x", "entry": pkg["entry"], "tp": pkg["tp"]},
                          meta=pkg["meta"], window=window, direction=direction, current_price=price,
                          stop=pkg["sl"], target=pkg["tp"], strategy="t")
    return rec


def test_ml_entry_package_carries_risk_and_entry_time_and_telemetry_gets_open_r():
    df = _frame(2)
    pkg = M.order_package({"symbol": "ETHUSDT"}, candles_df=df, reference_frames=_refs(), model=_model(0.0, 0.4))
    assert pkg["direction"] == "short"
    assert pkg["meta"]["risk_per_unit"] == pytest.approx(abs(pkg["entry"] - pkg["sl"]))
    assert pkg["meta"]["entry_time"] == pd.Timestamp(df["ts"].iloc[-1]).isoformat()
    rec = _open_r(pkg, pkg["entry"] - 0.5 * pkg["meta"]["risk_per_unit"], "short")
    assert rec["open_r"] == pytest.approx(0.5)


def test_claude_desk_package_carries_risk_and_entry_time():
    pkg = cd.order_package({}, _row())
    assert pkg["meta"]["risk_per_unit"] == pytest.approx(2.0) and pkg["meta"]["entry_time"]
    assert _open_r(pkg, 101.0, "long")["open_r"] == pytest.approx(0.5)


def _db(tmp_path, pkgs, trades=()):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE order_packages (order_package_id TEXT, strategy_name TEXT, entry REAL, sl REAL, "
              "created_at TEXT, status TEXT, linked_trade_id INT, meta TEXT)")
    c.execute("CREATE TABLE trades (id INT, order_package_id TEXT, created_at TEXT)")
    c.executemany("INSERT INTO order_packages VALUES (?,?,?,?,?,?,?,?)", pkgs)
    c.executemany("INSERT INTO trades VALUES (?,?,?)", trades)
    c.commit()
    c.close()
    return str(p)


def _meta(db, pid):
    c = sqlite3.connect(db)
    m = json.loads(c.execute("SELECT meta FROM order_packages WHERE order_package_id=?", (pid,)).fetchone()[0])
    c.close()
    return m


def test_backfill_adds_missing_keys_only_dry_run_default_and_idempotent(tmp_path):
    db = _db(tmp_path, [
        ("a", "ml_entry", 1.2504, 1.26569, "2026-11-01T10:00:00", "open", 6828, '{"k": 1}'),
        ("b", "ml_entry", 10.0, 9.0, "2026-11-01T11:00:00", "open", None, '{"risk_per_unit": 7, "entry_time": "T"}'),
        ("c", "ml_entry", 10.0, 9.0, "2026-11-01T11:00:00", "closed", None, "{}"),
        ("d", "other", 10.0, 9.0, "2026-11-01T11:00:00", "open", None, "{}"),
        ("e", "claude_desk", 5.0, 5.0, "2026-11-01T11:00:00", "open", None, "{}"),
    ], [(6828, "a", "2026-11-01T10:00:09")])
    assert bf.main(["--db", db]) == 0
    assert _meta(db, "a") == {"k": 1}  # dry run
    assert bf.main(["--db", db, "--apply"]) == 0
    a = _meta(db, "a")
    assert a["risk_per_unit"] == pytest.approx(0.01529) and a["entry_time"] == "2026-11-01T10:00:09" and a["k"] == 1
    assert _meta(db, "b") == {"risk_per_unit": 7, "entry_time": "T"}  # never overwritten
    assert _meta(db, "c") == {} and _meta(db, "d") == {} and _meta(db, "e") == {}  # closed / other / zero risk
    assert bf.main(["--db", db, "--apply"]) == 0 and _meta(db, "a") == a
