"""ibs_reversion_stage0: the self-test (mean-reverting synthetic -> positive gross R, costs charged, no overlap)
and the no-look-ahead property of an entry (the signal bar's own close is the entry; exits start the next bar)."""
import datetime as dt
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
ibs = importlib.import_module("ibs_reversion_stage0")


def test_self_test_passes():
    assert ibs._self_test() == 0


def _bars(rows):
    t0 = dt.datetime(2022, 1, 3, tzinfo=dt.timezone.utc)
    return [{"ts": t0 + dt.timedelta(days=i), "o": o, "h": h, "l": l, "c": c} for i, (o, h, l, c) in enumerate(rows)]


def test_long_entry_at_signal_close_and_ibs_exit():
    flat = [(100, 101, 99, 100)] * 20
    sig = [(100, 101, 95, 95.5)]           # IBS = 0.083 -> long at 95.5
    nxt = [(95.6, 102, 95.4, 101.5)]       # close 101.5 > prior high 101 -> ibs_exit
    tr = ibs.simulate(_bars(flat + sig + nxt + flat), dict(ibs.DEFAULT_ARM), cost_bps=0.0, atr_period=14, sma=200)
    first = tr[0]
    assert first["outcome"] == "ibs_exit" and first["bars_held"] == 1
    assert first["gross_r"] > 0


def test_gap_through_stop_exits_at_open():
    flat = [(100, 101, 99, 100)] * 20
    sig = [(100, 101, 95, 95.5)]
    gap = [(80, 81, 79, 80)]
    tr = ibs.simulate(_bars(flat + sig + gap + flat), dict(ibs.DEFAULT_ARM), cost_bps=0.0, atr_period=14, sma=200)
    assert tr[0]["outcome"] == "stop_gap" and tr[0]["gross_r"] < -1.0
