"""scripts/research/evidence_fold_robustness.py: the three fold-level reductions behind
RQ-20260922-001 / -002 / -012, on planted records (a fold-concentrated leg, a recency-negative leg,
a single-trade-dependent leg, and a clean control for each)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.research import evidence_fold_robustness as m


def _rec(net, folds, **kw):
    fd = [{"fold": i + 1, "trades": 5, "net_r": v, "start": f"2026-0{i + 1}-01", "end": f"2026-0{i + 1}-28"}
          for i, v in enumerate(folds)]
    return dict({"strategy": "x", "coverage_state": "measured", "net_r_oos": net, "folds": len(fd),
                 "fold_detail": fd, "n_trades_oos": 5 * len(fd)}, **kw)


def test_002_concentrated_vs_spread():
    recs = {"conc": _rec(5.0, [6.0, -0.5, -0.5]), "spread": _rec(3.0, [1.0, 1.0, 1.0])}
    v = m.rule_002(recs, ["conc", "spread"])
    assert v["measurement"]["per_leg"]["conc"]["fold_concentrated"] is True
    assert v["measurement"]["per_leg"]["spread"]["fold_concentrated"] is False
    assert v["measurement"]["fold_concentrated"] == 1 and v["verdict"] == "indeterminate"  # 50%: between 25% and 62.5%


def test_002_bands():
    conc = {f"c{i}": _rec(1.0, [2.0, -0.5, -0.5]) for i in range(5)}
    assert m.rule_002(conc, list(conc))["verdict"] == "pass"
    spread = {f"s{i}": _rec(3.0, [1.0, 1.0, 1.0]) for i in range(5)}
    assert m.rule_002(spread, list(spread))["verdict"] == "fail"


def test_002_skips_records_without_complete_fold_detail():
    bad = _rec(1.0, [1.0, 1.0])
    bad["folds"] = 3
    v = m.rule_002({"bad": bad}, ["bad", "absent"])
    assert v["read_state"] == "no_data" and v["skipped"] == ["bad", "absent"]


def test_012_recency():
    recs = {"decaying": _rec(4.0, [5.0, 1.0, -2.0]), "steady": _rec(3.0, [1.0, 1.0, 1.0]),
            "loser": _rec(-1.0, [1.0, 0.0, -2.0])}
    v = m.rule_012(recs)
    pl = v["measurement"]["per_leg"]
    assert pl["decaying"]["recency_negative"] and not pl["steady"]["recency_negative"]
    assert not pl["loser"]["recency_negative"]  # net_r_oos <= 0 is never recency_negative
    assert v["n"] == 2 and v["measurement"]["recency_negative"] == 1  # loser is outside the population
    assert pl["loser"]["oldest_share"] is None


def test_001_jackknife_from_committed_ledger(tmp_path: Path):
    ledger = tmp_path / "runs" / "leg__trades.jsonl"
    ledger.parent.mkdir(parents=True)
    rows = [{"entry_time": "2026-01-05", "net_r": 4.0}, {"entry_time": "2026-01-10", "net_r": -0.5},
            {"entry_time": "2026-01-20", "net_r": 0.5}, {"entry_time": "2025-06-01", "net_r": 99.0}]  # last is IS
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    rec = _rec(4.0, [4.0], source_run="runs/leg__trades.jsonl")
    v = m.rule_001({"leg": rec}, ["leg", "nolegrecord"], repo=tmp_path)
    leg = v["measurement"]["per_leg"]["leg"]
    assert leg["n_oos_trades_in_ledger"] == 3 and leg["max_trade_net_r"] == 4.0  # IS trade excluded
    assert leg["jackknife_min"] == 0.0 and leg["single_trade_dependent"] is True
    assert v["verdict"] == "pass" and "nolegrecord" in v["measurement"]["skipped"]


def test_real_corpus_reads(tmp_path: Path):
    """The committed corpus must produce a measured verdict for each rule (guards a schema drift)."""
    for rule in ("002", "012", "001"):
        v = m.grade(rule)
        assert v["read_state"] == "measured" and v["n"] > 0, rule
        assert v["decision_rule"]["id"] == m.RULE_IDS[rule]
