"""The batched, cached refresher changes TIMING only, never a decision (row ML-EQ-ENTRY-TIMING, Tier 2; operator 2026-11-11 "Approve the fix").

REPLAY: one synthetic venue (extended-hours 1h bars, an in-progress partial bar, a sparse symbol, a split that re-adjusts history mid-replay, a symbol
the batch answers rate-limited once) serves BOTH paths at every decision close over ~1 month (2026-10-06..2026-11-06, 2 closes a day):

* OLD -- ``refresh_once`` with ``get_ohlcv(limit=LIMIT_BARS)`` per symbol (the pre-change pass);
* NEW -- ``refresh_batched`` through ``BarCache`` (multi-symbol incremental reads, a restart that reloads the cache from disk mid-replay).

The snapshot FILES must be byte-identical at every close, and the scored decisions (``ml_entry_eq.score_pool`` on the real struct artifact) equal.
PLANTED: with the overlap check disabled the same replay DIVERGES at the split -- so the replay can see a difference when there is one.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.exchange import alpaca_connector as AC  # noqa: E402
from src.runtime import ml_entry_eq_features as F  # noqa: E402
from src.runtime import ml_entry_eq_refresher as R  # noqa: E402

POOL = ["SPY"] + [f"E{i}" for i in range(13)] + ["SPARSE", "SPLIT", "FLAKY"]
SPLIT_AT = pd.Timestamp("2026-10-20T13:00:00Z")          # from this instant the venue serves SPLIT's history re-adjusted 2:1


class Venue:
    """Alpaca-shaped answers from one synthetic tape; only bars that exist at ``now`` are visible, the in-progress bar partially."""

    def __init__(self, seed=7):
        rng = np.random.default_rng(seed)
        days = pd.bdate_range("2025-12-01", "2026-12-31", tz="America/New_York")
        rows = {}
        for s in POOL:
            ts, px = [], []
            p = 100.0 + rng.uniform(-30, 30)
            for d in days:
                hours = range(9, 16) if s == "SPARSE" else range(4, 20)      # SPARSE: RTH only, with gaps
                for h in hours:
                    if s == "SPARSE" and rng.uniform() < 0.15:
                        continue
                    t = (d + pd.Timedelta(hours=h)).tz_convert("UTC")
                    p *= float(np.exp(rng.normal(0, 0.004)))
                    ts.append(t)
                    px.append(p)
            px = np.array(px)
            o = np.round(px * (1 + rng.normal(0, 0.001, len(px))), 2)
            c = np.round(px, 2)
            hi = np.round(np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, len(px)))), 2)
            lo = np.round(np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, len(px)))), 2)
            v = rng.integers(1_000, 900_000, len(px))
            rows[s] = pd.DataFrame({"t": ts, "o": o, "h": hi, "l": lo, "c": c, "v": v})
        self.rows = rows
        self.now = None
        self.flaky_once = True
        self.multi_calls = 0
        self.single_calls = 0

    def _visible(self, s):
        df = self.rows[s]
        now = self.now
        done = df[df["t"] + pd.Timedelta(hours=1) <= now].copy()
        if s == "SPLIT" and now >= SPLIT_AT:
            pre = done["t"] < SPLIT_AT
            for k in ("o", "h", "l", "c"):
                done.loc[pre, k] = np.round(done.loc[pre, k] / 2, 2)
            done.loc[pre, "v"] = done.loc[pre, "v"] * 2
        cur = df[(df["t"] <= now) & (df["t"] + pd.Timedelta(hours=1) > now)].copy()
        if len(cur):                                     # the in-progress bar: a different close and a fraction of the volume
            cur["c"] = np.round(cur["c"] * 1.003, 2)
            cur["v"] = cur["v"] // 3
        return pd.concat([done, cur], ignore_index=True)

    @staticmethod
    def _dicts(df):
        return [{"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": float(o), "h": float(h), "l": float(lo), "c": float(c), "v": int(v)}
                for t, o, h, lo, c, v in zip(df["t"], df["o"], df["h"], df["l"], df["c"], df["v"])]

    # AlpacaMarketData surface
    def get_ohlcv(self, symbol, timeframe="1h", limit=100):
        self.single_calls += 1
        df = self._visible(symbol)
        df = df[df["t"] >= R._window_start(self.now)].iloc[-int(limit):]
        return AC._bars_frame(self._dicts(df)) if len(df) else None

    def get_bars_multi(self, symbols, timeframe, start, chunk=100):
        self.multi_calls += 1
        frames, states = {}, {}
        st = pd.Timestamp(start)
        for s in symbols:
            if s == "FLAKY" and self.flaky_once:
                self.flaky_once = False
                states[s] = "rate_limited"
                continue
            df = self._visible(s)
            df = df[df["t"] >= st]
            if len(df):
                frames[s] = AC._bars_frame(self._dicts(df))
                states[s] = "ok"
            else:
                states[s] = "empty"
        return frames, states


def _closes(start="2026-10-01", end="2026-11-12"):
    out = []
    for d in pd.bdate_range(start, end, tz="America/New_York"):
        for h in range(10, 17):
            c = (d + pd.Timedelta(hours=h)).tz_convert("UTC")
            if F.is_decision_close(c):
                out.append(c)
    return out


def _replay(tmp_path, merge=None, start="2026-10-06", end="2026-11-06"):
    venue = Venue()
    old_p, new_p = tmp_path / "old" / "s.json", tmp_path / "new" / "s.json"
    cache_p = tmp_path / "new" / "bar_cache.pkl"
    cache = R.BarCache(venue, cache_p, sleep=lambda _x: None)
    if merge is not None:
        cache._merge = merge.__get__(cache)
    closes = _closes(start, end)
    diverged, n = [], 0
    for i, c in enumerate(closes):
        now = c + pd.Timedelta(seconds=R.SETTLE_S + 7)
        venue.now = now
        if i == len(closes) // 2:                         # a trader restart: the cache comes back from disk
            cache = R.BarCache(venue, cache_p, sleep=lambda _x: None)
            if merge is not None:
                cache._merge = merge.__get__(cache)
        a = R.refresh_once(POOL, lambda s: venue.get_ohlcv(s, "1h", limit=R.LIMIT_BARS), now, old_p, sleep=lambda _x: None, pace_s=0.0)
        b = R.refresh_batched(POOL, cache, now, new_p)
        n += 1
        if old_p.read_bytes() != new_p.read_bytes() or a["missing"] != b["missing"]:
            diverged.append((str(c), a["missing"], b["missing"]))
    return n, diverged, venue, closes


def test_replay_snapshots_are_byte_identical_and_decisions_equal(tmp_path):
    n, diverged, venue, closes = _replay(tmp_path)
    assert n >= 40, n                                     # population: every decision close 2026-10-06..2026-11-06 (2 a day)
    assert diverged == [], diverged[:3]
    # the cache really was used: after the seed, a pass is one multi-symbol call plus the few per-symbol fallbacks (split, flaky)
    assert venue.multi_calls <= 2 * n + 2
    assert venue.single_calls - n * len(POOL) <= 6, venue.single_calls - n * len(POOL)

    # decisions: the real struct artifact scores the last close's snapshots identically (they are the same bytes; scored anyway)
    from src.units.strategies import ml_entry_eq as L
    cfg = {"structure_exit": "pivot=5;sl_only", "artifact": "ml/candidates/ml_entry_eq_v3_struct_ens5/model.json", "session": None}
    old = json.loads((tmp_path / "old" / "s.json").read_text())
    new = json.loads((tmp_path / "new" / "s.json").read_text())
    assert set(POOL) - set(old["symbols"]) <= {"SPARSE"}      # only the gappy symbol may lack this close's bar
    syms = list(old["symbols"])
    assert json.dumps(L.score_pool(cfg, old, syms), sort_keys=True, default=str) == json.dumps(L.score_pool(cfg, new, syms), sort_keys=True, default=str)


def test_planted_no_overlap_check_diverges_at_the_split(tmp_path):
    def _blind_merge(self, old, new):                     # the cache WITHOUT its overlap comparison: trusts stale history
        if new is None or len(new) == 0:
            return None
        first = new["timestamp"].iloc[0]
        keep = old[old["timestamp"] < first]
        return pd.concat([keep, new], ignore_index=True).drop_duplicates("timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)
    _n, diverged, _v, _c = _replay(tmp_path, merge=_blind_merge, start="2026-10-15", end="2026-10-23")
    assert diverged, "the replay must detect a cache that keeps pre-split history"
    assert pd.Timestamp(diverged[0][0]) >= SPLIT_AT


def test_window_start_is_the_connectors_lookback(monkeypatch):
    from datetime import datetime, timezone
    fixed = datetime(2026, 11, 12, 16, 2, 37, tzinfo=timezone.utc)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed
    monkeypatch.setattr(AC, "datetime", _DT)
    assert R._window_start(pd.Timestamp(fixed)) == pd.Timestamp(AC._lookback_start("1h", R.LIMIT_BARS))


def test_cache_falls_back_per_symbol_when_the_batch_fails(tmp_path):
    class Down:
        def __init__(self):
            self.single = []

        def get_bars_multi(self, symbols, timeframe, start, chunk=100):
            return {}, {s: "rate_limited" for s in symbols}

        def get_ohlcv(self, s, timeframe="1h", limit=100):
            self.single.append(s)
            return None if s == "GONE" else pd.DataFrame({"timestamp": pd.to_datetime(["2026-11-12T15:00:00Z"]), "open": [1.0], "high": [1.0],
                                                           "low": [1.0], "close": [1.0], "volume": [1]})
    md = Down()
    c = R.BarCache(md, tmp_path / "c.pkl", sleep=lambda _x: None)
    st = c.update(["A", "B", "GONE"], pd.Timestamp("2026-11-12T16:02:30Z"))
    assert md.single == ["A", "B", "GONE"] and st["per_symbol"] == 3 and st["covered"] == 2
    assert c.get("GONE") is None and c.get("A") is not None


def test_a_bad_cache_file_is_a_reseed_not_a_crash(tmp_path):
    p = tmp_path / "c.pkl"
    p.write_bytes(b"not a pickle")
    c = R.BarCache(object(), p)
    assert c.frames == {} and c.seeded_at is None


@pytest.mark.parametrize("now,ref_close,want", [
    ("2026-11-12T15:10:00Z", "2026-11-11T20:00:00Z", (16 * 60 + 2.5 - (15 * 60 + 10)) * 60),   # sleeps to 16:02:30, not a free 240 s
    ("2026-11-12T15:58:00Z", "2026-11-11T20:00:00Z", 270.0),                                   # 16:02:30 is 4.5 min away -> POLL_S cap
    ("2026-11-12T16:03:00Z", "2026-11-11T20:00:00Z", float(R.FAST_POLL_S)),                    # past close+settle, bar not seen yet -> fast poll
    ("2026-11-12T16:03:00Z", "2026-11-12T16:00:00Z", float(R.POLL_S)),                         # pass's close seen -> normal cadence
    ("2026-11-12T00:03:00Z", "2026-11-11T20:00:00Z", float(R.POLL_S)),                         # 00:00Z is not an RTH close -> no fast poll
])
def test_next_sleep_is_close_aligned(now, ref_close, want):
    got = R.next_sleep_s(pd.Timestamp(now), pd.Timestamp(ref_close))
    assert got == min(float(R.POLL_S), want)


def test_aligned_wake_lands_exactly_on_close_plus_settle():
    now = pd.Timestamp("2026-11-12T19:31:00Z")
    t = now
    for _ in range(20):                                    # follow the loop's sleeps until it wakes past 20:00
        t = t + pd.Timedelta(seconds=R.next_sleep_s(t, pd.Timestamp("2026-11-12T16:00:00Z")))
        if t >= pd.Timestamp("2026-11-12T20:00:00Z"):
            break
    assert t == pd.Timestamp("2026-11-12T20:00:00Z") + pd.Timedelta(seconds=R.SETTLE_S)
