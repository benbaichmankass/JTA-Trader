"""mark-entry-unfilled (2026-11-20, trade 8034 / db-integrity INV-2): the planted-control self-test
must pass in CI, and the INV-2 checker must accept what the script writes."""
from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ops"))

meu = importlib.import_module("mark_entry_unfilled")


def test_self_test_passes():
    assert meu._self_test() == 0


def test_marker_is_the_provenance_constant():
    from src.runtime.provenance import UNMEASURED_MARKER
    assert meu.UNMEASURED == UNMEASURED_MARKER


def test_cli_refuses_without_named_targets(capsys):
    assert meu.main(["--reason", "x"]) == 2
    assert meu.main(["--trade-ids", "8034"]) == 2
    assert meu.main(["--trade-ids", "80a4", "--reason", "x"]) == 2


def test_a_wrong_db_path_refuses_and_never_creates_a_file(tmp_path):
    """Issue #27636: the first live run opened a path that was not the journal, and a plain
    sqlite3.connect would have created an empty file there. mode=rw refuses instead."""
    missing = tmp_path / "nope.db"
    assert meu.main(["--db", str(missing), "--trade-ids", "8034", "--reason", "x"]) == 1
    assert not missing.exists()
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert meu.main(["--db", str(empty), "--trade-ids", "8034", "--reason", "x"]) == 1


def test_wrapper_resolves_the_db_after_loading_secrets_and_checks_it():
    text = (REPO / "scripts" / "ops" / "mark_entry_unfilled_action.sh").read_text()
    assert text.index("load_runtime_secrets\nDB_PATH=") >= 0
    assert "SELECT COUNT(*) FROM trades" in text and "mode=rw" in text
    assert text.count('--db "${DB_PATH}"') >= 2


# ---------------------------------------------------------------------------
# Trade 8034 (issue #27646): the notes cap dropped the marker. Pinned on the REAL notes shape.
# ---------------------------------------------------------------------------

NOTES_8034 = json.dumps({
    "closed_at": "2026-11-19T21:02:11.850350+00:00", "closed_by": "position_snapshot_reconciler",
    "reset_event": False,
    "closed_reason": "(symbol, side) confirmed absent from the exchange open-positions snapshot across two "
                     "observations AND, where the integration supports it, by a direct per-symbol broker check "
                     "(alpaca 404); integration has no per-order status reader (non-Bybit). PnL filled by the "
                     "local-PnL sweep (mark-to-market).",
    "broker_leg_read": "no_filled_leg"})
REASON_8034 = ("INV-2 on trade 8034 (paper). Its DAY mleg entry expired unfilled before PR #27537 deployed; it "
               "closed as exchange_flat_reconciled with pnl NULL. Relabel it entry_unfilled with the explicit "
               "unmeasured marker. Manager-approved Tier-2 writeback.")
OID = "10fd4469-aa72-4c9a-a893-ff5cafcc491d"


def test_8034_notes_keep_the_marker_and_the_reversal_key():
    blob = meu._build_notes(NOTES_8034, "exchange_flat_reconciled", OID, REASON_8034)
    n = json.loads(blob)
    assert len(blob) <= 500
    assert meu._marker_survives(blob, "exchange_flat_reconciled")
    assert n["closed_at"] and n["closed_by"] == "position_snapshot_reconciler"


def test_a_blob_that_lost_the_marker_never_passes():
    assert not meu._marker_survives('{"_truncated": true}', "exchange_flat_reconciled")
    assert not meu._marker_survives("not json", "exchange_flat_reconciled")


def _journal(path, exit_reason, notes):
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, status TEXT, exit_reason TEXT,"
                    " pnl REAL, notes TEXT, broker_order_id TEXT);")
    c.execute("INSERT INTO trades VALUES (8034,'alpaca_options_paper','closed',?,NULL,?,?)",
              (exit_reason, notes, OID))
    c.commit()
    c.close()


def test_restore_rebuilds_8034_from_the_backup(tmp_path):
    live, bak = tmp_path / "j.db", tmp_path / "j.bak"
    _journal(live, "entry_unfilled", '{"_truncated": true}')
    _journal(bak, "exchange_flat_reconciled", NOTES_8034)
    assert meu.main(["--db", str(live), "--trade-ids", "8034", "--reason", REASON_8034,
                     "--restore-notes-from", str(bak), "--apply"]) == 0
    c = sqlite3.connect(live)
    er, notes = c.execute("SELECT exit_reason, notes FROM trades WHERE id=8034").fetchone()
    c.close()
    n = json.loads(notes)
    assert er == "entry_unfilled" and n["pnl_source"] == "unmeasured"
    assert n["pre_mark_exit_reason"] == "exchange_flat_reconciled" and n["broker_leg_read"] == "no_filled_leg"
    # idempotent: a second run skips
    assert meu.main(["--db", str(live), "--trade-ids", "8034", "--reason", "x",
                     "--restore-notes-from", str(bak), "--apply"]) == 0


def test_restore_refuses_a_backup_that_is_not_the_pre_write_state(tmp_path):
    live, bak = tmp_path / "j.db", tmp_path / "j.bak"
    _journal(live, "entry_unfilled", '{"_truncated": true}')
    _journal(bak, "entry_unfilled", '{"_truncated": true}')
    assert meu.main(["--db", str(live), "--trade-ids", "8034", "--reason", "x",
                     "--restore-notes-from", str(bak), "--apply"]) == 1
    c = sqlite3.connect(live)
    assert c.execute("SELECT notes FROM trades WHERE id=8034").fetchone()[0] == '{"_truncated": true}'
    c.close()
