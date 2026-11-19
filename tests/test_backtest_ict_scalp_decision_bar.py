"""`--decision-bar closed|forming` on backtest_ict_scalp.py (row ICT-SCALP-FORMING-BAR-ARM).

RQ-20261118-abab-56 matched 3 of 46 live ict_scalp_eth_15m trades to the closed-bar harness (43 live-only, median entry 4.8 min into the 15m bar):
live decides on the still-forming bar, the harness on closed bars. This locks the as-traded arm: (1) closed (default, and with a 1m frame supplied) is
BYTE-IDENTICAL to the harness before the change (the same golden as the --side-filter / --skip-hours builds), (2) the frame handed to order_package at
tick k is exactly the closed history plus bar i truncated to its first k minutes (no lookahead), (3) ticks run every 2 min (forming_bar_entries.session_ticks: 2..12 on a 15m bar), first passing tick
wins, entry stamped at that tick, (4) a stop/target touched in the rest of the entry bar exits on that bar (stop first), (5) a minute with no 1m data is
never invented, (6) unsupported combinations are refused, (7) exit_lever_ablation's argv carries the 1m CSV only when one is given.
Cost globals are pinned (main() used to leak them across tests; #27175 / #27179)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.backtest_ict_scalp as h

REPO = Path(__file__).resolve().parents[1]
GOLD = json.loads((REPO / "tests" / "data" / "ict_scalp_side_filter_golden.json").read_text())
TF = 15


@pytest.fixture(autouse=True)
def _pin_module_cost_globals(monkeypatch):
    from src.runtime import execution_costs as ec
    monkeypatch.setattr(h, "FEE_BPS_ROUNDTRIP", ec.DEFAULT_FEE_BPS_ROUNDTRIP)
    monkeypatch.setattr(h, "SLIPPAGE_BPS_ROUNDTRIP", 0.0)
    monkeypatch.setattr(h, "FUNDING_BPS_PER_WINDOW", 0.0)
    monkeypatch.setattr(h, "FUNDING_WINDOW_HOURS", ec.FUNDING_WINDOW_HOURS)
    monkeypatch.setattr(h, "CONTRACT_COST", None)


def _df(n=None):
    df = pd.read_csv(REPO / GOLD["source_csv"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df if n is None else df.iloc[:n].reset_index(drop=True)


def _m1(df: pd.DataFrame) -> pd.DataFrame:
    """1m rows whose aggregate over each 15m bar IS that bar (open, high, low, close): a linear open->close path, the bar's high on minute 5 and
    its low on minute 9 (every other minute stays inside [low, high])."""
    rows = []
    for ts, o, hi, lo, c in zip(df["timestamp"], df["open"], df["high"], df["low"], df["close"]):
        path = np.linspace(o, c, TF + 1)
        for m in range(TF):
            a, b = path[m], path[m + 1]
            mh = min(max(a, b), hi)
            ml = max(min(a, b), lo)
            if m == 5:
                mh = hi
            if m == 9:
                ml = lo
            rows.append({"timestamp": ts + pd.Timedelta(minutes=m), "open": a, "high": max(mh, a, b) if m == 5 else mh,
                         "low": min(ml, a, b) if m == 9 else ml, "close": b, "volume": 1.0})
    out = pd.DataFrame(rows)
    out.loc[out.index[::TF], "open"] = df["open"].to_numpy()
    return out


def _run(df, decision_bar="closed", m1=None, **extra):
    return h.run_backtest(df, cfg_overrides=GOLD["cfg_overrides"], _collect_trades=True, return_trades=True, decision_bar=decision_bar,
                          decision_1m=m1, **GOLD["kwargs"], **extra)


def test_closed_default_is_byte_identical_to_the_golden_with_or_without_a_1m_frame():
    df = _df()
    for kw in ({}, {"m1": _m1(df.iloc[:200])}):
        res = _run(df, **kw)
        rows = [[str(t.entry_time), t.direction, round(float(t.entry), 6), round(float(t.sl), 6), str(t.exit_time), t.outcome,
                 round(float(t.r_multiple), 6)] for t in res["_trades_full"]]
        assert rows == GOLD["trades"]
        for k, v in GOLD["summary"].items():
            assert res[k] == v


def test_the_frame_at_tick_k_is_closed_history_plus_the_truncated_bar(monkeypatch):
    df = _df(260)
    m1 = _m1(df)
    seen = []

    def spy(cfg, candles_df=None):
        seen.append(candles_df.copy())
        raise ValueError("no signal")           # observe every tick, never trade

    monkeypatch.setattr(h, "order_package", spy)
    _run(df, "forming", m1)
    assert seen
    by_bar = {}
    for fr in seen:
        by_bar.setdefault(fr["timestamp"].iloc[-1], []).append(fr)
    ticks = {len(v) for v in by_bar.values()}
    assert ticks == {6}, f"15m bar => ticks at 2,4,...,12 (6), got {ticks}"
    bar_ts, frames = next(iter(by_bar.items()))
    i = int(df.index[df["timestamp"] == bar_ts][0])
    for k, fr in zip(range(2, 14, 2), frames):
        sub = m1[(m1["timestamp"] >= bar_ts) & (m1["timestamp"] < bar_ts + pd.Timedelta(minutes=k))]
        last = fr.iloc[-1]
        assert last["open"] == df["open"].iloc[i]
        assert last["high"] == pytest.approx(sub["high"].max()) and last["low"] == pytest.approx(sub["low"].min())
        assert last["close"] == pytest.approx(sub["close"].iloc[-1])
        # everything before the forming row is the CLOSED history, untouched
        prev = fr.iloc[:-1].reset_index(drop=True)
        assert prev.equals(df.iloc[i - len(prev): i].reset_index(drop=True))


def test_first_passing_tick_wins_and_the_entry_is_stamped_at_that_tick(monkeypatch):
    df = _df(260)
    m1 = _m1(df)

    def always(cfg, candles_df=None):
        c = float(candles_df["close"].iloc[-1])
        return {"direction": "long", "entry": c, "sl": c - 5.0, "tp": c + 50.0, "confidence": 1.0, "meta": {}}

    monkeypatch.setattr(h, "order_package", always)
    res = _run(df, "forming", m1)
    trades = res["_trades_full"]
    assert trades
    for t in trades:
        assert t.meta["decision_bar"] == "forming" and t.meta["tick_min"] == 2
        assert pd.Timestamp(t.entry_time).minute % TF == 2, "stamped 2 min into its bar, not at the bar open"


def test_a_stop_or_target_touched_in_the_rest_of_the_entry_bar_exits_on_that_bar(monkeypatch):
    df = _df(260)
    m1 = _m1(df)
    state = {}

    def pkg_factory(sl_off, tp_off):
        def f(cfg, candles_df=None):
            c = float(candles_df["close"].iloc[-1])
            return {"direction": "long", "entry": c, "sl": c - sl_off, "tp": c + tp_off, "confidence": 1.0, "meta": {}}
        return f

    monkeypatch.setattr(h, "order_package", pkg_factory(1e9, 1e-6))      # target a hair above: touched in the rest of the bar
    tp_run = _run(df, "forming", m1)["_trades_full"]
    assert tp_run and all(t.outcome == "tp_hit" and t.exit_index == t.entry_index for t in tp_run)
    monkeypatch.setattr(h, "order_package", pkg_factory(1e-6, 1e-6))     # both touched in the rest of the bar: stop first
    both = _run(df, "forming", m1)["_trades_full"]
    assert both and all(t.outcome == "sl_hit" and t.exit_index == t.entry_index for t in both)
    assert state == {}


def test_a_bar_without_1m_data_is_never_invented(monkeypatch):
    df = _df(260)
    m1 = _m1(df)
    gap_bar = df["timestamp"].iloc[150]
    m1 = m1[~((m1["timestamp"] >= gap_bar) & (m1["timestamp"] < gap_bar + pd.Timedelta(minutes=TF)))]
    called = []

    def spy(cfg, candles_df=None):
        called.append(candles_df["timestamp"].iloc[-1])
        raise ValueError("no signal")

    monkeypatch.setattr(h, "order_package", spy)
    _run(df, "forming", m1)
    assert gap_bar not in called and df["timestamp"].iloc[149] in called


def test_unsupported_combinations_and_bad_values_are_refused():
    df = _df(200)
    m1 = _m1(df)
    with pytest.raises(ValueError, match="decision_1m"):
        _run(df, "forming", None)
    with pytest.raises(ValueError, match="closed\\|forming"):
        _run(df, "intrabar", m1)
    with pytest.raises(ValueError, match="market entry"):
        _run(df, "forming", m1, entry_mode="limit")
    with pytest.raises(ValueError, match="stamp_regime"):
        _run(df, "forming", m1, stamp_regime=True)


def test_cli_needs_a_1m_csv_for_forming_and_parser_defaults(tmp_path):
    p = h.build_parser()
    a = p.parse_args([])
    assert a.decision_bar == "closed" and a.minutes_1m_csv is None
    assert p.parse_args(["--decision-bar", "forming", "--minutes-1m-csv", "x.csv"]).decision_bar == "forming"
    with pytest.raises(SystemExit):
        p.parse_args(["--decision-bar", "intrabar"])
    rc = h.main(["backtest_ict_scalp", "--data", str(REPO / GOLD["source_csv"]), "--symbol", "MGC", "--timeframe", "15m",
                 "--ignore-yaml", "--decision-bar", "forming"])
    assert rc == 2
    rc = h.main(["backtest_ict_scalp", "--data", str(REPO / GOLD["source_csv"]), "--symbol", "MGC", "--timeframe", "15m",
                 "--ignore-yaml", "--decision-bar", "forming", "--minutes-1m-csv", str(tmp_path / "missing.csv")])
    assert rc == 2


def test_ablation_argv_carries_the_1m_csv_only_when_given():
    import yaml
    import scripts.research.regime_debt_matrix as rdm
    strategies = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]
    leg = "ict_scalp_eth_15m"
    cfg = strategies[leg]
    base, _, _ = rdm.build_harness_cmd(leg, cfg, "ict_scalp", "d.csv", "15m", "e.jsonl", "j.json")
    withm, _, _ = rdm.build_harness_cmd(leg, cfg, "ict_scalp", "d.csv", "15m", "e.jsonl", "j.json", forming_1m="m.csv")
    assert "--minutes-1m-csv" not in base
    assert withm[:len(base)] == base and withm[len(base):] == ["--minutes-1m-csv", "m.csv"]
