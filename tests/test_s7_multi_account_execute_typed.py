"""Tests for S7 (M11): multi_account_execute_typed on Coordinator.

Validates:
  - multi_account_execute_typed delegates each typed pkg to multi_account_execute
  - flat packages are skipped
  - empty list returns []
  - multiple packages produce concatenated results
  - legacy_pkg fields are correctly mapped from typed pkg
  - meta['allocator_qty'] is set from typed pkg qty
  - pipeline typed dispatch path calls multi_account_execute_typed (flag on)
  - pipeline fallback when allocator returns empty (flag on)
  - pipeline legacy path when flag off
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Minimal stubs — no coordinator import needed for pure-unit tests
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _FakeTypedPkg:
    strategy_id: str = "ict_scalp_5m"
    symbol: str = "BTCUSDT"
    side: str = "long"
    entry_price: float = 100.0
    stop_loss: float = 98.0
    take_profit: float = 106.0
    qty: float = 0.5
    account_id: str = ""
    order_type: str = "market"
    timestamp_utc: str = ""
    attribution: dict = dataclasses.field(default_factory=dict)

    @property
    def is_flat(self) -> bool:
        return self.qty == 0.0 or self.side == "none"


# ---------------------------------------------------------------------------
# multi_account_execute_typed unit tests (coordinator stubbed)
# ---------------------------------------------------------------------------

class TestMultiAccountExecuteTyped:
    """Pure-unit tests — coordinator.multi_account_execute is stubbed."""

    def _make_coord(self, execute_return: List[Dict[str, Any]]):
        from src.core.coordinator import Coordinator, OrderPackage

        coord = Coordinator.__new__(Coordinator)
        coord._allocator = None
        coord._units_path = ""
        coord._accounts_path = ""
        coord._instruments_path = ""
        coord._cfg = {}
        coord._shadow_predictors_cache = {}

        # Capture calls to multi_account_execute
        captured: List[OrderPackage] = []

        def _fake_execute(pkg, accounts_path=None, **kwargs):
            captured.append(pkg)
            return execute_return

        coord.multi_account_execute = _fake_execute
        return coord, captured

    def test_empty_list_returns_empty(self):
        coord, captured = self._make_coord([])
        result = coord.multi_account_execute_typed([])
        assert result == []
        assert captured == []

    def test_single_pkg_delegates_to_execute(self):
        from src.core.coordinator import OrderPackage
        coord, captured = self._make_coord([{"name": "bybit_1", "status": "ok"}])
        typed = _FakeTypedPkg()
        result = coord.multi_account_execute_typed([typed])
        assert result == [{"name": "bybit_1", "status": "ok"}]
        assert len(captured) == 1
        legacy = captured[0]
        assert isinstance(legacy, OrderPackage)
        assert legacy.strategy == "ict_scalp_5m"
        assert legacy.symbol == "BTCUSDT"
        assert legacy.direction == "long"
        assert legacy.entry == 100.0
        assert legacy.sl == 98.0
        assert legacy.tp == 106.0
        assert legacy.confidence == 0.0

    def test_allocator_qty_stored_in_meta(self):
        coord, captured = self._make_coord([])
        typed = _FakeTypedPkg(qty=2.75)
        coord.multi_account_execute_typed([typed])
        assert captured[0].meta == {"allocator_qty": 2.75}

    def test_flat_pkg_skipped(self):
        coord, captured = self._make_coord([{"status": "ok"}])
        flat = _FakeTypedPkg(qty=0.0)
        result = coord.multi_account_execute_typed([flat])
        assert result == []
        assert captured == []

    def test_side_none_pkg_skipped(self):
        coord, captured = self._make_coord([{"status": "ok"}])
        flat = _FakeTypedPkg(side="none", qty=1.0)
        result = coord.multi_account_execute_typed([flat])
        assert result == []
        assert captured == []

    def test_multiple_pkgs_results_concatenated(self):
        coord, captured = self._make_coord([{"name": "bybit_1"}])
        pkgs = [_FakeTypedPkg(strategy_id="s1"), _FakeTypedPkg(strategy_id="s2")]
        result = coord.multi_account_execute_typed(pkgs)
        assert result == [{"name": "bybit_1"}, {"name": "bybit_1"}]
        assert len(captured) == 2
        assert captured[0].strategy == "s1"
        assert captured[1].strategy == "s2"

    def test_accounts_path_forwarded(self):
        coord, captured = self._make_coord([])
        paths_seen: List[Any] = []

        def _fake_execute(pkg, accounts_path=None, **kwargs):
            paths_seen.append(accounts_path)
            return []

        coord.multi_account_execute = _fake_execute
        coord.multi_account_execute_typed([_FakeTypedPkg()], accounts_path="/custom/accounts.yaml")
        assert paths_seen == ["/custom/accounts.yaml"]

    def test_mixed_flat_and_live_pkgs(self):
        coord, captured = self._make_coord([{"status": "dispatched"}])
        pkgs = [
            _FakeTypedPkg(qty=0.0),       # flat — skip
            _FakeTypedPkg(qty=1.5),       # live — dispatch
            _FakeTypedPkg(side="none"),   # flat — skip
            _FakeTypedPkg(qty=2.0),       # live — dispatch
        ]
        result = coord.multi_account_execute_typed(pkgs)
        assert len(result) == 2
        assert len(captured) == 2


# ---------------------------------------------------------------------------
# Pipeline S7 integration (all heavy deps stubbed via patch)
# ---------------------------------------------------------------------------

def _make_signal_pkg(side="long", entry=100.0, sl=98.0, tp=106.0, strategy="ict_scalp_5m"):
    from src.core.signal_contract import SignalPackage
    return SignalPackage(
        strategy_id=strategy,
        symbol="BTCUSDT",
        account_id="",
        side=side,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        timestamp_utc="2026-01-01T00:00:00Z",
        raw={},
        source_context={},
    )


def _base_settings(centralized: bool = True) -> dict:
    return {
        "CENTRALIZED_ALLOCATOR": "true" if centralized else "false",
        "MULTI_ACCOUNT_DISPATCH": "true",
        "SHADOW_BALANCE_USDT": "10000",
        "SYMBOL": "BTCUSDT",
    }


def _make_full_signal(sig_pkg=None) -> dict:
    return {
        "side": "buy",
        "symbol": "BTCUSDT",
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 106.0,
        "meta": {"strategy_name": "ict_scalp_5m"},
        "signal_package": sig_pkg,
    }


