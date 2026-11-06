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
