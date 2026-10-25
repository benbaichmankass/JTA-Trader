"""JOURNAL-OFFVM-BACKUP: naming, retention and the remote snapshot (no OCI needed)."""
import datetime as dt
import gzip
import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


bk = _load("journal_offvm_backup", "scripts/ops/journal_offvm_backup.py")
D = dt.date


def test_names_roundtrip_and_weekly_on_sunday():
    n = bk.object_name("trade_journal", "daily", D(2026, 10, 13))
    assert n == "trade_journal/daily/trade_journal-20261013.db.gz"
    assert bk.parse_name(n) == ("trade_journal", "daily", D(2026, 10, 13))
    assert bk.parse_name("trade_journal/daily/other-20261013.db.gz") is None
    assert bk.kinds_for(D(2026, 10, 11)) == ["daily", "weekly"]  # Sunday
    assert bk.kinds_for(D(2026, 10, 13)) == ["daily"]


def test_prune_keeps_30d_daily_and_12w_weekly_and_ignores_strays():
    today = D(2026, 10, 13)
    names = [
        bk.object_name("trade_journal", "daily", today - dt.timedelta(days=30)),   # keep
        bk.object_name("trade_journal", "daily", today - dt.timedelta(days=31)),   # prune
        bk.object_name("trade_journal", "weekly", today - dt.timedelta(days=84)),  # keep
        bk.object_name("trade_journal", "weekly", today - dt.timedelta(days=85)),  # prune
        "notes/readme.txt",                                                         # never
    ]
    assert bk.prune_candidates(names, today) == sorted([names[1], names[3]])


def test_consecutive_daily_counts_back_from_today_or_yesterday():
    today = D(2026, 10, 13)
    have = [bk.object_name("trade_journal", "daily", today - dt.timedelta(days=i)) for i in (1, 2, 3, 5)]
    assert bk.consecutive_daily(have, "trade_journal", today) == 3
    have.append(bk.object_name("trade_journal", "daily", today))
    assert bk.consecutive_daily(have, "trade_journal", today) == 4
    assert bk.consecutive_daily([], "trade_journal", today) == 0


def test_remote_snapshot_is_consistent_verified_and_leaves_source_untouched(tmp_path):
    db = tmp_path / "live.db"
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
    con.executemany("INSERT INTO trades(symbol) VALUES (?)", [("x",)] * 50)
    con.commit()  # leave the connection open: a live WAL DB with -wal present
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ops/journal_snapshot_remote.py"),
         "--db", str(db), "--out-dir", str(tmp_path / "o"), "--label", "trade_journal"],
        capture_output=True, text=True, check=True)
    j = json.loads(out.stdout)
    assert j["state"] == "ok" and j["integrity"] == "ok" and j["counts"] == {"trades": 50}
    gz = pathlib.Path(j["gz_path"])
    assert j["gz_bytes"] == gz.stat().st_size
    restored = tmp_path / "r.db"
    restored.write_bytes(gzip.open(gz).read())
    assert sqlite3.connect(restored).execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 50
    assert not list((tmp_path / "o").glob("*.snap.db*"))  # raw snapshot removed
    assert con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 50
    con.close()


def test_remote_snapshot_reports_absent_db(tmp_path):
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ops/journal_snapshot_remote.py"),
         "--db", str(tmp_path / "nope.db"), "--out-dir", str(tmp_path), "--label", "x"],
        capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == {"label": "x", "state": "absent"}
