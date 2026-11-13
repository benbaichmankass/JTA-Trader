"""Row EQ-FORMING-BAR-REPLAY: the US-equity forming-bar replay.

Pins the session alignment (ET date + minute of the ET day, across DST), the cash-session ticks, the regime_debt_matrix
forwarding (decision_bar modelled only when a 1m source is given), and the two scripts' offline self-tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import forming_bar_entries as fbe  # noqa: E402
import regime_debt_matrix as rdm  # noqa: E402


def _bars(dates):
    return pd.DataFrame({"timestamp": pd.to_datetime(dates, utc=True), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})


def test_session_alignment_across_dst():
    bars = _bars(["2024-03-08", "2024-03-11"])                     # EST, then EDT
    m1 = pd.DataFrame({"timestamp": pd.to_datetime(["2024-03-08 14:30", "2024-03-08 20:59",
                                                    "2024-03-11 13:30", "2024-03-11 19:59",
                                                    "2024-03-12 13:30"], utc=True),
                       "high": [2.0, 3.0, 4.0, 5.0, 9.0], "low": 1.0, "close": [1.5, 2.5, 3.5, 4.5, 8.5]})
    M = fbe.minute_matrices(m1, bars, 1440, session="us_equity")
    assert M["last_c"][0, 570] == 1.5 and M["last_c"][1, 570] == 3.5      # 09:30 ET both days
    assert M["run_h"][0, 959] == 3.0 and M["run_h"][1, 959] == 5.0        # 15:59 ET both days
    assert np.isnan(M["run_h"][0, 569])                                   # nothing before the open
    assert np.nanmax(M["run_h"]) == 5.0                                   # 03-12 has no bar: dropped, not misplaced


def test_session_mode_refuses_intraday_stamped_bars():
    bars = _bars(["2024-03-08 04:00"])
    m1 = pd.DataFrame({"timestamp": pd.to_datetime(["2024-03-08 14:30"], utc=True), "high": [1.0], "low": 1.0, "close": 1.0})
    with pytest.raises(ValueError, match="session DATE"):
        fbe.minute_matrices(m1, bars, 1440, session="us_equity")


def test_session_ticks_are_the_cash_session():
    t = fbe.session_ticks("us_equity", 1440)
    assert t[0] == 572 and t[-1] == 960 and all(b - a == 2 for a, b in zip(t, t[1:]))
    assert fbe.session_ticks(None, 1440) == list(range(2, 1439, 2))       # crypto unchanged


def test_crypto_default_alignment_unchanged():
    bars = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=2, freq="4h", tz="UTC"),
                         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})
    m1 = pd.DataFrame({"timestamp": pd.to_datetime(["2024-01-01 00:00", "2024-01-01 04:07"], utc=True),
                       "high": [2.0, 3.0], "low": 1.0, "close": [1.5, 2.5]})
    M = fbe.minute_matrices(m1, bars, 240)
    assert M["last_c"][0, 0] == 1.5 and M["last_c"][1, 7] == 2.5


def test_block_with_arm_params_overrides_entry_params_only():
    b = fbe.block_with_arm_params({"donchian": 20, "atr_period": 14, "atr_stop_mult": 2.5, "tp_r": 1.5, "long_only": True},
                                  donchian=30, atr_period=10, atr_stop_mult=3.0, long_only=False)
    assert (b["donchian"], b["atr_period"], b["atr_stop_mult"], b["tp_r"], b["long_only"]) == (30, 10, 3.0, 1.5, True)


def _cfg(**kw):
    return {"symbols": ["TQQQ"], "timeframe": "1d", "donchian": 20, "atr_period": 14, "atr_stop_mult": 2.5,
            "trail_mult": 4.0, "long_only": True, **kw}


def test_build_harness_cmd_models_forming_only_with_a_1m_source():
    argv, faithful, omitted = rdm.build_harness_cmd("leg", _cfg(), "trend", "d.csv", "1d", "e.jsonl", "j.json")
    assert "decision_bar" in omitted and not faithful and "--decision-bar" not in argv
    argv, faithful, omitted = rdm.build_harness_cmd("leg", _cfg(), "trend", "d.csv", "1d", "e.jsonl", "j.json",
                                                    forming_1m="m.csv", forming_session="us_equity")
    assert "decision_bar" not in omitted and faithful
    i = argv.index("--decision-bar")
    assert argv[i + 1] == "forming" and argv[argv.index("--minutes-1m-csv") + 1] == "m.csv"
    assert argv[argv.index("--decision-session") + 1] == "us_equity" and argv[argv.index("--strategy-name") + 1] == "leg"
    # a decision_bar: closed leg is never switched to forming by a 1m source
    argv, faithful, omitted = rdm.build_harness_cmd("leg", _cfg(decision_bar="closed"), "trend", "d.csv", "1d",
                                                    "e.jsonl", "j.json", forming_1m="m.csv")
    assert "--decision-bar" not in argv and faithful


@pytest.mark.parametrize("script", ["equity_1m_source.py", "eq_forming_bar_replay.py"])
def test_self_tests(script):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / script), "--self-test"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "self-test passed" in r.stdout
