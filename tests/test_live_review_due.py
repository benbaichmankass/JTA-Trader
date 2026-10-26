"""LTR-1: live_review_due -- the L0 due computation, route and gate client."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import yaml

from src.runtime import live_review_due as lrd

NOW = datetime(2026, 10, 25, 14, 4, tzinfo=timezone.utc)
CFG = lrd.load_config()


def row(**kw):
    base = {"order_package_id": "pkg-1", "strategy": "ada_pullback_2h",
            "account_id": "bybit_2", "symbol": "ADAUSDT", "direction": "short",
            "open_r": 0.2, "peak_r": 0.3, "giveback_r": 0.1, "r_to_target": 3.0,
            "updated_at": NOW.isoformat(), "lifecycle": "open"}
    base.update(kw)
    return base


def review(pkg="pkg-1", event="daily_floor", level="x", at=NOW - timedelta(hours=30), peak=None):
    return {"order_package_id": pkg, "reviewed_at": at.isoformat(),
            "trigger": {"event": event, "level": level}, "state": {"peak_r": peak}}


def events(res):
    return [[e["event"] for e in d["events"]] for d in res["due"]]


def test_config_floor_accounts_exist_in_accounts_yaml():
    accts = yaml.safe_load(open("config/accounts.yaml"))["accounts"]
    for a in CFG["events"]["daily_floor"]["accounts"]:
        assert a in accts


def test_quiet_reviewed_package_is_not_due():
    res = lrd.compute_due([row()], [review(at=NOW - timedelta(hours=3))], CFG, NOW)
    assert res["due_count"] == 0 and res["due"] == []


def test_never_reviewed_real_money_is_due_daily_floor():
    assert events(lrd.compute_due([row()], [], CFG, NOW)) == [["daily_floor"]]


def test_floor_not_applied_to_soak_account():
    assert lrd.compute_due([row(account_id="bybit_1")], [], CFG, NOW)["due_count"] == 0


def test_r_milestone_fires_once_per_level():
    r = row(open_r=2.4, peak_r=2.5, giveback_r=0.1)
    seen = [review(at=NOW - timedelta(hours=3), event="r_milestone", level=2, peak=2.5)]
    assert lrd.compute_due([r], seen, CFG, NOW)["due_count"] == 0  # 2 == "2.0"
    seen = [review(at=NOW - timedelta(hours=5), event="r_milestone", level=2, peak=2.5)]
    r3 = row(open_r=3.1, peak_r=3.2, giveback_r=0.1)
    res = lrd.compute_due([r3], seen, CFG, NOW)
    assert res["due"][0]["events"][0]["level"] == 3.0


def test_cooldown_one_review_per_closed_bar_but_giveback_exempt():
    bar = lrd.bar_start(NOW, 7200)
    just = review(at=bar + timedelta(minutes=1), event="daily_floor", level="d", peak=2.0)
    r = row(open_r=1.4, peak_r=2.6, giveback_r=1.2)  # new_peak + giveback + milestone
    res = lrd.compute_due([r], [just], CFG, NOW)
    assert events(res) == [["giveback"]]


def test_new_peak_needs_a_baseline_and_a_step():
    prior = [review(at=NOW - timedelta(hours=5), peak=1.0, level="z")]
    ok = lrd.compute_due([row(open_r=0.5, peak_r=1.6, giveback_r=0.1)], prior, CFG, NOW)
    assert "new_peak" in events(ok)[0]
    no = lrd.compute_due([row(open_r=0.5, peak_r=1.4, giveback_r=0.1)], prior, CFG, NOW)
    assert no["due_count"] == 0


def test_giveback_threshold_is_max_of_floor_and_fraction():
    prior = [review(at=NOW - timedelta(hours=5), peak=4.0, level="z")]
    # peak 4 -> need max(0.5, 1.2)=1.2 ; giveback 1.0 is not enough
    res = lrd.compute_due([row(open_r=3.0, peak_r=4.0, giveback_r=1.0, r_to_target=1.0)],
                          prior, CFG, NOW)
    assert all("giveback" not in e for e in events(res))
    res = lrd.compute_due([row(open_r=2.7, peak_r=4.0, giveback_r=1.3, r_to_target=1.0)],
                          prior, CFG, NOW)
    assert "giveback" in events(res)[0]


def test_near_target():
    prior = [review(at=NOW - timedelta(hours=5), level="z")]
    res = lrd.compute_due([row(r_to_target=0.3)], prior, CFG, NOW)
    assert events(res) == [["near_target"]]


def test_stale_telemetry_flagged():
    old = (NOW - timedelta(hours=2)).isoformat()
    res = lrd.compute_due([row(updated_at=old)], [], CFG, NOW)
    assert res["due"][0]["telemetry_stale"] is True


def test_timeframe_from_suffix():
    assert lrd.timeframe_seconds("trend_donchian_sol_4h", "2h") == 14400
    assert lrd.timeframe_seconds("x_1d", "2h") == 86400
    assert lrd.timeframe_seconds("weird", "2h") == 7200


# collapsed-state: measured -- fixture rows only need the measured peak state; the
# production reader (live_review_due) does not branch on peak_state at all.
def _db(path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT)")
    c.execute("INSERT INTO trades VALUES (7, 'open')")
    cols = ("order_package_id,trade_id,strategy,symbol,account_id,direction,open_r,peak_r,"
            "peak_state,giveback_r,r_to_target,updated_at")
    c.execute(f"CREATE TABLE position_telemetry ({cols}, terminal_state, levers)")
    for r in rows:
        c.execute(f"INSERT INTO position_telemetry ({cols}) VALUES ({','.join('?' * 12)})", r)
    c.commit()
    c.close()


def test_payload_looked_zero_vs_could_not_look(tmp_path):
    db = str(tmp_path / "j.db")
    _db(db, [("pkg-1", "7", "ada_pullback_2h", "ADAUSDT", "bybit_2", "short",
              0.2, 0.3, "measured", 0.1, 3.0, NOW.isoformat())])
    rv = tmp_path / "r.jsonl"
    rv.write_text(json.dumps(review(at=NOW - timedelta(hours=1))) + "\n")
    out = lrd.live_review_due(db_path=db, reviews_path=str(rv), now=NOW)
    assert out["read_state"] == "looked" and out["due_count"] == 0 and out["open_count"] == 1
    assert out["reviews_state"] == "read" and "mechanics_venue" in out["events_not_evaluated"]
    bad = lrd.live_review_due(db_path=str(tmp_path / "missing.db"), reviews_path=str(rv), now=NOW)
    assert bad["read_state"] == "could_not_look"
    assert bad["due_count"] is None and bad["open_count"] is None and bad["reason"]


def test_absent_reviews_is_reported_not_hidden(tmp_path):
    db = str(tmp_path / "j.db")
    _db(db, [("pkg-1", "7", "ada_pullback_2h", "ADAUSDT", "bybit_2", "short",
              0.2, 0.3, "measured", 0.1, 3.0, NOW.isoformat())])
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW)
    assert out["reviews_state"] == "absent" and out["due_count"] == 1


def test_cli_exit_codes(tmp_path):
    def run(doc):
        p = tmp_path / "d.json"
        p.write_text(json.dumps(doc))
        return subprocess.run([sys.executable, "scripts/ops/live_review_due.py",
                               "--from-file", str(p)], capture_output=True, text=True)
    r = run({"read_state": "looked", "due_count": 0, "open_count": 3})
    assert r.returncode == 10 and r.stdout.count("\n") == 1
    r = run({"read_state": "could_not_look", "due_count": None, "reason": "boom"})
    assert r.returncode == 11 and "boom" in r.stderr
    r = run({"read_state": "looked", "due_count": 1, "due": [{"order_package_id": "p"}]})
    assert r.returncode == 0 and "order_package_id" in r.stdout


def test_route_requires_diag_token():
    from fastapi.testclient import TestClient
    from src.web.api.main import app
    r = TestClient(app).get("/api/diag/live_review_due")
    assert r.status_code in (401, 503)


# ---- LTR-DUE-TELEMETRY-LESS: open packages with no telemetry row are listed, never dropped ----
def _journal(path, packages, trades=()):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE order_packages (order_package_id, strategy_name, symbol, direction, status)")
    c.execute("DROP TABLE IF EXISTS trades")
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status, order_package_id, strategy_name, "
              "symbol, direction, account_id)")
    for p in packages:
        c.execute("INSERT INTO order_packages VALUES (?,?,?,?,?)", p)
    for t in trades:
        c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?)", t)
    c.commit()
    c.close()


def _telemetry_less_db(tmp_path):
    db = str(tmp_path / "j.db")
    _db(db, [("pkg-1", "7", "ada_pullback_2h", "ADAUSDT", "bybit_2", "short",
              0.2, 0.3, "measured", 0.1, 3.0, NOW.isoformat())])
    _journal(db,
             [("pkg-1", "ada_pullback_2h", "ADAUSDT", "short", "open"),
              ("pkg-2", "xrp_squeeze_1h", "XRPUSDT", "long", "open"),
              ("pkg-3", "old_leg_1h", "BTCUSDT", "long", "closed")],
             [(7, "open", "pkg-1", "ada_pullback_2h", "ADAUSDT", "short", "bybit_2"),
              (9, "open", "pkg-4", "eth_fade_1h", "ETHUSDT", "short", "bybit_2")])
    return db


def test_open_count_includes_telemetry_less_packages(tmp_path):
    db = _telemetry_less_db(tmp_path)
    rv = tmp_path / "r.jsonl"
    rv.write_text(json.dumps(review(at=NOW - timedelta(hours=1))) + "\n")
    out = lrd.live_review_due(db_path=db, reviews_path=str(rv), now=NOW)
    assert out["read_state"] == "looked"
    # telemetry-open pkg-1 + journal-open pkg-2 (order_packages) + pkg-4 (trades only); pkg-3 closed
    assert out["open_count"] == 3 and out["open_count_complete"] is True
    less = {p["order_package_id"]: p for p in out["telemetry_less"]}
    assert set(less) == {"pkg-2", "pkg-4"}
    for p in less.values():
        assert p["telemetry_state"] == "telemetry_absent"
        assert {e["event"] for e in p["events_could_not_look"]} == set(lrd.TELEMETRY_EVENTS)
        assert all(e["reason"] == "telemetry_absent" for e in p["events_could_not_look"])


def test_telemetry_less_real_money_package_can_be_due_on_daily_floor(tmp_path):
    db = _telemetry_less_db(tmp_path)
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW)
    due = {d["order_package_id"]: d for d in out["due"]}
    assert "pkg-4" in due  # bybit_2 trade row, never reviewed -> daily_floor needs no telemetry
    assert [e["event"] for e in due["pkg-4"]["events"]] == ["daily_floor"]
    assert due["pkg-4"]["telemetry_state"] == "telemetry_absent"
    assert due["pkg-4"]["telemetry_stale"] is None
    assert "pkg-2" not in due  # no account known -> no floor; still listed, not dropped
    assert "pkg-2" in {p["order_package_id"] for p in out["telemetry_less"]}


def test_journal_unreadable_is_not_an_empty_open_set(tmp_path):
    db = str(tmp_path / "j.db")  # telemetry table only: no order_packages / trades
    _db(db, [("pkg-1", "7", "ada_pullback_2h", "ADAUSDT", "bybit_2", "short",
              0.2, 0.3, "measured", 0.1, 3.0, NOW.isoformat())])
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW)
    assert out["open_count"] == 1 and out["open_count_complete"] is False
    assert out["journal_open_state"] == "could_not_look" and out["journal_open_reason"]
    assert out["telemetry_less"] == []
