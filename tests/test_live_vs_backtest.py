"""scripts/research/live_vs_backtest.py -- the live-vs-backtest first step."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops")):
    if p not in sys.path:
        sys.path.insert(0, p)

import live_vs_backtest as lvb  # noqa: E402

# Backtest corpus: mean +0.5R, sd ~1; 60 trades, deterministic.
BT = [(-1.0 if i % 3 == 0 else 1.0) + (0.0 if i % 2 else 0.5) for i in range(60)]


def _root(tmp_path, leg="leg_a", xs=BT, with_run=True):
    (tmp_path / "comms/strategy_evidence/runs").mkdir(parents=True)
    run = "comms/strategy_evidence/runs/leg_a__trades.jsonl"
    if with_run:
        (tmp_path / run).write_text("\n".join(json.dumps({"net_r": x}) for x in xs))
    (tmp_path / f"comms/strategy_evidence/{leg}.json").write_text(
        json.dumps({"strategy": leg, "source_run": run, "fidelity": "faithful"}))
    return tmp_path


def _row(total_r, n=20):
    return {"name": "leg_a", "trades": n, "rTradeCount": n, "totalR": total_r,
            "totalPnlMeasured": 1.0, "pnlCoverage": 1.0}


def test_verdict_flips_with_live_r(tmp_path):
    root = _root(tmp_path)
    res = {r: lvb.check_leg("leg_a", "realMoney", _row(r), root, draws=4000)["verdict"]
           for r in (-30.0, 10.0, 80.0)}
    assert res == {-30.0: lvb.BELOW, 10.0: lvb.CONSISTENT, 80.0: lvb.ABOVE}


def test_band_and_percentile_are_reported(tmp_path):
    r = lvb.check_leg("leg_a", "realMoney", _row(10.0), _root(tmp_path), draws=4000)
    assert r["p5"] < r["p50"] < r["p95"] and r["n"] == 20
    assert 5.0 <= r["live_percentile"] <= 95.0 and r["backtest_n"] == 60


def test_deterministic_for_fixed_seed(tmp_path):
    root = _root(tmp_path)
    a = lvb.check_leg("leg_a", "realMoney", _row(3.0), root, draws=2000)
    b = lvb.check_leg("leg_a", "realMoney", _row(3.0), root, draws=2000)
    assert a == b


def test_no_backtest_record_and_missing_source_run(tmp_path):
    assert lvb.check_leg("nope", "realMoney", _row(1.0), tmp_path)["verdict"] == lvb.NO_BACKTEST
    root = _root(tmp_path, with_run=False)
    r = lvb.check_leg("leg_a", "realMoney", _row(1.0), root)
    assert r["verdict"] == lvb.NO_BACKTEST and "not a committed file" in r["why"]


def test_too_few_backtest_rows_is_no_backtest(tmp_path):
    root = _root(tmp_path, xs=[1.0])
    assert lvb.check_leg("leg_a", "realMoney", _row(1.0), root)["verdict"] == lvb.NO_BACKTEST


def test_no_live_trades_is_not_a_verdict(tmp_path):
    root = _root(tmp_path)
    assert lvb.check_leg("leg_a", "mirror", None, root)["verdict"] == lvb.NO_LIVE
    assert lvb.check_leg("leg_a", "mirror", {"rTradeCount": 0, "totalR": None}, root)["verdict"] == lvb.NO_LIVE


def test_thin_n_is_insufficient_and_flags_worse_than_worst(tmp_path):
    root = _root(tmp_path)
    r = lvb.check_leg("leg_a", "realMoney", _row(-1.5, n=1), root, draws=2000)
    assert r["verdict"] == lvb.THIN and r["worse_than_worst_bt_trade"] is True
    r = lvb.check_leg("leg_a", "realMoney", _row(-0.5, n=1), root, draws=2000)
    assert r["verdict"] == lvb.THIN and r["worse_than_worst_bt_trade"] is False


def test_run_reads_both_books_from_payload(tmp_path):
    root = _root(tmp_path)
    side = {"perStrategy": {"leg_a": {"last": {"perStrategy": [_row(-30.0)]}}}}
    recent = {"realMoney": side, "mirror": {"perStrategy": {}}}
    rows = lvb.run(recent, [("acct", "leg_a")], root, draws=2000)
    assert [(r["book"], r["verdict"]) for r in rows] == [("realMoney", lvb.BELOW),
                                                         ("mirror", lvb.NO_LIVE)]


def test_real_corpus_loads_for_stage2_legs():
    """Reads the repo's own committed evidence (not a fixture)."""
    bt = lvb.load_backtest_r("xrp_pullback_2h")
    assert len(bt["xs"]) >= 30 and bt["why"] is None


# ── the config-date cut (PERF-F1-DEMOTION-SIGNAL, 2026-11-12) ──────────────
def _recent(total_r, since=None, n=20):
    book = {"readState": "ok", "perStrategy": {"leg_a": {"last": {"perStrategy": [_row(total_r, n)]}}}}
    return {"since": since, "realMoney": book, "mirror": book}


def test_cut_applied_reads_the_cut_payload_not_the_uncut_one(tmp_path):
    root = _root(tmp_path)
    cuts = {"leg_a": {"since": "2026-11-06T21:52:07Z", "fingerprint": None}}
    rows = lvb.run(_recent(-30.0), [("acct", "leg_a")], root, draws=2000, cuts=cuts,
                   cut_payloads={"2026-11-06T21:52:07Z": _recent(10.0, since="2026-11-06T21:52:07Z")})
    assert {r["config_cut"] for r in rows} == {"applied"}
    assert {r["verdict"] for r in rows} == {lvb.CONSISTENT}      # uncut would read BELOW


def test_cut_payload_without_since_echo_is_unavailable_never_the_uncut_rows(tmp_path):
    root = _root(tmp_path)
    cuts = {"leg_a": {"since": "2026-11-06T21:52:07Z", "fingerprint": None}}
    rows = lvb.run(_recent(-30.0), [("acct", "leg_a")], root, draws=2000, cuts=cuts,
                   cut_payloads={"2026-11-06T21:52:07Z": _recent(10.0, since=None)})   # old route: no echo
    assert {r["verdict"] for r in rows} == {lvb.CUT_UNAVAILABLE}
    assert {r["config_cut"] for r in rows} == {"unavailable"}


def test_unknown_cut_reads_uncut_and_says_so(tmp_path):
    rows = lvb.run(_recent(10.0), [("acct", "leg_a")], _root(tmp_path), draws=2000,
                   cuts={"leg_a": {"since": None, "fingerprint": None, "why": "shallow"}}, cut_payloads={})
    assert {r["config_cut"] for r in rows} == {"unknown"} and {r["verdict"] for r in rows} == {lvb.CONSISTENT}


def test_stale_backtest_when_record_fingerprint_differs(tmp_path):
    root = _root(tmp_path)
    rec = root / "comms/strategy_evidence/leg_a.json"
    rec.write_text(json.dumps({**json.loads(rec.read_text()), "config_fingerprint": "sha256:old"}))
    r = lvb.check_leg("leg_a", "realMoney", _row(10.0), root, draws=2000, current_fp="sha256:new")
    assert r["verdict"] == lvb.STALE_BT
    assert lvb.check_leg("leg_a", "realMoney", _row(10.0), root, draws=2000,
                         current_fp="sha256:old")["verdict"] == lvb.CONSISTENT


def test_config_since_finds_the_commit_that_set_the_current_fingerprint(tmp_path):
    import subprocess

    def git(*a, date=None):
        env = {"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date} if date else {}
        import os
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", **env})
    git("init", "-q")
    cfg = tmp_path / "config/strategies.yaml"
    cfg.parent.mkdir(parents=True)
    steps = [("2026-11-01T00:00:00+00:00", {"leg_a": {"lookback": 10}, "leg_b": {"x": 1}}),
             ("2026-11-06T21:52:07+00:00", {"leg_a": {"lookback": 20}, "leg_b": {"x": 1}}),
             # a gate-only change keeps the fingerprint (execution is excluded from it)
             ("2026-11-08T00:00:00+02:00", {"leg_a": {"lookback": 20, "execution": "live"}, "leg_b": {"x": 1}})]
    import yaml
    for date, body in steps:
        cfg.write_text(yaml.safe_dump({"strategies": body}))
        git("add", "-A")
        git("commit", "-q", "-m", date, date=date)
    out = lvb.config_since(["leg_a", "leg_b", "leg_gone"], tmp_path)
    assert out["leg_a"]["state"] == "derived" and out["leg_a"]["since"] == "2026-11-06T21:52:07Z"
    # leg_b never changed: the history ends before a change -> unknown, never the root's date
    assert out["leg_b"]["state"] == "unknown" and out["leg_b"]["since"] is None and out["leg_b"]["why"]
    assert out["leg_gone"]["since"] is None and "not in" in out["leg_gone"]["why"]
