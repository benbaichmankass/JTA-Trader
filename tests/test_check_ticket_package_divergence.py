"""scripts/ops/check_ticket_package_divergence.py — a prop ticket still open while its package is closed
(PHONE-AMEND-REFUSED-1025: breakout_2 prop-manual-2e786ef17c05, 2026-10-25)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ctpd", ROOT / "scripts/ops/check_ticket_package_divergence.py")
ctpd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctpd)


def _t(status, op_status, **kw):
    return {"account_id": "breakout_2", "ticket_id": "T", "order_package_id": "pkg", "status": status,
            "op_status": op_status, **kw}


def test_the_incident_shape_is_found():
    rows = ctpd.divergent([_t("filled", "closed", close_reason="sl_cross",
                              phone_trail={"amend_id": "T#a6", "amend_status": "refused", "fails": 6})])
    assert len(rows) == 1 and rows[0]["close_reason"] == "sl_cross" and rows[0]["fails"] == 6


def test_consistent_tickets_are_not_divergent():
    assert ctpd.divergent([_t("closed", "closed"), _t("filled", "open"), _t("placed", "emitted"),
                           _t("suppressed", "closed"), _t("skipped", "closed"), _t("filled", None)]) == []


def test_placed_counts_as_open():
    assert len(ctpd.divergent([_t("placed", "closed")])) == 1


def test_every_prop_account_is_in_the_population():
    accts = ctpd.prop_accounts()
    assert {"breakout_2", "tradeify_1", "velotrade_1"} <= set(accts)
