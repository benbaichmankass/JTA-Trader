"""/api/bot/positions rows carry an additive ``orderPackageId`` (null stays null)."""
from __future__ import annotations

import asyncio

import pytest

from src.web.api.routers import dashboard as dash
from tests.fixtures.real_schema_db import (
    insert_order_package, insert_trade, make_canonical_db)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "trade_journal.db"
    make_canonical_db(path)
    monkeypatch.setattr(dash, "_DB_PATH", path)
    return path


def _open(db, **kw):
    f = {"timestamp": "2026-11-12T10:00:00Z", "symbol": "BTCUSDT",
         "direction": "long", "entry_price": 60000.0, "position_size": 0.001,
         "status": "open", "is_backtest": 0, "is_demo": 0}
    f.update(kw)
    return insert_trade(db, **f)


def test_rows_expose_order_package_id_direct_fallback_and_null(db):
    direct = _open(db, order_package_id="op-direct")
    via_link = _open(db, symbol="ETHUSDT")
    insert_order_package(db, order_package_id="op-link", linked_trade_id=via_link,
                         created_at="2026-11-12T10:00:00Z")
    none = _open(db, symbol="SOLUSDT")
    rows = {r[0]: r for r in dash._fetch_open_position_rows(False)}
    assert rows[direct][13] == "op-direct"
    assert rows[via_link][13] == "op-link"
    assert rows[none][13] is None


def test_wire_has_key_and_null_is_null(db, monkeypatch):
    _open(db, order_package_id="op-1")
    _open(db, symbol="SOLUSDT")

    async def fake_read(fn, *a, **k):
        return None, "unavailable"
    monkeypatch.setattr(dash, "run_account_read", fake_read)
    out = asyncio.run(dash._build_positions(False))
    assert sorted(str(r["orderPackageId"]) for r in out) == ["None", "op-1"]
    assert all("orderPackageId" in r for r in out)
    assert any(r["orderPackageId"] is None for r in out)
