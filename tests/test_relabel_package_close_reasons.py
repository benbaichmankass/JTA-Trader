"""relabel_package_close_reasons: fixed ids, unanimous sl/tp, conditional, idempotent."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import relabel_package_close_reasons as rp

A, B, C, D = rp.TARGET_IDS[:4]


def _db(tmp_path, pkgs, trades):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE order_packages (order_package_id TEXT, status TEXT, "
              "close_reason TEXT, linked_trade_id INT, meta TEXT)")
    c.execute("CREATE TABLE trades (id INT, order_package_id TEXT, status TEXT, exit_reason TEXT)")
    c.executemany("INSERT INTO order_packages VALUES (?,?,?,?,?)", pkgs)
    c.executemany("INSERT INTO trades VALUES (?,?,?,?)", trades)
    c.commit()
    c.close()
    return str(p)


def _read(db, pid):
    c = sqlite3.connect(db)
    r = c.execute("SELECT close_reason, meta FROM order_packages WHERE order_package_id=?",
                  (pid,)).fetchone()
    c.close()
    return r


def test_relabels_keeps_prior_and_is_idempotent(tmp_path, capsys):
    db = _db(tmp_path,
             [(A, "closed", "reconciler_filled", 1, '{"x": 1}')],
             [(1, A, "closed", "sl"), (2, A, "closed", "sl")])
    assert rp.main(["--db", db]) == 0           # dry run writes nothing
    assert _read(db, A)[0] == "reconciler_filled"
    assert rp.main(["--db", db, "--apply"]) == 0
    reason, meta = _read(db, A)
    assert reason == "sl" and json.loads(meta) == {"x": 1, "pre_label_close_reason": "reconciler_filled"}
    assert rp.main(["--db", db, "--apply"]) == 0   # re-run: no-op, prior value not clobbered
    assert json.loads(_read(db, A)[1])["pre_label_close_reason"] == "reconciler_filled"


def test_mixed_or_non_true_labels_are_refused(tmp_path):
    db = _db(tmp_path,
             [(A, "closed", "reconciler_filled", 1, None),
              (B, "closed", "reconciler_filled", 3, None),
              (C, "closed", "reconciler_filled", 5, None)],
             [(1, A, "closed", "sl"), (2, A, "closed", "tp"),          # mixed
              (3, B, "closed", "operator_flatten_reconciled"),          # not sl/tp
              (5, C, "open", "sl")])                                    # trade not closed
    assert rp.main(["--db", db, "--apply"]) == 0
    for pid in (A, B, C):
        assert _read(db, pid)[0] == "reconciler_filled"


def test_real_close_reason_is_never_overwritten_and_other_ids_untouched(tmp_path):
    other = "pkg-not-in-the-list"
    db = _db(tmp_path,
             [(A, "closed", "e4_time_stop_24h", 1, None),
              (other, "closed", "reconciler_filled", 9, None)],
             [(1, A, "closed", "sl"), (9, other, "closed", "sl")])
    rp.main(["--db", db, "--apply"])
    assert _read(db, A)[0] == "e4_time_stop_24h"
    assert _read(db, other)[0] == "reconciler_filled"


def test_missing_package_is_refused_not_crash(tmp_path):
    db = _db(tmp_path, [], [])
    assert rp.main(["--db", db, "--apply"]) == 0


def test_thirteen_unique_ids():
    assert len(rp.TARGET_IDS) == len(set(rp.TARGET_IDS)) == 13
