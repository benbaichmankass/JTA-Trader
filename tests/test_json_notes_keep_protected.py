"""DUMP-CAPPED-DROPS-PROTECTED (2026-11-20): when the protected keys alone exceed
the cap, dump_capped must degrade gradually and loudly, never delete every
protected key at once. Live trade 7131 (alpaca_paper USO, closed 2026-11-16)
stores notes of exactly {"_truncated": true}."""
from __future__ import annotations

import json
import logging

from src.utils.json_notes import dump_capped


def _close_notes() -> dict:
    # A 7131-shaped close: many protected stamps plus long protected prose.
    return {
        "trade_id": "8d1b6a2c-1f3e-4c2a-9b7e-3a5d0c2e9f11",
        "closed_at": "2026-11-16T14:35:52.198271+00:00",
        "closed_by": "stuck_strategy_watchdog",
        "closed_reason": "watchdog — position flat at exchange; broker closed-pnl unmatched " * 4,
        "exit_price_source": "exchange_fill",
        "exit_reason_source": "price_vs_pkg_bracket",
        "pnl_source": "local_compute",
        "pre_label_exit_reason": "stuck_strategy_watchdog",
        "broker_leg_read": "no_filled_leg",
        "entry_price_source": "fill",
        "entry_price_source_reason": "alpaca_order_status filled_avg_price",
        "package_entry": "142.31",
        "junk": "x" * 3000,
    }


def test_protected_strings_shortened_before_any_key_is_lost():
    out = dump_capped(_close_notes(), 420)
    d = json.loads(out)
    assert len(out) <= 420
    # the close stamps survive WHOLE (an id or timestamp is never cut, only dropped whole)
    assert d["closed_at"] == "2026-11-16T14:35:52.198271+00:00"
    for k in ("closed_by", "exit_price_source", "pnl_source", "exit_reason_source"):
        assert d[k] == _close_notes()[k], (k, d)
    assert d["closed_reason"].endswith("…")          # protected prose shortened, kept
    assert d["_truncated"] is True and "junk" not in d


def test_keys_shed_one_at_a_time_and_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="src.utils.json_notes"):
        out = dump_capped(_close_notes(), 160)
    d = json.loads(out)
    assert len(out) <= 160
    kept = [k for k in d if k != "_truncated"]
    assert kept, d                      # NOT the bare marker
    assert "protected key(s)" in caplog.text and "dropped" in caplog.text


def test_bare_marker_only_when_nothing_fits_and_it_is_loud(caplog):
    with caplog.at_level(logging.WARNING, logger="src.utils.json_notes"):
        out = dump_capped({"closed_at": "2026-06-19T10:00:00+00:00", "big": "q" * 999}, 20)
    assert json.loads(out) == {"_truncated": True}
    assert "EVERY protected key lost" in caplog.text


def test_no_warning_when_unprotected_trimming_suffices(caplog):
    with caplog.at_level(logging.WARNING, logger="src.utils.json_notes"):
        out = dump_capped({"closed_at": "2026-06-19T10:00:00+00:00", "junk": "z" * 4000}, 120)
    assert json.loads(out)["closed_at"] == "2026-06-19T10:00:00+00:00"
    assert caplog.text == ""


def _row_8034_shape() -> dict:
    """Trade 8034's stored notes as read 2026-11-20 (/api/diag/journal, 499 chars at a 500 cap),
    with the reconciler's full ~330-char closed_reason restored and one more marker added, i.e.
    the next writer on a row already at the cap."""
    return {
        "closed_at": "2026-11-19T21:02:11.850350+00:00",
        "closed_by": "position_snapshot_reconciler",
        "reset_event": False,
        "closed_reason": ("(symbol, side) confirmed absent from the exchange open-positions snapshot "
                          "across two observations AND, where the integration supports it, by a direct "
                          "per-symbol broker check (alpaca 404); integration has no per-order status "
                          "reader (non-Bybit). PnL filled by the local-PnL sweep (mark-to-market)."),
        "broker_leg_read": "no_filled_leg",
        "pnl_source": "unmeasured",
        "unmeasured_reason": "entry_unfilled",
        "pre_mark_exit_reason": "exchange_flat_reconciled",
        "entry_unfilled_marked_at": "2026-11-20T06:43:44+00:00",
        "entry_unfilled_venue": "order 10fd4469-aa7: terminal expired, filled_qty 0",
        "entry_unfilled_reason": "Repair trade 8034's notes (paper): the DAY mleg entry expired unfilled",
        "exit_price_source": "unmeasured",
        "exit_reason_source": "venue_order_status",
    }


def test_the_8034_shape_keeps_its_close_stamps_whole_at_the_live_500_cap():
    raw = dump_capped(_row_8034_shape(), 500)
    d = json.loads(raw)
    assert len(raw) <= 500
    src = _row_8034_shape()
    for k in ("closed_at", "closed_by", "pnl_source", "exit_price_source",
              "exit_reason_source", "pre_mark_exit_reason", "broker_leg_read"):
        assert d.get(k) == src[k], (k, d)
