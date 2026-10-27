"""Desk EVENT TRIGGERS (row DESK-SHORT-HOLD-LANE item 2): src/runtime/desk_event_trigger.py."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from src.runtime import desk_event_trigger as det
from scripts.ops import desk_intake as di

cdr = di.cdr
dw = cdr.desk_write
ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config/desk_triggers.yaml").read_text())
NOW = datetime(2026, 10, 27, 10, 30, 5, tzinfo=timezone.utc)


def bars(n=80, step=0.0, last=None):
    """n closed 5m bars ending at NOW: flat 1.0-range candles around 100, optional trend, optional last bar."""
    t0 = int(NOW.timestamp()) - 300 * n
    out, c = [], 100.0
    for i in range(n):
        o = c
        c = o + step
        out.append({"time": t0 + 300 * i, "open": o, "high": max(o, c) + 0.5, "low": min(o, c) - 0.5, "close": c})
    if last:
        out[-1] = dict(out[-1], **last)
    return out


def kinds(fs):
    return sorted(f["kind"] for f in fs)


def test_quiet_market_fires_nothing_and_a_forming_bar_is_dropped():
    b = bars()
    assert det.detect("AVAXUSDT", b, CFG) == []
    forming = b + [{"time": int(NOW.timestamp()), "open": 100, "high": 130, "low": 99, "close": 129}]
    assert det.closed_bars(forming, "5m", NOW) == b


def test_atr_burst_and_level_break():
    b = bars(last={"open": 100.0, "high": 104.0, "low": 99.8, "close": 103.9})
    fs = det.detect("AVAXUSDT", b, CFG)
    assert "atr_burst" in kinds(fs) and "level_break" in kinds(fs)
    lb = next(f for f in fs if f["kind"] == "level_break")
    assert lb["detail"]["side"] == "up" and lb["key"].startswith("AVAXUSDT|level_break|")


def test_sweep_is_a_wick_beyond_the_level_that_closes_back_inside():
    b = bars(last={"open": 100.0, "high": 101.2, "low": 99.6, "close": 100.1})
    assert kinds(det.detect("AVAXUSDT", b, CFG)) == ["liquidity_sweep"]


def test_momentum_burst_over_three_bars():
    b = bars()
    for i, c in zip((-3, -2, -1), (101.0, 102.0, 103.0)):
        b[i] = dict(b[i], open=c - 1, close=c, high=c + 0.1, low=c - 1.1)
    assert "momentum_burst" in kinds(det.detect("AVAXUSDT", b, CFG))


def test_near_signal_and_calendar_detectors():
    pk = {"meta": {"packet_id": "DP-20261027T1000Z-scan-1h"},
          "system_book": {"read_state": "read", "near_signals_read_state": "read",
                          "items": [{"symbol": "AVAXUSDT", "status": "near_signal", "bars_to_signal": 1, "leg": "x", "side": "long"}]}}
    cal = lambda s, now: (0.8, {"class": "cpi", "time": (now + timedelta(minutes=10)).isoformat()})  # noqa: E731
    assert kinds(det.detect_book("AVAXUSDT", pk, CFG, NOW, cal)) == ["calendar", "near_signal"]
    unread = copy.deepcopy(pk)
    unread["system_book"]["near_signals_read_state"] = "could_not_look"
    far = lambda s, now: (0.8, {"class": "cpi", "time": (now + timedelta(minutes=50)).isoformat()})  # noqa: E731
    assert det.detect_book("AVAXUSDT", unread, CFG, NOW, far) == []


def _f(kind, sym="AVAXUSDT"):
    return {"kind": kind, "symbol": sym, "bar": "b", "key": f"{sym}|{kind}|b", "detail": {}}


def test_plan_wakes_once_on_the_strongest_and_rate_limits_the_rest():
    chosen, lim = det.plan([_f("level_break"), _f("atr_burst")], {}, CFG, NOW)
    assert chosen["kind"] == "atr_burst" and lim == [(_f("level_break"), "not_strongest")]
    st = {"seen_keys": [_f("atr_burst")["key"]], "wakes": [{"at": (NOW - timedelta(minutes=10)).isoformat(), "symbol": "AVAXUSDT"}]}
    chosen, lim = det.plan([_f("atr_burst"), _f("level_break")], st, CFG, NOW)
    assert chosen is None and [w for _, w in lim] == ["deduped", "cooldown"]
    st = {"wakes": [{"at": (NOW - timedelta(minutes=m)).isoformat(), "symbol": "ETHUSDT"} for m in (5, 20)]}
    assert det.plan([_f("atr_burst")], st, CFG, NOW)[1][0][1] == "hour_cap"
    st = {"wakes": [{"at": (NOW - timedelta(minutes=5 * i)).isoformat(), "symbol": "ETHUSDT"}
                    for i in range(1, 1 + CFG["max_per_day"])]}
    assert all(det._parse(w["at"]).date() == NOW.date() for w in st["wakes"])
    assert det.plan([_f("atr_burst")], st, CFG, NOW)[1][0][1] == "day_cap"


def test_cost_line_states_the_measured_rate_and_the_ceiling():
    st = {"wakes": [{"at": NOW.isoformat()}, {"at": (NOW - timedelta(days=1)).isoformat()}]}
    c = det.cost_line(st, CFG, NOW)
    assert c["wakes_today"] == 1 and c["usd_ceiling_per_day"] == round(CFG["max_per_day"] * CFG["cost_per_wake_usd"], 2)


def test_labels_join_claudes_answer_and_the_outcome_on_packet_id():
    labs = [{"fired": _f("atr_burst"), "disposition": "posted", "packet_id": "P1"},
            {"fired": _f("level_break"), "disposition": "not_strongest", "packet_id": None}]
    out = det.join_labels(labs, [{"packet_id": "P1", "decision_id": "D1", "action": "propose_entry", "label_source": "live"}],
                          [{"decision_id": "D1", "kind": "realised", "r_net": 0.8}])
    assert out[0]["answer"] == "propose_entry" and out[0]["outcome"] == [{"kind": "realised", "r_net": 0.8}]
    assert out[1]["answer"] is None and out[1]["outcome"] is None


class _Http:
    def __init__(self, code=201):
        self.code, self.posts = code, []

    def __call__(self, method, url, body, auth):
        self.posts.append((method, url, json.loads(body)))
        return self.code, {"html_url": "u"}


def _stage(tmp_path):
    p = copy.deepcopy(cdr.GOOD_SCAN)
    p["meta"]["trigger"] = {"kind": "atr_burst", "symbol": "ETHUSDT", "bar": "b", "detail": {}}
    st = tmp_path / "stage"
    from scripts.ops import desk_branch
    assert desk_branch.publish(p, st, det.TRIGGER_POINTER)["state"] == "ok"
    assert not (st / "comms/desk/latest_scan.json").exists()  # the hourly pointer never moves
    return st, p


def _run(tmp_path, firing_bars, http, state=None, commit=("c" * 40, None)):
    logs = tmp_path / "logs"
    if state:
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "trigger_state.json").write_text(json.dumps(state))
    st, _ = _stage(tmp_path)
    calls = []
    res = det.run_once(cfg=CFG, now_fn=lambda: NOW, bars_fn=lambda s, tf, n: {"AVAXUSDT": firing_bars},
                       auth_fn=lambda: "tok", fetch=lambda url, auth: (404, None), http=http, pr_fn=lambda: 7,
                       build_fn=lambda f, cfg, text: (calls.append(f) or (st, None)),
                       commit_fn=lambda *a, **k: commit, calendar_fn=None, logs=logs, receipt=tmp_path / "r.json")
    labels = [json.loads(x) for x in (logs / "trigger_labels.jsonl").read_text().splitlines()] \
        if (logs / "trigger_labels.jsonl").exists() else []
    return res, labels, calls


def test_a_firing_lands_one_packet_and_posts_one_trigger_marker(tmp_path):
    http = _Http()
    res, labels, calls = _run(tmp_path, bars(last={"open": 100.0, "high": 104.0, "low": 99.8, "close": 103.9}), http)
    assert res["state"] == "posted" and len(calls) == 1 and calls[0]["kind"] == "atr_burst"
    (_, url, body), = http.posts
    assert url.endswith("/issues/7/comments") and '"kind":"desk-trigger-wake"' in body["body"]
    assert {x["disposition"] for x in labels} == {"posted", "not_strongest"}
    assert res["cost"]["wakes_today"] == 1 and "near_signal" in " ".join(res["unread"])
    res2, _, calls2 = _run(tmp_path, bars(last={"open": 100.0, "high": 104.0, "low": 99.8, "close": 103.9}), _Http())
    assert res2["state"] == "limited" and calls2 == []  # same bar: deduped, no second wake


def test_a_refused_commit_is_a_label_not_a_stop(tmp_path):
    res, labels, _ = _run(tmp_path, bars(last={"open": 100.0, "high": 104.0, "low": 99.8, "close": 103.9}), _Http(),
                          commit=(None, 403))
    assert res["state"] == "could_not_commit" and res["http_code"] == 403
    assert any(x["disposition"] == "could_not_commit" for x in labels)


def test_unreadable_candles_are_named_not_quiet(tmp_path):
    res = det.run_once(cfg=CFG, now_fn=lambda: NOW, bars_fn=lambda s, tf, n: {"AVAXUSDT": None}, auth_fn=lambda: None,
                       fetch=lambda url, auth: (404, None), calendar_fn=None, logs=tmp_path, receipt=tmp_path / "r.json")
    assert res["state"] == "quiet" and "AVAXUSDT:candles" in res["unread"]


def test_the_packet_schema_takes_a_trigger_and_desk_write_labels_the_row_with_it(tmp_path):
    p = copy.deepcopy(cdr.GOOD_SCAN)
    p["meta"]["trigger"] = {"kind": "atr_burst", "symbol": "ETHUSDT", "bar": "b", "detail": {"range_atr": 2.4}}
    assert cdr.packet_problems(p, json.loads(cdr.PACKET_SCHEMA.read_text())) == []
    draft = {"action": "no_trade", "confidence": "suggestive", "basis": "ev_positive", "rationale": "r", "weighed": []}
    row = dw.compile_row(draft, {"packet_id": p["meta"]["packet_id"], "packet_sha": cdr.packet_sha(p)}, p,
                         json.loads(cdr.DECISION_SCHEMA.read_text()), now=datetime(2026, 10, 26, 9, 5, tzinfo=timezone.utc),
                         skill_sha=None)
    assert row["trigger_event"] == "atr_burst"


def test_main_kicks_the_trigger_from_the_tick_loop():
    assert "desk_event_trigger.kick()" in (ROOT / "src/main.py").read_text()
