"""prop-report-skip (2026-11-05, BREAKOUT-UNRECORDED-1101): journal ONE never-filled prop
ticket as `skipped` via ingest_report; every other case refused, nothing written."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.ops import prop_report_skip as prs

TID = "prop-manual-8468ab1f682f"
REASON = "unconfirmed live submit; limit never filled; operator cancelled at venue"


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(p))
    from src.prop import prop_journal

    prop_journal.ensure_tables()
    c = sqlite3.connect(p)
    tickets = [(TID, "breakout_2", "placed"), ("prop-manual-aaa111", "breakout_2", "filled"),
               ("prop-manual-bbb222", "breakout_1", "placed"), ("prop-manual-ccc333", "breakout_2", "emitted"),
               ("prop-manual-ddd444", "breakout_2", "placed"), ("prop-manual-eee555", "breakout_2", "closed")]
    for tid, acct, st in tickets:
        c.execute("INSERT INTO prop_tickets (ticket_id, account_id, strategy, symbol, direction, status, created_at) "
                  "VALUES (?,?,?,?,?,?,?)", (tid, acct, "s", "ETHUSDT", "long", st, "2026-11-04T15:00:00+00:00"))
    # TID: one unconfirmed `placed` fill (the real case). ddd444: placed ticket but an `open` fill row.
    for tid, st in [(TID, "placed"), ("prop-manual-ddd444", "open")]:
        c.execute("INSERT INTO prop_fills (account_id, ticket_id, symbol, direction, qty, entry_price, status, "
                  "reported_at, created_at) VALUES ('breakout_2',?,'ETHUSDT','long',0.29,2379.36,?,"
                  "'2026-11-04T15:05:00+00:00','2026-11-04T15:05:00+00:00')", (tid, st))
    c.commit()
    c.close()
    return p


@pytest.fixture
def platforms(tmp_path: Path) -> Path:
    p = tmp_path / "prop_platforms.yaml"
    p.write_text("accounts:\n  breakout_1: {platform: dxtrade}\nphone_accounts:\n  breakout_2: {platform: breakout_phone}\n")
    return p


def _run(db, platforms, capsys, tid=TID, account="breakout_2", reason=REASON, apply=False, confirm=None):
    argv = ["--db", str(db), "--account", account, "--ticket-id", tid, "--platforms", str(platforms),
            "--reason", reason]
    if apply:
        argv += ["--apply", "--confirm", tid if confirm is None else confirm]
    rc = prs.main(argv)
    return rc, json.loads(capsys.readouterr().out)


def _status(db, tid=TID):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT status FROM prop_tickets WHERE ticket_id = ?", (tid,)).fetchone()[0]
    finally:
        c.close()


def _nfills(db):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT COUNT(*) FROM prop_fills").fetchone()[0]
    finally:
        c.close()


def test_positive_control_apply_skips_the_ticket(db, platforms, capsys):
    rc, out = _run(db, platforms, capsys, apply=True)
    assert rc == 0, out
    assert out["before"]["status"] == "placed"
    assert out["after"]["ticket"]["status"] == "skipped"
    assert out["after"]["skip_fill"]["status"] == "skipped"
    assert out["after"]["skip_fill"]["reason"] == REASON
    assert Path(out["backup"]).exists()
    assert _status(db) == "skipped"


def test_dry_run_writes_nothing(db, platforms, capsys):
    n = _nfills(db)
    rc, out = _run(db, platforms, capsys)
    assert rc == 0 and out["mode"] == "dry_run"
    assert out["after"]["would_ingest"]["status"] == "skipped"
    assert _status(db) == "placed" and _nfills(db) == n


def test_emitted_ticket_is_skippable(db, platforms, capsys):
    rc, out = _run(db, platforms, capsys, tid="prop-manual-ccc333")
    assert rc == 0, out


@pytest.mark.parametrize("kw,why", [
    ({"reason": "  "}, "reason is required"),
    ({"account": "nope_1"}, "not a configured prop account"),
    ({"tid": "prop-manual-fff666"}, "ticket not found"),
    ({"tid": "prop-manual-bbb222"}, "belongs to breakout_1"),
    ({"tid": "prop-manual-aaa111"}, "not skippable"),
    ({"tid": "prop-manual-eee555"}, "not skippable"),
    ({"tid": "prop-manual-ddd444"}, "that is a position"),
])
def test_refusals_write_nothing(db, platforms, capsys, kw, why):
    n = _nfills(db)
    rc, out = _run(db, platforms, capsys, apply=True, **kw)
    assert rc == 3 and why in out["why"], out
    assert _nfills(db) == n and _status(db) == "placed"


def test_apply_without_matching_confirm_is_refused(db, platforms, capsys):
    n = _nfills(db)
    rc, out = _run(db, platforms, capsys, apply=True, confirm="prop-manual-other")
    assert rc == 3 and "apply needs confirm" in out["why"]
    assert _status(db) == "placed" and _nfills(db) == n


def test_rerun_after_apply_is_a_clean_refusal(db, platforms, capsys):
    assert _run(db, platforms, capsys, apply=True)[0] == 0
    rc, out = _run(db, platforms, capsys, apply=True)
    assert rc == 3 and "not skippable" in out["why"]
