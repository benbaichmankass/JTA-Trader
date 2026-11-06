"""Two accounts get the SAME venue funding id for one settlement; both rows must land."""
from src.runtime.exchange_funding_puller import _ccxt_funding_to_row
from src.runtime.exchange_fills_store import upsert_funding
import sqlite3


def _entry():
    return {"id": "abc", "symbol": "ETH/USDT:USDT", "amount": 0.01,
            "timestamp": 1793865600000}


def test_same_venue_id_two_accounts_both_stored(tmp_path):
    db = tmp_path / "f.sqlite"
    r1 = _ccxt_funding_to_row(_entry(), "bybit_1")
    r2 = _ccxt_funding_to_row(_entry(), "bybit_2")
    assert r1["funding_id"] != r2["funding_id"]
    assert upsert_funding([r1], path=db) == 1
    assert upsert_funding([r2], path=db) == 1      # control: bare id would give 0
    assert upsert_funding([r1, r2], path=db) == 0  # idempotent
    n = sqlite3.connect(db).execute("select count(*) from exchange_funding").fetchone()[0]
    assert n == 2


def test_legacy_bare_id_row_not_duplicated(tmp_path):
    db = tmp_path / "f.sqlite"
    legacy = _ccxt_funding_to_row(_entry(), "bybit_2")
    legacy["funding_id"] = "abc"
    assert upsert_funding([legacy], path=db) == 1
    assert upsert_funding([_ccxt_funding_to_row(_entry(), "bybit_2")], path=db) == 0


def test_store_sign_negative_is_paid():
    # ccxt Bybit amount is positive when paid; the store convention is negative = paid.
    assert _ccxt_funding_to_row(_entry(), "bybit_2")["funding_usd"] == -0.01


def test_legacy_rows_migrated_once(tmp_path):
    from src.runtime.exchange_fills_store import init_db
    db = tmp_path / "f.sqlite"
    init_db(db)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO exchange_funding (funding_id, account_id, symbol, funding_usd, funding_time) "
              "VALUES ('abc','bybit_2','ETH/USDT:USDT',0.01,'2026-11-05T08:00:00+00:00')")
    c.commit()
    c.close()
    upsert_funding([], path=db)
    upsert_funding([], path=db)  # second call must not flip again
    row = sqlite3.connect(db).execute("select funding_id, funding_usd from exchange_funding").fetchone()
    assert row == ("bybit_2:abc", -0.01)
