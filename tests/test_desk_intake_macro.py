"""DESK-MACRO v2 paper routing (a): the macro brief is a second source for the desk intake's queue, judged by the SAME
rules as a desk propose_entry (both brackets, demo-floor gate, leg rostered, symbol on the leg). Seeded on first start."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))

import desk_intake as di  # noqa: E402

NOW = datetime(2026, 11, 27, 13, 30, tzinfo=timezone.utc)


def _trade(sym="SPY", stop=650.0, tp=720.0):
    return {"proposal": {"symbol": sym, "side": "long", "timeframe": "1d", "entry": {"type": "limit", "level": 690.0,
                         "good_till_bars": 3}, "stop": {"level": stop}, "tp": {"level": tp, "p_hit": 0.4}},
            "management": {"design": "d"}}


def _brief(tmp: Path, bid: str, trades, judged=NOW - timedelta(minutes=20), supersedes=None, name=None):
    b = {"schema": "desk_macro_brief/1", "brief_id": bid, "judged_at": judged.isoformat(), "supersedes": supersedes,
         "packet_path": "comms/desk/macro/packets/x.json", "packet_sha": "abc", "trades": trades}
    (tmp / f"{name or bid}.json").write_text(json.dumps(b))


def _run(tmp, logs, **kw):
    base = dict(apply=True, root=tmp, logs=logs, now_fn=lambda: NOW, mandates_fn=lambda: {"mandates": [
        {"id": "MD-TRADE-DESK", "functions": {"entry_generation": {}}}]}, leg_fn=lambda: True,
        accounts_fn=lambda: {"accounts": {}}, symbols_fn=lambda: ["SPY", "GLD"])
    base.update(kw)
    return di.run_macro_pass(**base)


def _log(logs):
    p = logs / "intake.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_first_start_seeds_and_never_trades_an_old_brief(tmp_path):
    briefs, logs = tmp_path / "b", tmp_path / "l"
    briefs.mkdir(), logs.mkdir()
    _brief(briefs, "DMB-1", [_trade()])
    st = _run(briefs, logs)
    assert st["seeded"] == 1 and not (logs / "accepted_proposals.jsonl").exists()


def test_new_trades_are_judged_by_the_desk_rules_and_queued(tmp_path):
    briefs, logs = tmp_path / "b", tmp_path / "l"
    briefs.mkdir(), logs.mkdir()
    _run(briefs, logs)                                         # seed (empty)
    _brief(briefs, "DMB-2", [_trade("SPY"), _trade("SLV"), _trade("GLD", tp=None)])
    st = _run(briefs, logs)
    v = {r["decision_id"]: (r["verdict"], r["detail"]) for r in _log(logs)}
    assert v["DMB-2/T1"][0] == "accepted"
    assert v["DMB-2/T2"] == ("refused", "symbol_not_in_desk_leg:SLV (leg trades ['SPY', 'GLD'])")
    assert v["DMB-2/T3"][1].startswith("both_brackets_required")
    q = [json.loads(x) for x in (logs / "accepted_proposals.jsonl").read_text().splitlines()]
    assert len(q) == 1 and q[0]["source"] == "desk_macro" and q[0]["proposal"]["symbol"] == "SPY"
    assert q[0]["intent_id"] == "MI-DMB-2-T1" and q[0]["management"] == {"design": "d"}
    assert st["verdicts"] == {"accepted": 1, "refused": 2}
    assert _run(briefs, logs)["new"] == 0                      # once


def test_a_superseded_brief_never_trades_and_the_gate_still_applies(tmp_path):
    briefs, logs = tmp_path / "b", tmp_path / "l"
    briefs.mkdir(), logs.mkdir()
    _run(briefs, logs)
    _brief(briefs, "DMB-3", [_trade()])
    _brief(briefs, "DMB-4", [_trade("GLD")], supersedes="DMB-3", name="day_DMB-4")
    _run(briefs, logs, mandates_fn=lambda: None)
    v = {r["decision_id"]: r for r in _log(logs)}
    assert "DMB-3/T1" not in v                                 # superseded: never judged
    assert v["DMB-4/T1"]["verdict"] == "refused" and v["DMB-4/T1"]["detail"].startswith(di.R_GATED)


def test_a_stale_brief_is_refused_named(tmp_path):
    briefs, logs = tmp_path / "b", tmp_path / "l"
    briefs.mkdir(), logs.mkdir()
    _run(briefs, logs)
    _brief(briefs, "DMB-5", [_trade()], judged=NOW - timedelta(hours=7))
    _run(briefs, logs)
    assert _log(logs)[0]["detail"].startswith("stale_decision")


def test_dry_run_writes_no_state(tmp_path):
    briefs, logs = tmp_path / "b", tmp_path / "l"
    briefs.mkdir(), logs.mkdir()
    _brief(briefs, "DMB-6", [_trade()])
    st = _run(briefs, logs, apply=False)
    assert st["verdicts"] == {"would_accept": 1} and not (logs / "intake_macro_state.json").exists()


def test_the_rows_watcher_runs_the_macro_source_only_when_briefs_change(tmp_path):
    from src.runtime import live_review_rows_watch as w
    calls = []
    files = [(("a.json", 1.0),)]
    st = w.run_macro_pass(files_fn=lambda: files[0], intake=lambda: calls.append(1) or {"exit": 0, "new": 1},
                          logs=tmp_path)
    assert st["intake"] == "ran" and calls == [1]
    st = w.run_macro_pass(files_fn=lambda: files[0], intake=lambda: calls.append(1) or {"exit": 0}, logs=tmp_path)
    assert st["intake"] == "unchanged" and calls == [1]
    files[0] = (("a.json", 1.0), ("b.json", 2.0))
    assert w.run_macro_pass(files_fn=lambda: files[0], intake=lambda: calls.append(1) or {"exit": 0},
                            logs=tmp_path)["intake"] == "ran"


# ----------------------------------------------------------------------------- (c) queue_scored: fetch on demand
def test_queue_scored_leg_ticks_only_live_queued_symbols():
    from src.units.strategies import claude_desk as cd
    at = "2026-11-27T13:00:00+00:00"
    rows = [{"at": at, "proposal": {"symbol": "SLV", "timeframe": "1d", "entry": {"good_till_bars": 3}}},
            {"at": at, "proposal": {"symbol": "FXI", "timeframe": "1h", "entry": {"good_till_bars": 1}}},
            {"at": at, "proposal": {"symbol": "XLE", "timeframe": "1h", "entry": {"good_till_bars": 1}, "max_hold_min": 600}},
            {"at": at, "proposal": {"symbol": "EEM"}},                       # expiry unreadable: kept a day, never dropped
            {"at": at, "proposal": {"symbol": "SLV", "timeframe": "1d", "entry": {"good_till_bars": 3}}}]
    t = datetime(2026, 11, 27, 16, 0, tzinfo=timezone.utc)
    assert cd.tick_symbols(rows, t) == ["SLV", "XLE", "EEM"]              # FXI expired at 14:00; XLE alive via max_hold
    assert cd.tick_symbols(rows, t + timedelta(days=4)) == []


def test_tick_exempt_legs_leave_the_static_fetch_set():
    from src.config.symbol_sets import is_tick_exempt, tick_strategies_cfg
    cfg = {"a": {"symbols": ["X"]}, "q": {"symbols": ["Y"], "queue_scored": True}, "p": {"symbols": ["Z"], "pool_scored": True}}
    t = tick_strategies_cfg(cfg)
    assert t["a"]["symbols"] == ["X"] and t["q"]["symbols"] == [] and t["p"]["symbols"] == []
    assert is_tick_exempt(cfg["q"]) and not is_tick_exempt(cfg["a"])
