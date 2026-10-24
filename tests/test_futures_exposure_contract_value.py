"""MGC-SIZING-OVERSIZE: gross-exposure ceiling must count the futures contract
multiplier. ib_paper sized 96/150 MGC (x10/pt) ~ 3.7-5.8x equity because no
ceiling existed; and a ceiling measured as qty*price would have read 1/10 of that."""
import sqlite3

from src.units.accounts.risk import RiskManager


def _rm(tmp_path, max_gross):
    db = tmp_path / "j.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE trades (account_id TEXT, symbol TEXT, status TEXT,"
                  " position_size REAL, entry_price REAL, is_backtest INT)")
        c.execute("INSERT INTO trades VALUES ('a','MGC','open',10,4000.0,0)")
        c.execute("INSERT INTO trades VALUES ('a','ETHUSDT','open',2,2000.0,0)")
    rm = RiskManager({"risk_pct": 0.015, "max_gross_exposure_pct": max_gross},
                     account_id="a")
    rm._risk_db_path = lambda: str(db)
    return rm


def test_open_gross_notional_applies_contract_value(tmp_path):
    rm = _rm(tmp_path, 2.0)
    assert rm._open_gross_notional_from_db() == 10 * 4000.0 * 10.0 + 2 * 2000.0
    assert rm._open_notional_for_symbol("MGC") == 10 * 4000.0 * 10.0
