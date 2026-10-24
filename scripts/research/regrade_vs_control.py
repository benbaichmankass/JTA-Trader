#!/usr/bin/env python3
# wiring: manual-only - one-off evidence re-grade (REPLACE-GRADE-CONTROL-REGRADE); re-run by hand, see docs/research/replace-grade-control-regrade-2026-10-24.md
"""Re-grade committed exit-lever ``replace`` results with the control clause enforced (REPLACE-GRADE-CONTROL-REGRADE).

Reads each unit's committed result artifact (``measurement.arms`` carries n / net_r / max_drawdown_r / per-fold net R,
so no backtest is re-run), rebuilds the grade parameters from the unit's own ``run.command``, and calls
``exit_lever_ablation.grade_replace`` twice: without controls (must reproduce the stored verdict, else the row is
reported as NOT REPRODUCED) and with ``vs_controls`` (what ``--vs-control`` does on the CLI).
Tier 1: reads research/ only, writes the JSON path given by --out.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import exit_lever_ablation as ela

# unit -> {candidate-arm-or-"*": [control arms]}; "*" = every non-baseline, non-control arm. Read from each unit's
# registered decision_rule text (the sentence naming the unconditional control), not from the harness.
CONTROLS: dict[str, dict[str, list[str]]] = {
    "RQ-20261022-b7e1-04": {"*": ["UT15"]}, "RQ-20261022-b7e1-05": {"*": ["UT15"]},
    "RQ-20261022-b7e1-06": {"*": ["UT15"]}, "RQ-20261022-b7e1-07": {"*": ["UT15"]},
    "RQ-20261022-b7e1-10": {"*": ["UT20"]},
    "RQ-20261022-b7e1-08": {"*": ["UB25", "UB33", "UB50"]},   # rule text: net_r(C) > net_r(UB25/UB33/UB50)
    "RQ-20261022-eba2-07": {"MB": ["UB"], "MT": ["UT"]}, "RQ-20261022-eba2-08": {"MB": ["UB"], "MT": ["UT"]},
    "RQ-20261023-1d5c-01": {"*": ["UT"]}, "RQ-20261023-1d5c-02": {"*": ["UT"]},
    "RQ-20261023-1d5c-03": {"*": ["UT"]}, "RQ-20261023-1d5c-04": {"*": ["UT"]},
}
# b7e1-08 sensitivity: matched pairs (BG25->UB25, ...) instead of all three
B7E1_08_MATCHED = {"BG25": ["UB25"], "BG33": ["UB33"], "BG50": ["UB50"]}


def _flag(cmd: list[str], name: str, cast=str, default=None):
    return cast(cmd[cmd.index(name) + 1]) if name in cmd else default


def regrade(unit_id: str, controls: dict[str, list[str]]) -> dict:
    with open(REPO / "research/queue" / f"{unit_id}.yaml", encoding="utf-8") as fh:
        u = yaml.safe_load(fh)
    cmd = [str(c) for c in u["run"]["command"]]
    files = glob.glob(str(REPO / "research/results" / unit_id / "*.jsonl"))
    if len(files) != 1:  # pinned: a unit with several landed rows must be graded by naming the row, not by picking one
        raise SystemExit(f"{unit_id}: expected exactly 1 landed result, found {len(files)}")
    print(f"[{unit_id}] artifact {Path(files[0]).relative_to(REPO)}")
    with open(files[0], encoding="utf-8") as fh:
        rec = json.loads(fh.readline())
    m = rec["measurement"]
    arms, old = m["arms"], m["grade"]
    baseline = _flag(cmd, "--baseline")
    labels = [cmd[i + 1].split("=")[0] for i, c in enumerate(cmd) if c == "--arm"]
    folds = _flag(cmd, "--folds", int, 6)
    ela.N_FOLDS = folds
    kw = {"baseline": baseline, "fold_majority": _flag(cmd, "--fold-majority", int, 5), "n_floor": _flag(cmd, "--n-floor", int, 39),
          "dd_tol_frac": _flag(cmd, "--dd-tol-frac", float, 0.35), "control": old.get("control"),
          "delta_r_per_trade": _flag(cmd, "--delta-r-per-trade", float, 0.0)}
    ctl_all = {c for cs in controls.values() for c in cs}
    vs = {}
    for cand in [lab for lab in labels if lab != baseline and lab not in ctl_all]:
        vs[cand] = controls.get(cand) or controls.get("*", [])
    # (1) reproduction: the grader as it ran, every non-baseline arm a candidate
    repro = ela.grade_replace(arms, candidates=[x for x in labels if x != baseline], **kw)
    # (2) control clause enforced; control arms are never candidates
    new = ela.grade_replace(arms, candidates=[x for x in labels if x != baseline and x not in ctl_all], vs_controls=vs, **kw)
    # (3) as registered: net R only (no fold clause on the contrast) -- the rule text of these units states no fold clause
    net_only = {}
    for cand, ctls in vs.items():
        row = new["candidates"].get(cand)
        if row is None:
            continue
        cond = (row["delta_net_r"] > 0 and row["delta_net_r"] >= new["delta_r_bar"]
                and row["folds_ge_incumbent"] >= kw["fold_majority"]
                and row["max_drawdown_r"] <= row["max_drawdown_cap"])
        net_only[cand] = bool(cond and all(arms[cand]["net_r"] > arms[c]["net_r"] for c in ctls))
    return {"unit": unit_id, "leg": m.get("leg"), "baseline": baseline, "old_verdict": old["verdict"], "old_label": old.get("label"),
            "reproduced": repro["verdict"] == old["verdict"] and repro.get("label") == old.get("label"),
            "repro_verdict": repro["verdict"], "new_verdict": new["verdict"], "new_label": new.get("label"),
            "new_pass_net_only": sorted(c for c, v in net_only.items() if v),
            "old_pass_candidates": sorted(c for c, v in old.get("candidates", {}).items() if v.get("passes")),
            "new_pass_candidates": sorted(c for c, v in new.get("candidates", {}).items() if v.get("passes")),
            "candidates": {c: {"net_r": v["net_r"], "d_vs_A": v["delta_net_r"], "folds_ge_A": v["folds_ge_incumbent"],
                                "dd": v["max_drawdown_r"], "dd_cap": v["max_drawdown_cap"], "passes_old": old["candidates"].get(c, {}).get("passes"),
                                "passes_new": v["passes"], "vs_controls": v.get("vs_controls")} for c, v in new["candidates"].items()},
            "result_file": str(Path(files[0]).relative_to(REPO)), "n_A": arms[baseline]["n"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rows = [regrade(u, c) for u, c in CONTROLS.items()]
    sens = regrade("RQ-20261022-b7e1-08", B7E1_08_MATCHED)
    sens["unit"] += "#matched-pairs"
    rows.append(sens)
    Path(a.out).write_text(json.dumps(rows, indent=1, default=str) + "\n", encoding="utf-8")
    for r in rows:
        print(r["unit"], r["old_verdict"], "->", r["new_verdict"], "reproduced" if r["reproduced"] else "NOT-REPRODUCED",
              "old_pass", r["old_pass_candidates"], "new_pass", r["new_pass_candidates"], "net_only", r["new_pass_net_only"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
