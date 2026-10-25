"""XRP-REDUCE-OTHER-CLOSES: an intent_reduce leg is never an ENTRY slippage sample.

Once the reduce audit row carries ``broker_order_id`` (its REDUCE order, a
close of the parent journalled in the reduce side's direction), the entry join
in ``realized_slippage.measure`` would otherwise read that close fill as an
entry against the reduce package's ``entry``. Control: the same row as an
ordinary trade IS sampled, so the probe can see a positive.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "realized_slippage",
    Path(__file__).resolve().parents[1] / "scripts/research/realized_slippage.py",
)
rs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rs)


def _run(tmp_path, monkeypatch, setup_type):
    monkeypatch.setattr(rs, "load_accounts_dict", lambda: {
        "bybit_2": {"account_class": "real_money", "exchange": "bybit"}})
    (tmp_path / "fills.json").write_text(json.dumps([
        {"order_id": "oid-r", "side": "Buy", "qty": "3.3", "price": "1.3893"}]))
    (tmp_path / "trades.json").write_text(json.dumps([{
        "id": 6533, "account_id": "bybit_2", "symbol": "XRPUSDT",
        "direction": "long", "status": "open", "setup_type": setup_type,
        "broker_order_id": "oid-r", "order_package_id": "pkg-1",
        "strategy_name": "xrp_pullback_2h", "created_at": "2026-10-09T02:00:40Z",
    }]))
    (tmp_path / "order_packages.json").write_text(json.dumps([
        {"order_package_id": "pkg-1", "entry": 1.3898}]))
    return [r for r in rs.measure(tmp_path)["rows"] if r["side"] == "entry"]


def test_reduce_leg_fill_is_not_an_entry_sample(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, "intent_reduce") == []


def test_control_ordinary_trade_is_sampled(tmp_path, monkeypatch):
    assert len(_run(tmp_path, monkeypatch, "xrp_pullback_2h")) == 1
