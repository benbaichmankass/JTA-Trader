#!/usr/bin/env python3
# wiring: research/queue/RQ-20260922-002.yaml, RQ-20260922-012.yaml, RQ-20260922-001.yaml (run.command) via research-script-run.yml
"""Fold-level reductions over the committed Stage-0 evidence records.

WHY THIS EXISTS
---------------
Three queued questions (RQ-20260922-001 / -002 / -012) were `blocked` for 29 days on one fact: the
statistic is a one-line reduction over data that is already committed under `comms/strategy_evidence/`,
but nothing computed it into a durable research result (checklist E5). This script is that reduction.
Each `--rule` implements the unit's own pre-registered statistic and decision rule VERBATIM; it adds
no threshold of its own.

  --rule 002  RULE-RQ0922-002-FOLD-ROBUSTNESS
              drop_max_fold = net_r_oos - max(fold.net_r), per leg that PASSES the roster-promotion bar
              (scripts/ci/check_roster_promotion_evidence.census, distinct legs, re-derived at run time).
              fold_concentrated = drop_max_fold <= 0. >=62.5% of the population -> pass (finding: RULE-D1's
              pooled sum does not discriminate; deliverable is an amendment PROPOSAL); <=2 of 8 equivalent
              share (<=25%) -> fail (RULE-D1 stands); between -> indeterminate. The unit registered the
              counts 5/8 and 2/8; they are carried as the SHARES 62.5% and 25.0% because the passing set moves.
  --rule 012  RULE-RQ0922-012-FOLD-RECENCY
              recency_negative = fold_detail[-1].net_r < 0 while net_r_oos > 0, over every record with
              coverage_state == measured and len(fold_detail) == folds. >=40% of the net_r_oos > 0 legs ->
              pass; <=15% -> fail; between -> indeterminate.
  --rule 001  RULE-RQ0922-001-JACKKNIFE-STAGE0
              jackknife_min = net_r_oos - max(per-trade net_r over the OOS folds), per alpaca_live leg, from
              the leg's committed `source_run` ledger. A trade is OOS when its entry_time falls inside a
              fold_detail [start, end]. Any leg with jackknife_min <= 0 -> pass (single_trade_dependent
              found); all > 0 -> fail (the passes stand).

Verdict vocabulary follows the other `scripts/research/` producers: `pass` means the unit's FINDING
condition held (it is a finding, not an endorsement); `read_state` is `measured` or `no_data`.
Tier-1 research tooling: reads committed files, writes `<out>/verdict.json` only. It changes no config and
amends no rule -- the amendment is the operator's call.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "comms" / "strategy_evidence"
sys.path.insert(0, str(REPO))

#: 002 -- shares of the passing population (the unit registered 5/8 and 2/8).
R002_YES, R002_NO = 5 / 8, 2 / 8
#: 012 -- shares of the net_r_oos > 0 population.
R012_YES, R012_NO = 0.40, 0.15

RULE_IDS = {"002": "RULE-RQ0922-002-FOLD-ROBUSTNESS", "012": "RULE-RQ0922-012-FOLD-RECENCY",
            "001": "RULE-RQ0922-001-JACKKNIFE-STAGE0"}


def _records(evidence_dir: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in sorted(evidence_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("strategy"):
            out[p.stem] = d
    return out


def _folds(rec: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    fd = rec.get("fold_detail")
    if str(rec.get("coverage_state") or "").lower() != "measured" or not isinstance(fd, list):
        return None
    if not fd or rec.get("folds") != len(fd) or rec.get("net_r_oos") is None:
        return None
    if any(not isinstance(f, dict) or f.get("net_r") is None for f in fd):
        return None
    return sorted(fd, key=lambda f: str(f.get("start")))


def _band(share: float, yes: float, no: float) -> str:
    return "pass" if share >= yes else ("fail" if share <= no else "indeterminate")


def rule_002(records: Dict[str, Dict[str, Any]], passing_legs: List[str]) -> Dict[str, Any]:
    per, skipped = {}, []
    for leg in passing_legs:
        fd = _folds(records[leg]) if leg in records else None
        if fd is None:
            skipped.append(leg)
            continue
        net = float(records[leg]["net_r_oos"])
        drop = round(net - max(float(f["net_r"]) for f in fd), 4)
        per[leg] = {"net_r_oos": net, "max_fold_net_r": max(float(f["net_r"]) for f in fd),
                    "drop_max_fold": drop, "fold_concentrated": drop <= 0}
    n = len(per)
    if not n:
        return {"verdict": "not_applicable", "read_state": "no_data", "n": 0, "skipped": skipped}
    k = sum(1 for v in per.values() if v["fold_concentrated"])
    share = k / n
    return {"verdict": _band(share, R002_YES, R002_NO), "read_state": "measured", "n": n,
            "measurement": {"fold_concentrated": k, "share": round(share, 4), "bars": {"yes": R002_YES, "no": R002_NO},
                            "per_leg": per, "skipped_no_fold_detail": skipped},
            "population": f"{n} distinct legs clearing the roster-promotion bar (census passes_bar, re-derived at run time)"}


def rule_012(records: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    per = {}
    for leg, rec in records.items():
        fd = _folds(rec)
        if fd is None:
            continue
        net = float(rec["net_r_oos"])
        last = float(fd[-1]["net_r"])
        per[leg] = {"net_r_oos": net, "last_fold_net_r": last,
                    "drop_oldest": round(net - float(fd[0]["net_r"]), 4),
                    "oldest_share": round(float(fd[0]["net_r"]) / net, 4) if net > 0 else None,
                    "recency_negative": net > 0 and last < 0}
    pos = {k: v for k, v in per.items() if v["net_r_oos"] > 0}
    if not pos:
        return {"verdict": "not_applicable", "read_state": "no_data", "n": 0}
    k = sum(1 for v in pos.values() if v["recency_negative"])
    share = k / len(pos)
    return {"verdict": _band(share, R012_YES, R012_NO), "read_state": "measured", "n": len(pos),
            "measurement": {"recency_negative": k, "share": round(share, 4), "bars": {"yes": R012_YES, "no": R012_NO},
                            "legs_with_fold_detail": len(per), "per_leg": per,
                            "would_stop_passing": sorted(l for l, v in pos.items() if v["recency_negative"])},
            "population": f"{len(pos)} legs with net_r_oos > 0 among {len(per)} measured records carrying a complete fold_detail"}


def _oos_trades(rec: Dict[str, Any], repo: Path) -> Optional[List[float]]:
    src = rec.get("source_run")
    fd = _folds(rec)
    if not src or fd is None or not (repo / src).is_file():
        return None
    spans = [(str(f["start"]), str(f["end"])) for f in fd]
    out: List[float] = []
    for line in (repo / src).read_text().splitlines():
        try:
            t = json.loads(line)
        except ValueError:
            continue
        et = str(t.get("entry_time") or "")
        if t.get("net_r") is not None and any(a <= et <= b for a, b in spans):
            out.append(float(t["net_r"]))
    return out


def rule_001(records: Dict[str, Dict[str, Any]], legs: List[str], repo: Path = REPO) -> Dict[str, Any]:
    per, skipped = {}, {}
    for leg in legs:
        rec = records.get(leg)
        tr = _oos_trades(rec, repo) if rec else None
        if not tr:
            skipped[leg] = "no record, no committed source_run ledger, or no OOS trades"
            continue
        net = float(rec["net_r_oos"])
        jk = round(net - max(tr), 4)
        per[leg] = {"net_r_oos": net, "n_oos_trades_in_ledger": len(tr), "n_trades_oos_record": rec.get("n_trades_oos"),
                    "max_trade_net_r": round(max(tr), 4), "jackknife_min": jk, "single_trade_dependent": jk <= 0}
    if not per:
        return {"verdict": "not_applicable", "read_state": "no_data", "n": 0, "skipped": skipped}
    dep = [l for l, v in per.items() if v["single_trade_dependent"]]
    return {"verdict": "pass" if dep else "fail", "read_state": "measured", "n": len(per),
            "measurement": {"single_trade_dependent_legs": dep, "per_leg": per, "skipped": skipped},
            "population": f"{len(per)} alpaca_live legs with a committed per-trade ledger"}


def grade(rule: str, evidence_dir: Path = EVIDENCE, repo: Path = REPO) -> Dict[str, Any]:
    records = _records(evidence_dir)
    base = {"rule_id": RULE_IDS[rule], "decision_rule": {"id": RULE_IDS[rule]}, "tool": "scripts/research/evidence_fold_robustness.py"}
    if rule == "012":
        return dict(base, **rule_012(records))
    import yaml
    from scripts.ci import check_roster_promotion_evidence as cr
    accounts_text = (repo / "config" / "accounts.yaml").read_text()
    strategies = (yaml.safe_load((repo / "config" / "strategies.yaml").read_text()) or {}).get("strategies") or {}
    cen = cr.census(accounts_text, strategies, evidence_dir)
    if rule == "002":
        legs = sorted({s["leg"] for s in cen["slots"] if s["passes_bar"]})
        return dict(base, **rule_002(records, legs))
    legs = sorted({s["leg"] for s in cen["slots"] if s["account"] == "alpaca_live"})
    return dict(base, **rule_001(records, legs, repo))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rule", required=True, choices=sorted(RULE_IDS))
    ap.add_argument("--evidence-dir", default=str(EVIDENCE))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    v = grade(a.rule, Path(a.evidence_dir))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=1, default=float) + "\n")
    print(json.dumps({k: v.get(k) for k in ("rule_id", "verdict", "read_state", "n", "population")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
