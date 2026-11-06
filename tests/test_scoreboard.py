"""SCOREBOARD-PNL-FIRST: scripts/ops/scoreboard.py — populations, read-states, provenance never folded."""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.ops import scoreboard as sb

NOW = datetime(2026, 11, 1, 8, 20, tzinfo=timezone.utc)


def _t(i, acct, cls, pnl, closed="2026-10-20T00:00:00+00:00", **kw):
    return {"id": i, "account_id": acct, "account_class": cls, "status": "closed", "pnl": pnl, "closed_at": closed,
            "timestamp": closed, "is_backtest": 0, "notes": "{}", **kw}


ROWS = [
    _t(1, "bybit_2", "real_money", 10.0, fee_taker_usd=0.1, cost_source="broker"),
    _t(2, "bybit_2", "real_money", -30.0, fee_taker_usd=0.2, funding_paid_usd=0.05, cost_source="estimate"),
    _t(3, "bybit_2", "real_money", -5.0, closed="2026-08-01T00:00:00+00:00", fee_taker_usd=0.3, cost_source="estimate"),
    _t(4, "bybit_portfolio", "paper", 4.0),
    _t(5, "bybit_1", "paper", -2.0),
    _t(6, "bybit_1", "paper", None),                      # closed but unpriced -> counted, not summed
    _t(7, "bybit_2", "real_money", 99.0, is_backtest=1),  # backtest excluded
    _t(8, "bybit_2", "real_money", 1.0, closed="2026-11-02T00:00:00+00:00"),  # after the cutoff
]


def test_books_split_and_populations():
    books = sb.trade_books(ROWS, NOW)
    rm = books["real_money"]["inception"]
    assert (rm["n"], rm["net_usd"], rm["profit_factor"], rm["win_pct"]) == (3, -25.0, 0.29, 33.3)
    assert books["real_money"]["trailing_30d"]["n"] == 2  # row 3 is older than 30 d
    assert books["mirror"]["inception"]["n"] == 1 and books["mirror"]["inception"]["net_usd"] == 4.0
    assert books["paper"]["inception"]["n"] == 1 and books["paper"]["closed_unpriced"] == 1
    assert "pnl NOT NULL" in rm["population"]


def test_empty_book_is_empty_not_zero():
    a = sb.aggregate([], "x")
    assert a["read_state"] == "empty" and a["net_usd"] is None and a["profit_factor"] is None


def _snap(acct, bal, ts, ok=1):
    return {"account_id": acct, "balance": bal, "api_ok": ok, "ts": ts}


def test_no_snapshots_is_a_dash_with_state_not_zero():
    books = sb.trade_books(ROWS, NOW, None)
    i = books["real_money"]["inception"]
    assert i["pct"] is None and i["pct_state"] == "no_start_equity"
    assert sb.fmt_pct(None) == "—" and sb.fmt_money(None) == "—"


def test_pct_is_net_over_broker_equity_at_start():
    snaps = [_snap("bybit_2", 1000.0, "2026-07-01T00:00:00+00:00"),
             _snap("bybit_2", 900.0, "2026-10-02T00:00:00+00:00"),   # start of the 30 d window (NOW-30d = 10-02 08:20)
             _snap("bybit_2", 5000.0, "2026-10-30T00:00:00+00:00")]  # a later deposit must NOT move the start basis
    r = sb.trade_books(ROWS, NOW, snaps)["real_money"]
    # inception: first snapshot 07-01 -> trades closed >= 07-01: rows 1,2 (row 3 is 08-01 too) => net -25 / 1000
    assert r["inception"]["pct"] == -2.5 and r["inception"]["pct_state"] == "read"
    # 30 d: equity at 10-02 is 900; trades in window: rows 1,2 => -20 / 900
    assert r["trailing_30d"]["pct"] == -2.22


def test_failed_broker_read_is_a_gap_not_zero_equity():
    snaps = [_snap("bybit_2", None, "2026-07-01T00:00:00+00:00", ok=0), _snap("bybit_2", 0.0, "2026-07-02T00:00:00+00:00")]
    assert sb.trade_books(ROWS, NOW, snaps)["real_money"]["inception"]["pct_state"] == "no_start_equity"


def test_stale_start_snapshot_is_refused():
    snaps = [_snap("bybit_2", 1000.0, "2026-09-01T00:00:00+00:00")]  # 30+ days before the window start: beyond tolerance
    r = sb.trade_books(ROWS, NOW, snaps)["real_money"]
    assert r["trailing_30d"]["pct"] is None and r["trailing_30d"]["pct_state"] == "no_start_equity"
    assert r["inception"]["pct"] is not None  # inception uses the first snapshot


def test_partial_when_one_account_lacks_equity():
    rows = ROWS + [_t(20, "alpaca_live", "real_money", -4.0)]
    snaps = [_snap("bybit_2", 1000.0, "2026-07-01T00:00:00+00:00")]
    i = sb.trade_books(rows, NOW, snaps)["real_money"]["inception"]
    assert i["pct_state"] == "partial" and "alpaca_live" in i["pct_basis"]


def test_cost_never_folds_estimated_into_measured():
    c = sb.cost_block(ROWS, NOW)
    m, e = c["buckets"]["measured"], c["buckets"]["estimated"]
    assert (m["n"], m["total_usd"]) == (1, 0.1)
    assert (e["n"], e["total_usd"]) == (2, 0.55)
    assert c["measured_share"] == 0.3333 and c["n"] == 3


def test_prop_unreadable_is_not_zero():
    p = sb.prop_book(None, None, {}, NOW)
    assert p["inception"]["read_state"] == "unreadable" and p["inception"]["net_usd"] is None


def test_prop_net_and_pct_from_declared_size():
    ov = {"present": True, "generated_at": "x", "equity": {"accounts_total": 2, "accounts": [
        {"account_id": "a", "equity": 4900.0, "counted_in_total": True},
        {"account_id": "b", "equity": 9900.0, "counted_in_total": True}]}}
    fills = {"present": True, "fills": [
        {"status": "closed", "pnl": -20.0, "closed_at": "2026-10-25T00:00:00+00:00", "raw": '{"provenance":"estimated"}'},
        {"status": "closed", "pnl": None, "closed_at": "2026-10-26T00:00:00+00:00"}]}
    p = sb.prop_book(ov, fills, {"a": 5000.0, "b": 10000.0}, NOW)
    assert p["inception"]["net_usd"] == -200.0 and p["inception"]["pct"] == -1.33
    assert p["trailing_30d"]["n"] == 1 and p["closed_unpriced"] == 1
    assert p["trailing_30d"]["fill_provenance_counts"] == {"estimated": 1}


def test_build_unreadable_when_source_missing(tmp_path):
    out = sb.build(source="file", rows_file=str(tmp_path / "nope.json"), now=NOW)
    assert out["readState"] == "unreadable" and out["books"] is None
    assert "could not look" in "\n".join(sb.render_lines(out))


def test_render_has_all_books_and_dashes():
    out = sb.compute(ROWS, now=NOW, root=sb.REPO_ROOT)
    md = "\n".join(sb.render_lines(out))
    for label in sb.BOOK_LABEL.values():
        assert label in md
    assert "Prop | —" in md  # prop unreadable here (no overview) -> dash, not $0.00
