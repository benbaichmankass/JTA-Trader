"""SOAK-MECH-B: a closed trade's exit is priced from the ONE venue order that
closed it, before the close-time candle.

THE DEFECT (MEASURED 2026-10-17, bybit_raw_order_history + exchange fills,
bybit_1 XRPUSDT): trade 6171 (xrp_pullback_2h, long 1221.9) shared a one-way
position with 6193 (ict_scalp_xrp_5m, long 87674.6). 6193's stop sold 87674.6
at 09:11:18; a reduce-only sell of exactly 1221.9 @ 1.5428 ended 6171 at
09:11:56. ``exit_from_fills`` sums every close-side fill in the window, stopped
at 87674.6 and refused, and the row was booked at the 1.5399 close-time candle
(ESTIMATED) with its own fill on disk.

The Alpaca shape (3934 GLD short 108): eight buy fills of ONE stop order sum to
108 -- the backfill must price it. The refusal shape (6023 QQQ long 22): four
sell orders of 5/10/10/3 (+4 more on one of them), none of them 22 -- the
resolver must refuse rather than pick one.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import order_monitor as om
from src.runtime.fills_pnl import FILL_EXIT_SOURCE, exit_from_one_order_fills
from src.runtime.provenance import MEASURED, classify

_T0 = datetime(2026, 9, 25, 18, 2, 5, tzinfo=timezone.utc)
_OPEN_MS = int(_T0.timestamp() * 1000)
_CLOSE_MS = int((_T0 + timedelta(hours=15, minutes=13)).timestamp() * 1000)

_FILLS = """
CREATE TABLE exchange_fills (
    exec_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, price REAL NOT NULL, qty REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0, fee_currency TEXT, exec_time TEXT NOT NULL,
    order_id TEXT, is_maker INTEGER NOT NULL DEFAULT 0, raw TEXT,
    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _iso(d: datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


@pytest.fixture
def fills(tmp_path):
    path = tmp_path / "fills.sqlite"
    c = sqlite3.connect(str(path))
    c.executescript(_FILLS)
    c.commit()
    c.close()
    n = [0]

    def add(order_id, qty, price, at, *, side="sell", account="bybit_1",
            symbol="XRP/USDT:USDT", fee=0.0):
        n[0] += 1
        c = sqlite3.connect(str(path))
        c.execute("INSERT INTO exchange_fills (exec_id, account_id, symbol, side, price, qty,"
                  " fee, exec_time, order_id) VALUES (?,?,?,?,?,?,?,?,?)",
                  (f"e{n[0]}", account, symbol, side, price, qty, fee, _iso(at), order_id))
        c.commit()
        c.close()

    ns = type("F", (), {})()
    ns.add, ns.path = add, str(path)
    ns.factory = lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return ns


def _xrp_6171(fills):
    t = datetime(2026, 9, 26, 9, 11, 18, tzinfo=timezone.utc)
    fills.add("9b8f3c32", 87674.6, 1.5435, t)                          # sibling 6193's stop
    fills.add("15ee6294", 1221.9, 1.5428, t + timedelta(seconds=38), fee=1.04)  # ended 6171


def _resolve(fills, **kw):
    args = dict(account_id="bybit_1", symbol="XRPUSDT", direction="long",
                opened_at_ms=_OPEN_MS, closed_at_ms=_CLOSE_MS, qty=1221.9,
                conn_factory=fills.factory)
    args.update(kw)
    return exit_from_one_order_fills(**args)


# ------------------------------------------------------------- the resolver
def test_netted_sibling_close_resolves_to_the_order_of_this_rows_qty(fills):
    _xrp_6171(fills)
    rec = _resolve(fills)
    assert rec is not None
    assert rec["order_id"] == "15ee6294" and rec["match"] == "single_order_qty"
    assert rec["avg_exit_price"] == pytest.approx(1.5428)
    assert rec["fees"] == pytest.approx(1.04)
    assert classify(rec["source"], "exit_price_source") == MEASURED


def test_the_cumulative_reader_refuses_the_same_window(fills):
    """CONTROL: the pre-fix reader on the same fills refuses -- which is why
    6171 reached the candle at all."""
    from src.runtime.fills_pnl import exit_from_fills
    _xrp_6171(fills)
    assert exit_from_fills(account_id="bybit_1", symbol="XRPUSDT", direction="long",
                           opened_at_ms=_OPEN_MS, closed_at_ms=_CLOSE_MS, qty=1221.9,
                           conn_factory=fills.factory) is None


def test_own_bracket_order_wins_over_a_same_qty_stranger(fills):
    t = _T0 + timedelta(hours=2)
    fills.add("stranger", 1221.9, 1.50, t)
    fills.add("own-sl", 1221.9, 1.49, t + timedelta(seconds=5))
    rec = _resolve(fills, own_order_ids=("own-sl", None))
    assert rec["order_id"] == "own-sl" and rec["match"] == "own_bracket_order"


def test_two_orders_of_this_qty_is_ambiguous_and_refuses(fills):
    t = _T0 + timedelta(hours=2)
    fills.add("a", 1221.9, 1.50, t)
    fills.add("b", 1221.9, 1.51, t + timedelta(minutes=1))
    assert _resolve(fills) is None


def test_qqq_6023_shape_refuses(fills):
    """22 shares out through orders of 9/10/10/3: no single order is ours."""
    t = datetime(2026, 9, 24, 13, 30, tzinfo=timezone.utc)
    for oid, q, px in (("7e90", 5, 735.3), ("953b", 10, 735.44), ("7e90", 4, 735.43),
                       ("5a37", 10, 735.49), ("7a0e", 3, 735.17)):
        fills.add(oid, q, px, t, account="alpaca_paper", symbol="QQQ")
        t += timedelta(seconds=30)
    rec = exit_from_one_order_fills(
        account_id="alpaca_paper", symbol="QQQ", direction="long",
        opened_at_ms=int(datetime(2026, 9, 21, 14, 25, tzinfo=timezone.utc).timestamp() * 1000),
        closed_at_ms=int(datetime(2026, 9, 24, 13, 37, tzinfo=timezone.utc).timestamp() * 1000),
        qty=22, conn_factory=fills.factory)
    assert rec is None


def test_a_fill_after_the_close_bound_is_not_ours(fills):
    fills.add("late", 1221.9, 1.6, datetime.fromtimestamp(_CLOSE_MS / 1000, tz=timezone.utc)
              + timedelta(minutes=5))
    assert _resolve(fills) is None


def test_no_store_refuses():
    assert exit_from_one_order_fills(
        account_id="bybit_1", symbol="XRPUSDT", direction="long", opened_at_ms=_OPEN_MS,
        closed_at_ms=_CLOSE_MS, qty=1.0, conn_factory=lambda: None) is None


# ----------------------------------------------------------- the live sweep
_TRADES = """
CREATE TABLE trades (
    id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT,
    position_size REAL, entry_price REAL, exit_price REAL, pnl REAL,
    pnl_percent REAL, status TEXT, is_backtest INTEGER DEFAULT 0, setup_type TEXT,
    order_package_id TEXT, closed_at TEXT, created_at TEXT, exit_reason TEXT,
    timestamp TEXT, notes TEXT, sl_order_id TEXT, tp_order_id TEXT
);
"""


class _DB:
    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def update_trade(self, tid, updates):
        sets = ", ".join(f"{k} = ?" for k in updates)
        c = sqlite3.connect(self.path)
        c.execute(f"UPDATE trades SET {sets} WHERE id = ?", (*updates.values(), int(tid)))
        c.commit()
        c.close()


def test_sweep_prices_from_the_own_order_fill_before_the_candle(tmp_path, fills, monkeypatch):
    """Recent closes in the sweep window: the 6171 shape is priced off order
    15ee6294 (MEASURED), and the candle is never asked."""
    now = datetime.now(timezone.utc)
    opened, closed = now - timedelta(hours=20), now - timedelta(hours=7)
    fills.add("9b8f3c32", 87674.6, 1.5435, closed - timedelta(minutes=3))
    fills.add("15ee6294", 1221.9, 1.5428, closed - timedelta(minutes=2), fee=1.04)
    path = tmp_path / "j.db"
    c = sqlite3.connect(str(path))
    c.executescript(_TRADES)
    c.execute("INSERT INTO trades (id, account_id, symbol, direction, position_size, entry_price,"
              " status, exit_reason, created_at, closed_at, notes, sl_order_id, tp_order_id)"
              " VALUES (6171,'bybit_1','XRPUSDT','long',1221.9,1.5669,'closed','reconciler_filled',"
              " ?,?,?,'e6c58ca5','2f1105a5')",
              (_iso(opened), _iso(closed), json.dumps({"closed_by": "monitor_reconciler"})))
    c.commit()
    c.close()
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile",
                        lambda: {"bybit_1": {"account_id": "bybit_1", "exchange": "bybit"}})
    import src.runtime.exit_anchor as EA
    monkeypatch.setattr(EA, "bar_close_at", lambda *a, **k: pytest.fail("candle reached"))
    import src.runtime.fills_pnl as FP
    monkeypatch.setattr(FP, "_open_ro", lambda cf: fills.factory())
    db = _DB(path)
    summary = om._sweep_local_pnl_for_unpriced(db)
    assert summary["filled"] == 1, summary
    r = dict(db.connect().execute("SELECT * FROM trades WHERE id=6171").fetchone())
    n = json.loads(r["notes"])
    assert r["exit_price"] == pytest.approx(1.5428)
    assert n["exit_price_source"] == FILL_EXIT_SOURCE
    assert r["pnl"] == pytest.approx((1.5428 - 1.5669) * 1221.9 - 1.04, abs=1e-3)


# ------------------------------------------------------------- the backfill
def _journal(tmp_path):
    path = tmp_path / "journal.db"
    c = sqlite3.connect(str(path))
    c.executescript(_TRADES)
    rows = [
        # 6171: candle-priced Bybit row (ESTIMATED) -> repriced
        (6171, "bybit_1", "XRPUSDT", "long", 1221.9, 1.5669, 1.5399, -32.9913,
         "reconciler_filled", "2026-09-25T18:02:05+00:00", "2026-09-26T09:14:45+00:00",
         {"exit_price_source": "candle_at_close"}, "e6c58ca5", "2f1105a5"),
        # 3934: Alpaca GLD short, no exit price -> priced
        (3934, "alpaca_paper", "GLD", "short", 108, 371.52, None, None,
         "exchange_flat_reconciled", "2026-07-24T13:33:01+00:00", "2026-08-05T13:46:35+00:00",
         {"closed_by": "position_snapshot_reconciler"}, None, None),
        # 6027: already MEASURED -> never touched
        (6027, "alpaca_paper", "QLD", "long", 100, 95.09, 92.7962, -229.38, "sl_cross",
         "2026-09-21T15:39:17+00:00", "2026-10-14T16:32:40+00:00",
         {"exit_price_source": "exchange_fill"}, None, None),
    ]
    for (i, a, s, d, q, e, x, p, why, o, cl, n, sl, tp) in rows:
        c.execute("INSERT INTO trades (id, account_id, symbol, direction, position_size,"
                  " entry_price, exit_price, pnl, status, exit_reason, created_at, closed_at,"
                  " notes, sl_order_id, tp_order_id) VALUES (?,?,?,?,?,?,?,?,'closed',?,?,?,?,?,?)",
                  (i, a, s, d, q, e, x, p, why, o, cl, json.dumps(n), sl, tp))
    c.commit()
    c.close()
    return str(path)


def _gld_fills(fills):
    t = datetime(2026, 8, 5, 13, 32, 25, tzinfo=timezone.utc)
    for q, px in ((54, 385.33), (5, 385.48), (12, 385.51), (33, 385.30),
                  (1, 384.94), (1, 385.02), (1, 384.96), (1, 384.81)):
        fills.add("2f158adf", q, px, t, side="buy", account="alpaca_paper", symbol="GLD")
        t += timedelta(seconds=20)
    # the NEXT day's unrelated buy must stay outside the close bound
    fills.add("6db1989c", 7, 389.41, datetime(2026, 8, 6, 19, 2, tzinfo=timezone.utc),
              side="buy", account="alpaca_paper", symbol="GLD")


def test_backfill_plans_dry_run_without_writing(tmp_path, fills, capsys):
    from scripts.ops import backfill_own_fill_exits as bf
    _xrp_6171(fills)
    _gld_fills(fills)
    db = _journal(tmp_path)
    assert bf.run(db, fills.path, apply=False, ids=[6171, 3934, 6027]) == 0
    out = capsys.readouterr().out
    assert "PLAN id=6171" in out and "PLAN id=3934" in out
    assert "SKIP id=6027" in out and "already MEASURED" in out
    c = sqlite3.connect(db)
    assert c.execute("SELECT exit_price FROM trades WHERE id=3934").fetchone()[0] is None


def test_backfill_apply_writes_measured_exit_and_keeps_the_reason(tmp_path, fills):
    from scripts.ops import backfill_own_fill_exits as bf
    _xrp_6171(fills)
    _gld_fills(fills)
    db = _journal(tmp_path)
    bf.run(db, fills.path, apply=True, ids=[6171, 3934, 6027])
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    x = dict(c.execute("SELECT * FROM trades WHERE id=6171").fetchone())
    g = dict(c.execute("SELECT * FROM trades WHERE id=3934").fetchone())
    q = dict(c.execute("SELECT * FROM trades WHERE id=6027").fetchone())
    assert x["exit_price"] == pytest.approx(1.5428)
    assert x["exit_reason"] == "reconciler_filled", "labels are backfill-exit-labels' job"
    nx = json.loads(x["notes"])
    assert nx["exit_price_source"] == "exchange_fill"
    assert nx["backfill_own_fill"]["prior_exit_price"] == pytest.approx(1.5399)
    assert nx["backfill_own_fill"]["prior_exit_price_source"] == "candle_at_close"
    vwap = (54 * 385.33 + 5 * 385.48 + 12 * 385.51 + 33 * 385.30
            + 384.94 + 385.02 + 384.96 + 384.81) / 108
    assert g["exit_price"] == pytest.approx(vwap)
    assert g["pnl"] == pytest.approx((371.52 - vwap) * 108, abs=1e-3)
    assert g["exit_reason"] == "exchange_flat_reconciled"
    assert q["exit_price"] == pytest.approx(92.7962) and q["pnl"] == pytest.approx(-229.38)


def test_backfill_loses_the_race_to_a_concurrent_writer(tmp_path, fills, monkeypatch):
    from scripts.ops import backfill_own_fill_exits as bf
    _gld_fills(fills)
    db = _journal(tmp_path)
    real = bf.plan_row

    def plan_then_someone_writes(row, cf):
        out = real(row, cf)
        c = sqlite3.connect(db)
        c.execute("UPDATE trades SET exit_price = 1.0 WHERE id = ?", (row["id"],))
        c.commit()
        c.close()
        return out

    monkeypatch.setattr(bf, "plan_row", plan_then_someone_writes)
    bf.run(db, fills.path, apply=True, ids=[3934])
    assert sqlite3.connect(db).execute(
        "SELECT exit_price FROM trades WHERE id=3934").fetchone()[0] == 1.0


def test_apply_without_ids_is_refused(monkeypatch, tmp_path):
    from scripts.ops import backfill_own_fill_exits as bf
    monkeypatch.setattr("sys.argv", ["x", "--apply", "--db", str(tmp_path / "j.db"),
                                     "--fills-db", str(tmp_path / "f.db")])
    assert bf.main() == 2
