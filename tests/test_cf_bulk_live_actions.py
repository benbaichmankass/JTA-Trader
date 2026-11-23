"""CF-FIDELITY-ACTION-REPLAY: cf_bulk_live replays a package's recorded stop/target path (position_path_history) and, when asked,
its non-bracket journal close; defaults stay byte-identical."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    sys.path.insert(0, str(p))
import cf_bulk_live as b  # noqa: E402
import cf_core  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

T0 = 1_792_000_000
PKG = {"order_package_id": "pkg-t", "strategy_name": "s", "symbol": "ADAUSDT", "direction": "long", "entry": 100.0, "sl": 99.0, "tp": 104.0,
       "exit_plan": '{"stop": {"price": 99.0}}', "meta": {}}


def _row(i, sl, tp=104.0):
    return {"bar_ts": lrc._iso(T0 + 3600 * i), "sl_price": sl, "tp_price": tp, "first_seen_at": lrc._iso(T0 + 3600 * i + 60),
            "written_at": lrc._iso(T0 + 3600 * i + 3500)}


def test_path_actions_tighten_widen_and_tp_with_window_timing():
    rows = [_row(0, 99.0), _row(1, 100.0), _row(2, 99.5), _row(3, 99.5, 105.0)]
    acts = b.derive_path_actions(PKG, rows, "last")
    assert [(a["kind"], a["level"]) for a in acts] == [("set_stop", 100.0), ("widen_stop", 99.5), ("set_tp", 105.0)]
    first = b.derive_path_actions(PKG, rows, "first")
    assert all(f["ts_epoch"] < l["ts_epoch"] for f, l in zip(first, acts))           # placement inside the write window
    assert all(a["time_provenance"] == "ESTIMATED(path_row_window)" for a in acts)


def test_no_change_means_no_action_and_short_side_tightens_downward():
    assert b.derive_path_actions(PKG, [_row(0, 99.0), _row(1, 99.0)]) == []
    short = dict(PKG, direction="short", entry=100.0, sl=101.0, tp=96.0, exit_plan='{"stop": {"price": 101.0}}')
    assert b.derive_path_actions(short, [_row(0, 101.0, 96.0), _row(1, 100.2, 96.0)])[0]["kind"] == "set_stop"


def test_journal_close_only_for_non_bracket_exits():
    leg = {"account_class": "real_money", "timestamp": lrc._iso(T0), "closed_at": lrc._iso(T0 + 600)}
    assert b.journal_close_actions([dict(leg, exit_reason="sl")]) == []
    c = b.journal_close_actions([dict(leg, exit_reason="reconciler_filled")])
    assert c and c[0]["kind"] == "close" and c[0]["ts_epoch"] == T0 + 600


def _bars(path):
    return [{"time": T0 + 300 * i, "open": px, "high": px + 0.05, "low": px - 0.05, "close": px, "volume": 1.0, "dur": 300} for i, px in enumerate(path)]


def _leg():
    return [{"id": 1, "account_id": "a", "account_class": "paper", "status": "closed", "position_size": 1.0, "entry_price": 100.0, "exit_price": 100.5,
             "exit_reason": "x", "pnl": 0.5, "timestamp": lrc._iso(T0), "closed_at": lrc._iso(T0 + 3000), "fee_taker_usd": 0.0, "cost_source": None}]


def _rep(rec):
    return next(a for a in rec["arms"] if a["arm_id"] == "replayed_actual")


def test_replayed_actual_follows_a_recorded_stop_move_and_default_is_unchanged():
    bars = _bars([100.0, 101.0, 101.0, 100.4, 100.4, 100.4, 100.4, 100.4, 100.4, 100.4, 100.4, 100.4])
    base = cf_core.grade_package(PKG, _leg(), bars, [], [], {}, {}, n_random=5)
    moved = [{"ts_epoch": T0 + 600, "kind": "set_stop", "level": 100.8}]
    got = cf_core.grade_package(PKG, _leg(), bars, [], moved, {}, {}, n_random=5, actions_authoritative=True)
    assert _rep(base)["exit"]["reason"] != "stop" or _rep(base)["gross_r"] != _rep(got)["gross_r"]
    assert _rep(got)["exit"]["reason"] == "stop" and _rep(got)["gross_r"] > 0          # stopped at the tightened 100.8, a gain
    again = cf_core.grade_package(PKG, _leg(), bars, [], [], {}, {}, n_random=5)
    assert again["arms"] == base["arms"]                                               # no actions: byte-identical


def test_a_close_action_replays_the_journal_exit_and_labels_do_not_crash():
    bars = _bars([100.0] * 12)
    cl = [{"ts_epoch": T0 + 900, "kind": "close", "frac": 1.0}]
    rec = cf_core.grade_package(PKG, _leg(), bars, [], cl, {}, {}, n_random=5)
    assert _rep(rec)["exit"]["reason"] == "close"
    assert any(a["arm_id"] == "less_without_action_1" for a in rec["arms"])
