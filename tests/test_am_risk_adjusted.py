"""RULE-AM-RISK-ADJUSTED-V1 (scripts/research/am_risk_adjusted.py): the risk-adjusted graduation rule for an
active-management action class (operator decision 2026-10-29, row AM-RISK-ADJUSTED-RULE; doctrine in
docs/ARCHITECTURE-CANONICAL.md § Active management, clause 4).

Planted positive and negative controls on the pure grade, the end-to-end wiring through
``exit_lever_ablation.py --grade risk_adjusted`` on synthetic candles, and the re-grade's own positive control:
the book maxDD it recomputes from a landed record's per-trade file must equal the harness's own figure.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import am_risk_adjusted as am  # noqa: E402


def _books():
    hold = am._synth(400, giveback=True)
    be = am._synth(400, giveback=False)
    rnd = [dict(t, net_r=(t["net_r"] - 0.3 if i % 4 == 0 else t["net_r"])) for i, t in enumerate(hold)]
    return hold, be, rnd


def test_rule_parameters_are_explicit_and_carried():
    for k in ("max_r_cost_per_trade", "min_dd_cut_pct", "min_cvar5_cut_pct", "fold_majority", "random_control"):
        assert k in am.RULE_V1
    assert am.RULE_V1["id"] == "RULE-AM-RISK-ADJUSTED-V1"
    assert (am.RULE_V1["max_r_cost_per_trade"], am.RULE_V1["min_dd_cut_pct"]) == (0.05, 0.15)
    hold, be, _ = _books()
    g = am.grade_risk_adjusted({"A": hold, "BE": be}, baseline="A", candidates=["BE"])
    assert g["rule"]["id"] == am.RULE_ID and g["rule"]["max_r_cost_per_trade"] == 0.05


def test_positive_control_passes():
    hold, be, rnd = _books()
    g = am.grade_risk_adjusted({"A": hold, "BE": be, "RND": rnd}, baseline="A", candidates=["BE"],
                               controls={"BE": ["RND"]})
    c = g["candidates"]["BE"]
    assert g["verdict"] == "pass" and c["label"] == "risk_adjusted_pass"
    assert all(c["clauses"].values())


def test_negative_control_fails_on_cost():
    hold, _be, rnd = _books()
    costly = [dict(t, net_r=t["net_r"] - 0.2) for t in hold]
    g = am.grade_risk_adjusted({"A": hold, "X": costly, "RND": rnd}, baseline="A", candidates=["X"],
                               controls={"X": ["RND"]})
    assert g["verdict"] == "fail" and g["candidates"]["X"]["clauses"]["R1_cost"] is False


def test_small_cost_big_cut_passes_and_large_cost_does_not():
    """The operator's trade-off: giving up a little R for a big risk cut passes; giving up more than the bar fails."""
    hold, be, rnd = _books()
    n = len(hold)
    winners = sum(1 for t in be if t["net_r"] > 0)
    for cost, expect in ((0.03, "pass"), (0.08, "fail")):
        # the R given up comes off the WINNERS (a banked or capped gain), so the losing tail is untouched
        need = cost * n - (sum(x["net_r"] for x in hold) - sum(x["net_r"] for x in be))
        shaved = [dict(t, net_r=t["net_r"] - (need / winners if t["net_r"] > 0 else 0.0)) for t in be]
        g = am.grade_risk_adjusted({"A": hold, "C": shaved, "RND": rnd}, baseline="A", candidates=["C"],
                                   controls={"C": ["RND"]})
        assert round(g["candidates"]["C"]["r_cost_per_trade"], 6) == pytest.approx(cost, abs=1e-6)
        assert g["candidates"]["C"]["verdict"] == expect


def test_without_random_control_it_cannot_pass():
    hold, be, _ = _books()
    g = am.grade_risk_adjusted({"A": hold, "BE": be}, baseline="A", candidates=["BE"])
    assert g["verdict"] == "indeterminate" and g["candidates"]["BE"]["label"] == "no_random_control"


def test_beaten_by_random_control_fails():
    hold, be, _ = _books()
    k = [dict(t, net_r=t["net_r"] + 0.1) for t in be]
    g = am.grade_risk_adjusted({"A": hold, "BE": be, "K": k}, baseline="A", candidates=["BE"], controls={"BE": ["K"]})
    assert g["candidates"]["BE"]["label"] == "fails_R4"


def test_floors():
    hold, be, _ = _books()
    assert am.grade_risk_adjusted({"A": hold[:20], "B": be[:20]}, baseline="A", candidates=["B"])["label"] == "underpowered"
    g = am.grade_risk_adjusted({"A": hold, "B": [dict(t) for t in hold]}, baseline="A", candidates=["B"])
    assert g["candidates"]["B"]["label"] == "lever_never_fired"


def test_freed_risk_budget_counts():
    """Extra trades the candidate takes (risk freed early) add to its book; r_cost is per BASELINE trade."""
    hold, be, _ = _books()
    extra = be + [dict(be[-1], net_r=4.0)]
    a = am.grade_risk_adjusted({"A": hold, "B": be}, baseline="A", candidates=["B"])["candidates"]["B"]
    b = am.grade_risk_adjusted({"A": hold, "B": extra}, baseline="A", candidates=["B"])["candidates"]["B"]
    assert b["r_cost_per_trade"] == pytest.approx(a["r_cost_per_trade"] - 4.0 / len(hold), abs=1e-6)


def test_max_drawdown_and_weekly_cvar_arithmetic():
    tr = [{"exit_time": f"2024-01-0{i}T00:00:00+00:00", "entry_time": "2024-01-01T00:00:00+00:00", "net_r": r}
          for i, r in enumerate([1, -2, -1, 3, -0.5], start=1)]
    assert am.max_drawdown(tr) == 3.0   # peak 1 -> trough -2
    m = am.book_metrics(tr)
    assert m["net_r"] == 0.5 and m["weeks"] == 1 and m["cvar5_week_r"] == 0.5


def test_self_test_passes():
    assert am._self_test() == 0


@pytest.mark.parametrize("unit", ["RQ-20261026-ed1c-17", "RQ-20261024-9a7e-01"])
def test_regrade_reproduces_the_harness_drawdown(unit):
    """Positive control for the re-grade: the book maxDD recomputed from the landed per-trade file equals the
    harness's own max_drawdown_r for the baseline arm (to rounding)."""
    spec = am.REGRADE_RECORDS[unit]
    d = REPO / spec["dir"]
    if not d.exists():
        pytest.skip("record not in this checkout")
    bt = json.loads((d / "A__bt.json").read_text())
    assert am.max_drawdown(am.load_trades(d / "A__trades.jsonl")) == pytest.approx(float(bt["max_drawdown_r"]), abs=1e-3)


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    import numpy as np
    import pandas as pd
    d = tmp_path_factory.mktemp("amra")
    rng = np.random.default_rng(11)
    ts = pd.date_range("2022-01-01", "2026-01-01", freq="2h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.01, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, len(ts))))
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo,
                  "close": c, "volume": 1000.0}).to_csv(d / "c.csv", index=False)
    out = d / "out"
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"),
                        "--leg", "xrp_pullback_2h", "--arm", "A=", "--arm", "BE15=--be-floor-r=1.5",
                        "--data-csv", str(d / "c.csv"), "--grade", "risk_adjusted", "--baseline", "A",
                        "--delta-r", "0", "--fold-majority", "2", "--folds", "4", "--n-floor", "10",
                        "--out", str(out)], cwd=REPO, capture_output=True, text=True, check=False, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return out


def test_end_to_end_grade_is_the_named_rule(e2e):
    rec = json.loads((e2e / "verdict.json").read_text())
    g = rec["measurement"]["grade"]
    assert g["rule"]["id"] == am.RULE_ID and g["rule"]["fold_majority"] == 2 and g["rule"]["folds"] == 4
    assert rec["verdict"] in ("pass", "fail", "indeterminate")
    c = g["candidates"]["BE15"]
    assert c["n_folds"] == 4 and set(c["clauses"]) == {"R1_cost", "R2_risk_cut", "R3_folds", "R4_control"}
    # no random control declared -> it can never read pass
    assert c["verdict"] != "pass"
    # the grade reads the same per-trade files the arms summary was built from
    assert c["book"]["n"] == rec["measurement"]["arms"]["BE15"]["n"]


def test_pooled_grade_over_two_dirs(e2e, tmp_path):
    arms = e2e / "arms"
    out = tmp_path / "pooled"
    rc = am.main(["grade", "--arms-dir", str(arms), "--arms-dir", str(arms), "--baseline", "A",
                  "--candidate", "BE15", "--n-floor", "10", "--folds", "4", "--fold-majority", "2", "--out", str(out)])
    assert rc == 0
    g = json.loads((out / "verdict.json").read_text())
    single = json.loads((e2e / "verdict.json").read_text())["measurement"]["grade"]
    assert g["baseline_book"]["n"] == 2 * single["baseline_book"]["n"]


def test_roster_legs_reparses_accounts_yaml():
    """The first test's leg set is read from config/accounts.yaml at run time, never quoted."""
    import yaml
    doc = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text())
    accs = doc.get("accounts", doc)
    expect = [s if isinstance(s, str) else s.get("name") for s in accs["bybit_2"].get("strategies") or []]
    assert am.roster_legs(["bybit_2"]) == expect and expect
    with pytest.raises(KeyError):
        am.roster_legs(["no_such_account"])


@pytest.mark.parametrize("n_better, expect", [(1, "pass"), (2, "fails_R4")])
def test_many_random_draws_need_95_percent_beaten(n_better, expect):
    """With N seeded random draws, C must beat >= 95% of them (20 draws: at most 1 may beat C)."""
    hold, be, rnd = _books()
    books = {"A": hold, "BE": be}
    for i in range(20):
        books[f"R{i}"] = [dict(t, net_r=t["net_r"] + 0.1) for t in be] if i < n_better else rnd
    g = am.grade_risk_adjusted(books, baseline="A", candidates=["BE"], controls={"BE": [f"R{i}" for i in range(20)]})
    assert g["candidates"]["BE"]["verdict" if expect == "pass" else "label"] == expect


def test_run_legs_end_to_end(e2e, tmp_path):
    """run-legs drives exit_lever_ablation per leg and grades the pooled book (one synthetic leg here)."""
    csv = e2e.parent / "c.csv"
    out = tmp_path / "rl"
    rc = am.main(["run-legs", "--leg", "xrp_pullback_2h", "--arm", "A=", "--arm", "BE15=--be-floor-r=1.5",
                  f"--leg-args=xrp_pullback_2h=--data-csv={csv}", "--baseline", "A", "--candidate", "BE15",
                  "--n-floor", "10", "--folds", "4", "--fold-majority", "2", "--out", str(out)])
    assert rc == 0
    rec = json.loads((out / "verdict.json").read_text())
    assert rec["decision_rule"]["id"] == am.RULE_ID and rec["read_state"] == "measured"
    assert rec["per_leg"]["xrp_pullback_2h"]["exit_code"] == 0
    assert rec["pooled"]["baseline_book"]["n"] == json.loads((e2e / "verdict.json").read_text())["n"]
