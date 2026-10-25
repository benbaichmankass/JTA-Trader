"""The isolated pairs executor on a SESSION venue (Alpaca) — PAIRS-ALPACA-BUILD.

Covers src/units/strategies/pairs_venue.py, the session branch of
pairs_executor.run_pairs_tick, the spread-target leg TP (TP doctrine), and a
bar-by-bar PARITY check of the live decision path against the harness that
produced the RQ-20261007-025 evidence (scripts/backtest_pairs.py).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.units.strategies import pairs_engine as pe  # noqa: E402
from src.units.strategies import pairs_executor as px  # noqa: E402
from src.units.strategies import pairs_venue as pv  # noqa: E402

# The registered RQ-20261007-025 parameters (OOS.json params block).
REG = dict(lookback=20, entry_z=2.0, exit_z=0.5, stop_z=2.0, max_hold_bars=20,
           hedge_beta="one")


def _params(**kw):
    return pe.PairParams("GLD", "GDX", **{**REG, **kw})


def _stamps_ending(n, end="2026-10-12"):
    """n weekday daily stamps whose LAST is session *end* (the fake clock's day)."""
    d = datetime.fromisoformat(end).replace(hour=4, tzinfo=timezone.utc)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _daily_stamps(n, start="2026-01-02"):
    # Alpaca daily bars are stamped at the session date's 04:00Z (00:00 ET).
    d0 = datetime.fromisoformat(start).replace(hour=4, tzinfo=timezone.utc)
    out, d = [], d0
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _jammed(n=120, jam=0.15, seed=4):
    """GLD/GDX-like closes whose LAST bar is jammed (|z| >> entry_z)."""
    rng = np.random.default_rng(seed)
    lb = np.cumsum(rng.normal(0, 0.01, n)) + np.log(60.0)
    s = np.zeros(n)
    for i in range(1, n):
        s[i] = 0.9 * s[i - 1] + rng.normal(0, 0.01)
    s[-1] = s[-2] + jam
    la = lb + np.log(5.0) + s
    return list(np.exp(la)), list(np.exp(lb))


# ── pure: session clock ────────────────────────────────────────────────────

def _clock(is_open, minutes_to_close=5):
    now = datetime(2026, 10, 12, 19, 55, tzinfo=timezone.utc)
    return {"is_open": is_open, "timestamp": now.isoformat(),
            "next_close": (now + timedelta(minutes=minutes_to_close)).isoformat(),
            "next_open": (now + timedelta(hours=14)).isoformat()}


def test_window_states_are_four_and_distinct():
    assert pv.decision_window_state(_clock(True, 5)) == "in_window"
    assert pv.decision_window_state(_clock(True, 90)) == "open_outside_window"
    assert pv.decision_window_state(_clock(False)) == "closed"
    assert pv.decision_window_state(None) == "unreadable"
    assert pv.decision_window_state({"is_open": True}) == "unreadable"     # no next_close
    assert pv.decision_window_state({"is_open": "?"}) == "unreadable"      # not a bool


# ── pure: trading-bar counts reproduce the harness's indices ───────────────

def test_bars_after_counts_trading_bars_not_calendar_days():
    stamps = _daily_stamps(30)
    opened = stamps[0] + timedelta(hours=15, minutes=52)   # inside bar 0's session
    # Over a weekend the calendar count would jump; the trading count does not.
    assert pv.bars_after(opened, stamps[:1]) == 0
    assert pv.bars_after(opened, stamps[:21]) == 20         # harness j - i at timeout
    assert pv.bars_after(None, stamps) is None


def test_cooldown_matches_harness_next_idx():
    stamps = _daily_stamps(10)
    closed = ("found", stamps[3] + timedelta(hours=15, minutes=52))   # exit at bar e=3
    # harness: next_idx = e + 1 + cooldown_bars = 5 for cooldown 1
    assert pv.cooldown_state(1, closed, stamps[:5]) == "cooling"   # bar 4
    assert pv.cooldown_state(1, closed, stamps[:6]) == "clear"     # bar 5
    assert pv.cooldown_state(0, closed, stamps[:5]) == "clear"     # bar 4 = e+1
    assert pv.cooldown_state(1, ("none", None), stamps) == "clear"
    assert pv.cooldown_state(1, ("error", None), stamps) == "unreadable"


def test_last_close_time_three_states(tmp_path):
    import sqlite3
    db = tmp_path / "j.db"
    assert pv.last_close_time("pairs_gld_gdx_a", "alpaca_paper", str(db))[0] == "error"
    from tests.test_pairs_executor import _real_trades_ddl
    conn = sqlite3.connect(db)
    conn.execute(_real_trades_ddl())
    conn.commit()
    assert pv.last_close_time("pairs_gld_gdx_a", "alpaca_paper", str(db)) == ("none", None)
    conn.execute(
        "INSERT INTO trades (timestamp, symbol, direction, entry_price, position_size, "
        "status, strategy_name, account_id, closed_at, is_backtest) "
        "VALUES (?,?,?,?,?,?,?,?,?,0)",
        ("2026-10-01T19:52:00+00:00", "GLD", "long", 300.0, 10, "closed",
         "pairs_gld_gdx_a", "alpaca_paper", "2026-10-05T19:52:00+00:00"))
    conn.commit()
    conn.close()
    st, dt = pv.last_close_time("pairs_gld_gdx_a", "alpaca_paper", str(db))
    assert st == "found" and dt == datetime(2026, 10, 5, 19, 52, tzinfo=timezone.utc)


# ── pure: whole shares + buying power ──────────────────────────────────────

def test_whole_share_legs_floor_never_round_up():
    assert pv.whole_share_legs(10.99, 3.0000000001) == (10, 3)
    assert pv.whole_share_legs(0.7, 5) == (0, 5)


def test_fit_buying_power_states():
    assert pv.fit_buying_power(10, 50, 300.0, 60.0, 100000.0)["bp_state"] == "fits"
    unk = pv.fit_buying_power(10, 50, 300.0, 60.0, None)
    assert unk["bp_state"] == "unknown" and (unk["qty_a"], unk["qty_b"]) == (10, 50)
    sc = pv.fit_buying_power(100, 500, 300.0, 60.0, 30000.0)   # gross 60k vs cap 28.5k
    assert sc["bp_state"] == "scaled"
    assert sc["qty_a"] * 300 + sc["qty_b"] * 60 <= 30000.0 * pv.BUYING_POWER_BUFFER
    assert abs(sc["qty_b"] / sc["qty_a"] - 5.0) < 0.2           # hedge ratio kept
    assert pv.fit_buying_power(1, 5, 300.0, 60.0, 100.0)["bp_state"] == "insufficient"


def test_align_frames_inner_joins_on_timestamp():
    st = _daily_stamps(4)
    a = ([1.0, 2.0, 3.0, 4.0], st)
    b = ([10.0, 30.0, 40.0], [st[0], st[2], st[3]])        # day 1 missing on B
    ca, cb, ts = pv.align_frames(a, b)
    assert ts == [st[0], st[2], st[3]] and ca == [1.0, 3.0, 4.0] and cb == [10.0, 30.0, 40.0]


# ── pure: shorts ───────────────────────────────────────────────────────────

class _ShortClient:
    def __init__(self, enabled=True, asset=None):
        self._enabled, self._asset = enabled, asset

    def account_status(self):
        return {"shorting_enabled": self._enabled}

    def asset_short_status(self, symbol):
        return self._asset


@pytest.fixture(autouse=True)
def _clear_short_cache():
    from src.runtime import broker_shorting_gate as g
    g._clear_cache()
    px._clock_streaks.clear()
    yield
    g._clear_cache()


@pytest.mark.parametrize("enabled,asset,reason", [
    (False, {"shortable": True, "easy_to_borrow": True}, "broker_shorting_disabled"),
    (True, {"tradable": True, "shortable": False}, "asset_not_shortable"),
    (True, {"tradable": True, "shortable": True, "easy_to_borrow": False}, "asset_hard_to_borrow"),
    (True, {"tradable": False}, "asset_not_tradable"),
    (True, {"tradable": True, "shortable": True, "easy_to_borrow": True}, None),
    (True, None, None),          # could not look -> not refused (venue + unwind own it)
])
def test_short_leg_block(enabled, asset, reason):
    acct = {"account_id": f"alpaca_t_{enabled}_{reason}", "exchange": "alpaca"}
    got, state = pv.short_leg_block(_ShortClient(enabled, asset), acct, "GDX")
    assert got == reason, state


# ── pure: spread-target TP (TP doctrine clause 1) ──────────────────────────

@pytest.mark.parametrize("jam", [0.15, -0.15])
def test_decide_pair_whole_shares_and_predictive_leg_tps(jam):
    ca, cb = _jammed(jam=jam)
    d = px.decide_pair(_params(), ca, cb, open_state=None, held_symbols=set(),
                       risk_budget_usd=1500.0, correlation_open=0,
                       whole_units=True, leg_tp="spread_target")
    assert d.event == "open", d.soak
    assert d.soak["tp_basis"] == "spread_target"
    for leg in d.legs:
        assert leg.qty == int(leg.qty) and leg.qty >= 1           # whole shares
        if leg.direction == "long":
            assert leg.sl < leg.entry_ref < leg.tp
        else:
            assert leg.tp < leg.entry_ref < leg.sl
    # Each leg's TP alone closes the predicted gap: A carries +gap, B carries -gap.
    gap = d.soak["tp_gap_log"]
    la, lb = d.legs
    assert np.isclose(np.log(la.tp / la.entry_ref), gap, atol=1e-6)
    assert np.isclose(np.log(lb.tp / lb.entry_ref), -gap, atol=1e-6)
    # ...and it is NOT the backstop the Bybit sleeve uses.
    _, tp_backstop = px.psz.leg_protective_levels(la.direction, la.entry_ref, d.soak["risk"], 3.0)
    assert not np.isclose(la.tp, tp_backstop)


def test_backstop_default_unchanged_for_bybit_pairs():
    ca, cb = _jammed()
    d = px.decide_pair(_params(), ca, cb, open_state=None, held_symbols=set(),
                       risk_budget_usd=1500.0, correlation_open=0)
    assert d.soak["tp_basis"] == "backstop"
    assert any(leg.qty != int(leg.qty) for leg in d.legs)        # fractional, as before


def test_leg_target_prices_refuses_a_gap_not_in_favour():
    assert pe.leg_target_prices("long_spread", 300, 60, 0.10, 0.05, 1.0) is None
    assert pe.leg_target_prices("short_spread", 300, 60, 0.05, 0.10, 1.0) is None
    assert pe.leg_target_prices("long_spread", 300, 60, 0.05, 0.10, 1.0) is not None


# ── harness parity: the live decision path reproduces backtest_pairs ───────

def _harness_trades(ca, cb, stamps, cooldown):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import backtest_pairs as bp
    m = pd.DataFrame({"timestamp": stamps, "close_a": ca, "close_b": cb})
    rows = []
    bp.run_backtest(m, cooldown_bars=cooldown, timeframe="1d", pair="GLD/GDX",
                    collect_rows=rows, **REG)
    return [(r["entry_time"], r["exit_time"], r["outcome"]) for r in rows]


def _live_trades(ca, cb, stamps, cooldown):
    """Replay the LIVE decision path one bar at a time: decide_pair on the
    window ending at bar t, trading-bar bars_held and cooldown from
    pairs_venue (the same functions run_pairs_tick calls)."""
    params, out, pos, last_close = _params(), [], None, ("none", None)
    for t in range(len(ca)):
        wa, wb, ws = ca[:t + 1], cb[:t + 1], stamps[:t + 1]
        decided_at = ws[-1] + timedelta(hours=15, minutes=52)    # inside bar t's session
        if pos is not None:
            op = pe.OpenPair(pos["dir"], pos["entry_spread"], pos["stop_spread"],
                             pv.bars_after(pos["opened"], ws))
            d = px.decide_pair(params, wa, wb, open_state=op, held_symbols=set(),
                               risk_budget_usd=1000.0, correlation_open=0)
            if d.event == "close":
                out.append((pos["t"], ws[-1], d.soak["outcome"]))
                pos, last_close = None, ("found", decided_at)
            continue
        if pv.cooldown_state(cooldown, last_close, ws) != "clear":
            continue
        d = px.decide_pair(params, wa, wb, open_state=None, held_symbols=set(),
                           risk_budget_usd=1000.0, correlation_open=0)
        if d.event == "open":
            pos = {"dir": d.soak["direction"], "entry_spread": d.soak["entry_spread"],
                   "stop_spread": d.soak["stop_spread"], "opened": decided_at, "t": ws[-1]}
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_live_path_reproduces_harness_trades(seed):
    n = 600
    rng = np.random.default_rng(seed)
    lb = np.cumsum(rng.normal(0, 0.012, n)) + np.log(60.0)
    s = np.zeros(n)
    for i in range(1, n):
        s[i] = 0.93 * s[i - 1] + rng.normal(0, 0.015)
    ca, cb = list(np.exp(lb + np.log(5.0) + s)), list(np.exp(lb))
    stamps = _daily_stamps(n)
    harness = _harness_trades(ca, cb, stamps, cooldown=1)
    # The harness force-closes an open trade on the LAST bar (data end); the
    # live path simply still holds it. Compare every trade before that.
    harness = [h for h in harness if h[1] != stamps[-1]]
    live = _live_trades(ca, cb, stamps, cooldown=1)
    assert len(harness) >= 20                     # a real population, not 2 trades
    assert live == harness


# ── run_pairs_tick on the session venue ────────────────────────────────────

class _FakeAlpaca:
    def __init__(self, *, is_open=True, minutes_to_close=5, bp=1_000_000.0,
                 shortable=True, clock_ok=True):
        self._clock = _clock(is_open, minutes_to_close) if clock_ok else None
        self._bp, self._shortable = bp, shortable

    def clock(self):
        return self._clock

    def buying_power(self):
        return self._bp

    def account_status(self):
        return {"shorting_enabled": True}

    def asset_short_status(self, symbol):
        return {"tradable": True, "shortable": self._shortable, "easy_to_borrow": True}


def _session_env(tmp_path, monkeypatch, *, client, jam=0.15, execute=None, closer=None,
                 directional=None, dd_trip=False):
    """Wire run_pairs_tick for ONE live GLD/GDX pair on alpaca_paper."""
    from tests.test_pairs_executor import _empty_journal
    ca, cb = _jammed(jam=jam)
    stamps = _stamps_ending(len(ca))      # last bar = the fake clock's session
    soak, placed, closes, saved = [], [], [], []
    monkeypatch.setattr(px, "_load_pairs_config", lambda path=None: {
        "account_id": "bybit_1", "pairs_risk_fraction": 1.0,
        "pairs": [{"name": "pairs_gld_gdx", "account_id": "alpaca_paper",
                   "symbol_a": "GLD", "symbol_b": "GDX", "execution": "live",
                   "timeframe": "1d", "cooldown_bars": 1, "leg_tp": "spread_target",
                   **REG}],
    })
    monkeypatch.setattr(pv, "fetch_leg_frame",
                        lambda sym, tf, lim, s: ((ca if sym == "GLD" else cb), stamps))
    monkeypatch.setattr(pv, "build_client", lambda acct: client)
    monkeypatch.setattr(px, "_save_decision_bars", lambda state: saved.append(dict(state)))
    monkeypatch.setattr(px, "_load_decision_bars", lambda: {})
    monkeypatch.setattr(px, "_dd_switch_blocks", lambda *a, **k: dd_trip)
    if directional is not None:
        monkeypatch.setattr(px, "_directional_open_state",
                            lambda acct, sym, db: directional.get(sym, "absent"))
    import src.units.accounts.execute as _exec
    monkeypatch.setattr(_exec, "_fetch_balance", lambda *a, **k: 100000.0)

    def _exec_default(pkg, acct, **k):
        placed.append((pkg.symbol, pkg.direction, k.get("qty_override"), pkg.sl, pkg.tp,
                       acct.get("account_id")))
        return f"T{len(placed)}"
    monkeypatch.setattr(_exec, "execute_pkg", execute or _exec_default)

    def _close_default(client_, acct, *, symbol, side, qty, **k):
        closes.append((symbol, side, qty))
        return {"ok": True}
    monkeypatch.setattr(_exec, "close_open_position", closer or _close_default)
    import src.core.coordinator as _coord
    monkeypatch.setattr(_coord, "_log_new_order_package", lambda pkg: None)
    import src.units.accounts.qty_legalize as _ql
    monkeypatch.setattr(_ql, "legalize_qty",
                        lambda qty, *, symbol, **k: _ql.LegalizedQty(
                            qty=qty, ok=True, reason="", venue_min=1, step=1,
                            source="instrument_profile"))
    import src.config.accounts_loader as _al
    monkeypatch.setattr(_al, "load_accounts_dict", lambda *a, **k: {
        "alpaca_paper": {"exchange": "alpaca", "account_class": "paper", "mode": "live",
                         "risk": {"risk_pct": 0.015}}})
    import src.utils.paths as _paths
    monkeypatch.setattr(_paths, "trade_journal_db_path", lambda: str(tmp_path / "j.db"))
    _empty_journal(tmp_path / "j.db")
    import src.runtime.pairs_soak as _soak
    monkeypatch.setattr(_soak, "record_pairs_soak", lambda rec: soak.append(rec) or True)
    alerts = []
    import src.runtime.outcomes as _out
    monkeypatch.setattr(_out, "report", lambda *a, **k: alerts.append((a, k)))
    return {"soak": soak, "placed": placed, "closes": closes, "saved": saved,
            "alerts": alerts}


def test_tick_in_window_opens_both_legs_whole_shares_on_alpaca_paper(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca())
    px.run_pairs_tick({})
    assert [r["event"] for r in env["soak"]] == ["open"], env["soak"]
    assert len(env["placed"]) == 2
    (sa, da, qa, sla, tpa, acc_a), (sb, db_, qb, slb, tpb, _) = env["placed"]
    assert (sa, sb) == ("GLD", "GDX") and {da, db_} == {"long", "short"}
    assert acc_a == "alpaca_paper"
    assert qa == int(qa) and qb == int(qb) and qa >= 1 and qb >= 1
    assert env["soak"][0]["tp_basis"] == "spread_target"


def test_tick_outside_window_decides_nothing_and_keeps_the_bar(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(minutes_to_close=120))
    px.run_pairs_tick({})
    assert env["soak"] == [] and env["placed"] == []
    assert env["saved"] == []           # bar NOT consumed: the in-window tick decides it


def test_tick_market_closed_places_nothing(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(is_open=False))
    px.run_pairs_tick({})
    assert env["soak"] == [] and env["placed"] == [] and env["saved"] == []


def test_tick_clock_unreadable_warns_once_then_one_red_flag(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(clock_ok=False))
    for _ in range(5):
        px.run_pairs_tick({})
    kinds = [a[1] for a, _k in env["alerts"] if a and a[0] == "pairs_clock_unreadable"]
    assert kinds == ["unreadable", "red_flag"]
    assert env["placed"] == []


def test_legging_failure_unwinds_the_placed_leg(tmp_path, monkeypatch):
    """Leg A fills, leg B is rejected (e.g. borrow pulled between check and
    send): leg A is flattened at its own qty, the row reads open_failed, and a
    WARN (clean unwind) is raised — never a naked leg left silently."""
    calls = []

    def _exec(pkg, acct, **k):
        calls.append(pkg.symbol)
        if pkg.symbol == "GDX":
            raise RuntimeError("Alpaca rejected order for GDX: not shortable")
        return "T1"
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(), execute=_exec)
    px.run_pairs_tick({})
    assert calls == ["GLD", "GDX"]
    assert len(env["closes"]) == 1 and env["closes"][0][0] == "GLD"
    assert env["soak"][0]["event"] == "open_failed"
    kinds = [(a[0], a[1]) for a, _k in env["alerts"]]
    assert ("pairs_partial_placement", "unwound") in kinds


def test_legging_failure_with_failed_unwind_is_critical(tmp_path, monkeypatch):
    def _exec(pkg, acct, **k):
        if pkg.symbol == "GDX":
            raise RuntimeError("rejected")
        return "T1"
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(), execute=_exec,
                       closer=lambda *a, **k: {"ok": False, "error": "market closed"})
    px.run_pairs_tick({})
    kinds = [(a[0], a[1]) for a, _k in env["alerts"]]
    assert ("pairs_naked_leg", "unresolved") in kinds
    assert env["soak"][0]["naked_legs"]


def test_short_leg_not_shortable_refuses_whole_pair_before_sending(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(shortable=False))
    px.run_pairs_tick({})
    assert env["placed"] == []
    assert env["soak"][0]["event"] == "skip_short_unavailable"
    assert env["soak"][0]["short_block"]["reason"] == "asset_not_shortable"


def test_directional_position_on_a_leg_symbol_refuses_the_pair(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(),
                       directional={"GLD": "present"})
    px.run_pairs_tick({})
    assert env["placed"] == []
    assert env["soak"][0]["event"] == "skip_directional_conflict"


def test_directional_unreadable_retries_next_tick(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(),
                       directional={"GDX": "unreadable"})
    px.run_pairs_tick({})
    assert env["placed"] == []
    assert env["soak"][0]["event"] == "skip_state_unreadable"
    assert env["saved"] and "pairs_gld_gdx" not in env["saved"][-1]   # bar un-consumed


def test_buying_power_scales_the_pair_down(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(bp=20000.0))
    px.run_pairs_tick({})
    assert env["soak"][0]["event"] == "open"
    gross = sum(q * (300 if s == "GLD" else 60) for s, _d, q, *_ in env["placed"])
    assert env["soak"][0]["buying_power"]["state"] == "scaled"
    assert gross < 20000.0 * 1.5          # order-of-magnitude bound; exact cap uses entry_ref


def test_daily_dd_switch_blocks_new_pairs(tmp_path, monkeypatch):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca(), dd_trip=True)
    px.run_pairs_tick({})
    assert env["placed"] == []
    assert env["soak"][0]["event"] == "skip_daily_dd_switch"


def test_real_config_gld_gdx_entry_uses_the_registered_params():
    cfg = px._load_pairs_config("config/pairs.yaml")
    p = next(x for x in cfg["pairs"] if x["name"] == "pairs_gld_gdx")
    assert p["account_id"] == "alpaca_paper"
    params = px._params_from_cfg(p)
    assert (params.lookback, params.entry_z, params.exit_z, params.stop_z,
            params.max_hold_bars, params.hedge_beta) == (20, 2.0, 0.5, 2.0, 20, "one")
    assert p["timeframe"] == "1d" and p["cooldown_bars"] == 1
    assert p["leg_tp"] == "spread_target"


# ── AlpacaClient reads added for the session venue ─────────────────────────

def test_alpaca_clock_and_asset_reads_three_states(monkeypatch):
    from src.units.accounts.alpaca_client import AlpacaClient
    c = AlpacaClient(api_key="k", api_secret="s")
    monkeypatch.setattr(c, "_request", lambda m, p, j=None: {"retCode": 0, "result": {
        "is_open": True, "timestamp": "t", "next_open": "o", "next_close": "c", "x": 1}})
    assert c.clock() == {"is_open": True, "timestamp": "t", "next_open": "o", "next_close": "c"}
    monkeypatch.setattr(c, "_request", lambda m, p, j=None: {"retCode": 500, "retMsg": "x"})
    assert c.clock() is None and c.asset_short_status("GDX") is None   # could not look
    monkeypatch.setattr(c, "_request", lambda m, p, j=None: {"retCode": 0, "result": {
        "symbol": "GDX", "tradable": True, "shortable": True, "easy_to_borrow": False,
        "fractionable": True}})
    assert c.asset_short_status("gdx") == {"tradable": True, "shortable": True,
                                           "easy_to_borrow": False, "fractionable": True}
    assert AlpacaClient(api_key="", api_secret="").clock() is None     # no creds


# ── TP revision through the trade (TP doctrine clause 2) ───────────────────

def _seed_open_gld_gdx(db, *, tp_a, tp_b):
    import sqlite3
    from tests.test_pairs_executor import _real_trades_ddl
    conn = sqlite3.connect(db)
    conn.execute(_real_trades_ddl())
    for sym, strat, side, tp in (("GLD", "pairs_gld_gdx_a", "short", tp_a),
                                 ("GDX", "pairs_gld_gdx_b", "long", tp_b)):
        conn.execute(
            "INSERT INTO trades (timestamp, symbol, direction, entry_price, position_size, "
            "status, strategy_name, account_id, take_profit_1, is_backtest) "
            "VALUES (?,?,?,?,?,?,?,?,?,0)",
            ("2026-10-01T19:52:00+00:00", sym, side, 300.0 if sym == "GLD" else 60.0,
             10 if sym == "GLD" else 50, "open", strat, "alpaca_paper", tp))
    conn.commit()
    conn.close()


def test_revise_leg_tps_moves_both_legs_to_the_new_target(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "j.db"
    _seed_open_gld_gdx(db, tp_a=1.0, tp_b=999.0)
    import src.utils.paths as _paths
    monkeypatch.setattr(_paths, "trade_journal_db_path", lambda: str(db))
    sent = []
    import src.units.accounts.execute as _exec
    monkeypatch.setattr(_exec, "modify_open_order",
                        lambda client, acct, **k: sent.append(k) or {"ok": True})
    ca, cb = _jammed(jam=0.15)            # short_spread still extended -> gap < 0
    pair = {"name": "pairs_gld_gdx", "symbol_a": "GLD", "symbol_b": "GDX"}
    out = px._revise_leg_tps(object(), {"account_id": "alpaca_paper", "exchange": "alpaca"},
                             pair, _params(), ca, cb, "short_spread")
    assert [r["revised"] for r in out] == [True, True], out
    assert [k["symbol"] for k in sent] == ["GLD", "GDX"]
    assert sent[0]["qty"] == 10 and sent[1]["qty"] == 50          # trade-scoped amend
    assert sent[0]["tp"] < ca[-1] and sent[1]["tp"] > cb[-1]      # short A below, long B above
    rows = sqlite3.connect(db).execute(
        "SELECT symbol, take_profit_1 FROM trades ORDER BY id").fetchall()
    assert rows == [("GLD", sent[0]["tp"]), ("GDX", sent[1]["tp"])]


def test_revise_leg_tps_failed_amend_leaves_the_journal_tp(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "j.db"
    _seed_open_gld_gdx(db, tp_a=1.0, tp_b=999.0)
    import src.utils.paths as _paths
    monkeypatch.setattr(_paths, "trade_journal_db_path", lambda: str(db))
    import src.units.accounts.execute as _exec
    monkeypatch.setattr(_exec, "modify_open_order",
                        lambda client, acct, **k: {"ok": False, "error": "venue said no"})
    ca, cb = _jammed(jam=0.15)
    out = px._revise_leg_tps(object(), {"account_id": "alpaca_paper", "exchange": "alpaca"},
                             {"name": "pairs_gld_gdx", "symbol_a": "GLD", "symbol_b": "GDX"},
                             _params(), ca, cb, "short_spread")
    assert all(r["revised"] is False and r["error"] == "venue said no" for r in out)
    rows = sqlite3.connect(db).execute("SELECT take_profit_1 FROM trades ORDER BY id").fetchall()
    assert rows == [(1.0,), (999.0,)]


def test_session_bars_held_reads_open_time_from_leg_rows(tmp_path):
    db = tmp_path / "j.db"
    _seed_open_gld_gdx(db, tp_a=1.0, tp_b=999.0)      # no order_packages table -> leg rows
    stamps = _daily_stamps(40, start="2026-09-01")
    n, basis = px._session_bars_held({"name": "pairs_gld_gdx", "symbol_a": "GLD",
                                      "symbol_b": "GDX"}, "alpaca_paper", str(db), stamps)
    assert basis == "leg_rows"
    assert n == sum(1 for t in stamps if t > datetime(2026, 10, 1, 19, 52, tzinfo=timezone.utc))


# ── REVIEW #17747 item 1: paper-only is enforced IN CODE, at runtime ───────

def _real_account(acct_id):
    import yaml
    d = yaml.safe_load(open("config/accounts.yaml", encoding="utf-8"))
    d = d.get("accounts", d)
    return dict(d[acct_id])


@pytest.mark.parametrize("acct_id,refusal", [
    ("alpaca_live", "not_paper"),          # real money
    ("alpaca_portfolio", "stage2_mirror"),  # paper, but the Stage-2 mirror
    ("bybit_2", "not_paper"),
    ("no_such_account", "not_paper"),       # unknown id fails closed
])
def test_tick_refuses_a_pair_routed_to_a_non_soak_account(tmp_path, monkeypatch,
                                                          acct_id, refusal):
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpaca())
    import src.config.accounts_loader as _al
    real = {} if acct_id == "no_such_account" else {acct_id: _real_account(acct_id)}
    monkeypatch.setattr(_al, "load_accounts_dict", lambda *a, **k: real)
    monkeypatch.setattr(px, "_load_pairs_config", lambda path=None: {
        "pairs": [{"name": "pairs_gld_gdx", "account_id": acct_id, "symbol_a": "GLD",
                   "symbol_b": "GDX", "execution": "live", "timeframe": "1d",
                   "leg_tp": "spread_target", **REG}]})
    px._non_paper_alerted.clear()
    for _ in range(3):
        px.run_pairs_tick({})
    assert env["placed"] == [] and env["closes"] == []
    assert [r["event"] for r in env["soak"]] == ["skip_non_paper_account"]
    assert env["soak"][0]["refusal"] == refusal
    crit = [k for a, k in env["alerts"] if a[0] == "pairs_non_paper_account"]
    assert len(crit) == 1                          # one alert, not one per tick


def test_pairs_account_refusal_is_fail_closed():
    assert pv.pairs_account_refusal({"account_class": "paper"}) is None
    assert pv.pairs_account_refusal({"account_class": "paper",
                                     "paper_role": "portfolio"}) == "stage2_mirror"
    assert pv.pairs_account_refusal({"account_class": "real_money"}) == "not_paper"
    assert pv.pairs_account_refusal({}) == "not_paper"
    assert pv.pairs_account_refusal(None) == "not_paper"


# ── REVIEW item 3: the daily-DD switch now also gates NEW Bybit pairs ──────

def _bybit_env(tmp_path, monkeypatch, *, dd_trip):
    from tests.test_pairs_executor import _empty_journal, _extended_spread
    ca, cb = _extended_spread()
    soak, placed = [], []
    monkeypatch.setattr(px, "_load_pairs_config", lambda path=None: {
        "account_id": "bybit_1", "pairs_risk_fraction": 1.0,
        "pairs": [{"name": "pairs_sol_btc", "symbol_a": "SOLUSDT", "symbol_b": "BTCUSDT",
                   "execution": "live", "timeframe": "1h", "hedge_beta": "one"}]})
    monkeypatch.setattr(px, "_fetch_leg",
                        lambda sym, tf, lim, s: (list(ca) if sym == "SOLUSDT" else list(cb), "T1"))
    monkeypatch.setattr(px, "_save_decision_bars", lambda state: None)
    monkeypatch.setattr(px, "_load_decision_bars", lambda: {})
    monkeypatch.setattr(pv, "build_client", lambda acct: object())
    import src.units.accounts.execute as _exec
    monkeypatch.setattr(_exec, "_fetch_balance", lambda *a, **k: 100000.0)
    monkeypatch.setattr(_exec, "execute_pkg",
                        lambda pkg, acct, **k: placed.append(pkg.symbol) or "T")
    import src.core.coordinator as _coord
    monkeypatch.setattr(_coord, "_log_new_order_package", lambda pkg: None)
    import src.units.accounts.qty_legalize as _ql
    monkeypatch.setattr(_ql, "legalize_qty",
                        lambda qty, *, symbol, **k: _ql.LegalizedQty(
                            qty=qty, ok=True, reason="", venue_min=0.001, step=0.001,
                            source="instrument_profile"))
    import src.config.accounts_loader as _al
    monkeypatch.setattr(_al, "load_accounts_dict", lambda *a, **k: {
        "bybit_1": {"exchange": "bybit", "account_class": "paper",
                    "risk": {"risk_pct": 0.015,
                             "daily_dd_switch": {"armed": True, "limit_pct": 0.03}}}})
    import src.utils.paths as _paths
    monkeypatch.setattr(_paths, "trade_journal_db_path", lambda: str(tmp_path / "j.db"))
    _empty_journal(tmp_path / "j.db")
    import src.runtime.pairs_soak as _soak
    monkeypatch.setattr(_soak, "record_pairs_soak", lambda rec: soak.append(rec) or True)
    # Pin the REAL _dd_switch_blocks -> RiskManager.check_dd_switch wiring.
    import src.units.accounts.risk as _risk
    seen = {}

    def _check(self):
        seen["account_id"] = self.account_id
        seen["equity"] = self._live_equity
        return dd_trip
    monkeypatch.setattr(_risk.RiskManager, "check_dd_switch", _check)
    return soak, placed, seen


def test_dd_switch_tripped_blocks_new_bybit_pairs(tmp_path, monkeypatch):
    """BEHAVIOUR CHANGE on the existing Bybit sleeve (intended, PR #17747): a
    tripped account daily-DD switch now refuses NEW pairs on bybit_1 too."""
    soak, placed, seen = _bybit_env(tmp_path, monkeypatch, dd_trip=True)
    px.run_pairs_tick({})
    assert placed == []
    assert soak[0]["event"] == "skip_daily_dd_switch"
    assert seen == {"account_id": "bybit_1", "equity": 100000.0}


def test_dd_switch_untripped_leaves_bybit_pairs_unchanged(tmp_path, monkeypatch):
    soak, placed, _ = _bybit_env(tmp_path, monkeypatch, dd_trip=False)
    px.run_pairs_tick({})
    assert soak[0]["event"] == "open" and placed == ["SOLUSDT", "BTCUSDT"]


# ── REVIEW item 6: half-open cleanup sends nothing outside RTH ─────────────

def _seed_one_open_leg(db):
    import sqlite3
    from tests.test_pairs_executor import _real_trades_ddl
    conn = sqlite3.connect(db)
    conn.execute(_real_trades_ddl())
    conn.execute(
        "INSERT INTO trades (timestamp, symbol, direction, entry_price, position_size, "
        "status, strategy_name, account_id, is_backtest) VALUES (?,?,?,?,?,?,?,?,0)",
        ("2026-10-09T19:52:00+00:00", "GLD", "short", 300.0, 10, "open",
         "pairs_gld_gdx_a", "alpaca_paper"))
    conn.commit()
    conn.close()


@pytest.mark.parametrize("is_open,minutes,clock_ok,expect_closes", [
    (False, 5, True, 0),        # overnight / weekend: nothing sent, every tick
    (True, 300, True, 3),       # RTH (even outside the decision window): cleaned each tick
    (True, 5, False, 0),        # clock unreadable: nothing sent
])
def test_half_open_cleanup_only_sends_in_regular_hours(tmp_path, monkeypatch, is_open,
                                                       minutes, clock_ok, expect_closes):
    env = _session_env(tmp_path, monkeypatch,
                       client=_FakeAlpaca(is_open=is_open, minutes_to_close=minutes,
                                          clock_ok=clock_ok),
                       closer=lambda c, a, *, symbol, side, qty, **k: (
                           env_closes.append((symbol, side, qty)) or {"ok": False,
                                                                     "error": "unfilled"}))
    env_closes: list = []
    (tmp_path / "j.db").unlink()
    _seed_one_open_leg(tmp_path / "j.db")
    px._state_alert_last.clear()
    for _ in range(3):
        px.run_pairs_tick({})
    assert len(env_closes) == expect_closes
    assert env["placed"] == []
    # collapsed-state: half_open — this test SELECTS the half-open soak rows to count their cadence; it decides nothing for the other events, which are asserted elsewhere in this file.
    rows = [r for r in env["soak"] if r["event"] == "half_open"]
    assert len(rows) == 1                                     # cadence: once per hour
    if expect_closes == 0:
        assert rows[0]["cleanup_deferred"] == "market_not_open"
    else:
        assert "cleanup_deferred" not in rows[0]


# ── REVIEW item 7: the decision bar is TODAY's session bar ─────────────────

class _Trades:
    def __init__(self, px_map, age=10.0):
        self.px, self.age = px_map, age

    def latest_trade(self, symbol):
        p = self.px.get(symbol)
        return None if p is None else {"price": p, "age_s": self.age}


def test_ensure_session_bar_forming_bar_present_is_used_as_is():
    st = _stamps_ending(3)
    src, ca, cb, ts = pv.ensure_session_bar("GLD", "GDX", [1.0, 2, 3], [4.0, 5, 6], st,
                                            _clock(True), _Trades({}))
    assert src == "forming_bar" and ts == st and ca == [1.0, 2, 3]


def test_ensure_session_bar_appends_today_from_latest_trade_edt_and_est():
    st = _stamps_ending(3, end="2026-10-09")               # completed bars only (Fri)
    src, ca, cb, ts = pv.ensure_session_bar("GLD", "GDX", [1.0, 2, 3], [4.0, 5, 6], st,
                                            _clock(True), _Trades({"GLD": 301.5, "GDX": 61.2}))
    assert src == "latest_trade"
    assert ca[-1] == 301.5 and cb[-1] == 61.2
    assert ts[-1] == datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)   # EDT midnight
    winter = {"is_open": True, "timestamp": "2026-12-14T20:52:00+00:00",
              "next_close": "2026-12-14T21:00:00+00:00"}
    src, _, _, ts = pv.ensure_session_bar("GLD", "GDX", [1.0], [2.0],
                                          _stamps_ending(1, end="2026-12-11"), winter,
                                          _Trades({"GLD": 1.0, "GDX": 2.0}))
    assert src == "latest_trade" and ts[-1] == datetime(2026, 12, 14, 5, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("trades", [_Trades({"GLD": 301.5}),          # one leg unreadable
                                    _Trades({"GLD": 1.0, "GDX": 2.0}, age=3600.0),  # stale print
                                    object()])                         # no reader at all
def test_ensure_session_bar_stale_when_today_cannot_be_read(trades):
    st = _stamps_ending(3, end="2026-10-09")
    src, ca, _, ts = pv.ensure_session_bar("GLD", "GDX", [1.0, 2, 3], [4.0, 5, 6], st,
                                           _clock(True), trades)
    assert src == "stale" and ts == st and ca == [1.0, 2, 3]


class _FakeAlpacaTrades(_FakeAlpaca):
    def __init__(self, prices, **kw):
        super().__init__(**kw)
        self._prices = prices

    def latest_trade(self, symbol):
        p = self._prices.get(symbol)
        return None if p is None else {"price": p, "age_s": 5.0}


def test_tick_completed_bars_only_decides_on_latest_trade(tmp_path, monkeypatch):
    ca, cb = _jammed(jam=0.15)
    client = _FakeAlpacaTrades({"GLD": ca[-1], "GDX": cb[-1]})
    env = _session_env(tmp_path, monkeypatch, client=client)
    # The fetch ends at the PREVIOUS session; today's bar must come from trades.
    stamps = _stamps_ending(len(ca) - 1, end="2026-10-09")
    monkeypatch.setattr(pv, "fetch_leg_frame",
                        lambda sym, tf, lim, s: ((ca[:-1] if sym == "GLD" else cb[:-1]), stamps))
    px.run_pairs_tick({})
    assert env["soak"][0]["event"] == "open"
    assert env["soak"][0]["decision_bar_source"] == "latest_trade"


def test_tick_completed_bars_only_without_trades_decides_nothing(tmp_path, monkeypatch):
    ca, cb = _jammed(jam=0.15)
    env = _session_env(tmp_path, monkeypatch, client=_FakeAlpacaTrades({}))
    stamps = _stamps_ending(len(ca) - 1, end="2026-10-09")
    monkeypatch.setattr(pv, "fetch_leg_frame",
                        lambda sym, tf, lim, s: ((ca[:-1] if sym == "GLD" else cb[:-1]), stamps))
    px.run_pairs_tick({})
    assert env["soak"] == [] and env["placed"] == []
    assert env["saved"] == []            # bar not consumed: next tick retries
