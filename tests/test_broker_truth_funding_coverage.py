"""COST-BROKER-SOURCED: funding is only written when the funding store reaches the close."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ops import backfill_broker_truth_costs as b


def _mk(tmp_path, funding_rows):
    j = tmp_path / "j.db"
    f = tmp_path / "f.db"
    c = sqlite3.connect(j)
    c.execute("CREATE TABLE trades(id INTEGER, account_id TEXT, symbol TEXT, direction TEXT, broker_order_id TEXT,"
              "cost_source TEXT, funding_paid_usd REAL, fee_taker_usd REAL, fee_maker_usd REAL, timestamp TEXT,"
              "closed_at TEXT, status TEXT, is_backtest INT)")
    c.execute("INSERT INTO trades VALUES(1,'bybit_2','ETHUSDT','long','o1','estimate',NULL,NULL,NULL,"
              "'2026-11-05T00:00:00+00:00','2026-11-05T10:00:00+00:00','closed',0)")
    c.commit()
    c.close()
    c = sqlite3.connect(f)
    c.execute("CREATE TABLE exchange_fills(account_id,symbol,side,qty,fee,fee_currency,is_maker,order_id,exec_time,exec_id)")
    c.execute("INSERT INTO exchange_fills VALUES('bybit_2','ETHUSDT','buy',1,0.1,'USDT',0,'o1','2026-11-05T00:00:01+00:00','e1')")
    c.execute("INSERT INTO exchange_fills VALUES('bybit_2','ETHUSDT','sell',1,0.1,'USDT',0,'x9','2026-11-05T10:00:00+00:00','e2')")
    c.execute("CREATE TABLE exchange_funding(account_id,symbol,funding_usd,funding_time)")
    for r in funding_rows:
        c.execute("INSERT INTO exchange_funding VALUES('bybit_2','ETHUSDT',?,?)", r)
    c.commit()
    c.close()
    return str(j), str(f)


def _fund(j):
    c = sqlite3.connect(j)
    return c.execute("SELECT cost_source, funding_paid_usd FROM trades").fetchone()


def test_stale_funding_store_gives_null_not_zero(tmp_path):
    j, f = _mk(tmp_path, [(-0.5, "2026-11-04T08:00:00+00:00")])  # store stops before the close
    b.sweep(j, f, apply=True, with_funding=True)
    assert _fund(j) == ("broker", None)


def test_covered_funding_is_written(tmp_path):
    j, f = _mk(tmp_path, [(-0.5, "2026-11-05T08:00:00+00:00"), (0.0, "2026-11-05T16:00:00+00:00")])
    b.sweep(j, f, apply=True, with_funding=True)
    cs, fv = _fund(j)
    assert cs == "broker" and fv == 0.5


def test_null_funding_topped_up_later(tmp_path):
    j, f = _mk(tmp_path, [(-0.5, "2026-11-04T08:00:00+00:00")])
    b.sweep(j, f, apply=True, with_funding=True)
    c = sqlite3.connect(f)
    c.execute("INSERT INTO exchange_funding VALUES('bybit_2','ETHUSDT',-0.5,'2026-11-05T08:00:00+00:00')")
    c.execute("INSERT INTO exchange_funding VALUES('bybit_2','ETHUSDT',0,'2026-11-05T16:00:00+00:00')")
    c.commit()
    c.close()
    s = b.sweep(j, f, apply=True, with_funding=True)
    assert s["funding_topped_up"] == 1 and _fund(j) == ("broker", 0.5)


def test_funding_not_written_by_default(tmp_path):
    j, f = _mk(tmp_path, [(-0.5, "2026-11-05T08:00:00+00:00"), (0.0, "2026-11-05T16:00:00+00:00")])
    b.sweep(j, f, apply=True)
    assert _fund(j) == ("broker", None)


def test_with_funding_recomputes_inverted_stored_value(tmp_path):
    j, f = _mk(tmp_path, [(-0.5, "2026-11-05T08:00:00+00:00"), (0.0, "2026-11-05T16:00:00+00:00")])
    b.sweep(j, f, apply=True)  # fees only -> broker, funding NULL
    c = sqlite3.connect(j)
    c.execute("UPDATE trades SET funding_paid_usd=-0.5")  # the old inverted value
    c.commit()
    c.close()
    s = b.sweep(j, f, apply=True, with_funding=True)
    assert s["funding_corrected"] == 1 and s["funding_sign_flipped"] == 1
    assert _fund(j) == ("broker", 0.5)
    s2 = b.sweep(j, f, apply=True, with_funding=True)
    assert s2["funding_corrected"] == 0
