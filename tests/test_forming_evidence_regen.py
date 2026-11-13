"""CRYPTO-FORMING-RDM-FORWARD: the pullback harness's forming-bar 1m forward and the crypto forming-leg evidence regen."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

import regime_debt_matrix as rdm  # noqa: E402
import forming_evidence_regen as fer  # noqa: E402


def _leg(name):
    cfgs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    return cfgs.get("strategies", cfgs)[name]


def test_pullback_forming_1m_forward_flips_faithful():
    cfg = _leg("eth_pullback_2h")
    assert rdm.classify(cfg) == "pullback"
    argv, faithful, omitted = rdm.build_harness_cmd("eth_pullback_2h", cfg, "pullback", "d.csv", "2h", "e.jsonl", "j.json")
    assert "decision_bar" in omitted and not faithful and "--decision-bar" not in argv
    argv, faithful, omitted = rdm.build_harness_cmd("eth_pullback_2h", cfg, "pullback", "d.csv", "2h", "e.jsonl", "j.json",
                                                    forming_1m="m.csv")
    assert "decision_bar" not in omitted and faithful, omitted
    assert argv[argv.index("--decision-bar") + 1] == "forming"
    assert argv[argv.index("--minutes-1m-csv") + 1] == "m.csv"
    assert argv[argv.index("--strategy-name") + 1] == "eth_pullback_2h"
    assert "--decision-session" not in argv  # crypto: no session mode


def test_pullback_closed_leg_never_switched_to_forming():
    cfg = {**_leg("eth_pullback_2h"), "decision_bar": "closed"}
    argv, faithful, omitted = rdm.build_harness_cmd("eth_pullback_2h", cfg, "pullback", "d.csv", "2h", "e.jsonl", "j.json",
                                                    forming_1m="m.csv")
    assert "--decision-bar" not in argv and "decision_bar" not in omitted


def test_backtest_pullback_accepts_the_1m_cli():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "backtest_pullback.py"), "--help"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "--minutes-1m-csv" in r.stdout and "--decision-session" in r.stdout


def test_plan_scopes_binance_forming_trend_and_pullback_only():
    rows = {r["leg"]: r for r in fer.plan(["eth_pullback_2h", "trend_donchian_sol_prop", "slv_trend_1h", "no_such_leg"])}
    assert not rows["eth_pullback_2h"].get("skip") and rows["eth_pullback_2h"]["harness"] == "pullback"
    assert not rows["trend_donchian_sol_prop"].get("skip") and rows["trend_donchian_sol_prop"]["data_start"]
    assert "yahoo" in rows["slv_trend_1h"]["skip"]
    assert rows["no_such_leg"]["skip"]


def test_self_test():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / "forming_evidence_regen.py"), "--self-test"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "self-test passed" in r.stdout
