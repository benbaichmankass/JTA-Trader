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
CFG_LIVE = lrd.load_config()
# the pre-existing cases pin the trigger events; the judgement slot (DESK-AM-REFOCUS) has its own cases below
CFG = {**CFG_LIVE, "events": {k: v for k, v in CFG_LIVE["events"].items() if k != "judgement_cadence"}}


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


def test_floor_applies_to_paper_and_soak_accounts():
    # Operator 2026-10-26 "All accounts now" (MD-TRADE-DESK): paper and soak books are
    # floored too. Before that this test pinned bybit_1 as NOT floored.
    assert events(lrd.compute_due([row(account_id="bybit_1")], [], CFG, NOW)) == [["daily_floor"]]


def test_floor_not_applied_to_an_account_off_the_list():
    assert lrd.compute_due([row(account_id="oanda_practice")], [], CFG, NOW)["due_count"] == 0


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
    assert out["reviews_state"] == "read" and "mechanics_venue_tp" in out["events_not_evaluated"]
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
    # + the DESK-AM-REFOCUS judgement slot, which also needs no telemetry
    assert [e["event"] for e in due["pkg-4"]["events"]] == ["daily_floor", "judgement_cadence"]
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


# ---------------------------------------------------------------- mechanics dedupe (GLD wedge)
# Operator 2026-10-26: a wedged paper package must not be re-reviewed every bar. The review
# rows of that period carry a null trigger.level (the schema said number|null), so the
# dedupe is inferred from the row's evidence and re-surfaces only when the evidence moves.
def _gld_row():
    return row(order_package_id="pkg-gld", strategy="gld_pullback_1h", account_id="alpaca_paper",
               symbol="GLD", direction="long", telemetry_absent=True)


def _gld_ctx(venue_sl=416.09, pkg_sl=414.53875):
    return {"pkg-gld": {
        "venue": {"state": "read", "pkg_sl": pkg_sl, "pkg_tp": None, "meta_atr": 2.0925,
                  "snapshots": [{"account_id": "alpaca_paper", "read_state": "measured",
                                 "venue_sl": venue_sl, "ref_sl": pkg_sl,
                                 "read_at": NOW.isoformat()}]},
        "history": []}}


def _flag(event="manual", level=None, evidence="alpaca_paper: venue SL 416.09 != package SL 414.53875",
          sl=414.53875, at=NOW - timedelta(minutes=50), verdict="mismatch", action="flag_mechanics"):
    return {"order_package_id": "pkg-gld", "reviewed_at": at.isoformat(),
            "trigger": {"event": event, "level": level},
            "mechanics": {"verdict": verdict, "evidence": evidence},
            "recommendation": {"action": action}, "state": {"sl": sl, "tp": 461.32723, "peak_r": None}}


def _mech_due(reviews, ctx=None):
    res = lrd.compute_due([_gld_row()], reviews, CFG, NOW, market=ctx or _gld_ctx())
    return [(e["event"], e["level"]) for d in res["due"] for e in d["events"] if e["event"] == "mechanics"]


def test_gld_wedge_is_due_once_then_quiet_on_an_unchanged_repeat():
    assert _mech_due([]) == [("mechanics", "venue_sl_diverges")]
    for ev, lv in (("manual", None), ("mechanics", None), ("mechanics", "venue_sl_diverges")):
        assert _mech_due([_flag(ev, lv)]) == [], (ev, lv)  # null-level history rows too
    many = [_flag(at=NOW - timedelta(hours=h)) for h in range(1, 11)]
    assert _mech_due(many) == []


def test_gld_wedge_is_due_again_when_the_venue_stop_changes():
    assert _mech_due([_flag()], _gld_ctx(venue_sl=417.5)) == [("mechanics", "venue_sl_diverges")]
    assert _mech_due([_flag()], _gld_ctx(pkg_sl=413.9)) == [("mechanics", "venue_sl_diverges")]
    # ... and quiet again once that new state has been answered
    again = [_flag(), _flag("mechanics", "venue_sl_diverges", "alpaca_paper: venue SL 417.5 != package SL 414.53875")]
    assert _mech_due(again, _gld_ctx(venue_sl=417.5)) == []


def test_cleared_mismatch_forgets_the_answer():
    ok = _flag(verdict="match", action="hold", evidence="venue matches", at=NOW - timedelta(minutes=20))
    assert _mech_due([_flag(), ok]) == [("mechanics", "venue_sl_diverges")]


def test_a_later_review_that_is_not_a_mechanics_answer_does_not_reopen_it():
    mkt = review("pkg-gld", "giveback", 1.0, at=NOW - timedelta(minutes=10))
    mkt["mechanics"] = {"verdict": "mismatch", "evidence": "alpaca_paper: venue SL 416.09 != package SL 414.53875"}
    assert _mech_due([_flag(), mkt]) == []


def test_market_events_still_dedupe_on_event_and_level_and_ignore_the_mechanics_rule():
    at = NOW - timedelta(hours=3)
    r = row(open_r=1.2, peak_r=1.2)
    assert lrd.compute_due([r], [review(event="r_milestone", level=1.0, at=at)], CFG, NOW)["due_count"] == 0
    r = row(open_r=2.2, peak_r=2.2)
    res = lrd.compute_due([r], [review(event="r_milestone", level=1.0, at=at)], CFG, NOW)
    assert [e["level"] for d in res["due"] for e in d["events"]] == [2.0]


# --- LTR-DUE-MIRROR-LAG: rows on live-review/rows that main lacks ------------------------------

def _branch(rows):
    return lambda: {"state": "read", "rows": rows, "tip": "abc"}


def _branch_row(rid, at, peak, event="r_milestone", level=2.0):
    r = review(event=event, level=level, at=at, peak=peak)
    r["review_id"] = rid
    return r


def test_branch_only_review_suppresses_rewake_new_peak_and_cooldown(tmp_path):
    db = str(tmp_path / "j.db")
    _db(db, [("pkg-1", "7", "ada_pullback_2h", "ADAUSDT", "bybit_2", "short",
              2.2, 2.3, "measured", 0.1, 3.0, NOW.isoformat())])
    main = tmp_path / "main.jsonl"
    main.write_text(json.dumps(dict(review(at=NOW - timedelta(hours=30), peak=1.8), review_id="old")) + "\n")
    # main alone: peak 2.3 vs last reviewed 1.8 (>= step_r 0.5) -> new_peak due, no cooldown
    alone = lrd.live_review_due(db_path=db, reviews_path=str(main), now=NOW)
    assert any(e["event"] == "new_peak" for d in alone["due"] for e in d["events"])
    # the 2.14R review exists only on the branch, one bar ago: new_peak is below step_r over it
    # and the package is inside the cooldown bar
    row = _branch_row("br1", NOW - timedelta(minutes=5), 2.14)
    out = lrd.live_review_due(db_path=db, reviews_path=str(main), now=NOW, branch=_branch([row]))
    assert out["branch_state"] == "read" and out["branch_rows_added"] == 1
    assert not any(e["event"] in ("new_peak", "r_milestone") for d in out["due"] for e in d["events"])


def test_branch_rows_dedupe_by_review_id_against_main():
    m = [{"review_id": "a", "order_package_id": "p"}]
    got = lrd.merge_branch_rows(m, [{"review_id": "a", "order_package_id": "p"}, {"review_id": "b"}])
    assert [r["review_id"] for r in got] == ["a", "b"]


def test_branch_read_failure_falls_back_to_main_only(tmp_path):
    db = str(tmp_path / "j.db")
    _db(db, [("pkg-1", "7", "ada_pullback_2h", "ADAUSDT", "bybit_2", "short",
              0.2, 0.3, "measured", 0.1, 3.0, NOW.isoformat())])
    main = tmp_path / "main.jsonl"
    main.write_text(json.dumps(review(at=NOW - timedelta(hours=1))) + "\n")
    bad = lambda: {"state": "could_not_look", "rows": [], "reason": "branch_ref_absent: x"}  # noqa: E731
    out = lrd.live_review_due(db_path=db, reviews_path=str(main), now=NOW, branch=bad)
    assert out["read_state"] == "looked" and out["reviews_state"] == "read"
    assert out["branch_state"] == "could_not_look" and "branch_ref_absent" in out["branch_reason"]
    boom = lrd.read_branch_rows(git=lambda *a, **k: (1, "no ref"))
    assert boom["state"] == "could_not_look" and boom["rows"] == []
    raising = lrd.read_branch_rows(git=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert raising["state"] == "could_not_look"


# ----------------------------------------------------------------------------- DESK-AM-REFOCUS judgement_cadence

def _prior(last=None):
    return {"fired": set(), "last": last, "peak": None, "mech": None}


def test_judgement_cadence_is_one_utc_slot_per_timeframe():
    now = datetime(2026, 10, 31, 9, 30, tzinfo=timezone.utc)
    ev = lrd.judgement_cadence_event(_prior(), CFG_LIVE, now, 7200)                 # 2h leg: 4h slots
    assert ev[0] == "judgement_cadence" and ev[1] == "2026-10-31T08:00:00+00:00"
    # operator 2026-10-30: every timeframe every 4h
    assert lrd.judgement_cadence_event(_prior(), CFG_LIVE, now, 14400)[1] == "2026-10-31T08:00:00+00:00"
    assert lrd.judgement_cadence_event(_prior(), CFG_LIVE, now, 86400)[1] == "2026-10-31T08:00:00+00:00"


def test_a_review_inside_the_slot_satisfies_it_and_short_hold_timeframes_get_none():
    now = datetime(2026, 10, 31, 9, 30, tzinfo=timezone.utc)
    assert lrd.judgement_cadence_event(_prior(datetime(2026, 10, 31, 8, 5, tzinfo=timezone.utc)), CFG_LIVE, now, 7200) is None
    assert lrd.judgement_cadence_event(_prior(datetime(2026, 10, 31, 7, 55, tzinfo=timezone.utc)), CFG_LIVE, now, 7200) is not None
    assert lrd.judgement_cadence_event(_prior(), CFG_LIVE, now, 900) is None          # 15m: the short-hold lane
    assert lrd.judgement_cadence_event(_prior(), {"events": {}}, now, 7200) is None   # block removed = reverted


def test_judgement_cadence_reaches_the_due_list_and_dedupes_on_its_slot():
    now = datetime(2026, 10, 31, 9, 30, tzinfo=timezone.utc)
    row = {"order_package_id": "pkg-jc", "strategy": "ada_pullback_2h", "account_id": "bybit_2", "lifecycle": "open",
           "open_r": 0.2, "peak_r": 0.3, "updated_at": now.isoformat()}
    due = lrd.compute_due([row], [], CFG_LIVE, now=now)
    evs = [e for d in due["due"] for e in d["events"] if e["event"] == "judgement_cadence"]
    assert len(evs) == 1 and evs[0]["level"] == "2026-10-31T08:00:00+00:00"
    answered = {"order_package_id": "pkg-jc", "reviewed_at": "2026-10-31T09:31:00Z",
                "trigger": {"event": "judgement_cadence", "level": "2026-10-31T08:00:00+00:00"}}
    again = lrd.compute_due([row], [answered], CFG_LIVE, now=now + timedelta(minutes=5))
    assert not [e for d in again["due"] for e in d["events"] if e["event"] == "judgement_cadence"]


def test_judgement_cadence_skips_unreviewed_accounts_and_mandate_scoped_packages():
    now = datetime(2026, 10, 31, 9, 30, tzinfo=timezone.utc)
    row = {"order_package_id": "pkg-jc", "strategy": "ada_pullback_2h", "lifecycle": "open",
           "open_r": 0.2, "peak_r": 0.3, "updated_at": now.isoformat()}
    jc = lambda res: [e for d in res["due"] for e in d["events"] if e["event"] == "judgement_cadence"]  # noqa: E731
    assert not jc(lrd.compute_due([dict(row, account_id="oanda_practice")], [], CFG_LIVE, now=now))
    cad = {"pkg-jc": {"mandate": "MD-X", "minutes": 60}}
    assert not jc(lrd.compute_due([dict(row, account_id="bybit_2")], [], CFG_LIVE, now=now, cadence=cad))


# ----------------------------------------------------------------------------- TRIGGER-FIRST-REVIEWS (2026-10-31)

TF_NOW = datetime(2026, 11, 3, 15, 10, tzinfo=timezone.utc)      # Tuesday, US RTH and CME open; 2h bar began 14:00
TF_CLOSED = datetime(2026, 11, 1, 15, 10, tzinfo=timezone.utc)   # Sunday: US equity closed; CME not yet open (18:00 ET)


def _tf_cfg(min_move=0.5):
    cfg = {"events": {"judgement_cadence": {"hours_by_timeframe": {"2h": 2}}}}
    if min_move is not None:
        cfg["events"]["judgement_cadence"]["min_move_atr"] = min_move
    return cfg


def _hist(prices, now, tf=7200, atr=2.0):
    """One path-history bar per tf, newest last, ending at the current bar."""
    n = len(prices)
    return {"history": [{"bar_ts": (lrd.bar_start(now, tf) - timedelta(seconds=tf * (n - 1 - i))).isoformat(),
                         "last_price": p, "atr": atr} for i, p in enumerate(prices)]}


def _jc(symbol, prior, ctx, now=TF_NOW, cfg=None):
    skips = []
    ev = lrd.judgement_cadence_event(prior, cfg or _tf_cfg(), now, 7200,
                                     {"order_package_id": "pkg-tf", "symbol": symbol}, ctx, skips)
    return ev, skips


def test_trigger_first_closed_market_package_gets_no_slot():
    for sym in ("SPY", "MGC"):
        ev, skips = _jc(sym, _prior(), None, now=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc))  # Sunday midday
        assert ev is None and len(skips) == 1
        assert skips[0]["state"] == "skipped_closed_market" and skips[0]["order_package_id"] == "pkg-tf"
    ev, skips = _jc("BTCUSDT", _prior(), None, now=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc))
    assert ev is not None and not skips                                              # crypto is always open


def test_trigger_first_open_market_no_new_bar_gets_no_slot():
    last = datetime(2026, 11, 3, 14, 5, tzinfo=timezone.utc)                          # inside the current 2h bar
    cfg = _tf_cfg()
    cfg["events"]["judgement_cadence"]["hours_by_timeframe"] = {"2h": 1}              # slot 15:00 > last, bar 14:00 <= last
    ev, skips = _jc("SPY", _prior(last), _hist([100, 101], TF_NOW), cfg=cfg)
    assert ev is None and skips[0]["state"] == "skipped_nothing_new" and "no closed 2h bar" in skips[0]["reason"]


def test_trigger_first_new_bar_but_small_move_gets_no_slot_and_big_move_fires():
    last = datetime(2026, 11, 3, 13, 55, tzinfo=timezone.utc)                         # a bar has closed since
    small = _jc("SPY", _prior(last), _hist([100.0, 100.0, 100.9], TF_NOW))            # 0.9 / ATR 2 = 0.45 < 0.5
    assert small[0] is None and small[1][0]["state"] == "skipped_nothing_new" and "0.45 ATR" in small[1][0]["reason"]
    at = _jc("SPY", _prior(last), _hist([100.0, 100.0, 101.0], TF_NOW))               # exactly 0.5 ATR
    assert at[0] is not None and at[0][0] == "judgement_cadence" and not at[1]
    down = _jc("MGC", _prior(last), _hist([100.0, 100.0, 98.0], TF_NOW))              # moves are absolute
    assert down[0] is not None and not down[1]


def test_trigger_first_unreadable_inputs_and_unknown_class_fire_with_a_reason():
    last = datetime(2026, 11, 3, 13, 55, tzinfo=timezone.utc)
    ev, skips = _jc("SPY", _prior(last), None)                                        # no history at all
    assert ev is not None and not skips and "unreadable" in lrd.package_novelty(_prior(last), None, 0.5, TF_NOW, 7200)[1]
    ev, _ = _jc("ZZZ-UNPROFILED", _prior(last), _hist([1, 1, 1], TF_NOW))             # unknown symbol -> crypto/open, moves 0
    assert ev is None                                                                  # open, but measured quiet
    ok, cls, why = lrd.package_market_state("SPY", TF_NOW)
    assert ok and cls == "us_equity"


def test_trigger_first_unknown_asset_class_reads_open_and_says_why(monkeypatch):
    import src.runtime.market_hours as mh
    monkeypatch.setattr(mh, "asset_class_for_symbol", lambda s: "weird_class")
    ok, cls, why = lrd.package_market_state("X", TF_NOW)
    assert ok and cls == "weird_class" and "not modelled" in why
    monkeypatch.setattr(mh, "asset_class_for_symbol", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, cls, why = lrd.package_market_state("X", TF_NOW)
    assert ok and "market_hours_unreadable" in why


def test_trigger_first_without_min_move_atr_only_the_market_gate_applies():
    last = datetime(2026, 11, 3, 14, 5, tzinfo=timezone.utc)
    ev, skips = _jc("SPY", _prior(last), _hist([100, 100], TF_NOW), cfg=_tf_cfg(None))
    assert ev is None and not skips                                                    # the slot was already reviewed (legacy rule)
    ev, skips = _jc("SPY", _prior(datetime(2026, 11, 3, 11, 0, tzinfo=timezone.utc)), None, cfg=_tf_cfg(None))
    assert ev is not None and not skips


def test_trigger_first_compute_due_records_skips_and_daily_floor_skips_only_closed_markets():
    cfg = dict(CFG_LIVE)
    floor = (cfg["events"]["daily_floor"].get("accounts") or ["bybit_2"])[0]
    row = {"order_package_id": "pkg-spy", "strategy": "ada_pullback_2h", "symbol": "SPY", "account_id": floor,
           "lifecycle": "open", "open_r": 0.1, "peak_r": 0.1}
    sun = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    res = lrd.compute_due([dict(row, updated_at=sun.isoformat())], [], cfg, now=sun)
    names = {e["event"] for d in res["due"] for e in d["events"]}
    assert "daily_floor" not in names and "judgement_cadence" not in names
    assert {s["event"] for s in res["skipped_slots"]} == {"daily_floor", "judgement_cadence"}
    assert all(s["state"] == "skipped_closed_market" for s in res["skipped_slots"])
    assert res["skipped_slots_count"] == 2
    tue = datetime(2026, 11, 3, 15, 10, tzinfo=timezone.utc)                          # open, never reviewed
    res = lrd.compute_due([dict(row, updated_at=tue.isoformat())], [], cfg, now=tue)
    names = {e["event"] for d in res["due"] for e in d["events"]}
    assert {"daily_floor", "judgement_cadence"} <= names and not res["skipped_slots"]
