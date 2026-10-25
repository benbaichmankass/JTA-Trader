"""live_bt_trade_join: the per-bar join, the cause split, and its gap identity (pure, synthetic data)."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research")]

import live_bt_trade_join as j  # noqa: E402


def _live(tid, side, opened, closed, entry, exit_, reason="sl"):
    return {"id": tid, "side": side, "openedAt": opened, "closedAt": closed, "entryPrice": entry,
            "exitPrice": exit_, "closeReason": reason, "pnlProvenance": "measured", "pattern": "leg",
            "realizedPnl": 123.0}


def _pkg(pid, direction, created, bar, entry, rpu):
    return {"orderPackageId": pid, "strategy": "leg", "direction": direction, "createdAt": created,
            "entry": entry, "sl": entry - rpu, "meta": {"entry_time": bar, "risk_per_unit": rpu}, "pnl": 9.0}


def _bt(t, direction, gross, net, reason="stop"):
    r = {"entry_time": t, "direction": direction, "gross_r": gross, "net_r": net, "exit_reason": reason,
         "exit_time": t}
    r["_t"] = j._ts(t)
    return r


LIVE = [
    # matched: live bar 10:00, backtest twin at 10:00; filled 0.1 R adverse, stopped at -1 R from the fill
    _live("1", "buy", "2026-09-01T10:05:00+00:00", "2026-09-01T14:00:00+00:00", 1.01, 0.91),
    # live-only: no backtest trade near this bar
    _live("2", "sell", "2026-09-03T06:04:00+00:00", "2026-09-03T09:00:00+00:00", 2.0, 2.1),
    # no package at all
    _live("3", "buy", "2026-09-05T00:00:00+00:00", "2026-09-05T00:00:00+00:00", 1.0, 1.0, reason="other"),
]
PKGS = [
    _pkg("p1", "long", "2026-09-01T10:05:00+00:00", "2026-09-01 10:00:00", 1.00, 0.1),
    _pkg("p2", "short", "2026-09-03T06:04:00+00:00", "2026-09-03 06:00:00", 2.00, 0.1),
]
BT = [
    _bt("2026-09-01 10:00:00+00:00", "long", -1.0, -1.05),
    _bt("2026-09-02 12:00:00+00:00", "short", 2.0, 1.95, "take_profit"),  # backtest-only (live missed it)
]


def test_classes_r_basis_and_flags():
    res = j.join("leg", LIVE, PKGS, BT, "2h")
    by = {r["trade_id"]: r for r in res["rows"]}
    assert by["1"]["class"] == "matched" and by["2"]["class"] == "live_only"
    assert by["3"]["class"] == "execution_unattributable"
    assert set(by["3"]["flags"]) == {"no_package_or_r_basis", "zero_duration", "close_not_tp_sl"}
    # R basis is meta.risk_per_unit (0.1), not the package sl: (0.91 - 1.01) / 0.1 = -1.0
    assert by["1"]["live_gross_r"] == -1.0
    assert by["1"]["entry_slip_r"] == 0.1  # filled 0.01 above a long package entry: adverse
    assert by["2"]["live_gross_r"] == -1.0
    assert by["1"]["minutes_into_bar"] == 5.0


def test_cause_split_and_gap_identity():
    s = j.join("leg", LIVE, PKGS, BT, "2h")["summary"]
    assert s["bt_only"] == {"n": 1, "net_r": 1.95}
    # entry = live-only (-1.0) minus backtest-only (+1.95)
    assert s["components_r"]["entry"] == -2.95
    # exit on the matched pair = live -1.0 - bt gross -1.0 - slip 0.1
    assert s["components_r"]["exit"] == -0.1
    assert s["components_r"]["execution"] == 0.1
    assert s["largest_component"] == "entry"
    assert s["gap_identity_residual_r"] == 0.0
    assert s["gap_r"] == round(-2.0 - (-1.05 + 1.95), 4)


def test_alt_arm_delta_and_live_only_fire():
    alt = [_bt("2026-09-03 06:00:00+00:00", "short", -1.0, -1.04)]  # fires on the live-only bar, not the matched one
    s = j.join("leg", LIVE, PKGS, BT, "2h", alts={"C9": alt})["summary"]["alt_arms"]["C9"]
    assert s["on_live_only_trades_alt_fires"] == ["2"]
    assert s["live_trades_whose_twin_changes_gt_0_1r"] == ["1", "2"]
    assert s["backtest_twin_r_delta_on_live_bars"] == round(1.05 - 1.04, 4)


def test_off_roster_span_is_not_a_missed_trade():
    res = j.join("leg", LIVE, PKGS, BT, "2h", exclude=[("2026-09-02T00:00:00+00:00", "2026-09-03T00:00:00+00:00")])
    assert res["summary"]["bt_only"] == {"n": 0, "net_r": 0}
    assert res["window"]["excluded_bt"] == {"n": 1, "net_r": 1.95}
    assert res["summary"]["components_r"]["entry"] == -1.0
    assert res["summary"]["gap_identity_residual_r"] == 0.0


def test_main_strips_dollar_fields(tmp_path):
    closed = tmp_path / "c.json"
    closed.write_text(json.dumps([dict(r, account="bybit_2") for r in LIVE]))
    pk = tmp_path / "p.json"
    pk.write_text(json.dumps(PKGS))
    bt = tmp_path / "bt.jsonl"
    bt.write_text("\n".join(json.dumps({k: v for k, v in r.items() if k != "_t"}) for r in BT))
    assert j.main(["--leg", "leg", "--timeframe", "2h", "--bt-trades", str(bt), "--closed-json", str(closed),
                   "--packages-json", str(pk), "--out", str(tmp_path / "o")]) == 0
    text = (tmp_path / "o" / "leg.json").read_text()
    assert "realizedPnl" not in text and '"pnl"' not in text
