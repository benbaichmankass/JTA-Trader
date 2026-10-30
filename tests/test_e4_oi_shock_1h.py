"""e4_oi_shock_1h + src/runtime/oi_feed.py (row E4-DEMO-LEG).

The decisive test is PARITY: ``detect_events`` must find exactly the events the frozen replay's E4 branch
(``scripts/research/desk_event_entry_replay.py::detect``, PR #21720) finds on the same rows. The replay's
arithmetic is copied verbatim below as ``_replay_e4`` (numpy, cumulative sums) so the parity holds whether or
not that script is on this tree.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from src.runtime import oi_feed
from src.units.strategies import e4_oi_shock_1h as e4

OI_Z, OI_W, OI_LAG_BARS, OI_COOL_S = 3.0, 2016, 12, 6 * 3600
T0 = 1_760_000_400 - (1_760_000_400 % 3600)   # an hour boundary


def _replay_e4(t: np.ndarray, oi: np.ndarray):
    """The replay's E4 detector loop, verbatim (minus the side, which needs candles): [(known, cutoff)]."""
    ch = np.zeros(len(oi))
    good = (oi[OI_LAG_BARS:] > 0) & (oi[:-OI_LAG_BARS] > 0)
    ch[OI_LAG_BARS:][good] = oi[OI_LAG_BARS:][good] / oi[:-OI_LAG_BARS][good] - 1
    ok = np.zeros(len(oi), bool)
    ok[OI_LAG_BARS:] = good & ((t[OI_LAG_BARS:] - t[:-OI_LAG_BARS]) == 3600)
    cs, cs2 = np.cumsum(ch), np.cumsum(ch ** 2)
    last = -1e18
    out = []
    for i in range(OI_W + OI_LAG_BARS, len(oi)):
        if not ok[i] or t[i] - t[i - OI_W] > 7.5 * 86400:
            continue
        m = (cs[i - 1] - cs[i - OI_W - 1]) / OI_W
        v = (cs2[i - 1] - cs2[i - OI_W - 1]) / OI_W - m * m
        if v <= 0:
            continue
        known = t[i] + 300
        if (ch[i] - m) / math.sqrt(v) >= OI_Z and known - last >= OI_COOL_S:
            out.append((float(known), int(math.ceil(known / 3600) * 3600)))
            last = known
    return out


def _series(n: int = 2600, seed: int = 7, shocks=(2300, 2310, 2400, 2500, 2590), gap_at=None):
    rng = np.random.default_rng(seed)
    t = T0 + 300 * np.arange(n, dtype=np.int64)
    if gap_at is not None:
        t[gap_at:] += 900
    oi = 1e6 * np.exp(np.cumsum(rng.normal(0, 0.0005, n)))
    for s in shocks:
        oi[s:] *= 1.04                                    # a step: the 1h change spikes for 12 rows
    return t, oi


def _rows(t, oi, bf=1):
    return [[int(a), float(b), float(a) + 300, bf] for a, b in zip(t, oi)]


@pytest.mark.parametrize("gap_at", [None, 2350])
def test_detector_matches_the_frozen_replay(gap_at):
    t, oi = _series(gap_at=gap_at)
    ref = _replay_e4(t.astype(float), oi)
    got = [(e["known"], e["cutoff"]) for e in e4.detect_events(_rows(t, oi))]
    assert len(ref) >= 3, "fixture must contain events (a probe that finds nothing proves nothing)"
    assert got == ref


def test_cooldown_and_threshold_are_the_frozen_numbers():
    assert (e4.DEFAULTS["oi_z"], e4.DEFAULTS["oi_window"], e4.DEFAULTS["oi_lag_rows"], e4.DEFAULTS["oi_cooldown_s"]) == (
        OI_Z, OI_W, OI_LAG_BARS, OI_COOL_S)
    assert (e4.DEFAULTS["sl_atr"], e4.DEFAULTS["tp_r"] * e4.DEFAULTS["sl_atr"], e4.DEFAULTS["horizon_bars"]) == (1.5, 3.0, 24)


def test_config_block_equals_the_frozen_rule():
    import yaml
    cfg = yaml.safe_load(open("config/strategies.yaml"))["strategies"]["e4_oi_shock_1h"]
    for k in ("oi_z", "oi_window", "oi_lag_rows", "oi_cooldown_s", "atr_period", "sl_atr", "tp_r", "horizon_bars"):
        assert float(cfg[k]) == float(e4.DEFAULTS[k]), k
    assert sorted(cfg["symbols"]) == ["ADAUSDT", "AVAXUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    assert cfg["execution"] == "live" and cfg["decision_bar"] == "closed"
    accts = yaml.safe_load(open("config/accounts.yaml"))["accounts"]
    on = sorted(a for a, v in accts.items() if "e4_oi_shock_1h" in (v.get("strategies") or []))
    assert on == ["bybit_1"], "E4 is approved for the bybit_1 DEMO only"


# ----------------------------------------------------------------------------- known_at (point in time)
def test_known_at_rule_time_when_held_by_the_decision():
    ts = T0 - 300                                  # rule known_at = T0 (the cutoff)
    assert oi_feed.known_at([ts, 1.0, T0 + 30, 0]) == T0
    assert oi_feed.known_at([ts, 1.0, T0 + oi_feed.DECISION_WAIT_S + 1, 0]) == T0 + oi_feed.DECISION_WAIT_S + 1
    assert oi_feed.known_at([ts, 1.0, T0 + 9999, 1]) == T0      # backfill keeps the rule time


def test_a_row_seen_late_rolls_to_the_next_cutoff():
    t, oi = _series(shocks=(2590,))
    rows = _rows(t, oi, bf=0)
    ev = e4.detect_events(rows)[-1]
    i = next(k for k, r in enumerate(rows) if r[0] == ev["ts"])
    rows[i][2] = ev["cutoff"] + oi_feed.DECISION_WAIT_S + 60
    late = [e for e in e4.detect_events(rows) if e["ts"] == ev["ts"]][0]
    assert late["cutoff"] == ev["cutoff"] + 3600


# ----------------------------------------------------------------------------- order package + monitor
def _frame(closes, end_open):
    n = len(closes)
    ts = [pd.Timestamp(end_open - 3600 * (n - 1 - k), unit="s", tz="UTC") for k in range(n)]
    c = np.array(closes, float)
    return pd.DataFrame({"timestamp": ts, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c})


def _event_rows_at(cutoff):
    t, oi = _series(shocks=(2590,))
    ev = e4.detect_events(_rows(t, oi))[-1]
    shift = cutoff - ev["cutoff"]
    return _rows(t + shift, oi), ev["z"]


@pytest.mark.parametrize("last,direction", [(101.0, "long"), (99.0, "short")])
def test_order_package_side_and_frozen_bracket(last, direction):
    cutoff = T0 + 100 * 3600
    rows, _z = _event_rows_at(cutoff)
    closes = [100.0] * 30 + [last]
    df = _frame(closes, cutoff - 3600)
    pkg = e4.order_package({"symbol": "BTCUSDT"}, candles_df=df, oi_rows=rows)
    assert pkg["direction"] == direction
    atr = pkg["meta"]["atr14"]
    side = 1 if direction == "long" else -1
    assert pkg["entry"] == last
    assert pkg["sl"] == pytest.approx(last - side * 1.5 * atr)
    assert pkg["tp"] == pytest.approx(last + side * 3.0 * atr)
    assert pkg["meta"]["decision_cutoff"] == cutoff
    assert pkg["meta"]["time_stop_at"] == cutoff + 24 * 3600


def test_atr_is_the_replay_sma_of_true_range():
    closes = [100.0 + k for k in range(20)]
    df = _frame(closes, T0)
    h, lo, c = df["high"].tolist(), df["low"].tolist(), df["close"].tolist()
    trs = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, 20)]
    assert e4.atr_sma(h, lo, c, 14) == pytest.approx(sum(trs[-14:]) / 14)


def test_no_event_at_this_cutoff_and_flat_bar_are_not_actionable():
    cutoff = T0 + 100 * 3600
    rows, _ = _event_rows_at(cutoff)
    with pytest.raises(ValueError, match="no_e4_event_at_cutoff"):
        e4.order_package({}, candles_df=_frame([100.0] * 30 + [101.0], cutoff), oi_rows=rows)
    with pytest.raises(ValueError, match="flat_last_bar"):
        e4.order_package({}, candles_df=_frame([100.0] * 31, cutoff - 3600), oi_rows=rows)


def test_monitor_time_stop(monkeypatch):
    pkg = {"meta": {"time_stop_at": T0 + 86400}}
    monkeypatch.setattr(e4, "_now", lambda: T0 + 86400 - 1)
    assert e4.monitor({}, None, pkg) is None
    monkeypatch.setattr(e4, "_now", lambda: T0 + 86400)
    assert e4.monitor({}, None, pkg) == {"action": "close", "reason": "e4_time_stop_24h"}
    assert e4.monitor({}, None, {"meta": "garbage"}) is None


def test_monitor_verdict_is_schema_valid():
    from src.runtime.strategy_verdict import validate_verdict
    validate_verdict({"action": "close", "reason": "e4_time_stop_24h"})


# ----------------------------------------------------------------------------- the feed
class _Venue:
    """A fake Bybit open-interest endpoint: newest first, at most `limit` rows ending at endTime."""

    def __init__(self, now, n=3000, fail=False):
        self.rows = [((int(now) // 300) * 300 - 300 * k, 1e6 + k) for k in range(n)]
        self.fail, self.calls = fail, 0

    def __call__(self, url, timeout):
        from urllib.parse import parse_qs, urlparse
        self.calls += 1
        if self.fail:
            raise OSError("down")
        q = parse_qs(urlparse(url).query)
        lim = int(q["limit"][0])
        end = int(q["endTime"][0]) // 1000 if "endTime" in q else 1e18
        sel = [r for r in self.rows if r[0] <= end][:lim]
        return {"retCode": 0, "result": {"list": [{"timestamp": str(a * 1000), "openInterest": str(b)} for a, b in sel]}}


def test_refresh_warms_up_from_venue_history_and_grades_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("OI_FEED_DIR", str(tmp_path))
    oi_feed._LAST_REFRESH.clear()
    now = float(T0 + 120)
    v = _Venue(now)
    st = oi_feed.refresh("BTCUSDT", now=now, getter=v)
    assert st["read_state"] == "fresh" and st["warm"] is True
    assert st["span_s"] >= oi_feed.WARMUP_S
    assert all(r[3] == 1 for r in st["rows"])            # history fetched after the fact = backfill
    doc = json.loads((tmp_path / "status.json").read_text())
    assert doc["symbols"]["BTCUSDT"]["read_state"] == "fresh"
    # next refresh: one small page, new rows are LIVE with their first-seen time
    v.rows.insert(0, (v.rows[0][0] + 300, 2e6))
    st2 = oi_feed.refresh("BTCUSDT", now=now + 300, getter=v, force=True)
    newest = st2["rows"][-1]
    assert newest[3] == 0 and newest[2] == now + 300


def test_refresh_failure_is_could_not_look_never_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("OI_FEED_DIR", str(tmp_path))
    oi_feed._LAST_REFRESH.clear()
    st = oi_feed.refresh("ETHUSDT", now=float(T0), getter=_Venue(T0, fail=True))
    assert st["read_state"] == "could_not_look" and st["n_rows"] == 0 and "down" in st["last_error"]


def test_stale_store_is_graded_stale():
    rows = [[T0 - 3600, 1.0, T0 - 3300, 0]]
    assert oi_feed.grade(rows, T0 + 60, None)["read_state"] == "stale"


def test_merge_first_sight_wins():
    rows = [[100, 1.0, 50.0, 0]]
    assert oi_feed.merge(rows, [(100, 9.0), (400, 2.0)], seen=999.0, backfill=False) == 1
    assert rows[0] == [100, 1.0, 50.0, 0] and rows[1] == [400, 2.0, 999.0, 0]


# ----------------------------------------------------------------------------- builder (end to end, mocked venue)
def test_builder_emits_the_e4_package_on_the_cutoff_bar(tmp_path, monkeypatch):
    from src.runtime import strategy_signal_builders as ssb
    import src.runtime.market_data as md
    import time as _time

    cutoff = T0 + 100 * 3600
    rows, _ = _event_rows_at(cutoff)
    monkeypatch.setenv("OI_FEED_DIR", str(tmp_path))
    monkeypatch.setattr(oi_feed, "refresh", lambda sym, now=None: {"rows": rows, "read_state": "fresh", "newest_age_s": 1})
    monkeypatch.setattr(_time, "time", lambda: cutoff + 30.0)
    monkeypatch.setattr(ssb, "_closed_window_skip", lambda *a, **k: None)
    monkeypatch.setattr(ssb, "_build_killzone_exchange", lambda s: None)
    df = _frame([100.0] * 30 + [101.0, 102.0], cutoff)       # last row = the forming bar
    monkeypatch.setattr(md, "fetch_candles", lambda *a, **k: df)
    monkeypatch.setattr(ssb, "_decision_frame", lambda d, *a, **k: (d.iloc[:-1], None))
    monkeypatch.setattr(ssb, "_record_closed_decision", lambda *a, **k: None)
    monkeypatch.setattr(ssb, "_closed_catchup_age", lambda *a, **k: None)
    sig = ssb.e4_oi_shock_1h_signal_builder({"SYMBOL": "BTCUSDT"})
    assert sig["side"] == "buy", sig.get("meta")
    assert sig["meta"]["strategy_name"] == "e4_oi_shock_1h"
    assert sig["meta"]["decision_cutoff"] == cutoff
    line = json.loads((tmp_path / "e4_decisions.jsonl").read_text().splitlines()[-1])
    assert line["decision"] == "buy" and line["cutoff"] == cutoff


def test_builder_is_registered_once_in_the_intent_roster():
    from src.runtime.intent_multiplexer import _default_intent_builders
    from src.runtime.intents import DEFAULT_PRIORITIES
    from src.runtime.strategy_signal_builders import e4_oi_shock_1h_signal_builder
    assert _default_intent_builders()["e4_oi_shock_1h"] is e4_oi_shock_1h_signal_builder
    assert DEFAULT_PRIORITIES["e4_oi_shock_1h"] == 0
