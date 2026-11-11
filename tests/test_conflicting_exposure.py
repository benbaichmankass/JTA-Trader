"""CONFLICTING-EXPOSURE-ALERT: a symbol held long AND short across the books -> ONE alert + a queued review.

An alert, never a gate: nothing here refuses, closes or halts anything.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from src.runtime import conflicting_exposure as ce


def _db(tmp_path, trades=(), tickets=(), prop_table=True):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, order_package_id TEXT, strategy_name TEXT, symbol TEXT, "
              "direction TEXT, entry_price REAL, stop_loss REAL, account_id TEXT, account_class TEXT, status TEXT)")
    for t in trades:
        c.execute("INSERT INTO trades (order_package_id, strategy_name, symbol, direction, entry_price, stop_loss, "
                  "account_id, account_class, status) VALUES (?,?,?,?,?,?,?,?,?)", t)
    if prop_table:
        c.execute("CREATE TABLE prop_tickets (ticket_id TEXT, order_package_id TEXT, strategy TEXT, symbol TEXT, "
                  "direction TEXT, entry REAL, sl REAL, account_id TEXT, status TEXT)")
        for t in tickets:
            c.execute("INSERT INTO prop_tickets VALUES (?,?,?,?,?,?,?,?,?)", t)
    c.commit()
    c.close()
    return str(p)


# The 2026-11-11 SOL book (fixture accounts are the roster names; no balances, no venue ids).
SOL_TRADES = [
    ("pkg-long", "ml_entry", "SOLUSDT", "long", 84.81, 83.11, "bybit_2", "real_money", "open"),
    ("pkg-long", "ml_entry", "SOLUSDT", "long", 84.81, 83.11, "bybit_portfolio", "paper", "open"),
    ("pkg-pb", "sol_pullback_2h", "SOLUSDT", "short", 85.17, 87.78, "bybit_1", "paper", "open"),
    ("pkg-eth", "ml_entry", "ETHUSDT", "long", 2079.0, 2040.0, "bybit_2", "real_money", "open"),
    ("pkg-old", "ml_entry", "SOLUSDT", "short", 90.0, 92.0, "bybit_2", "real_money", "closed"),
]
SOL_TICKETS = [
    ("t1", "pkg-short", "trend_donchian_sol_4h", "SOLUSDT", "short", 87.64, 89.105, "velotrade_1", "filled"),
    ("t2", "pkg-short", "trend_donchian_sol_4h", "SOLUSDT", "short", 87.64, 89.105, "tradeify_1", "filled"),
    ("t3", "pkg-long", "ml_entry", "SOLUSDT", "long", 84.81, 83.11, "breakout_2", "filled"),
    ("t4", "pkg-long", "ml_entry", "SOLUSDT", "long", 84.81, 83.11, "velotrade_1", "suppressed"),
    ("t5", "pkg-x", "ml_entry", "SOLUSDT", "short", 80.0, 82.0, "breakout_2", "closed"),
]
STRATS = {"strategies": {"ml_entry": {"timeframe": "1h"}, "trend_donchian_sol_4h": {"timeframe": "4h"},
                         "sol_pullback_2h": {"timeframe": "2h"}}}


@pytest.fixture
def strategies_yaml(tmp_path):
    import yaml
    p = tmp_path / "strategies.yaml"
    p.write_text(yaml.safe_dump(STRATS))
    return str(p)


def test_sol_book_is_one_conflict_across_journal_and_prop(tmp_path, strategies_yaml):
    db = _db(tmp_path, SOL_TRADES, SOL_TICKETS)
    legs = ce.read_open_legs(db, mark_fn=lambda s: 84.2, strategies_path=strategies_yaml)
    assert legs["state"] == "read" and legs["books"]["journal"]["state"] == "read"
    by = {x["order_package_id"]: x for x in legs["legs"]}
    assert set(by) == {"pkg-long", "pkg-pb", "pkg-eth", "pkg-short"}  # closed / suppressed / closed ticket excluded
    assert by["pkg-long"]["accounts"] == ["bybit_2", "bybit_portfolio", "breakout_2"]
    assert by["pkg-long"]["timeframe"] == "1h" and by["pkg-short"]["timeframe"] == "4h"
    assert by["pkg-short"]["open_r"] == pytest.approx(2.35, abs=0.01)
    assert by["pkg-long"]["open_r"] == pytest.approx(-0.36, abs=0.01)
    conflicts = ce.find_conflicts(legs["legs"])
    assert [c["symbol"] for c in conflicts] == ["SOLUSDT"]  # ETH is long only: no conflict
    assert set(conflicts[0]["packages"]) == {"pkg-long", "pkg-pb", "pkg-short"}
    text = ce.render_alert(conflicts[0])
    for needle in ("SOLUSDT", "ml_entry (1h)", "trend_donchian_sol_4h (4h)", "velotrade_1", "+2.35R", "Alert only"):
        assert needle in text


def test_same_side_only_is_not_a_conflict():
    legs = [{"order_package_id": "a", "symbol": "SOLUSDT", "direction": "short"},
            {"order_package_id": "b", "symbol": "SOLUSDT", "direction": "short"}]
    assert ce.find_conflicts(legs) == []


def test_symbol_spellings_normalise():
    assert ce.normalize_symbol("SOL/USDT:USDT") == ce.normalize_symbol("solusdt") == "SOLUSDT"
    legs = [{"order_package_id": "a", "symbol": ce.normalize_symbol("SOL/USDT:USDT"), "direction": "long"},
            {"order_package_id": "b", "symbol": ce.normalize_symbol("SOLUSDT"), "direction": "sell"}]
    for x in legs:
        x["direction"] = ce.side_of(x["direction"])
    assert len(ce.find_conflicts(legs)) == 1


def test_key_is_stable_and_changes_with_the_package_set():
    a = [{"order_package_id": "p1", "direction": "long"}, {"order_package_id": "p2", "direction": "short"}]
    b = list(reversed(a))
    assert ce.conflict_key("SOLUSDT", a) == ce.conflict_key("SOLUSDT", b)
    c = a + [{"order_package_id": "p3", "direction": "short"}]
    assert ce.conflict_key("SOLUSDT", a) != ce.conflict_key("SOLUSDT", c)


def test_unreadable_journal_is_could_not_look_never_no_conflict(tmp_path):
    out = ce.detect(str(tmp_path / "missing.db"))
    assert out["state"] == "could_not_look" and out["conflicts"] == []


def test_missing_mark_reads_dash_not_zero(tmp_path, strategies_yaml):
    db = _db(tmp_path, SOL_TRADES, SOL_TICKETS)
    legs = ce.read_open_legs(db, mark_fn=None, strategies_path=strategies_yaml)
    assert all(x["open_r"] is None and x["open_r_state"] == "could_not_look" for x in legs["legs"])
    text = ce.render_alert(ce.find_conflicts(legs["legs"])[0])
    assert "open — est" in text and "+0.00R" not in text


def test_alert_sends_once_per_conflict_and_again_after_resolution(tmp_path, strategies_yaml):
    db = _db(tmp_path, SOL_TRADES, SOL_TICKETS)
    sent = []
    st = tmp_path / "state.json"
    found = ce.detect(db)
    r1 = ce.alert(found, path=st, send=lambda t: sent.append(t) or True)
    r2 = ce.alert(found, path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 1 and r1["sent"] and r2["standing"] == r1["sent"] and not r2["sent"]
    ce.alert({"state": "read", "conflicts": []}, path=st, send=lambda t: sent.append(t) or True)  # resolved
    ce.alert(found, path=st, send=lambda t: sent.append(t) or True)  # comes back
    assert len(sent) == 2


def test_failed_send_is_retried_and_could_not_look_keeps_state(tmp_path):
    db = _db(tmp_path, SOL_TRADES, SOL_TICKETS)
    st = tmp_path / "state.json"
    found = ce.detect(db)
    r = ce.alert(found, path=st, send=lambda t: False)
    assert r["failed"] and not r["sent"]
    sent = []
    ce.alert(found, path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 1
    ce.alert({"state": "could_not_look", "reason": "x"}, path=st, send=lambda t: sent.append(t) or True)
    assert json.loads(st.read_text())["alerted"]  # a failed read is not a resolution
    ce.alert(found, path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 1


def test_alert_never_raises_on_a_raising_sender(tmp_path):
    db = _db(tmp_path, SOL_TRADES, SOL_TICKETS)

    def boom(_):
        raise RuntimeError("telegram down")
    r = ce.alert(ce.detect(db), path=tmp_path / "s.json", send=boom)
    assert r["failed"]


def test_compute_due_queues_a_review_per_package_in_the_conflict():
    from src.runtime import live_review_due as lrd
    cfg = {"events": {}, "cooldown_exempt": ["conflicting_exposure"], "default_timeframe": "2h"}
    conflict = {"symbol": "SOLUSDT", "key": "SOLUSDT#abc", "packages": ["pkg-long", "pkg-short"],
                "legs": [{"order_package_id": "pkg-long", "leg": "ml_entry", "direction": "long", "timeframe": "1h"},
                         {"order_package_id": "pkg-short", "leg": "trend_donchian_sol_4h", "direction": "short",
                          "timeframe": "4h"}]}
    rows = [{"order_package_id": "pkg-long", "strategy": "ml_entry", "symbol": "SOLUSDT", "direction": "long",
             "telemetry_absent": True},
            {"order_package_id": "pkg-eth", "strategy": "ml_entry", "symbol": "ETHUSDT", "direction": "long",
             "telemetry_absent": True}]
    now = datetime(2026, 11, 11, 22, 40, tzinfo=timezone.utc)
    res = lrd.compute_due(rows, [], cfg, now, conflicts=[conflict])
    ev = {d["order_package_id"]: [e for e in d["events"] if e["event"] == ce.EVENT] for d in res["due"]}
    assert ev.get("pkg-long") and ev["pkg-long"][0]["level"] == "SOLUSDT#abc"
    assert "trend_donchian_sol_4h short 4h" in ev["pkg-long"][0]["why"]
    assert not ev.get("pkg-eth")
    # answered once -> quiet for the same conflict key
    reviews = [{"order_package_id": "pkg-long", "reviewed_at": "2026-11-11T22:41:00Z",
                "trigger": {"event": ce.EVENT, "level": "SOLUSDT#abc"}, "recommendation": {"action": "hold"}}]
    res2 = lrd.compute_due(rows, reviews, cfg, datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc),
                           conflicts=[conflict])
    assert not any(e["event"] == ce.EVENT for d in res2["due"] for e in d["events"])


def test_wake_plan_dedupes_conflict_on_level():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("lrw", Path("scripts/ops/live_review_wake.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert ce.EVENT in m.LEVEL_DEDUPED_EVENTS


def test_wake_poster_alert_hook_is_contained(tmp_path):
    from src.runtime import live_review_wake_post as wp
    sent = []
    doc = {"conflicting_exposure": {"state": "read", "conflicts": [
        {"symbol": "SOLUSDT", "key": "SOLUSDT#k", "packages": ["a", "b"],
         "legs": [{"order_package_id": "a", "leg": "x_1h", "direction": "long", "symbol": "SOLUSDT",
                   "entry": 84.81, "sl": 83.11, "accounts": ["breakout_2"], "open_r": None},
                  {"order_package_id": "b", "leg": "y_4h", "direction": "short", "symbol": "SOLUSDT",
                   "entry": 87.64, "sl": 89.105, "accounts": ["tradeify_1"], "open_r": None}]}]}}
    r = wp.conflict_alert(doc, send=lambda t: sent.append(t) or True, path=tmp_path / "s.json",
                          mark_fn=lambda s: 84.2)
    assert r["sent"] == ["SOLUSDT#k"] and "+2.35R" in sent[0] and "-0.36R" in sent[0]
    assert wp.conflict_alert({}, path=tmp_path / "s.json")["state"] == "absent"


def test_wake_poster_never_imports_the_market_feed():
    """local_pnl -> market_data -> exchange -> order path: importing it here breaks .importlinter (vwap contract)."""
    from pathlib import Path
    for f in ("src/runtime/live_review_wake_post.py", "src/runtime/conflicting_exposure.py"):
        assert "local_pnl" not in Path(f).read_text(), f


def test_config_exempts_the_event_from_the_bar_cooldown():
    import yaml
    from pathlib import Path
    due = yaml.safe_load(Path("config/live_trade_review.yaml").read_text())["due"]
    assert ce.EVENT in due["cooldown_exempt"]
