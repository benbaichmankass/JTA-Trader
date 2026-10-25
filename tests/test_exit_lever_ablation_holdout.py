"""exit_lever_ablation.py --grade holdout: select on the earliest span, test the selected arm ONCE
on the pre-registered latest span (operator decision 2026-10-16, "Require holdout").

Planted/clean pairs: a planted lookahead trade is refused before selection; an arm that only looks
good on the held-back span is never selected; the block the grade writes is the block
scripts/ops/mandate_resolver.py R-HOLDOUT accepts.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO)]
import exit_lever_ablation as e  # noqa: E402

LO = pd.Timestamp("2022-01-01", tz="UTC")
HI = pd.Timestamp("2026-01-01", tz="UTC")


def _t(day: str, net: float, exit_day: str | None = None) -> dict:
    return {"entry_time": f"{day} 00:00:00+00:00", "exit_time": f"{exit_day or day} 12:00:00+00:00",
            "net_r": net}


def _monthly(start: str, months: int, net: float) -> list[dict]:
    return [_t(str(d.date()), net) for d in pd.date_range(start, periods=months, freq="MS")]


# ── the boundary ─────────────────────────────────────────────────────────────
def test_boundary_is_the_latest_quarter_when_it_holds_the_floor():
    entries = [t["entry_time"] for t in _monthly("2022-01-01", 48, 1.0)] * 3   # 36 in the last year
    p = e.holdout_boundary(entries, LO, HI, frac=0.25, min_trades=25, max_frac=0.40)
    assert p["share"] == 0.25 and not p["grown"] and not p["short_at_cap"]
    assert p["boundary"] == HI - (HI - LO) * 0.25


def test_boundary_grows_to_the_floor_then_caps_and_says_so():
    thin = [t["entry_time"] for t in _monthly("2022-01-01", 48, 1.0)]         # 1 a month
    p = e.holdout_boundary(thin * 2, LO, HI, frac=0.25, min_trades=25, max_frac=0.40)
    assert 0.25 < p["share"] <= 0.40 and p["grown"] and not p["short_at_cap"]
    assert p["baseline_n_holdout"] >= 25
    p = e.holdout_boundary(thin, LO, HI, frac=0.25, min_trades=25, max_frac=0.40)
    assert p["share"] == 0.40 and p["short_at_cap"] and p["baseline_n_holdout"] < 25


def test_boundary_rejects_a_bad_share():
    with pytest.raises(ValueError):
        e.holdout_boundary([], LO, HI, frac=0.5, min_trades=25, max_frac=0.4)


# ── the lookahead guard ──────────────────────────────────────────────────────
def test_discovery_drops_held_back_and_straddling_trades():
    b = pd.Timestamp("2025-01-01", tz="UTC")
    tr = [_t("2024-06-01", 1.0), _t("2024-12-31", 1.0, exit_day="2025-01-02"), _t("2025-03-01", 9.0)]
    assert [x["entry_time"][:10] for x in e.discovery_trades(tr, b)] == ["2024-06-01"]


def test_planted_lookahead_trade_is_refused_before_selection():
    b = pd.Timestamp("2025-01-01", tz="UTC")
    edges = [LO + (b - LO) / 4 * i for i in range(4)] + [b]
    clean = {"B": _monthly("2022-01-01", 30, 1.0)}
    sel, _ = e.select_on_discovery(clean, order=["B"], baseline="B", boundary=b, edges=edges,
                                   n_floor=10, fold_majority=3)
    assert sel == "B"
    planted = {"B": clean["B"] + [_t("2025-06-01", 50.0)]}
    with pytest.raises(e.HoldoutLeak):
        e.select_on_discovery(planted, order=["B"], baseline="B", boundary=b, edges=edges,
                              n_floor=10, fold_majority=3)


def test_an_arm_that_shines_only_on_the_holdout_is_never_selected():
    b = pd.Timestamp("2025-01-01", tz="UTC")
    edges = [LO + (b - LO) / 4 * i for i in range(4)] + [b]
    full = {"B": _monthly("2022-01-01", 48, 0.5),
            "X": _monthly("2022-01-01", 36, -0.1) + _monthly("2025-01-01", 12, 20.0)}
    disc = {k: e.discovery_trades(v, b) for k, v in full.items()}
    sel, table = e.select_on_discovery(disc, order=["B", "X"], baseline="B", boundary=b, edges=edges,
                                       n_floor=10, fold_majority=3)
    assert sel == "B" and table["X"]["eligible"] is False


def test_a_tie_goes_to_the_baseline():
    b = pd.Timestamp("2025-01-01", tz="UTC")
    edges = [LO + (b - LO) / 4 * i for i in range(4)] + [b]
    same = _monthly("2022-01-01", 36, 1.0)
    sel, _ = e.select_on_discovery({"A": list(same), "B": list(same)}, order=["A", "B"], baseline="B",
                                   boundary=b, edges=edges, n_floor=10, fold_majority=3)
    assert sel == "B"


# ── grading ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sel,held,verdict,label", [
    ("B", {"n": 30, "net_r": 3.0}, "pass", "confirmed"),
    ("B", {"n": 30, "net_r": -0.1}, "fail", "not_replicated"),
    ("B", {"n": 30, "net_r": 0.0}, "fail", "not_replicated"),
    ("B", {"n": 24, "net_r": 9.0}, "indeterminate", "underpowered"),
    (None, None, "fail", "no_discovery"),
])
def test_grade_holdout(sel, held, verdict, label):
    g = e.grade_holdout(sel, held, min_trades=25, plan={}, table={"B": {"n": 40}, "C": {"n": 10}}, n_floor=25)
    assert (g["verdict"], g["label"]) == (verdict, label)
    assert g["selected_from"] == 2


# ── end to end on synthetic candles, and the contract with the resolver ─────
@pytest.fixture(scope="module")
def run(tmp_path_factory):
    import numpy as np
    d = tmp_path_factory.mktemp("holdout")
    rng = np.random.default_rng(7)
    ts = pd.date_range("2022-01-01", "2026-01-01", freq="2h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.01, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, len(ts))))
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo,
                  "close": c, "volume": 1000.0}).to_csv(d / "c.csv", index=False)
    out = d / "out"
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"),
                        "--leg", "xrp_pullback_2h", "--arm", "B=", "--arm", "S=atr_stop_mult=2.0",
                        "--data-csv", str(d / "c.csv"), "--grade", "holdout", "--baseline", "B",
                        "--delta-r", "0", "--fold-majority", "2", "--folds", "4", "--n-floor", "10",
                        "--research-unit", "RQ-TEST", "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True, check=False, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return json.loads((out / "verdict.json").read_text())


def test_end_to_end_writes_a_resolver_shaped_block(run):
    import mandate_resolver as mr
    hc = run["measurement"]["holdout_confirmation"]
    assert run["verdict"] in ("pass", "fail", "indeterminate")
    assert hc["verdict"] == run["measurement"]["label"]
    assert hc["verdict"] in (mr.HOLDOUT_PASS,) + mr.HOLDOUT_FAIL + mr.HOLDOUT_THIN
    assert hc["evaluations_on_holdout"] == (0 if hc["verdict"] == "no_discovery" else 1)
    assert mr._parse_ts(hc["discovery"]["end"]) < mr._parse_ts(hc["holdout"]["start"])
    assert hc["cost_stack"]["fees"] > 0 and hc["cost_stack"]["slippage"] > 0 and "funding" in hc["cost_stack"]
    assert hc["decision_rule"]["registered_before_run"] is True
    assert hc["source_run"] is None   # whoever writes the record points it at the committed verdict


def test_a_record_carrying_the_block_is_read_by_the_resolver(run, tmp_path):
    """Contract, not shape-matching: put the produced block on a record and let R-HOLDOUT read it."""
    import mandate_resolver as mr
    hc = dict(run["measurement"]["holdout_confirmation"])
    src = "comms/research/RQ-TEST/1/verdict.json"
    (tmp_path / src).parent.mkdir(parents=True)
    (tmp_path / src).write_text(json.dumps(run))
    hc["source_run"] = src
    rec = {"config_fingerprint": hc["selected_config_fingerprint"], mr.HOLDOUT_FIELD: hc}
    ctx = {"evidence": {}}
    bar = {"holdout_required": True, "holdout_min_n": 25}
    try:
        mr._holdout("xrp_pullback_2h", "S1", "S2", rec, bar, {"id": "MD-PROMOTE-S1-S2"}, tmp_path, ctx)
        outcome = "pass"
    except mr._Refuse as r:
        outcome = "refuse:" + r.clause
    except mr._NeedsData as nd:
        outcome = "needs:" + nd.detail
    thin = (hc["n_holdout"] or 0) < 25
    if hc["verdict"] == "no_discovery" or (hc["verdict"] == "not_replicated" and not thin):
        assert outcome == "refuse:R-HOLDOUT", outcome
    elif hc["verdict"] == "confirmed" and not thin:
        assert outcome == "pass", outcome
    else:
        assert outcome.startswith("needs:"), outcome


def test_thin_discovery_is_a_power_shortfall_not_a_fail():
    """Planted: no arm reaches the discovery floor -> indeterminate, never the decisive no_discovery."""
    g = e.grade_holdout(None, None, min_trades=25, plan={}, table={"B": {"n": 12}, "C": {"n": 9}}, n_floor=25)
    assert (g["verdict"], g["label"]) == ("indeterminate", "insufficient_discovery")
