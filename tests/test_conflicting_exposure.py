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
    # closed / suppressed / closed ticket excluded; pkg-pb is on bybit_1 (paper TESTING): out of scope
    assert set(by) == {"pkg-long", "pkg-eth", "pkg-short"}
    assert legs["books"]["journal"]["paper_testing_rows_skipped"] == 1
    assert by["pkg-long"]["accounts"] == ["bybit_2", "bybit_portfolio", "breakout_2"]
    assert by["pkg-long"]["timeframe"] == "1h" and by["pkg-short"]["timeframe"] == "4h"
    assert by["pkg-short"]["open_r"] == pytest.approx(2.35, abs=0.01)
    assert by["pkg-long"]["open_r"] == pytest.approx(-0.36, abs=0.01)
    conflicts = ce.find_conflicts(legs["legs"])
    assert [c["symbol"] for c in conflicts] == ["SOLUSDT"]  # ETH is long only: no conflict
    assert set(conflicts[0]["packages"]) == {"pkg-long", "pkg-short"}
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
    from pathlib import Path

    import yaml
    due = yaml.safe_load(Path("config/live_trade_review.yaml").read_text())["due"]
    assert ce.EVENT in due["cooldown_exempt"]


def test_open_r_measures_1r_from_the_initial_risk_not_the_trailed_stop(tmp_path, strategies_yaml):
    """2026-11-14 16:07Z: trend_donchian_1h BTC short pkg-13ec01223e304ad4 read '+60.52R est' while its packets read
    about +1.7R: 1R was |entry - CURRENT stop|, and the stop had trailed to within a few dollars of entry."""
    trades = [("pkg-s", "trend_donchian", "BTCUSDT", "short", 100000.0, 99950.0, "bybit_2", "real_money", "open"),
              ("pkg-l", "ml_entry", "BTCUSDT", "long", 97000.0, 96000.0, "bybit_2", "real_money", "open"),
              ("pkg-n", "ml_entry", "BTCUSDT", "long", 97500.0, 96500.0, "bybit_2", "real_money", "open")]
    db = _db(tmp_path, trades)
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE order_packages (order_package_id TEXT, meta TEXT)")
    c.execute("INSERT INTO order_packages VALUES (?, ?)", ("pkg-s", json.dumps({"risk_per_unit": 1750.0})))
    c.execute("INSERT INTO order_packages VALUES (?, ?)", ("pkg-l", "not json"))
    c.commit()
    c.close()
    legs = ce.read_open_legs(db, mark_fn=lambda s: 97000.0, strategies_path=strategies_yaml)
    by = {x["order_package_id"]: x for x in legs["legs"]}
    assert by["pkg-s"]["open_r"] == pytest.approx(1.71, abs=0.01)          # 3000 / 1750, not 3000 / 50 = 60
    assert by["pkg-s"]["open_r_basis"] == "initial_risk"
    assert by["pkg-l"]["open_r_basis"] == "current_stop" and by["pkg-l"]["open_r"] == pytest.approx(0.0)
    text = ce.render_alert(ce.find_conflicts(legs["legs"])[0])
    assert "+1.71R est, pkg pkg-s" in text and "(1R from the current stop)" in text


def test_no_order_packages_table_falls_back_to_the_stop_and_says_so(tmp_path, strategies_yaml):
    db = _db(tmp_path, SOL_TRADES, SOL_TICKETS)
    legs = ce.read_open_legs(db, mark_fn=lambda s: 84.2, strategies_path=strategies_yaml)
    assert {x["open_r_basis"] for x in legs["legs"]} == {"current_stop"}


# ── 2026-11-15: a leg LEAVING is not a new conflict (carry_forward) ──────────────────────────────────────────────
# Tonight's ETHUSDT book, package ids as measured: one ml_entry_v2 long vs four shorts that exited one by one.
ETH_LONG = ("pkg-ec790aada2a548dc", "ml_entry_v2", "ETHUSDT", "long", 1768.52, 1703.64, "bybit_2", "real_money", "open")
ETH_SHORTS = [
    ("pkg-48c5cfab364e430c", "trend_donchian_eth_4h", "ETHUSDT", "short", 1960.0, 2010.0, "bybit_2", "real_money", "open"),
    ("pkg-665b2dff5ef04889", "trend_donchian_eth_4h", "ETHUSDT", "short", 1960.0, 2010.0, "bybit_2", "real_money", "open"),
    ("pkg-edd087a2c21c4421", "trend_donchian_eth", "ETHUSDT", "short", 1950.0, 2000.0, "bybit_2", "real_money", "open"),
    ("pkg-fd52297225d14860", "trend_donchian_eth_prop", "ETHUSDT", "short", 1950.0, 2000.0, "bybit_2", "real_money",
     "open"),
]


def _eth_book(tmp_path, n_shorts):
    d = tmp_path / f"b{n_shorts}"
    d.mkdir(exist_ok=True)
    return _db(d, [ETH_LONG] + ETH_SHORTS[:n_shorts])


def test_tonights_three_eth_keys_are_the_raw_package_hashes():
    """Pins the diagnosis: the three keys that fired at 00:10Z / 02:20Z / 03:01Z are the sorted-package hashes of
    the book as each short exited (nothing else churns into the key)."""
    def key(n):
        legs = [{"order_package_id": ETH_LONG[0], "direction": "long"}] + [
            {"order_package_id": s[0], "direction": "short"} for s in ETH_SHORTS[:n]]
        return ce.conflict_key("ETHUSDT", legs)
    assert [key(4), key(3), key(2)] == ["ETHUSDT#f9b0dbe1d5", "ETHUSDT#43d62acadb", "ETHUSDT#71bffc9581"]


def test_tonights_three_eth_keys_produce_one_alert_not_three(tmp_path):
    st = tmp_path / "state.json"
    sent = []
    keys = []
    for n in (4, 3, 2):                                   # 00:10Z, then fd522972 exits 02:20Z, edd087a2 exits 03:01Z
        found = ce.detect(_eth_book(tmp_path, n), state=st)
        keys.append(found["conflicts"][0]["key"])
        ce.alert(found, path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 1
    assert keys == ["ETHUSDT#f9b0dbe1d5"] * 3            # the review level never moves either
    doc = json.loads(st.read_text())
    assert list(doc["alerted"]) == ["ETHUSDT#f9b0dbe1d5"]
    assert len(doc["alerted"]["ETHUSDT#f9b0dbe1d5"]["packages"]) == 5   # the alerted (superset) record is kept


def test_alert_alone_carries_forward_even_without_detect(tmp_path):
    """alert() applies the same rule to a doc whose keys were not carried (e.g. built before the state existed)."""
    st = tmp_path / "state.json"
    sent = []
    for n in (4, 3):
        found = ce.find_conflicts(ce.read_open_legs(_eth_book(tmp_path, n))["legs"])
        r = ce.alert({"state": "read", "conflicts": found}, path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 1 and r["standing"] == ["ETHUSDT#f9b0dbe1d5"] and not r["sent"]


def test_a_genuinely_new_joiner_still_alerts(tmp_path):
    st = tmp_path / "state.json"
    sent = []
    ce.alert(ce.detect(_eth_book(tmp_path, 2), state=st), path=st, send=lambda t: sent.append(t) or True)
    # a short that was NOT in the alerted set joins (here: the 3rd short opening after the first alert)
    found = ce.detect(_eth_book(tmp_path, 3), state=st)
    assert found["conflicts"][0]["key"] == "ETHUSDT#43d62acadb" and "carried_from" not in found["conflicts"][0]
    r = ce.alert(found, path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 2 and r["sent"] == ["ETHUSDT#43d62acadb"]
    # a joiner on the OTHER side alerts too
    d = tmp_path / "join_long"
    d.mkdir()
    db = _db(d, [ETH_LONG, ("pkg-newlong", "e4_oi_shock_1h", "ETHUSDT", "long", 1800.0, 1750.0, "bybit_2", "real_money",
                            "open")] + ETH_SHORTS[:3])
    ce.alert(ce.detect(db, state=st), path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 3


def test_leave_then_join_alerts_on_the_join(tmp_path):
    st = tmp_path / "state.json"
    sent = []
    ce.alert(ce.detect(_eth_book(tmp_path, 3), state=st), path=st, send=lambda t: sent.append(t) or True)
    ce.alert(ce.detect(_eth_book(tmp_path, 2), state=st), path=st, send=lambda t: sent.append(t) or True)  # leave
    assert len(sent) == 1
    d = tmp_path / "swap"
    d.mkdir()
    db = _db(d, [ETH_LONG] + ETH_SHORTS[:2] + [ETH_SHORTS[3]])          # fd522972 was never alerted: a joiner
    ce.alert(ce.detect(db, state=st), path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 2


def test_an_emptied_side_resolves_and_a_recurrence_alerts_again(tmp_path):
    st = tmp_path / "state.json"
    sent = []
    ce.alert(ce.detect(_eth_book(tmp_path, 4), state=st), path=st, send=lambda t: sent.append(t) or True)
    d = tmp_path / "flat"
    d.mkdir()
    gone = ce.detect(_db(d, list(ETH_SHORTS)), state=st)                # the long exited: no conflict
    assert gone["conflicts"] == []
    ce.alert(gone, path=st, send=lambda t: sent.append(t) or True)
    assert json.loads(st.read_text())["alerted"] == {}
    found = ce.detect(_eth_book(tmp_path, 2), state=st)                 # same packages come back: a NEW conflict
    assert found["conflicts"][0]["key"] == "ETHUSDT#71bffc9581"
    ce.alert(found, path=st, send=lambda t: sent.append(t) or True)
    assert len(sent) == 2


def test_carry_forward_is_per_symbol_and_skips_malformed_records():
    c = [{"symbol": "XRPUSDT", "key": "XRPUSDT#new", "packages": ["a", "b"]}]
    known = {"ETHUSDT#old": {"symbol": "ETHUSDT", "packages": ["a", "b", "c"]},
             "XRPUSDT#bad": None,
             "XRPUSDT#late": {"symbol": "XRPUSDT", "packages": ["a", "b", "c"], "first_alerted_at": "2026-11-15T02"},
             "XRPUSDT#early": {"symbol": "XRPUSDT", "packages": ["a", "b", "d"], "first_alerted_at": "2026-11-15T01"}}
    out = ce.carry_forward(c, known)
    assert out[0]["key"] == "XRPUSDT#early" and out[0]["raw_key"] == "XRPUSDT#new"
    assert ce.carry_forward([{"symbol": "ETHUSDT", "key": "ETHUSDT#x", "packages": ["z"]}], known)[0]["key"] == \
        "ETHUSDT#x"


def test_unreadable_state_carries_nothing_forward(tmp_path):
    st = tmp_path / "state.json"
    st.write_text("{not json")
    found = ce.detect(_eth_book(tmp_path, 3), state=st)
    assert found["conflicts"][0]["key"] == "ETHUSDT#43d62acadb"         # raw key: fails toward re-alerting


def test_review_level_stays_on_the_alerted_key_so_a_shrink_queues_no_second_review(tmp_path):
    from src.runtime import live_review_due as lrd
    st = tmp_path / "state.json"
    ce.alert(ce.detect(_eth_book(tmp_path, 4), state=st), path=st, send=lambda t: True)
    cfg = {"events": {}, "cooldown_exempt": [ce.EVENT], "default_timeframe": "2h"}
    rows = [{"order_package_id": ETH_LONG[0], "strategy": "ml_entry_v2", "symbol": "ETHUSDT", "direction": "long",
             "telemetry_absent": True}]
    reviews = [{"order_package_id": ETH_LONG[0], "reviewed_at": "2026-11-15T00:15:00Z",
                "trigger": {"event": ce.EVENT, "level": "ETHUSDT#f9b0dbe1d5"}, "recommendation": {"action": "hold"}}]
    shrunk = ce.detect(_eth_book(tmp_path, 3), state=st)["conflicts"]
    res = lrd.compute_due(rows, reviews, cfg, datetime(2026, 11, 15, 2, 21, tzinfo=timezone.utc), conflicts=shrunk)
    assert not any(e["event"] == ce.EVENT for d in res["due"] for e in d["events"])


# Operator 2026-11-16: the alert considers real money, prop and the paper-portfolio mirrors only, never the
# paper-TESTING books. The 14:31 SOL alert named a bybit_1 scalp long and a bybit_1 pullback short.
def test_paper_testing_legs_never_make_or_join_a_conflict(tmp_path, strategies_yaml):
    trades = [
        ("pkg-scalp", "ict_scalp_sol_15m", "SOLUSDT", "long", 71.0, 70.0, "bybit_1", "paper", "open"),
        ("pkg-pb", "sol_pullback_2h", "SOLUSDT", "short", 72.0, 73.5, "bybit_1", "paper", "open"),
        ("pkg-eqp", "slv_trend_1h", "SLV", "long", 30.0, 29.0, "alpaca_paper", "paper", "open"),
        ("pkg-eql", "slv_trend_1h", "SLV", "short", 30.0, 31.0, "alpaca_live", "real_money", "open"),
    ]
    tickets = [("t1", "pkg-prop", "ml_entry", "SOLUSDT", "short", 71.34, 73.17, "tradeify_1", "filled")]
    legs = ce.read_open_legs(_db(tmp_path, trades, tickets), strategies_path=strategies_yaml)
    assert {x["order_package_id"] for x in legs["legs"]} == {"pkg-prop", "pkg-eql"}
    assert legs["books"]["journal"]["paper_testing_rows_skipped"] == 3
    assert ce.find_conflicts(legs["legs"]) == []  # the prop short alone, the SLV short alone


def test_mirror_and_prop_still_conflict_with_real_money(tmp_path, strategies_yaml):
    trades = [("pkg-m", "ml_entry", "SOLUSDT", "long", 71.0, 70.0, "bybit_portfolio", "paper", "open")]
    tickets = [("t1", "pkg-prop", "ml_entry", "SOLUSDT", "short", 71.34, 73.17, "tradeify_1", "filled")]
    legs = ce.read_open_legs(_db(tmp_path, trades, tickets), strategies_path=strategies_yaml)
    conflicts = ce.find_conflicts(legs["legs"])
    assert [set(c["packages"]) for c in conflicts] == [{"pkg-m", "pkg-prop"}]


def test_in_scope_is_class_or_mirror():
    mirrors = {"bybit_portfolio", "alpaca_portfolio"}
    assert ce.in_scope("bybit_2", "real_money", mirrors) and ce.in_scope("tradeify_1", "prop", mirrors)
    assert ce.in_scope("bybit_portfolio", "paper", mirrors) and ce.in_scope("alpaca_portfolio", "paper", mirrors)
    for testing in ("bybit_1", "alpaca_paper", "ib_paper", "alpaca_options_paper"):
        assert not ce.in_scope(testing, "paper", mirrors)
