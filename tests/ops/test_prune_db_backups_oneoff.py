"""prune-db-backups one-off `file:` path (VM-DISK-GROWTH-20261102): exact basename + confirm, narrow refusals."""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "prune_db_backups.sh"


def _run(tmp_path, **env):
    db = tmp_path / "trade_journal.db"
    e = {**os.environ, "TRADE_JOURNAL_DB": str(db), **env}
    return subprocess.run(["bash", str(SCRIPT)], env=e, cwd=REPO, capture_output=True, text=True)


def _mk(tmp_path):
    for n in ("trade_journal.db", "trade_journal.db-wal", "trade_journal.db-shm",
              "trade_journal.db.bak-own-fill-exits-20261017T072615Z", "other.txt"):
        (tmp_path / n).write_bytes(b"x")


def test_oneoff_needs_confirm_and_apply(tmp_path):
    _mk(tmp_path)
    b = "trade_journal.db.bak-own-fill-exits-20261017T072615Z"
    for extra in ({}, {"ACTION_APPLY": "true"}, {"ACTION_CONFIRM": "yes"}, {"ACTION_APPLY": "true", "ACTION_CONFIRM": "y"}):
        r = _run(tmp_path, ACTION_FILE=b, **extra)
        assert r.returncode == 0 and (tmp_path / b).exists(), r.stdout + r.stderr
        assert "NOT DELETED" in r.stdout


def test_oneoff_deletes_exactly_one_file_with_confirm(tmp_path):
    _mk(tmp_path)
    b = "trade_journal.db.bak-own-fill-exits-20261017T072615Z"
    r = _run(tmp_path, ACTION_FILE=b, ACTION_APPLY="true", ACTION_CONFIRM="yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / b).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "other.txt", "trade_journal.db", "trade_journal.db-shm", "trade_journal.db-wal"]


def test_oneoff_refuses_live_db_wal_shm_paths_and_non_backups(tmp_path):
    _mk(tmp_path)
    for bad in ("trade_journal.db", "trade_journal.db-wal", "trade_journal.db-shm", "other.txt",
                "../trade_journal.db.bak-x", "sub/trade_journal.db.bak-x", "..", "trade_journal.db.bak-missing"):
        r = _run(tmp_path, ACTION_FILE=bad, ACTION_APPLY="true", ACTION_CONFIRM="yes")
        assert r.returncode == 3 and "REFUSED" in r.stdout, (bad, r.stdout, r.stderr)
    assert (tmp_path / "trade_journal.db").exists() and (tmp_path / "other.txt").exists()


def test_general_rule_unchanged_keep_zero_still_refused(tmp_path):
    _mk(tmp_path)
    r = _run(tmp_path, ACTION_KEEP="0")
    assert r.returncode == 2 and "keep must be >= 1" in r.stdout
