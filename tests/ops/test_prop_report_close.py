"""prop-report-close (2026-10-12): journal the CLOSE of ONE open prop position via
ingest_report; exit price optional; every other case refused, nothing written."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.ops import prop_report_close as prc

NOW = "2026-10-12T14:00:00+00:00"
TID = "prop-manual-903de9527c23"


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(p))
    from src.prop import prop_journal

    prop_journal.ensure_tables()
    c = sqlite3.connect(p)
    for tid, acct, st in [(TID, "breakout_2", "filled"), ("prop-manual-aaa111", "breakout_2", "filled"),
                          ("prop-manual-bbb222", "breakout_1", "filled"), ("prop-manual-ccc333", "breakout_2", "emitted"),
                          ("prop-manual-ddd444", "breakout_2", "filled")]:
        c.execute("INSERT INTO prop_tickets (ticket_id, account_id, strategy, symbol, direction, status, created_at) "
                  "VALUES (?,?,?,?,?,?,?)", (tid, acct, "s", "SOLUSDT", "long", st, "2026-10-12T01:00:00+00:00"))
    fills = [  # id, ticket, symbol, status
        (TID, "SOLUSDT", "filled"), ("prop-manual-aaa111", "ETHUSDT", "open"),
        ("prop-manual-aaa111", "ETHUSDT", "closed"), ("prop-manual-ddd444", "BTCUSDT", "open"),
        (None, "BTCUSDT", "open"),
    ]
    for tid, sym, st in fills:
        c.execute("INSERT INTO prop_fills (account_id, ticket_id, symbol, direction, qty, entry_price, sl, status, "
                  "opened_at, reported_at, created_at) VALUES ('breakout_2',?,?,'long',17.26263867,111.16,109.71,?,"
                  "'2026-10-12T05:00:00+00:00','2026-10-12T05:00:00+00:00','2026-10-12T05:00:00+00:00')",
                  (tid, sym, st))
    c.commit()
    c.close()
    return p


@pytest.fixture
def platforms(tmp_path: Path) -> Path:
    p = tmp_path / "prop_platforms.yaml"
    p.write_text("accounts:\n  breakout_1: {platform: dxtrade}\nphone_accounts:\n  breakout_2: {platform: breakout_phone}\n")
    return p


def _run(db, platforms, capsys, tid=TID, account="breakout_2", extra=(), apply=False):
    argv = ["--db", str(db), "--account", account, "--ticket-id", tid, "--platforms", str(platforms),
            "--now", NOW, "--reason", "approx close"] + list(extra) + (["--apply"] if apply else [])
    rc = prc.main(argv)
    return rc, json.loads(capsys.readouterr().out)


def _q(db, sql, *a):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, a)]
    finally:
        c.close()


def test_dry_run_writes_nothing_and_shows_plan(db, platforms, capsys):
    rc, out = _run(db, platforms, capsys, extra=["--closed-at", "2026-10-12T13:30:00Z"])
    assert rc == 0 and out["mode"] == "dry_run"
    rep = out["after"]["would_insert_close_fill"]
    assert rep["status"] == "closed" and rep["exit_price"] is None and rep["pnl"] is None
    assert rep["provenance"] == "UNVERIFIED" and rep["closed_at"].startswith("2026-10-12T13:30:00")
    assert out["open_fill"]["id"] == 1
    assert len(_q(db, "SELECT id FROM prop_fills")) == 5
    assert _q(db, "SELECT status FROM prop_tickets WHERE ticket_id=?", TID)[0]["status"] == "filled"


def test_apply_exit_unknown_closes_with_null_exit_and_pnl(db, platforms, capsys):
    rc, out = _run(db, platforms, capsys, apply=True, extra=["--closed-at", "2026-10-12T13:30:00Z"])
    assert rc == 0 and Path(out["backup"]).exists()
    row = _q(db, "SELECT * FROM prop_fills WHERE ticket_id=? AND status='closed'", TID)
    assert len(row) == 1
    r = row[0]
    assert r["exit_price"] is None and r["pnl"] is None and r["entry_price"] == 111.16
    assert r["symbol"] == "SOLUSDT" and r["direction"] == "long" and r["closed_at"].startswith("2026-10-12T13:30")
    assert json.loads(r["raw"])["provenance"] == "UNVERIFIED"
    assert _q(db, "SELECT status FROM prop_tickets WHERE ticket_id=?", TID)[0]["status"] == "closed"
    assert out["after"]["still_listed_open"] is False
    # the original open row is untouched
    assert _q(db, "SELECT status FROM prop_fills WHERE id=1")[0]["status"] == "filled"


def test_apply_with_exit_price_gross_pnl_estimated(db, platforms, capsys):
    rc, out = _run(db, platforms, capsys, apply=True, extra=["--exit-price", "111.39"])
    assert rc == 0
    r = _q(db, "SELECT * FROM prop_fills WHERE ticket_id=? AND status='closed'", TID)[0]
    assert r["exit_price"] == 111.39
    assert r["pnl"] == pytest.approx((111.39 - 111.16) * 17.26263867, abs=1e-3)
    assert json.loads(r["raw"])["provenance"] == "ESTIMATED"


def test_apply_twice_second_is_refused(db, platforms, capsys):
    assert _run(db, platforms, capsys, apply=True)[0] == 0
    rc, out = _run(db, platforms, capsys, apply=True)
    assert rc == 3 and "already" in out["why"]
    assert len(_q(db, "SELECT id FROM prop_fills WHERE ticket_id=? AND status='closed'", TID)) == 1


@pytest.mark.parametrize("tid,account,needle", [
    ("prop-manual-ffffff", "breakout_2", "not found"),
    ("prop-manual-bbb222", "breakout_2", "belongs to breakout_1"),
    ("prop-manual-aaa111", "breakout_2", "already"),          # has a closed row
    ("prop-manual-ccc333", "breakout_2", "no open/filled"),   # emitted, never filled
    (TID, "nope_9", "not a configured prop account"),
])
def test_refusals_write_nothing(db, platforms, capsys, tid, account, needle):
    rc, out = _run(db, platforms, capsys, tid=tid, account=account, apply=True)
    assert rc == 3 and needle in out["why"]
    assert len(_q(db, "SELECT id FROM prop_fills")) == 5
    assert "backup" not in out


def test_newer_fill_for_same_position_key_refused(db, platforms, capsys):
    # ddd444's BTCUSDT open row (id 4) is followed by an unlinked BTCUSDT open row (id 5).
    rc, out = _run(db, platforms, capsys, tid="prop-manual-ddd444", apply=True)
    assert rc == 3 and "newer fill row" in out["why"]


@pytest.mark.parametrize("extra", [["--exit-price", "abc"], ["--exit-price", "-1"], ["--exit-price", "0"],
                                   ["--closed-at", "yesterday"]])
def test_bad_numbers_and_dates_refused(db, platforms, capsys, extra):
    rc, out = _run(db, platforms, capsys, extra=extra, apply=True)
    assert rc == 3 and not out["ok"]
    assert len(_q(db, "SELECT id FROM prop_fills")) == 5


PLACED = "prop-manual-762f959676fd"


def _add_placed(db: Path, ticket_status: str = "placed") -> None:
    c = sqlite3.connect(db)
    c.execute("INSERT INTO prop_tickets (ticket_id, account_id, strategy, symbol, direction, status, created_at) "
              "VALUES (?,?,?,?,?,?,?)", (PLACED, "breakout_2", "trend_donchian_eth_prop", "ETHUSDT", "short",
                                         ticket_status, "2026-10-12T21:57:37+00:00"))
    c.execute("INSERT INTO prop_fills (account_id, ticket_id, symbol, direction, qty, entry_price, sl, tp, status, "
              "reported_at, created_at) VALUES ('breakout_2',?,'ETHUSDT','short',0.57,2491.47,2535.25,2244.81,"
              "'placed','2026-10-13T04:43:03+00:00','2026-10-13T04:43:03+00:00')", (PLACED,))
    c.commit()
    c.close()


def test_placed_row_refused_without_flag(db, platforms, capsys):
    """LIVE-SILENCE-DIAG: default behaviour unchanged — a `placed` row may still be a resting order."""
    _add_placed(db)
    rc, out = _run(db, platforms, capsys, tid=PLACED, apply=True)
    assert rc == 3 and "no open/filled" in out["why"]
    assert _q(db, "SELECT status FROM prop_tickets WHERE ticket_id=?", PLACED)[0]["status"] == "placed"


def test_from_placed_closes_and_clears_reticket_block(db, platforms, capsys):
    """LIVE-SILENCE-DIAG: a placed ticket that filled and stopped out off-journal blocks every later
    same-key ticket (no time window). --from-placed closes it through ingest_report and the block lifts."""
    _add_placed(db)
    from src.prop.breakout_executor import _reticket_suppress_reason

    assert "outstanding_ticket:placed" in (_reticket_suppress_reason("breakout_2", "ETHUSDT", "short") or "")
    rc, out = _run(db, platforms, capsys, tid=PLACED, apply=True,
                   extra=["--from-placed", "--exit-price", "2535.25", "--closed-at", "2026-10-13T05:00:00Z"])
    assert rc == 0, out
    r = _q(db, "SELECT * FROM prop_fills WHERE ticket_id=? AND status='closed'", PLACED)[0]
    assert r["pnl"] == pytest.approx((2491.47 - 2535.25) * 0.57, abs=1e-3)
    assert json.loads(r["raw"])["provenance"] == "ESTIMATED"
    assert _q(db, "SELECT status FROM prop_tickets WHERE ticket_id=?", PLACED)[0]["status"] == "closed"
    assert _reticket_suppress_reason("breakout_2", "ETHUSDT", "short") is None


def test_from_placed_needs_a_placed_ticket(db, platforms, capsys):
    _add_placed(db, ticket_status="emitted")
    rc, out = _run(db, platforms, capsys, tid=PLACED, apply=True, extra=["--from-placed"])
    assert rc == 3 and "no open/filled" in out["why"]
