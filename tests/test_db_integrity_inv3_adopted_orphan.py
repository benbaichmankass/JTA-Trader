"""INV-3 narrows to exclude RESOLVED adopted orphans (2026-11-20, manager decision).

Measured case: ib_paper MGC trade 7735 (paper). The orphan adopter wrote it
2026-11-18T07:42:12Z for a venue position no journal row owned
(strategy_name='orphan_adopt', setup_type='adopted_orphan'), so it had no order
package by construction. The exit-coverage resolver flattened it at 07:45:10Z
(exit_reason='exit_coverage_no_strategy'). INV-3 then flagged it as a missing
package link: a by-design row, not a write-path bug.

Contract:
* a closed adopted orphan WITH an exit_reason is exempt from INV-3 and counted by INV-3b;
* an adopted orphan with no exit_reason still flags;
* an adopted orphan still open past ADOPTED_ORPHAN_OPEN_GRACE_HOURS still flags;
* an ordinary unlinked row still flags;
* INV-3b never alerts but always counts (the exemption is not a mute button);
* a journal without setup_type runs the original INV-3 unchanged.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta, timezone


def _load():
    spec = importlib.util.spec_from_file_location("check_db_integrity", "scripts/check_db_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CDI = _load()
_NOW = datetime(2026, 11, 20, 4, 0, 0, tzinfo=timezone.utc)

_SCHEMA = """
CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, status TEXT, pnl REAL,
  is_backtest INTEGER DEFAULT 0, account_class TEXT, order_package_id TEXT, closed_at TEXT,
  created_at TEXT, timestamp TEXT, notes TEXT, setup_type TEXT, strategy_name TEXT, exit_reason TEXT);
CREATE TABLE order_packages (order_package_id TEXT PRIMARY KEY, linked_trade_id INTEGER, status TEXT,
  updated_at TEXT);
"""


def _iso(dt):
    return dt.isoformat()


def _row_7735(**over):
    """Trade 7735's shape (paper), with ids and times relative to _NOW."""
    created = _NOW - timedelta(hours=2)
    r = {"id": 7735, "account_id": "ib_paper", "symbol": "MGC", "status": "closed", "pnl": 124.04,
         "account_class": "paper", "order_package_id": None, "closed_at": _iso(created + timedelta(minutes=3)),
         "created_at": _iso(created), "timestamp": _iso(created),
         "notes": json.dumps({"closed_by": "exit_coverage_resolver", "pnl_source": "local_compute"}),
         "setup_type": "adopted_orphan", "strategy_name": "orphan_adopt",
         "exit_reason": "exit_coverage_no_strategy"}
    r.update(over)
    return r


def _checks(tmp_path, rows, schema=_SCHEMA):
    db = tmp_path / "j.db"
    c = sqlite3.connect(str(db))
    c.executescript(schema)
    for r in rows:
        cols = [k for k in r if k in {x[1] for x in c.execute("PRAGMA table_info(trades)")}]
        c.execute(f"INSERT INTO trades ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                  [r[k] for k in cols])
    c.commit()
    c.close()
    rep = CDI.run_checks(str(db), window_hours=24, now=_NOW)
    return {k["id"]: k for k in rep["checks"]}


def test_resolved_adopted_orphan_is_exempt_and_counted(tmp_path):
    ch = _checks(tmp_path, [_row_7735()])
    assert ch["INV-3"]["total_count"] == 0 and ch["INV-3"]["alert"] is False
    assert ch["INV-3b"]["total_count"] == 1 and ch["INV-3b"]["sample_ids"] == [7735]
    assert ch["INV-3b"]["alert"] is False


def test_adopted_orphan_without_exit_reason_still_flags(tmp_path):
    for i, er in enumerate((None, "")):
        d = tmp_path / f"d{i}"
        d.mkdir()
        ch = _checks(d, [_row_7735(exit_reason=er)])
        assert ch["INV-3"]["total_count"] == 1 and ch["INV-3"]["alert"] is True
        assert ch["INV-3b"]["total_count"] == 0


def test_adopted_orphan_open_past_the_grace_still_flags(tmp_path):
    old = _NOW - timedelta(hours=CDI.ADOPTED_ORPHAN_OPEN_GRACE_HOURS + 0.5)
    ch = _checks(tmp_path, [_row_7735(status="open", exit_reason=None, closed_at=None,
                                      created_at=_iso(old), timestamp=_iso(old))])
    assert ch["INV-3"]["total_count"] == 1 and ch["INV-3"]["alert"] is True


def test_adopted_orphan_open_inside_the_grace_is_exempt(tmp_path):
    fresh = _NOW - timedelta(minutes=5)
    ch = _checks(tmp_path, [_row_7735(status="open", exit_reason=None, closed_at=None,
                                      created_at=_iso(fresh), timestamp=_iso(fresh))])
    assert ch["INV-3"]["total_count"] == 0 and ch["INV-3b"]["total_count"] == 1


def test_an_ordinary_unlinked_row_still_flags(tmp_path):
    ch = _checks(tmp_path, [_row_7735(id=1, setup_type="ict_fvg", strategy_name="x")])
    assert ch["INV-3"]["total_count"] == 1 and ch["INV-3b"]["total_count"] == 0


def test_journal_without_setup_type_runs_the_original_check(tmp_path):
    schema = _SCHEMA.replace(", setup_type TEXT, strategy_name TEXT, exit_reason TEXT", "")
    ch = _checks(tmp_path, [_row_7735()], schema=schema)
    assert ch["INV-3"]["total_count"] == 1
    assert ch["INV-3b"]["total_count"] == 0


def test_adoption_provenance_survives_the_close_write_cap():
    """7735's close write left adopted_at/adopted_by as "": a 7735-shaped blob must keep them."""
    from src.utils.json_notes import dump_capped
    notes = {"adopted_at": "2026-11-18T07:42:12.206015+00:00", "adopted_by": "reverse_reconciler",
             "adopted_reason": "exchange reported an open MGC position on ib_paper with no matching "
                               "trades.status='open' row; no originating order package recovered — bare adopt",
             "exchange_entry_price": 3767.0192, "exchange_size": 5.0,
             "closed_at": "2026-11-18T07:45:10.635579+00:00", "closed_by": "exit_coverage_resolver",
             "closed_reason": "no recoverable strategy / order package — flattened (exit-coverage reattach-or-close)",
             "exchange_close_skipped": None, "close_fees_usd": 0.0, "exit_price_source": "exchange_fill",
             "pnl_source": "local_compute", "contract_value_usd": 10.0}
    out = json.loads(dump_capped(notes, 500))
    assert out["adopted_at"] == notes["adopted_at"] and out["adopted_by"] == "reverse_reconciler"
