"""DESK-18-GEN-REPLAY-S0: the entry-generation replay driver.

Synthetic candles throughout (no network): fill / exit semantics, the cost stack, no look-ahead in both
directions, the mask, the weekly-cluster bootstrap, the transplanted random-entry geometry, scorer-assigned
novelty, proposal intake, the registered rule, and one CLI round trip (packets -> proposals -> score).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))
sys.path.insert(0, str(REPO / "scripts" / "ci"))

import check_desk_records as cdr  # noqa: E402
import desk_scan_packet as dsp  # noqa: E402
from scripts.research import desk_gen_replay_driver as drv  # noqa: E402
from src.runtime import execution_costs as xc  # noqa: E402

T0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
SEC = 3600


def _series(rows, prefix=20, atr=1.0, fee=7.5, slip=3.0, fund=1.0, symbol="ETHUSDT", pad=12):
    """`prefix` quiet bars at 100, then `rows` (o, h, l, c), then `pad` quiet bars at the last close so a path
    reaches its full horizon (a path that does not is `unresolved`, by design). ATR is a constant `atr`."""
    rows = list(rows)
    last = rows[-1][3] if rows else 100.0
    allrows = [(100.0, 100.5, 99.5, 100.0)] * prefix + rows + [(last, last + 0.2, last - 0.2, last)] * pad
    n = len(allrows)
    a = np.array(allrows, dtype=float)
    return drv.Series(symbol, np.array([T0 + i * SEC for i in range(n)], dtype=np.int64), a[:, 0], a[:, 1], a[:, 2],
                      a[:, 3], np.full(n, atr), fee, slip, fund)


def _walk_df(n, seed, start=100.0, vol=0.005):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0.0, vol, n)))
    open_ = np.concatenate([[start], close[:-1]])
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    ts = pd.date_range("2025-05-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": hi, "low": lo, "close": close})


@pytest.fixture(scope="module")
def candles_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("candles")
    n = int((datetime(2026, 10, 1, tzinfo=timezone.utc) - datetime(2025, 5, 1, tzinfo=timezone.utc)).total_seconds() // SEC)
    for k, s in enumerate(drv.REGISTERED_SYMBOLS):
        _walk_df(n, 100 + k).to_csv(d / f"{s}_1h.csv", index=False)
    return d


@pytest.fixture(scope="module")
def market(candles_dir):
    mkt, missing = drv.load_market(candles_dir, drv.REGISTERED_SYMBOLS)
    assert not missing
    return mkt


# ----------------------------------------------------------------------------- the replay engine
class TestSimulate:
    def test_market_long_hits_tp_and_pays_the_cost_stack(self):
        s = _series([(100.2, 103.5, 99.9, 103.0)])
        t = drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5)
        assert t.state == "filled" and t.reason == "tp"
        risk = 100.2 - 98.0
        gross = (103.0 - 100.2) / risk
        cost = xc.roundtrip_cost_r(entry=100.2, exit_price=103.0, risk=risk, entry_time=datetime.fromtimestamp(T0 + 20 * SEC, tz=timezone.utc).isoformat(),
                                   exit_time=datetime.fromtimestamp(T0 + 21 * SEC, tz=timezone.utc).isoformat(),
                                   fee_bps_roundtrip=7.5, slippage_bps_roundtrip=3.0, funding_bps_per_window=1.0)["total_cost_r"]
        assert t.gross_r == pytest.approx(gross) and t.cost_r == pytest.approx(cost) and cost > 0
        assert t.net_r == pytest.approx(gross - cost)
        assert t.days == pytest.approx(1 / 24)

    def test_short_is_symmetric(self):
        s = _series([(99.8, 100.1, 96.5, 97.0)])
        t = drv.simulate(s, 19, -1.0, "market", 100.0, 102.0, 97.0, 1, 5)
        assert t.state == "filled" and t.reason == "tp"
        assert t.gross_r == pytest.approx((99.8 - 97.0) / (102.0 - 99.8))

    def test_stop_is_checked_before_target_inside_a_bar(self):
        s = _series([(100.0, 104.0, 97.5, 101.0)])      # both levels inside one bar
        t = drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5)
        assert t.reason == "sl" and t.exit_px == 98.0 and t.gross_r < 0

    def test_gap_through_the_stop_fills_at_the_open(self):
        s = _series([(100.0, 100.4, 99.6, 100.0), (96.0, 96.5, 95.0, 95.5)])
        t = drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5)
        assert t.reason == "gap_sl" and t.exit_px == 96.0 and t.gross_r == pytest.approx((96.0 - 100.0) / 2.0)

    def test_gap_through_the_target_fills_at_the_open(self):
        s = _series([(100.0, 100.4, 99.6, 100.0), (105.0, 106.0, 104.5, 105.5)])
        t = drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5)
        assert t.reason == "gap_tp" and t.exit_px == 105.0

    def test_time_stop_exits_at_the_close_of_the_horizon_bar(self):
        s = _series([(100.0, 100.4, 99.6, 100.2)] * 6)
        t = drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 4)
        assert t.reason == "timeout" and t.exit_i == t.fill_i + 3 and t.exit_px == 100.2

    def test_data_end_is_unresolved_not_a_loss(self):
        s = _series([(100.0, 100.4, 99.6, 100.2)] * 2, pad=0)
        assert drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 10).state == "unresolved"   # horizon runs off the data
        assert drv.simulate(s, 21, 1.0, "market", 100.0, 98.0, 103.0, 1, 10).state == "unresolved"   # no bar after the cutoff

    def test_limit_needs_price_to_trade_through_the_level(self):
        touch = _series([(100.0, 100.4, 99.0, 99.6)] + [(100.0, 100.4, 99.6, 100.0)] * 6)
        assert drv.simulate(touch, 19, 1.0, "limit", 99.0, 97.0, 102.0, 3, 5).state == "unfilled"   # low == level: a touch
        through = _series([(100.0, 100.4, 98.9, 99.6)] + [(100.0, 100.4, 99.6, 100.0)] * 6)
        t = drv.simulate(through, 19, 1.0, "limit", 99.0, 97.0, 102.0, 3, 5)
        assert t.state == "filled" and t.fill_px == 99.0

    def test_limit_gap_below_fills_at_the_open(self):
        s = _series([(98.0, 98.5, 97.8, 98.2)] + [(98.2, 98.6, 98.0, 98.4)] * 6)
        t = drv.simulate(s, 19, 1.0, "limit", 99.0, 96.0, 101.0, 3, 5)
        assert t.state == "filled" and t.fill_px == 98.0

    def test_a_limit_fill_bar_credits_no_target_but_does_check_the_stop(self):
        s = _series([(100.0, 104.0, 98.9, 103.0)] + [(103.0, 103.2, 102.8, 103.0)] * 6)   # fills, and a TP-sized high in the same bar
        t = drv.simulate(s, 19, 1.0, "limit", 99.0, 97.0, 103.0, 3, 5)
        assert t.state == "filled" and t.reason != "tp" and t.fill_i == 20
        s2 = _series([(100.0, 100.4, 96.9, 99.0)] + [(99.0, 99.2, 98.8, 99.0)] * 6)
        assert drv.simulate(s2, 19, 1.0, "limit", 99.0, 97.0, 103.0, 3, 5).reason == "sl"

    def test_stop_entry_fills_through_the_level_at_the_worse_of_level_and_open(self):
        s = _series([(101.5, 102.0, 101.0, 101.8)] + [(101.8, 102.2, 101.6, 102.0)] * 6)
        t = drv.simulate(s, 19, 1.0, "stop", 101.0, 99.0, 104.0, 2, 5)
        assert t.state == "filled" and t.fill_px == 101.5

    def test_unfilled_limit_expires(self):
        s = _series([(100.0, 100.4, 99.6, 100.0)] * 8)
        t = drv.simulate(s, 19, 1.0, "limit", 95.0, 93.0, 99.0, 3, 5)
        assert t.state == "unfilled" and t.reason == "expired"

    def test_refusals_are_counted_not_priced(self):
        s = _series([(97.9, 98.3, 97.6, 98.0)] + [(98.0, 98.4, 97.8, 98.0)] * 6)
        assert drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5).state == "refused"        # opens through the stop
        tight = _series([(100.0, 100.4, 99.6, 100.0)] * 8)
        assert drv.simulate(tight, 19, 1.0, "market", 100.0, 99.95, 103.0, 1, 5).reason == "risk"      # < 0.1 ATR
        passed = _series([(104.0, 104.5, 103.8, 104.2)] + [(104.2, 104.6, 104.0, 104.3)] * 6)
        assert drv.simulate(passed, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5).reason == "tp_passed"

    def test_zero_cost_on_a_filled_trade_raises_rather_than_reading_as_free(self):
        s = _series([(100.2, 103.5, 99.9, 103.0)], fee=0.0, slip=0.0, fund=0.0)
        with pytest.raises(AssertionError, match="zero cost"):
            drv.simulate(s, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5)

    def test_replay_reads_only_bars_after_the_cutoff(self):
        rows = [(100.2, 103.5, 99.9, 103.0)] + [(103.0, 103.4, 102.8, 103.1)] * 5
        a = _series(rows)
        b = _series(rows)
        for arr in (b.o, b.h, b.l, b.c):
            arr[:19] = arr[:19] * 3.0             # garble everything BEFORE the cutoff bar
        ta = drv.simulate(a, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5)
        tb = drv.simulate(b, 19, 1.0, "market", 100.0, 98.0, 103.0, 1, 5)
        assert drv._same_outcome(ta, tb)


# ----------------------------------------------------------------------------- schedule, folds
class TestSchedule:
    def test_deterministic_and_gapped_and_inside_the_window(self):
        a, b = drv.make_schedule(n=200), drv.make_schedule(n=200)
        assert a == b and len(a) == 200 and len(set(a)) == 200
        s = sorted(a)
        assert min(y - x for x, y in zip(s, s[1:])) >= drv.MIN_GAP_H * SEC
        assert drv._epoch(drv.WINDOW_START) <= s[0] and s[-1] < drv._epoch(drv.WINDOW_END)
        assert all(c % SEC == 0 for c in a)

    def test_a_prefix_of_a_long_schedule_is_the_short_schedule(self):
        assert drv.make_schedule(n=500)[:60] == drv.make_schedule(n=60)

    def test_the_registered_length_is_reachable(self):
        assert len(drv.make_schedule()) == drv.SCHEDULE_LEN

    def test_folds_partition_the_window_evenly(self):
        s = drv.make_schedule()
        counts = [sum(1 for c in s if drv.fold_of(c) == f) for f in range(1, drv.N_FOLDS + 1)]
        assert sum(counts) == len(s) and min(counts) > 0.2 * len(s)
        assert drv.fold_of(drv._epoch(drv.WINDOW_START)) == 1 and drv.fold_of(drv._epoch(drv.WINDOW_END) - SEC) == drv.N_FOLDS


# ----------------------------------------------------------------------------- packets: no look-ahead, the mask
class TestPackets:
    def _cutoff(self, market):
        return drv.make_schedule(n=5)[2]

    def test_future_bars_cannot_move_a_packet(self, market):
        ce = self._cutoff(market)
        classes = {s: ["paper"] for s in market}
        a, _ = drv.build_masked_packet(market, classes, ce, 3)
        shocked = {}
        for s, ser in market.items():
            j = ser.last_closed(ce)
            arrs = [x.copy() for x in (ser.o, ser.h, ser.l, ser.c)]
            for x in arrs:
                x[j + 1:] = x[j + 1:] * 3.0
            shocked[s] = drv.Series.from_bars(s, [{"time": int(ser.t[i]), "open": float(arrs[0][i]), "high": float(arrs[1][i]),
                                                    "low": float(arrs[2][i]), "close": float(arrs[3][i])} for i in range(len(ser.t))])
        b, _ = drv.build_masked_packet(shocked, classes, ce, 3)
        assert cdr.packet_sha(a) == cdr.packet_sha(b)

    def test_trimming_the_lookback_equals_handing_the_builder_every_bar(self, market):
        ce = self._cutoff(market)
        uni = [{"symbol": s, "venue": "bybit", "classes": ["paper"]} for s in sorted(market)]
        full = {s: market[s].bars(0, len(market[s].t) - 1) for s in market}
        trimmed = {}
        for s in market:
            i = market[s].last_closed(ce)
            trimmed[s] = market[s].bars(i - (drv.LOOKBACK + max(drv.HORIZONS) + dsp.ATR_PERIOD + 5), i)
        kw = dict(cutoff=datetime.fromtimestamp(ce, tz=timezone.utc), tf="1h", universe=uni, horizons=drv.HORIZONS,
                  lookback=drv.LOOKBACK, system_book=None, desk_book=None)
        pa = dsp.build_scan_packet(candles=full, built_at=kw["cutoff"], **kw)
        pb = dsp.build_scan_packet(candles=trimmed, built_at=kw["cutoff"], **kw)
        assert cdr.packet_sha(pa) == cdr.packet_sha(pb)

    def test_aliases_are_redrawn_per_packet(self, market):
        ce = self._cutoff(market)
        classes = {s: ["paper"] for s in market}
        maps = {tuple(sorted(drv.build_masked_packet(market, classes, ce, k)[1]["alias"].items())) for k in range(6)}
        assert len(maps) > 1

    def test_masked_packet_passes_the_guard_and_the_leak_scan(self, market):
        ce = self._cutoff(market)
        m, key = drv.build_masked_packet(market, {s: ["paper"] for s in market}, ce, 0)
        assert dsp.validate(m) == []
        assert m["meta"]["mode"] == "historical_masked" and m["system_book"]["read_state"] == "could_not_look"
        assert drv.leak_scan(json.dumps(m, sort_keys=True), key, sorted(market)) == []

    def test_leak_scan_finds_a_planted_symbol_date_and_price(self, market):
        ce = self._cutoff(market)
        m, key = drv.build_masked_packet(market, {s: ["paper"] for s in market}, ce, 0)
        bad = json.loads(json.dumps(m))
        alias = bad["universe"][0]["symbol"]
        bad["meta"]["note"] = f"{key['alias'][alias]} {datetime.fromtimestamp(ce, tz=timezone.utc):%Y-%m-%d}"
        bad["universe"][0]["last_close"] = round(100.0 / key["price_scale"][alias], 4)
        found = drv.leak_scan(json.dumps(bad), key, sorted(market))
        assert any("symbol token" in f for f in found) and any("cutoff date" in f for f in found) \
            and any("equals the real price" in f for f in found)

    def test_a_missing_symbol_file_is_named_not_an_empty_series(self, tmp_path, candles_dir):
        (tmp_path / "ETHUSDT_1h.csv").write_text((candles_dir / "ETHUSDT_1h.csv").read_text())
        mkt, missing = drv.load_market(tmp_path, ["ETHUSDT", "BTCUSDT"])
        assert list(mkt) == ["ETHUSDT"] and missing == ["BTCUSDT"]


# ----------------------------------------------------------------------------- statistics
class TestClusterStats:
    def _rows(self, weeks=40, per=10, rho_shared=0.0, seed=1):
        rng = np.random.default_rng(seed)
        rows = []
        for w in range(weeks):
            shared = rng.normal(0, 1)
            for _ in range(per):
                x = rho_shared * shared + rng.normal(0, 1)
                rows.append({"week": f"2026-W{w:02d}", "net_r": x, "days": 1.0, "diff": x - 0.1})
        return rows

    def test_known_means_and_per_capital_day(self):
        rows = [{"week": "W1", "net_r": 1.0, "days": 0.5, "diff": 0.5}, {"week": "W1", "net_r": -0.5, "days": 0.5, "diff": None},
                {"week": "W2", "net_r": 2.0, "days": 1.0, "diff": 1.0}]
        st = drv.cluster_stats(rows, draws=500)
        assert st["n"] == 3 and st["mean_net_r"] == pytest.approx(2.5 / 3)
        assert st["net_r_per_capital_day"] == pytest.approx(2.5 / 2.0) and st["capital_days"] == pytest.approx(2.0)
        assert st["n_paired"] == 2 and st["paired_diff_vs_random"] == pytest.approx(0.75)

    def test_clustering_widens_the_interval_when_a_week_shares_a_market(self):
        flat = drv.cluster_stats(self._rows(rho_shared=0.0), draws=2000)
        shared = drv.cluster_stats(self._rows(rho_shared=2.0), draws=2000)
        w_flat = flat["mean_ci95"][1] - flat["mean_ci95"][0]
        w_shared = shared["mean_ci95"][1] - shared["mean_ci95"][0]
        assert w_shared > 1.5 * w_flat

    def test_deterministic_under_the_seed_and_empty_is_not_a_zero(self):
        a, b = drv.cluster_stats(self._rows(), draws=300), drv.cluster_stats(self._rows(), draws=300)
        assert a == b and drv.cluster_stats([]) == {"n": 0, "weeks": 0}

    def test_required_n_is_the_designs_arithmetic(self):
        assert drv.required_n(1.0, 0.10) == 784 and drv.required_n(1.0, 0.20) == 196
        assert drv.required_n(float("nan"), 0.1) is None


# ----------------------------------------------------------------------------- random-entry geometry
class TestRandomEntry:
    def test_geometry_round_trips_at_its_own_cutoff(self, market):
        ser = market["ETHUSDT"]
        i = int(drv.eligible_cutoffs(ser, drv.WINDOW_START, drv.WINDOW_END)[400])
        a = float(ser.atr[i])
        lvl, stp, tpl = float(ser.c[i]) - 0.4 * a, float(ser.c[i]) - 1.9 * a, float(ser.c[i]) + 1.2 * a
        t1 = drv.simulate(ser, i, 1.0, "limit", lvl, stp, tpl, 3, 12)
        g = drv.geometry_of(ser, i, 1.0, "limit", lvl, stp, tpl, 3, 12)
        t2 = drv.transplant(ser, i, g)
        assert drv._same_outcome(t1, t2) and g["offset_atr"] == pytest.approx(0.4)

    def test_geometry_is_scale_free_so_it_moves_to_another_symbol(self, market):
        a, b = market["ETHUSDT"], market["SOLUSDT"]
        g = {"side": -1.0, "etype": "market", "offset_atr": 0.0, "sl_atr": 1.5, "tp_atr": 3.0, "good_till": 1, "horizon": 12}
        i = int(drv.eligible_cutoffs(b, drv.WINDOW_START, drv.WINDOW_END)[100])
        t = drv.transplant(b, i, g)
        assert t is not None and t.state in ("filled", "refused")
        assert a.symbol != b.symbol

    def test_baseline_is_random_not_the_cutoff_itself(self, market):
        ser = market["BTCUSDT"]
        g = {"side": 1.0, "etype": "market", "offset_atr": 0.0, "sl_atr": 1.5, "tp_atr": 3.0, "good_till": 1, "horizon": 24}
        pool = drv.eligible_cutoffs(ser, drv.WINDOW_START, drv.WINDOW_END, 2)
        assert len(pool) > 500
        r1 = drv.random_baseline(ser, g, pool, np.random.default_rng(1), 100)
        r2 = drv.random_baseline(ser, g, pool, np.random.default_rng(2), 100)
        assert r1["n"] > 90 and r1["mean"] != r2["mean"]
        assert drv.random_baseline(ser, g, np.array([], dtype=int), np.random.default_rng(1), 10)["mean"] is None


# ----------------------------------------------------------------------------- novelty
class TestNovelty:
    def _leg(self, symbol="ETHUSDT", start=1000, end=10_000_000, trades=None, tf=7200):
        trades = trades or []
        return drv.LegList("leg_x", symbol, tf, start, end, trades, {}, [drv._t(t["entry_time"]) for t in trades],
                           [drv._t(t["exit_time"]) for t in trades])

    def _trade(self, direction, e, x):
        f = lambda s: datetime.fromtimestamp(s, tz=timezone.utc).isoformat()   # noqa: E731
        return {"direction": direction, "entry_time": f(e), "exit_time": f(x), "net_r": 0.1}

    def test_every_state(self):
        c = 100_000
        legs = [self._leg(trades=[self._trade("long", c - 3600, c + 3600), self._trade("short", c + 3600, c + 9000),
                                  self._trade("long", c + 20_000, c + 30_000)])]
        ros = {"ETHUSDT": {"leg_x"}, "SOLUSDT": set()}
        assert drv.classify_novelty("ETHUSDT", 1.0, c, legs, ros) == "duplicates_system_package"      # a long is open
        assert drv.classify_novelty("ETHUSDT", -1.0, c, legs, ros) == "duplicates_near_signal"        # a short enters within 1 bar
        assert drv.classify_novelty("ETHUSDT", 1.0, c + 5_000, legs, ros) == "new"                    # nothing open, nothing within a bar
        assert drv.classify_novelty("SOLUSDT", 1.0, c, legs, ros) == "new_no_leg"                     # no ROSTERED leg trades the symbol
        assert drv.classify_novelty("ETHUSDT", 1.0, 5, legs, ros) == "unclassifiable"                 # outside every evidence window

    def test_new_is_claimed_only_when_every_rostered_leg_was_looked_at(self):
        c = 100_000
        legs = [self._leg(trades=[self._trade("long", c - 3600, c + 3600)])]
        two = {"ETHUSDT": {"leg_x", "leg_without_a_list"}}
        assert drv.classify_novelty("ETHUSDT", -1.0, c, legs, two) == "unclassifiable"               # one rostered leg is unseen
        assert drv.classify_novelty("ETHUSDT", 1.0, c, legs, two) == "duplicates_system_package"      # a positive is still a positive

    def test_rostered_legs_are_read_from_config(self):
        r = drv.rostered_legs(drv.REGISTERED_SYMBOLS)
        assert set(r) == set(drv.REGISTERED_SYMBOLS) and all(isinstance(v, set) for v in r.values())
        assert "xrp_pullback_2h" in r["XRPUSDT"] and "ada_pullback_2h" in r["ADAUSDT"]

    def test_the_desk_leg_is_not_part_of_the_strategies_book(self):
        # claude_desk is rostered on every replay symbol and has no Stage-0 list: left in, nothing is ever `new`
        r = drv.rostered_legs(drv.REGISTERED_SYMBOLS)
        assert all("claude_desk" not in names for names in r.values())
        legs, gaps = drv.load_strategy_lists(r)
        assert not any(g.startswith("claude_desk") for g in gaps)

    def test_a_rostered_leg_without_a_record_is_a_named_gap(self):
        legs, gaps = drv.load_strategy_lists({"BTCUSDT": {"no_such_leg_xyz"}})
        assert legs == [] and any("no_such_leg_xyz" in g and "no committed evidence record" in g for g in gaps)

    def test_strategy_own_table_counts_only_the_window(self):
        s0 = drv._epoch(drv.WINDOW_START)
        legs = [self._leg(trades=[self._trade("long", s0 + 100, s0 + 7300), self._trade("long", s0 - 100, s0 + 7300)])]
        t = drv.strategy_own_table(legs, drv.WINDOW_START, drv.WINDOW_END)
        assert t["pooled"]["n"] == 1 and t["per_leg"][0]["n"] == 1


# ----------------------------------------------------------------------------- proposal intake
def _proposal(alias, **kw):
    pr = {"symbol": alias, "venue_class": "masked:perp", "side": "long", "timeframe": "1h", "horizon_bars": 12,
          "entry": {"type": "market", "level": 100.0, "good_till_bars": 1}, "stop": {"level": 98.5, "basis": "swing_level"},
          "tp": {"level": 103.0, "basis": "swing_level", "p_hit": 0.4}, "expected_r_net": 0.2, "thesis": "t",
          "novelty": "unverifiable", "onboarding": "onboarded"}
    pr.update(kw)
    return pr


class TestIntake:
    def _packets(self, market):
        ce = drv.make_schedule(n=3)
        pk, keys = {}, {}
        for k, c in enumerate(ce):
            m, key = drv.build_masked_packet(market, {s: ["paper"] for s in market}, c, k)
            pk[m["meta"]["packet_id"]] = m
            keys[m["meta"]["packet_id"]] = key
        return pk, keys

    def _write(self, tmp_path, rows):
        f = tmp_path / "p.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return f

    def test_valid_refused_capped_and_unknown(self, market, tmp_path):
        pk, keys = self._packets(market)
        pid = next(iter(pk))
        alias = pk[pid]["universe"][0]["symbol"]
        alias2 = pk[pid]["universe"][1]["symbol"]
        alias3 = pk[pid]["universe"][2]["symbol"]
        rows = [
            {"packet_id": pid, "action": "propose_entry", "proposal": _proposal(alias), "judge_prior": 0.4},
            {"packet_id": pid, "action": "propose_entry", "proposal": _proposal(alias), "judge_prior": 0.4},                     # duplicate symbol
            {"packet_id": pid, "action": "propose_entry", "proposal": _proposal(alias2, tp={"level": 190.0, "basis": "swing_level", "p_hit": 0.4}), "judge_prior": 0.4},   # TP sentinel
            {"packet_id": pid, "action": "propose_entry", "proposal": _proposal(alias3), "judge_prior": 0.4},
            {"packet_id": pid, "action": "propose_entry", "proposal": _proposal(pk[pid]["universe"][3]["symbol"]), "judge_prior": 0.4},   # over the cap of 2
            {"packet_id": pid, "action": "propose_entry", "proposal": _proposal(alias, novelty="new"), "judge_prior": 0.4},       # novelty is the scorer's
        ]
        by, acc = drv.read_proposals(self._write(tmp_path, rows), pk)
        assert [r["proposal"]["symbol"] for r in by[pid]] == [alias, alias3]
        assert acc["refused"] == 2 and acc["duplicate_symbol"] == 1 and acc["over_cap"] == 1
        assert any("TP doctrine" in k for k in acc["refused_reasons"])
        with pytest.raises(ValueError, match="not in the packets file"):
            drv.read_proposals(self._write(tmp_path, [{"packet_id": "P-nope", "action": "no_trade"}]), pk)
        with pytest.raises(ValueError, match="no_trade|propose_entry"):
            drv.read_proposals(self._write(tmp_path, [{"packet_id": pid, "action": "buy"}]), pk)

    def test_enums_and_novelty_are_checked_against_the_schema(self, market, tmp_path):
        pk, _ = self._packets(market)
        pid = next(iter(pk))
        alias = pk[pid]["universe"][0]["symbol"]
        rows = [{"packet_id": pid, "action": "propose_entry", "judge_prior": 0.4,
                 "proposal": _proposal(alias, stop={"level": 98.5, "basis": "vibes"})},
                {"packet_id": pid, "action": "propose_entry", "judge_prior": 0.4,
                 "proposal": _proposal(pk[pid]["universe"][1]["symbol"], novelty="new")}]
        by, acc = drv.read_proposals(self._write(tmp_path, rows), pk)
        assert by[pid] == [] and acc["refused"] == 2
        assert any("closed enum" in k for k in acc["refused_reasons"]) and any("unverifiable" in k for k in acc["refused_reasons"])

    def test_a_row_missing_fields_is_refused_not_a_crash(self, market, tmp_path):
        pk, _ = self._packets(market)
        pid = next(iter(pk))
        rows = [{"packet_id": pid, "action": "propose_entry", "proposal": {"symbol": "ASSET_01"}, "judge_prior": 0.4}]
        by, acc = drv.read_proposals(self._write(tmp_path, rows), pk)
        assert by[pid] == [] and acc["refused"] == 1


# ----------------------------------------------------------------------------- the registered rule
def _stats(**kw):
    st = {"n": 300, "mean_net_r": 0.25, "mean_ci95": [0.05, 0.45], "net_r_per_capital_day": 1.2,
          "per_capital_day_ci95": [0.2, 2.2], "paired_diff_vs_random": 0.30, "paired_diff_ci95": [0.10, 0.50],
          "folds_positive": 3, "post_cutoff": {"state": "measured", "n": 80, "mean": 0.2}}
    st.update(kw)
    return st


class TestRule:
    def test_pass_and_its_labels(self):
        v, why = drv.grade_arm(_stats(), n_min=200, selfcheck=True, label="all")
        assert v == "pass" and any("forward-shadow" in w for w in why) and any("+0.10 R" in w for w in why)
        v2, why2 = drv.grade_arm(_stats(n=900), n_min=200, selfcheck=True, label="all")
        assert v2 == "pass" and not any("+0.10 R" in w for w in why2)

    @pytest.mark.parametrize("change,verdict", [
        ({"n": 150}, "indeterminate"),
        ({"mean_ci95": [-0.1, 0.5]}, "indeterminate"),
        ({"net_r_per_capital_day": -0.1, "per_capital_day_ci95": [-0.5, 0.1]}, "indeterminate"),
        ({"paired_diff_ci95": [-0.05, 0.4]}, "indeterminate"),
        ({"folds_positive": 2}, "indeterminate"),
        ({"post_cutoff": {"state": "measured", "n": 80, "mean": -0.1}}, "indeterminate"),
        ({"post_cutoff": {"state": "could_not_look", "n": 0, "mean": None}}, "indeterminate"),
        ({"mean_net_r": -0.1, "mean_ci95": [-0.3, 0.1]}, "fail"),
        ({"mean_net_r": 0.2, "mean_ci95": [-0.4, -0.01]}, "fail"),
        ({"paired_diff_vs_random": -0.2, "paired_diff_ci95": [-0.4, -0.05]}, "fail"),
    ])
    def test_each_clause_bites(self, change, verdict):
        assert drv.grade_arm(_stats(**change), n_min=200, selfcheck=True, label="all")[0] == verdict

    def test_a_thin_post_cutoff_stratum_does_not_block_but_is_labelled(self):
        v, why = drv.grade_arm(_stats(post_cutoff={"state": "measured", "n": 10, "mean": -1.0}), n_min=200, selfcheck=True, label="all")
        assert v == "pass" and any("post-cutoff n < 20" in w for w in why)

    def test_without_a_passing_selfcheck_nothing_is_a_verdict(self):
        assert drv.grade_arm(_stats(), n_min=200, selfcheck=None, label="all")[0] == "indeterminate"
        assert drv.grade_arm(_stats(), n_min=200, selfcheck=False, label="all")[0] == "indeterminate"

    def test_the_subset_floor_is_lower(self):
        assert drv.grade_arm(_stats(n=120), n_min=drv.N_MIN_NEW, selfcheck=True, label="new")[0] == "pass"
        assert drv.grade_arm(_stats(n=120), n_min=drv.N_MIN_ALL, selfcheck=True, label="all")[0] == "indeterminate"


# ----------------------------------------------------------------------------- the instrument gates (unit 01)
class TestSelfcheckParts:
    def test_the_newest_landed_run_is_found_and_none_is_not_a_pass(self, tmp_path):
        for run, v in (("100", "fail"), ("2000", "pass"), ("999", "fail")):
            (tmp_path / "RQ-X" / run).mkdir(parents=True)
            (tmp_path / "RQ-X" / run / "verdict.json").write_text(json.dumps({"verdict": v}))
        (tmp_path / "RQ-X" / "notes").mkdir()
        (tmp_path / "RQ-X" / "notes" / "verdict.json").write_text("{}")
        got = drv.latest_verdict_path("RQ-X", tmp_path)
        assert got.parent.name == "2000" and json.loads(got.read_text())["verdict"] == "pass"
        assert drv.latest_verdict_path("RQ-NONE", tmp_path) is None and drv.latest_verdict_path(None, tmp_path) is None

    def test_cost_fidelity_matches_a_list_priced_by_the_same_function_and_catches_a_perturbed_one(self):
        fee, slip, fund = dsp.cost_policy("ETHUSDT")
        e, sl, g = 100.0, 98.0, 1.5
        px = e + g * 2.0
        et, xt = "2026-03-02T00:00:00+00:00", "2026-03-02T09:00:00+00:00"
        c = xc.roundtrip_cost_r(entry=e, exit_price=px, risk=2.0, entry_time=et, exit_time=xt, fee_bps_roundtrip=fee,
                                slippage_bps_roundtrip=slip, funding_bps_per_window=fund)

        def leg(off):
            t = {"entry": e, "sl": sl, "gross_r": g, "direction": "long", "entry_time": et, "exit_time": xt,
                 "cost_fee_r": c["fee_r"], "cost_slippage_r": c["slippage_r"] + off, "cost_funding_r": c["funding_r"], "net_r": 0.0}
            return drv.LegList("x", "ETHUSDT", 7200, 0, 1, [t], {"fees": fee, "slippage": slip, "funding": fund}, [], [])

        ok = drv.cost_fidelity([leg(0.0)])
        bad = drv.cost_fidelity([leg(0.05)])
        assert ok["n_compared"] == 1 and ok["max_abs_dev_R"] < 1e-9
        assert bad["max_abs_dev_R"] == pytest.approx(0.05)

    def test_a_leg_priced_on_another_policy_is_excluded_and_named(self):
        t = {"entry": 100.0, "sl": 98.0, "gross_r": 1.0, "direction": "long", "entry_time": "2026-03-02T00:00:00+00:00",
             "exit_time": "2026-03-02T09:00:00+00:00", "cost_fee_r": 0.1, "cost_slippage_r": 0.1, "cost_funding_r": 0.1, "net_r": 0.0}
        out = drv.cost_fidelity([drv.LegList("y", "ETHUSDT", 7200, 0, 1, [t], {"fees": 99.0, "slippage": 99.0, "funding": 99.0}, [], [])])
        assert out["n_compared"] == 0 and out["legs_excluded_policy_differs"] == 1

    def test_missing_candles_make_the_selfcheck_indeterminate_not_a_pass(self):
        r = drv.selfcheck({}, ["BTCUSDT"], [], [], {})
        assert r["verdict"] == "indeterminate" and "BTCUSDT" in r["note"]

    def test_oracle_and_anti_oracle_are_separated_on_synthetic_candles(self, market):
        cuts = drv.make_schedule(n=400)[:120]
        orc = drv.cluster_stats(drv._policy_oracle(market, cuts, (1.5, 2.0, 24), "oracle", np.random.default_rng(1)), 7, 1000)
        anti = drv.cluster_stats(drv._policy_oracle(market, cuts, (1.5, 2.0, 24), "anti", np.random.default_rng(1)), 7, 1000)
        assert orc["mean_net_r"] > 0 > anti["mean_net_r"]
        assert orc["paired_diff_ci95"][0] > 0 and anti["paired_diff_ci95"][1] < 0


# ----------------------------------------------------------------------------- end to end
class TestRoundTrip:
    def test_score_unmasks_the_levels_and_replays_them_on_the_real_path(self, market, candles_dir, tmp_path):
        out = tmp_path / "pk"
        assert drv.main(["packets", "--out", str(out), "--candles-dir", str(candles_dir), "--n", "6"]) == 0
        packets = {r["packet_id"]: r["packet"] for r in map(json.loads, (out / "packets.jsonl").read_text().splitlines())}
        keys = {k["packet_id"]: k for k in json.loads((out / "mask-key.json").read_text())["keys"]}
        assert len(packets) == 6 and "packet" not in json.dumps(json.loads((out / "mask-key.json").read_text()))[:0]
        rows, expect = [], []
        for n, (pid, p) in enumerate(packets.items()):
            alias = p["universe"][0]["symbol"]
            if n % 2:
                rows.append({"packet_id": pid, "action": "no_trade"})
                continue
            rows.append({"packet_id": pid, "action": "propose_entry", "judge_prior": 0.4,
                         "proposal": _proposal(alias, stop={"level": 98.0, "basis": "swing_level"},
                                               tp={"level": 103.0, "basis": "swing_level", "p_hit": 0.4})})
            key = keys[pid]
            sym, sc = key["alias"][alias], key["price_scale"][alias]
            ser = market[sym]
            i = ser.last_closed(key["cutoff_epoch"])
            expect.append(drv.simulate(ser, i, 1.0, "market", 100.0 / sc, 98.0 / sc, 103.0 / sc, 1, 12))
        pf = tmp_path / "proposals.jsonl"
        pf.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        sc_v = tmp_path / "sc.json"
        sc_v.write_text(json.dumps({"verdict": "pass"}))
        res_dir = tmp_path / "res"
        assert drv.main(["score", "--out", str(res_dir), "--candles-dir", str(candles_dir), "--proposals", str(pf),
                         "--packets", str(out / "packets.jsonl"), "--mask-key", str(out / "mask-key.json"), "--subset", "all",
                         "--selfcheck-verdict", str(sc_v), "--model-cutoff", "2026-06-01"]) == 0
        v = json.loads((res_dir / "verdict.json").read_text())
        m = v["measurement"]
        want = [t for t in expect if t.state == "filled"]
        assert m["stats"]["n"] == len(want) and v["verdict"] == "indeterminate"             # n << 200: never a verdict
        assert m["intake"]["no_trade"] == 3 and m["intake"]["propose_entry"] == 3 and m["n_packets_judged"] == 6
        if want:
            assert m["stats"]["mean_net_r"] == pytest.approx(float(np.mean([t.net_r for t in want])))
        assert sum(m["counts"]["novelty"].values()) == 3

    def test_score_without_packets_rederives_them_and_verifies_the_sha(self, candles_dir, tmp_path, capsys):
        out = tmp_path / "pk3"
        assert drv.main(["packets", "--out", str(out), "--candles-dir", str(candles_dir), "--n", "4"]) == 0
        packets = {r["packet_id"]: r["packet"] for r in map(json.loads, (out / "packets.jsonl").read_text().splitlines())}
        rows = [{"packet_id": pid, "action": "no_trade"} for pid in packets]
        pf = tmp_path / "pr.jsonl"
        pf.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        args = ["score", "--candles-dir", str(candles_dir), "--proposals", str(pf), "--mask-key", str(out / "mask-key.json"), "--subset", "all"]
        assert drv.main(args + ["--out", str(tmp_path / "ok")]) == 0
        v = json.loads((tmp_path / "ok" / "verdict.json").read_text())
        assert v["measurement"]["n_packets_judged"] == 4 and v["measurement"]["intake"]["no_trade"] == 4 and v["verdict"] == "indeterminate"
        # candle drift between the judge's run and the score run is refused, not silently re-priced
        key = json.loads((out / "mask-key.json").read_text())
        key["keys"][0]["packet_sha"] = "0" * 64
        (out / "mask-key.json").write_text(json.dumps(key))
        capsys.readouterr()
        assert drv.main(args + ["--out", str(tmp_path / "bad")]) == 2
        assert "differ from what the judge saw" in capsys.readouterr().out

    def _judged(self, candles_dir, tmp_path, keep, n=6, propose=True, extra=(), withhold=()):
        out = tmp_path / "pkd"
        assert drv.main(["packets", "--out", str(out), "--candles-dir", str(candles_dir), "--n", str(n)]) == 0
        if withhold:                                    # a packet withheld at build time (mask leak) has no key
            kf = json.loads((out / "mask-key.json").read_text())
            kf["keys"] = [k for k in kf["keys"] if k["index"] not in withhold]
            (out / "mask-key.json").write_text(json.dumps(kf))
        packets = [json.loads(r) for r in (out / "packets.jsonl").read_text().splitlines()]
        keys = {k["packet_id"]: k for k in json.loads((out / "mask-key.json").read_text())["keys"]}
        rows = []
        for r in packets:
            if r["packet_id"] not in keys or keys[r["packet_id"]]["index"] not in keep:
                continue
            alias = r["packet"]["universe"][0]["symbol"]
            rows.append({"packet_id": r["packet_id"], "action": "propose_entry", "judge_prior": 0.4, "proposal": _proposal(alias)} if propose
                        else {"packet_id": r["packet_id"], "action": "no_trade"})
        pf = tmp_path / "pr.jsonl"
        pf.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        res = tmp_path / "res"
        sc = tmp_path / "sc.json"
        sc.write_text(json.dumps({"verdict": "pass"}))
        assert drv.main(["score", "--out", str(res), "--candles-dir", str(candles_dir), "--proposals", str(pf), "--mask-key",
                         str(out / "mask-key.json"), "--selfcheck-verdict", str(sc), "--model-cutoff", "2026-06-01", *extra]) == 0
        return json.loads((res / "verdict.json").read_text())["measurement"]

    def test_a_leak_withheld_index_is_not_a_skipped_packet(self, candles_dir, tmp_path):
        # judged-1 withheld indices 406 and 805: no key, never offered to a judge; the rest was judged in full
        m = self._judged(candles_dir, tmp_path, keep={0, 1, 3, 4, 5}, withhold={2})
        assert m["design"]["is_schedule_prefix"] is True and m["design"]["stopping_rule_respected"] is True
        assert m["design"]["packets_judged"] == 5

    def test_judged_1_shape_is_a_respected_prefix_and_exhausts_the_schedule(self):
        held = {406, 805}
        keyed = [i for i in range(drv.SCHEDULE_LEN) if i not in held]
        d = drv.stopping_design(keyed, keyed, [i for i in keyed if i % 2 == 0][:732])
        assert d["packets_judged"] == 1498 and d["is_schedule_prefix"] is True
        assert d["schedule_exhausted"] is True and d["stopping_rule_respected"] is True
        assert drv.stopping_design([i for i in keyed if i != 100], keyed, [])["is_schedule_prefix"] is False

    def test_a_keyed_packet_left_unjudged_is_still_not_a_prefix(self, candles_dir, tmp_path):
        m = self._judged(candles_dir, tmp_path, keep={0, 1, 3, 4, 5}, withhold=())
        assert m["design"]["is_schedule_prefix"] is False

    def test_filled_counts_every_fill_before_the_subset_filter(self, candles_dir, tmp_path):
        m = self._judged(candles_dir, tmp_path, keep={0, 1, 2, 3, 4, 5}, extra=("--subset", "new"))
        c = m["counts"]
        assert c["excluded_by_subset"] > 0                                         # the real rostered legs make some cells non-new
        assert c["filled"] == c["filled_in_subset"] + c["excluded_by_subset"] and c["filled"] > 0
        assert m["fill_rate"] == pytest.approx(c["filled"] / c["proposals_valid"])

    def test_judged_packets_that_are_not_a_schedule_prefix_are_not_scored_as_a_verdict(self, candles_dir, tmp_path):
        m = self._judged(candles_dir, tmp_path, keep={0, 2, 3})                 # packet 1 skipped
        assert m["design"]["is_schedule_prefix"] is False and m["design"]["stopping_rule_respected"] is False
        assert m["verdict"] == "indeterminate" and "stopping rule" in m["reasons"][0]

    def test_judging_past_the_registered_stop_is_flagged(self, candles_dir, tmp_path, monkeypatch):
        monkeypatch.setattr(drv, "BATCH", 2)
        monkeypatch.setattr(drv, "STOP_PROPOSALS", 1)
        m = self._judged(candles_dir, tmp_path, keep={0, 1, 2, 3, 4, 5})
        assert m["design"]["is_schedule_prefix"] is True and m["design"]["valid_proposals_before_last_batch"] >= 1
        assert m["design"]["stopping_rule_respected"] is False and m["verdict"] == "indeterminate"

    def test_intake_mode_counts_valid_proposals_without_replaying_anything(self, candles_dir, tmp_path, capsys):
        out = tmp_path / "pki"
        assert drv.main(["packets", "--out", str(out), "--candles-dir", str(candles_dir), "--n", "5"]) == 0
        packets = [json.loads(r) for r in (out / "packets.jsonl").read_text().splitlines()]
        rows = [{"packet_id": r["packet_id"], "action": "propose_entry", "judge_prior": 0.4, "proposal": _proposal(r["packet"]["universe"][0]["symbol"])}
                for r in packets[:3]] + [{"packet_id": r["packet_id"], "action": "no_trade"} for r in packets[3:]]
        pf = tmp_path / "pr.jsonl"
        pf.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        capsys.readouterr()
        assert drv.main(["intake", "--out", str(tmp_path / "unused"), "--candles-dir", str(candles_dir), "--proposals", str(pf),
                         "--mask-key", str(out / "mask-key.json")]) == 0
        got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert got["packets_judged"] == 5 and got["valid_proposals_total"] == 3 and got["is_schedule_prefix"] is True
        assert got["next_batch_allowed"] is True and got["intake"]["no_trade"] == 2
        assert not (tmp_path / "unused").exists()                                   # nothing was written, nothing was replayed

    def test_a_clean_prefix_respects_the_rule(self, candles_dir, tmp_path):
        m = self._judged(candles_dir, tmp_path, keep={0, 1, 2, 3, 4, 5})
        assert m["design"]["stopping_rule_respected"] is True and m["design"]["packets_judged"] == 6

    def test_packets_mode_never_writes_the_key_into_the_packet_file(self, candles_dir, tmp_path):
        out = tmp_path / "pk2"
        assert drv.main(["packets", "--out", str(out), "--candles-dir", str(candles_dir), "--n", "3"]) == 0
        text = (out / "packets.jsonl").read_text()
        key = json.loads((out / "mask-key.json").read_text())
        for k in key["keys"]:
            assert datetime.fromtimestamp(k["cutoff_epoch"], tz=timezone.utc).strftime("%Y-%m-%d") not in text
        assert not any(s in text for s in drv.REGISTERED_SYMBOLS)
        proto = (out / "JUDGE-PROTOCOL.md").read_text()
        assert "unverifiable" in proto and "ASSET" not in key and "%(" not in proto and str(drv.MAX_PER_PACKET) in proto
        assert not any(s in proto for s in drv.REGISTERED_SYMBOLS)

    def test_baselines_mode_measures_every_reference_geometry_on_synthetic_candles(self, candles_dir, tmp_path):
        assert drv.main(["baselines", "--out", str(tmp_path / "b"), "--candles-dir", str(candles_dir)]) == 0
        v = json.loads((tmp_path / "b" / "verdict.json").read_text())
        m = v["measurement"]
        assert set(m["geometries"]) == {g[0] for g in drv.REFERENCE_GEOMETRIES}
        assert all(g["n"] >= drv.BASELINE_N_FLOOR for g in m["geometries"].values())
        assert all(g["mean_cost_r"] > 0 for g in m["geometries"].values())
        assert m["n_required_at_pooled_sd"]["+0.10R"] > m["n_required_at_pooled_sd"]["+0.20R"] > 0
        assert v["data_inputs"] and v["read_state"] == "measured"


# ----------------------------------------------------------------------------- DESK-S3-VOL-MATCHED-BASELINE (driver form)
class TestVolMatchedCompanions:
    def test_matched_pool_is_same_symbol_fold_and_decile_and_never_wider_than_the_fold(self, market):
        ser = market["ETHUSDT"]
        pool = drv.eligible_cutoffs(ser, drv.WINDOW_START, drv.WINDOW_END, 2)
        ap = drv.atr_pct_of(ser)
        i = int(pool[len(pool) // 2])
        mp = drv.vol_matched_pool(ser, pool, i)
        assert 0 < len(mp) < len(pool) and set(mp.tolist()) <= set(pool.tolist())
        allc = drv.eligible_cutoffs(ser, drv.WINDOW_START, drv.WINDOW_END)
        edges = np.quantile(ap[allc], np.linspace(0, 1, 11)[1:-1])
        assert len({int(np.searchsorted(edges, ap[j])) for j in mp}) == 1 == len({int(np.searchsorted(edges, ap[i]))})
        # a pool from another fold yields only that fold's members: matching cannot draw across folds
        other = drv.eligible_cutoffs(ser, drv.WINDOW_START, drv.WINDOW_END, 3)
        assert not set(drv.vol_matched_pool(ser, other, i).tolist()) & set(pool.tolist())

    def test_random_baseline_reports_gross_and_keeps_the_registered_net_mean(self, market):
        ser = market["BTCUSDT"]
        g = {"side": 1.0, "etype": "market", "offset_atr": 0.0, "sl_atr": 1.5, "tp_atr": 3.0, "good_till": 1, "horizon": 24}
        pool = drv.eligible_cutoffs(ser, drv.WINDOW_START, drv.WINDOW_END, 2)
        r = drv.random_baseline(ser, g, pool, np.random.default_rng(1), 100)
        assert r["gross_mean"] > r["mean"]                                           # gross = net + a positive cost
