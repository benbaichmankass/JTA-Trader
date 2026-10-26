"""DESK-6-SHADOW-PILOT: the desk branch hops (publish, mirror) and the outcome replay.

Every row the pilot produces must pass desk-records-guard on main, so the tests run the guard's own
findings() over what these scripts write, not a hand-written expectation.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts" / "ci", ROOT / "scripts" / "ops", ROOT / "tests"):
    sys.path.insert(0, str(p))

import check_desk_records as cdr  # noqa: E402
import desk_branch  # noqa: E402
import desk_outcomes  # noqa: E402
from test_trading_desk_brief import _example, _scan_packet  # noqa: E402

CUT = datetime(2026, 10, 26, 13, 0, tzinfo=timezone.utc)
H = 3600


def _bar(i, o, h, l, c):
    return {"time": CUT.timestamp() + i * H, "open": o, "high": h, "low": l, "close": c}


def _prop(**kw):
    p = {"symbol": "ETHUSDT", "venue_class": "bybit:perp", "side": "long", "timeframe": "1h", "horizon_bars": 4,
         "entry": {"type": "market", "level": 100.0, "good_till_bars": 2},
         "stop": {"level": 98.0, "basis": "swing_level"}, "tp": {"level": 104.0, "basis": "swing_level", "p_hit": 0.4},
         "expected_r_net": 0.2, "thesis": "t", "novelty": "unverifiable", "onboarding": "onboarded"}
    p.update(kw)
    return p


def _zero(**kw):
    return 0.0


def test_replay_tp_sl_both_horizon_and_not_yet():
    tp = [_bar(0, 100, 101, 99.5, 100.5), _bar(1, 100.5, 104.5, 100, 104)]
    assert desk_outcomes.replay(_prop(), CUT, tp, _zero)["close_reason"] == "tp_hit"
    both = [_bar(0, 100, 105, 97, 100)]
    r = desk_outcomes.replay(_prop(), CUT, both, _zero)
    assert r["close_reason"] == "sl_hit" and r["net_r"] == -1.0  # both in one bar -> the stop
    flat = [_bar(i, 100, 100.5, 99.5, 101) for i in range(4)]
    r = desk_outcomes.replay(_prop(), CUT, flat, _zero)
    assert r["close_reason"] == "horizon" and r["net_r"] == 0.5 and r["bars_held"] == 4
    assert desk_outcomes.replay(_prop(), CUT, flat[:2], _zero) is None  # horizon not elapsed: no row
    early = [_bar(-1, 50, 200, 1, 50)] + flat  # a bar opening before the cutoff is never used
    assert desk_outcomes.replay(_prop(), CUT, early, _zero)["close_reason"] == "horizon"


def test_replay_limit_fill_and_expiry_and_cost():
    lim = _prop(entry={"type": "limit", "level": 99.0, "good_till_bars": 2}, stop={"level": 97.0, "basis": "swing_level"})
    miss = [_bar(0, 100, 101, 99.5, 100), _bar(1, 100, 101, 99.5, 100)]
    assert desk_outcomes.replay(lim, CUT, miss, _zero) == {"kind": "expired_unfilled"}
    hit = [_bar(0, 100, 100, 98.9, 99.5)] + [_bar(i, 99.5, 99.8, 99.2, 99.5) for i in range(1, 4)]
    r = desk_outcomes.replay(lim, CUT, hit, lambda **kw: 0.1)
    assert r["kind"] == "replayed" and abs(r["net_r"] - (0.25 - 0.1)) < 1e-9


def test_run_writes_rows_the_guard_accepts(tmp_path):
    p = _scan_packet()
    prop_row = _example(p)
    nt = copy.deepcopy(prop_row)
    nt.update(decision_id="DD-20261026T1300Z-scan-1h-2", action="no_trade", proposal=None, judge_prior=None)
    for a in nt["alternatives"]:
        a["chosen"] = a["action"] == "no_trade"
    d = tmp_path / "desk"
    (d / "packets").mkdir(parents=True)
    (d / "packets" / f"{p['meta']['packet_id']}.json").write_text(json.dumps(p))
    (d / "decisions.jsonl").write_text(json.dumps(prop_row) + "\n" + json.dumps(nt) + "\n")
    for f in ("touches.jsonl", "outcomes.jsonl", "consumed.jsonl"):
        (d / f).write_text("")
    # ETH long limit 99 / stop 96 / tp 105, good_till 3, horizon 12: fills bar 1, tp bar 2
    bars = [_bar(0, 100, 100.5, 99.5, 100), _bar(1, 100, 100, 98.8, 99.2), _bar(2, 99.2, 105.5, 99, 105)]
    bars += [_bar(i, 105, 105.5, 104.5, 105) for i in range(3, 20)]
    now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    res = desk_outcomes.run(d / "decisions.jsonl", d / "outcomes.jsonl", lambda s, tf: bars, now=now)
    assert res["written"] == 2
    rows = [json.loads(x) for x in (d / "outcomes.jsonl").read_text().splitlines()]
    assert {r["kind"] for r in rows} == {"replayed", "not_computable"}
    assert next(r for r in rows if r["kind"] == "replayed")["close_reason"] == "tp_hit"
    assert cdr.findings(decisions=d / "decisions.jsonl", touches=d / "touches.jsonl", packets=d / "packets") == []
    again = desk_outcomes.run(d / "decisions.jsonl", d / "outcomes.jsonl", lambda s, tf: bars, now=now)
    assert again["written"] == 0  # idempotent by decision_id


def test_run_could_not_look_writes_nothing(tmp_path):
    p = _scan_packet()
    (tmp_path / "decisions.jsonl").write_text(json.dumps(_example(p)) + "\n")
    res = desk_outcomes.run(tmp_path / "decisions.jsonl", tmp_path / "outcomes.jsonl", lambda s, tf: None,
                            now=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc))
    assert res["written"] == 0 and res["waiting"] == ["DD-20261026T1300Z-scan-1h-1"]


def test_publish_pointer_matches_the_guard_and_refuses_a_bad_packet(tmp_path):
    p = _scan_packet()
    res = desk_branch.publish(p, tmp_path)
    assert res["state"] == "ok" and res["packet_sha"] == cdr.packet_sha(p)
    staged = json.loads((tmp_path / res["path"]).read_text())
    assert cdr.packet_sha(staged) == res["packet_sha"]
    assert json.loads((tmp_path / desk_branch.POINTER).read_text())["packet_id"] == p["meta"]["packet_id"]
    bad = copy.deepcopy(p)
    bad["universe"] = []
    assert desk_branch.publish(bad, tmp_path / "x")["state"] == "refused"


def test_mirror_by_decision_id_with_its_packet(tmp_path):
    p = _scan_packet()
    row = json.dumps(_example(p))
    pk = json.dumps(p).encode()
    branch = {desk_branch.DECISIONS: (row + "\n").encode(), f"{desk_branch.PACKETS}/{p['meta']['packet_id']}.json": pk}
    res = desk_branch.mirror(tmp_path, branch.get)
    assert res["mirrored"] == 1 and not res["skipped"]
    assert desk_branch.mirror(tmp_path, branch.get)["mirrored"] == 0  # re-run is a no-op
    (tmp_path / desk_branch.DECISIONS).write_text("")
    (tmp_path / f"{desk_branch.PACKETS}/{p['meta']['packet_id']}.json").write_text("{}")
    res = desk_branch.mirror(tmp_path, branch.get)
    assert res["mirrored"] == 0 and "differs on main" in res["skipped"][0]["why"]
    assert desk_branch.mirror(tmp_path, {}.get)["state"] == "could_not_look"
