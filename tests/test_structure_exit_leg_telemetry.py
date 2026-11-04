"""A structure-exit leg must still write position telemetry.

PAPER-MECHANICS-20261104 item 5. In ``trend_donchian.monitor`` and
``htf_pullback_trend_2h.monitor`` the STRUCTURE-EXITS-DEFAULT branch returned
``structure_exit_verdict(...)`` BEFORE the M31 P2 ``record_position_telemetry``
hook, which sits on the chandelier path. So every leg declaring
``structure_exit`` (bybit_1 trend_donchian_{sol,eth,1h}, tlt/gld pullback, all
``pivot=5``) wrote no telemetry row, and the live review read each one as
``could_not_look``. Measured 2026-11-04 18:24Z on
``/api/diag/position_telemetry?limit=300``: the three bybit_1 packages opened
that day with ``structure_exit`` had no row; the two without it did.

Pins: the hook fires on the structure branch, the verdict is unchanged, and a
telemetry failure never reaches the verdict.
"""
from __future__ import annotations

import importlib

import pytest

from src.runtime import position_telemetry as pt
from src.runtime import structure_exit_live as sxl

from tests.test_structure_exit_live import _pkg, bars2h  # noqa: F401  (fixture)

_MODS = [
    ("src.units.strategies.trend_donchian", "4h"),
    ("src.units.strategies.htf_pullback_trend_2h", "2h"),
]


@pytest.fixture(autouse=True)
def _no_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path))


@pytest.mark.parametrize("modname,tf", _MODS)
def test_structure_branch_records_telemetry(monkeypatch, bars2h, modname, tf):  # noqa: F811
    calls = []
    monkeypatch.setattr(pt, "record_position_telemetry",
                        lambda **kw: calls.append(kw))
    monkeypatch.setattr(sxl, "structure_exit_verdict",
                        lambda meta, pkg, df, **k: {"sl": 1.0})
    mod = importlib.import_module(modname)
    df = bars2h.iloc[:400]
    pkg = _pkg(df, 200, "long", tf=tf)
    pkg["meta"]["max_hold_min"] = 10 ** 9
    verdict = mod.monitor({}, df.iloc[:260], pkg)
    assert verdict == {"sl": 1.0}
    assert len(calls) == 1, f"{modname}: no telemetry on the structure branch"
    kw = calls[0]
    assert kw["open_pkg"]["order_package_id"] == pkg["order_package_id"]
    assert kw["direction"] == "long"
    assert kw["stop"] == pytest.approx(float(pkg["sl"]))
    assert kw["atr"] and kw["atr"] > 0
    assert kw["window"] is not None and len(kw["window"]) > 0


@pytest.mark.parametrize("modname,tf", _MODS)
def test_telemetry_failure_never_changes_the_verdict(monkeypatch, bars2h, modname, tf):  # noqa: F811
    def _boom(**_kw):
        raise RuntimeError("telemetry down")

    monkeypatch.setattr(pt, "record_position_telemetry", _boom)
    monkeypatch.setattr(sxl, "structure_exit_verdict",
                        lambda meta, pkg, df, **k: {"tp": 2.0})
    mod = importlib.import_module(modname)
    df = bars2h.iloc[:400]
    pkg = _pkg(df, 200, "long", tf=tf)
    pkg["meta"]["max_hold_min"] = 10 ** 9
    assert mod.monitor({}, df.iloc[:260], pkg) == {"tp": 2.0}
