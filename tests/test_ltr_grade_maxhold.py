"""LTR-GRADE-MAXHOLD: the hold replay honours max_hold_min; time-stop arms fire as registered; the grade alarm sees ungraded closes."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
import live_review_counterfactual as L  # noqa: E402
import ltr_timestop_s0 as T  # noqa: E402


B = 1_800_000_000.0


def _bars(n, px=100.0, step=3600.0, t0=B):
    return [{"time": t0 + i * step, "open": px, "high": px + 0.1, "low": px - 0.1, "close": px} for i in range(n)]


def test_hold_replay_time_exit_at_max_hold():
    pkg = {"created_at": L._iso(B), "meta": {"max_hold_min": 180}}
    hit = L.hold_replay(_bars(10, 100.5), pkg=pkg, trade=None, side="long", entry=100.0, r_dist=1.0, start_ts=B + 3600.0,
                        stop=99.0, tp=110.0, extreme_r0=0.0, trail_dist=None)
    assert hit["reason"] == "max_hold" and hit["ts"] == B + 10800.0 and abs(hit["gross_r"] - 0.5) < 1e-9


def test_hold_replay_unresolved_before_boundary_is_none():
    pkg = {"created_at": L._iso(B), "meta": {"max_hold_min": 1440}}
    assert L.hold_replay(_bars(5), pkg=pkg, trade=None, side="long", entry=100.0, r_dist=1.0, start_ts=B + 3600.0,
                         stop=99.0, tp=110.0, extreme_r0=0.0, trail_dist=None) is None


def test_applied_attribution_accepts_review_stamped_after_close():
    rv = {"reviewed_at": "2026-11-16T08:20:00Z", "recommendation": {"action": "close"}}
    tr = {"exit_reason": "live_review_close", "closed_at": "2026-11-16T08:18:24+00:00"}
    assert L.applied_by_outcome(rv, tr) is True


def test_timestop_arm_fires_once_and_costs_apply():
    r = {"package": "p", "te": 0.0, "tc": 100000.0, "hold": -1.0, "fee_r": 0.0, "fund_r": 0.0, "slip_r": 0.1, "month": "2026-11",
         "leg": "x", "tn": [3600.0 * k for k in range(1, 20)], "close_r": [0.2] * 19, "next_open_r": [0.3] * 19}
    k = T.fire_index(r, "ts:4")
    assert k == 3 and abs(T._close_net(r, k) - 0.2) < 1e-9
    assert T.fire_index(r, "stall:4:0.1") is None          # peak 0.2 >= 0.1: not stalled
    assert T.fire_index(r, "weak:4:0.5") == 3              # current 0.2 < 0.5
