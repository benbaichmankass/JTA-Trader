"""BL-20260619-ETHMIN — sub-venue-min qty is a clean per-trade risk refusal.

Reproduces the bybit_2 ETHUSDT churn (6 rejections on 2026-06-19): a
~$100 real-money balance at ~0.26% per-trade risk sizes ~0.005-0.007 ETH,
which is below Bybit's ETHUSDT ``minOrderQty`` of 0.01. Pre-fix that
sub-min qty reached the ``_submit_order`` pre-flight and was journaled as
``status='exchange_rejected'`` on every recurring signal — noisy churn
that looks like a broker/exec failure.

The fix refuses the order at the sizing/risk layer in the coordinator with
a clean ``status='rejected'`` row and a distinct ``below_venue_min_qty``
cause, NOT an ``exchange_rejected`` fill row. The qty is never floored UP
(that would silently exceed the configured risk). The account stays live
(Prime Directive) — only this one trade is refused.

Exercised end-to-end: ``Coordinator.multi_account_execute`` routes a sub-min
sized qty through the clean-refusal path with the ``below_venue_min_qty`` token.

The per-symbol venue-minimum RESOLUTION now lives in the one seam,
``src/units/accounts/qty_legalize.py`` (``legalize_qty`` / ``instrument_lot``);
the sizing-layer ``execute.venue_min_qty_for`` copy was retired in Phase 4 of the
qty-legalization consolidation (``docs/sizing-legalization-DESIGN.md``). Direct
resolver-matrix coverage now lives in ``tests/test_qty_legalize.py``; this file
keeps the live-path integration regression that proves the seam is wired into the
coordinator's clean refusal.
"""
from __future__ import annotations

import sqlite3
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from src.core.coordinator import Coordinator, OrderPackage
from src.units.accounts import precision
from src.units.accounts.execute import BelowVenueMinQtyRefusal, _submit_order
from src.units.accounts.qty_legalize import LegalizedQty


@pytest.fixture(autouse=True)
def _clean_caches():
    precision._LOT_CACHE.clear()
    precision._LIVE_CACHE.clear()
    yield
    precision._LOT_CACHE.clear()
    precision._LIVE_CACHE.clear()


# --- Coordinator integration: live path routes sub-min through clean refusal ---

_ACCOUNTS_YAML = textwrap.dedent("""\
    accounts:
      bybit_2:
        type: regular
        exchange: bybit
        market_type: linear
        account_class: real_money
        api_key_env: BYBIT_KEY_2
        strategies: [eth_pullback_2h]
        risk:
          max_dd_pct: 0.05
          daily_usd: 100
          pos_size: 500
          risk_pct: 0.01
          min_balance_usd: 50
""")


def _eth_pkg() -> OrderPackage:
    return OrderPackage(
        strategy="eth_pullback_2h",
        symbol="ETHUSDT",
        direction="short",
        entry=1700.0,
        sl=1740.0,
        tp=1620.0,
        confidence=0.42,
        meta={"strategy_name": "eth_pullback_2h", "entry_reason": "pullback signal"},
    )


@pytest.fixture(autouse=True)
def _stub_account_creds(monkeypatch):
    monkeypatch.setenv("BYBIT_KEY_2", "test-value")
    monkeypatch.setenv("BYBIT_KEY_2_SECRET", "test-secret")


@pytest.fixture()
def accounts_yaml(tmp_path):
    p = tmp_path / "accounts.yaml"
    p.write_text(_ACCOUNTS_YAML)
    return str(p)


@pytest.fixture()
def coord(tmp_path):
    units_yaml = tmp_path / "units.yaml"
    units_yaml.write_text("units: {}\n")
    return Coordinator(units_path=str(units_yaml))


@pytest.fixture()
def tmp_journal(tmp_path, monkeypatch):
    db_path = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db_path))
    return db_path


def _rejected_rows(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT account_id, strategy_name, status, entry_reason "
            "FROM trades"
        ).fetchall()]
    finally:
        conn.close()


class TestCoordinatorVenueMinRefusal:
    def test_sub_min_eth_qty_sized_up_not_refused(
        self, coord, accounts_yaml, tmp_journal,
    ):
        # REVERSED 2026-11-09 (operator, Tier 3): a sub-venue-min qty (0.006 ETH
        # < 0.01 minOrderQty) is no longer refused at the coordinator guard; it
        # proceeds to dispatch, where the seam sizes it up in _submit_order.
        seen = {}

        def _fake_exec(pkg, account_cfg, *a, **kw):
            seen["called"] = True
            return "T-1"

        with patch(
            "src.units.accounts.risk.RiskManager.position_size",
            return_value=0.006,
        ), patch(
            "src.strategy_registry.execution_mode", return_value="live",
        ), patch(
            "src.units.accounts.clients.bybit_client_for",
            return_value=object(),
        ), patch(
            "src.units.accounts.execute.execute_pkg", side_effect=_fake_exec,
        ):
            coord.multi_account_execute(
                _eth_pkg(),
                accounts_path=accounts_yaml,
                balance_fetcher=lambda _a: 100.0,
            )

        assert seen.get("called") is True
        assert not [r for r in _rejected_rows(tmp_journal)
                    if "below_venue_min_qty" in (r["entry_reason"] or "")]

    def test_submit_order_leak_path_routes_benign_no_ping(
        self, coord, accounts_yaml, tmp_journal,
    ):
        # Covers the LEAK the fix targets: the sized-path pre-check's venue-min
        # lookup returns None (rule unknown at gate time), so the refusal only
        # surfaces at _submit_order as a BelowVenueMinQtyRefusal. The coordinator
        # must route that typed exception to the benign skip — a clean 'rejected'
        # row, no failure ping, and NOT an 'exchange_rejected' fill.
        def _no_rule(qty, **_kw):
            return LegalizedQty(
                qty=qty, ok=True, reason="", venue_min=None, step=None,
                source="unknown", qty_str=str(float(qty)),
            )

        with patch(
            "src.units.accounts.risk.RiskManager.position_size",
            return_value=0.006,
        ), patch(
            "src.strategy_registry.execution_mode",
            return_value="live",
        ), patch(
            "src.units.accounts.clients.bybit_client_for",
            return_value=object(),
        ), patch(
            # venue-min unknown → pre-check is skipped, refusal leaks to submit.
            "src.units.accounts.qty_legalize.legalize_qty",
            side_effect=_no_rule,
        ), patch(
            "src.units.accounts.execute.execute_pkg",
            side_effect=BelowVenueMinQtyRefusal(
                "qty 0.006 for ETHUSDT is below the exchange lot minimum "
                "after step-alignment — refusing pre-flight."
            ),
        ), patch(
            "src.core.coordinator._emit_execution_failure_ping",
        ) as ping:
            coord.multi_account_execute(
                _eth_pkg(),
                accounts_path=accounts_yaml,
                balance_fetcher=lambda _a: 100.0,
            )

        ping.assert_not_called()
        rows = _rejected_rows(tmp_journal)
        assert len(rows) == 1
        assert rows[0]["status"] == "rejected"
        assert rows[0]["status"] != "exchange_rejected"
        assert "below_venue_min_qty" in (rows[0]["entry_reason"] or "")


class TestSubmitOrderSubMinRefusal:
    """_submit_order raises the TYPED benign exception (not a plain
    RuntimeError routed through report_api_failure) — BL-20260716-BYBIT2-SUBMIN-QTY.
    """

    def test_refusal_is_runtime_error_subclass(self):
        # Guarantees existing ``except RuntimeError`` callers are unaffected.
        assert issubclass(BelowVenueMinQtyRefusal, RuntimeError)

    def test_submit_order_submin_raises_typed_without_report_api_failure(self):
        account_cfg = {"exchange": "bybit", "market_type": "linear",
                       "account_id": "bybit_2"}
        order = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.00037473,
                 "sl": None, "tp": None}
        sub_min = LegalizedQty(
            qty=0.0, ok=False, reason="below_venue_min_qty",
            venue_min=0.001, step=0.001, source="live_lot_rule", qty_str="0.000",
        )
        with patch(
            "src.units.accounts.execute.get_tick_size", return_value=0.1,
        ), patch(
            "src.units.accounts.qty_legalize.legalize_qty", return_value=sub_min,
        ), patch(
            "src.runtime.api_reporting.report_api_failure",
        ) as report:
            with pytest.raises(BelowVenueMinQtyRefusal):
                _submit_order(MagicMock(), order, account_cfg)

        # The benign refusal must NOT be reported as an API/place-order failure
        # (that is the ERROR-level ``bybit_place_order_failed`` banner row).
        report.assert_not_called()
