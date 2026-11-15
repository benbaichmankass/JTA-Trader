"""HEALTH-20261112-JOURNAL-BAK-RETENTION: the shared pre-APPLY backup keeps only the newest per tag."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from scripts.ops import journal_backup as jb


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "trade_journal.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t (x INTEGER)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    for side in ("-wal", "-shm"):
        (tmp_path / f"trade_journal.db{side}").write_bytes(b"live")
    return p


def _touch(p: Path, mtime: int) -> Path:
    p.write_bytes(b"old")
    os.utime(p, (mtime, mtime))
    return p


def test_default_keep_is_one_per_tag_and_two_in_total():
    assert jb.KEEP_PER_PREFIX == 1
    assert jb.KEEP_TOTAL == 2


def test_total_cap_across_tags_keeps_fresh_plus_newest_other(db: Path):
    """AM-OPS review: per-tag N=1 alone lets 13 tags x 2.7 GB pile up; cap the total."""
    d = db.parent
    olds = [_touch(d / f"trade_journal.db.bak-{t}-1794330728", 1_000 + i)
            for i, t in enumerate(["prop-report-open", "prop-ticket-expire", "reduce-pnl", "own-fill-exits"])]
    tag_first = _touch(d / "trade_journal.db.reconcile-orphan-bak-20261101T000000Z", 5_000)  # newest other
    unrelated = _touch(d / "trade_journal.db.bak-prop-report-open-notastamp", 1_000)
    other_db = _touch(d / "trainer_store.db.bak-x-1794330728", 1_000)
    dest = jb.take_backup(str(db), "prop-report-close")
    assert Path(dest).exists() and tag_first.exists()
    assert not any(p.exists() for p in olds)
    assert unrelated.exists() and other_db.exists()
    for live in ("trade_journal.db", "trade_journal.db-wal", "trade_journal.db-shm"):
        assert (d / live).exists()
    assert len(jb.all_backups(str(db))) == 2


@pytest.mark.parametrize("method", ["online", "copy"])
def test_new_backup_is_a_readable_copy(db: Path, method: str):
    dest = jb.take_backup(str(db), "prop-report-close", method=method)
    assert Path(dest).name.startswith("trade_journal.db.bak-prop-report-close-")
    assert sqlite3.connect(dest).execute("SELECT x FROM t").fetchall() == [(1,)]


def test_prunes_older_same_tag_only(db: Path):
    d = db.parent
    old1 = _touch(d / "trade_journal.db.bak-prop-report-close-1794330728", 1_000)
    old2 = _touch(d / "trade_journal.db.bak-prop-report-close-20261101T000000Z", 2_000)
    other_tag = _touch(d / "trade_journal.db.bak-prop-report-open-1794330728", 1_000)
    # a tag that EXTENDS ours must never match ours
    ext = _touch(d / "trade_journal.db.bak-prop-report-close-extra-1794330728", 1_000)
    odd = _touch(d / "trade_journal.db.bak-prop-report-close-notastamp", 1_000)
    dest = jb.take_backup(str(db), "prop-report-close", keep_total=99)  # isolate the per-tag rule
    assert Path(dest).exists()
    assert not old1.exists() and not old2.exists()
    for keep in (other_tag, ext, odd):
        assert keep.exists()
    for live in ("trade_journal.db", "trade_journal.db-wal", "trade_journal.db-shm"):
        assert (d / live).exists()


def test_keep_two_keeps_new_plus_newest_old(db: Path):
    d = db.parent
    older = _touch(d / "trade_journal.db.bak-reduce-pnl-20261101T000000Z", 1_000)
    newer = _touch(d / "trade_journal.db.bak-reduce-pnl-20261102T000000Z", 2_000)
    dest = jb.take_backup(str(db), "reduce-pnl", method="copy", stamp_style="iso", keep=2)
    assert Path(dest).exists() and newer.exists() and not older.exists()


def test_tag_first_spelling(db: Path):
    d = db.parent
    old = _touch(d / "trade_journal.db.reconcile-orphan-bak-20261101T000000Z", 1_000)
    plain = _touch(d / "trade_journal.db.bak-reconcile-orphan-20261101T000000Z", 1_000)
    dest = jb.take_backup(str(db), "reconcile-orphan", method="copy", stamp_style="iso", tag_first=True)
    assert Path(dest).name.startswith("trade_journal.db.reconcile-orphan-bak-")
    assert not old.exists() and plain.exists()


def test_failed_backup_prunes_nothing(db: Path, monkeypatch):
    d = db.parent
    old = _touch(d / "trade_journal.db.bak-prop-report-skip-1794330728", 1_000)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(jb.shutil, "copy2", boom)
    with pytest.raises(OSError):
        jb.take_backup(str(db), "prop-report-skip", method="copy")
    assert old.exists()


def test_prune_error_does_not_fail_the_backup(db: Path, monkeypatch):
    d = db.parent
    _touch(d / "trade_journal.db.bak-prop-ticket-expire-1794330728", 1_000)
    real_remove = os.remove

    def flaky(p):
        if "1794330728" in str(p):
            raise PermissionError("nope")
        real_remove(p)

    monkeypatch.setattr(jb.os, "remove", flaky)
    dest = jb.take_backup(str(db), "prop-ticket-expire")
    assert Path(dest).exists()


@pytest.mark.parametrize("mod, func, tag", [
    ("prop_report_close", "_backup", "prop-report-close"),
    ("prop_report_open", "_backup", "prop-report-open"),
    ("prop_report_skip", "_backup", "prop-report-skip"),
    ("prop_ticket_expire", "_backup", "prop-ticket-expire"),
    ("prop_ticket_reissue", "_backup", "prop-ticket-reissue"),
    ("prop_fix_mislinked_close", "_backup_db", "prop-mislinked-close"),
    ("repair_prop_fill_direction", "_backup_db", "prop-fill-direction"),
    ("supersede_options_adoption_artifacts", "_backup_db", "supersede-options-artifacts"),
    ("supersede_intent_reduce_phantom_pnl", "_backup_db", "supersede-intent-reduce-phantom-pnl"),
    ("supersede_reset_orphan_artifacts", "_backup_db", "supersede-reset-orphan-artifacts"),
])
def test_every_writer_goes_through_the_shared_helper(db: Path, mod: str, func: str, tag: str):
    import importlib
    m = importlib.import_module(f"scripts.ops.{mod}")
    old = _touch(db.parent / f"trade_journal.db.bak-{tag}-1000", 1_000)
    dest = getattr(m, func)(str(db))
    assert Path(dest).name.startswith(f"trade_journal.db.bak-{tag}-")
    assert not old.exists()


def test_reconcile_orphan_history_goes_through_the_shared_helper(db: Path):
    from scripts.ops import reconcile_orphan_history as m
    old = _touch(db.parent / "trade_journal.db.reconcile-orphan-bak-20261101T000000Z", 1_000)
    dest = m._backup_db(str(db))
    assert Path(dest).name.startswith("trade_journal.db.reconcile-orphan-bak-")
    assert not old.exists()


def test_no_writer_hand_rolls_a_bak_copy():
    """Every `.bak-` journal copy in scripts/ops goes through take_backup (the regrowth's cause)."""
    root = Path(__file__).resolve().parents[2] / "scripts" / "ops"
    offenders = []
    for p in root.glob("*.py"):
        if p.name == "journal_backup.py":
            continue
        s = p.read_text()
        if ('.bak-' in s or '-bak-' in s) and ("shutil.copy2(db_path" in s or ".backup(dst)" in s):
            offenders.append(p.name)
    assert offenders == []
