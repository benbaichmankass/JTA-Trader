"""PI-20261119-IXACGZFL-0002: the --live fault intake pages the diag journal until its window is covered.

A fixed 300-row read let faulted trades age out unfiled (2026-11-19: a 72 h re-run read 26 closed trades
against 29 read by an earlier 48 h run). The journal is newest-first by id, the window is by closed_at."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))

import mechanics_fault_intake as fi  # noqa: E402

NOW = datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc)
CUT = (NOW - timedelta(hours=72)).isoformat()


def _row(i, opened, closed=None, status="closed"):
    return {"id": i, "status": status, "is_backtest": 0, "timestamp": opened.isoformat(),
            "closed_at": closed.isoformat() if closed else None}


class Pages:
    def __init__(self, rows, page=4):
        self.rows, self.page, self.offsets = rows, page, []

    def __call__(self, offset):
        self.offsets.append(offset)
        return self.rows[offset:offset + self.page]


def test_pages_past_the_old_300_cap_and_keeps_an_old_trade_closed_in_the_window(monkeypatch):
    monkeypatch.setattr(fi, "PAGE", 4)
    rows = [_row(100 - k, NOW - timedelta(hours=k), None, status="open") for k in range(9)]
    # an OLD trade (opened 10 days ago, low id, deep in the history) that CLOSED inside the window
    rows.append(_row(50, NOW - timedelta(days=10), NOW - timedelta(hours=1)))
    rows += [_row(40 - k, NOW - timedelta(days=20 + k), NOW - timedelta(days=19)) for k in range(4)]
    f = Pages(rows)
    closed, cov = fi._live_trades(CUT, fetch=f)
    assert [r["id"] for r in closed] == [50]
    assert cov["state"] == "complete" and cov["pages"] == 3 and f.offsets == [0, 4, 8]


def test_short_page_is_exhausted_history():
    rows = [_row(3, NOW - timedelta(hours=2), NOW - timedelta(hours=1))]
    closed, cov = fi._live_trades(CUT, fetch=Pages(rows, page=fi.PAGE))
    assert [r["id"] for r in closed] == [3] and cov["state"] == "exhausted" and cov["pages"] == 1


def test_page_cap_is_reported_truncated_never_complete(monkeypatch):
    monkeypatch.setattr(fi, "PAGE", 2)
    monkeypatch.setattr(fi, "MAX_PAGES", 3)
    rows = [_row(100 - k, NOW - timedelta(minutes=k), NOW - timedelta(minutes=k)) for k in range(20)]
    closed, cov = fi._live_trades(CUT, fetch=Pages(rows, page=2))
    assert cov["state"] == "truncated" and cov["rows_read"] == 6 and len(closed) == 6


def test_a_failed_page_raises_could_not_look():
    def boom(offset):
        raise RuntimeError("diag_fetch rc=3")
    try:
        fi._live_trades(CUT, fetch=boom)
    except RuntimeError:
        return
    raise AssertionError("a failed read must raise, never return an empty population")
