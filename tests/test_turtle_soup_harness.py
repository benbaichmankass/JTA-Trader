"""Build gap (b) (row E25 / RQ-20261101-78fc-12): turtle_soup is routed to a faithful per-leg harness.

Pins: the classifier routes exactly the turtle_soup leg; its argv forwards every live key as --override (so an
exit_lever_ablation arm's cfg is what runs) and grades faithful; keys the live adapter never reads stay PLAIN; and
the harness's own offline self-test (position grouping, R normalisation, drawdown) passes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import regime_debt_matrix as rdm  # noqa: E402


def _legs():
    c = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    return c.get("strategies", c)


def test_classifier_routes_exactly_turtle_soup():
    routed = [n for n, b in _legs().items() if isinstance(b, dict) and rdm.classify(b) == "turtle_soup"]
    assert routed == ["turtle_soup"]


def test_argv_forwards_every_live_key_and_is_faithful():
    cfg = _legs()["turtle_soup"]
    argv, faithful, omitted = rdm.build_harness_cmd("turtle_soup", cfg, "turtle_soup", "d.csv", "15m", "e.jsonl", "j.json")
    assert faithful and omitted == []
    assert argv[1].endswith("scripts/backtest_turtle_soup.py")
    overrides = {argv[i + 1].split("=", 1)[0] for i, t in enumerate(argv) if t == "--override"}
    live = {k for k in rdm._TS_LEVER_KEYS if cfg.get(k) is not None}
    assert overrides == live


def test_unread_live_config_keys_are_plain_not_levers():
    for k in ("entry_tf", "max_entry_wait_bars_1m", "trail_atr_mult"):
        assert k in rdm._TS_PLAIN and k not in rdm._TS_LEVER_KEYS
    src = "\n".join(p.read_text() for p in (REPO / "src").rglob("*.py"))
    assert "sweep_lookback_15m" in src                       # the probe can find a positive
    for k in ("entry_tf", "max_entry_wait_bars_1m", "trail_atr_mult"):
        assert k not in src, f"{k} is now read under src/ -- it must become a modelled lever, not PLAIN"


def test_an_undeclared_key_degrades_to_approximate():
    cfg = {**_legs()["turtle_soup"], "some_new_lever": 1}
    _argv, faithful, omitted = rdm.build_harness_cmd("turtle_soup", cfg, "turtle_soup", "d.csv", "15m", "e", "j")
    assert not faithful and omitted == ["some_new_lever"]


def test_harness_self_test():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "backtest_turtle_soup.py"), "--self-test"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=300, check=False)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
