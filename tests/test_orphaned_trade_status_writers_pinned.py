"""ORDER-AUDIT-4 item 21 (PI-20260930-MEK2XMWT-0003) — pin who may write
``trades.status = 'orphaned'``.

`orphaned` is TERMINAL for the open-package gate (`order_monitor.
_TERMINAL_TRADE_STATUSES`, `strategy_monocle._TERMINAL_LEG_STATUSES`). That is
only safe while every writer of the status has first established that the row
holds no venue position. MEASURED 2026-10-15 (diag journal trades ids
2631-6630, exchange_positions):
- 16 orphaned rows, all written 2026-06-17..07-06, none since.
- Every venue position on the readable accounts equals its open-row qty (0
  untracked).
- The one live writer is `_mark_orphaned`, called only from
  `_reconcile_open_trades` in two cases. The first is an order `not_found`
  whose (symbol, side) is absent from a READABLE snapshot twice (FIX-CA-04).
  The second is a terminal zero-fill order, which never opened a position.
  The predicate is recorded on the row (`notes.orphaned_reason`).

So no flat/unknown split is needed today. This test makes a NEW writer, or a
caller that does not say its predicate, fail CI instead of silently creating
the position-unknown case the pipeline item described.
"""
from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_OM = _SRC / "runtime" / "order_monitor.py"


def _py_sources():
    for p in _SRC.rglob("*.py"):
        yield p, p.read_text(encoding="utf-8", errors="replace")


def test_only_mark_orphaned_writes_the_trade_status():
    writes = []
    pat = re.compile(r"""["']status["']\s*:\s*["']orphaned["']""")
    for p, text in _py_sources():
        for m in pat.finditer(text):
            writes.append((p.relative_to(_SRC).as_posix(),
                           text.count("\n", 0, m.start()) + 1))
    assert [w[0] for w in writes] == ["runtime/order_monitor.py"], writes
    om = _OM.read_text()
    fn = om.index("def _mark_orphaned(")
    nxt = om.index("\ndef ", fn + 1)
    assert fn < om.index('"status": "orphaned"') < nxt, (
        "the only trades.status='orphaned' write must live in _mark_orphaned")


def test_mark_orphaned_has_one_caller_and_it_states_its_predicate():
    calls = []
    for p, text in _py_sources():
        for m in re.finditer(r"(?<!def )_mark_orphaned\(", text):
            calls.append((p.relative_to(_SRC).as_posix(),
                          text[m.start():m.start() + 80]))
    assert len(calls) == 1, calls
    assert calls[0][0] == "runtime/order_monitor.py"
    assert "reason=_orphan_reason" in calls[0][1], calls


def test_the_not_found_branch_requires_a_readable_absent_position_twice():
    om = _OM.read_text()
    i = om.index('"reconciler — order not_found + position absent "')
    block = om[om.rindex('if status_str == "not_found" or filled_qty <= 0:', 0, i):i]
    assert "if positions_cache is None:" in block          # could not look -> skip
    assert "in unreadable_syms" in block                   # FIX-CA-08
    assert "in positions_cache" in block                   # live -> stay open
    assert "_close_confirm_seconds()" in block             # absent twice
