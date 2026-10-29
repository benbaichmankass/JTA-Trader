"""SINCE-ENTRY-WINDOW-FIX (2026-10-29): the first bar of a trade is not 199 bars.

`exit_levers.since_entry` returned the FULL fetched frame whenever its filter
came back empty. The filter is empty in exactly one, very common case: the
first bar after every entry, when no CLOSED bar yet opens at/after the entry
time. Every caller then treated ~200 PRE-ENTRY bars as the trade:

* position telemetry recorded ``bars_held 199`` and a pre-entry ``peak_r`` —
  SLV slv_trend_1h short pkg-3df9800bf7f04882 (alpaca_paper, opened
  2026-10-29T13:32:37Z) fired a false live-review STALL wake two minutes after
  its fill ("199 bars held >= 12 with peak_r -0.24 < 0.5");
* the chandelier ratchets (trend_donchian, htf_pullback_trend_2h,
  fade_breakout_4h, squeeze_breakout_4h) took their extreme from pre-entry bars,
  so a pre-entry low could TIGHTEN a short's stop (shown below).

What these tests pin:

1. The reproduction — the pre-fix definition (kept verbatim below as a
   reference) yields 199 bars and a pre-entry peak for that exact shape.
2. The fix — with a readable entry time the result is the filtered frame,
   0 or 1 rows in the first bar, and it INCLUDES the bar containing the entry.
3. The fallback survives only when the entry/timestamps are unreadable, and it
   is stamped so telemetry reports ``unanchored``.
4. Every caller degrades a 0/1-row window to "no move / thin_window", never
   raises, never moves a stop.
"""
from __future__ import annotations

import json

import pytest

pd = pytest.importorskip("pandas")

from src.runtime import exit_levers  # noqa: E402
from src.runtime import position_telemetry as pt  # noqa: E402
from src.runtime import trail_decay  # noqa: E402

N_BARS = 200


def _frame(n=N_BARS, last_open="2026-10-29T12:00:00Z", lows=None, freq="1h"):
    """`n` 1h bars whose LAST bar opens at `last_open` (all closed)."""
    ts = pd.date_range(end=last_open, periods=n, freq=freq, tz="UTC")
    lows = lows if lows is not None else [100.0 - 0.5] * n
    return pd.DataFrame({
        "timestamp": ts,
        "open": [lo + 0.5 for lo in lows], "high": [lo + 1.0 for lo in lows],
        "low": lows, "close": [lo + 0.5 for lo in lows], "volume": [1.0] * n,
    })


def _pkg(entry_time="2026-10-29T13:32:37+00:00", entry=100.0, **meta):
    m = {"risk_per_unit": 2.0, "entry_time": entry_time, "timeframe": "1h"}
    m.update(meta)
    return {"order_package_id": "pkg-3df9800bf7f04882", "symbol": "SLV",
            "entry": entry, "sl": 104.0, "tp": 90.0, "direction": "short",
            "account_id": "alpaca_paper", "strategy_name": "slv_trend_1h",
            "meta": m}


def _pre_fix_since_entry(candles_df, open_pkg):
    """The definition before this fix, verbatim — a reference, not a caller."""
    meta = open_pkg.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta) if meta else {}
        except Exception:  # noqa: BLE001
            meta = {}
    entry_ts = (meta.get("entry_time") if isinstance(meta, dict) else None) or \
        open_pkg.get("created_at")
    if entry_ts is None or "timestamp" not in getattr(candles_df, "columns", []):
        return candles_df
    try:
        ts = pd.to_datetime(candles_df["timestamp"], utc=True, errors="coerce")
        cutoff = pd.to_datetime(entry_ts, utc=True, errors="coerce")
        if pd.isna(cutoff):
            return candles_df
        filtered = candles_df[ts >= cutoff]
        return filtered if len(filtered) > 0 else candles_df
    except Exception:  # noqa: BLE001
        return candles_df


# --- 1. THE REPRODUCTION --------------------------------------------------- #

def test_pre_fix_definition_reproduces_the_false_stall():
    """Entry at 13:32 inside a bar that has not closed: the pre-fix window is
    the whole pre-entry frame, so telemetry reads ~200 bars held and a peak
    measured over bars the trade never saw."""
    df = _frame(n=N_BARS, last_open="2026-10-29T12:00:00Z")
    pkg = _pkg()
    old = _pre_fix_since_entry(df, pkg)
    assert len(old) == N_BARS                      # full pre-entry frame
    rec = pt.build_record(open_pkg=pkg, meta=pkg["meta"], window=old,
                          direction="short", current_price=101.15)
    assert rec["bars_held"] == N_BARS
    assert rec["peak_state"] == "measured"         # a pre-entry peak, "measured"

    # The 199 of the incident: the frame also carried the bar CONTAINING the
    # entry (13:00) — excluded by `ts >= cutoff` — so 199 pre-entry bars + 0.
    df2 = _frame(n=N_BARS - 1, last_open="2026-10-29T12:00:00Z")
    assert len(_pre_fix_since_entry(df2, pkg)) == 199


# --- 2. THE FIX ------------------------------------------------------------ #

def test_first_bar_with_no_trade_bar_closed_is_empty_not_the_full_frame():
    df = _frame(last_open="2026-10-29T12:00:00Z")
    w = exit_levers.since_entry(df, _pkg())
    assert len(w) == 0
    assert exit_levers.since_entry_is_anchored(w)


def test_the_bar_that_contains_the_entry_is_included():
    """13:00 bar contains a 13:32 entry: it is the trade's first bar."""
    df = _frame(last_open="2026-10-29T13:00:00Z")
    w = exit_levers.since_entry(df, _pkg())
    assert len(w) == 1
    assert pd.Timestamp(w["timestamp"].iloc[0]) == pd.Timestamp("2026-10-29T13:00:00Z")
    df3 = _frame(last_open="2026-10-29T15:00:00Z")
    assert len(exit_levers.since_entry(df3, _pkg())) == 3   # 13:00, 14:00, 15:00


def test_entry_on_a_bar_boundary_is_unchanged():
    """trend_donchian stamps entry_time = the signal bar's OPEN: same rows as
    the pre-fix `ts >= cutoff` filter whenever that filter was non-empty."""
    df = _frame(last_open="2026-10-29T15:00:00Z")
    pkg = _pkg(entry_time="2026-10-29T13:00:00+00:00")
    new = exit_levers.since_entry(df, pkg)
    old = _pre_fix_since_entry(df, pkg)
    assert list(new["timestamp"]) == list(old["timestamp"])
    assert len(new) == 3


def test_bar_length_is_inferred_when_the_timeframe_is_undeclared():
    df = _frame(last_open="2026-10-29T13:00:00Z")
    pkg = _pkg()
    pkg["meta"].pop("timeframe")
    assert len(exit_levers.since_entry(df, pkg)) == 1


def test_created_at_is_the_anchor_when_entry_time_is_absent():
    df = _frame(last_open="2026-10-29T12:00:00Z")
    pkg = _pkg()
    pkg["meta"].pop("entry_time")
    pkg["created_at"] = "2026-10-29T13:32:37+00:00"
    w = exit_levers.since_entry(df, pkg)
    assert len(w) == 0 and exit_levers.since_entry_is_anchored(w)


def test_the_callers_frame_is_never_mutated():
    df = _frame(last_open="2026-10-29T13:00:00Z")
    exit_levers.since_entry(df, _pkg())
    exit_levers.since_entry(df.drop(columns=["timestamp"]), _pkg())
    assert exit_levers.SINCE_ENTRY_ANCHORED_ATTR not in df.attrs


# --- 3. THE FALLBACK IS ONLY FOR "WE COULD NOT LOOK" ----------------------- #

@pytest.mark.parametrize("mutate", [
    lambda df, pkg: (df.drop(columns=["timestamp"]), pkg),
    lambda df, pkg: (df, {**pkg, "meta": {**pkg["meta"], "entry_time": None}}),
    lambda df, pkg: (df, {**pkg, "meta": {**pkg["meta"], "entry_time": "not-a-time"}}),
    lambda df, pkg: (df.assign(timestamp=["garbage"] * len(df)), pkg),
])
def test_full_frame_fallback_only_when_unreadable_and_it_is_stamped(mutate):
    df, pkg = mutate(_frame(), _pkg())
    w = exit_levers.since_entry(df, pkg)
    assert len(w) == len(df)
    assert not exit_levers.since_entry_is_anchored(w)


def test_telemetry_reports_a_fallback_frame_unanchored_not_measured():
    df, pkg = _frame().drop(columns=["timestamp"]), _pkg()
    w = exit_levers.since_entry(df, pkg)
    rec = pt.build_record(open_pkg=pkg, meta=pkg["meta"], window=w,
                          direction="short", current_price=101.0)
    assert rec["peak_state"] == "unanchored"
    assert rec["peak_r"] is None


def test_a_frame_since_entry_never_touched_keeps_the_callers_claim():
    assert exit_levers.since_entry_is_anchored(pd.DataFrame({"high": [1.0]}))
    assert exit_levers.since_entry_is_anchored(None)


# --- 4. EVERY CALLER DEGRADES A 0/1-ROW WINDOW ----------------------------- #

@pytest.mark.parametrize("last_open,rows", [("2026-10-29T12:00:00Z", 0),
                                            ("2026-10-29T13:00:00Z", 1)])
def test_telemetry_first_bar_is_thin_window_not_199_bars(last_open, rows):
    pkg = _pkg()
    w = exit_levers.since_entry(_frame(last_open=last_open), pkg)
    rec = pt.build_record(open_pkg=pkg, meta=pkg["meta"], window=w,
                          direction="short", current_price=101.15)
    assert rec["bars_held"] == rows
    assert rec["peak_state"] == "thin_window"
    assert rec["peak_r"] is None
    assert rec["open_r"] == pytest.approx(-0.575)


@pytest.mark.parametrize("last_open", ["2026-10-29T12:00:00Z", "2026-10-29T13:00:00Z"])
def test_stale_and_giveback_never_fire_in_the_first_bar(last_open):
    df = _frame(last_open=last_open)
    pkg = _pkg(stale_exit_bars=1, stale_exit_below_r=10.0,
               giveback_min_mfe_r=0.01, giveback_r=0.01)
    for fn in (exit_levers.stale_stop_verdict, exit_levers.giveback_verdict):
        assert fn(pkg["meta"], {}, pkg, df, 103.0, "short") is None


@pytest.mark.parametrize("last_open", ["2026-10-29T12:00:00Z", "2026-10-29T13:00:00Z"])
def test_trail_decay_keeps_the_base_mult(last_open):
    pkg = _pkg(trail_decay_tight_mult=1.0, trail_decay_arm_r=0.01)
    w = exit_levers.since_entry(_frame(last_open=last_open), pkg)
    assert trail_decay.resolve_trail_mult(pkg["meta"], {}, pkg, w, 3.0, "short") == 3.0


def test_momentum_entry_index_is_none_on_an_empty_window():
    from src.runtime.momentum_levers import _entry_index

    assert _entry_index(_frame(last_open="2026-10-29T12:00:00Z"), _pkg()) is None
    assert _entry_index(_frame(last_open="2026-10-29T13:00:00Z"), _pkg()) == N_BARS - 1


def _deep_prior_low_frame():
    """A short entered at 100 two minutes ago; ~150 bars earlier the low was 89.5.
    Pre-fix, the chandelier took that pre-entry low as the trade's extreme."""
    lows = [99.5] * N_BARS
    lows[50] = 89.5
    return _frame(last_open="2026-10-29T12:00:00Z", lows=lows)


@pytest.fixture
def _no_side_writes(monkeypatch):
    """The ratchets also call observe-only telemetry/soak writers; keep the
    test hermetic — they are pinned above, not here."""
    monkeypatch.setattr(pt, "record_position_telemetry", lambda **kw: None)
    from src.runtime import exit_lever_soak
    monkeypatch.setattr(exit_lever_soak, "record_exit_lever_annotation",
                        lambda **kw: None)


def test_pre_fix_window_would_have_tightened_a_short_on_a_pre_entry_low():
    """The money half of the bug: ext 89.5 + 3 x 2 ATR = 95.5 < sl 104 and above
    price 94 — the pre-fix trail moved a real stop off a bar before the entry."""
    w = _pre_fix_since_entry(_deep_prior_low_frame(), _pkg())
    candidate = float(w["low"].min()) + 3.0 * 2.0
    assert candidate < 104.0 and candidate > 94.0


@pytest.mark.usefixtures("_no_side_writes")
def test_donchian_trail_does_not_move_in_the_first_bar():
    from src.units.strategies import trend_donchian as donch

    pkg = _pkg(atr=2.0, trail_mult=3.0, entry_bar_closed=False)
    out = donch._trail_verdict(pkg["meta"], {}, pkg, _deep_prior_low_frame(),
                               94.0, "short", 104.0)
    assert out is None


@pytest.mark.usefixtures("_no_side_writes")
@pytest.mark.parametrize("module", ["fade_breakout_4h", "squeeze_breakout_4h",
                                    "htf_pullback_trend_2h"])
def test_other_trail_units_delegate_and_do_not_move_in_the_first_bar(module):
    import importlib
    import inspect

    unit = importlib.import_module(f"src.units.strategies.{module}")
    assert "exit_levers" in inspect.getsource(unit._since_entry), \
        f"{module} kept a private copy of since_entry"
    assert len(unit._since_entry(_deep_prior_low_frame(), _pkg())) == 0


# --- 5. THE STICKY PRE-ENTRY PEAK (running MAX in write_record) ------------ #

def _telemetry_db(tmp_path):
    import sqlite3

    path = str(tmp_path / "j.db")
    with sqlite3.connect(path) as c:
        c.execute(f"""CREATE TABLE {pt.TABLE} (
            order_package_id TEXT PRIMARY KEY, trade_id TEXT, strategy TEXT,
            symbol TEXT, account_id TEXT, direction TEXT, entry REAL,
            risk_per_unit REAL, last_price REAL, open_r REAL, peak_r REAL,
            peak_state TEXT, giveback_r REAL, bars_held INTEGER,
            bars_since_peak INTEGER, cap_r REAL, pct_of_cap REAL,
            r_to_stop REAL, r_to_target REAL, rr_from_here REAL,
            peak_provenance TEXT, levers TEXT, updated_at TEXT)""")
    return path


def _stored(path):
    import sqlite3

    with sqlite3.connect(path) as c:
        return c.execute(f"SELECT peak_r, bars_held FROM {pt.TABLE}").fetchone()


def _first_bar_then_three_bars(pkg):
    """A short, entry 100 / risk 2. First bar: the pre-fix window (200 pre-entry
    bars, low 89.5 => a 'peak' of 5.25R). Three bars later: the true window,
    whose lows never left 99.5 => a true peak of 0.25R."""
    from datetime import datetime, timezone

    t0 = datetime(2026, 10, 29, 13, 34, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 29, 16, 5, tzinfo=timezone.utc)
    first = pt.build_record(open_pkg=pkg, meta=pkg["meta"],
                            window=_pre_fix_since_entry(_deep_prior_low_frame(), pkg),
                            direction="short", current_price=100.5, now=t0)
    true_w = exit_levers.since_entry(_frame(last_open="2026-10-29T15:00:00Z"), pkg)
    later = pt.build_record(open_pkg=pkg, meta=pkg["meta"], window=true_w,
                            direction="short", current_price=100.5, now=t1)
    return first, later


def test_a_pre_entry_peak_is_sticky_under_the_running_max(tmp_path):
    """(a) Under the running MAX alone (a window that cannot prove it holds the
    whole trade), the pre-entry 5.25R survives every later pass."""
    db = _telemetry_db(tmp_path)
    first, later = _first_bar_then_three_bars(_pkg())
    assert first["bars_held"] == N_BARS and first["peak_r"] == pytest.approx(5.25)
    assert later["peak_r"] == pytest.approx(0.25)
    assert first["peak_authoritative"] == 0               # pre-fix frame proves nothing
    unproven = {**later, "peak_authoritative": 0}
    assert pt.write_record(first, db_path=db)
    assert pt.write_record(unproven, db_path=db)
    assert _stored(db)[0] == pytest.approx(5.25)          # sticky false peak


def test_a_window_holding_the_whole_trade_repairs_the_sticky_peak(tmp_path):
    """(b) The next pass whose window holds the whole trade (anchored, first
    row = the bar containing the entry) replaces the stored peak with its own."""
    db = _telemetry_db(tmp_path)
    first, later = _first_bar_then_three_bars(_pkg())
    assert later["peak_authoritative"] == 1
    assert pt.write_record(first, db_path=db)
    assert pt.write_record(later, db_path=db)
    peak_r, bars = _stored(db)
    assert peak_r == pytest.approx(0.25) and bars == 3


def test_a_genuine_in_trade_peak_survives(tmp_path):
    """Control: a real in-trade peak is inside every later whole-trade window,
    so replacing with the window's peak keeps it."""
    db = _telemetry_db(tmp_path)
    pkg = _pkg()
    lows = [99.5] * N_BARS
    lows[-3] = 95.5                                       # 13:00 bar => 2.25R
    w = exit_levers.since_entry(_frame(last_open="2026-10-29T15:00:00Z", lows=lows), pkg)
    rec = pt.build_record(open_pkg=pkg, meta=pkg["meta"], window=w,
                          direction="short", current_price=100.0)
    assert rec["peak_authoritative"] == 1
    assert pt.write_record(rec, db_path=db) and pt.write_record(rec, db_path=db)
    assert _stored(db)[0] == pytest.approx(2.25)


def test_a_trade_older_than_the_fetch_keeps_the_running_max(tmp_path):
    """A window whose first bar opens AFTER the entry cannot see the whole
    trade, so a lower pass must not walk the stored peak backwards."""
    db = _telemetry_db(tmp_path)
    pkg = _pkg(entry_time="2026-10-01T00:00:00+00:00")
    deep = exit_levers.since_entry(_deep_prior_low_frame(), pkg)
    shallow = exit_levers.since_entry(_frame(last_open="2026-10-29T12:00:00Z"), pkg)
    r1 = pt.build_record(open_pkg=pkg, meta=pkg["meta"], window=deep,
                         direction="short", current_price=100.0)
    r2 = pt.build_record(open_pkg=pkg, meta=pkg["meta"], window=shallow,
                         direction="short", current_price=100.0)
    assert r1["peak_authoritative"] == 0 and r2["peak_authoritative"] == 0
    assert pt.write_record(r1, db_path=db) and pt.write_record(r2, db_path=db)
    assert _stored(db)[0] == pytest.approx(5.25)


def test_window_covers_trade_is_false_when_it_cannot_be_proven():
    assert not pt.window_covers_trade(None, {"entry_time": "2026-10-29T13:00:00Z"})
    assert not pt.window_covers_trade(pd.DataFrame({"high": [1.0]}),
                                      {"entry_time": "2026-10-29T13:00:00Z"})
    w = exit_levers.since_entry(_frame(last_open="2026-10-29T13:00:00Z"), _pkg())
    assert pt.window_covers_trade(w, _pkg()["meta"])
    assert not pt.window_covers_trade(w, {})


def test_an_unstamped_frame_never_counts_as_the_whole_trade():
    """The pre-fix frame (no since_entry stamp) starts before the entry, which
    is exactly why 'first row <= entry' alone is not proof."""
    pkg = _pkg()
    assert not pt.window_covers_trade(_pre_fix_since_entry(_deep_prior_low_frame(), pkg),
                                      pkg["meta"])


def test_the_donchian_trail_window_keeps_the_stamp():
    """The real telemetry path: `_trail_window` (closed bars, entry-bar re-price)
    must still read as a whole-trade window."""
    from src.units.strategies import trend_donchian as donch

    pkg = _pkg(entry_time="2026-10-20T13:00:00+00:00", entry_bar_closed=True)
    w = donch._trail_window(pkg["meta"], {}, _frame(last_open="2026-10-20T15:00:00Z"), pkg)
    assert len(w) == 3 and pt.window_covers_trade(w, pkg["meta"])
