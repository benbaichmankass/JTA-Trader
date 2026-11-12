"""UI-TRADING-PUSH T1: GET /api/bot/stream -- one reader, many clients (routers/stream.py)."""
# ruff: noqa: RUF059  (the env fixture is unpacked whole in every test for readability)
from __future__ import annotations

import json
import sqlite3

import pytest

from src.web.api.routers import stream as S


def _db(path):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT,
                 direction TEXT, entry_price REAL, exit_price REAL, stop_loss REAL, take_profit_1 REAL,
                 position_size REAL, status TEXT, pnl REAL, strategy_name TEXT, account_id TEXT,
                 account_class TEXT, order_package_id TEXT, closed_at TEXT, exit_reason TEXT,
                 is_backtest BOOLEAN DEFAULT 0)""")
    c.execute("""CREATE TABLE order_packages (order_package_id TEXT PRIMARY KEY, strategy_name TEXT, symbol TEXT,
                 direction TEXT, entry REAL, sl REAL, tp REAL, confidence REAL, status TEXT,
                 linked_trade_id INTEGER, close_reason TEXT, created_at TEXT, updated_at TEXT)""")
    c.commit()
    return c


@pytest.fixture
def env(tmp_path):
    dbp = tmp_path / "j.db"
    led = tmp_path / "alerts_ledger.jsonl"
    led.write_text("")
    conn = _db(dbp)
    health = {"doc": {"ok": 1}}
    t = [0.0]
    b = S.Broadcaster(db_path=lambda: str(dbp), ledger_path=lambda: led, health=lambda: dict(health["doc"]),
                      clock=lambda: t[0], pnl_snapshot=lambda: (None, float("inf")))
    return b, conn, led, health, t


def _types(b):
    return [json.loads(raw.split(b"data: ", 1)[1])["type"] for _, _, raw in b.ring]


def _step(b, t, dt=1.0):
    t[0] += dt
    b.tick()
    b.flush()


def test_prime_emits_nothing_old_then_each_change_once(env):
    b, conn, led, health, t = env
    conn.execute("INSERT INTO trades (symbol,status,stop_loss,take_profit_1,account_id) VALUES ('OLD','open',1,2,'a')")
    conn.commit()
    led.write_text(json.dumps({"ts": "2026-11-12T07:00:00Z", "kind": "old", "channel": "system"}) + "\n")
    _step(b, t)
    assert _types(b) == ["health"]                         # priming: only the first health doc
    # new trade + new package + new alert
    conn.execute("INSERT INTO trades (symbol,status,stop_loss,take_profit_1,account_id) VALUES ('BTC','open',9,11,'a')")
    conn.execute("INSERT INTO order_packages VALUES ('op1','s','BTC','long',10,9,11,0.6,'open',NULL,NULL,'t0','t0')")
    conn.commit()
    with led.open("a") as fh:
        fh.write(json.dumps({"ts": "2026-11-12T08:00:00Z", "kind": "new", "channel": "system", "body": "x"}) + "\n")
    _step(b, t)
    assert sorted(_types(b)[1:]) == ["alert", "package", "position", "trade"]
    n = len(b.ring)
    _step(b, t)
    assert len(b.ring) == n                                # nothing changed: nothing emitted
    # bracket move on an open trade, package update, close
    conn.execute("UPDATE trades SET stop_loss = 9.5 WHERE symbol = 'BTC'")
    conn.execute("UPDATE order_packages SET updated_at = 't1' WHERE order_package_id = 'op1'")
    conn.commit()
    _step(b, t)
    assert sorted(_types(b)[n:]) == ["bracket", "package"]
    m = len(b.ring)
    conn.execute("UPDATE trades SET status = 'closed', pnl = -1 WHERE symbol = 'BTC'")
    conn.execute("UPDATE order_packages SET status = 'closed' WHERE order_package_id = 'op1'")
    conn.commit()
    _step(b, t)
    assert sorted(_types(b)[m:]) == ["package", "position", "trade"]


def test_health_pushed_only_on_change_and_every_30s(env):
    b, conn, led, health, t = env
    _step(b, t)
    _step(b, t, 31)
    assert _types(b).count("health") == 1                  # unchanged doc: not pushed again
    health["doc"] = {"ok": 0}
    _step(b, t, 5)
    assert _types(b).count("health") == 1                  # inside 30 s: not computed
    _step(b, t, 31)
    assert _types(b).count("health") == 2


def test_trimmed_ledger_does_not_replay(env):
    b, conn, led, health, t = env
    _step(b, t)
    rows = [json.dumps({"ts": f"2026-11-12T08:0{i}:00Z", "kind": f"k{i}", "channel": "system"}) for i in range(3)]
    led.write_text("\n".join(rows) + "\n")
    _step(b, t)
    assert _types(b).count("alert") == 3
    led.write_text(rows[2] + "\n" + json.dumps({"ts": "2026-11-12T08:09:00Z", "kind": "k9", "channel": "system"}) + "\n")
    _step(b, t)
    assert _types(b).count("alert") == 4                   # trimmed: only the genuinely new row


def test_unreadable_source_is_could_not_look_never_a_frame(env, tmp_path):
    b, conn, led, health, t = env
    b._db_path = lambda: str(tmp_path / "missing" / "nope.db")
    _step(b, t)
    _step(b, t)
    assert b.sources["journal"]["read_state"] == "could_not_look"
    assert "package" not in _types(b) and "trade" not in _types(b)


def test_backfill_and_gap(env):
    b, conn, led, health, t = env
    for i in range(5):
        b.emit("alert", {"i": i})
    b.flush()
    frames, gap = b.backfill(3)
    assert len(frames) == 2 and gap is False
    t[0] += S.RING_SECONDS + 1
    b.emit("alert", {"i": 99})
    b.flush()
    frames, gap = b.backfill(2)
    assert gap is True and len(frames) == 1


@pytest.mark.asyncio
async def test_two_clients_one_read_same_bytes(env):
    import asyncio
    b, conn, led, health, t = env
    q1, q2 = asyncio.Queue(), asyncio.Queue()
    b.clients |= {q1, q2}
    reads = {"n": 0}
    orig = b.read_journal

    def counted(emit=True):
        reads["n"] += 1
        return orig(emit)
    b.read_journal = counted
    _step(b, t)
    conn.execute("INSERT INTO order_packages VALUES ('op2','s','ETH','long',1,1,1,0.5,'open',NULL,NULL,'a','a')")
    conn.commit()
    _step(b, t)
    assert reads["n"] == 2                                 # one read per tick, whatever the client count
    a = [q1.get_nowait() for _ in range(q1.qsize())]
    c = [q2.get_nowait() for _ in range(q2.qsize())]
    assert a == c and any(b'"type":"package"' in x for x in a)


def test_route_is_mounted_and_status_answers():
    from fastapi.testclient import TestClient

    from src.web.api import main
    c = TestClient(main.app)
    paths = c.get("/openapi.json").json()["paths"]
    assert "/api/bot/stream" in paths and "/api/bot/stream/status" in paths
    r = c.get("/api/bot/stream/status")
    assert r.status_code == 200 and "sources" in r.json()


def _pos(tid, pnl, src="broker", prov="estimated", open_r=None):
    return {"id": tid, "account": "bybit_2", "symbol": "SOLUSDT", "side": "short", "qty": 1.0, "entryPrice": 100.0,
            "unrealizedPnl": pnl, "unrealizedPnlSource": src, "unrealizedPnlProvenance": prov,
            "r": {"openR": open_r} if open_r is not None else None}


def test_pnl_frames_only_on_threshold_or_provenance_change(env):
    b, conn, led, health, t = env
    snap = {"rows": [_pos("7", 10.0, open_r=0.5)], "age": 3.0}
    b._pnl_snapshot = lambda: (snap["rows"], snap["age"])
    _step(b, t)                                     # prime: baseline only
    assert "pnl" not in _types(b)
    snap["rows"] = [_pos("7", 10.3)]
    _step(b, t, 6)
    assert "pnl" not in _types(b)                    # 0.3 < PNL_MIN_MOVE
    snap["rows"] = [_pos("7", 11.0, open_r=0.6)]
    _step(b, t, 6)
    frames = [json.loads(raw.split(b"data: ", 1)[1]) for _, _, raw in b.ring]
    p = [f for f in frames if f["type"] == "pnl"]
    assert len(p) == 1 and p[0]["payload"]["unrealizedPnl"] == 11.0 and p[0]["payload"]["prev_unrealizedPnl"] == 10.0
    assert p[0]["payload"]["unrealizedPnlProvenance"] == "estimated" and p[0]["payload"]["snapshot_age_s"] == 3.0
    assert p[0]["payload"]["openR"] == 0.6 and p[0]["payload"]["as_of"].endswith("Z")
    snap["rows"] = [_pos("7", 11.0, src="unavailable", prov="unverified")]
    _step(b, t, 6)
    assert _types(b).count("pnl") == 2               # provenance change pushes even with no move
    _step(b, t, 2)
    assert _types(b).count("pnl") == 2               # inside PNL_EVERY_S: not read again


def test_pnl_no_snapshot_is_could_not_look_and_no_venue_call(env):
    b, conn, led, health, t = env
    calls = []
    b._pnl_snapshot = lambda: calls.append(1) or (None, float("inf"))
    _step(b, t)
    _step(b, t, 6)
    assert b.sources["pnl"]["read_state"] == "could_not_look" and "pnl" not in _types(b)
    assert len(calls) == 2                           # one peek per 5 s, nothing else


def test_default_pnl_snapshot_peeks_without_building(monkeypatch):
    from src.web.api.routers import dashboard
    built = []
    monkeypatch.setattr(dashboard, "_build_positions", lambda *a, **k: built.append(1))
    dashboard._POSITIONS_SWR.clear()
    rows, age = S._default_pnl_snapshot()
    assert rows is None and age == float("inf") and built == []
    dashboard._POSITIONS_SWR._store(True, [_pos("1", 2.0)])
    rows, age = S._default_pnl_snapshot()
    assert rows[0]["id"] == "1" and age < 5 and built == []
    dashboard._POSITIONS_SWR.clear()
