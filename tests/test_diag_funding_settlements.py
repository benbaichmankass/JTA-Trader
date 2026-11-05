"""/api/diag/funding_settlements: read_state is never collapsed to 0."""
from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace


from src.runtime import exchange_accounts, exchange_fills_store as store
from src.web.api.routers import diag


def _call(monkeypatch, tmp_path, accounts, seed):
    db = tmp_path / "f.sqlite"
    store.init_db(db)
    conn = sqlite3.connect(db)
    for r in seed:
        conn.execute(
            "INSERT INTO bybit_transaction_log (txn_id,account_id,txn_type,currency,symbol,"
            "change_usd,funding,txn_time,txn_time_ms) VALUES (?,?,?,?,?,?,?,?,?)", r)
    conn.commit()
    conn.close()
    monkeypatch.setattr(store, "get_fills_db_path", lambda: db)
    monkeypatch.setattr(exchange_accounts, "live_bybit_fill_accounts",
                        lambda: [SimpleNamespace(account_id=a) for a in accounts])
    monkeypatch.setattr(diag, "_require_diag_token", lambda req: None)
    return diag.get_funding_settlements(None, None, 10)


def test_states(monkeypatch, tmp_path):
    now = int(time.time() * 1000)
    seed = [
        ("a", "bybit_2", "SETTLEMENT", "USDT", "BTCUSDT", -0.01, -0.01, "t", now - 3_600_000),
        ("b", "bybit_flat", "TRADE", "USDT", "BTCUSDT", 1.0, 0.0, "t", now),
    ]
    res = _call(monkeypatch, tmp_path, ["bybit_2", "bybit_flat", "bybit_new"], seed)
    by = {a["account_id"]: a for a in res["accounts"]}
    assert by["bybit_2"]["read_state"] == "measured"
    assert by["bybit_2"]["settlements_last_24h"] == 1
    assert by["bybit_flat"]["read_state"] == "no_rows_in_window"
    assert by["bybit_flat"]["settlements"] is None
    assert by["bybit_new"]["read_state"] == "not_pulled"
    assert by["bybit_new"]["settlements_last_24h"] is None
