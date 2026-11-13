"""CRYPTO-FORMING-RDM-FORWARD: the pullback harness's forming-bar 1m forward and the crypto forming-leg evidence regen."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

import regime_debt_matrix as rdm  # noqa: E402
import forming_evidence_regen as fer  # noqa: E402


def _leg(name):
    cfgs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    return cfgs.get("strategies", cfgs)[name]


def test_pullback_forming_1m_forward_flips_faithful():
    cfg = _leg("eth_pullback_2h")
    assert rdm.classify(cfg) == "pullback"
    argv, faithful, omitted = rdm.build_harness_cmd("eth_pullback_2h", cfg, "pullback", "d.csv", "2h", "e.jsonl", "j.json")
    assert "decision_bar" in omitted and not faithful and "--decision-bar" not in argv
    argv, faithful, omitted = rdm.build_harness_cmd("eth_pullback_2h", cfg, "pullback", "d.csv", "2h", "e.jsonl", "j.json",
                                                    forming_1m="m.csv")
    assert "decision_bar" not in omitted and faithful, omitted
    assert argv[argv.index("--decision-bar") + 1] == "forming"
    assert argv[argv.index("--minutes-1m-csv") + 1] == "m.csv"
    assert argv[argv.index("--strategy-name") + 1] == "eth_pullback_2h"
    assert "--decision-session" not in argv  # crypto: no session mode


def test_pullback_closed_leg_never_switched_to_forming():
    cfg = {**_leg("eth_pullback_2h"), "decision_bar": "closed"}
    argv, faithful, omitted = rdm.build_harness_cmd("eth_pullback_2h", cfg, "pullback", "d.csv", "2h", "e.jsonl", "j.json",
                                                    forming_1m="m.csv")
    assert "--decision-bar" not in argv and "decision_bar" not in omitted


def test_backtest_pullback_accepts_the_1m_cli():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "backtest_pullback.py"), "--help"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "--minutes-1m-csv" in r.stdout and "--decision-session" in r.stdout


def test_plan_scopes_forming_trend_and_pullback_legs():
    rows = {r["leg"]: r for r in fer.plan(["eth_pullback_2h", "trend_donchian_sol_prop", "slv_trend_1h", "no_such_leg"])}
    assert not rows["eth_pullback_2h"].get("skip") and rows["eth_pullback_2h"]["harness"] == "pullback"
    assert not rows["trend_donchian_sol_prop"].get("skip") and rows["trend_donchian_sol_prop"]["data_start"]
    assert rows["slv_trend_1h"]["mode"] == "us_equity_intraday" and not rows["slv_trend_1h"].get("skip")
    assert rows["no_such_leg"]["skip"]


def test_self_test():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / "forming_evidence_regen.py"), "--self-test"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "self-test passed" in r.stdout


# --- CRYPTO-FORMING-EQUITY-REGEN: the US-equity daily branch ------------------------------------------------------

def _fake_alpaca(days=300):
    import numpy as np
    import pandas as pd
    mins, daily, p = [], [], 100.0
    for d in pd.bdate_range(end="2026-11-12", periods=days):
        t0 = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(minutes=570)
        c = p * np.exp(np.cumsum(np.full(390, 1e-5)))
        for i in range(0, 390, 30):  # a sparse minute set is enough for the fetch path
            mins.append({"t": (t0 + pd.Timedelta(minutes=i)).tz_convert("UTC").isoformat(),
                         "o": c[i], "h": c[i], "l": c[i], "c": c[i], "v": 1})
        daily.append({"t": (pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=4))
                      .tz_convert("UTC").isoformat(), "o": c[0], "h": c[::30].max(), "l": c[::30].min(), "c": c[-30], "v": 1})
        p = c[-1]

    class FC:
        key_kind, calls, n_429 = "fake", 0, 0

        def bars(self, symbols, timeframe, start, end, feed="iex", adjustment="split"):
            self.calls += 1
            assert feed == "iex"  # the live feed
            return {symbols[0]: daily if timeframe == "1Day" else mins}
    return FC


def test_equity_daily_fetch_writes_one_source_and_reads_the_window_off_the_data(tmp_path):
    row = fer.plan(["spy_trend_long_1d"])[0]
    assert row["mode"] == "us_equity_daily" and not row.get("skip")
    err = fer.fetch(row, tmp_path, tmp_path / "log", {}, "2026-11-13", client_factory=_fake_alpaca())
    assert err is None, err
    assert row["decision_session"] == "us_equity"
    assert Path(row["data_csv"]).exists() and Path(row["m1_csv"]).exists()
    # 365-day record window back from the pinned end; the window is what the CSV holds, not the request
    assert row["window_used"][0].startswith("2025-11-1") and row["window_used"][1].startswith("2026-11-12")
    assert row["source_meta"]["feed"] == "iex"


def test_equity_regen_forwards_the_us_session(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, log):
        seen["argv"] = argv
        return 1
    monkeypatch.setattr(fer, "_run", fake_run)
    row = {"leg": "spy_trend_long_1d", "data_csv": "d.csv", "m1_csv": "m.csv", "folds": 4, "decision_session": "us_equity"}
    assert fer.regen(row, tmp_path, tmp_path / "log").get("error")
    a = seen["argv"]
    assert a[a.index("--decision-session") + 1] == "us_equity"
    assert a[a.index("--minutes-1m-csv") + 1] == "m.csv"
    row.pop("decision_session")
    fer.regen(row, tmp_path, tmp_path / "log")
    assert "--decision-session" not in seen["argv"]  # crypto: no session


def test_plan_refuses_futures_with_a_reason():
    rows = {r["leg"]: r for r in fer.plan(["mgc_trend_1h", "mes_trend_long_1d", "slv_trend_1h", "gld_pullback_1d"])}
    assert "futures" in rows["mgc_trend_1h"]["skip"] and "futures" in rows["mes_trend_long_1d"]["skip"]
    assert rows["slv_trend_1h"]["mode"] == "us_equity_intraday"
    assert rows["gld_pullback_1d"]["mode"] == "us_equity_daily" and not rows["gld_pullback_1d"].get("skip")


# --- phase B: the intraday US-session forming mode (slv_trend_1h and the other 1h equity legs) ---------------------

def test_intraday_tick_mask_is_the_live_gate():
    """Ticks count only where src.runtime.market_hours.is_market_open('us_equity') is true at bar start + k: its
    [open, close) bounds and its DST-month approximation carry over (the live function is called, not re-implemented)."""
    import pandas as pd
    import forming_bar_entries as fbe
    from src.runtime.market_hours import is_market_open
    bars = pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-07-15 13:00Z",   # EDT: the 09:00 bar -- ticks from 09:30 (k=30, inclusive)
        "2026-07-15 19:00Z",   # 15:00 EDT: the whole bar
        "2026-07-15 20:00Z",   # 16:00 EDT: closed
        "2026-11-13 14:00Z",   # EST: ticks from 14:30Z
        "2026-03-20 13:00Z",   # DST in effect, but live's month table reads March as standard time -> closed
        "2026-07-18 14:00Z",   # Saturday
    ], utc=True)})
    ticks = list(range(2, 59, 2))
    m = fbe.intraday_tick_mask(bars, ticks)
    on = [[k for k, v in zip(ticks, row) if v] for row in m]
    assert on[0][0] == 30 and on[0][-1] == 58
    assert len(on[1]) == len(ticks)
    assert on[2] == [] and on[4] == [] and on[5] == []
    assert on[3][0] == 30
    # exact agreement with the live function on every cell
    for i, t0 in enumerate(bars["timestamp"]):
        for j, k in enumerate(ticks):
            assert m[i, j] == is_market_open("us_equity", (t0 + pd.Timedelta(minutes=k)).to_pydatetime())


def test_intraday_mode_maps_minutes_to_clock_aligned_bars():
    """us_equity_intraday must NOT use the daily ET-date mapping: a 1m row lands in the clock hour that contains it."""
    import numpy as np
    import pandas as pd
    import forming_bar_entries as fbe
    bars = pd.DataFrame({"timestamp": pd.to_datetime(["2026-07-15 13:00Z", "2026-07-15 14:00Z"], utc=True)})
    ts = pd.date_range("2026-07-15 13:00Z", periods=120, freq="1min")
    m1 = pd.DataFrame({"timestamp": ts, "high": np.arange(120.0) + 1, "low": np.arange(120.0), "close": np.arange(120.0)})
    mats = fbe.minute_matrices(m1, bars, 60, session="us_equity_intraday")
    assert mats["run_h"][0, 59] == 60.0 and mats["run_h"][1, 0] == 61.0
    assert mats["last_c"][1, 59] == 119.0


def test_equity_source_hourly_alignment_is_measured():
    import pandas as pd
    import equity_1m_source as eqs
    ts = pd.date_range("2026-07-15 08:00Z", periods=12 * 60, freq="1min")  # 04:00..15:59 EDT: extended + cash
    # each hour peaks in its FIRST minute: in the 09:00 bar that is premarket, which only the "all" set holds
    m1 = pd.DataFrame({"timestamp": ts, "open": 1.0, "high": [1.0 + (59 - i % 60) / 100 for i in range(len(ts))],
                       "low": 1.0, "close": 1.0, "volume": 1})
    hourly = (m1.assign(h=ts.floor("60min")).groupby("h").agg(high=("high", "max"), low=("low", "min"))
              .reset_index().rename(columns={"h": "timestamp"}))
    a = eqs.alignment_hourly(hourly, m1)
    assert a["all"]["match_share"] == 1.0 and a["rth"]["match_share"] < 1.0 and a["chosen"] == "all"
    assert a["rth"]["hours_compared"] < a["all"]["hours_compared"]  # each set's own denominator


def test_plan_routes_1h_equity_to_the_intraday_mode():
    rows = {r["leg"]: r for r in fer.plan(["slv_trend_1h", "qqq_pullback_1h", "mgc_trend_1h"])}
    assert rows["slv_trend_1h"]["mode"] == "us_equity_intraday" and not rows["slv_trend_1h"].get("skip")
    assert rows["qqq_pullback_1h"]["mode"] == "us_equity_intraday"
    assert "futures" in rows["mgc_trend_1h"]["skip"]
