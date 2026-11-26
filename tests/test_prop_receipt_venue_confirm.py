"""LTR-PROP-CLOSE-FALSE-APPLIED (2026-11-26): a prop-VM / phone live-review request is only RECORDED on the ticket; the
venue confirmation is the account executor's (or phone's) own later report. The receipt must never call it a verified
read-back.

Measured: LR-20261115T1141Z-pkg-ec406687dc6d449f, tradeify_1 [prop_vm] APPLIED with disposition verified_readback true,
while the terminal still held the SOL position; the venue close came 204 min later. Each test fails on the pre-fix code.
"""
from __future__ import annotations

import types

from scripts.ops import live_review_apply as lra
from scripts.ops import live_review_dispatch as d


def _intent(**kw):
    base = dict(mandate="MD-TRADE-DESK", review_id="LR-T", action="close")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_prop_vm_close_is_queued_not_venue_verified(monkeypatch):
    from src.prop import vm_close

    monkeypatch.setattr(vm_close, "request_close",
                        lambda *a, **k: {"result": vm_close.R_QUEUED, "close_id": "vmc-1", "detail": "recorded"})
    leg = {"row": {"ticket_id": "T1", "account_id": "tradeify_1"}}
    res = lra._exec_prop_vm_close(leg, "close", _intent())
    assert res["result"] == lra.X_APPLIED            # control flow unchanged: the request was placed
    assert res["venue_confirmed"] is False          # but it is not a venue read-back
    assert "vm_close_done" in res["venue_confirmed_by"]
    assert lra._venue_verified(res) is False


def test_venue_readback_executors_still_verify():
    # A Bybit / Alpaca executor returns a venue read-back (no venue_confirmed key): still verified.
    assert lra._venue_verified({"result": lra.X_APPLIED, "venue_after": 1.0}) is True
    assert lra._venue_verified({"result": lra.X_APPLY_FAILED}) is False
    assert lra._venue_verified({"result": lra.X_APPLIED, **lra._venue_pending("x")}) is False


def test_receipt_line_reads_queued_for_a_ticket_request():
    entry = {
        "account_reads": [{"account_id": "tradeify_1", "account_class": "prop", "read": "would_apply", "evidence": "e"},
                          {"account_id": "bybit_2", "account_class": "real_money", "read": "would_apply",
                           "evidence": "e"}],
        "accounts_applied": [
            {"account_id": "tradeify_1", "level": None,
             "executor": {"result": lra.X_APPLIED, "close_id": "vmc-1", **lra._venue_pending("vm_close_done")}},
            {"account_id": "bybit_2", "level": None, "executor": {"result": lra.X_APPLIED, "venue_size_after": 0.0}},
        ],
        "disposition": {"route": "auto_applied", "verified_readback": False, "venue_unconfirmed": ["tradeify_1"]},
    }
    lines = d.summarize(entry)
    assert lines[0].startswith(">>> tradeify_1 [prop]: QUEUED")
    assert lines[1].startswith(">>> bybit_2 [real_money]: APPLIED")
