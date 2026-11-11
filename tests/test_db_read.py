"""scripts/ops/db_read.py: the read-only stand-in for the sqlite3 CLI the VM does not have (AUD-20261104-FLATTEN-LABEL)."""
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("db_read", REPO / "scripts/ops/db_read.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trades (id INTEGER, account_id TEXT, exit_reason TEXT, pnl REAL)")
    c.executemany("INSERT INTO trades VALUES (?,?,?,?)", [(4935, "bybit_portfolio", "reconciler_filled", None),
                                                          (6844, "bybit_2", "operator_flatten_reconciled", -3.5)])
    c.commit()
    c.close()
    return str(p)


def test_scalar_count_and_empty(db):
    assert D.run(db, "SELECT COUNT(*) FROM trades WHERE pnl IS NULL;") == "1"
    assert D.run(db, "SELECT id FROM trades WHERE id = 1") == ""


def test_table_has_header_rule_and_rows(db):
    out = D.run(db, "SELECT id, account_id, exit_reason, pnl FROM trades WHERE id IN (4935,6844);", table=True)
    lines = out.splitlines()
    assert lines[0].split() == ["id", "account_id", "exit_reason", "pnl"]
    assert set(lines[1]) <= {"-", " "}
    assert "4935" in lines[2] and "reconciler_filled" in lines[2] and len(lines) == 4


@pytest.mark.parametrize("sql", ["UPDATE trades SET pnl=0", "DELETE FROM trades", "SELECT 1; DELETE FROM trades",
                                 "PRAGMA journal_mode", "ATTACH 'x' AS y"])
def test_refuses_anything_but_one_select(db, sql):
    with pytest.raises(ValueError):
        D.run(db, sql)


def test_database_is_opened_read_only(db, monkeypatch):
    seen = {}
    real = sqlite3.connect

    def spy(target, *a, **k):
        seen["target"], seen["uri"] = target, k.get("uri")
        return real(target, *a, **k)
    monkeypatch.setattr(D.sqlite3, "connect", spy)
    D.run(db, "SELECT 1")
    assert seen["target"].endswith("?mode=ro") and seen["uri"] is True


def test_cli_exit_codes(db):
    ok = subprocess.run([sys.executable, str(REPO / "scripts/ops/db_read.py"), db, "SELECT COUNT(*) FROM trades"],
                        capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.strip() == "2"
    bad = subprocess.run([sys.executable, str(REPO / "scripts/ops/db_read.py"), db, "DROP TABLE trades"],
                         capture_output=True, text=True)
    assert bad.returncode == 2 and "only one SELECT" in bad.stderr
