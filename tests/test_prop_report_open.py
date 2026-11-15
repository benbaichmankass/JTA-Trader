"""prop-report-open (2026-11-11, breakout_2 ETH long prop-manual-c54b2229aa1c): a ticket the stale-entry sweep
marked `skipped` although its order FILLED is recorded as an open position through ingest_report."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("prop_report_open", REPO / "scripts/ops/prop_report_open.py")
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

TID = "prop-manual-c54b2229aa1c"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db))
    plat = tmp_path / "prop_platforms.yaml"
    plat.write_text("phone_accounts:\n  breakout_2: {}\naccounts:\n  tradeify_1: {}\n")
    from src.prop import breakout_notify, prop_journal
    monkeypatch.setattr(breakout_notify, "emit_prop_fill", lambda fill: {"push": False, "telegram": False})
    prop_journal.record_ticket({"ticket_id": TID, "account_id": "breakout_2", "symbol": "ETHUSDT",
                                "direction": "long", "entry": 2077.57, "sl": 2043.70, "tp": 2128.37,
                                "qty": 0.5167, "status": "skipped", "order_package_id": "pkg-462cfc59b2a1469b"})
    return db, plat


def _run(db, plat, *extra):
    return P.main(["--db", str(db), "--account", "breakout_2", "--ticket-id", TID, "--platforms", str(plat),
                   *extra])


def _ticket(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return dict(c.execute("SELECT * FROM prop_tickets WHERE ticket_id = ?", (TID,)).fetchone())
    finally:
        c.close()


def test_dry_run_writes_nothing(env, capsys):
    db, plat = env
    assert _run(db, plat, "--reason", "operator chat 21:20Z: open ETH long") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["report"]["status"] == "open"
    assert out["report"]["entry_price_source"].startswith("ticket_planned_entry")
    assert _ticket(db)["status"] == "skipped"


def test_apply_records_open_fill_and_moves_ticket_to_filled(env, capsys):
    db, plat = env
    rc = _run(db, plat, "--reason", "operator chat 21:20Z: 'There is an open ETH long trade.'",
              "--apply", "--confirm", TID)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, out
    assert _ticket(db)["status"] == "filled"
    f = out["after"]["open_fill"]
    assert f["status"] == "open" and f["ticket_id"] == TID and f["direction"] == "long"
    assert f["sl"] == pytest.approx(2043.70) and f["tp"] == pytest.approx(2128.37)
    assert out["backup"] and Path(out["backup"]).exists()
    # idempotent: a second run is refused, nothing doubled
    assert _run(db, plat, "--reason", "again", "--apply", "--confirm", TID) == 3


@pytest.mark.parametrize("extra, why", [
    (["--reason", ""], "reason is required"),
    (["--reason", "x", "--entry-price", "-3"], "not a positive number"),
    (["--reason", "x", "--apply", "--confirm", "wrong"], "apply needs confirm"),
])
def test_refusals(env, capsys, extra, why):
    db, plat = env
    assert _run(db, plat, *extra) == 3
    assert why in json.loads(capsys.readouterr().out)["why"]
    assert _ticket(db)["status"] == "skipped"


def test_refuses_other_account_and_unconfigured_account(env, capsys):
    db, plat = env
    rc = P.main(["--db", str(db), "--account", "tradeify_1", "--ticket-id", TID, "--platforms", str(plat),
                 "--reason", "x"])
    assert rc == 3 and "belongs to breakout_2" in json.loads(capsys.readouterr().out)["why"]
    rc = P.main(["--db", str(db), "--account", "nope", "--ticket-id", TID, "--platforms", str(plat), "--reason", "x"])
    assert rc == 3 and "not a configured prop account" in json.loads(capsys.readouterr().out)["why"]


def test_refuses_when_another_open_fill_holds_the_same_position(env, capsys):
    db, plat = env
    from src.prop import prop_journal
    prop_journal.insert_fill({"account_id": "breakout_2", "ticket_id": "prop-manual-aaaaaa", "symbol": "ETHUSDT",
                              "direction": "long", "qty": 0.5, "entry_price": 2070.0, "status": "open"})
    assert _run(db, plat, "--reason", "x") == 3
    assert "double-count open risk" in json.loads(capsys.readouterr().out)["why"]
